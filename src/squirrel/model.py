# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function

import hashlib
import numpy as num
from os import urandom
from base64 import urlsafe_b64encode

from pyrocko import util
from pyrocko.guts import Object, String, Timestamp, Float, Int, Unicode, \
    Tuple, List, StringChoice
from pyrocko.model import Content
from pyrocko.response import FrequencyResponse, MultiplyResponse, \
    IntegrationResponse, DifferentiationResponse, simplify_responses, \
    FrequencyResponseCheckpoint

from .error import ConversionError


guts_prefix = 'squirrel'

separator = '\t'

g_content_kinds = [
    'undefined',
    'waveform',
    'station',
    'channel',
    'response',
    'event',
    'waveform_promise']


g_content_kind_ids = (
    UNDEFINED, WAVEFORM, STATION, CHANNEL, RESPONSE, EVENT,
    WAVEFORM_PROMISE) = range(len(g_content_kinds))

g_tmin, g_tmax = util.get_working_system_time_range()[:2]


try:
    g_tmin_queries = max(g_tmin, util.str_to_time_fillup('1900-01-01'))
except Exception:
    g_tmin_queries = g_tmin


def to_kind(kind_id):
    return g_content_kinds[kind_id]


def to_kinds(kind_ids):
    return [g_content_kinds[kind_id] for kind_id in kind_ids]


def to_kind_id(kind):
    return g_content_kinds.index(kind)


def to_kind_ids(kinds):
    return [g_content_kinds.index(kind) for kind in kinds]


g_kind_mask_all = 0xff


def to_kind_mask(kinds):
    if kinds:
        return sum(1 << kind_id for kind_id in to_kind_ids(kinds))
    else:
        return g_kind_mask_all


def str_or_none(x):
    if x is None:
        return None
    else:
        return str(x)


def float_or_none(x):
    if x is None:
        return None
    else:
        return float(x)


def int_or_none(x):
    if x is None:
        return None
    else:
        return int(x)


def int_or_g_tmin(x):
    if x is None:
        return g_tmin
    else:
        return int(x)


def int_or_g_tmax(x):
    if x is None:
        return g_tmax
    else:
        return int(x)


def tmin_or_none(x):
    if x == g_tmin:
        return None
    else:
        return x


def tmax_or_none(x):
    if x == g_tmax:
        return None
    else:
        return x


def time_or_none_to_str(x):
    if x is None:
        return '...'.ljust(17)
    else:
        return util.time_to_str(x)


def codes_to_str_abbreviated(codes, indent='  '):
    codes = ['.'.join(x) for x in codes]

    if len(codes) > 20:
        scodes = '\n' + util.ewrap(codes[:10], indent=indent) \
            + '\n%s[%i more]\n' % (indent, len(codes) - 20) \
            + util.ewrap(codes[-10:], indent='  ')
    else:
        scodes = '\n' + util.ewrap(codes, indent=indent) \
            if codes else '<none>'

    return scodes


g_offset_time_unit_inv = 1000000000
g_offset_time_unit = 1.0 / g_offset_time_unit_inv


def tsplit(t):
    if t is None:
        return None, 0.0

    seconds = num.floor(t)
    offset = t - seconds
    return int(seconds), int(round(offset * g_offset_time_unit_inv))


def tjoin(seconds, offset, deltat):
    if seconds is None:
        return None

    if deltat is not None and deltat < 1e-3:
        return util.to_time_float(seconds) \
            + util.to_time_float(offset*g_offset_time_unit)
    else:
        return seconds + offset*g_offset_time_unit


tscale_min = 1
tscale_max = 365 * 24 * 3600  # last edge is one above
tscale_logbase = 20

tscale_edges = [tscale_min]
while True:
    tscale_edges.append(tscale_edges[-1]*tscale_logbase)
    if tscale_edges[-1] >= tscale_max:
        break


tscale_edges = num.array(tscale_edges)


def tscale_to_kscale(tscale):

    # 0 <= x < tscale_edges[1]: 0
    # tscale_edges[1] <= x < tscale_edges[2]: 1
    # ...
    # tscale_edges[len(tscale_edges)-1] <= x: len(tscale_edges)

    return int(num.searchsorted(tscale_edges, tscale))


