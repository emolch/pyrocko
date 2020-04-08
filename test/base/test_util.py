from __future__ import division, print_function, absolute_import
import re
import sys
import unittest
import tempfile
import shutil
import time
import os
from random import random
import numpy as num
from pyrocko import util

try:
    range = xrange
except NameError:
    pass


class UtilTestCase(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.tempdir = tempfile.mkdtemp()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tempdir)

    def fpath(self, fn):
        return os.path.join(self.tempdir, fn)

    def testTime(self):

        for fmt, accu in zip(
                ['%Y-%m-%d %H:%M:%S.3FRAC', '%Y-%m-%d %H:%M:%S.2FRAC',
                 '%Y-%m-%d %H:%M:%S.1FRAC', '%Y-%m-%d %H:%M:%S',
                 '%Y-%m-%d %H.%M.%S.3FRAC'],
                [0.001, 0.01, 0.1, 1., 0.001, 0.001]):

            ta = util.str_to_time('1960-01-01 10:10:10')
            tb = util.str_to_time('2020-01-01 10:10:10')

            for i in range(10000):
                t1 = ta + random() * (tb-ta)
                s = util.time_to_str(t1, format=fmt)
                t2 = util.str_to_time(s, format=fmt)
                assert abs(t1 - t2) < accu
                fmt_opt = re.sub(r'\.[0-9]FRAC$', '', fmt) + '.OPTFRAC'
                t3 = util.str_to_time(s, format=fmt_opt)
                assert abs(t1 - t3) < accu

    def testTimeRange(self):
        tmin, tmax = util.get_working_system_time_range()[:2]
        stmin, stmax = map(util.time_to_str, (tmin, tmax))
        tmin2, tmax2 = map(util.str_to_time, (stmin, stmax))
        assert tmin == tmin2
        assert tmax == tmax2
        if sys.maxsize > 2**32:
            assert tmax - tmin > 200*365*24*60*60

    def testBigTime(self):
        ymin, ymax = util.get_working_system_time_range()[2:]
        s = '2500-01-01 00:00:00.000'
        if ymin <= 2500 <= ymax:
            tx = util.str_to_time(s)
            assert s == util.time_to_str(tx)

        else:
            with self.assertRaises(util.TimeStrError):
                util.str_to_time(s)

    def testIterTimes(self):

        tmin = util.str_to_time('1999-03-20 20:10:10')
        tmax = util.str_to_time('2001-05-20 10:00:05')

        ii = 0
        for ymin, ymax in util.iter_years(tmin, tmax):
            for mmin, mmax in util.iter_months(ymin, ymax):
                ii += 1
                s1 = util.time_to_str(mmin)
                s2 = util.time_to_str(mmax)

        assert ii == 12*3
        assert s1 == '2001-12-01 00:00:00.000'
        assert s2 == '2002-01-01 00:00:00.000'

    def testTimeError(self):
        ok = False
        try:
            util.str_to_time('abc')
        except util.TimeStrError:
            ok = True

        assert ok

    def benchmark_stt_tts(self):
        for x in range(2):
            if x == 1:
                util.util_ext = None
            t = util.str_to_time('1999-03-20 20:10:10')
            tt1 = time.time()
            for i in range(10000):
                s = util.tts(t)
                util.stt(s)

            tt2 = time.time()
            print(tt2 - tt1)

    def test_consistency_merge(self):
        data = [
            ('a', 1, 2, 3.),
            ('a', 2, 2, 3.),
            ('a', 1, 2, 3.)]

        merged = util.consistency_merge(data, error='ignore')
        assert merged == (1, 2, 3.0)

    def test_leap_seconds(self):
        from_sys = {}
        import platform
        if platform.system() != 'Darwin':
            for t, n in util.read_leap_seconds():  # not available on Mac OS X
                from_sys[t] = n

        for t, n in util.read_leap_seconds2():
            if t in from_sys:
                assert from_sys[t] == n

    def test_gps_utc_offset(self):
        for t_utc_0 in [x[0] for x in util.read_leap_seconds2()]:
            t_utc_0 = float(t_utc_0)
            ts_utc = num.linspace(
                t_utc_0 - 2.0, t_utc_0 + 2.0, 17)

            for t_utc in ts_utc:
                t_gps = t_utc + util.gps_utc_offset(t_utc)
                t_utc2 = t_gps + util.utc_gps_offset(t_gps)

                self.assertEqual(util.tts(t_utc), util.tts(t_utc2))

            ts_gps = num.linspace(
                ts_utc[0] + util.gps_utc_offset(ts_utc[0]),
                ts_utc[-1] + util.gps_utc_offset(ts_utc[-1]), 17 + 4)

            t_utc_wrapped = []
            for t_gps in ts_gps:
                t_utc = t_gps + util.utc_gps_offset(t_gps)
                t_utc_wrapped.append(t_utc - t_utc_0)

            num.testing.assert_almost_equal(
                t_utc_wrapped,
                num.concatenate((
                    num.linspace(-2.0, 0.75, 12),
                    num.linspace(0.0, 2.0, 9))))

    def test_plf_integration(self):
        import numpy as num

        x = num.array([1., 1., 3., 3.])
        y = num.array([0., 1., 1., 0.])
        x_edges = num.array([0.5, 1.5, 2.5, 3.5])
        yy = util.plf_integrate_piecewise(x_edges, x, y)
        assert num.all(num.abs(yy - num.array([0.5, 1.0, 0.5])) < 1e-6)

        x = num.array([0., 1., 2., 3.])
        y = num.array([0., 1., 1., 0.])
        x_edges = num.array([0., 1., 2., 3.])
        yy = util.plf_integrate_piecewise(x_edges, x, y)
        assert num.all(num.abs(yy - num.array([0.5, 1.0, 0.5])) < 1e-6)

    def test_arange2(self):
        num.testing.assert_almost_equal(
            util.arange2(0., 1., 0.1), num.linspace(0., 1., 11))

        with self.assertRaises(util.ArangeError):
            util.arange2(0., 1.05, 0.1)

        num.testing.assert_almost_equal(
            util.arange2(0., 1.04, 0.1, error='round'),
            num.linspace(0., 1., 11))

        num.testing.assert_almost_equal(
            util.arange2(0., 1.05, 0.1, error='floor'),
            num.linspace(0., 1., 11))

        num.testing.assert_almost_equal(
            util.arange2(0., 1.05, 0.1, error='ceil'),
            num.linspace(0., 1.1, 12))

    def test_gform(self):
        s = ''
        for i in range(-11, 12):
            v = 1/3. * 10**i
            s += '|%s|\n' % util.gform(v)

        self.assertEqual(s.strip(), '''
|   3.33E-12 |
|   3.33E-11 |
|   3.33E-10 |
|   3.33E-09 |
|   3.33E-08 |
|   3.33E-07 |
|   3.33E-06 |
|   3.33E-05 |
|   3.33E-04 |
|   3.33E-03 |
|   3.33E-02 |
|   0.333    |
|   3.33     |
|  33.3      |
| 333.       |
|   3.33E+03 |
|   3.33E+04 |
|   3.33E+05 |
|   3.33E+06 |
|   3.33E+07 |
|   3.33E+08 |
|   3.33E+09 |
|   3.33E+10 |'''.strip())

    def test_download(self):
        fn = self.fpath('responses.xml')
        url = 'https://data.pyrocko.org/examples/responses.xml'

        stat = []

        def status(d):
            stat.append(d)

        util.download_file(url, fn, status_callback=status)

        url = 'https://data.pyrocko.org/testing/my_test_dir'
        dn = self.fpath('my_test_dir')
        util.download_dir(url, dn, status_callback=status)

        d = stat[-1]

        dwant = {
            'ntotal_files': 4,
            'nread_files': 4,
            'ntotal_bytes_all_files': 22,
            'nread_bytes_all_files': 22,
            'ntotal_bytes_current_file': 8,
            'nread_bytes_current_file': 8}

        for k in dwant:
            assert k in d
            assert d[k] == dwant[k]

    def test_threadpoolctl_or_dummy(self):
        threadpool_limits = util.get_threadpool_limits()

        with threadpool_limits(limits=1, user_api='blas'):
            pass


if __name__ == "__main__":
    util.setup_logging('test_util', 'info')
    unittest.main()
