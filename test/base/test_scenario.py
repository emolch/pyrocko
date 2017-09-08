from __future__ import division, print_function, absolute_import
import unittest
from tempfile import mkdtemp
import shutil

from pyrocko import scenario, util, gf, config
from pyrocko.scenario import targets
from pyrocko.plot import gmtpy

util.force_dummy_progressbar = True

km = 1000.


def have_store(store_id):
    engine = gf.get_engine()
    try:
        engine.get_store(store_id)
        return True, ''
    except gf.NoSuchStore:
        return False, 'GF store "%s" not available' % store_id


def have_kite():
    try:
        import kite  # noqa
        return True
    except ImportError:
        return False


def have_srtm_credentials():
    if config.config().earthdata_credentials is None:
        return False
    return True


class ScenarioTestCase(unittest.TestCase):
    store_id = 'crust2_m5_hardtop_8Hz_fine'
    store_id_static = 'ak135_static'

    tempdirs = []

    @classmethod
    def tearDownClass(cls):
        for d in cls.tempdirs:
            continue
            shutil.rmtree(d)

    @unittest.skipUnless(*have_store(store_id))
    def test_scenario_waveforms(self):
        tempdir = mkdtemp(prefix='pyrocko-scenario')
        self.tempdirs.append(tempdir)

        vmin = 2500.

        generator = scenario.ScenarioGenerator(
            seed=20,
            center_lat=42.6,
            center_lon=13.3,
            radius=60*km,
            target_generators=[
                targets.WaveformGenerator(
                    store_id=ScenarioTestCase.store_id,
                    station_generator=targets.RandomStationGenerator(
                        nstations=5,
                        avoid_water=False),
                    noise_generator=targets.waveform.WhiteNoiseGenerator(),
                    seismogram_quantity='velocity'),
                ],
            source_generator=scenario.DCSourceGenerator(
                time_min=util.str_to_time('2017-01-01 00:00:00'),
                time_max=util.str_to_time('2017-01-01 02:00:00'),
                radius=10*km,
                depth_min=1*km,
                depth_max=10*km,
                magnitude_min=3.0,
                magnitude_max=4.5,
                strike=120.,
                dip=45.,
                rake=90.,
                perturbation_angle_std=15.,
                nevents=3)
        )

        def twin(source):
            tmin = source.time
            tmax = source.time + 100*km / vmin
            return tmin, tmax

        engine = gf.get_engine()
        generator.init_modelling(engine)

        ref_sources = generator.get_sources()
        ref_trs_list = []
        for source in ref_sources:
            trs = generator.get_waveforms(*twin(source))
            trs.sort(key=lambda tr: tr.nslc_id)
            ref_trs_list.append(trs)

        collection = scenario.ScenarioCollection(tempdir, engine)
        collection.add_scenario('one', generator)
        with self.assertRaises(scenario.ScenarioError):
            collection.add_scenario('one', generator)

        assert len(collection.list_scenarios()) == 1
        assert collection.list_scenarios()[0].scenario_id == 'one'

        s = collection.get_scenario('one')

        for ref_trs, source in zip(
                ref_trs_list,
                s.get_generator().get_sources()):

            trs = generator.get_waveforms(*twin(source))
            trs.sort(key=lambda tr: tr.nslc_id)
            self.assert_traces_almost_equal(trs, ref_trs)

        collection2 = scenario.ScenarioCollection(tempdir, engine)

        assert len(collection2.list_scenarios()) == 1
        assert collection2.list_scenarios()[0].scenario_id == 'one'

        s = collection2.get_scenario('one')

        for ref_trs, source in zip(
                ref_trs_list,
                s.get_generator().get_sources()):

            trs = generator.get_waveforms(*twin(source))
            trs.sort(key=lambda tr: tr.nslc_id)
            self.assert_traces_almost_equal(trs, ref_trs)

        tmin, tmax = s.get_time_range()
        s.ensure_data(tmin, tmax)
        p = s.get_waveform_pile()

        for ref_trs, source in zip(
                ref_trs_list,
                s.get_generator().get_sources()):

            tmin, tmax = twin(source)
            trs = p.all(tmin=tmin, tmax=tmax, include_last=False)
            trs.sort(key=lambda tr: tr.nslc_id)
            self.assert_traces_almost_equal(trs, ref_trs)

    @unittest.skipUnless(
        have_kite(),
        'Kite is not available')
    @unittest.skipUnless(*have_store(store_id))
    @unittest.skipUnless(*have_store(store_id_static))
    def test_scenario_insar(self):
        tempdir = mkdtemp(prefix='pyrocko-scenario')
        self.tempdirs.append(tempdir)

        generator = scenario.ScenarioGenerator(
            seed=20,
            center_lat=42.6,
            center_lon=13.3,
            radius=60*km,
            target_generators=[
                targets.InSARGenerator(
                    resolution=(20, 20),
                    noise_generator=targets.insar.AtmosphericNoiseGenerator(
                        amplitude=1e-5))
                ],
            source_generator=scenario.DCSourceGenerator(
                time_min=util.str_to_time('2017-01-01 00:00:00'),
                time_max=util.str_to_time('2017-01-01 02:00:00'),
                radius=10*km,
                depth_min=1*km,
                depth_max=10*km,
                magnitude_min=3.0,
                magnitude_max=4.5,
                strike=120.,
                dip=45.,
                rake=90.,
                perturbation_angle_std=15.,
                nevents=3)
        )

        engine = gf.get_engine()
        generator.init_modelling(engine)

        collection = scenario.ScenarioCollection(tempdir, engine)
        collection.add_scenario('insar', generator)

        s = collection.get_scenario('insar')
        s.ensure_data()

    @unittest.skipUnless(*have_store(store_id_static))
    def test_scenario_gnss(self):
        tempdir = mkdtemp(prefix='pyrocko-scenario')
        self.tempdirs.append(tempdir)

        generator = scenario.ScenarioGenerator(
            seed=20,
            center_lat=42.6,
            center_lon=13.3,
            radius=60*km,
            target_generators=[
                targets.GNSSCampaignGenerator(
                    station_generator=targets.RandomStationGenerator(
                        avoid_water=False,
                        channels=None))
                ],
            source_generator=scenario.DCSourceGenerator(
                time_min=util.str_to_time('2017-01-01 00:00:00'),
                time_max=util.str_to_time('2017-01-01 02:00:00'),
                radius=10*km,
                depth_min=1*km,
                depth_max=10*km,
                magnitude_min=3.0,
                magnitude_max=4.5,
                strike=120.,
                dip=45.,
                rake=90.,
                perturbation_angle_std=15.,
                nevents=3)
        )

        engine = gf.get_engine()
        generator.init_modelling(engine)

        collection = scenario.ScenarioCollection(tempdir, engine)
        collection.add_scenario('gnss', generator)

        s = collection.get_scenario('gnss')
        assert len(s.get_gnss_campaigns()) == 1

    @unittest.skipUnless(
        have_kite(),
        'Kite is not available')
    @unittest.skipUnless(*have_store(store_id))
    @unittest.skipUnless(*have_store(store_id_static))
    def test_scenario_combinations(self):

        generator = scenario.ScenarioGenerator(
            seed=20,
            center_lat=42.6,
            center_lon=13.3,
            radius=60*km,
            target_generators=[
                targets.WaveformGenerator(
                    store_id=ScenarioTestCase.store_id,
                    station_generator=targets.RandomStationGenerator(
                        avoid_water=False),
                    noise_generator=targets.waveform.WhiteNoiseGenerator(),
                    seismogram_quantity='velocity'),
                targets.InSARGenerator(
                    resolution=(20, 20),
                    noise_generator=targets.insar.AtmosphericNoiseGenerator(
                        amplitude=1e-5)),
                targets.GNSSCampaignGenerator(
                    station_generator=targets.RandomStationGenerator(
                        avoid_water=False,
                        channels=None))
                ],
            source_generator=scenario.DCSourceGenerator(
                time_min=util.str_to_time('2017-01-01 00:00:00'),
                time_max=util.str_to_time('2017-01-01 02:00:00'),
                radius=10*km,
                depth_min=1*km,
                depth_max=10*km,
                magnitude_min=3.0,
                magnitude_max=4.5,
                strike=120.,
                dip=45.,
                rake=90.,
                perturbation_angle_std=15.,
                nevents=3)
        )

        engine = gf.get_engine()
        generator.init_modelling(engine)

        for src in scenario.sources.AVAILABLE_SOURCES:
            generator.source_generator = src(
                time_min=util.str_to_time('2017-01-01 00:00:00'),
                time_max=util.str_to_time('2017-01-01 02:00:00'),
                radius=1*km,
                depth_min=1.5*km,
                depth_max=5*km,
                magnitude_min=3.0,
                magnitude_max=4.5)
            generator.source_generator.update_hierarchy(generator)

            generator.get_stations()
            generator.get_waveforms()
            generator.get_insar_scenes()
            generator.get_gnss_campaigns()

    @unittest.skipUnless(*have_store(store_id_static))
    @unittest.skipUnless(
        gmtpy.have_gmt(), 'GMT not available')
    @unittest.skipUnless(
        have_srtm_credentials(),
        'No Earthdata credentials in config.')
    def test_scenario_map(self):
        tempdir = mkdtemp(prefix='pyrocko-scenario')
        self.tempdirs.append(tempdir)

        generator = scenario.ScenarioGenerator(
            seed=20,
            center_lat=42.6,
            center_lon=13.3,
            radius=60*km,
            target_generators=[
                targets.WaveformGenerator(
                    store_id=ScenarioTestCase.store_id,
                    station_generator=targets.RandomStationGenerator(
                        avoid_water=False),
                    noise_generator=targets.waveform.WhiteNoiseGenerator(),
                    seismogram_quantity='velocity'),
                targets.InSARGenerator(
                    resolution=(20, 20),
                    noise_generator=targets.insar.AtmosphericNoiseGenerator(
                        amplitude=1e-5)),
                targets.GNSSCampaignGenerator(
                    station_generator=targets.RandomStationGenerator(
                        avoid_water=False,
                        channels=None))
                ],
            source_generator=scenario.DCSourceGenerator(
                time_min=util.str_to_time('2017-01-01 00:00:00'),
                time_max=util.str_to_time('2017-01-01 02:00:00'),
                radius=10*km,
                depth_min=1*km,
                depth_max=10*km,
                magnitude_min=3.0,
                magnitude_max=4.5,
                strike=120.,
                dip=45.,
                rake=90.,
                perturbation_angle_std=15.,
                nevents=3)
        )

        engine = gf.get_engine()

        collection = scenario.ScenarioCollection(tempdir, engine)
        collection.add_scenario('plot', generator)

        s = collection.get_scenario('plot')
        s.get_map()

    def assert_traces_almost_equal(self, trs1, trs2):
        assert len(trs1) == len(trs2)
        for (tr1, tr2) in zip(trs1, trs2):
            tr1.assert_almost_equal(tr2)


if __name__ == '__main__':
    util.setup_logging('test_scenario', 'warning')
    unittest.main()