class WaveformPromise(Content):
    '''
    Information about a waveform potentially available at a remote site.
    '''

    agency = String.T(default='', help='Agency code (2-5)')
    network = String.T(default='', help='Deployment/network code (1-8)')
    station = String.T(default='', help='Station code (1-5)')
    location = String.T(default='', help='Location code (0-2)')
    channel = String.T(default='', help='Channel code (3)')
    extra = String.T(default='', help='Extra/custom code')

    tmin = Timestamp.T()
    tmax = Timestamp.T()

    deltat = Float.T(optional=True)

    source_hash = String.T()

    @property
    def codes(self):
        return (
            self.agency, self.network, self.station, self.location,
            self.channel, self.extra)

    @property
    def time_span(self):
        return (self.tmin, self.tmax)


class InvalidWaveform(Exception):
    pass


class WaveformOrder(Object):
    source_id = String.T()
    codes = Tuple.T(None, String.T())
    deltat = Float.T()
    tmin = Timestamp.T()
    tmax = Timestamp.T()
    gaps = List.T(Tuple.T(2, Timestamp.T()))

    @property
    def client(self):
        return self.source_id.split(':')[1]

    def describe(self, site='?'):
        return '%s:%s %s [%s - %s]' % (
            self.client, site, '.'.join(self.codes),
            util.time_to_str(self.tmin), util.time_to_str(self.tmax))

    def validate(self, tr):
        if tr.ydata.size == 0:
            raise InvalidWaveform(
                'waveform with zero data samples')

        if tr.deltat != self.deltat:
            raise InvalidWaveform(
                'incorrect sampling interval - waveform: %g s, '
                'meta-data: %g s' % (
                    tr.deltat, self.deltat))

        if not num.all(num.isfinite(tr.ydata)):
            raise InvalidWaveform('waveform has NaN values')


def order_summary(orders):
    codes = sorted(set(order.codes[1:-1] for order in orders))
    if len(codes) >= 2:
        return '%i orders, %s - %s' % (
            len(orders),
            '.'.join(codes[0]),
            '.'.join(codes[-1]))

    else:
        return '%i orders, %s' % (
            len(orders),
            '.'.join(codes[0]))


class Station(Content):
    '''
    A seismic station.
    '''

    agency = String.T(default='', help='Agency code (2-5)')
    network = String.T(default='', help='Deployment/network code (1-8)')
    station = String.T(default='', help='Station code (1-5)')
    location = String.T(default='', optional=True, help='Location code (0-2)')

    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)

    lat = Float.T()
    lon = Float.T()
    elevation = Float.T(optional=True)
    depth = Float.T(optional=True)

    description = Unicode.T(optional=True)

    @property
    def codes(self):
        return (
            self.agency, self.network, self.station,
            self.location if self.location is not None else '*')

    @property
    def time_span(self):
        return (self.tmin, self.tmax)

    def get_pyrocko_station(self):
        from pyrocko import model
        return model.Station(
            network=self.network,
            station=self.station,
            location=self.location if self.location is not None else '*',
            lat=self.lat,
            lon=self.lon,
            elevation=self.elevation,
            depth=self.depth)

    def _get_pyrocko_station_args(self):
        return (
            '*',
            self.network,
            self.station,
            self.location if self.location is not None else '*',
            self.lat,
            self.lon,
            self.elevation,
            self.depth)


