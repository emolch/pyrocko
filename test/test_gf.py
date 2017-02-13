import time
import sys
import random
import math
from pyrocko import guts
import unittest
from tempfile import mkdtemp
import logging
import numpy as num

from pyrocko import gf, util, cake


logger = logging.getLogger('test_gf.py')


r2d = 180. / math.pi
d2r = 1.0 / r2d
km = 1000.


def numeq(a, b, eps):
    return (num.all(num.asarray(a).shape == num.asarray(b).shape and
            num.abs(num.asarray(a) - num.asarray(b)) < eps))


class PulseConfig(guts.Object):
    fwhm = guts.Float.T(default=0.02)
    velocity = guts.Float.T(default=1000.)

    def evaluate(self, distance, t):
        tarr = distance / self.velocity
        denom = self.fwhm / (2.*math.sqrt(math.log(2.)))
        return num.exp(-((t-tarr)/denom)**2)


class GFTestCase(unittest.TestCase):

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

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)
        self.tempdirs = []
        self.pulse_store_dir = None
        self.regional_ttt_store_dir = None
        self.benchmark_store_dir = None

    def __del__(self):
        import shutil

        for d in self.tempdirs:
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

    def get_regional_ttt_store_dir(self):
        if self.regional_ttt_store_dir is None:
            self.regional_ttt_store_dir = self._create_regional_ttt_store()

        return self.regional_ttt_store_dir

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

    def _create_regional_ttt_store(self):

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
        for deci in (1, 2, 3, 4):
            for i in range(nrecords):
                tr = store.get(i, decimate=deci)
                itmin, itmax = store.get_span(i, decimate=deci)
                self.assertEqual(tr.itmin, itmin)
                self.assertEqual(tr.data.size, itmax-itmin + 1)

        store.close()

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
                self.assertTrue(numeq(tra.data, trb.data, 0.001))
                self.assertTrue(numeq(tra.begin_value, trb.begin_value, 0.001))
                self.assertTrue(numeq(tra.end_value, trb.end_value, 0.001))

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

        store.close()

    def test_sum_statics(self):

        nrecords = 8

        store = gf.BaseStore(self.create(nrecords=nrecords))
        for i in xrange(5):
            n = random.randint(0, 5)
            indices = num.random.randint(nrecords, size=n)
            weights = num.random.random(n)
            shifts = num.random.random(n)*nrecords

            dyn = store.sum(
                indices, shifts, weights,
                itmin=None,
                nsamples=None,
                decimate=1,
                implementation='c',
                optimization='enable')

            sta = store.sum_statics(
                indices, weights,
                implementation=None,
                optimization='enable')

            if len(dyn.data) > 0:
                num.testing.assert_array_almost_equal(dyn.data[-1], sta.value,
                                                      5)

        store.close()

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
                codes=('', 'STA', '', component),
                north_shift=500.,
                east_shift=0.)

            for component in 'ZNE'
        ]

        pulse = engine.get_store_extra(None, 'pulse')

        response = engine.process(sources=sources, targets=targets)
        for source, target, tr in response.iter_results():
            t = tr.get_xdata()

            dist = math.sqrt((source.depth - target.depth)**2 +
                             source.distance_to(target)**2)

            data = pulse.evaluate(dist, t-source.time)

            phi = math.atan2((source.depth - target.depth),
                             source.distance_to(target)) * r2d

            azi, bazi = source.azibazi_to(target)

            data *= source.moment

            if tr.channel.endswith('N'):
                data *= math.cos(phi*d2r) * math.cos(azi*d2r)
            elif tr.channel.endswith('E'):
                data *= math.cos(phi*d2r) * math.sin(azi*d2r)
            elif tr.channel.endswith('Z'):
                data *= math.sin(phi*d2r)

            tr2 = tr.copy(data=False)
            tr2.set_ydata(data)
            tr2.set_codes(location='X')

            self.assertTrue(numeq(data, tr.ydata, 0.01))

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

        self.assertTrue(numeq(trs[0].ydata, trs[1].ydata, 0.01))

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
                logger.warn(
                    'test_stf_pre_post: max difference of %.1f %%' % perc)

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
                    for repeat in xrange(nrepeats):
                        for sdepth in sdepths:
                            for icomp in xrange(1):
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
                    print label, num.mean(nread/t1)

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

                        for repeat in xrange(nrepeats):
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
                        print label, num.mean(nread/t1)

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
        for i in xrange(len(sources) * len(targetss[0])):
            s1, t1, tr1 = iters[0].next()
            s2, t2, tr2 = iters[1].next()
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
        store_dir = self.get_regional_ttt_store_dir()

        store = gf.Store(store_dir)

        args = (10*km, 1500*km)
        assert(store.t('P', args) is not None)
        self.assertEqual(store.t('last(S|P)', args), store.t('S', args))
        self.assertEqual(store.t('(S|P)', args), store.t('S', args))
        self.assertEqual(store.t('(P|S)', args), store.t('P', args))
        self.assertEqual(store.t('first(S|P)', args), store.t('P', args))

        with self.assertRaises(gf.NoSuchPhase):
            store.t('nonexistant', args)

        with self.assertRaises(AssertionError):
            store.t('P', (10*km,))

        with self.assertRaises(gf.OutOfBounds):
            print store.t('P', (10*km, 5000*km))

        with self.assertRaises(gf.OutOfBounds):
            print store.t('P', (30*km, 1500*km))

    def test_timing_new_syntax(self):
        store_dir = self.get_regional_ttt_store_dir()

        store = gf.Store(store_dir)

        args = (10*km, 1500*km)

        assert numeq(store.t('stored:P', args), store.t('cake:P', args), 0.1)
        assert numeq(store.t('vel_surface:15', args), 100., 0.1)
        assert numeq(store.t('+0.1S', args), 150., 0.1)
        assert numeq(
            store.t('{stored:P}+0.1S', args),
            store.t('{cake:P}', args) + store.t('{vel_surface:10}', args),
            0.1)

    def test_timing_evaluate(self):
        phase_defs = 'abcdefg'
        args = "dummy"

        times = {}
        times_list = []
        for phase_def in phase_defs:
            times_list.append(num.random.random())
            times[str("stored:" + phase_def)] = {args: times_list[-1]}

        times_min = num.min(times_list)
        times_max = num.max(times_list)

        def get_phase(phase_def):

            t = times[phase_def]

            def return_time(args):
                return t[args]

            return return_time

        tf = gf.Timing(
            'first('+'|'.join([str(pd) for pd in phase_defs]) + ')-10')
        tl = gf.Timing(
            'last('+'|'.join([str(pd) for pd in phase_defs]) + ')+10')

        first_onset = tf.evaluate(get_phase, args)
        last_onset = tl.evaluate(get_phase, args)

        self.assertEqual(first_onset, times_min-10)
        self.assertEqual(last_onset, times_max+10)

    def test_timing_evaluate_many(self):
        phase_defs = 'abcdefg'
        nvals = 20
        args = range(nvals)
        times = {}
        times_list = []

        min_times = num.empty(nvals)
        min_times[:] = num.nan
        max_times = num.empty(nvals)
        max_times[:] = num.nan

        for phase_def in phase_defs:
            data = num.random.random(nvals)
            data[num.random.randint(0, nvals)] = num.nan
            times_list.append(data)
            times[str("stored:" + phase_def)] = dict(zip(args, times_list[-1]))

            min_times = num.nanmin((min_times, times_list[-1]), 0)
            max_times = num.nanmax((max_times, times_list[-1]), 0)

        def get_phase(phase_def):
            t = times[phase_def]

            def return_times(args):
                vals = num.array([t[k] for k in args])
                return vals

            return return_times

        tf = gf.Timing('first('+'|'.join(
            [str(pd) for pd in phase_defs])+')+2.5')
        tl = gf.Timing('last('+'|'.join(
            [str(pd) for pd in phase_defs])+')-2.5')

        first_onset = tf.evaluate(get_phase, args)
        last_onset = tl.evaluate(get_phase, args)

        self.assertTrue((first_onset == min_times+2.5).all())
        self.assertTrue((last_onset == max_times-2.5).all())
        self.assertTrue(len(first_onset) == nvals)
        self.assertTrue(len(last_onset) == nvals)

        tf = gf.Timing('first{stored:'+'|stored:'.join([str(pd) for pd in
                                                        phase_defs])+'}')
        tl = gf.Timing('last{stored:'+'|stored:'.join([str(pd) for pd in
                                                       phase_defs])+'}')

        first_onset = tf.evaluate(get_phase, args)
        last_onset = tl.evaluate(get_phase, args)

        self.assertTrue((first_onset == min_times).all())
        self.assertTrue((last_onset == max_times).all())
        self.assertTrue(len(first_onset) == nvals)
        self.assertTrue(len(last_onset) == nvals)

    def test_timing_store_evaluate_many(self):
        store_dir = self.get_regional_ttt_store_dir()

        store = gf.Store(store_dir)
        n = 100
        vel = 100.
        config = store.config
        zs = num.random.uniform(
            config.source_depth_min, config.source_depth_max, n)
        ds = num.random.uniform(
            config.distance_min, config.distance_max, n)

        args = num.vstack((zs, ds)).T

        arrs_ref = num.empty(len(args))
        for i, a in enumerate(args):
            arrs_ref[i] = store.t('P', tuple(a))

        arrs_p = store.t('P', args)
        arrs_p_cake = store.t('cake:P', args)
        arrs_vel = store.t('vel:%s' % vel, args)
        arrs_vel_horizontal = store.t('vel_surface:%s' % vel, args)

        assert numeq(arrs_ref, arrs_p, 1e-1)
        assert numeq(arrs_ref, arrs_p_cake, 1.)
        self.assertEqual(arrs_vel.shape, (len(args),))
        self.assertEqual(arrs_vel_horizontal.shape, (len(args),))
        assert all(args.T[1]/(vel*1000.) == arrs_vel_horizontal)

        self.assertTrue(all(store.t('first{vel:%s|stored:P}' % vel, args) ==
                        arrs_vel))
        self.assertTrue(all(store.t('last{vel:%s|stored:P}' % vel, args) ==
                        arrs_p))

if __name__ == '__main__':
    util.setup_logging('test_gf', 'warning')
    unittest.main()
