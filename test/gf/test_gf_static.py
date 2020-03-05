from __future__ import division, print_function, absolute_import

import unittest
import numpy as num
import cProfile
import math
import logging
import shutil
import time

from tempfile import mkdtemp
from ..common import Benchmark
from pyrocko import gf, util, cake
from pyrocko.fomosto import qseis, psgrn_pscmp


random = num.random
logger = logging.getLogger('pyrocko.test.test_gf_static')
benchmark = Benchmark()

r2d = 180. / math.pi
d2r = 1.0 / r2d
km = 1000.


@unittest.skipUnless(
    qseis.have_backend(), 'backend qseis not available')
@unittest.skipUnless(
    psgrn_pscmp.have_backend(), 'backend psgrn_pscmp not available')
class GFStaticTest(unittest.TestCase):
    tempdirs = []
    stores = {}

    @classmethod
    def tearDownClass(cls):
        for d in cls.tempdirs:
            shutil.rmtree(d)

    def get_store_dir(self, name):
        create = {
            'qseis': self._create_qseis_store,
            'pscmp': self._create_psgrn_pscmp_store}

        if name not in self.stores:
            self.stores[name] = create[name]()

        return self.stores[name]

    def setUp(self):
        return False
        self.cprofile = cProfile.Profile()
        self.cprofile.enable()
        self.addCleanup(
            lambda: self.cprofile.dump_stats(
                '/tmp/process_static_params.prof'))

    def _create_psgrn_pscmp_store(self):
        mod = cake.LayeredModel.from_scanlines(cake.read_nd_model_str('''
 0. 5.8 3.46 2.6 1264. 600.
 20. 5.8 3.46 2.6 1264. 600.
 20. 6.5 3.85 2.9 1283. 600.
 35. 6.5 3.85 2.9 1283. 600.
mantle
 35. 8.04 4.48 3.58 1449. 600.
 77.5 8.045 4.49 3.5 1445. 600.
 77.5 8.045 4.49 3.5 180.6 75.
 120. 8.05 4.5 3.427 180. 75.
 120. 8.05 4.5 3.427 182.6 76.06
 165. 8.175 4.509 3.371 188.7 76.55
 210. 8.301 4.518 3.324 201. 79.4
 210. 8.3 4.52 3.321 336.9 133.3
 410. 9.03 4.871 3.504 376.5 146.1
 410. 9.36 5.08 3.929 414.1 162.7
 660. 10.2 5.611 3.918 428.5 172.9
 660. 10.79 5.965 4.229 1349. 549.6'''.lstrip()))

        store_dir = mkdtemp(prefix='gfstore')
        self.tempdirs.append(store_dir)
        store_id = 'psgrn_pscmp_test'
        version = '2008a'

        c = psgrn_pscmp.PsGrnPsCmpConfig()
        c.psgrn_config.sampling_interval = 1.
        c.psgrn_config.version = version
        c.pscmp_config.version = version

        config = gf.meta.ConfigTypeA(
            id=store_id,
            ncomponents=10,
            sample_rate=1./(3600. * 24.),
            receiver_depth=0.*km,
            source_depth_min=0.*km,
            source_depth_max=20.*km,
            source_depth_delta=0.5*km,
            distance_min=0.*km,
            distance_max=40.*km,
            distance_delta=0.5*km,
            modelling_code_id='psgrn_pscmp.%s' % version,
            earthmodel_1d=mod,
            tabulated_phases=[])
        config.validate()

        gf.store.Store.create_editables(
            store_dir, config=config, extra={'psgrn_pscmp': c})

        store = gf.store.Store(store_dir, 'r')
        store.close()

        psgrn_pscmp.build(store_dir, nworkers=4)

        return store_dir

    def _create_qseis_store(self):
        mod = cake.LayeredModel.from_scanlines(cake.read_nd_model_str('''
 0. 5.8 3.46 2.6 1264. 600.
 20. 5.8 3.46 2.6 1264. 600.
 20. 6.5 3.85 2.9 1283. 600.
 35. 6.5 3.85 2.9 1283. 600.'''.lstrip()))
        store_dir = mkdtemp(prefix='gfstore')
        self.tempdirs.append(store_dir)

        qsconf = qseis.QSeisConfig()
        qsconf.qseis_version = '2006a'

        qsconf.time_region = (
            gf.meta.Timing('0'),
            gf.meta.Timing('end+100'))

        qsconf.cut = (
            gf.meta.Timing('0'),
            gf.meta.Timing('end+100'))

        qsconf.wavelet_duration_samples = 0.001
        qsconf.sw_flat_earth_transform = 0

        config = gf.meta.ConfigTypeA(
            id='qseis_test',
            ncomponents=10,
            sample_rate=0.25,
            receiver_depth=0.*km,
            source_depth_min=2.5*km,
            source_depth_max=10*km,
            source_depth_delta=2.5*km,
            distance_min=0*km,
            distance_max=20*km,
            distance_delta=2.5*km,
            modelling_code_id='qseis.2006a',
            earthmodel_1d=mod,
            tabulated_phases=[
                gf.meta.TPDef(
                    id='begin',
                    definition='p,P,p\\,P\\'),
                gf.meta.TPDef(
                    id='end',
                    definition='2.5'),
            ])

        config.validate()
        gf.store.Store.create_editables(
            store_dir, config=config, extra={'qseis': qsconf})

        store = gf.store.Store(store_dir, 'r')
        store.make_ttt()
        store.close()
        qseis.build(store_dir, nworkers=1)
        return store_dir

    def test_process_static(self):
        src_length = 5 * km
        src_width = 2 * km
        ntargets = 1600
        interp = ['nearest_neighbor', 'multilinear']
        interpolation = interp[0]

        source = gf.RectangularSource(
            lat=0., lon=0.,
            north_shift=0., east_shift=0., depth=6.5*km,
            width=src_width, length=src_length,
            dip=90., rake=90., strike=90.,
            slip=1.)

        phi = num.zeros(ntargets)              # Horizontal from E
        theta = num.ones(ntargets) * num.pi/2  # Vertical from vertical
        phi.fill(num.deg2rad(192.))
        theta.fill(num.deg2rad(90.-23.))

        sattarget = gf.SatelliteTarget(
            north_shifts=(random.rand(ntargets)-.5) * 25. * km,
            east_shifts=(random.rand(ntargets)-.5) * 25. * km,
            tsnapshot=20,
            interpolation=interpolation,
            phi=phi,
            theta=theta)

        static_target = gf.StaticTarget(
            north_shifts=(random.rand(ntargets)-.5) * 25. * km,
            east_shifts=(random.rand(ntargets)-.5) * 25. * km,
            tsnapshot=20,
            interpolation=interpolation)

        engine = gf.LocalEngine(store_dirs=[self.get_store_dir('pscmp')])

        def process_target(nprocs):

            @benchmark.labeled('process-nearest_neighbor-np%d' % nprocs)
            def process_nearest_neighbor():
                sattarget.interpolation = 'nearest_neighbor'
                return engine.process(source, sattarget, nprocs=nprocs)

            @benchmark.labeled('process-multilinear-np%d' % nprocs)
            def process_multilinear():
                sattarget.interpolation = 'multilinear'
                return engine.process(source, sattarget, nprocs=nprocs)

            return process_nearest_neighbor(), process_multilinear()

        def process_multiple_targets():
            return engine.process(source, [sattarget, static_target])

        for np in [1, 2, 4]:
            nn, ml = process_target(nprocs=np)

        process_multiple_targets()

        # self.plot_static_los_result(ml)

    def test_pseudo_dyn_rupture_vs_rectangular(self):

        engine = gf.LocalEngine(store_dirs=[self.get_store_dir('pscmp')])
        store = engine.get_store('psgrn_pscmp_test')
        ntargets = 50
        interpolation = 'nearest_neighbor'

        source_params = dict(
            north_shift=2*km,
            east_shift=2*km,
            depth=6.5*km,
            width=2.*km,
            length=4*km,
            dip=random.uniform(0., 90.),
            strike=random.uniform(-180., 180.),
            magnitude=7.,
            anchor='top',
            decimation_factor=4)

        dyn_rupture = gf.PseudoDynamicRupture(
            nx=4, ny=4,
            tractions=(1.e4, 0.e4, 0.),
            **source_params)

        dyn_rupture.ensure_tractions()
        dyn_rupture.discretize_patches(store)
        slip = dyn_rupture.get_okada_slip()
        rake = num.arctan2(slip[:, 1].mean(), slip[:, 0].mean())

        rect_rupture = gf.RectangularSource(
            rake=float(rake*d2r),
            **source_params)

        static_target = gf.StaticTarget(
            north_shifts=(random.rand(ntargets)-.5) * 25. * km,
            east_shifts=(random.rand(ntargets)-.5) * 25. * km,
            tsnapshot=20,
            interpolation=interpolation)

        result = engine.process(rect_rupture, static_target)
        synth_disp_rect = result.results_list[0][0].result

        result = engine.process(dyn_rupture, static_target)
        synth_disp_dyn = result.results_list[0][0].result

        down_rect = synth_disp_rect['displacement.d']
        down_dyn = synth_disp_dyn['displacement.d']

        num.testing.assert_allclose(down_rect, down_dyn)

    @staticmethod
    def plot_static_los_result(result):
        import matplotlib.pyplot as plt

        fig, _ = plt.subplots(1, 4)

        N = result.request.targets[0].coords5[:, 2]
        E = result.request.targets[0].coords5[:, 3]
        result = result.results_list[0][0].result

        vranges = [(result['displacement.%s' % c].max(),
                    result['displacement.%s' % c].min()) for c in list('ned') +
                   ['los']]

        lmax = num.abs([num.min(vranges), num.max(vranges)]).max()
        levels = num.linspace(-lmax, lmax, 50)

        for dspl, ax in zip(list('ned') + ['los'], fig.axes):
            cmap = ax.tricontourf(E, N, result['displacement.%s' % dspl],
                                  cmap='seismic', levels=levels)
            ax.set_title('displacement.%s' % dspl)
            ax.set_aspect('equal')

        fig.colorbar(cmap)
        plt.show()

    def test_sum_static(self):
        from pyrocko.gf import store_ext
        benchmark.show_factor = True

        store = gf.Store(self.get_store_dir('qseis'))
        store.open()
        src_length = 2 * km
        src_width = 5 * km
        ntargets = 1600
        interp = ['nearest_neighbor', 'multilinear']
        interpolation = interp[0]

        source = gf.RectangularSource(
            lat=0., lon=0.,
            depth=5*km, north_shift=0., east_shift=0.,
            width=src_width, length=src_length)

        static_target = gf.StaticTarget(
            north_shifts=5*km + random.rand(ntargets) * 5*km,
            east_shifts=0*km + random.rand(ntargets) * 5*km)
        targets = static_target.get_targets()

        dsource = source.discretize_basesource(store, targets[0])
        source_coords_arr = dsource.coords5()
        mts_arr = dsource.m6s

        receiver_coords_arr = num.empty((len(targets), 5))
        for itarget, target in enumerate(targets):
            receiver = target.receiver(store)
            receiver_coords_arr[itarget, :] = \
                [receiver.lat, receiver.lon, receiver.north_shift,
                 receiver.east_shift, receiver.depth]

        def sum_target(cstore, irecords, delays_t, delays_s,
                       weights, pos, nthreads):

            @benchmark.labeled('sum-timeseries-np%d' % nthreads)
            def sum_timeseries():
                nsummands = weights.size // ntargets
                res = num.zeros(ntargets)
                for t in range(ntargets):
                    sl = slice(t*nsummands, (t+1) * nsummands)
                    r = store_ext.store_sum(
                        cstore, irecords[sl], delays_t[sl],
                        weights[sl], pos, 1)
                    res[t] = r[0]
                return res

            @benchmark.labeled('sum-static-np%d' % nthreads)
            def sum_static():
                return store_ext.store_sum_static(
                    cstore, irecords, delays_s, weights,
                    pos, ntargets, nthreads)

            return sum_timeseries(), sum_static()

        args = (store.cstore, source_coords_arr, mts_arr, receiver_coords_arr,
                'elastic10', interpolation, 0)

        benchmark.clear()
        for nthreads in [1, 2, 4]:
            for (weights, irecords) in store_ext.make_sum_params(*args):
                delays_t = num.zeros_like(weights, dtype=num.float64)
                delays_s = dsource.times.astype(num.float64)
                pos = 6
                t, s = sum_target(store.cstore, irecords, delays_t, delays_s,
                                  weights, pos, nthreads)
                # print benchmark.__str__(header=False)
                num.testing.assert_equal(t, s)
                benchmark.clear()

    def test_gnss_target(self):
        src_length = 5 * km
        src_width = 2 * km
        nstations = 100
        interp = ['nearest_neighbor', 'multilinear']
        interpolation = interp[0]

        source = gf.RectangularSource(
            lat=0., lon=0.,
            north_shift=0., east_shift=0., depth=6.5*km,
            width=src_width, length=src_length,
            dip=90., rake=90., strike=90.,
            slip=1.)

        gnss_target = gf.GNSSCampaignTarget(
            lats=(random.uniform(-.2, .2, nstations)),
            lons=(random.uniform(-.2, .2, nstations)),
            interpolation=interpolation)

        engine = gf.LocalEngine(store_dirs=[self.get_store_dir('pscmp')])
        res = engine.process(source, gnss_target, nprocs=2)

        statics = res.static_results()
        for static in statics:
            assert len(static.campaign.stations) == nstations

    def test_new_static(self):
        from pyrocko.gf import store_ext
        benchmark.show_factor = True

        store = gf.Store(self.get_store_dir('pscmp'))
        store.open()
        src_length = 2 * km
        src_width = 2 * km
        ntargets = 20

        north_shifts, east_shifts = num.meshgrid(
            num.linspace(-20*km, 20*km, ntargets),
            num.linspace(-20*km, 20*km, ntargets))

        interp = ['nearest_neighbor', 'multilinear']
        interpolation = interp[1]

        source = gf.RectangularSource(
            lat=0., lon=0.,
            depth=5*km, north_shift=0., east_shift=0.,
            anchor='top',
            width=src_width, length=src_length)

        static_target = gf.GNSSCampaignTarget(
            north_shifts=north_shifts,
            east_shifts=east_shifts,
            lats=num.zeros_like(north_shifts),
            lons=num.zeros_like(north_shifts))

        targets = static_target.get_targets()

        dsource = source.discretize_basesource(store, targets[0])
        mts_arr = dsource.m6s
        delays_s = dsource.times.astype(num.float64)
        pos = 1

        scheme_desc = ['displacement.n', 'displacement.e', 'displacement.d']

        benchmark.clear()

        def run(interpolation=interp[0], nthreads=1, niter=1):

            @benchmark.labeled(' sum_statics %d cpu (%s)' %
                               (nthreads, interpolation))
            def fwd_model_seperate(interpolation=interp[0]):
                args = (store.cstore, dsource.coords5(), mts_arr,
                        static_target.coords5, 'elastic10', interpolation,
                        nthreads)

                sum_params = store_ext.make_sum_params(*args)

                out = {}

                for icomp, comp in enumerate(scheme_desc):
                    weights, irecords = sum_params[icomp]
                    out[comp] = store_ext.store_sum_static(
                            store.cstore, irecords, delays_s, weights,
                            pos, ntargets**2, nthreads)
                return out

            @benchmark.labeled('calc_statics %d cpu (%s)' %
                               (nthreads, interpolation))
            def fwd_model_unified(interpolation=interp[0]):
                out = {}
                res = store_ext.store_calc_static(
                        store.cstore,
                        dsource.coords5(),
                        mts_arr,
                        dsource.times,
                        static_target.coords5,
                        'elastic10',
                        interpolation,
                        pos,
                        nthreads)
                for comp, r in zip(scheme_desc, res):
                    out[comp] = r

                return out

            for _ in range(niter):
                res1 = fwd_model_seperate(interpolation)
            for _ in range(niter):
                res2 = fwd_model_unified(interpolation)

            for r1, r2 in zip(res1.values(), res2.values()):
                num.testing.assert_equal(r1, r2)

        for interpolation in interp:
            continue
            for nthreads in [1, 2, 4, 8, 0]:
                run(interpolation, nthreads)
            # print(benchmark)
            benchmark.clear()

        run(interpolation, nthreads=0, niter=30)
        # print(benchmark)

        def plot(displ):
            import matplotlib.pyplot as plt
            size = int(num.sqrt(displ.size))
            fig = plt.figure()
            ax = fig.gca()
            ax.imshow(displ.reshape((size, size)))
            plt.show()

        # plot(res1['displacement.n'])

    def test_static_timing(self):
        src_length = 5 * km
        src_width = 2 * km
        nstations = 100
        day = 3600 * 24
        interp = ['nearest_neighbor', 'multilinear']
        interpolation = interp[0]

        source = gf.RectangularSource(
            lat=0., lon=0.,
            north_shift=0., east_shift=0., depth=6.5*km,
            width=src_width, length=src_length,
            dip=90., rake=90., strike=90.,
            slip=1.,
            time=time.time()-day)

        source = gf.DCSource(
            lat=0., lon=0.,
            north_shift=0., east_shift=0., depth=6.5*km,
            dip=90., rake=90., strike=90.,
            time=time.time()-day)

        lats = random.uniform(-.2, .2, nstations)
        lons = random.uniform(-.2, .2, nstations)

        target_1 = gf.StaticTarget(
            lats=lats,
            lons=lons,
            interpolation=interpolation,
            tsnapshot=time.time() + day)

        target_2 = gf.StaticTarget(
            lats=lats,
            lons=lons,
            interpolation=interpolation,
            tsnapshot=time.time())

        engine = gf.LocalEngine(store_dirs=[self.get_store_dir('pscmp')])
        res = engine.process(source, [target_1, target_2], nprocs=0)\

        statics_1, statics_2 = res.static_results()
        num.testing.assert_equal(
            statics_1.result['displacement.n'],
            statics_2.result['displacement.n'])


if __name__ == '__main__':
    util.setup_logging('test_gf', 'warning')
    unittest.main(defaultTest='GFStaticTest')
