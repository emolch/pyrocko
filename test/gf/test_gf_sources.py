from __future__ import division, print_function, absolute_import
import sys
import math
import unittest
import numpy as num
from tempfile import mkdtemp
import shutil

from pyrocko import gf, util, guts, cake, moment_tensor as pmt

r2d = 180. / math.pi
d2r = 1.0 / r2d
km = 1000.


def numeq(a, b, eps):
    return (num.all(num.asarray(a).shape == num.asarray(b).shape and
            num.abs(num.asarray(a) - num.asarray(b)) < eps))


def default_source(S, **kwargs):
    if S is not gf.CombiSource:
        return S(**kwargs)
    else:
        return S([gf.MTSource(**kwargs)])


class GFSourcesTestCase(unittest.TestCase):
    tempdirs = []

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        self._dummy_store = None
        self._dummy_homogeneous_store = None

    @classmethod
    def tearDownClass(cls):
        for d in cls.tempdirs:
            shutil.rmtree(d)

    if sys.version_info < (2, 7):
        from contextlib import contextmanager

        @contextmanager
        def assertRaises(self, exc):

            gotit = False
            try:
                yield None
            except exc:
                gotit = True

            assert gotit, 'expected to get a %s exception' % exc

        def assertIsNone(self, value):
            assert value is None, 'expected None but got %s' % value

    def test_source_to_event(self):

        def stype(x):
            return x.__class__.__name__

        for S in gf.source_classes:
            if S is gf.CombiSource:
                continue

            stf = gf.TriangularSTF(effective_duration=2.0)
            s1 = S(lat=10., lon=20., depth=1000.,
                   north_shift=500., east_shift=500., stf=stf)
            ev = s1.pyrocko_event()

            try:
                s1_mag = s1.get_magnitude()
                mess = ''
            except (gf.DerivedMagnitudeError, NotImplementedError) as e:
                s1_mag = 'N/A'
                mess = '* %s *' % e

            if ev.magnitude is not None:
                ev_mag = ev.magnitude
            else:
                ev_mag = 'N/A'

            assert ev.lat == s1.lat
            assert ev.lon == s1.lon
            assert ev.north_shift == s1.north_shift
            assert ev.east_shift == s1.east_shift

            s2 = S.from_pyrocko_event(ev)

            assert ev.lat == s2.lat
            assert ev.lon == s2.lon
            assert ev.north_shift == s2.north_shift
            assert ev.east_shift == s2.east_shift

            if ev.moment_tensor:
                mt_mag = ev.moment_tensor.magnitude
            else:
                mt_mag = 'N/A'

            try:
                s2_mag = s2.get_magnitude()
                mess = ''
            except (gf.DerivedMagnitudeError, NotImplementedError) as e:
                s2_mag = 'N/A'
                mess = '* %s *' % e

            # print(
            #     stype(s1).ljust(32),
            #     s1_mag,
            #     ev.magnitude or 'N/A',
            #     mt_mag,
            #     s2_mag,
            #     mess)

            del mess

            def assert_mag_eq(mag1, mag2):
                if 'N/A' not in (mag1, mag2):
                    num.testing.assert_approx_equal(mag1, mag2)

            assert_mag_eq(s1_mag, ev_mag)
            assert_mag_eq(s1_mag, mt_mag)
            assert_mag_eq(s1_mag, s2_mag)

            if not isinstance(s1, gf.DoubleDCSource):
                assert numeq(
                    [s1.effective_lat, s1.effective_lon,
                     s1.depth, s1.stf.effective_duration],
                    [s2.effective_lat, s2.effective_lon,
                     s2.depth, s2.stf.effective_duration], 0.001)
            else:
                assert numeq(
                    [s1.effective_lat, s1.effective_lon,
                     s1.depth, s1.stf.effective_duration],
                    [s2.effective_lat, s2.effective_lon,
                     s2.depth, s2.stf1.effective_duration], 0.001)

    def test_source_dict(self):
        s1 = gf.DCSource(strike=0.)
        s1.strike = 10.
        s2 = s1.clone(strike=20.)
        s2.update(strike=30.)
        s2['strike'] = 40.
        d = dict(s2)
        s3 = gf.DCSource(**d)
        s3.strike

    def test_sgrid(self):

        r = gf.Range

        source = gf.DCSource()
        sgrid = source.grid(rake=r(-10, 10, 1),
                            strike=r(-100, 100, n=21),
                            depth=r('0k .. 100k : 10k'),
                            magnitude=r(1, 2, 1))

        sgrid = guts.load_string(sgrid.dump())

        n = len(sgrid)
        i = 0
        for source in sgrid:
            i += 1

        assert i == n

    def test_sgrid2(self):
        expect = [10., 12., 14., 16., 18., 20.]
        source = gf.DCSource()
        sgrid = source.grid(dip=gf.Range(10, 20, 2))
        dips = []
        for source in sgrid:
            dips.append(source.dip)

        num.testing.assert_array_almost_equal(
            dips, expect)

        source = gf.DCSource(dip=10)
        sgrid = source.grid(dip=gf.Range(1, 2, 0.2, relative='mult'))
        dips = []
        for source in sgrid:
            dips.append(source.dip)

        num.testing.assert_array_almost_equal(
            dips, expect)

    def dummy_store(self):
        if self._dummy_store is None:

            conf = gf.ConfigTypeA(
                id='empty_regional',
                source_depth_min=0.,
                source_depth_max=20*km,
                source_depth_delta=10*km,
                distance_min=1000*km,
                distance_max=2000*km,
                distance_delta=10*km,
                sample_rate=2.0,
                ncomponents=10,
                earthmodel_1d=cake.load_model(crust2_profile=(50., 10.)))

            store_dir = mkdtemp(prefix='gfstore')
            self.tempdirs.append(store_dir)

            gf.Store.create(store_dir, config=conf)
            self._dummy_store = gf.Store(store_dir)

        return self._dummy_store

    def dummy_homogeneous_store(self):
        mod = cake.LayeredModel.from_scanlines(
            cake.read_nd_model_str('''
0 6 3.46  3.0  1000 500
20 6 3.46  3.0  1000 500
'''.lstrip()))

        if self._dummy_homogeneous_store is None:

            conf = gf.ConfigTypeA(
                id='empty_homogeneous',
                source_depth_min=0.,
                source_depth_max=20*km,
                source_depth_delta=10*km,
                distance_min=1000*km,
                distance_max=2000*km,
                distance_delta=10*km,
                sample_rate=2.0,
                ncomponents=10,
                earthmodel_1d=mod)

            store_dir = mkdtemp(prefix='gfstore')
            self.tempdirs.append(store_dir)

            gf.Store.create(store_dir, config=conf)
            self._dummy_homogeneous_store = gf.Store(store_dir)

        return self._dummy_homogeneous_store

    def test_combine_dsources(self):
        store = self.dummy_store()
        dummy_target = gf.Target()
        for S in gf.source_classes:
            if not hasattr(S, 'discretize_basesource'):
                continue

            for lats in [[10., 10., 10.], [10., 11., 12.]]:
                sources = [
                    default_source(
                        S,
                        lat=lat, lon=20., depth=1000.,
                        north_shift=500., east_shift=500.)

                    for lat in lats]

                dsources = [
                    s.discretize_basesource(store, target=dummy_target)
                    for s in sources]

                DS = dsources[0].__class__

                dsource = DS.combine(dsources)
                assert dsource.nelements == sum(s.nelements for s in dsources)

    def test_source_times(self):
        store = self.dummy_store()
        dummy_target = gf.Target()
        for S in gf.source_classes:
            if not hasattr(S, 'discretize_basesource'):
                continue

            if S.T.classname == 'PseudoDynamicRupture':
                continue

            for t in [0.0, util.str_to_time('2014-01-01 10:00:00')]:
                source = default_source(S, time=t)
                dsource = source.discretize_basesource(
                    store, target=dummy_target)
                cent = dsource.centroid()
                assert numeq(cent.time, t, 0.0001)

    def test_outline(self):
        s = gf.MTSource(
            east_shift=5. * km,
            north_shift=-3. * km,
            depth=7. * km)

        outline = s.outline()
        numeq(outline, num.array([[-3000., 5000., 7000.]]), 1e-8)

        rs = gf.RectangularSource(
            length=2 * km,
            width=2 * km)

        outline = rs.outline()
        numeq(
            outline,
            num.array(
                [[-1.e3, 0.0, 0.0],
                 [1.e3, 0.0, 0.0],
                 [1.e3, 0.0, 2.e3],
                 [-1.e3, 0.0, 2.e3],
                 [-1.e3, 0.0, 0.0]]),
            1e-8)

    def test_rect_source_anchors(self):
        sources = {}
        for anchor in ['top', 'center', 'bottom']:
            sources[anchor] = gf.RectangularSource(
                width=5 * km,
                length=20 * km,
                anchor=anchor,
                dip=120.,
                strike=45.,
                east_shift=0 * km,
                north_shift=0 * km)

        def plot_sources(sources):
            import matplotlib.pyplot as plt
            fig = plt.figure()
            ax = fig.gca()
            colors = ['b', 'r', 'y']
            for i, src in enumerate(sources.itervalues()):
                n, e = src.outline(cs='xy').T
                ax.fill(e, n, color=colors[i], alpha=0.5)
            plt.show()

        # plot_sources(sources)

    def test_explosion_source(self):

        target = gf.Target(
            interpolation='nearest_neighbor')

        ex = gf.ExplosionSource(
            magnitude=5.,
            volume_change=4.,
            depth=5 * km)

        with self.assertRaises(gf.DerivedMagnitudeError):
            ex.validate()

        ex = gf.ExplosionSource(
            depth=5 * km)

        ex.validate()

        self.assertEqual(ex.get_moment(), 1.0)

        # magnitude input
        magnitude = 3.
        ex = gf.ExplosionSource(
            magnitude=magnitude,
            depth=5 * km)

        store = self.dummy_store()

        with self.assertRaises(gf.DerivedMagnitudeError):
            ex.get_volume_change()

        volume_change = ex.get_volume_change(
            store, target)

        self.assertAlmostEqual(
            ex.get_magnitude(store, target), magnitude)

        # validate with MT source
        moment = ex.get_moment(store, target) * float(num.sqrt(2. / 3))

        mt = gf.MTSource(mnn=moment, mee=moment, mdd=moment)

        self.assertAlmostEqual(
            ex.get_magnitude(store, target),
            mt.get_magnitude(store=store, target=target))

        # discretized sources
        d_ex = ex.discretize_basesource(store=store, target=target)
        d_mt = mt.discretize_basesource(store=store, target=target)

        d_ex_m6s = d_ex.get_source_terms('elastic10')
        d_mt_m6s = d_mt.get_source_terms('elastic10')

        numeq(d_ex_m6s, d_mt_m6s, 1e-20)

        # interpolation method
        with self.assertRaises(TypeError):
            ex.get_volume_change(
                store, gf.Target(interpolation='nearest_neighbour'))

        # volume change input
        ex = gf.ExplosionSource(
            volume_change=volume_change,
            depth=5 * km)

        self.assertAlmostEqual(
            ex.get_magnitude(store, target), 3.0)

        ex = gf.ExplosionSource(
            magnitude=3.0,
            depth=-5.)

        with self.assertRaises(gf.DerivedMagnitudeError):
            ex.get_volume_change(store, target)

    def test_rect_source(self):

        store = self.dummy_homogeneous_store()

        depth = 10 * km
        # shear
        rect1 = gf.RectangularSource(
            depth=10*km,
            magnitude=5.0,
            width=5*km,
            length=5*km)

        rect2 = gf.RectangularSource(
            depth=depth,
            slip=pmt.magnitude_to_moment(5.0) / (
                5*km * 5*km * store.config.earthmodel_1d.material(
                    depth).shear_modulus()),
            width=5*km,
            length=5*km)

        self.assertAlmostEqual(
            rect1.get_magnitude(),
            rect2.get_magnitude(
                store, gf.Target(interpolation='nearest_neighbor')))

        # tensile
        rect3 = gf.RectangularSource(
            depth=depth,
            magnitude=5.0,
            width=5*km,
            length=5*km,
            opening_fraction=1.)

        rect4 = gf.RectangularSource(
            depth=depth,
            slip=pmt.magnitude_to_moment(5.0) / (
                5*km * 5*km * store.config.earthmodel_1d.material(
                    depth).bulk()),
            width=5*km,
            length=5*km,
            opening_fraction=1.)

        self.assertAlmostEqual(
            rect3.get_magnitude(),
            rect4.get_magnitude(
                store, gf.Target(interpolation='nearest_neighbor')))

        # mixed
        of = -0.4
        rect5 = gf.RectangularSource(
            depth=depth,
            magnitude=5.0,
            width=5*km,
            length=5*km,
            opening_fraction=of)

        rect6 = gf.RectangularSource(
            depth=depth,
            slip=pmt.magnitude_to_moment(5.0) / (
                5*km * 5*km * (
                    store.config.earthmodel_1d.material(
                        depth).bulk() * abs(of) +
                    store.config.earthmodel_1d.material(
                        depth).shear_modulus() * (1 - abs(of)))),
            width=5*km,
            length=5*km,
            opening_fraction=of)

        self.assertAlmostEqual(
            rect5.get_magnitude(),
            rect6.get_magnitude(
                store, gf.Target(interpolation='nearest_neighbor')))

    def test_discretize_rect_source(self):

        store = self.dummy_homogeneous_store()
        target = gf.Target(interpolation='nearest_neighbor')

        for source in [
                gf.RectangularSource(
                    depth=10*km,
                    slip=0.5,
                    width=5*km,
                    length=5*km),
                gf.RectangularSource(
                    depth=10*km,
                    magnitude=5.0,
                    width=5*km,
                    length=5*km,
                    decimation_factor=2)]:

            dsource = source.discretize_basesource(store, target)
            m1 = source.get_moment(store, target)
            m2 = dsource.centroid().pyrocko_moment_tensor().scalar_moment()
            assert abs(m1 - m2) < abs(m1 + m2) * 1e-6

    def test_discretize_rect_source_stf(self):

        store = self.dummy_homogeneous_store()
        target = gf.Target(interpolation='nearest_neighbor')
        stf = gf.HalfSinusoidSTF(duration=3.)

        for source in [
                gf.RectangularSource(
                    depth=10*km,
                    slip=0.5,
                    width=5*km,
                    length=5*km,
                    stf=stf,
                    stf_mode='pre'),
                gf.RectangularSource(
                    depth=10*km,
                    magnitude=5.0,
                    width=5*km,
                    length=5*km,
                    decimation_factor=2,
                    stf=stf,
                    stf_mode='pre')]:

            dsource = source.discretize_basesource(store, target)
            amplitudes = source._discretize(store, target)[2]
            assert amplitudes[0] != amplitudes[1]

            m1 = source.get_moment(store, target)
            m2 = dsource.centroid().pyrocko_moment_tensor().scalar_moment()
            assert abs(m1 - m2) < abs(m1 + m2) * 1e-6


if __name__ == '__main__':
    util.setup_logging('test_gf_sources', 'warning')
    unittest.main()
