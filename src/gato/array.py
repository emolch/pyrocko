from collections import defaultdict

import numpy as num

from pyrocko import util
from pyrocko.guts import Object, String, List, Timestamp, Dict, Tuple, Float, \
    StringChoice
from pyrocko.model.location import Location
from pyrocko.squirrel import CodesNSLCE, FDSNSource, Dataset, CodesNSL, \
    Sensor, CodesMatcher, codes_patterns_for_kind, CHANNEL

from pyrocko.has_paths import HasPaths, Path
from .grid.location import UnstructuredLocationGrid, distances_3d

guts_prefix = 'gato'
km = 1000.


def time_or_none_to_str(t):
    return util.time_to_str(t, '%Y-%m-%d') if t else '...'


class CodesTimeQueryArgs(Object):
    codes = List.T(CodesNSLCE.T())
    time = Timestamp.T(optional=True)
    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)


class SensorArrayInfo(Object):
    codes = List.T(CodesNSLCE.T())
    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)
    center = Location.T(optional=True)
    distances_stats = Tuple.T(5, Float.T(), optional=True)
    codes_nsl__ = List.T(CodesNSL.T())
    codes_nsl_by_channels = Dict.T(Tuple.T(String.T()), List.T(CodesNSL.T()))
    sensors = List.T(Sensor.T())
    request_query_args = CodesTimeQueryArgs.T()

    @property
    def n_codes_nsl(self):
        return len(self.codes_nsl)

    @property
    def n_codes(self):
        return len(self.codes)

    @property
    def str_codes_nsl_by_channels(self):
        return ', '.join(
            '%s: %i' % (','.join(k), len(v))
            for (k, v) in self.codes_nsl_by_channels.items())

    @property
    def str_distances_stats(self):
        return ', '.join('%5.1f' % (v/km) for v in self.distances_stats) \
            if self.distances_stats else ''

    @property
    def str_tmin(self):
        return time_or_none_to_str(self.tmin)

    @property
    def str_tmax(self):
        return time_or_none_to_str(self.tmax)

    @property
    def summary(self):
        return ' | '.join((
            '%3i' % self.n_codes_nsl,
            '%3i' % self.n_codes,
            time_or_none_to_str(self.tmin).ljust(10),
            time_or_none_to_str(self.tmax).ljust(10),
            '%-33s' % self.str_distances_stats,
            self.str_codes_nsl_by_channels))

    @property
    def codes_nsl(self):
        return sorted(set(CodesNSL(c) for c in self.codes))

    @codes_nsl.setter
    def codes_nsl(self, _):
        pass


class SensorArrayType(StringChoice):
    choices = [
        'seismic',
        'infrasound',
        'hydrophone',
    ]


class SensorArray(Object):
    name = String.T()
    codes = List.T(CodesNSLCE.T())
    type = SensorArrayType.T(optional=True)
    comment = String.T(optional=True)

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self._defined_in = 'unknown'

    def set_defined_in(self, defined_in):
        self._defined_in = defined_in

    def get_defined_in(self):
        return self._defined_in

    @property
    def summary(self):
        return ' | '.join(('%-17s' % self.name, self.type[:1]))

    @property
    def summary2(self):
        return ' | '.join(
            ('%-17s' % self.name, self.type[:1], self.comment or ''))

    def get_info(self, sq, codes=None, time=None, tmin=None, tmax=None):

        # First, get all sensors matching the array definition in the given
        # time constraints, then remove channels which do not match the codes
        # constraints.

        sensors = sq.get_sensors(
                codes=self.codes, time=time, tmin=tmin, tmax=tmax)

        sensors.sort(key=lambda sensor: sensor.codes)

        if codes is not None:
            codes = codes_patterns_for_kind(CHANNEL, codes)
            matcher = CodesMatcher(codes)
            for sensor in sensors:
                sensor.channels = [
                    channel for channel in sensor.channels
                    if matcher.match(channel.codes)]

            sensors = [sensor for sensor in sensors if sensor.channels]

        request_query_args = CodesTimeQueryArgs(
            codes=codes, time=time, tmin=tmin, tmax=tmax)

        tmins = []
        tmaxs = []
        codes = set()
        nsl_by_chas = defaultdict(set)
        for sensor in sensors:
            for channel in sensor.channels:
                codes.add(channel.codes)

            sensor_chas = tuple(
                sorted(set(
                    channel.codes.channel
                    for channel in sensor.channels)))

            nsl_by_chas[sensor_chas].add(CodesNSL(sensor.codes))

            tmins.append(sensor.tmin)
            tmaxs.append(sensor.tmax)

        tmins = [tmin for tmin in tmins if tmin is not None]
        tmin = min(tmins) if tmins else None
        tmax = None if None in tmaxs or not tmaxs else max(tmaxs)

        if sensors:
            grid = UnstructuredLocationGrid.from_locations(
                sensors, ignore_position_duplicates=True)

            center = grid.get_center()
            distances = distances_3d(grid, grid).flatten()
            distances = distances[distances != 0.0]
            distances_stats = tuple(num.percentile(
                distances, [0., 10., 50., 90., 100.])) \
                if distances.size != 0 else None
        else:
            center = None
            distances_stats = None

        codes_nsl_by_channels = dict(
            (k, sorted(v)) for (k, v) in nsl_by_chas.items())

        return SensorArrayInfo(
            codes=sorted(codes),
            codes_nsl_by_channels=codes_nsl_by_channels,
            tmin=tmin,
            tmax=tmax,
            distances_stats=distances_stats,
            center=center,
            sensors=sensors,
            request_query_args=request_query_args)


