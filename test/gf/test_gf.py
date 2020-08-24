from __future__ import division, print_function, absolute_import

import time
import sys
import random
import math
import unittest
import logging
import numpy as num
import shutil
from tempfile import mkdtemp

from pyrocko import guts
from pyrocko import gf, util, cake, ahfullgreen, trace
from pyrocko.fomosto import ahfullgreen as fomosto_ahfullgreen

from ..common import Benchmark

assert_ae = num.testing.assert_almost_equal


logger = logging.getLogger('pyrocko.test.test_gf')
benchmark = Benchmark()

local_stores = gf.LocalEngine(use_config=True).get_store_ids()

r2d = 180. / math.pi
d2r = 1.0 / r2d
km = 1000.


def arr(x):
    return num.asarray(x, dtype=num.float)


def numeq(a, b, eps):
    return (num.all(num.asarray(a).shape == num.asarray(b).shape and
            num.abs(num.asarray(a) - num.asarray(b)) < eps))


def _make_traces_homogeneous(
        dsource, receiver, material, deltat, net, sta, loc):

    comps = ['displacement.n', 'displacement.e', 'displacement.d']
    npad = 120

    dists = dsource.distances_to(receiver)

    dists = dsource.distances_to(receiver)
    azis, _ = dsource.azibazis_to(receiver)

    norths = dists * num.cos(azis*d2r)
    easts = dists * num.sin(azis*d2r)

    ddepths = receiver.depth - dsource.depths

    d3ds = num.sqrt(norths**2 + easts**2 + ddepths**2)
    times = dsource.times
    toff = math.floor(num.min(times) / deltat) * deltat

    tmin = num.min(
        (num.floor(times + d3ds / material.vp / deltat) - npad) * deltat)
    tmax = num.max(
        (num.ceil(times + d3ds / material.vs / deltat) + npad) * deltat)

    ns = int(round((tmax - tmin) / deltat))

    outx = num.zeros(ns)
    outy = num.zeros(ns)
    outz = num.zeros(ns)

    traces = []
    for ielement in range(dsource.nelements):
        x = (norths[ielement], easts[ielement], ddepths[ielement])

        if isinstance(dsource, gf.DiscretizedMTSource):
            m6 = dsource.m6s[ielement, :]
            f = (0., 0., 0.)
        elif isinstance(dsource, gf.DiscretizedSFSource):
            m6 = (0., 0., 0., 0., 0., 0.)
            f = dsource.forces[ielement, :]
        elif isinstance(dsource, gf.DiscretizedExplosionSource):
            m0 = dsource.m0s[ielement]
            m6 = (m0, m0, m0, 0., 0., 0.)
            f = (0., 0., 0.)
        else:
            assert False

        ahfullgreen.add_seismogram(
            material.vp, material.vs, material.rho, material.qp, material.qs,
            x, f, m6, 'displacement',
            deltat, tmin - (times[ielement] - toff), outx, outy, outz,
            stf=ahfullgreen.AhfullgreenSTFImpulse())

    for comp, o in zip(comps, (outx, outy, outz)):
        tr = trace.Trace(
            net, sta, loc, comp,
            tmin=tmin + toff, ydata=o, deltat=deltat)

        traces.append(tr)

    return traces


class PulseConfig(guts.Object):
    fwhm = guts.Float.T(default=0.02)
    velocity = guts.Float.T(default=1000.)

    def evaluate(self, distance, t):
        tarr = distance / self.velocity
        denom = self.fwhm / (2.*math.sqrt(math.log(2.)))
        return num.exp(-((t-tarr)/denom)**2)


