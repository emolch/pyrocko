# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import logging
import re

from ..model import QuantityType, match_codes, CodesNSLCE
from .. import error

from pyrocko.guts import Object, String, Duration, Float, clone, List

guts_prefix = 'squirrel.ops'

logger = logging.getLogger('psq.ops')


def odiff(a, b):
    ia = ib = 0
    only_a = []
    only_b = []
    while ia < len(a) or ib < len(b):
        # TODO remove when finished with implementation
        if ia > 0:
            assert a[ia] > a[ia-1]
        if ib > 0:
            assert b[ib] > b[ib-1]

        if ib == len(b) or (ia < len(a) and a[ia] < b[ib]):
            only_a.append(a[ia])
            ia += 1
        elif ia == len(a) or (ib < len(b) and a[ia] > b[ib]):
            only_b.append(b[ib])
            ib += 1
        elif a[ia] == b[ib]:
            ia += 1
            ib += 1

    return only_a, only_b


def _cglob_translate(creg):
    dd = []
    for c in creg:
        if c == '*':
            d = r'[^.]*'
        elif c == '?':
            d = r'[^.]'
        elif c == '.':
            d = r'\.'
        else:
            d = c

        dd.append(d)
    reg = ''.join(dd)
    return reg


class Filtering(Object):
    '''
    Base class for :py:class:`pyrocko.squirrel.model.Nut` filters.
    '''

    def filter(self, it):
        return list(it)


class RegexFiltering(Object):
    '''
    Filter by regex.
    '''
    pattern = String.T(default=r'(.*)')

    def __init__(self, **kwargs):
        Filtering.__init__(self, **kwargs)
        self._compiled_pattern = re.compile(self.pattern)

    def filter(self, it):
        return [
            x for x in it if self._compiled_pattern.fullmatch(x)]


class CodesPatternFiltering(Object):
    '''
    Filter by codes pattern.
    '''
    codes = List.T(CodesNSLCE.T(), optional=True)

    def filter(self, it):
        if self.codes is None:
            return list(it)
        else:
            return [
                x for x in it
                if any(match_codes(sc, x) for sc in self.codes)]


class Grouping(Object):
    '''
    Base class for :py:class:`pyrocko.squirrel.model.Nut` grouping mechanisms.
    '''

    def key(self, codes):
        return codes


class RegexGrouping(Grouping):
    '''
    Group by regex pattern.
    '''
    pattern = String.T(default=r'(.*)')

    def __init__(self, **kwargs):
        Grouping.__init__(self, **kwargs)
        self._compiled_pattern = re.compile(self.pattern)

    def key(self, codes):
        return self._compiled_pattern.fullmatch(codes.safe_str).groups()


class NetworkGrouping(RegexGrouping):
    '''
    Group by *network* code.
    '''
    pattern = String.T(default=_cglob_translate('(*).*.*.*.*'))


class StationGrouping(RegexGrouping):
    '''
    Group by *network.station* codes.
    '''
    pattern = String.T(default=_cglob_translate('(*.*).*.*.*'))


class LocationGrouping(RegexGrouping):
    '''
    Group by *network.station.location* codes.
    '''
    pattern = String.T(default=_cglob_translate('(*.*.*).*.*'))


class ChannelGrouping(RegexGrouping):
    '''
    Group by *network.station.location.channel* codes.

    This effectively groups all processings of a channel, which may differ in
    the *extra* codes attribute.
    '''
    pattern = String.T(default=_cglob_translate('(*.*.*.*).*'))


class SensorGrouping(RegexGrouping):
    '''
    Group by *network.station.location.sensor* and *extra* codes.

    For *sensor* all but the last character of the channel code (indicating the
    component) are used. This effectively groups all components of a sensor,
    or processings of a sensor.
    '''
    pattern = String.T(default=_cglob_translate('(*.*.*.*)?(.*)'))


class Translation(Object):
    '''
    Base class for :py:class:`pyrocko.squirrel.model.Nut` translators.
    '''

    def translate(self, codes):
        return codes


class AddSuffixTranslation(Translation):
    '''
    Add a suffix to :py:attr:`~pyrocko.squirrel.model.CodesNSLCEBase.extra`.
    '''
    suffix = String.T(default='')

    def translate(self, codes):
        return codes.replace(extra=codes.extra + self.suffix)


class RegexTranslation(AddSuffixTranslation):
    '''
    Translate :py:class:`pyrocko.squirrel.model.Codes` using a regular
    expression.
    '''
    pattern = String.T(default=r'(.*)')
    replacement = String.T(default=r'\1')

    def __init__(self, **kwargs):
        AddSuffixTranslation.__init__(self, **kwargs)
        self._compiled_pattern = re.compile(self.pattern)

    def translate(self, codes):
        return codes.__class__(
            self._compiled_pattern.sub(self.replacement, codes.safe_str))


class ReplaceComponentTranslation(RegexTranslation):
    '''
    Translate :py:class:`pyrocko.squirrel.model.Codes` by replacing a
    component.
    '''
    pattern = String.T(default=_cglob_translate('(*.*.*.*)?(.*)'))
    replacement = String.T(default=r'\1{component}\2')


def deregister(registry, group):
    for codes in group[2]:
        del registry[codes]


def register(registry, operator, group):
    for codes in group[2]:
        if codes in registry:
            logger.warning(
                'duplicate operator output codes: %s' % codes)
        registry[codes] = (operator, group)