class SensorArrayFromFDSN(SensorArray):
    sources = List.T(FDSNSource.T())


def to_codes(codes):
    return [CodesNSLCE(c) for c in codes]


def _make_fdsn_source(site, codes):
    return FDSNSource(site=site, codes=codes)


g_sensor_arrays = [
    SensorArrayFromFDSN(
        name=':' + name,
        type=typ,
        codes=to_codes(codes),
        comment=comment,
        sources=[_make_fdsn_source('iris', codes)])

    for (typ, name, codes, comment) in [
        ('hydrophone', 'dghan', ['IM.H08N?.*.?DH'], ''),
        ('hydrophone', 'dghas', ['IM.H08S?.*.?DH'], ''),
        ('infrasound', 'bermuda', ['IM.I51H?.*.?DF'], ''),
        ('infrasound', 'cocos', ['IM.I06H?.*.?DF'], ''),
        ('infrasound', 'dgha-land', ['IM.I52H?.*.?DF'], ''),
        ('infrasound', 'fairbanks', ['IM.I53H?.*.?DF'], ''),
        ('infrasound', 'hia', ['IM.I59H?.*.?DF'], ''),
        ('infrasound', 'narrogin', ['IM.I04H?.*.?DF'], ''),
        ('infrasound', 'nia', ['IM.I56H?.*.?DF'], ''),
        ('infrasound', 'pfia', ['IM.I57H?.*.?DF', 'IM.I57L?.*.?DF'], ''),
        ('infrasound', 'tdc', ['IM.H09N?.*.?DF', 'IM.I49H?.*.?DF'], ''),
        ('infrasound', 'warramunga', ['IM.I07H?.*.?DF'], ''),
        ('seismic', 'alice', ['AU.AS*.*.?H?'],
         'Alice Springs, Australia'),
        ('seismic', 'bca', ['IM.BC0?.*.?H?'],
         'Beaver Creek, Alaska, USA'),
        ('seismic', 'bma', ['IM.BM0?.*.?H?'],
         'Burnt Mountain, Alaska, USA'),
        ('seismic', 'esk', ['IM.EKB?.*.?H?', 'IM.EKR*.*.?H?'],
         'Eskdalemuir, Scotland'),
        ('seismic', 'ilar', ['IM.IL*.*.?H?'],
         'Eielson, Alaska, USA'),
        ('seismic', 'imar', ['IM.IM0?.*.?H?'],
         'Indian Mountain, Alaska, USA'),
        ('seismic', 'nvar', ['IM.NV*.*.?H?'],
         'Mina, Nevada, USA'),
        ('seismic', 'pdar', ['IM.PD0*.*.?H?', 'IM.PD1*.*.?H?'],
         'Wyoming, USA'),
        ('seismic', 'psar', ['AU.PSA*.*.?H?'],
         'Pilbara, northwestern Australia'),
        ('seismic', 'txar', ['IM.TX*.*.?H?'],
         'Lajitas, Texas, USA'),
        ('seismic', 'yka', ['CN.YKA*.*.?H?'],
         'Yellowknife, Northwest Territories, Canada,'),
        ('seismic', 'knet', ['KN.*.*.?H?'],
         'Kyrgyzstan'),
    ]
] + [
    SensorArrayFromFDSN(
        name=':' + name,
        type='seismic',
        codes=to_codes(codes),
        sources=[_make_fdsn_source('geofon', codes)],
        comment=comment)

    for (name, codes, comment) in [
        ('rohrbach', ['6A.V*.*.?H?'],
         'Rohrbach/Vogtland, German-Czech border region'),
        ('neumayer', ['AW.VNA??.*.?H?', 'AW.VNA2.*.?H?'],
         'Station Neumayer Watz, Antarctica'),
    ]
] + [
    SensorArrayFromFDSN(
        name=':' + name,
        type='seismic',
        codes=to_codes(codes),
        sources=[_make_fdsn_source('bgr', codes)],
        comment=comment)

    for (name, codes, comment) in [
        ('geres', [
            'GR.GEA?.*.?H?',
            'GR.GEB?.*.?H?',
            'GR.GEC?.*.?H?',
            'GR.GED?.*.?H?'],
         'GERESS, Germany'),
        ('grf', ['GR.GR??.*.?H?'], 'Gräfenberg, Germany')]
] + [
    SensorArrayFromFDSN(
        name=':' + name,
        type='seismic',
        codes=to_codes(codes),
        sources=[_make_fdsn_source('norsar', codes)],
        comment=comment)

    for (name, codes, comment) in [
        ('norsar', [
            'NO.NA*.*.*',
            'NO.NB*.*.*',
            'NO.NC*.*.*', ],
         'Central Norway'),
        ('arces', [
            'NO.ARA*.*.*',
            'NO.ARB*.*.*',
            'NO.ARC*.*.*',
            'NO.ARD*.*.*',
            'NO.ARE*.*.*'],
         'Northern Norway'),
        ('spits', [
            'NO.SPA*.*.*',
            'NO.SPB*.*.*'],
         'Spitsbergen, Norway'),
        ('bear', ['NO.BEA?.*.*'],
         'Bear Island, Norway'),
        ('hspa', ['NO.HSPA?.*.*'],
         'Hornsund, Spitsbergen, Norway'),
    ]
] + [
    SensorArrayFromFDSN(
        name=':' + name,
        type='seismic',
        codes=to_codes(codes),
        sources=[_make_fdsn_source('up', codes)],
        comment=comment)

    for (name, codes, comment) in [
        ('eger-s1', [
            '6A.LWS00.*.*',
            '6A.LWSA?.*.*',
            'SX.LWSB?.*.*',
            'SX.LWSC?.*.*'],
         'ICDP EGER S1, Landwuest, German-Czech border region'),
        ('eger-s1-borehole', [
            '6A.LWS00.*.*'],
         'Borehole array of ICDP EGER S1, Landwuest, German-Czech border region'),  # noqa
        ('eger-s1-surface', [
            '6A.LWSA?.*.*',
            'SX.LWSB?.*.*',
            'SX.LWSC?.*.*'],
         'Surface array of ICDP EGER S1, Landwuest, German-Czech border region'),  # noqa
    ]
]

