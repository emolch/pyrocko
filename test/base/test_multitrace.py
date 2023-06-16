
import unittest

import numpy as num

from pyrocko import trace, multitrace
from pyrocko import util


class MultiTraceTestCase(unittest.TestCase):

    def random_traces(
            self,
            tmin=util.str_to_time('1970-01-01 00:00:00'),
            n=10,
            deltat_choices=[0.5, 1., 2.],
            toffset_range=[-5., 5.],
            tlen_range=[200., 300.],
            dtype_choices=[float, int, num.int32]):

        tpad = max(
            trace.downsample_tpad(
                deltat, max(deltat_choices), allow_upsample_max=5)
            for deltat in deltat_choices)

        tpad += num.max(num.abs(toffset_range))

        tmin = tmin - tpad

        toffset = num.random.uniform(*toffset_range, n)
        deltats = num.random.choice(deltat_choices, n)
        tlens = num.random.uniform(*tlen_range, n) + 2 * tpad
        nsamples = (tlens / deltats).astype(int)
        dtypes = num.random.choice(dtype_choices, n)

        trs = []
        for i in range(n):
            data = num.random.normal(0., 1000., nsamples[i]).astype(dtypes[i])
            trs.append(trace.Trace(
                'NX', 'S%03i' % i, 'RAW', 'Z',
                tmin=tmin+toffset[i],
                deltat=deltats[i],
                ydata=data))

        return trs

    def test_creation(self):
        tmin = util.str_to_time('2023-06-13 00:00:00')
        tlen_range = [200., 300.]
        traces = self.random_traces(n=100, tmin=tmin, tlen_range=tlen_range)
        traces = trace.make_traces_compatible(traces)
        mt = multitrace.MultiTrace(traces)
        assert mt.tmin <= tmin
        assert mt.tmax >= tmin + tlen_range[0]
        # mt.snuffle()

    def test_downsample(self):
        traces = self.random_traces(n=100)
        for tr in traces:
            tpad = trace.downsample_tpad(tr.deltat, 2.)
            tr_orig = tr.copy()
            tr.downsample_to(2., cut=True, snap=True)
            assert tr.tmin <= tr_orig.tmin + tpad
            assert tr_orig.tmax - tpad <= tr.tmax