class Channel(Content):
    '''
    A channel of a seismic station.
    '''

    agency = String.T(default='', help='Agency code (2-5)')
    network = String.T(default='', help='Deployment/network code (1-8)')
    station = String.T(default='', help='Station code (1-5)')
    location = String.T(default='', help='Location code (0-2)')
    channel = String.T(default='', help='Channel code (3)')
    extra = String.T(default='', help='Extra/custom code')

    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)

    lat = Float.T()
    lon = Float.T()
    elevation = Float.T(optional=True)
    depth = Float.T(optional=True)

    dip = Float.T(optional=True)
    azimuth = Float.T(optional=True)
    deltat = Float.T(optional=True)

    @property
    def codes(self):
        return (
            self.agency, self.network, self.station, self.location,
            self.channel, self.extra)

    @property
    def time_span(self):
        return (self.tmin, self.tmax)

    def get_pyrocko_channel(self):
        from pyrocko import model
        return model.Channel(
            name=self.channel,
            azimuth=self.azimuth,
            dip=self.dip)

    def _get_pyrocko_station_args(self):
        return (
            self.channel,
            self.network,
            self.station,
            self.location,
            self.lat,
            self.lon,
            self.elevation,
            self.depth)

    def _get_pyrocko_channel_args(self):
        return (
            '*',
            self.channel,
            self.azimuth,
            self.dip)


observational_quantities = [
    'acceleration', 'velocity', 'displacement', 'pressure', 'rotation',
    'temperature']


technical_quantities = [
    'voltage', 'counts']


class QuantityType(StringChoice):
    choices = observational_quantities + technical_quantities


class ResponseStage(Object):
    input_quantity = QuantityType.T(optional=True)
    input_sample_rate = Float.T(optional=True)
    output_quantity = QuantityType.T(optional=True)
    output_sample_rate = Float.T(optional=True)
    elements = List.T(FrequencyResponse.T())
    log = List.T(Tuple.T(3, String.T()))

    @property
    def stage_type(self):
        if self.input_quantity in observational_quantities \
                and self.output_quantity in observational_quantities:
            return 'conversion'

        if self.input_quantity in observational_quantities \
                and self.output_quantity == 'voltage':
            return 'sensor'

        elif self.input_quantity == 'voltage' \
                and self.output_quantity == 'voltage':
            return 'electronics'

        elif self.input_quantity == 'voltage' \
                and self.output_quantity == 'counts':
            return 'digitizer'

        elif self.input_quantity == 'counts' \
                and self.output_quantity == 'counts' \
                and self.input_sample_rate != self.output_sample_rate:
            return 'decimation'

        elif self.input_quantity in observational_quantities \
                and self.output_quantity == 'counts':
            return 'combination'

        else:
            return 'unknown'

    @property
    def summary(self):
        irate = self.input_sample_rate
        orate = self.output_sample_rate
        factor = None
        if irate and orate:
            factor = irate / orate
        return 'ResponseStage, ' + (
            '%s%s => %s%s%s' % (
                self.input_quantity or '?',
                ' @ %g Hz' % irate if irate else '',
                self.output_quantity or '?',
                ' @ %g Hz' % orate if orate else '',
                ' :%g' % factor if factor else '')
        )

    def get_effective(self):
        return MultiplyResponse(responses=list(self.elements))


D = 'displacement'
V = 'velocity'
A = 'acceleration'

g_converters = {
    (V, D): IntegrationResponse(1),
    (A, D): IntegrationResponse(2),
    (D, V): DifferentiationResponse(1),
    (A, V): IntegrationResponse(1),
    (D, A): DifferentiationResponse(2),
    (V, A): DifferentiationResponse(1)}


def response_converters(input_quantity, output_quantity):
    if input_quantity is None or input_quantity == output_quantity:
        return []

    if output_quantity is None:
        raise ConversionError('Unspecified target quantity.')

    try:
        return [g_converters[input_quantity, output_quantity]]

    except KeyError:
        raise ConversionError('No rule to convert from "%s" to "%s".' % (
            input_quantity, output_quantity))