for array in g_sensor_arrays:
    array.set_defined_in('builtin')

g_sensor_arrays_dict = dict(
    (array.name, array) for array in g_sensor_arrays)


class SensorArrayFromFile(SensorArray, HasPaths):
    name = String.T()
    stations_path = Path.T()


class SensorArrayAndInfoContext(Object):
    array = SensorArray.T()
    info = SensorArrayInfo.T()


def get_named_arrays_dataset(names=None):

    if isinstance(names, str):
        names = [names]

    sources = []
    for array in g_sensor_arrays:
        if names is None or array.name in names:
            sources.extend(array.sources)

    if names is None:
        comment = 'Aggregated dataset containing data sources for all ' \
            'built-in arrays of Gato.'
    else:
        if len(names) == 1:
            comment = 'Data source for Gato array: %s' % names[0]
        else:
            comment = 'Data sources for Gato array: %s' % ', ' .join(names)

    return Dataset(sources=sources, comment=comment)


def get_named_arrays():
    return g_sensor_arrays_dict


def get_named_array(name):
    return g_sensor_arrays_dict[name]


__all__ = [
    'SensorArrayInfo',
    'SensorArray',
    'SensorArrayFromFDSN',
    'SensorArrayAndInfoContext',
    'get_named_arrays_dataset',
    'get_named_arrays',
    'get_named_array',
]
