# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel IO adaptor to read classic Pyrocko station and event files.
'''

import logging

from pyrocko.io.io_common import get_stats, touch  # noqa
from ... import model

logger = logging.getLogger('psq.io.textfiles')


def provided_formats():
    return ['pyrocko_stations', 'pyrocko_events']


def detect_pyrocko_stations(first512):
    try:
        first512 = first512.decode('utf-8')
    except UnicodeDecodeError:
        return False

    for line in first512.splitlines():
        t = line.split(None, 5)
        if len(t) in (5, 6):
            if len(t[0].split('.')) != 3:
                return False

            try:
                lat, lon, ele, dep = map(float, t[1:5])
                if lat < -90. or 90 < lat:
                    return False
                if lon < -180. or 180 < lon:
                    return False

                return True

            except Exception:
                return False

    return False


g_event_keys = set('''
name region catalog magnitude_type latitude longitude magnitude depth duration
north_shift east_shift mnn mee mdd mne mnd med strike1 dip1 rake1 strike2 dip2
rake2 duration time tags moment
'''.split())


def detect_pyrocko_events(first512):
    try:
        first512 = first512.decode('utf-8')
    except UnicodeDecodeError:
        return False

    lines = first512.splitlines()[:-1]
    ok = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith('#'):
            continue

        t = line.split(' = ', 1)
        if len(t) == 2:
            if t[0].strip() in g_event_keys:
                ok += 1
                continue
            else:
                return False

        if line.startswith('---'):
            ok += 1
            continue

        return False

    return ok > 2


def detect(first512):
    if detect_pyrocko_stations(first512):
        return 'pyrocko_stations'

    elif detect_pyrocko_events(first512):
        return 'pyrocko_events'

    return None


def float_or_none(s):
    if s.lower() == 'nan':
        return None
    else:
        return float(s)


def iload(format, file_path, segment, content):
    if format == 'pyrocko_stations':
        return iload_pyrocko_stations(file_path, segment, content)

    if format == 'pyrocko_events':
        return iload_pyrocko_events(file_path, segment, content)


def iload_pyrocko_stations(file_path, segment, content):

    inut = 0
    tmin = None
    tmax = None
    with open(file_path, 'r') as f:

        have_station = False
        for (iline, line) in enumerate(f):
            try:
                toks = line.split(None, 5)
                if len(toks) == 5 or len(toks) == 6:
                    net, sta, loc = toks[0].split('.')
                    lat, lon, elevation, depth = [float(x) for x in toks[1:5]]
                    if len(toks) == 5:
                        description = u''
                    else:
                        description = str(toks[5])

                    nut = model.make_station_nut(
                        file_segment=0,
                        file_element=inut,
                        codes=model.CodesNSL(net, sta, loc),
                        tmin=tmin,
                        tmax=tmax)

                    if 'station' in content:
                        nut.content = model.Station(
                            lat=lat,
                            lon=lon,
                            elevation=elevation,
                            depth=depth,
                            description=description,
                            **nut.station_kwargs)

                    yield nut
                    inut += 1

                    have_station = True

                elif len(toks) == 4 and have_station:
                    cha = toks[0]
                    azi = float_or_none(toks[1])
                    dip = float_or_none(toks[2])
                    gain = float(toks[3])

                    if gain != 1.0:
                        logger.warning(
                            '%s.%s.%s.%s gain value from stations '
                            'file ignored - please check' % (
                                        net, sta, loc, cha))

                    nut = model.make_channel_nut(
                        file_segment=0,
                        file_element=inut,
                        codes=model.CodesNSLCE(net, sta, loc, cha, ''),
                        tmin=tmin,
                        tmax=tmax)

                    if 'channel' in content:
                        nut.content = model.Channel(
                            lat=lat,
                            lon=lon,
                            elevation=elevation,
                            depth=depth,
                            azimuth=azi,
                            dip=dip,
                            **nut.channel_kwargs)

                    yield nut
                    inut += 1

                else:
                    raise Exception('invalid syntax')

            except Exception as e:
                logger.warning(
                    'skipping invalid station/channel definition: %s '
                    '(line: %i, file: %s' % (str(e), iline, file_path))


def iload_pyrocko_events(file_path, segment, content):
    from pyrocko import model as pmodel

    for iev, ev in enumerate(pmodel.Event.load_catalog(file_path)):
        nut = model.make_event_nut(
            file_segment=0,
            file_element=iev,
            codes=model.CodesX(ev.catalog or ''),
            tmin=ev.time,
            tmax=ev.time)

        if 'event' in content:
            nut.content = ev

        yield nut