class Response(Content):
    '''
    The instrument response of a seismic station channel.
    '''

    agency = String.T(default='', help='Agency code (2-5)')
    network = String.T(default='', help='Deployment/network code (1-8)')
    station = String.T(default='', help='Station code (1-5)')
    location = String.T(default='', help='Location code (0-2)')
    channel = String.T(default='', help='Channel code (3)')
    extra = String.T(default='', help='Extra/custom code')

    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)

    stages = List.T(ResponseStage.T())
    checkpoints = List.T(FrequencyResponseCheckpoint.T())

    deltat = Float.T(optional=True)
    log = List.T(Tuple.T(3, String.T()))

    @property
    def codes(self):
        return (
            self.agency, self.network, self.station, self.location,
            self.channel, self.extra)

    @property
    def time_span(self):
        return (self.tmin, self.tmax)

    @property
    def nstages(self):
        return len(self.stages)

    @property
    def input_quantity(self):
        return self.stages[0].input_quantity if self.stages else None

    @property
    def output_quantity(self):
        return self.stages[-1].input_quantity if self.stages else None

    @property
    def output_sample_rate(self):
        return self.stages[-1].output_sample_rate if self.stages else None

    @property
    def stages_summary(self):
        def grouped(xs):
            xs = list(xs)
            g = []
            for i in range(len(xs)):
                g.append(xs[i])
                if i+1 < len(xs) and xs[i+1] != xs[i]:
                    yield g
                    g = []

            if g:
                yield g

        return '+'.join(
            '%s%s' % (g[0], '(%i)' % len(g) if len(g) > 1 else '')
            for g in grouped(stage.stage_type for stage in self.stages))

    @property
    def summary(self):
        orate = self.output_sample_rate
        return Content.summary.fget(self) + ', ' + ', '.join((
            '%s => %s' % (
                self.input_quantity or '?', self.output_quantity or '?')
            + (' @ %g Hz' % orate if orate else ''),
            self.stages_summary,
        ))

    def get_effective(self, input_quantity=None):
        elements = response_converters(input_quantity, self.input_quantity)

        elements.extend(
            stage.get_effective() for stage in self.stages)

        return MultiplyResponse(responses=simplify_responses(elements))


class Event(Content):
    '''
    A seismic event.
    '''

    name = String.T(optional=True)
    time = Timestamp.T()
    duration = Float.T(optional=True)

    lat = Float.T()
    lon = Float.T()
    depth = Float.T(optional=True)

    magnitude = Float.T(optional=True)

    def get_pyrocko_event(self):
        from pyrocko import model
        model.Event(
            name=self.name,
            time=self.time,
            lat=self.lat,
            lon=self.lon,
            depth=self.depth,
            magnitude=self.magnitude,
            duration=self.duration)

    @property
    def time_span(self):
        return (self.time, self.time)


def ehash(s):
    return hashlib.sha1(s.encode('utf8')).hexdigest()


def random_name(n=8):
    return urlsafe_b64encode(urandom(n)).rstrip(b'=').decode('ascii')


