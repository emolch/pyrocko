from __future__ import division, print_function, absolute_import
import math
from time import time
import unittest
import logging
from tempfile import mkdtemp
import numpy as num
import os
import shutil
from copy import deepcopy
from multiprocessing import cpu_count

from pyrocko import orthodrome as ortd
from pyrocko import util, gf, cake  # noqa
from pyrocko.fomosto import psgrn_pscmp
from ..common import Benchmark

logger = logging.getLogger('pyrocko.test.test_gf_psgrn_pscmp')
benchmark = Benchmark()
uniform = num.random.uniform

r2d = 180. / math.pi
d2r = 1.0 / r2d
km = 1e3
mm = 1e-3

neast = 40
nnorth = 40

show_plot = int(os.environ.get('MPL_SHOW', 0))


def statics(engine, source, starget):
    store = engine.get_store(starget.store_id)
    dsource = source.discretize_basesource(store, starget)

    assert len(starget.north_shifts) == len(starget.east_shifts)

    out = num.zeros((len(starget.north_shifts), len(starget.components)))
    sfactor = source.get_factor()
    for i, (north, east) in enumerate(
            zip(starget.north_shifts, starget.east_shifts)):

        receiver = gf.Receiver(
            lat=starget.lat,
            lon=starget.lon,
            north_shift=north,
            east_shift=east,
            depth=starget.depth)

        values = store.statics(
            dsource, receiver, starget.components,
            interpolation=starget.interpolation)

        for icomponent, value in enumerate(values):
            out[i, icomponent] = value * sfactor

    return out


@unittest.skipUnless(
    psgrn_pscmp.have_backend(), 'backend psgrn_pscmp not available')
