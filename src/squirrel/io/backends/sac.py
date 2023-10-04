# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel IO adaptor to :py:mod:`pyrocko.io.sac`.
'''

from pyrocko.io.io_common import get_stats, touch  # noqa
from pyrocko import trace
from ... import model


km = 1000.


def provided_formats():
    return ['sac']


def detect(first512):
    from pyrocko.io import sac

    if sac.detect(first512):
        return 'sac'
    else:
        return None


def agg(*ds):
    out = {}
    for d in ds:
        out.update(d)

    return out


def nonetoempty(x):
    if x is None:
        return x
    else:
        return x.strip()


def iload(format, file_path, segment, content):
    assert format == 'sac'

    from pyrocko.io import sac

    load_data = 'waveform' in content

    s = sac.SacFile(file_path, load_data=load_data)

    codes = model.CodesNSLCE(
        nonetoempty(s.knetwk),
        nonetoempty(s.kstnm),
        nonetoempty(s.khole),
        nonetoempty(s.kcmpnm))

    tmin = s.get_ref_time() + s.b
    tmax = tmin + s.delta * s.npts

    tspan = dict(
        tmin=tmin,
        tmax=tmax,
        deltat=s.delta)

    inut = 0
    nut = model.make_waveform_nut(
        file_segment=0,
        file_element=inut,
        codes=codes,
        **tspan)

    if 'waveform' in content:
        nut.content = trace.Trace(
            ydata=s.data[0],
            **nut.waveform_kwargs)

    yield nut
    inut += 1

    if None not in (s.stla, s.stlo):
        position = dict(
            lat=s.stla,
            lon=s.stlo,
            elevation=s.stel,
            depth=s.stdp)

        nut = model.make_station_nut(
            file_segment=0,
            file_element=inut,
            codes=model.CodesNSL(*codes.nsl),
            **tspan)

        if 'station' in content:
            nut.content = model.Station(
                **agg(position, nut.station_kwargs))

        yield nut
        inut += 1

        dip = None
        if s.cmpinc is not None:
            dip = s.cmpinc - 90.

        nut = model.make_channel_nut(
            file_segment=0,
            file_element=inut,
            codes=codes,
            **tspan)

        if 'channel' in content:
            nut.content = model.Channel(
                azimuth=s.cmpaz,
                dip=dip,
                **agg(position, nut.channel_kwargs))

        yield nut
        inut += 1

    if None not in (s.evla, s.evlo, s.o):
        etime = s.get_ref_time() + s.o
        depth = None
        if s.evdp is not None:
            depth = s.evdp  # * km  #  unclear specs

        nut = model.make_event_nut(
            codes=model.CodesX(''),
            # name=nonetoempty(s.kevnm),
            file_segment=0,
            file_element=inut,
            tmin=etime,
            tmax=etime)

        if 'event' in content:
            nut.content = model.Event(
                lat=s.evla,
                lon=s.evlo,
                depth=depth,
                magnitude=s.mag,
                **nut.event_kwargs)

        yield nut
        inut += 1
