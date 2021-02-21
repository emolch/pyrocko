# python 2/3
from __future__ import division, print_function, absolute_import
import random
import math
import unittest
import logging
import os.path as op
from tempfile import mkdtemp

from subprocess import check_call
import numpy as num

from pyrocko import util, ahfullgreen, trace, io
from pyrocko.guts import Object, Float, Tuple, List, load

from .. import common

guts_prefix = 'test_ahfull'

logger = logging.getLogger('pyrocko.test.test_ahfull')

km = 1000.


def rand(mi, ma):
    return mi + random.random() * (ma-mi)


def g(trs, sta, cha):
    for tr in trs:
        if tr.station == sta and tr.channel == cha:
            return tr


class AhfullKiwiTestSetupEntry(Object):
    vp = Float.T()
    vs = Float.T()
    density = Float.T()
    x = Tuple.T(3, Float.T())
    f = Tuple.T(3, Float.T())
    m6 = Tuple.T(6, Float.T())
    tau = Float.T()
    deltat = Float.T()


class AhfullKiwiTestSetup(Object):
    setups = List.T(AhfullKiwiTestSetupEntry.T())


class AhfullTestCase(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)

    def _make_test_ahfull_kiwi_data(self):
        trs_all = []
        setups = []
        for i in range(100):
            s = AhfullKiwiTestSetupEntry(
                vp=3600.,
                vs=2000.,
                density=2800.,
                x=(rand(100., 1000.), rand(100., 1000.), rand(100., 1000.)),
                f=(rand(-1., 1.), rand(-1., 1.), rand(-1., 1.)),
                m6=tuple(rand(-1., 1.) for _ in range(6)),
                tau=0.005,
                deltat=0.001)

            def dump(stuff, fn):
                with open(fn, 'w') as f:
                    f.write(' '.join('%s' % x for x in stuff))
                    f.write('\n')

            dn = mkdtemp(prefix='test-ahfull-')
            fn_sources = op.join(dn, 'sources.txt')
            fn_receivers = op.join(dn, 'receivers.txt')
            fn_material = op.join(dn, 'material.txt')
            fn_stf = op.join(dn, 'stf.txt')

            dump((0., 0., 0., 0.) + s.m6 + s.f, fn_sources)
            dump(s.x + (1, 1), fn_receivers)
            dump((s.density, s.vp, s.vs), fn_material)

            nstf = int(round(s.tau * 5. / s.deltat))
            t = num.arange(nstf) * s.deltat
            t0 = nstf * s.deltat / 2.
            stf = num.exp(-(t-t0)**2 / (s.tau/math.sqrt(2.))**2)

            stf = num.cumsum(stf)
            stf /= stf[-1]
            stf[0] = 0.0

            data = num.vstack((t, stf)).T
            num.savetxt(fn_stf, data)

            check_call(
                ['ahfull', fn_sources, fn_receivers, fn_material, fn_stf,
                 '%g' % s.deltat, op.join(dn, 'ahfull'), 'mseed', '0'],
                stdout=open('/dev/null', 'w'))

            fns = [op.join(dn, 'ahfull-1-%s-1.mseed' % c) for c in 'xyz']

            trs = []
            for fn in fns:
                trs.extend(io.load(fn))

            for tr in trs:
                tr.set_codes(
                    station='S%03i' % i,
                    channel={'x': 'N', 'y': 'E', 'z': 'D'}[tr.channel])
                tr.shift(-round(t0/tr.deltat)*tr.deltat)

            trs_all.extend(trs)
            setups.append(s)

        setup = AhfullKiwiTestSetup(setups=setups)

        setup.dump(filename=common.test_data_file_no_download(
            'test_ahfull_kiwi_setup.yaml'))
        io.save(trs_all, common.test_data_file_no_download(
            'test_ahfull_kiwi_traces.mseed'))

    def test_ahfull_kiwi(self):
        setup = load(filename=common.test_data_file(
            'test_ahfull_kiwi_setup.yaml'))
        trs_ref = io.load(common.test_data_file(
            'test_ahfull_kiwi_traces.mseed'))

        for i, s in enumerate(setup.setups):
            d3d = math.sqrt(s.x[0]**2 + s.x[1]**2 + s.x[2]**2)

            tlen = d3d / s.vs * 2

            n = int(num.round(tlen / s.deltat))

            out_x = num.zeros(n)
            out_y = num.zeros(n)
            out_z = num.zeros(n)

            ahfullgreen.add_seismogram(
                s.vp, s.vs, s.density, 1000000.0, 1000000.0, s.x, s.f, s.m6,
                'displacement',
                s.deltat, 0.,
                out_x, out_y, out_z,
                ahfullgreen.AhfullgreenSTFGauss(tau=s.tau))

            trs = []
            for out, comp in zip([out_x, out_y, out_z], 'NED'):
                tr = trace.Trace(
                    '', 'S%03i' % i, 'P', comp,
                    deltat=s.deltat, tmin=0.0, ydata=out)

                trs.append(tr)

            trs2 = []

            for cha in 'NED':

                t1 = g(trs, 'S%03i' % i, cha)
                t2 = g(trs_ref, 'S%03i' % i, cha)

                tmin = max(t1.tmin, t2.tmin)
                tmax = min(t1.tmax, t2.tmax)

                t1 = t1.chop(tmin, tmax, inplace=False)
                t2 = t2.chop(tmin, tmax, inplace=False)

                trs2.append(t2)

                d = 2.0 * num.sum((t1.ydata - t2.ydata)**2) / \
                    (num.sum(t1.ydata**2) + num.sum(t2.ydata**2))

                if d >= 0.02:
                    print(d)
                    # trace.snuffle([t1, t2])

                assert d < 0.02

            # trace.snuffle(trs + trs2)


if __name__ == '__main__':
    util.setup_logging('test_ahfull', 'warning')
    unittest.main()
