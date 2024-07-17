
from pyrocko import trace, util, model, pile, guts, response
import unittest
import math
import time
import numpy as num
import pickle as pickle

from .. import common

try:
    range = xrange
except NameError:
    pass

sometime = 1234567890.
d2r = num.pi/180.


def numeq(a, b, eps):
    return num.all(num.abs(num.array(a) - num.array(b)) <= eps)


def floats(list_):
    return num.array(list_, dtype=float)


def is_multiple(x, d, eps):
    x2 = int(round(x / d)) * d
    return abs(x - x2) < d*eps


class TraceTestCase(unittest.TestCase):

    def testIntegrationDifferentiation(self):

        fmin = 0.1
        fmax = 2.0
        for tlen in [100., 1000., 10000]:
            for dt in [0.1, 0.05]:
                for f in [0.2, 0.5, 1.0]:

                    n = int(tlen/dt)
                    tfade = 2.0/fmin

                    xdata = num.arange(n)*dt
                    ydata = num.sin(xdata*2.*num.pi*f)
                    a = trace.Trace(channel='A', deltat=dt, ydata=ydata)

                    b = a.transfer(
                        tfade, (fmin/2., fmin, fmax, fmax*2.),
                        transfer_function=response.IntegrationResponse())
                    b.set_codes(channel='B')

                    c = a.transfer(
                        tfade, (fmin/2., fmin, fmax, fmax*2.),
                        transfer_function=response.DifferentiationResponse())
                    c.set_codes(channel='C')

                    eps = 0.005
                    xdata = b.get_xdata()
                    ydata = b.get_ydata()
                    ydata_shouldbe = -num.cos(xdata*2*num.pi*f) / (2.*num.pi*f)

                    # if num.amax(num.abs(ydata-ydata_shouldbe)) > eps:
                    # b_shouldbe = trace.Trace(
                    #     channel='B', location='integrated',
                    #     deltat=dt, ydata=ydata_shouldbe, tmin=xdata[0])
                    #     trace.snuffle([b, b_shouldbe])

                    assert num.amax(num.abs(ydata-ydata_shouldbe)) < eps, \
                        'integration failed'

                    xdata = c.get_xdata()
                    ydata = c.get_ydata()
                    ydata_shouldbe = num.cos(xdata*2*num.pi*f) * (2.*num.pi*f)

                    # if num.amax(num.abs(ydata-ydata_shouldbe)) > eps:
                    # c_shouldbe = trace.Trace(
                    #     channel='C', location='differentiated',
                    #     deltat=dt, ydata=ydata_shouldbe, tmin=xdata[0])
                    #     trace.snuffle([c, c_shouldbe])

                    assert num.amax(num.abs(ydata-ydata_shouldbe)) < eps, \
                        'differentiation failed'

    def test_differentiation(self):
        dt = 0.1
        dur = 10.0
        n = int(round(dur / dt))

        t0 = 5.0

        tau = 0.25

        t = num.arange(n)*dt
        y = num.exp(-(t-t0)**2/tau**2)
        a = trace.Trace(location='A', deltat=dt, ydata=y)

        dydt = num.exp(-(t-t0)**2/tau**2) * -2.0 / tau**2 * (t-t0)
        b = trace.Trace(location='B', deltat=dt, ydata=dydt)

        c = a.transfer(
            transfer_function=response.DifferentiationResponse(), demean=False)
        c.set_codes(location='C')

        d = a.differentiate(inplace=False, order=4)
        d.set_codes(location='D')

        e = a.differentiate(inplace=False, order=2)
        e.set_codes(location='E')

        bmax = b.absmax()[1]

        assert numeq(b.ydata, c.ydata, 0.0001*bmax)
        assert numeq(b.ydata, d.ydata, 0.03*bmax)
        assert numeq(b.ydata, e.ydata, 0.2*bmax)

        # trace.snuffle([a, b, c, d, e])

        c2 = c.transfer(
            transfer_function=response.DifferentiationResponse(), demean=False)
        c2.set_codes(location='C2')

        c2max = c2.absmax()[1]

        d2 = a.differentiate(inplace=False, n=2, order=4)
        d2.set_codes(location='D2')
        e2 = a.differentiate(inplace=False, n=2, order=2)
        e2.set_codes(location='E2')

        assert numeq(c2.ydata, d2.ydata, 0.02*c2max)
        assert numeq(c2.ydata, e2.ydata, 0.1*c2max)

        # trace.snuffle([c2, d2, e2])

    def testDegapping(self):
        dt = 1.0
        atmin = 100.

        for btmin in range(90, 120):
            a = trace.Trace(deltat=dt, ydata=num.zeros(10), tmin=atmin)
            b = trace.Trace(deltat=dt, ydata=num.ones(5), tmin=btmin)
            traces = [a, b]
            traces.sort(key=lambda a: a.full_id)
            xs = trace.degapper(traces)

            if btmin == 90:
                assert len(xs) == 2
            elif btmin > 90 and btmin < 115:
                assert len(xs) == 1
            else:
                assert len(xs) == 2

        a = trace.Trace(deltat=dt, ydata=num.zeros(10), tmin=100)
        b = trace.Trace(deltat=dt, ydata=num.ones(10), tmin=100)
        traces = [a, b]
        traces.sort(key=lambda a: a.full_id)
        xs = trace.degapper(traces)
        assert len(xs) == 1
        for x in xs:
            assert x.tmin == 100
            assert x.get_ydata().size == 10

        for meth, res in (
                ('use_second', [1., 1.]),
                ('use_first', [0., 0.]),
                ('crossfade_cos', [0.25, 0.75]),
                ('add', [0., 0.])):

            if meth == 'add':
                a = trace.Trace(deltat=dt, ydata=num.ones(10)*-1, tmin=100)
            else:
                a = trace.Trace(deltat=dt, ydata=num.zeros(10), tmin=100)
            b = trace.Trace(deltat=dt, ydata=num.ones(10), tmin=108)
            traces = [a, b]
            traces.sort(key=lambda a: a.full_id)
            xs = trace.degapper(traces, deoverlap=meth)
            for x in xs:
                assert x.ydata.size == 18
                assert numeq(x.ydata[8:10], res, 1e-6)

    def testRotation(self):
        s2 = math.sqrt(2.)
        ndata = num.array([s2, s2], dtype=float)
        edata = num.array([s2, 0.], dtype=float)
        dt = 1.0
        n = trace.Trace(deltat=dt, ydata=ndata, tmin=100, channel='N')
        e = trace.Trace(deltat=dt, ydata=edata, tmin=100, channel='E')
        rotated = trace.rotate([n, e], 45., ['N', 'E'], ['R', 'T'])
        for tr in rotated:
            if tr.channel == 'R':
                r = tr
            if tr.channel == 'T':
                t = tr

        assert numeq(r.get_ydata(), [2., 1.], 1.0e-6)
        assert numeq(t.get_ydata(), [0., -1], 1.0e-6)

    def testLQTRotation(self):
        ba = 225.
        inci = 90.-num.arctan(1./num.sqrt(2.))*180./num.pi
        in_channels = list('ZEN')
        zdata = num.ones(2)
        edata = num.ones(2)
        ndata = num.ones(2)
        z = trace.Trace(deltat=1., ydata=zdata, tmin=1., channel='Z')
        e = trace.Trace(deltat=1., ydata=edata, tmin=1., channel='E')
        n = trace.Trace(deltat=1., ydata=ndata, tmin=1., channel='N')
        l, q, t = trace.rotate_to_lqt([z, n, e], ba, inci, in_channels)  # noqa
        assert num.all(l.get_ydata() - num.sqrt(3.) < 1.0e-12)  # noqa
        assert num.all(t.get_ydata() < 1.0e-12)
        assert num.all(q.get_ydata() < 1.0e-12)

    def testProjection(self):
        s2 = math.sqrt(2.)
        ndata = num.array([s2, s2], dtype=float)
        edata = num.array([s2, 0.], dtype=float)
        ddata = num.array([1., -1.], dtype=float)
        dt = 1.0
        n = trace.Trace(deltat=dt, ydata=ndata, tmin=100, channel='N')
        e = trace.Trace(deltat=dt, ydata=edata, tmin=100, channel='E')
        d = trace.Trace(deltat=dt, ydata=ddata, tmin=100, channel='D')
        azi = 45.
        cazi = math.cos(azi*d2r)
        sazi = math.sin(azi*d2r)
        rot45 = num.array(
            [[cazi, sazi, 0], [-sazi, cazi, 0], [0, 0, -1]], dtype=float)

        def C(x):
            return model.Channel(x)

        rotated = trace.project(
            [n, e, d],
            rot45,
            [C('N'), C('E'), C('D')],
            [C('R'), C('T'), C('U')])

        for tr in rotated:
            if tr.channel == 'R':
                r = tr
            if tr.channel == 'T':
                t = tr
            if tr.channel == 'U':
                u = tr

        assert num.all(r.get_ydata() - num.array([2., 1.]) < 1.0e-6)
        assert num.all(t.get_ydata() - num.array([0., -1]) < 1.0e-6)
        assert num.all(u.get_ydata() - num.array([-1., 1.]) < 1.0e-6)

        deps = trace.project_dependencies(
            rot45,
            [C('N'), C('E'), C('D')],
            [C('R'), C('T'), C('U')])

        assert (
            set(['N', 'E']) == set(deps['R'])
            and set(['N', 'E']) == set(deps['T'])
            and set(['D']) == set(deps['U']))

        # should work though no horizontals given
        trace.project(
            [d],
            rot45,
            [C('N'), C('E'), C('D')], [C('R'), C('T'), C('U')])

        if tr.channel == 'U':
            u = tr

        assert num.all(u.get_ydata() - num.array([-1., 1.]) < 1.0e-6)

    def testExtend(self):
        tmin = sometime
        t = trace.Trace(tmin=tmin, ydata=num.ones(10, dtype=float))
        tmax = t.tmax
        t.extend(tmin-10.2, tmax+10.7)
        assert int(round(tmin-t.tmin)) == 10
        assert int(round(t.tmax-tmax)) == 11
        assert num.all(t.ydata[:10] == num.zeros(10, dtype=float))
        assert num.all(t.ydata[-11:] == num.zeros(11, dtype=float))
        assert num.all(t.ydata[10:-11] == num.ones(10, dtype=float))

        t = trace.Trace(tmin=tmin, ydata=num.arange(10, dtype=float)+1.)
        t.extend(tmin-10.2, tmax+10.7, fillmethod='repeat')
        assert num.all(t.ydata[:10] == num.ones(10, dtype=float))
        assert num.all(t.ydata[-11:] == num.zeros(11, dtype=float)+10.)
        assert num.all(t.ydata[10:-11] == num.arange(10, dtype=float)+1.)

    def testAppend(self):
        a = trace.Trace(ydata=num.zeros(0, dtype=float), tmin=sometime)
        for i in range(10000):
            a.append(num.arange(1000, dtype=float))
        assert a.ydata.size == 10000*1000

    def testDownsampling(self):

        data = [
            (1./125., 1/10., True)]

        for f in [0.1, 1.0, 10.]:
            for i in range(1, 6):
                data.append((f*float(1.), f*float(i), False))

        all_traces = []
        for cut in [True, False]:
            for (dt1, dt2, test_fail) in data:

                for toff in [
                        num.random.random() * dt1 + num.random.random() * dt2]:

                    n = 1024
                    xdata = num.arange(n, dtype=float)
                    ydata = num.exp(-((xdata-n/2)/10.)**2)

                    for orig_snap in (True, False):
                        t = trace.Trace(
                            ydata=ydata,
                            tmin=sometime+toff,
                            deltat=dt1,
                            location='1')

                        if orig_snap:
                            t.snap()

                        t2 = t.copy()
                        if test_fail:
                            with self.assertRaises(
                                    trace.UnavailableDecimation):
                                t2.downsample_to(
                                    dt2,
                                    allow_upsample_max=1,
                                    cut=cut)

                        for snap in (True, False):
                            t2 = t.copy()
                            t2.set_codes(location='2')
                            t2.downsample_to(
                                dt2,
                                allow_upsample_max=10,
                                snap=snap,
                                cut=cut)

                            tpad = trace.downsample_tpad(
                                t.deltat, dt2, allow_upsample_max=10)

                            tcut_before = t2.tmin - t.tmin
                            tcut_after = t.tmax - t2.tmax

                            if not cut:
                                if not snap:
                                    assert tcut_before == 0
                                else:
                                    assert tcut_before < 3 * dt2
                            else:
                                assert 0. <= tcut_before <= tpad

                            assert 0. <= tcut_after <= tpad

                            if snap and orig_snap:
                                assert is_multiple(t2.tmin, t2.deltat, 1e-3)
                            elif snap and not orig_snap:
                                assert abs(
                                    int(round(t2.tmin / t2.deltat)) *
                                    t2.deltat - t2.tmin) <= 0.51*t.deltat

                            tcopy = t.copy()
                            tcopy.set_station('%03i' % (len(all_traces)//2))
                            tcopy.set_location('original')
                            t2copy = t2.copy()
                            t2copy.set_station('%03i' % (len(all_traces)//2))
                            t2copy.set_location('downsampled')
                            all_traces.append(tcopy)
                            all_traces.append(t2copy)

        # trace.snuffle(all_traces)

    def testFiltering(self):
        tmin = sometime
        # b = time.time()
        for i in range(100):
            n = 10000
            t = trace.Trace(
                tmin=tmin, deltat=0.05, ydata=num.ones(n, dtype=float))
            t.lowpass(4,  5.)
            t.highpass(4, 0.1)
        # d1 = time.time() - b
        # b = time.time()
        for i in range(100):
            n = 10000
            t = trace.Trace(
                tmin=tmin, deltat=0.05, ydata=num.ones(n, dtype=float))
            t.bandpass_fft(0.1, 5.)
        # d2 = time.time() - b

        for i in range(100):
            n = 10000
            t = trace.Trace(
                tmin=tmin, deltat=0.05, ydata=num.ones(n, dtype=float))
            t.bandstop(3, 0.1, 5.)
        # d2 = time.time() - b

    def testCropping(self):
        n = 20
        tmin = sometime
        t = trace.Trace(
            tmin=tmin, deltat=0.05, ydata=num.ones(n, dtype=float))
        tmax = t.tmax
        t.ydata[:3] = 0.0
        t.ydata[-3:] = 0.0
        t.crop_zeros()
        assert abs(t.tmin - (tmin + 0.05*3)) < 0.05*0.01
        assert abs(t.tmax - (tmax - 0.05*3)) < 0.05*0.01
        t = trace.Trace(
            tmin=tmin, deltat=0.05, ydata=num.zeros(n, dtype=float))
        ok = False
        try:
            t.crop_zeros()
        except trace.NoData:
            ok = True

        assert ok

        t = trace.Trace(
            tmin=tmin, deltat=0.05, ydata=num.ones(n, dtype=float))
        t.crop_zeros()
        assert t.ydata.size == 20

    def testAdd(self):
        tmin = sometime
        deltat = 0.05
        for distortion in [-0.2, 0.2]:
            for ioffs, result in [(1, [0., 1., 1., 1., 0.]),
                                  (-1, [1., 1., 0., 0., 0.]),
                                  (3, [0., 0., 0., 1., 1.]),
                                  (10, [0., 0., 0., 0., 0.]),
                                  (-10, [0., 0., 0., 0., 0.])]:

                a = trace.Trace(
                    tmin=tmin, deltat=deltat,
                    ydata=num.zeros(5, dtype=float))
                b = trace.Trace(
                    tmin=tmin+(ioffs+distortion)*deltat, deltat=deltat,
                    ydata=num.ones(3, dtype=float))

                a.add(b, interpolate=False)
                assert numeq(a.ydata, result, 0.001)

    def testAdd2(self):
        for toff in num.random.random(100):
            t1 = trace.Trace(
                tmin=sometime, deltat=0.05,
                ydata=num.ones(5, dtype=float))
            t2 = trace.Trace(
                tmin=sometime-toff*0.1, deltat=0.05,
                ydata=num.ones(5, dtype=float))
            t1.add(t2, interpolate=False)

    def testPeaks(self):
        n = 1000
        t = trace.Trace(
            tmin=0, deltat=0.1, ydata=num.zeros(n, dtype=float))
        t.ydata[1] = 1.
        t.ydata[500] = 1.
        t.ydata[999] = 1.
        tp, ap = t.peaks(0.5, 1.)
        assert numeq(tp, [0.1, 50., 99.9], 0.0001)
        assert numeq(ap, [1., 1., 1.], 0.0001)

        t.ydata[504] = 1.0
        t.ydata[511] = 1.0

        tp, ap = t.peaks(0.5, 1.)

        assert numeq(tp, [0.1, 50, 51.1, 99.9], 0.0001)
        assert numeq(ap, [1., 1., 1., 1.], 0.0001)

    def testCorrelate(self):
        for la, lb, mode, res in [
                ([0, 1, .5, 0, 0],    [0, 0, 0, 1, 0],    'same', 0.3),
                ([0, 1, .5, 0, 0, 0], [0, 1, 0],          'valid', 0.1),
                ([0, 1, .5],          [0, 0, 0, 1, 0, 0], 'full', 0.3)]:

            for ia in range(5):
                for ib in range(5):

                    ya = floats(la + [0] * ia)
                    yb = floats(lb + [0] * ib)

                    a = trace.Trace(tmin=10., deltat=0.1, ydata=ya)
                    b = trace.Trace(tmin=10.1, deltat=0.1, ydata=yb)
                    c = trace.correlate(a, b, mode=mode)

                    assert numeq(c.max(), [res, 1.], 0.0001)

    def testCorrelateNormalization(self):

        ya = floats([1, 2, 1])
        yb = floats([0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 2, 1])

        a = trace.Trace(tmin=sometime, deltat=0.1, ydata=ya)
        b = trace.Trace(tmin=sometime, deltat=0.1, ydata=yb)

        c_ab = trace.correlate(a, b)
        c_ab2 = trace.correlate(a, b, normalization='gliding')
        c_ba = trace.correlate(b, a)
        c_ba2 = trace.correlate(b, a, normalization='gliding')
        assert numeq(c_ab.ydata, c_ba.ydata[::-1], 0.001)
        assert numeq(c_ab2.ydata, c_ba2.ydata[::-1], 0.001)

    def testNumpyCorrelate(self):
        primes = num.array(
            [1, 2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31], dtype=int)
        n = 6
        lines = []
        have_flips, have_errs = False, False
        for ia in range(1, n+1):
            for ib in range(1, n+1):

                a = primes[:ia]
                b = primes[ia:ia+ib]

                for mode in 'full', 'valid', 'same':
                    c1 = trace.numpy_correlate_emulate(a, b, mode=mode)
                    c2 = trace.numpy_correlate_fixed(a, b, mode=mode)

                    if a.size < b.size:
                        sl = '<'
                    elif a.size > b.size:
                        sl = '>'
                    else:
                        sl = '='

                    assert c1.dtype == c2.dtype

                    sa = ''
                    if num.all(c1 == c1[::-1]):
                        sa = ' (ambig)'

                    if num.all(c1 == c2):
                        sr = 'ok' + sa
                    elif num.all(c1 == c2[::-1]):
                        have_flips = True
                        sr = 'flip'
                    else:
                        have_errs = True
                        sr = 'err, %s != %s' % (c1, c2)

                    kmin, kmax = trace.numpy_correlate_lag_range(
                        a, b, mode=mode)

                    lines.append(
                        'len(a) = %i, len(b) = %i, '
                        'kmin = %2i, kmax = %2i, (%s), mode = %-6s %s'
                        % (a.size, b.size, kmin, kmax, sl, mode+', ', sr))

        assert not have_flips and not have_errs, '\n'.join(lines)

    def testFFTCorrelate(self):
        for na in range(1, 20):
            for nb in range(1, 20):
                a1 = num.random.random(na)
                a2 = num.random.random(nb)

                t1 = trace.Trace(station='t1', ydata=a1)
                t2 = trace.Trace(station='t2', ydata=a2)

                for mode in 'full', 'same', 'valid':
                    c1 = trace.correlate(t1, t2, mode=mode)
                    c2 = trace.correlate(t1, t2, mode=mode, use_fft=True)
                    c1.set_station('c1')
                    c2.set_station('c2')
                    assert c1.get_ydata().size == c2.get_ydata().size
                    d = num.abs(c1.get_ydata() - c2.get_ydata())

                    if not num.all(d < 1e-5):
                        assert mode == 'same'

                        assert abs(abs(c1.tmin-c2.tmin) - 1.0) < 1e-5
                        assert abs(abs(c1.tmax-c2.tmax) - 1.0) < 1e-5

                        tmin = max(c1.tmin, c2.tmin)
                        tmax = min(c1.tmax, c2.tmax)
                        c1.chop(tmin, tmax, include_last=True)
                        c2.chop(tmin, tmax, include_last=True)

                        d = num.abs(c1.get_ydata() - c2.get_ydata())
                        assert num.all(d < 1e-5)
                    else:
                        assert num.all(d < 1e-5)

    def testMovingSum(self):

        x = num.arange(5)
        assert numeq(
            trace.moving_sum(x, 3, mode='valid'),
            [3, 6, 9], 0.001)
        assert numeq(
            trace.moving_sum(x, 3, mode='full'),
            [0, 1, 3, 6, 9, 7, 4], 0.001)

    def testContinuousDownsample(self):

        y = num.random.random(1000)

        try:
            for (dt1, dt2) in [
                    (0.1, 1.0),
                    (0.2, 1.0),
                    (0.5, 1.0),
                    (0.2, 0.4),
                    (0.4, 1.2)]:

                for tadd in (0.0, 0.01, 0.2, 0.5, 0.7, 0.75):
                    a = trace.Trace(tmin=sometime+tadd, deltat=dt1, ydata=y)
                    bs = [trace.Trace(
                        location='b',
                        tmin=sometime+i*dt1*100+tadd,
                        deltat=dt1,
                        ydata=y[i*100:(i+1)*100]) for i in range(10)]

                    a.downsample_to(dt2, demean=False, snap=True)
                    c2s = []
                    downsampler = trace.co_downsample_to(
                        trace.co_list_append(c2s), dt2)

                    for b in bs:
                        c = downsampler.send(b)
                        c2s.append(c)

                    downsampler.close()
                    assert (round(c2s[0].tmin / dt2) * dt2 - c2s[0].tmin) \
                        / dt1 < 0.5001

        except trace.ScipyBug:
            raise unittest.SkipTest(
                'not supported on installed scipy version')

    def testEqualizeSamplingRates(self):
        y = num.random.random(1000)
        t1 = trace.Trace(tmin=0, ydata=y, deltat=0.01)
        t2 = trace.Trace(tmin=0, ydata=y, deltat=0.5)
        t1_new, t2_new = trace.equalize_sampling_rates(t1, t2)
        self.assertEqual(
            t1_new.deltat, t2_new.deltat,
            'Equalization of sampling rates failed: dt1=%s, dt2=%s'
            % (t1.deltat, t2.deltat))

    def testLxnorm(self):
        yref = num.array([0., 1.5, 2.3, 0., -1.])
        ytest = num.array([-1., 0.3, -0.3, 1., 0.2])
        m, n = trace.Lx_norm(ytest, yref, norm=1)
        self.assertEqual(m, 7., 'L1-norm: m is not 7., but %s' % str(m))
        self.assertEqual(n, 4.8, 'L1-norm: n is not 4.8, but %s' % str(n))

    def testMisfitOfSameTracesZero(self):
        y = num.random.random(10000)
        y -= max(y)*0.5
        t1 = trace.Trace(tmin=0, ydata=y, deltat=0.01)
        t2 = trace.Trace(tmin=0, ydata=y, deltat=0.01)
        # ttraces = [t2]
        fresponse = response.FrequencyResponse()
        taper = trace.CosFader(xfade=2.)
        norms = [1, 2]
        domains = ['time_domain', 'frequency_domain', 'envelope', 'absolute']
        setups = [trace.MisfitSetup(
            norm=n,
            taper=taper,
            domain=domain,
            filter=fresponse) for domain in domains for n in norms]

        for setup in setups:
            m, n, tr, tc = t1.misfit(candidate=t2, setup=setup, debug=True)
            if isinstance(tr, trace.Trace):
                self.assertEqual(tr.tmin, tc.tmin)
                self.assertTrue(all(tr.get_ydata() == tc.get_ydata()))
            else:
                self.assertTrue(all(tc == tr))

            self.assertEqual(m, 0., "misfit's m of equal traces is != 0")

    def testMisfitOfSameTracesDtDifferentShifted(self):
        test_file = common.test_data_file('1989.072.evt.mseed')

        p = pile.make_pile(test_file, show_progress=False)
        rt = p.all()[0]
        tt = rt.copy()

        # make downsampled, chopped copies:
        deltats = [0.5, 1.0, 2.0]
        tt.chop(tmin=rt.tmin+10, tmax=rt.tmax-15)
        tts = [tt.copy() for i in range(len(deltats))]
        [t.downsample_to(deltats[i]) for i, t in enumerate(tts)]

        # shift traces:
        t_shifts = [1.0, 0.49999, 0.5]
        for ts in t_shifts:
            tts_shifted = [t.copy() for t in tts]
            for x in tts_shifted:
                x.shift(ts)
            tts.extend(tts_shifted)

        a = rt.tmin
        d = rt.tmax
        b = a+(d-a)/10.
        c = d-(d-a)/10.

        taper = trace.CosTaper(a, b, c, d)
        fresponse = response.FrequencyResponse()
        norms = [1, 2]
        domains = ['time_domain', 'frequency_domain', 'envelope', 'absolute']
        setups = [trace.MisfitSetup(
            norm=n,
            taper=taper,
            domain=domain,
            filter=fresponse) for domain in domains for n in norms]

        for cand in tts:
            for setup in setups:
                m, n = rt.misfit(candidate=cand, setup=setup)
                self.assertNotEqual(m, None, "misfit's m is None")

    def testMisfitBox(self):

        ydata = num.zeros(9)
        ydata[3:6] = 1.0

        deltat = 0.5

        tr = trace.Trace(
            ydata=ydata,
            deltat=0.5, tmin=0.0)

        tshiftmin = - (tr.tmax - tr.tmin) * 2
        tshiftmax = (tr.tmax - tr.tmin) * 2

        tshifts = num.linspace(tshiftmin, tshiftmax,
                               int(round((tshiftmax-tshiftmin)/deltat))+1)

        candidates = []
        for tshift in tshifts:
            trc = tr.copy()
            trc.shift(tshift)
            candidates.append(trc)

        trace.MisfitSetup(
            norm=2,
            taper=trace.CosTaper(tr.tmin, tr.tmin, tr.tmax, tr.tmax),
            domain='time_domain')

    def testValidateFrequencyResponses(self):
        ttrace = trace.Trace(ydata=num.random.random(1000))
        inverse_eval = response.InverseEvalresp(
            respfile='test.txt',
            trace=ttrace,
            target='vel')

        inverse_eval.validate()

        pzk_response = response.PoleZeroResponse(
            zeros=[0+0j, 0+0j],
            poles=[1+0j, 2+0j],
            constant=10.)

        pzk_response.regularize()

    def testStretch(self):

        n = 100
        ydata = num.ones(n)
        ydata[n//2-10:n//2+10] = 2.0

        deltat = 0.01
        tr1 = trace.Trace(
            location='tr1',
            ydata=ydata,
            deltat=deltat,
            tmin=0.0)

        tr2 = tr1.copy()
        tr2.stretch(tr1.tmin-deltat, tr1.tmax+deltat)
        tr2.set_codes(location='tr2')

        tr3 = tr2.copy()
        tr3.stretch(tr1.tmin, tr1.tmax)
        tr3.set_codes(location='tr3')
        # trace.snuffle([tr1, tr2, tr3])

        assert numeq(tr1.ydata, tr3.ydata, 0.01)

    def benchmark_sinc(self):
        n = 10000000
        i_control = num.array([0., n-1], dtype=num.int64)
        t_control = num.array([0., n-1], dtype=float)
        s_in = num.zeros(n, dtype=float)
        s_out = num.zeros(n, dtype=float)
        tmin = 0.
        deltat = 1.0
        from pyrocko import signal_ext
        t1 = time.time()
        signal_ext.antidrift(i_control, t_control, s_in, tmin, deltat, s_out)
        t2 = time.time()
        print(t2 - t1)

    def test_transfer(self):
        n = 100
        ydata = num.random.random(n)
        deltat = 0.01
        tr1 = trace.Trace(
            location='tr1',
            ydata=ydata,
            deltat=deltat,
            tmin=0.0)
        tr2 = tr1.transfer()
        # tr2.ydata += tr1.ydata.mean()
        assert numeq(tr1.ydata, tr2.ydata, 0.01)

    def test_muliply_taper(self):

        taper = trace.CosTaper(0., 1., 2., 3.)
        taper2 = trace.MultiplyTaper([taper, taper])

        y = num.ones(31)
        taper(y, 0., 0.1)
        taper(y, 0., 0.1)

        z = num.ones(31)
        taper2(z, 0., 0.1)

        assert numeq(y, z, 1e-6)
        assert taper.time_span() == taper2.time_span()

    def test_costaper(self):
        from pyrocko import signal_ext
        x0 = 0.25
        dx = 0.01
        for i in range(100):
            y1 = num.ones(50)
            y2 = y1.copy()
            a, b, c, d = sorted(num.random.random(4))
            signal_ext.apply_costaper(a, b, c, d, y1, x0, dx)
            trace.apply_costaper(a, b, c, d, y2, x0, dx)
            assert numeq(y1, y2, 0.01)

    def test_pickle(self):
        y = num.random.random(10000)
        t1 = trace.Trace(tmin=0, ydata=y, deltat=0.01)
        s = pickle.dumps(t1)
        t2 = pickle.loads(s)
        assert numeq(t1.ydata, t2.ydata, 0.0)

    def test_sta_lta_right(self):

        n = 100
        y = num.zeros(n)
        y[:] = 0.00001

        y[50:52] = num.linspace(0., 1., 2)
        y[52:] = 1.0

        tr = trace.Trace(
            '', 'X', '', '',
            ydata=y, deltat=1.0)

        for itlong in range(1, 20):
            for itshort in range(1, itlong):

                tlong = float(itlong)
                tshort = float(itshort)

                stalta = tr.copy()
                stalta.sta_lta_right(tshort, tlong)
                stalta.set_codes(location='stalta')

                ydata = num.zeros(n)

                sh = int(round(tshort / tr.deltat))
                ln = int(round(tlong / tr.deltat))

                for i in range(ln-sh, n-sh):
                    ydata[i] = (1.0 / sh * num.sum(y[i:i+sh])) / (
                        1.0 / ln * num.sum(y[i+sh-ln:i+sh])) \
                        * float(sh)/float(ln)

                stalta_ref = trace.Trace(
                    '', 'X', 'ref', '',
                    ydata=ydata, deltat=1.0)

                stalta_ref.chop(float(ln-sh), float(n-sh))

                assert numeq(stalta.ydata, stalta_ref.ydata, 1e-3)

    def test_trace_equal(self):
        ydata = num.arange(10)
        tr1 = trace.Trace(ydata=ydata)
        tr2 = trace.Trace(ydata=ydata)

        tr_set = set([tr1, tr2])

        assert len(tr_set), 2

    def test_yaml(self):
        ydata = num.random.random(100)
        tmin = time.time()
        tr1 = trace.Trace(
            'N', 'STA1', '', 'BHZ', tmin=tmin, deltat=0.1, ydata=ydata)

        s = guts.dump(tr1)
        tr2 = guts.load_string(s)

        assert tr1 == tr2

    def test_fill_template(self):
        ydata = num.random.random(61)
        tmin = util.to_time_float(0.0)
        tr1 = trace.Trace(
            'N', 'STA1', '', 'BHZ', tmin=tmin, deltat=1.0, ydata=ydata)

        result = tr1.fill_template(
            '.'.join('%%(%s)s' % x for x in '''
                network station location channel extra
                network_safe station_safe location_safe channel_safe extra_safe
                network_dsafe station_dsafe location_dsafe channel_dsafe
                extra_dsafe
                tmin tmin_ms tmin_us tmin_year tmin_month tmin_day tmin_jday
                tmax tmax_ms tmax_us tmax_year tmax_month tmax_day tmax_jday
                julianday
                abc'''.split()), abc='cde')

        expect = \
            'N.STA1..BHZ..' \
            'N.STA1..BHZ..' \
            'N.STA1._.BHZ._.' \
            '1970-01-01_00-00-00.1970-01-01_00-00-00.000.1970-01-01_00-00-00.000000.1970.01.01.001.' \
            '1970-01-01_00-01-00.1970-01-01_00-01-00.000.1970-01-01_00-01-00.000000.1970.01.01.001.' \
            '1.' \
            'cde'  # noqa

        assert result == expect


if __name__ == '__main__':
    util.setup_logging('test_trace', 'warning')
    unittest.main()