class Nut(Object):
    '''
    Index entry referencing an elementary piece of content.

    So-called *nuts* are used in Pyrocko's Squirrel framework to hold common
    meta-information about individual pieces of waveforms, stations, channels,
    etc. together with the information where it was found or generated.
    '''

    file_path = String.T(optional=True)
    file_format = String.T(optional=True)
    file_mtime = Timestamp.T(optional=True)
    file_size = Int.T(optional=True)

    file_segment = Int.T(optional=True)
    file_element = Int.T(optional=True)

    kind_id = Int.T()
    codes = String.T()

    tmin_seconds = Timestamp.T()
    tmin_offset = Int.T(default=0, optional=True)
    tmax_seconds = Timestamp.T()
    tmax_offset = Int.T(default=0, optional=True)

    deltat = Float.T(default=0.0)

    content = Content.T(optional=True)

    content_in_db = False

    def __init__(
            self,
            file_path=None,
            file_format=None,
            file_mtime=None,
            file_size=None,
            file_segment=None,
            file_element=None,
            kind_id=0,
            codes='',
            tmin_seconds=None,
            tmin_offset=0,
            tmax_seconds=None,
            tmax_offset=0,
            deltat=None,
            content=None,
            tmin=None,
            tmax=None,
            values_nocheck=None):

        if values_nocheck is not None:
            (self.file_path, self.file_format, self.file_mtime,
             self.file_size,
             self.file_segment, self.file_element,
             self.kind_id, self.codes,
             self.tmin_seconds, self.tmin_offset,
             self.tmax_seconds, self.tmax_offset,
             self.deltat) = values_nocheck

            self.content = None
        else:
            if tmin is not None:
                tmin_seconds, tmin_offset = tsplit(tmin)

            if tmax is not None:
                tmax_seconds, tmax_offset = tsplit(tmax)

            self.kind_id = int(kind_id)
            self.codes = str(codes)
            self.tmin_seconds = int_or_g_tmin(tmin_seconds)
            self.tmin_offset = int(tmin_offset)
            self.tmax_seconds = int_or_g_tmax(tmax_seconds)
            self.tmax_offset = int(tmax_offset)
            self.deltat = float_or_none(deltat)
            self.file_path = str_or_none(file_path)
            self.file_segment = int_or_none(file_segment)
            self.file_element = int_or_none(file_element)
            self.file_format = str_or_none(file_format)
            self.file_mtime = float_or_none(file_mtime)
            self.file_size = int_or_none(file_size)
            self.content = content

        Object.__init__(self, init_props=False)

    def __eq__(self, other):
        return (isinstance(other, Nut) and
                self.equality_values == other.equality_values)

    def hash(self):
        return ehash(','.join(str(x) for x in self.key))

    def __ne__(self, other):
        return not (self == other)

    def get_io_backend(self):
        from . import io
        return io.get_backend(self.file_format)

    def file_modified(self):
        return self.get_io_backend().get_stats(self.file_path) \
            != (self.file_mtime, self.file_size)

    @property
    def dkey(self):
        return (self.kind_id, self.tmin_seconds, self.tmin_offset, self.codes)

    @property
    def key(self):
        return (
            self.file_path,
            self.file_segment,
            self.file_element,
            self.file_mtime)

    @property
    def equality_values(self):
        return (
            self.file_segment, self.file_element,
            self.kind_id, self.codes,
            self.tmin_seconds, self.tmin_offset,
            self.tmax_seconds, self.tmax_offset, self.deltat)

    @property
    def tmin(self):
        return tjoin(self.tmin_seconds, self.tmin_offset, self.deltat)

    @property
    def tmax(self):
        return tjoin(self.tmax_seconds, self.tmax_offset, self.deltat)

    @property
    def kscale(self):
        if self.tmin_seconds is None or self.tmax_seconds is None:
            return 0
        return tscale_to_kscale(self.tmax_seconds - self.tmin_seconds)

    @property
    def waveform_kwargs(self):
        agency, network, station, location, channel, extra = \
            self.codes.split(separator)

        return dict(
            agency=agency,
            network=network,
            station=station,
            location=location,
            channel=channel,
            extra=extra,
            tmin=self.tmin,
            tmax=self.tmax,
            deltat=self.deltat)

    @property
    def waveform_promise_kwargs(self):
        agency, network, station, location, channel, extra = \
            self.codes.split(separator)

        return dict(
            agency=agency,
            network=network,
            station=station,
            location=location,
            channel=channel,
            extra=extra,
            tmin=self.tmin,
            tmax=self.tmax,
            deltat=self.deltat)

    @property
    def station_kwargs(self):
        agency, network, station, location = self.codes.split(separator)
        return dict(
            agency=agency,
            network=network,
            station=station,
            location=location if location != '*' else None,
            tmin=tmin_or_none(self.tmin),
            tmax=tmax_or_none(self.tmax))

    @property
    def channel_kwargs(self):
        agency, network, station, location, channel, extra \
            = self.codes.split(separator)

        return dict(
            agency=agency,
            network=network,
            station=station,
            location=location,
            channel=channel,
            extra=extra,
            tmin=tmin_or_none(self.tmin),
            tmax=tmax_or_none(self.tmax),
            deltat=self.deltat)

    @property
    def response_kwargs(self):
        agency, network, station, location, channel, extra \
            = self.codes.split(separator)

        return dict(
            agency=agency,
            network=network,
            station=station,
            location=location,
            channel=channel,
            extra=extra,
            tmin=tmin_or_none(self.tmin),
            tmax=tmax_or_none(self.tmax),
            deltat=self.deltat)

    @property
    def event_kwargs(self):
        return dict(
            name=self.codes,
            time=self.tmin,
            duration=(self.tmax - self.tmin) or None)

    @property
    def trace_kwargs(self):
        agency, network, station, location, channel, extra = \
            self.codes.split(separator)

        return dict(
            network=network,
            station=station,
            location=location,
            channel=channel,
            extra=extra,
            tmin=self.tmin,
            tmax=self.tmax-self.deltat,
            deltat=self.deltat)

    @property
    def dummy_trace(self):
        return DummyTrace(self)

    @property
    def codes_tuple(self):
        return tuple(self.codes.split(separator))

    @property
    def summary(self):
        if self.tmin == self.tmax:
            ts = util.time_to_str(self.tmin)
        else:
            ts = '%s - %s' % (
                util.time_to_str(self.tmin),
                util.time_to_str(self.tmax))

        return ' '.join((
            ('%s,' % to_kind(self.kind_id)).ljust(9),
            ('%s,' % '.'.join(self.codes.split(separator))).ljust(18),
            ts))