class Operator(Object):

    filtering = Filtering.T(default=Filtering.D())
    grouping = Grouping.T(default=Grouping.D())
    translation = Translation.T(default=Translation.D())

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self._output_names_cache = {}
        self._groups = {}
        self._available = []

    @property
    def name(self):
        return self.__class__.__name__

    def describe(self):
        return self.name

    def iter_mappings(self):
        for k, group in self._groups.items():
            yield (group[1], group[2])

    def iter_in_codes(self):
        for k, group in self._groups.items():
            yield group[1]

    def iter_out_codes(self):
        for k, group in self._groups.items():
            yield group[2]

    def update_mappings(self, available, registry=None):
        available = list(available)
        removed, added = odiff(self._available, available)

        filt = self.filtering.filter
        gkey = self.grouping.key
        groups = self._groups

        need_update = set()

        for codes in filt(removed):
            k = gkey(codes)
            groups[k][0].remove(codes)
            need_update.add(k)

        for codes in filt(added):
            k = gkey(codes)
            if k not in groups:
                groups[k] = [set(), None, ()]

            groups[k][0].add(codes)
            need_update.add(k)

        for k in need_update:
            group = groups[k]
            if registry is not None:
                deregister(registry, group)

            group[1] = tuple(sorted(group[0]))
            if not group[1]:
                del groups[k]
            else:
                group[2] = self._out_codes(group[1])
                if registry is not None:
                    register(registry, self, group)

        self._available = available

    def _out_codes(self, in_codes):
        return [self.translation.translate(codes) for codes in in_codes]

    def get_channels(self, squirrel, group, *args, **kwargs):
        _, in_codes, out_codes = group
        assert len(in_codes) == 1 and len(out_codes) == 1
        channels = squirrel.get_channels(codes=in_codes[0], **kwargs)
        channels_out = []
        for channel in channels:
            channel_out = clone(channel)
            channel_out.codes = out_codes[0]
            channels_out.append(channel_out)

        return channels_out

    def get_waveforms(self, squirrel, group, **kwargs):
        _, in_codes, out_codes = group
        assert len(in_codes) == 1 and len(out_codes) == 1

        trs = squirrel.get_waveforms(codes=in_codes[0], **kwargs)
        for tr in trs:
            tr.set_codes(*out_codes[0])

        return trs

    # def update_waveforms(self, squirrel, tmin, tmax, codes):
    #     if codes is None:
    #         for _, in_codes, out_codes in self._groups.values():
    #             for codes in


class Parameters(Object):
    pass


class RestitutionParameters(Parameters):
    frequency_min = Float.T()
    frequency_max = Float.T()
    frequency_taper_factor = Float.T(default=1.5)
    time_taper_factor = Float.T(default=2.0)


class Restitution(Operator):
    translation = AddSuffixTranslation(suffix='R{quantity}')
    quantity = QuantityType.T(default='displacement')

    @property
    def name(self):
        return 'Restitution(%s)' % self.quantity[0]

    def _out_codes(self, group):
        return [
            codes.__class__(self.translation.translate(codes).safe_str.format(
                quantity=self.quantity[0]))
            for codes in group]

    def get_tpad(self, params):
        return params.time_taper_factor / params.frequency_min

    def get_waveforms(
            self, squirrel, codes, params, tmin, tmax, **kwargs):

        self_, (_, in_codes, out_codes) = squirrel.get_operator_group(codes)
        assert self is self_
        assert len(in_codes) == 1 and len(out_codes) == 1

        tpad = self.get_tpad(params)

        tmin_raw = tmin - tpad
        tmax_raw = tmax + tpad

        trs = squirrel.get_waveforms(
            codes=in_codes[0], tmin=tmin_raw, tmax=tmax_raw, **kwargs)

        try:
            resp = squirrel.get_response(
                codes=in_codes[0],
                tmin=tmin_raw,
                tmax=tmax_raw).get_effective(self.quantity)

        except error.NotAvailable:
            return []

        freqlimits = (
            params.frequency_min / params.frequency_taper_factor,
            params.frequency_min,
            params.frequency_max,
            params.frequency_max * params.frequency_taper_factor)

        trs_rest = []
        for tr in trs:
            tr_rest = tr.transfer(
                tfade=tpad,
                freqlimits=freqlimits,
                transfer_function=resp,
                invert=True)

            tr_rest.set_codes(*out_codes[0])

            trs_rest.append(tr_rest)

        return trs_rest


class Shift(Operator):
    translation = AddSuffixTranslation(suffix='S')
    delay = Duration.T()


class Transform(Operator):
    grouping = Grouping.T(default=SensorGrouping.D())
    translation = ReplaceComponentTranslation(suffix='T{system}')

    def _out_codes(self, group):
        return [
            self.translation.translate(group[0]).format(
                component=c, system=self.components.lower())
            for c in self.components]


class ToENZ(Transform):
    components = 'ENZ'

    def get_waveforms(
            self, squirrel, in_codes, out_codes, params, tmin, tmax, **kwargs):

        trs = squirrel.get_waveforms(
            codes=in_codes, tmin=tmin, tmax=tmax, **kwargs)

        for tr in trs:
            print(tr)


class ToRTZ(Transform):
    components = 'RTZ'
    backazimuth = Float.T()


class ToLTQ(Transform):
    components = 'LTQ'


class Composition(Operator):
    g = Operator.T()
    f = Operator.T()

    def __init__(self, g, f, **kwargs):
        Operator.__init__(self, g=g, f=f, **kwargs)

    @property
    def name(self):
        return '(%s ○ %s)' % (self.g.name, self.f.name)


__all__ = [
    'Grouping',
    'RegexGrouping',
    'NetworkGrouping',
    'StationGrouping',
    'LocationGrouping',
    'SensorGrouping',
    'ChannelGrouping',
    'Operator',
    'RestitutionParameters',
    'Restitution',
    'Shift',
    'ToENZ',
    'ToRTZ',
    'ToLTQ',
    'Composition']