class GFTestCase(unittest.TestCase):

    tempdirs = []

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

    @classmethod
    def setUpClass(cls):
        cls.pulse_store_dir = None
        cls.regional_ttt_store_dir = {}
        cls.benchmark_store_dir = None
        cls._dummy_store = None

    @classmethod
    def tearDownClass(cls):
        for d in cls.tempdirs:
            shutil.rmtree(d)

    def create(self, deltat=1.0, nrecords=10):
        d = mkdtemp(prefix='gfstore')
        store = gf.BaseStore.create(d, deltat, nrecords, force=True)

        store = gf.BaseStore(d, mode='w')
        for i in range(nrecords):
            data = num.asarray(num.random.random(random.randint(0, 7)),
                               dtype=gf.gf_dtype)

            tr = gf.GFTrace(data=data, itmin=1+i)
            store.put(i, tr)

        store.close()
        self.tempdirs.append(d)
        return d

    def get_pulse_store_dir(self):
        if self.pulse_store_dir is None:
            self.pulse_store_dir = self._create_pulse_store()

        return self.pulse_store_dir

    def get_regional_ttt_store_dir(self, typ='a'):
        if typ not in self.regional_ttt_store_dir:
            self.regional_ttt_store_dir[typ] = \
                self._create_regional_ttt_store(typ)

        return self.regional_ttt_store_dir[typ]

    def get_benchmark_store_dir(self):
        if self.benchmark_store_dir is None:
            self.benchmark_store_dir = self._create_benchmark_store()

        return self.benchmark_store_dir

    def _create_benchmark_store(self):
        conf = gf.ConfigTypeA(
            id='benchmark_store',
            source_depth_min=0.,
            source_depth_max=2.,
            source_depth_delta=1.,
            distance_min=1.0,
            distance_max=5001.0,
            distance_delta=5.0,
            sample_rate=2.0,
            ncomponents=5)

        deltat = 1.0/conf.sample_rate

        store_dir = mkdtemp(prefix='gfstore')
        self.tempdirs.append(store_dir)

        gf.Store.create(store_dir, config=conf)
        store = gf.Store(store_dir, 'w')
        for args in conf.iter_nodes():
            nsamples = int(round(args[1]))
            data = num.ones(nsamples)
            itmin = int(round(args[1]))
            tr = gf.GFTrace(data=data, itmin=itmin, deltat=deltat)
            store.put(args, tr)

        store.close()
        return store_dir

    def _create_regional_ttt_store(self, typ):

        if typ == 'a':
            conf = gf.ConfigTypeA(
                id='empty_regional',
                source_depth_min=0.,
                source_depth_max=20*km,
                source_depth_delta=10*km,
                distance_min=10*km,
                distance_max=2000*km,
                distance_delta=10*km,
                sample_rate=2.0,
                ncomponents=10,
                earthmodel_1d=cake.load_model(),
                tabulated_phases=[
                    gf.TPDef(id=id, definition=defi) for (id, defi) in [
                        ('depthp', 'p'),
                        ('pS', 'pS'),
                        ('P', 'P'),
                        ('S', 'S')
                    ]
                ])

        elif typ == 'b':
            conf = gf.ConfigTypeB(
                id='empty_regional_b',
                receiver_depth_min=0.,
                receiver_depth_max=5*km,
                receiver_depth_delta=5*km,
                source_depth_min=0.,
                source_depth_max=20*km,
                source_depth_delta=10*km,
                distance_min=10*km,
                distance_max=2000*km,
                distance_delta=10*km,
                sample_rate=2.0,
                ncomponents=10,
                earthmodel_1d=cake.load_model(),
                tabulated_phases=[
                    gf.TPDef(id=id, definition=defi) for (id, defi) in [
                        ('depthp', 'p'),
                        ('pS', 'pS'),
                        ('P', 'P'),
                        ('S', 'S')
                    ]
                ])

        store_dir = mkdtemp(prefix='gfstore')
        self.tempdirs.append(store_dir)

        gf.Store.create(store_dir, config=conf)
        store = gf.Store(store_dir)
        store.make_ttt()

        store.close()
        return store_dir

    def _create_pulse_store(self):

        conf = gf.ConfigTypeB(
            id='pulse',
            receiver_depth_min=0.,
            receiver_depth_max=10.,
            receiver_depth_delta=10.,
            source_depth_min=0.,
            source_depth_max=1000.,
            source_depth_delta=10.,
            distance_min=10.,
            distance_max=1000.,
            distance_delta=10.,
            sample_rate=200.,
            ncomponents=2.,
            component_scheme='elastic2')

        pulse = PulseConfig()

        # fnyq_spatial = pulse.velocity / math.sqrt(conf.distance_delta**2 +
        #                                       conf.source_depth_delta**2)

        store_dir = mkdtemp(prefix='gfstore')
        self.tempdirs.append(store_dir)

        gf.Store.create(store_dir, config=conf, force=True,
                        extra={'pulse': pulse})

        deltat = conf.deltat

        store = gf.Store(store_dir, mode='w')
        for args in store.config.iter_nodes(level=-1):

            rdepth, sdepth, surfdist = args
            dist = math.sqrt((rdepth-sdepth)**2 + surfdist**2)

            tarr = dist / pulse.velocity

            tmin = tarr - 5 * pulse.fwhm
            tmax = tarr + 5 * pulse.fwhm
            itmin = int(num.floor(tmin/deltat))
            itmax = int(num.ceil(tmax/deltat))
            tmin = itmin * deltat
            tmax = itmax * deltat
            nsamples = itmax - itmin + 1

            t = tmin + num.arange(nsamples) * deltat

            data = pulse.evaluate(dist, t)

            phi = math.atan2(rdepth-sdepth, surfdist)
            data = [data*math.cos(phi), data*math.sin(phi)]
            for icomponent, data in enumerate(data):
                is_zero = num.all(data == 0.0)

                tr = gf.GFTrace(data=data, itmin=itmin, deltat=deltat,
                                is_zero=is_zero)

                store.put(args + (icomponent,), tr)

        store.close()
        return store_dir

    def test_get_spans(self):
        nrecords = 8
        random.seed(0)
        num.random.seed(0)

        store = gf.BaseStore(self.create(nrecords=nrecords))
        for i in range(nrecords):
            for deci in (1, 2, 3, 4):
                tr = store.get(i, decimate=deci)
                itmin, itmax = store.get_span(i, decimate=deci)
                self.assertEqual(tr.itmin, itmin)
                self.assertEqual(tr.data.size, itmax-itmin + 1)

        store.close()

    def test_get_shear_moduli(self):
        for typ in ['a', 'b']:
            store_dir = self.get_regional_ttt_store_dir(typ)
            store = gf.Store(store_dir)

            sample_points = num.empty((20, 3))
            sample_points[:, 2] = num.linspace(
                0, store.config.coords[0].max(), 20)

            for interp in ('nearest_neighbor', 'multilinear'):
                store.config.get_shear_moduli(
                    lat=0., lon=0.,
                    points=sample_points,
                    interpolation=interp)

    def test_partial_get(self):
        nrecords = 8
        random.seed(0)
        num.random.seed(0)

        store = gf.BaseStore(self.create(nrecords=nrecords))
        for deci in (1, 2, 3, 4):
            for i in range(0, nrecords):
                tra = store.get(i, decimate=deci, implementation='c')
                trb = store.get(i, decimate=deci, implementation='python')
                self.assertEqual(tra.itmin, trb.itmin)
                self.assertEqual(tra.data.size, trb.data.size)
                assert_ae(tra.data, trb.data)
                assert_ae(tra.begin_value, trb.begin_value)
                assert_ae(tra.end_value, trb.end_value)

                tr = tra

                itmin_gf, nsamples_gf = tr.itmin, tr.data.size
                for itmin in range(itmin_gf - nsamples_gf,
                                   itmin_gf + nsamples_gf+1):

                    for nsamples in range(0, nsamples_gf*3):
                        for implementation in ['c', 'python']:
                            tr2 = store.get(i, itmin, nsamples, decimate=deci)
                            self.assertEqual(tr2.itmin, max(tr.itmin, itmin))
                            self.assertEqual(tr2.itmin + tr2.data.size,
                                             max(min(tr.itmin + tr.data.size,
                                                     itmin + nsamples),
                                                 tr2.itmin + tr2.data.size))

                            ilo = max(tr.itmin, tr2.itmin)
                            ihi = min(tr.itmin+tr.data.size,
                                      tr2.itmin+tr2.data.size)

                            a = tr.data[ilo-tr.itmin:ihi-tr.itmin]
                            b = tr2.data[ilo-tr2.itmin:ihi-tr2.itmin]

                            self.assertTrue(numeq(a, b, 0.001))

        store.close()

    def test_sum(self):

        nrecords = 8
        random.seed(0)
        num.random.seed(0)

        store = gf.BaseStore(self.create(nrecords=nrecords))

        from pyrocko.gf import store_ext
        store.open()

        store_ext.store_mapping_init(
            store.cstore, 'type_0',
            arr([0]), arr([nrecords-1]), arr([1]),
            num.array([nrecords], dtype=num.uint64),
            1)

        for deci in (1, 2, 3, 4):
            for i in range(300):
                n = random.randint(0, 5)
                indices = num.random.randint(nrecords, size=n)
                weights = num.random.random(n)
                shifts = num.random.random(n)*nrecords
                shifts[::2] = num.round(shifts[::2])

                for itmin, nsamples in [(None, None),
                                        (random.randint(0, nrecords),
                                         random.randint(0, nrecords))]:

                    a = store.sum(
                        indices, shifts, weights,
                        itmin=itmin,
                        nsamples=nsamples,
                        decimate=deci)

                    b = store.sum(
                        indices, shifts, weights,
                        itmin=itmin,
                        nsamples=nsamples,
                        decimate=deci,
                        implementation='alternative')

                    c = store.sum(
                        indices, shifts, weights,
                        itmin=itmin,
                        nsamples=nsamples,
                        decimate=deci,
                        implementation='reference')

                    self.assertEqual(a.itmin, c.itmin)
                    num.testing.assert_array_almost_equal(
                        a.data, c.data, 2)

                    self.assertEqual(b.itmin, c.itmin)
                    num.testing.assert_array_almost_equal(
                        b.data, c.data, 2)

                    if deci != 1:
                        continue

                    nthreads = 1
                    source_coords = num.zeros((n, 5))
                    source_coords[:, 4] = indices
                    receiver_coords = num.zeros((1, 5))
                    source_terms = num.zeros((n, 1))
                    source_terms[:, 0] = weights
                    results = store_ext.store_calc_timeseries(
                        store.cstore,
                        source_coords,
                        source_terms,
                        shifts,
                        receiver_coords,
                        'dummy',
                        'nearest_neighbor',
                        num.array(
                            [itmin if itmin is not None else 0],
                            dtype=num.int32),
                        num.array(
                            [nsamples if nsamples is not None else -1],
                            dtype=num.int32),
                        nthreads)

                    d = gf.GFTrace(*results[0][:2])
                    self.assertEqual(a.itmin, d.itmin)
                    num.testing.assert_array_almost_equal(
                        a.data, d.data, 2)

        store.close()

    def _test_sum_statics(self):

        nrecords = 20

        store = gf.BaseStore(self.create(nrecords=nrecords))
        for i in range(5):
            n = random.randint(1, 10)
            indices = num.random.randint(nrecords, size=n).astype(num.uint64)
            weights = num.random.random(n).astype(num.float32)
            shifts = (num.random.random(n)*nrecords/4).astype(num.float32)
            it = random.randint(0, 5)

            dyn = store.sum(
                indices, shifts, weights,
                itmin=it,
                nsamples=1,
                decimate=1,
                implementation='c',
                optimization='enable')

            sta = store.sum_statics(
                indices, shifts, weights,
                it, 1,
                nthreads=1)

            if len(dyn.data) > 0:
                num.testing.assert_array_almost_equal(
                    dyn.data[-1], sta[0], 5)

        store.close()

    def test_store_dir_type(self):
        with self.assertRaises(TypeError):
            gf.LocalEngine(store_dirs='dummy')

    def test_pulse(self):
        store_dir = self.get_pulse_store_dir()

        engine = gf.LocalEngine(store_dirs=[store_dir])

        sources = [
            gf.ExplosionSource(
                time=0.0,
                depth=depth,
                moment=moment)

            for moment in (1.0, 2.0, 3.0) for depth in [100., 200., 300.]
        ]

        targets = [
            gf.Target(
                quantity=quantity,
                codes=('', 'STA', quantity, component),
                north_shift=500.,
                east_shift=0.)

            for component in 'ZNE'
            for quantity in ['displacement', 'velocity', 'acceleration']
        ]

        pulse = engine.get_store_extra(None, 'pulse')
        store = engine.get_store('pulse')

        response = engine.process(sources=sources, targets=targets)
        for source, target, tr in response.iter_results():
            t = tr.get_xdata()

            dist = math.sqrt((source.depth - target.depth)**2 +
                             source.distance_to(target)**2)

            data = pulse.evaluate(dist, t-source.time)

            phi = math.atan2((source.depth - target.depth),
                             source.distance_to(target)) * r2d

            azi, bazi = source.azibazi_to(target)

            data *= source.get_moment(store) * math.sqrt(2./3.)

            if tr.channel.endswith('N'):
                data *= math.cos(phi*d2r) * math.cos(azi*d2r)
            elif tr.channel.endswith('E'):
                data *= math.cos(phi*d2r) * math.sin(azi*d2r)
            elif tr.channel.endswith('Z'):
                data *= math.sin(phi*d2r)

            tr2 = tr.copy(data=False)
            tr2.set_ydata(data)
            tr2.set_codes(location='X')

            if target.quantity == 'velocity':
                tr2 = tr2.transfer(
                    transfer_function=trace.DifferentiationResponse(),
                    demean=False)

            elif target.quantity == 'acceleration':
                tr2 = tr2.transfer(
                    transfer_function=trace.DifferentiationResponse(2),
                    demean=False)

            # trace.snuffle([tr, tr2])

            amax = num.max(num.abs(tr.ydata))
            if amax > 1e-10:
                # print(num.max(num.abs(tr2.ydata - tr.ydata) / amax))
                assert num.all(num.abs(tr2.ydata - tr.ydata) < 0.05 * amax)

    @unittest.skip('')
    def test_pulse_decimate(self):
        store_dir = self.get_pulse_store_dir()

        store = gf.Store(store_dir)
        store.make_decimated(2)

        engine = gf.LocalEngine(store_dirs=[store_dir])
        # pulse = engine.get_store_extra(None, 'pulse')

        source = gf.ExplosionSource(
            time=0.0,
            depth=100.,
            moment=1.0)

        targets = [
            gf.Target(
                codes=('', 'STA', '%s' % sample_rate, component),
                sample_rate=sample_rate,
                north_shift=500.,
                east_shift=0.)

            for component in 'N'
            for sample_rate in [None, store.config.sample_rate / 2.0]
        ]

        response = engine.process(source, targets)

        trs = []
        for source, target, tr in response.iter_results():
            tr.extend(0., 1.)
            if target.sample_rate is None:
                tr.downsample_to(2./store.config.sample_rate, snap=True)

            trs.append(tr)

        tmin = max(tr.tmin for tr in trs)
        tmax = min(tr.tmax for tr in trs)

        for tr in trs:
            tr.chop(tmin, tmax)

        num.testing.assert_almost_equal(
            trs[0].ydata, trs[1].ydata, 2)

    def test_stf_pre_post(self):
        store_dir = self.get_pulse_store_dir()
        engine = gf.LocalEngine(store_dirs=[store_dir])
        store = engine.get_store('pulse')

        for duration in [0., 0.05, 0.1]:
            trs = []
            for mode in ['pre', 'post']:
                source = gf.ExplosionSource(
                    time=store.config.deltat * 0.5,
                    depth=200.,
                    moment=1.0,
                    stf=gf.BoxcarSTF(duration=duration),
                    stf_mode=mode)

                target = gf.Target(
                    codes=('', 'STA', '', 'Z'),
                    north_shift=500.,
                    east_shift=0.,
                    store_id='pulse')

                xtrs = engine.process(source, target).pyrocko_traces()
                for tr in xtrs:
                    tr.set_codes(location='%3.1f_%s' % (duration, mode))
                    trs.append(tr)

            tmin = max(tr.tmin for tr in trs)
            tmax = min(tr.tmax for tr in trs)
            for tr in trs:
                tr.chop(tmin, tmax)

            amax = max(num.max(num.abs(tr.ydata)) for tr in trs)
            perc = num.max(num.abs(trs[0].ydata - trs[1].ydata) / amax) * 100.
            if perc > 0.1:
                logger.warning(
                    'test_stf_pre_post: max difference of %.1f %%' % perc)

    def test_target_source_timing(self):
        store_dir = self.get_pulse_store_dir()
        engine = gf.LocalEngine(store_dirs=[store_dir])

        for stime in [0., -160000., time.time()]:
            source = gf.ExplosionSource(
                        depth=200.,
                        magnitude=4.,
                        time=stime)

            targets = [
                gf.Target(
                    codes=('', 'STA', '', component),
                    north_shift=500.,
                    tmin=source.time-300.,
                    tmax=source.time+300.,
                    east_shift=500.)

                for component in 'ZNE'
            ]

            response = engine.process(source, targets)
            synthetic_traces = response.pyrocko_traces()
            data = num.zeros(num.shape(synthetic_traces[0].ydata))
            for tr in synthetic_traces:
                data += tr.ydata

            sum_data = num.sum(abs(tr.ydata))
            assert sum_data > 1.0

    def test_target_store_deltat(self):
        store_dir = self.get_pulse_store_dir()
        engine = gf.LocalEngine(store_dirs=[store_dir])
        store = engine.get_store('pulse')

        source = gf.ExplosionSource(
            depth=200.,
            magnitude=4.,
            time=0.)

        targets = [gf.Target(
            codes=('', 'STA', '', 'Z'),
            north_shift=500.,
            east_shift=500.,
            sample_rate=None,
            store_id='pulse')]

        response = engine.process(source, targets)
        synthetic_traces = response.pyrocko_traces()

        assert synthetic_traces[0].deltat == store.config.deltat

        targets = [gf.Target(
            codes=('', 'STA', '', 'Z'),
            north_shift=500.,
            east_shift=500.,
            sample_rate=100.,
            store_id='pulse')]

        response = engine.process(source, targets)
        synthetic_traces = response.pyrocko_traces()

        assert synthetic_traces[0].deltat == 1./targets[0].sample_rate

        targets = [
            gf.Target(
                codes=('', 'STA', '', 'Z'),
                north_shift=500.,
                east_shift=500.,
                sample_rate=100.,
                interpolation='multilinear',
                store_id='pulse'),
            gf.Target(
                codes=('', 'STA2', '', 'Z'),
                north_shift=600.,
                east_shift=600.,
                sample_rate=50.,
                interpolation='nearest_neighbor',
                store_id='pulse')]

        response = engine.process(source, targets)
        synthetic_traces = response.pyrocko_traces()

        deltat_tr = [tr.deltat for tr in synthetic_traces]
        deltat_targ = [1./t.sample_rate for t in targets]

        for deltat_t, deltat_ta in zip(deltat_tr, deltat_targ):
            assert deltat_t == deltat_ta

    def benchmark_get(self):
        store_dir = self.get_benchmark_store_dir()

        import pylab as lab
        for implementation in ('c', 'python'):
            store = gf.Store(store_dir, use_memmap=True)
            for nrepeats in (1, 2):
                data = []
                for distance in store.config.coords[1]:
                    sdepths = num.repeat(store.config.coords[0],
                                         store.config.ncomponents)
                    t = time.time()
                    for repeat in range(nrepeats):
                        for sdepth in sdepths:
                            for icomp in range(1):
                                store.get(
                                    (sdepth, distance, icomp),
                                    implementation=implementation)

                    tnew = time.time()
                    data.append((distance, tnew - t))

                if nrepeats != 1:
                    d, t1 = num.array(data, dtype=num.float).T
                    nread = nrepeats * store.config.ns[0]
                    smmap = implementation
                    label = 'nrepeats %i, impl %s' % (nrepeats, smmap)
                    print(label, num.mean(nread/t1))

                    lab.plot(d, nread/t1, label=label)

        lab.legend()
        lab.show()

    def benchmark_sum(self):

        store_dir = self.get_benchmark_store_dir()

        import pylab as lab
        for implementation in ('c', 'python'):
            store = gf.Store(store_dir, use_memmap=True)
            for weight in (0.0, 1.0):
                for nrepeats in (1, 2):
                    data = []
                    for distance in store.config.coords[1]:
                        n = store.config.ncomponents*store.config.ns[0]
                        sdepths = num.repeat(store.config.coords[0],
                                             store.config.ncomponents)
                        distances = num.repeat([distance], n)
                        comps = num.tile(store.config.coords[2],
                                         store.config.ns[0])
                        args = (sdepths, distances, comps)
                        weights = num.repeat([weight], n)
                        delays = num.arange(n, dtype=num.float) \
                            * store.config.deltat * 0.5

                        t = time.time()

                        for repeat in range(nrepeats):
                            store.sum(args, delays, weights,
                                      implementation=implementation)

                        tnew = time.time()

                        data.append(((distance-store.config.distance_min)+1,
                                     tnew - t))

                    if nrepeats != 1:
                        d, t1 = num.array(data, dtype=num.float).T
                        nread = nrepeats * store.config.ns[0] \
                            * store.config.ncomponents
                        label = 'nrepeats %i, weight %g, impl %s' % (
                            nrepeats, weight, implementation)
                        print(label, num.mean(nread/t1))

                        lab.plot(d, nread/t1, label=label)

        lab.legend()
        lab.show()

    def test_optimization(self):
        store_dir = self.get_pulse_store_dir()
        engine = gf.LocalEngine(store_dirs=[store_dir])

        sources = [
            gf.RectangularExplosionSource(
                time=0.0025,
                depth=depth,
                moment=1.0,
                length=100.,
                width=0.,
                nucleation_x=-1)

            for depth in [100., 200., 300.]
        ]

        targetss = [
            [
                gf.Target(
                    codes=('', 'STA', opt, component),
                    north_shift=500.,
                    east_shift=125.,
                    depth=depth,
                    interpolation='multilinear',
                    optimization=opt)

                for component in 'ZNE' for depth in [0., 5., 10]]
            for opt in ('disable', 'enable')
        ]

        resps = [engine.process(sources, targets) for targets in targetss]

        iters = [resp.iter_results() for resp in resps]
        for i in range(len(sources) * len(targetss[0])):
            s1, t1, tr1 = next(iters[0])
            s2, t2, tr2 = next(iters[1])
            self.assertEqual(tr1.data_len(), tr2.data_len())
            self.assertEqual(tr1.tmin, tr2.tmin)
            self.assertTrue(numeq(tr1.ydata, tr2.ydata, 0.0001))

    def test_timing_defs(self):

        for s, d in [
                ('100.0', dict(offset=100)),
                ('cake: P ', dict(offset=0.0, phases=['cake:P'])),
                ('iaspei: Pdiff', dict(
                    phases=['iaspei:Pdiff'])),
                ('{iaspei: Pdiff}-50', dict(
                    phases=['iaspei:Pdiff'], offset=-50.)),
                ('{cake: P | iaspei: Pdiff}-10', dict(
                    offset=-10.,
                    phases=['cake:P', 'iaspei:Pdiff'])),
                ('first{cake: p | cake: P}', dict(
                    phases=['cake:p', 'cake:P'], select='first')),
                ('first(p|P)-10', dict(
                    phases=['stored:p', 'stored:P'], select='first',
                    offset=-10.)),
                ('{stored:begin}-50', dict(
                    phases=['stored:begin'], offset=-50.))]:
            t = gf.Timing(s)

            if 'phases' in d:
                for a, b in zip(d['phases'], t.phase_defs):
                    self.assertEqual(a, b)

            if 'offset' in d:
                self.assertTrue(numeq(d['offset'], t.offset, 0.001))

            if 'select' in d:
                self.assertEqual(d['select'], t.select)

    def test_timing(self):
        for typ, args, args_out_list in [
                ('a', (10*km, 1500*km),
                 [(10*km, 5000*km), (30*km, 1500*km)]),
                ('b', (5*km, 10*km, 1500*km),
                 [(100*km, 10*km, 1500*km),
                  (5*km, 10*km, 5000*km),
                  (5*km, 30*km, 1500*km)])]:
            store_dir = self.get_regional_ttt_store_dir(typ)

            store = gf.Store(store_dir)

            assert(store.t('P', args) is not None)
            self.assertEqual(store.t('last(S|P)', args), store.t('S', args))
            self.assertEqual(store.t('(S|P)', args), store.t('S', args))
            self.assertEqual(store.t('(P|S)', args), store.t('P', args))
            self.assertEqual(store.t('first(S|P)', args), store.t('P', args))

            with self.assertRaises(gf.NoSuchPhase):
                store.t('nonexistant', args)

            with self.assertRaises(AssertionError):
                store.t('P', (10*km,))

            for args_out in args_out_list:
                with self.assertRaises(gf.OutOfBounds):
                    store.t('P', args_out)

    def test_timing_new_syntax(self):
        for typ, args in [
                ('a', (10*km, 1500*km)),
                ('b', (5*km, 10*km, 1500*km))]:

            store_dir = self.get_regional_ttt_store_dir(typ)

            store = gf.Store(store_dir)

            assert numeq(
                store.t('stored:P', args), store.t('cake:P', args), 0.1)
            assert numeq(store.t('vel_surface:15', args), 100., 0.1)
            assert numeq(store.t('+0.1S', args), 150., 0.1)
            assert numeq(
                store.t('{stored:P}+0.1S', args),
                store.t('{cake:P}', args) + store.t('{vel_surface:10}', args),
                0.1)

    def test_ttt_lsd(self):
        for typ in ['a', 'b']:
            store_dir = self.get_regional_ttt_store_dir(typ)

            phase_id = 'P'

            store = gf.Store(store_dir)
            ph = store.get_stored_phase(phase_id)
            assert ph.check_holes()
            store.fix_ttt_holes(phase_id)

            ph = store.get_stored_phase(phase_id + '.lsd')
            assert not ph.check_holes()

    def dummy_store(self):
        if self._dummy_store is None:

            conf = gf.ConfigTypeA(
                id='empty_regional',
                source_depth_min=0.,
                source_depth_max=20*km,
                source_depth_delta=1*km,
                distance_min=1*km,
                distance_max=2000*km,
                distance_delta=1*km,
                sample_rate=2.0,
                ncomponents=10)

            store_dir = mkdtemp(prefix='gfstore')
            self.tempdirs.append(store_dir)

            gf.Store.create(store_dir, config=conf)
            self._dummy_store = gf.Store(store_dir)

        return self._dummy_store

    def test_make_params(self):
        from pyrocko.gf import store_ext
        benchmark.show_factor = True

        def test_make_params_bench(store, dim, ntargets, interpolation,
                                   nthreads):
            source = gf.RectangularSource(
                lat=0., lon=0.,
                depth=10*km, north_shift=0.1, east_shift=0.1,
                width=dim, length=dim)

            targets = [gf.Target(
                lat=random.random()*10.,
                lon=random.random()*10.,
                north_shift=0.1,
                east_shift=0.1) for x in range(ntargets)]

            dsource = source.discretize_basesource(store, targets[0])
            source_coords_arr = dsource.coords5()
            mts_arr = dsource.m6s

            receiver_coords_arr = num.empty((len(targets), 5))
            for itarget, target in enumerate(targets):
                receiver = target.receiver(store)
                receiver_coords_arr[itarget, :] = \
                    [receiver.lat, receiver.lon, receiver.north_shift,
                     receiver.east_shift, receiver.depth]
            ns = mts_arr.shape[0]
            label = '_ns%04d_nt%04d_%s_np%02d' % (
                ns,
                len(targets),
                interpolation,
                nthreads)

            @benchmark.labeled('c%s' % label)
            def make_param_c():
                return store_ext.make_sum_params(
                    store.cstore,
                    source_coords_arr,
                    mts_arr,
                    receiver_coords_arr,
                    'elastic10',
                    interpolation, nthreads)

            @benchmark.labeled('p%s' % label)
            def make_param_python():
                weights_c = []
                irecords_c = []
                for itar, target in enumerate(targets):
                    receiver = target.receiver(store)
                    dsource = source.discretize_basesource(store, target)

                    for i, (component, args, delays, weights) in \
                            enumerate(store.config.make_sum_params(
                                dsource, receiver)):
                        if len(weights_c) <= i:
                            weights_c.append([])
                            irecords_c.append([])

                        if interpolation == 'nearest_neighbor':
                            irecords = num.array(store.config.irecords(*args))
                            weights = num.array(weights)
                        else:
                            assert interpolation == 'multilinear'
                            irecords, ip_weights =\
                                store.config.vicinities(*args)
                            neach = irecords.size // args[0].size
                            weights = num.repeat(weights, neach) * ip_weights
                            delays = num.repeat(delays, neach)

                        weights_c[i].append(weights)
                        irecords_c[i].append(irecords)
                for c in range(len(weights_c)):
                    weights_c[c] = num.concatenate([w for w in weights_c[c]])
                    irecords_c[c] = num.concatenate([ir for
                                                     ir in irecords_c[c]])

                return list(zip(weights_c, irecords_c))

            rc = make_param_c()
            rp = make_param_python()

            logger.info(benchmark.__str__(header=False))
            benchmark.clear()

            # Comparing the results
            if isinstance(store.config, gf.meta.ConfigTypeA):
                idim = 4
            elif isinstance(store.config, gf.meta.ConfigTypeB):
                idim = 8
            if interpolation == 'nearest_neighbor':
                idim = 1

            nsummands_scheme = [5, 5, 3]  # elastic8
            nsummands_scheme = [6, 6, 4]  # elastic10
            for i, nsummands in enumerate(nsummands_scheme):
                for r in [0, 1]:
                    r_c = rc[i][r]
                    r_p = rp[i][r].reshape(ntargets, nsummands, ns*idim)
                    r_p = num.transpose(r_p, axes=[0, 2, 1])

                    num.testing.assert_almost_equal(r_c, r_p.flatten())

        '''
        Testing loop
        '''
        # dims = [2*km, 5*km, 8*km, 16*km]
        # ntargets = [10, 100, 1000]

        # dims = [16*km]
        # ntargets = [1000]
        dims = [2*km, 5*km]
        ntargets = [10, 100]

        store = self.dummy_store()
        store.open()

        for interpolation in ['multilinear', 'nearest_neighbor']:
            for d in dims:
                for nt in ntargets:
                    for nthreads in [1, 2]:
                        test_make_params_bench(
                            store, d, nt, interpolation, nthreads)

        benchmark.show_factor = False

    @unittest.skipIf('global_2s' not in local_stores,
                     'depends on store global_2s')
    def test_calc_timeseries(self):
        from pyrocko.gf import store_ext
        benchmark.show_factor = True

        engine = gf.LocalEngine(use_config=True)

        def test_timeseries(
                store, source, targets, interpolation, nthreads,
                random_itmin=False, random_nsamples=False):

            ntargets = len(targets)
            dsource = source.discretize_basesource(store, targets[0])
            source_coords_arr = dsource.coords5()
            scheme = store.config.component_scheme
            source_terms = dsource.get_source_terms(scheme)

            receiver_coords_arr = num.empty((len(targets), 5))
            for itarget, target in enumerate(targets):
                receiver = target.receiver(store)
                receiver_coords_arr[itarget, :] = \
                    [receiver.lat, receiver.lon, receiver.north_shift,
                     receiver.east_shift, receiver.depth]

            delays = dsource.times

            itmin = num.zeros(ntargets, dtype=num.int32)
            nsamples = num.full(ntargets, -1, dtype=num.int32)

            if random_itmin:
                itmin = num.random.randint(-20, 5, size=ntargets,
                                           dtype=num.int32)
            if random_nsamples:
                nsamples = num.random.randint(10, 100, size=ntargets,
                                              dtype=num.int32)

            @benchmark.labeled('calc_timeseries-%s' % interpolation)
            def calc_timeseries():

                return store_ext.store_calc_timeseries(
                    store.cstore,
                    source_coords_arr,
                    source_terms,
                    delays,
                    receiver_coords_arr,
                    scheme,
                    interpolation,
                    itmin,
                    nsamples,
                    nthreads)

            @benchmark.labeled('sum_timeseries-%s' % interpolation)
            def sum_timeseries():
                results = []
                for itarget, target in enumerate(targets):
                    params = store_ext.make_sum_params(
                        store.cstore,
                        source_coords_arr,
                        source_terms,
                        target.coords5[num.newaxis, :].copy(),
                        scheme,
                        interpolation,
                        nthreads)

                    for weights, irecords in params:
                        neach = irecords.size // dsource.times.size
                        delays2 = num.repeat(dsource.times, neach)
                        r = store_ext.store_sum(
                            store.cstore,
                            irecords,
                            delays2,
                            weights,
                            int(itmin[itarget]),
                            int(nsamples[itarget]))

                        results.append(r)

                return results

            res_calc = calc_timeseries()
            res_sum = sum_timeseries()

            for c, s in zip(res_calc, res_sum):
                num.testing.assert_equal(c[0], s[0], verbose=True)
                for cc, cs in zip(c[1:-1], s[1:]):
                    assert cc == cs

        source_store_targets = [
            (
                gf.ExplosionSource(time=0.0, depth=100., moment=1.0),
                gf.Store(self.get_pulse_store_dir()),
                [
                    gf.Target(
                        codes=('', 'STA', '', component),
                        north_shift=500.,
                        east_shift=500.,
                        tmin=-300.,
                        tmax=+300.)
                    for component in 'ZNE'
                ]
            ),
            (
                gf.RectangularSource(
                    lat=0., lon=0., depth=5*km,
                    length=1*km, width=1*km, anchor='top'),
                engine.get_store('global_2s'),
                [
                    gf.Target(
                        codes=('', 'STA%02i' % istation, '', component),
                        lat=lat,
                        lon=lon,
                        store_id='global_2s')
                    for component in 'ZNE'
                    for istation, (lat, lon) in enumerate(
                        num.random.random((1, 2)))
                ]
            )
        ]

        for source, store, targets in source_store_targets:
            store.open()
            for interp in ['multilinear', 'nearest_neighbor']:
                for random_itmin in [True, False]:
                    for random_nsamples in [True, False]:
                        test_timeseries(
                            store, source, targets,
                            interpolation=interp,
                            nthreads=1,
                            random_itmin=random_itmin,
                            random_nsamples=random_nsamples)

                print(benchmark)
                benchmark.clear()

    @unittest.skipIf('global_2s' not in local_stores,
                     'depends on store global_2s')
    def test_process_timeseries(self):
        engine = gf.LocalEngine(use_config=True)

        sources = [
            gf.ExplosionSource(
                time=0.0,
                depth=depth,
                moment=moment)

            for moment in [2., 4., 8.] for depth in [3000., 6000., 12000.]
        ]

        targets = [
            gf.Target(
                codes=('', 'ST%d' % i, '', component),
                north_shift=shift*km,
                east_shift=0.,
                tmin=tmin,
                store_id='global_2s',
                tmax=None if tmin is None else tmin+40.)

            for component in 'ZNE' for i, shift in enumerate([100])
            for tmin in [None, 5., 20.]
        ]

        response_sum = engine.process(sources=sources, targets=targets,
                                      calc_timeseries=False, nthreads=1)

        response_calc = engine.process(sources=sources, targets=targets,
                                       calc_timeseries=True, nthreads=1)

        for (source, target, tr), (source_n, target_n, tr_n) in zip(
                response_sum.iter_results(), response_calc.iter_results()):
            assert source is source_n
            assert target is target_n

            t1 = tr.get_xdata()
            t2 = tr_n.get_xdata()
            num.testing.assert_equal(t1, t2)

            disp1 = tr.get_ydata()
            disp2 = tr_n.get_ydata()

            num.testing.assert_equal(disp1, disp2)

    def _test_homogeneous_scenario(
            self,
            config_type_class,
            component_scheme,
            discretized_source_class):

        if config_type_class.short_type == 'C' \
                or component_scheme.startswith('poro'):

            assert False

        store_id = 'homogeneous_%s_%s' % (
            config_type_class.short_type, component_scheme)

        vp = 5.8 * km
        vs = 3.46 * km

        mod = cake.LayeredModel.from_scanlines(cake.read_nd_model_str('''
  0. %(vp)g %(vs)g 2.6 1264. 600.
 20. %(vp)g %(vs)g 2.6 1264. 600.'''.lstrip() % dict(vp=vp/km, vs=vs/km)))

        store_type = config_type_class.short_type
        params = dict(
            id=store_id,
            sample_rate=1000.,
            modelling_code_id='ahfullgreen',
            component_scheme=component_scheme,
            earthmodel_1d=mod)

        if store_type in ('A', 'B'):
            params.update(
                source_depth_min=1.*km,
                source_depth_max=2.*km,
                source_depth_delta=0.5*km,
                distance_min=4.*km,
                distance_max=6.*km,
                distance_delta=0.5*km)

        if store_type == 'A':
            params.update(
                receiver_depth=3.*km)

        if store_type == 'B':
            params.update(
                receiver_depth_min=2.*km,
                receiver_depth_max=3.*km,
                receiver_depth_delta=0.5*km)

        if store_type == 'C':
            params.update(
                source_depth_min=1.*km,
                source_depth_max=2.*km,
                source_depth_delta=0.5*km,
                source_east_shift_min=1.*km,
                source_east_shift_max=2.*km,
                source_east_shift_delta=0.5*km,
                source_north_shift_min=2.*km,
                source_north_shift_max=3.*km,
                source_north_shift_delta=0.5*km)

        config = config_type_class(**params)

        config.validate()

        store_dir = mkdtemp(prefix=store_id)
        self.tempdirs.append(store_dir)

        conf = fomosto_ahfullgreen.AhfullgreenConfig()

        gf.store.Store.create_editables(
            store_dir, config=config, extra={'ahfullgreen': conf})

        store = gf.store.Store(store_dir, 'r')
        store.make_ttt()
        store.close()

        fomosto_ahfullgreen.build(store_dir, nworkers=1)

        store = gf.store.Store(store_dir, 'r')

        dsource_type = discretized_source_class.__name__

        params = {}
        if dsource_type == 'DiscretizedMTSource':
            params.update(
                m6s=num.array([
                    [1., 2., 3., 4., 5., 6.],
                    [1., 2., 3., 4., 5., 6.]]))
        elif dsource_type == 'DiscretizedExplosionSource':
            params.update(
                m0s=num.array([2., 2.]))
        elif dsource_type == 'DiscretizedSFSource':
            params.update(
                forces=num.array([[1., 2., 3.], [1., 2., 3.]]))
        elif dsource_type == 'DiscretizedPorePressureSource':
            params.update(
                pp=num.array([3., 3.]))

        snorth = 2.0*km
        seast = 2.0*km
        sdepth = 1.0*km
        rnorth = snorth + 3.*km
        reast = seast + 4.*km
        rdepth = 3.0*km

        t0 = 10.0 * store.config.deltat

        dsource = discretized_source_class(
            times=num.array([t0, t0+5.*store.config.deltat]),
            north_shifts=num.array([snorth, snorth]),
            east_shifts=num.array([seast, seast]),
            depths=num.array([sdepth, sdepth]),
            **params)

        receiver = gf.Receiver(
            north_shift=rnorth,
            east_shift=reast,
            depth=rdepth)

        components = gf.component_scheme_to_description[
            component_scheme].provided_components

        for seismogram in [store.seismogram, store.calc_seismograms]:
            for interpolation in ['nearest_neighbor', 'multilinear']:
                trs1 = []

                res = seismogram(dsource, receiver, components,
                                 interpolation=interpolation)
                if isinstance(res, list) and len(res) == 1:
                    res = res[0]
                for component, gtr in res.items():

                    tr = gtr.to_trace('', 'STA', seismogram.__name__,
                                      component)
                    trs1.append(tr)

                trs2 = _make_traces_homogeneous(
                    dsource, receiver,
                    store.config.earthmodel_1d.require_homogeneous(),
                    store.config.deltat, '', 'STA', 'reference')

                tmin = max(tr.tmin for tr in trs1+trs2)
                tmax = min(tr.tmax for tr in trs1+trs2)
                for tr in trs1+trs2:
                    tr.chop(tmin, tmax)
                    assert tr.data_len() > 2

                trs1.sort(key=lambda tr: tr.channel)
                trs2.sort(key=lambda tr: tr.channel)

                denom = 0.0
                for t1, t2 in zip(trs1, trs2):
                    assert t1.channel == t2.channel
                    denom += num.sum(t1.ydata**2) + num.sum(t2.ydata**2)

                ds = []
                for t1, t2 in zip(trs1, trs2):
                    ds.append(2.0 * num.sum((t1.ydata - t2.ydata)**2) / denom)

                ds = num.array(ds)

                if component_scheme == 'elastic8':
                    limit = 1e-2
                else:
                    limit = 1e-6

                if not num.all(ds < limit):
                    trace.snuffle(trs1+trs2)

                assert num.all(ds < limit)

    def test_nodes(x):
        from pyrocko.gf.meta import nodes, nditer_outer

        xs = [
            num.linspace(0., 2., 3),
            num.linspace(0., 3., 4),
            num.linspace(0., 4., 5)]

        ps = nodes(xs)
        for i, p in enumerate(nditer_outer(xs)):
            assert num.all(p == ps[i])


for config_type_class in gf.config_type_classes:
    for scheme in config_type_class.provided_schemes:
        for discretized_source_class in gf.discretized_source_classes:
            if scheme in discretized_source_class.provided_schemes:
                name = 'test_homogeneous_scenario_%s_%s_%s' % (
                    config_type_class.short_type,
                    scheme,
                    discretized_source_class.__name__)

                def make_method(
                        config_type_class, scheme, discretized_source_class):

                    @unittest.skipIf(
                        scheme.startswith('poro')
                        or config_type_class.short_type == 'C',
                        'todo: test poro and store type C')
                    def test_homogeneous_scenario(self):
                        return self._test_homogeneous_scenario(
                            config_type_class,
                            scheme,
                            discretized_source_class)

                    test_homogeneous_scenario.__name__ = name

                    return test_homogeneous_scenario
                setattr(GFTestCase, name, make_method(
                    config_type_class, scheme, discretized_source_class))


if __name__ == '__main__':
    util.setup_logging('test_gf', 'warning')
    unittest.main()