class GFPsgrnPscmpTestCase(unittest.TestCase):

    tempdirs = []
    pscmp_store_dir = None
    psgrn_config = None

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)

    @classmethod
    def tearDownClass(cls):
        for d in cls.tempdirs:
            shutil.rmtree(d)

    def test_isolated_isotropic_component(self):
        shear = 31126160000.0
        lame_lambda = 25211680000.0

        cdm = num.array([
            [(2 * shear + lame_lambda), lame_lambda, lame_lambda],
            [lame_lambda, (2 * shear + lame_lambda), lame_lambda],
            [lame_lambda, lame_lambda, (2 * shear + lame_lambda)]])

        nullf = psgrn_pscmp.get_nullification_factor(
            mu=shear, lame_lambda=lame_lambda)

        cdm[0:2, :] *= nullf
        null_cdm = cdm.sum(0)

        num.testing.assert_allclose(null_cdm[0:2], num.zeros(2))

    @classmethod
    def get_pscmp_store_info(cls):
        if cls.pscmp_store_dir is None:
            cls.pscmp_store_dir, cls.psgrn_config \
                = cls._create_psgrn_pscmp_store()

        return cls.pscmp_store_dir, cls.psgrn_config

    @classmethod
    def _create_psgrn_pscmp_store(cls, extra_config=None):

        mod = cake.LayeredModel.from_scanlines(cake.read_nd_model_str('''
   0. 5.8 3.46 2.6 1264. 600.
  20. 5.8 3.46 2.6 1264. 600.
  20. 6.5 3.85 2.9 1283. 600.
  35. 6.5 3.85 2.9 1283. 600.
mantle
  35. 8.04 4.48 3.58 1449. 600.
  77. 8.045 4.49 3.5 1445. 600.
  77. 8.045 4.49 3.5 180.6 75.
 120. 8.05 4.5 3.427 180. 75.
 120. 8.05 4.5 3.427 182.6 76.06
 165. 8.175 4.509 3.371 188.7 76.55
 210. 8.301 4.518 3.324 201. 79.4
 210. 8.3 4.52 3.321 336.9 133.3
 410. 9.03 4.871 3.504 376.5 146.1
 410. 9.36 5.08 3.929 414.1 162.7
 660. 10.2 5.611 3.918 428.5 172.9
 660. 10.79 5.965 4.229 1349. 549.6 5e17 1e19 1'''.lstrip()))

        store_dir = mkdtemp(prefix='gfstore')
        # store_dir = '/tmp/pscmp_gfstore'
        cls.tempdirs.append(store_dir)
        store_id = 'psgrn_pscmp_test'

        if not extra_config:
            c = psgrn_pscmp.PsGrnPsCmpConfig()
            c.psgrn_config.sampling_interval = 1.
        else:
            c = extra_config

        version = '2008a'
        c.psgrn_config.version = version
        c.pscmp_config.version = version

        config = gf.meta.ConfigTypeA(
            id=store_id,
            modelling_code_id='psgrn_pscmp.%s' % version,
            earthmodel_1d=mod,
            sample_rate=1. / (3600. * 24.),
            component_scheme='elastic10',
            tabulated_phases=[],
            ncomponents=10,
            receiver_depth=0. * km,
            source_depth_min=0. * km,
            source_depth_max=6. * km,
            source_depth_delta=0.25 * km,
            distance_min=0. * km,
            distance_max=40. * km,
            distance_delta=.25 * km)

        config.validate()
        if not os.path.exists(os.path.join(store_dir, 'config')):
            gf.store.Store.create_editables(
                store_dir, config=config, extra={'psgrn_pscmp': c})

            store = gf.store.Store(store_dir, 'r')
            store.close()

            # build store
            try:
                psgrn_pscmp.build(store_dir, nworkers=cpu_count())
            except psgrn_pscmp.PsCmpError as e:
                if str(e).find('could not start psgrn/pscmp') != -1:
                    logger.warn('psgrn/pscmp not installed; '
                                'skipping test_pyrocko_gf_vs_pscmp')
                    return
                else:
                    raise e

        return store_dir, c

    def fomosto_vs_psgrn_pscmp(self, pscmp_sources, gf_sources, atol=2*mm):

        def plot_components_compare(fomosto_comps, psgrn_comps):
            import matplotlib.pyplot as plt

            fig, axes = plt.subplots(4, 3)

            for i, (fcomp, pscomp, cname) in enumerate(
                    zip(fomosto_comps, psgrn_comps, ['N', 'E', 'D'])):
                fdispl = fcomp.reshape(nnorth, neast)
                pdispl = pscomp.reshape(nnorth, neast)
                pcbound = num.max([num.abs(pdispl.min()), pdispl.max()])
                # fcbound = num.max([num.abs(fdispl.min()), fdispl.max()])

                axes[0, i].imshow(
                    pdispl, cmap='seismic', vmin=-pcbound, vmax=pcbound)
                axes[1, i].imshow(
                    fdispl, cmap='seismic', vmin=-pcbound, vmax=pcbound)
                diff = pdispl - fdispl
                rdiff = pdispl / fdispl
                axes[2, i].imshow(diff, cmap='seismic')
                axes[3, i].imshow(rdiff, cmap='seismic')

                axes[0, i].set_title('PSCMP %s' % cname)
                axes[1, i].set_title('Fomosto %s' % cname)
                axes[2, i].set_title(
                    'abs diff min max %f, %f' % (diff.min(), diff.max()))
                axes[3, i].set_title(
                    'rel diff min max %f, %f' % (rdiff.min(), rdiff.max()))

            plt.show()

        store_dir, c = self.get_pscmp_store_info()

        origin = gf.Location(
            lat=10.,
            lon=-15.)

        N, E = num.meshgrid(num.linspace(-20. * km, 20. * km, nnorth),
                            num.linspace(-20. * km, 20. * km, neast))

        # direct pscmp output
        lats, lons = ortd.ne_to_latlon(
            origin.lat, origin.lon, N.flatten(), E.flatten())

        cc = c.pscmp_config
        cc.observation = psgrn_pscmp.PsCmpScatter(lats=lats, lons=lons)

        cc.rectangular_source_patches = pscmp_sources
        cc.snapshots = psgrn_pscmp.PsCmpSnapshots(
            tmin=0.,
            tmax=1.,
            deltatdays=1.)

        ccf = psgrn_pscmp.PsCmpConfigFull(**cc.items())
        ccf.psgrn_outdir = os.path.join(store_dir, c.gf_outdir) + '/'

        t2 = time()
        runner = psgrn_pscmp.PsCmpRunner(keep_tmp=False)
        runner.run(ccf)
        ps2du = runner.get_results(component='displ')[0]
        logger.info('pscmp stacking time %f s' % (time() - t2))

        un_pscmp = ps2du[:, 0]
        ue_pscmp = ps2du[:, 1]
        ud_pscmp = ps2du[:, 2]

        # test against engine
        starget_nn = gf.StaticTarget(
            lats=num.full(N.size, origin.lat),
            lons=num.full(N.size, origin.lon),
            north_shifts=N.flatten(),
            east_shifts=E.flatten(),
            interpolation='nearest_neighbor')

        starget_ml = gf.StaticTarget(
            lats=num.full(N.size, origin.lat),
            lons=num.full(N.size, origin.lon),
            north_shifts=N.flatten(),
            east_shifts=E.flatten(),
            interpolation='multilinear')

        engine = gf.LocalEngine(store_dirs=[store_dir])

        for source in gf_sources:
            t0 = time()
            r = engine.process(source, [starget_nn, starget_ml])
            logger.info('pyrocko stacking time %f' % (time() - t0))
            for i, static_result in enumerate(r.static_results()):
                un_fomosto = static_result.result['displacement.n']
                ue_fomosto = static_result.result['displacement.e']
                ud_fomosto = static_result.result['displacement.d']

                if show_plot:
                    fomosto_comps = [un_fomosto, ue_fomosto, ud_fomosto]
                    psgrn_comps = [un_pscmp, ue_pscmp, ud_pscmp]
                    plot_components_compare(fomosto_comps, psgrn_comps)

                num.testing.assert_allclose(un_fomosto, un_pscmp, atol=atol)
                num.testing.assert_allclose(ue_fomosto, ue_pscmp, atol=atol)
                num.testing.assert_allclose(ud_fomosto, ud_pscmp, atol=atol)

    def test_fomosto_vs_psgrn_pscmp_shear(self):

        origin = gf.Location(
            lat=10.,
            lon=-15.)

        # test GF store
        TestRF = dict(
            lat=origin.lat,
            lon=origin.lon,
            depth=2. * km,
            width=0.2 * km,
            length=7. * km,
            rake=uniform(-90., 90.),
            dip=uniform(0., 90.),
            strike=uniform(0., 360.),
            slip=uniform(1., 5.))

        source_plain = gf.RectangularSource(
            aggressive_oversampling=True,
            **TestRF)
        source_with_time = gf.RectangularSource(
            time=123.5,
            aggressive_oversampling=True,
            **TestRF)

        gf_sources = [source_plain, source_with_time]
        pscmp_sources = [psgrn_pscmp.PsCmpRectangularSource(**TestRF)]

        self.fomosto_vs_psgrn_pscmp(
            pscmp_sources=pscmp_sources, gf_sources=gf_sources, atol=5*mm)

    def test_fomosto_vs_psgrn_pscmp_tensile(self):

        origin = gf.Location(
            lat=10.,
            lon=-15.)

        # test GF store
        TestRF = dict(
            lat=origin.lat,
            lon=origin.lon,
            depth=2. * km,
            width=2. * km,
            length=5. * km,
            rake=uniform(-90., 90.),
            dip=uniform(0., 90.),
            strike=uniform(0., 360.))

        slip = uniform(1., 2.)

        for open_mode in [-1., 1.]:   # closing, opening

            source_plain = gf.RectangularSource(
                aggressive_oversampling=True,
                **TestRF)
            source_plain.update(slip=slip, opening_fraction=open_mode)

            source_with_time = deepcopy(source_plain)
            source_with_time.update(time=123.5)

            gf_sources = [source_plain, source_with_time]

            pscmp_sources = [psgrn_pscmp.PsCmpRectangularSource(
                opening=slip * open_mode, slip=0., **TestRF)]

            self.fomosto_vs_psgrn_pscmp(
                pscmp_sources=pscmp_sources, gf_sources=gf_sources, atol=7*mm)

    def test_fomosto_vs_psgrn_pscmp_tensile_shear(self):

        origin = gf.Location(
            lat=10.,
            lon=-15.)

        # test GF store
        TestRF = dict(
            lat=origin.lat,
            lon=origin.lon,
            depth=3. * km,
            width=2. * km,
            length=5. * km,
            rake=uniform(-90., 90.),
            dip=uniform(0., 90.),
            strike=uniform(0., 360.))

        opening_fraction = 0.4
        slip = uniform(1., 5.)
        opening = slip * opening_fraction
        pscmp_slip = slip - opening

        source_plain = gf.RectangularSource(
            aggressive_oversampling=True,
            **TestRF)
        source_plain.update(slip=slip, opening_fraction=opening_fraction)

        source_with_time = deepcopy(source_plain)
        source_with_time.update(time=123.5)

        gf_sources = [source_plain, source_with_time]
        pscmp_sources = [psgrn_pscmp.PsCmpRectangularSource(
            opening=opening, slip=pscmp_slip, **TestRF)]

        self.fomosto_vs_psgrn_pscmp(
            pscmp_sources=pscmp_sources, gf_sources=gf_sources, atol=7*mm)

    def plot_gf_distance_sampling(self):
        origin = gf.Location(
            lat=10.,
            lon=-15.)

        # test GF store
        TestRF = dict(
            lat=origin.lat,
            lon=origin.lon,
            depth=2. * km,
            width=1. * km,
            length=3. * km,
            rake=uniform(-90., 90.),
            dip=uniform(0., 90.),
            strike=uniform(0., 360.),
            slip=uniform(1., 5.))

        source_plain = gf.RectangularSource(
            aggressive_oversampling=True,
            **TestRF)

        N, E = num.meshgrid(num.linspace(-20. * km, 20. * km, nnorth),
                            num.linspace(-20. * km, 20. * km, neast))

        starget_ml = gf.StaticTarget(
            lats=num.full(N.size, origin.lat),
            lons=num.full(N.size, origin.lon),
            north_shifts=N.flatten(),
            east_shifts=E.flatten(),
            interpolation='multilinear')

        # Getting reference gf_distance_sampling = 10.

        def get_displacements(source):
            store_dir, c = self.get_pscmp_store_info()
            engine = gf.LocalEngine(store_dirs=[store_dir])
            r = engine.process(source, starget_ml)
            ref_result = r.static_results()[0]

            compare_results = {}
            for gf_dist_spacing in (0.25, .5, 1., 2., 4., 8., 10.,):
                extra_config = psgrn_pscmp.PsGrnPsCmpConfig()
                extra_config.psgrn_config.gf_distance_spacing = gf_dist_spacing
                extra_config.psgrn_config.gf_depth_spacing = .5

                store_dir, c = self._create_psgrn_pscmp_store(extra_config)
                engine = gf.LocalEngine(store_dirs=[store_dir])
                t0 = time()
                r = engine.process(source, starget_ml)
                logger.info('pyrocko stacking time %f s' % (time() - t0))

                static_result = r.static_results()[0]
                compare_results[gf_dist_spacing] = static_result

                num.testing.assert_allclose(
                    ref_result.result['displacement.n'],
                    static_result.result['displacement.n'],
                    atol=1*mm)
                num.testing.assert_allclose(
                    ref_result.result['displacement.e'],
                    static_result.result['displacement.e'],
                    atol=1*mm)
                num.testing.assert_allclose(
                    ref_result.result['displacement.d'],
                    static_result.result['displacement.d'],
                    atol=1*mm)

            return ref_result, compare_results

        # ref_result, compare_results = get_displacements(source_plain)
        # self.plot_displacement_differences(ref_result, compare_results)

        import matplotlib.pyplot as plt

        fig = plt.figure()
        ax = fig.gca()

        for depth in (2., 4., 8., 12.):
            source_plain.depth = depth * km
            ref_result, compare_results = get_displacements(source_plain)
            self.plot_differences(
                ax, ref_result, compare_results,
                label='Source Depth %.2f km' % depth)

        ax.legend()

        if show_plot:
            plt.show()

    def plot_displacement_differences(self, reference, compare):
        import matplotlib.pyplot as plt

        ncompare = len(compare)
        fig, axes = plt.subplots(ncompare + 1, 1)

        ax = axes[0]
        ref_displ = reference.result['displacement.d'].reshape(nnorth, neast)
        ax.imshow(ref_displ, cmap='seismic')
        ax.set_title('Reference displacement')

        for (gf_distance, comp), ax in zip(compare.items(), axes[1:]):
            displ = comp.result['displacement.d'].reshape(nnorth, neast)
            displ -= ref_displ
            ax.imshow(displ, cmap='seismic')
            ax.set_title('GF Distance %.2f' % gf_distance)

        ax.legend()
        if show_plot:
            plt.show()

    def plot_differences(self, ax, reference, compare, **kwargs):
        for key, comp in compare.items():
            print(key, comp.result['displacement.n'].shape)

        ref_displ = num.linalg.norm(tuple(reference.result.values()), axis=0)

        differences = num.array([
            num.linalg.norm(tuple(comp.result.values()), axis=0)
            for comp in compare.values()])

        differences = num.abs(differences)
        differences /= num.abs(ref_displ)
        differences -= 1.

        ax.plot(tuple(compare.keys()), differences.max(axis=1)*100., **kwargs)
        ax.set_ylabel('% Difference')
        ax.set_xlabel('gf_distance_spacing [km]')
        # ax.xaxis.set_major_formatter(
        #     FuncFormatter(lambda x, v: '%.1f%' % v))
        # ax.set_xticks(tuple(compare.keys()))
        ax.grid(alpha=.3)
        return ax


if __name__ == '__main__':
    util.setup_logging('test_gf_psgrn_pscmp', 'info')
    unittest.main()
