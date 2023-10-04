# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for `SUDS <https://seiscode.iris.washington.edu/projects/suds>`_
waveforms and station information.
'''

import sys
import struct
import logging
import numpy as num
from collections import namedtuple, defaultdict

from pyrocko import util, trace, model
from .io_common import FileLoadError


g_suds_zero = None


def get_suds_zero():
    global g_suds_zero
    if g_suds_zero is None:
        g_suds_zero = util.str_to_time('1970-01-01 00:00:00')

    return g_suds_zero


logger = logging.getLogger('pyrocko.io.suds')


class SudsError(Exception):
    pass


class SudsStructBase(object):

    @classmethod
    def unpack(cls, s):
        return cls._make(struct.unpack(cls.fmt, s))


class SudsStructtag(SudsStructBase, namedtuple(
        'SudsStructtag',
        'sync, machine, struct_type, struct_length, data_length')):

    __slots__ = ()
    fmt = '<cchll'


class SudsStatident(SudsStructBase, namedtuple(
        'SudsStatident',
        'network, st_name, component, inst_type')):

    def nslc(self):
        return (
            str(self.network.rstrip(b'\0 ').decode('ascii')),
            str(self.st_name.rstrip(b'\0 ').decode('ascii')),
            '',
            str(self.component.rstrip(b'\0 ').decode('ascii')))

    __slots__ = ()
    fmt = '<4s5sch'


class SudsStationcomp(SudsStructBase, namedtuple(
        'SudsStationcomp',
        'sc_name, azim, incid, st_lat, st_long, elev, enclosure, annotation, '
        'recorder, rockclass, rocktype, sitecondition, sensor_type, '
        'data_type, data_units, polarity, st_status, max_gain, clip_value, '
        'con_mvolts, channel, atod_gain, effective, clock_correct, '
        'station_delay')):

    __slots__ = ()
    fmt = '<%ishhddfcccchccccccfffhhlff' % struct.calcsize(SudsStatident.fmt)

    @classmethod
    def unpack(cls, s):
        v = struct.unpack(cls.fmt, s)
        v = (SudsStatident.unpack(v[0]),) + v[1:]
        return cls._make(v)

    def to_station(self):
        net, sta, loc, cha = self.sc_name.nslc()
        station = model.Station(
            network=net,
            station=sta,
            location=loc,
            lat=self.st_lat,
            lon=self.st_long,
            elevation=self.elev)

        station.add_channel(
            model.Channel(
                name=cha,
                azimuth=self.azim,
                dip=self.incid - 90.))

        return station


class SudsDescriptrace(SudsStructBase, namedtuple(
        'SudsDescriptrace',
        'dt_name, begintime, localtime, datatype, descriptor, digi_by, '
        'processed, length, rate, mindata, maxdata, avenoise, numclip, '
        'time_correct, rate_correct')):

    __slots__ = ()
    fmt = '<%isdhcchhlffffldf' % struct.calcsize(SudsStatident.fmt)

    @classmethod
    def unpack(cls, s):
        v = struct.unpack(cls.fmt, s)
        v = (SudsStatident.unpack(v[0]),) + v[1:]
        return cls._make(v)

    def to_trace(self, data):
        tmin = self.begintime - get_suds_zero()
        deltat = 1.0 / self.rate

        if data is None:
            tmax = tmin + (self.length - 1) * deltat
            arr = None
        else:
            tmax = None
            if self.datatype == b'l':
                arr = num.frombuffer(data, dtype=num.int32)
            elif self.datatype == b'i':
                arr = num.frombuffer(data, dtype=num.int16)
            elif self.datatype == b'f':
                arr = num.frombuffer(data, dtype=num.float32)
            elif self.datatype == b'd':
                arr = num.frombuffer(data, dtype=num.float64)
            else:
                raise SudsError(
                    'data type "%s" not implemented yet' % self.datatype)

            if self.length != arr.size:
                raise SudsError('found and reported number of samples differ')

        return trace.Trace(
            self.dt_name.network.rstrip(b'\0 '),
            self.dt_name.st_name.rstrip(b'\0 '),
            '',
            self.dt_name.component.rstrip(b'\0 '),
            ydata=arr,
            deltat=deltat,
            tmin=tmin,
            tmax=tmax)


struct_names = {
    0: 'no_struct',
    1: 'statident',
    2: 'structtag',
    3: 'terminator',
    4: 'equipment',
    5: 'stationcomp',
    6: 'muxdata',
    7: 'descriptrace',
    8: 'loctrace',
    9: 'calibration',
    10: 'feature',
    11: 'residual',
    12: 'event',
    13: 'ev_descript',
    14: 'origin',
    15: 'error',
    16: 'focalmech',
    17: 'moment',
    18: 'velmodel',
    19: 'layers',
    20: 'comment',
    21: 'profile',
    22: 'shotgather',
    23: 'calib',
    24: 'complex',
    25: 'triggers',
    26: 'trigsetting',
    27: 'eventsetting',
    28: 'detector',
    29: 'atodinfo',
    30: 'timecorrection',
    31: 'instrument',
    32: 'chanset'}

max_struct_type = max(struct_names.keys())


struct_classes = {}
for struct_id, struct_name in struct_names.items():
    g = globals()
    if struct_id > 0:
        class_name = 'Suds' + struct_name.capitalize()
        if class_name in g:
            struct_classes[struct_id] = g[class_name]


def read_suds_struct(f, cls, end_ok=False):
    size = struct.calcsize(cls.fmt)
    s = f.read(size)
    if end_ok and len(s) == 0:
        return None

    if size != len(s):
        raise SudsError('premature end of file')
    o = cls.unpack(s)

    return o


def _iload(filename, load_data=True, want=('traces', 'stations')):
    try:
        f = open(filename, 'rb')
        while True:
            tag = read_suds_struct(f, SudsStructtag, end_ok=True)
            if tag is None:
                break

            if tag.struct_type in struct_classes:
                cls = struct_classes[tag.struct_type]
                if tag.struct_length != struct.calcsize(cls.fmt):
                    raise SudsError(
                        'expected and reported struct lengths differ')

                s = read_suds_struct(f, cls)
                if isinstance(s, SudsStationcomp) and 'stations' in want:
                    station = s.to_station()
                    yield station

                if tag.data_length > 0:
                    if isinstance(s, SudsDescriptrace) and 'traces' in want:
                        if load_data:
                            data = f.read(tag.data_length)
                            if tag.data_length != len(data):
                                raise SudsError('premature end of file')

                            tr = s.to_trace(data)
                        else:
                            f.seek(tag.data_length, 1)
                            tr = s.to_trace(None)

                        yield tr
                    else:
                        f.seek(tag.data_length, 1)

            else:
                logger.warning(
                    'skipping unsupported SUDS struct type %s (%s)' % (
                        tag.struct_type,
                        struct_names.get(tag.struct_type, '?')))

                f.seek(tag.struct_length, 1)

                if tag.data_length > 0:
                    f.seek(tag.data_length, 1)

    except (OSError, SudsError) as e:
        raise FileLoadError(e)

    finally:
        f.close()


def iload(filename, load_data=True):
    for tr in _iload(filename, load_data=load_data, want=('traces',)):
        yield tr


def load_stations(filename):
    stations = list(_iload(filename, load_data=False, want=('stations',)))

    gathered = defaultdict(list)
    for s in stations:
        nsl = s.nsl()
        gathered[nsl].append(s)

    stations_out = []
    for nsl, group in gathered.items():
        meta = [
            ('.'.join(s.nsl()) + '.' + s.get_channels()[0].name,
             s.lat, s.lon, s.elevation)
            for s in group]

        util.consistency_check(meta)

        channels = [s.get_channels()[0] for s in group]
        group[0].set_channels(channels)
        stations_out.append(group[0])

    return stations_out


def detect(first512):

    s = first512[:12]
    if len(s) != 12:
        return False

    tag = SudsStructtag.unpack(s)
    if tag.sync != b'S' \
            or tag.machine != b'6' \
            or tag.struct_type < 0 \
            or tag.struct_type > max_struct_type:

        return False

    return True


if __name__ == '__main__':
    util.setup_logging('pyrocko.suds')

    trs = list(iload(sys.argv[1], 'rb'))

    stations = load_stations(sys.argv[1])

    for station in stations:
        print(station)

    trace.snuffle(trs, stations=stations)
