# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Waveform data storage utilities.
'''

import math
import os
from collections import defaultdict

from pyrocko import guts, util, trace, io
from pyrocko.plot import nice_time_tick_inc_approx_secs

from . import error

guts_prefix = 'squirrel'

nsamples_block = 100000
nsamples_segment = 1024**2


def _translate_path_template(s):
    map_name = {
        'year': '%(wmin_year)s',
        'month': '%(wmin_month)s',
        'day': '%(wmin_day)s',
        'hour': '%(wmin_hour)s',
        'minute': '%(wmin_minute)s',
        'second': '%(wmin_second)s',
        'net': '%(network_dsafe)s',
        'sta': '%(station_dsafe)s',
        'loc': '%(location_dsafe)s',
        'cha': '%(channel_dsafe)s',
        'ext': '%(extra_dsafe)s'}

    return os.path.join(*[
        '.'.join(map_name[x] for x in entry.split('.'))
        for entry in s.split('/')])


def time_to_template_vars(prefix, t):
    d = dict(zip(
            [prefix + '_' + var
             for var in ['year', 'month', 'day', 'hour', 'minute', 'second']],
            util.time_to_str(t, '%Y.%m.%d.%H.%M.%S').split('.')))
    # needed for backwards compatibility
    d[prefix] = util.time_to_str(t, '%Y-%m-%d_%H-%M-%S')
    return d


def iter_windows(tmin, tmax, tinc, tinc_nonuniform):
    if tinc_nonuniform is None:
        tmin = math.floor(tmin / tinc) * tinc
        t = tmin
        while t < tmax:
            yield t, t + tinc
            t += tinc
    elif tinc_nonuniform == 'month':
        yield from util.iter_months(tmin, tmax)
    elif tinc_nonuniform == 'year':
        yield from util.iter_years(tmin, tmax)
    else:
        raise error.SquirrelError(
            'Available non-uniform time intervals: month, year. '
            'Invalid choice: %s' % tinc_nonuniform)


class StorageSchemeLayout(guts.Object):
    '''
    Specific directory layout within a storage scheme.
    '''
    name = guts.String.T(
        help='Name of the layout, informational.')
    time_increment = guts.Float.T(
        help='Time window length stored in each file[s]. Exact or '
             'approximate, depending on :py:gattr:`time_incement_nonuniform`.')
    time_increment_nonuniform = guts.String.T(
        optional=True,
        help='Identifier for non-uniform time windows. E.g. ``\'month\'`` or '
             '``\'year\'``.')
    path_template = guts.String.T(
        help='Template for file paths.')

    def get_additional(self, wmin, wmax):
        d = {}
        d.update(time_to_template_vars('wmin', wmin))
        d.update(time_to_template_vars('wmax', wmax))
        return d

    @classmethod
    def describe_header(self):
        return '%8s %11s %6s %10s %12s %10s %6s %4s %8s %6s' % (
            'rate',
            'deltat',
            'tblock',
            '',
            'tsegment',
            '',
            'layout',
            'fseg',
            'fsize',
            'levels')

    def describe(self, deltat):
        rate = 1.0 / deltat
        tblock = nice_time_tick_inc_approx_secs(deltat * nsamples_block)
        tsegment = deltat * nsamples_segment
        segments_per_file = self.time_increment / tsegment
        bytesize = self.time_increment / deltat * 4

        return '%8.1f %11.5f %6.0f %10s %12.0f %10s %6s %4.0f %8s %6i' % (
            rate,
            deltat,
            tblock,
            guts.str_duration(tblock),
            tsegment,
            guts.str_duration(tsegment),
            self.name,
            segments_per_file,
            util.human_bytesize(bytesize),
            len(self.path_template.split('/')))


class StorageScheme(guts.Object):
    '''
    Storage scheme for waveform archive data.
    '''
    name = guts.String.T(
        help='Storage scheme name.')
    layouts = guts.List.T(
        StorageSchemeLayout.T(),
        help='Directory layouts supported by the scheme.')
    min_segments_per_file = guts.Float.T(
        default=1.0,
        help='Target minimum number of segments to be stored in each file.')
    format = guts.String.T(
        default='mseed',
        help='File format of waveform data files.')
    description = guts.String.T(
        help='Description of the storage scheme.')

    def post_init(self):
        self._base_path = None

    def set_base_path(self, base_path):
        self._base_path = base_path

    def select_layout(self, deltat):
        tsegment = deltat * nsamples_segment
        twant = tsegment * self.min_segments_per_file
        for layout in self.layouts:
            if layout.time_increment > twant:
                return layout

        return layout

    def save(self, traces, **save_kwargs):

        assert save_kwargs.get('append', True)
        assert save_kwargs.get('check_append', True)

        save_kwargs['append'] = True
        save_kwargs['check_append'] = True
        additional_external = save_kwargs.pop('additional', {})

        by_deltat = defaultdict(list)
        for tr in traces:
            by_deltat[tr.deltat].append(tr)

        file_names = set()
        for deltat, traces_group in by_deltat.items():
            layout = self.select_layout(deltat)
            traces_group = trace.degapper(traces_group, maxgap=0)  # deoverlap
            tmin = min(tr.tmin for tr in traces_group)
            tmax = max(tr.tmax for tr in traces_group)
            for wmin, wmax in iter_windows(
                    tmin,
                    tmax,
                    layout.time_increment,
                    layout.time_increment_nonuniform):

                traces_window = []
                for tr in traces_group:
                    try:
                        traces_window.append(
                            tr.chop(wmin, wmax, inplace=False))
                    except trace.NoData:
                        pass

                additional = layout.get_additional(wmin, wmax)
                additional.update(additional_external)

                file_names.update(io.save(
                    traces_window,
                    layout.path_template
                    if self._base_path is None
                    else os.path.join(self._base_path, layout.path_template),
                    additional=additional,
                    **save_kwargs))

        return sorted(file_names)


_g_schemes_list = []
_g_schemes_list.append(StorageScheme(
    name='default',
    description='Dynamic storage scheme with balanced file sizes of '
                '10 - 400 MB and a balanced directory hierarchy of 4-6 levels',
    layouts=[
        StorageSchemeLayout(
            name=name,
            time_increment=time_increment,
            time_increment_nonuniform=time_increment_nonuniform,
            path_template=_translate_path_template(path_template))
        for (name, time_increment, time_increment_nonuniform, path_template)
        in [
            ('second', 1.0, None, 'net/sta/loc.cha/year/month/day/hour/net.sta.loc.cha.year.month.day.hour.minute.second'),  # noqa
            ('minute', 60.0,  None,'net/sta/loc.cha/year/month/day/net.sta.loc.cha.ext.year.month.day.hour.minute'),  # noqa
            ('hour', 3600.0,  None,'net/sta/loc.cha/year/month/net.sta.loc.cha.ext.year.month.day.hour'),  # noqa
            ('day', 86400.0,  None,'net/sta/loc.cha/year/net.sta.loc.cha.ext.year.month.day'),  # noqa
            ('month', 2628000.0, 'month','net/sta/loc.cha/year/net.sta.loc.cha.ext.year.month'),  # noqa
            ('year', 31536000.0, 'year', 'net/sta/loc.cha/net.sta.loc.cha.ext.year')]],  # noqa
    min_segments_per_file=1.5))


_g_schemes_list.append(StorageScheme(
    name='sds',
    description='Directory scheme conforming to SeisComP Data Structure (SDS) '
                'archive format (https://www.seiscomp.de/seiscomp3/doc'
                '/applications/slarchive/SDS.html). The scheme has a fixed '
                'layout with day files.',
    layouts=[
        StorageSchemeLayout(
            name='sds',
            time_increment=24*3600.,
            path_template=os.path.join(
                '%(wmin_year)s',
                '%(network_safe)s',
                '%(station_safe)s',
                '%(channel_safe)s.D',
                '%(network_safe)s.%(station)s.%(location)s.%(channel)s.D'
                '.%(wmin_year)s.%(wmin_jday)s'))]))

g_schemes = dict((scheme.name, scheme) for scheme in _g_schemes_list)


def get_storage_scheme(name):
    return g_schemes[name]


class StorageSchemeChoice(guts.StringChoice):
    '''
    Name of a supported storage scheme.
    '''
    choices = list(g_schemes.keys())


__all__ = [
    'get_storage_scheme',
    'StorageScheme',
    'StorageSchemeLayout',
    'StorageSchemeChoice']
