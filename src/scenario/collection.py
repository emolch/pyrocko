# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Handle collections of scenarios.
'''


import os
import tarfile
import errno
import numpy as num
import time


from pyrocko.guts import Object, Timestamp
from pyrocko import gf, guts, util, pile
from pyrocko.plot import gmtpy

from .scenario import draw_scenario_gmt
from .error import ScenarioError

op = os.path
guts_prefix = 'pf.scenario'


def mtime(p):
    return os.stat(p).st_mtime


class ScenarioCollectionItem(Object):
    scenario_id = gf.StringID.T()
    time_created = Timestamp.T()

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self._path = None
        self._pile = None
        self._engine = None
        self._scenes = None

    def set_base_path(self, path):
        self._path = path

    def get_base_path(self):
        if self._path is None:
            raise EnvironmentError('Base path not set!')
        return self._path

    def init_modelling(self, engine):
        self._engine = engine

    def get_path(self, *entry):
        return op.join(*((self._path,) + entry))

    def get_generator(self):
        generator = guts.load(filename=self.get_path('generator.yaml'))
        generator.init_modelling(self._engine)
        return generator

    def get_time_range(self):
        return self.get_generator().get_time_range()

    def have_waveforms(self, tmin, tmax):
        p = self.get_waveform_pile()
        trs_have = p.all(
            tmin=tmin, tmax=tmax, load_data=False, degap=False)

        return any(tr.data_len() > 0 for tr in trs_have)

    def get_waveform_pile(self):
        self.ensure_data()

        if self._pile is None:
            path_waveforms = self.get_path('waveforms')
            util.ensuredir(path_waveforms)
            fns = util.select_files(
                [path_waveforms], show_progress=False)

            self._pile = pile.Pile()
            if fns:
                self._pile.load_files(
                    fns, fileformat='mseed', show_progress=False)

        return self._pile

    def get_insar_scenes(self):
        from kite import Scene
        if self._scenes is None:
            self._scenes = []
            path_insar = self.get_path('insar')
            util.ensuredir(path_insar)

            fns = util.select_files([path_insar], include='\\.(npz)$',
                                    show_progress=False)
            for f in fns:
                self._scenes.append(Scene.load(f))

        return self._scenes

    def get_gnss_campaigns(self):
        return self.get_generator().get_gnss_campaigns()

    def make_map(self, path_pdf):
        draw_scenario_gmt(self.get_generator(), path_pdf)

    def get_map(self, format='pdf'):
        path_pdf = self.get_path('map.pdf')

        if not op.exists(path_pdf):
            self.make_map(path_pdf)

        path = self.get_path('map.%s' % format)

        outdated = op.exists(path) and mtime(path) < mtime(path_pdf)
        if not op.exists(path) or outdated:
            gmtpy.convert_graph(path_pdf, path)

        return path

    def ensure_data(self, tmin=None, tmax=None):
        return self.get_generator().ensure_data(
            self.get_path(), tmin, tmax)

    def get_archive(self):
        self.ensure_data()

        path_tar = self.get_path('archive.tar')
        if not op.exists(path_tar):
            path_base = self.get_path()
            path_waveforms = self.get_path('waveforms')
            self.ensure_data()

            fns = util.select_files(
                [path_waveforms], show_progress=False)

            f = tarfile.TarFile(path_tar, 'w')
            for fn in fns:
                fna = fn[len(path_base)+1:]
                f.add(fn, fna)

            f.close()

        return path_tar


class ScenarioCollection(object):

    def __init__(self, path, engine):
        self._scenario_suffix = 'scenario'
        self._path = path
        util.ensuredir(self._path)
        self._engine = engine
        self._load_scenarios()

    def _load_scenarios(self):
        scenarios = []
        base_path = self.get_path()
        for path_entry in os.listdir(base_path):
            scenario_id, suffix = op.splitext(path_entry)
            if suffix == '.' + self._scenario_suffix:
                path = op.join(base_path, path_entry, 'scenario.yaml')
                scenario = guts.load(filename=path)
                assert scenario.scenario_id == scenario_id
                scenario.set_base_path(op.join(base_path, path_entry))
                scenario.init_modelling(self._engine)
                scenarios.append(scenario)

        self._scenarios = scenarios
        self._scenarios.sort(key=lambda s: s.time_created)

    def get_path(self, scenario_id=None, *entry):
        if scenario_id is not None:
            return op.join(self._path, '%s.%s' % (
                scenario_id, self._scenario_suffix), *entry)
        else:
            return self._path

    def add_scenario(self, scenario_id, scenario_generator):

        if scenario_generator.seed is None:
            scenario_generator = guts.clone(scenario_generator)
            scenario_generator.seed = num.random.randint(1, 2**32-1)

        path = self.get_path(scenario_id)
        try:
            os.mkdir(path)
        except OSError as e:
            if e.errno == errno.EEXIST:
                raise ScenarioError(
                    'Scenario id is already in use: %s' % scenario_id)
            else:
                raise

        scenario = ScenarioCollectionItem(
            scenario_id=scenario_id,
            time_created=util.to_time_float(time.time()))

        scenario_path = self.get_path(scenario_id, 'scenario.yaml')
        guts.dump(scenario, filename=scenario_path)

        generator_path = self.get_path(scenario_id, 'generator.yaml')
        guts.dump(scenario_generator, filename=generator_path)

        scenario.set_base_path(self.get_path(scenario_id))
        scenario.init_modelling(self._engine)

        self._scenarios.append(scenario)

    def list_scenarios(self, ilo=None, ihi=None):
        return self._scenarios[ilo:ihi]

    def get_scenario(self, scenario_id):
        for scenario in self._scenarios:
            if scenario.scenario_id == scenario_id:
                return scenario

        raise KeyError(scenario_id)