def make_waveform_nut(
        agency='', network='', station='', location='', channel='', extra='',
        **kwargs):

    codes = separator.join(
        (agency, network, station, location, channel, extra))

    return Nut(
        kind_id=WAVEFORM,
        codes=codes,
        **kwargs)


def make_waveform_promise_nut(
        agency='', network='', station='', location='', channel='', extra='',
        **kwargs):

    codes = separator.join(
        (agency, network, station, location, channel, extra))

    return Nut(
        kind_id=WAVEFORM_PROMISE,
        codes=codes,
        **kwargs)


def make_station_nut(
        agency='', network='', station='', location='', **kwargs):

    codes = separator.join((agency, network, station, location))

    return Nut(
        kind_id=STATION,
        codes=codes,
        **kwargs)


def make_channel_nut(
        agency='', network='', station='', location='', channel='', extra='',
        **kwargs):

    codes = separator.join(
        (agency, network, station, location, channel, extra))

    return Nut(
        kind_id=CHANNEL,
        codes=codes,
        **kwargs)


def make_response_nut(
        agency='', network='', station='', location='', channel='', extra='',
        **kwargs):

    codes = separator.join(
        (agency, network, station, location, channel, extra))

    return Nut(
        kind_id=RESPONSE,
        codes=codes,
        **kwargs)


def make_event_nut(name='', **kwargs):

    codes = name

    return Nut(
        kind_id=EVENT, codes=codes,
        **kwargs)


def group_channels(nuts):
    by_ansl = {}
    for nut in nuts:
        if nut.kind_id != CHANNEL:
            continue

        ansl = nut.codes[:4]

        if ansl not in by_ansl:
            by_ansl[ansl] = {}

        group = by_ansl[ansl]

        k = nut.codes[4][:-1], nut.deltat, nut.tmin, nut.tmax

        if k not in group:
            group[k] = set()

        group.add(nut.codes[4])

    return by_ansl


class DummyTrace(object):

    def __init__(self, nut):
        self.nut = nut
        self._codes = None

    @property
    def tmin(self):
        return self.nut.tmin

    @property
    def tmax(self):
        return self.nut.tmax

    @property
    def deltat(self):
        return self.nut.deltat

    @property
    def codes(self):
        if self._codes is None:
            self._codes = self.nut.codes_tuple

        return self._codes

    @property
    def nslc_id(self):
        return self.codes[1:5]

    @property
    def agency(self):
        return self.codes[0]

    @property
    def network(self):
        return self.codes[1]

    @property
    def station(self):
        return self.codes[2]

    @property
    def location(self):
        return self.codes[3]

    @property
    def channel(self):
        return self.codes[4]

    @property
    def extra(self):
        return self.codes[5]

    def overlaps(self, tmin, tmax):
        return not (tmax < self.nut.tmin or self.nut.tmax < tmin)


__all__ = [
    'separator',
    'to_kind',
    'to_kinds',
    'to_kind_id',
    'to_kind_ids',
    'Content',
    'WaveformPromise',
    'Station',
    'Channel',
    'Nut',
]
