# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, division, print_function

import logging
import sys
import os
import os.path as op
import shutil
import random
from functools import wraps

import numpy as num

from pyrocko.guts import List
from pyrocko.plot import gmtpy
from pyrocko.gui.marker import PhaseMarker
from pyrocko import pile, util, model
from pyrocko.dataset import topo

from .error import ScenarioError, CannotCreatePath, LocationGenerationError
from .base import LocationGenerator
from .sources import SourceGenerator, DCSourceGenerator
from .targets import TargetGenerator, AVAILABLE_TARGETS

logger = logging.getLogger('pyrocko.scenario')
guts_prefix = 'pf.scenario'

km = 1000.


class ScenarioGenerator(LocationGenerator):
    '''
    Generator for synthetic seismo-geodetic scenarios.
    '''

    target_generators = List.T(
        TargetGenerator.T(),
        default=[],
        help='Targets to spawn in the scenario.')

    source_generator = SourceGenerator.T(
        default=DCSourceGenerator.D(),
        help='Sources to spawn in the scenario.')

    def __init__(self, **kwargs):
        LocationGenerator.__init__(self, **kwargs)
        for itry in range(self.ntries):

            try:
                self.get_stations()
                self.get_sources()
                return

            except LocationGenerationError:
                self.retry()

        raise ScenarioError(
            'Could not generate scenario within %i tries.' % self.ntries)

    def init_modelling(self, engine):
        self._engine = engine

    def get_engine(self):
        return self._engine

    def get_sources(self):
        return self.source_generator.get_sources()

    def get_events(self):
        return [s.pyrocko_event() for s in self.get_sources()]

    def collect(collector):
        if not callable(collector):
            raise AttributeError('This method should not be called directly.')

        @wraps(collector)
        def method(self, *args, **kwargs):
            result = []
            func = collector(self, *args, **kwargs)
            for gen in self.target_generators:
                result.extend(
                    func(gen) or [])
            return result

        return method

    @collect
    def get_stations(self):
        return lambda gen: gen.get_stations()

    @collect
    def get_targets(self):
        return lambda gen: gen.get_targets()

    @collect
    def get_waveforms(self, tmin=None, tmax=None):
        tmin, tmax = self._time_range_fill_defaults(tmin, tmax)
        return lambda gen: gen.get_waveforms(
            self._engine, self.get_sources(),
            tmin=tmin, tmax=tmax)

    @collect
    def get_onsets(self, tmin=None, tmax=None):
        tmin, tmax = self._time_range_fill_defaults(tmin, tmax)
        return lambda gen: gen.get_onsets(
            self._engine, self.get_sources(),
            tmin=tmin, tmax=tmax)

    @collect
    def get_insar_scenes(self, tmin=None, tmax=None):
        tmin, tmax = self._time_range_fill_defaults(tmin, tmax)
        return lambda gen: gen.get_insar_scenes(
            self._engine, self.get_sources(),
            tmin=tmin, tmax=tmax)

    @collect
    def get_gnss_campaigns(self, tmin=None, tmax=None):
        tmin, tmax = self._time_range_fill_defaults(tmin, tmax)
        return lambda gen: gen.get_gnss_campaigns(
            self._engine, self.get_sources(),
            tmin=tmin, tmax=tmax)

    def dump_data(self, path, overwrite=False):
        '''
        Invoke generators and dump the complete scenario.

        :param path: Output directory
        :type path: str
        :param overwrite: If ``True`` remove all previously generated files
            and recreating the scenario content. If ``False`` stop if
            previously generated content is found.
        :type overwrite: bool

        Wrapper to call :py:meth:`prepare_data` followed by
        :py:meth:`ensure_data` with default arguments.
        '''

        self.prepare_data(path, overwrite=False)
        self.ensure_data(path)

    def prepare_data(self, path, overwrite):
        '''
        Prepare directory for scenario content storage.

        :param path: Output directory
        :type path: str
        :param overwrite: If ``True``, remove all previously generated files
            and recreate the scenario content. If ``False``, stop if
            previously generated content is found.
        :type overwrite: bool
        '''

        for dentry in [
                'meta',
                'waveforms',
                'insar',
                'gnss']:

            dpath = op.join(path, dentry)
            if op.exists(dpath):
                if overwrite:
                    shutil.rmtree(dpath)
                else:
                    raise CannotCreatePath('Path exists: %s' % dpath)

        for fentry in [
                'events.txt',
                'sources.yml',
                'map.pdf',
                'README.md']:

            fpath = op.join(path, fentry)
            if op.exists(fpath):
                if overwrite:
                    os.unlink(fpath)
                else:
                    raise CannotCreatePath('Path exists: %s' % fpath)

    @collect
    def ensure_data(self, path, tmin=None, tmax=None):

        '''
        Generate and output scenario content to files, as needed.

        :param path: Output directory
        :type path: str
        :param tmin: Start of time interval to generate
        :type tmin: timestamp, optional
        :param tmax: End of time interval to generate
        :type tmax: timestamp, optional

        This method only generates the files which are relevant for the
        given time interval, and which have not yet been generated. It is safe
        to call this method several times, for different time windows, as
        needed.

        If no time interval is given, the origin times of the generated sources
        and signal propagation times are taken into account to estimate a
        reasonable default.
        '''

        tmin, tmax = self._time_range_fill_defaults(tmin, tmax)
        self.source_generator.ensure_data(path)

        meta_dir = op.join(path, 'meta')
        util.ensuredir(meta_dir)

        fn_stations = op.join(meta_dir, 'stations.txt')
        if not op.exists(fn_stations):
            model.station.dump_stations(
                self.get_stations(), fn_stations)

        fn_stations_yaml = op.join(meta_dir, 'stations.yml')
        if not op.exists(fn_stations_yaml):
            model.station.dump_stations_yaml(
                self.get_stations(), fn_stations_yaml)

        fn_stations_kml = op.join(meta_dir, 'stations.kml')
        if not op.exists(fn_stations_kml):
            model.station.dump_kml(
                self.get_stations(), fn_stations_kml)

        fn_markers = op.join(meta_dir, 'markers.txt')
        if not op.exists(fn_markers):
            markers = self.get_onsets()
            if markers:
                PhaseMarker.save_markers(markers, fn_markers)

        fn_readme = op.join(path, 'README.md')
        if not op.exists(fn_readme):
            dump_readme(fn_readme)

        def ensure_data(gen):
            logger.info('Creating files from %s...' % gen.__class__.__name__)
            return gen.ensure_data(
                self._engine, self.get_sources(), path, tmin=tmin, tmax=tmax)

        return ensure_data

    @collect
    def _get_time_ranges(self):
        return lambda gen: [gen.get_time_range(self.get_sources())]

    def get_time_range(self):
        ranges = num.array(
            self._get_time_ranges(), dtype=util.get_time_dtype())
        return ranges.min(), ranges.max()

    def _time_range_fill_defaults(self, tmin, tmax):
        stmin, stmax = self.get_time_range()
        return stmin if tmin is None else tmin, stmax if tmax is None else tmax

    def get_pile(self, tmin=None, tmax=None):
        p = pile.Pile()

        trf = pile.MemTracesFile(None, self.get_waveforms(tmin, tmax))
        p.add_file(trf)
        return p

    def make_map(self, filename):
        logger.info('Plotting scenario\'s map...')
        if not gmtpy.have_gmt():
            logger.warning('Cannot plot map, GMT is not installed.')
            return
        if self.radius is None or self.radius > 5000*km:
            logger.info(
                'Drawing map for scenarios with a radius > 5000 km is '
                'not implemented.')
            return

        try:
            draw_scenario_gmt(self, filename)
        except gmtpy.GMTError:
            logger.warning('GMT threw an error, could not plot map.')
        except topo.AuthenticationRequired:
            logger.warning('Cannot download topography data (authentication '
                           'required). Could not plot map.')

    def draw_map(self, fns):
        from pyrocko.plot import automap

        if isinstance(fns, str):
            fns = [fns]

        lat, lon = self.get_center_latlon()
        radius = self.get_radius()

        m = automap.Map(
            width=30.,
            height=30.,
            lat=lat,
            lon=lon,
            radius=radius,
            show_topo=True,
            show_grid=True,
            show_rivers=True,
            color_wet=(216, 242, 254),
            color_dry=(238, 236, 230)
            )

        self.source_generator.add_map_artists(m)

        sources = self.get_sources()
        for gen in self.target_generators:
            gen.add_map_artists(self.get_engine(), sources, m)

        # for patch in self.get_insar_patches():
        #     symbol_size = 50.
        #     coords = num.array(patch.get_corner_coordinates())
        #     m.gmt.psxy(in_rows=num.fliplr(coords),
        #                L=True,
        #                *m.jxyr)

        for fn in fns:
            m.save(fn)

    @property
    def stores_wanted(self):
        return set([gen.store_id for gen in self.target_generators
                    if hasattr(gen, 'store_id')])

    @property
    def stores_missing(self):
        return self.stores_wanted - set(self.get_engine().get_store_ids())

    def ensure_gfstores(self, interactive=False):
        if not self.stores_missing:
            return

        from pyrocko.gf import ws

        engine = self.get_engine()

        gf_store_superdirs = engine.store_superdirs

        if interactive:
            print('We could not find the following Green\'s function stores:\n'
                  '%s\n'
                  'We can try to download the stores from '
                  'http://kinherd.org into one of the following '
                  'directories:'
                  % '\n'.join('  ' + s for s in self.stores_missing))
            for idr, dr in enumerate(gf_store_superdirs):
                print(' %d. %s' % ((idr+1), dr))
            s = input('\nInto which directory should we download the GF '
                      'store(s)?\nDefault 1, (C)ancel: ')
            if s in ['c', 'C']:
                print('Canceled.')
                sys.exit(1)
            elif s == '':
                s = 0
            try:
                s = int(s)
                if s > len(gf_store_superdirs):
                    raise ValueError
            except ValueError:
                print('Invalid selection: %s' % s)
                sys.exit(1)
        else:
            s = 1

        download_dir = gf_store_superdirs[s-1]
        util.ensuredir(download_dir)
        logger.info('Downloading Green\'s functions stores to %s'
                    % download_dir)

        oldwd = os.getcwd()
        for store in self.stores_missing:
            os.chdir(download_dir)
            ws.download_gf_store(site='kinherd', store_id=store)

        os.chdir(oldwd)

    @classmethod
    def initialize(
            cls, path,
            center_lat=None, center_lon=None, radius=None,
            targets=AVAILABLE_TARGETS, stationxml=None, force=False):
        """Initialize a Scenario and create a ``scenario.yml``

        :param path: Path to create the scenerio in
        :type path: str
        :param center_lat: Center latitude [deg]
        :type center_lat: float, optional
        :param center_lon: Center longitude [deg]
        :type center_lon: float, optional
        :param radius: Scenario's radius in [m]
        :type radius: float, optional
        :param targets: Targets to throw into scenario,
            defaults to AVAILABLE_TARGETS
        :type targets: list of :class:`pyrocko.scenario.TargetGenerator`
            objects, optional
        :param force: If set to ``True``, overwrite directory
        :type force: bool
        :param stationxml: path to a StationXML to be used by the
            :class:`pyrocko.scenario.targets.WaveformGenerator`.
        :type stationxml: str
        :returns: Scenario
        :rtype: :class:`pyrocko.scenario.ScenarioGenerator`
        """
        import os.path as op

        if op.exists(path) and not force:
            raise CannotCreatePath('Directory %s alread exists.' % path)

        util.ensuredir(path)
        fn = op.join(path, 'scenario.yml')
        logger.debug('Writing new scenario to %s' % fn)

        scenario = cls(
            center_lat=center_lat,
            center_lon=center_lon,
            radius=radius)

        scenario.seed = random.randint(1, 2**32-1)

        scenario.target_generators.extend([t() for t in targets])

        scenario.update_hierarchy()

        scenario.dump(filename=fn)
        scenario.prepare_data(path, overwrite=force)

        return scenario


def draw_scenario_gmt(generator, fn):
    return generator.draw_map(fn)


def dump_readme(path):
    readme = '''# Pyrocko Earthquake Scenario

The directory structure of a scenario is layed out as follows:

## Map of the scenario
A simple map is generated from `pyrocko.automap` in map.pdf

## Earthquake Sources

Can be found as events.txt and sources.yml hosts the pyrocko.gf sources.

## Folder `meta`

Contains stations.txt and StationXML files for waveforms as well as KML data.
The responses are flat with gain of 1.0 at 1.0 Hz.

## Folder `waveforms`

Waveforms as mini-seed are stored here, segregated into days.

## Folder `gnss`

The GNSS campaign.yml is living here.
Use `pyrocko.guts.load(filename='campaign.yml)` to load the campaign.

## Folder `insar`

Kite InSAR scenes for ascending and descending tracks are stored there.
Use `kite.Scene.load(<filename>)` to inspect the scenes.

'''
    with open(path, 'w') as f:
        f.write(readme)

    return [path]
