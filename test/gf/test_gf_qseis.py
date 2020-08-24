from __future__ import division, print_function, absolute_import

import random
import math
import unittest
import logging
from tempfile import mkdtemp
import shutil

import numpy as num

from ..common import Benchmark
from multiprocessing import cpu_count

from pyrocko import util, trace, gf, cake  # noqa
from pyrocko.fomosto import qseis, ahfullgreen

logger = logging.getLogger('pyrocko.test.test_gf_qseis')
benchmark = Benchmark()

km = 1000.

r2d = 180. / math.pi
d2r = 1.0 / r2d


def rand(mi, ma):
    return mi + random.random() * (ma-mi)


def g(trs, cha):
    for tr in trs:
        if tr.channel == cha:
            return tr


@unittest.skipUnless(
    qseis.have_backend(), 'backend qseis not available')
class GFQSeisTestCase(unittest.TestCase):

    tempdirs = []

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)

    @classmethod
    def tearDownClass(cls):
        for d in cls.tempdirs:
            shutil.rmtree(d)

    def test_pyrocko_gf_vs_qseis(self):
        random.seed(2017)

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
            sample_rate=0.25,
            receiver_depth=0.*km,
            source_depth_min=10*km,
            source_depth_max=10*km,
            source_depth_delta=1*km,
            distance_min=550*km,
            distance_max=560*km,
            distance_delta=1*km,
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

        try:
            qseis.build(store_dir, nworkers=1)
        except qseis.QSeisError as e:
            if str(e).find('could not start qseis') != -1:
                logger.warn('qseis not installed; '
                            'skipping test_pyrocko_gf_vs_qseis')
                return
            else:
                raise

        source = gf.MTSource(
            lat=0.,
            lon=0.,
            depth=10.*km)

        source.m6 = tuple(random.random()*2.-1. for x in range(6))

        azi = random.random()*365.
        dist = 553.*km

        dnorth = dist * math.cos(azi*d2r)
        deast = dist * math.sin(azi*d2r)

        targets = []
        for cha in 'rtz':
            target = gf.Target(
                quantity='displacement',
                codes=('', '0000', 'PG', cha),
                north_shift=dnorth,
                east_shift=deast,
                depth=config.receiver_depth,
                store_id='qseis_test')

            dist = source.distance_to(target)
            azi, bazi = source.azibazi_to(target)

            if cha == 'r':
                target.azimuth = bazi + 180.
                target.dip = 0.
            elif cha == 't':
                target.azimuth = bazi - 90.
                target.dip = 0.
            elif cha == 'z':
                target.azimuth = 0.
                target.dip = 90.

            targets.append(target)

        runner = qseis.QSeisRunner()
        conf = qseis.QSeisConfigFull()
        conf.qseis_version = '2006a'
        conf.receiver_distances = [dist/km]
        conf.receiver_azimuths = [azi]
        conf.source_depth = source.depth/km
        conf.time_start = 0.0
        conf.time_window = 508.
        conf.time_reduction_velocity = 0.0
        conf.nsamples = 128
        conf.source_mech = qseis.QSeisSourceMechMT(
            mnn=source.mnn,
            mee=source.mee,
            mdd=source.mdd,
            mne=source.mne,
            mnd=source.mnd,
            med=source.med)
        conf.earthmodel_1d = mod

        conf.sw_flat_earth_transform = 0

        runner.run(conf)

        trs = runner.get_traces()
        for tr in trs:
            tr.shift(-config.deltat)
            tr.snap(interpolate=True)
            tr.lowpass(4, 0.05)
            tr.highpass(4, 0.01)

        engine = gf.LocalEngine(store_dirs=[store_dir])

        def process_wrap(nthreads=0):
            @benchmark.labeled('pyrocko.gf.process (nthreads-%d)' % nthreads)
            def process(nthreads):
                return engine.process(source, targets, nthreads=nthreads)\
                    .pyrocko_traces()
            return process(nthreads)

        for nthreads in range(1, cpu_count()+1):
            trs2 = process_wrap(nthreads)
        # print benchmark

        for tr in trs2:
            tr.snap(interpolate=True)
            tr.lowpass(4, 0.05)
            tr.highpass(4, 0.01)

        # trace.snuffle(trs+trs2)

        for cha in 'rtz':
            t1 = g(trs, cha)
            t2 = g(trs2, cha)
            tmin = max(t1.tmin, t2.tmin)
            tmax = min(t1.tmax, t2.tmax)
            t1.chop(tmin, tmax)
            t2.chop(tmin, tmax)
            d = 2.0 * num.sum((t1.ydata - t2.ydata)**2) / \
                (num.sum(t1.ydata**2) + num.sum(t2.ydata**2))

            assert d < 0.05

    def test_qseis_vs_ahfull(self):
        random.seed(23)

        vp = 5.8 * km
        vs = 3.46 * km

        mod = cake.LayeredModel.from_scanlines(cake.read_nd_model_str('''
  0. %(vp)g %(vs)g 2.6 1264. 600.
 20. %(vp)g %(vs)g 2.6 1264. 600.'''.lstrip() % dict(vp=vp/km, vs=vs/km)))

        store_id_qseis = 'homogeneous_qseis'
        store_id_ahfull = 'homogeneous_ahfull'

        ahconf = ahfullgreen.AhfullgreenConfig()

        qsconf = qseis.QSeisConfig()
        qsconf.qseis_version = '2006a'

        textra = 5.0

        qsconf.time_region = (
            gf.meta.Timing('{vel:%g}-%g' % (vp/km, textra)),
            gf.meta.Timing('{vel:%g}+%g' % (vs/km, textra)))

        qsconf.cut = (
            gf.meta.Timing('{vel:%g}-%g' % (vp/km, textra)),
            gf.meta.Timing('{vel:%g}+%g' % (vs/km, textra)))

        qsconf.relevel_with_fade_in = True

        qsconf.fade = (
            gf.meta.Timing('{vel:%g}-%g' % (vp/km, textra)),
            gf.meta.Timing('{vel:%g}-%g' % (vp/km, 0.)),
            gf.meta.Timing('{vel:%g}+%g' % (vs/km, 0.)),
            gf.meta.Timing('{vel:%g}+%g' % (vs/km, textra)))

        qsconf.wavelet_duration_samples = 0.001
        qsconf.sw_flat_earth_transform = 0
        qsconf.filter_surface_effects = 1
        qsconf.wavenumber_sampling = 5.
        qsconf.aliasing_suppression_factor = 0.01

        sample_rate = 10.

        config = gf.meta.ConfigTypeA(
            id=store_id_qseis,
            sample_rate=sample_rate,
            receiver_depth=0.*km,
            source_depth_min=1.*km,
            source_depth_max=19*km,
            source_depth_delta=6.*km,
            distance_min=2.*km,
            distance_max=20*km,
            distance_delta=2*km,
            modelling_code_id='qseis.2006a',
            earthmodel_1d=mod,
            tabulated_phases=[
                gf.meta.TPDef(
                    id='begin',
                    definition='p,P,p\\,P\\'),
                gf.meta.TPDef(
                    id='end',
                    definition='s,S,s\\,S\\'),
            ])

        config.validate()

        store_dir_qseis = mkdtemp(prefix=store_id_qseis)
        self.tempdirs.append(store_dir_qseis)

        gf.store.Store.create_editables(
            store_dir_qseis, config=config, extra={'qseis': qsconf})

        store = gf.store.Store(store_dir_qseis, 'r')
        store.make_ttt()
        store.close()

        try:
            qseis.build(store_dir_qseis, nworkers=1)
        except qseis.QSeisError as e:
            if str(e).find('could not start qseis') != -1:
                logger.warn('qseis not installed; '
                            'skipping test_pyrocko_gf_vs_qseis')
                return
            else:
                raise

        config = gf.meta.ConfigTypeA(
            id=store_id_ahfull,
            sample_rate=sample_rate,
            receiver_depth=0.*km,
            source_depth_min=1.*km,
            source_depth_max=19*km,
            source_depth_delta=6.*km,
            distance_min=2.*km,
            distance_max=20*km,
            distance_delta=2*km,
            modelling_code_id='ahfullgreen',
            earthmodel_1d=mod,
            tabulated_phases=[
                gf.meta.TPDef(
                    id='begin',
                    definition='p,P,p\\,P\\'),
                gf.meta.TPDef(
                    id='end',
                    definition='s,S,s\\,S\\'),
            ])

        config.validate()

        store_dir_ahfull = mkdtemp(prefix=store_id_qseis)
        self.tempdirs.append(store_dir_ahfull)

        gf.store.Store.create_editables(
            store_dir_ahfull, config=config, extra={'ahfullgreen': ahconf})

        store = gf.store.Store(store_dir_ahfull, 'r')
        store.make_ttt()
        store.close()

        ahfullgreen.build(store_dir_ahfull, nworkers=1)

        sdepth = rand(config.source_depth_min, config.source_depth_max)
        sdepth = round(
            (sdepth - config.source_depth_min)
            / config.source_depth_delta) * config.source_depth_delta \
            + config.source_depth_min

        source = gf.MTSource(
            lat=0.,
            lon=0.,
            depth=sdepth)

        source.m6 = tuple(rand(-1., 1.) for x in range(6))

        for ii in range(5):
            azi = random.random()*365.
            dist = rand(config.distance_min, config.distance_max)
            dist = round(dist / config.distance_delta) * config.distance_delta

            dnorth = dist * math.cos(azi*d2r)
            deast = dist * math.sin(azi*d2r)

            targets = []
            for cha in 'rtz':
                target = gf.Target(
                    quantity='displacement',
                    codes=('', '0000', 'PG', cha),
                    north_shift=dnorth,
                    east_shift=deast,
                    depth=config.receiver_depth,
                    store_id=store_id_ahfull)

                dist = source.distance_to(target)
                azi, bazi = source.azibazi_to(target)

                if cha == 'r':
                    target.azimuth = bazi + 180.
                    target.dip = 0.
                elif cha == 't':
                    target.azimuth = bazi - 90.
                    target.dip = 0.
                elif cha == 'z':
                    target.azimuth = 0.
                    target.dip = 90.

                targets.append(target)

            runner = qseis.QSeisRunner()
            conf = qseis.QSeisConfigFull()
            conf.qseis_version = '2006a'
            conf.receiver_distances = [dist/km]
            conf.receiver_azimuths = [azi]
            conf.receiver_depth = config.receiver_depth / km
            conf.source_depth = source.depth / km

            distance_3d_max = math.sqrt(
                config.distance_max**2 + (
                    config.source_depth_max - config.source_depth_min)**2)

            nsamples = trace.nextpow2(
                int(math.ceil(
                    distance_3d_max / vs * 2.0 + 2.*textra)
                    * config.sample_rate))

            conf.time_start = -textra
            conf.time_window = (nsamples-1) / config.sample_rate
            conf.time_reduction_velocity = 0.0
            conf.nsamples = nsamples
            conf.source_mech = qseis.QSeisSourceMechMT(
                mnn=source.mnn,
                mee=source.mee,
                mdd=source.mdd,
                mne=source.mne,
                mnd=source.mnd,
                med=source.med)
            conf.earthmodel_1d = mod

            conf.sw_flat_earth_transform = 0
            conf.filter_surface_effects = 1
            conf.wavenumber_sampling = 10.
            conf.wavelet_duration_samples = 0.001
            conf.aliasing_suppression_factor = 0.01

            conf.validate()

            runner.run(conf)

            trs = runner.get_traces()
            for tr in trs:
                pass
                tr.lowpass(4, config.sample_rate / 8., demean=False)
                tr.highpass(4, config.sample_rate / 80.)

            engine = gf.LocalEngine(store_dirs=[
                store_dir_ahfull, store_dir_qseis])

            trs2 = engine.process(source, targets).pyrocko_traces()
            for tr in trs2:
                tr.shift(config.deltat)
                tr.lowpass(4, config.sample_rate / 8., demean=False)
                tr.highpass(4, config.sample_rate / 80.)

            # trace.snuffle(trs+trs2)

            tmin = store.t(
                '{vel:%g}' % (vp/km), source, target) - textra*0.2
            tmax = store.t(
                '{vel:%g}' % (vs/km), source, target) + textra*0.2

            for tr in trs + trs2:
                tr.chop(tmin, tmax)

            denom = 0.0
            for cha in 'rtz':
                t1 = g(trs, cha)
                t2 = g(trs2, cha)
                denom += num.sum(t1.ydata**2) + num.sum(t2.ydata**2)

            ds = []
            for cha in 'rtz':
                t1 = g(trs, cha)
                t2 = g(trs2, cha)
                ds.append(2.0 * num.sum((t1.ydata - t2.ydata)**2) / denom)

            ds = num.array(ds)

            # if not num.all(ds < 0.05):
            #    trace.snuffle(trs+trs2)

            assert num.all(ds < 0.05)


if __name__ == '__main__':
    util.setup_logging('test_gf_qseis', 'warning')
    unittest.main()
