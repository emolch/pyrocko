from __future__ import division, print_function, absolute_import
import random
import unittest
import multiprocessing
import os
from itertools import product
from collections import defaultdict
import numpy as num
from ..common import TEST_CUDA, measure, require_gui, require_cuda
from ..common import implementations as _implementations

from pyrocko import util, trace, autopick

from pyrocko.parstack import (
    parstack_kernel_parameters, check_parstack_implementation_compatibility,
    CUDA_COMPILED, parstack, get_offset_and_length)

# remove unimplemented
implementations = set(_implementations) - {'cuda_thrust'}

implementations = [
    impl for impl in _implementations
    if check_parstack_implementation_compatibility(impl=impl)]


def g(list_, a):
    return num.array([getattr(x, a) for x in list_])


class ParstackTestCase(unittest.TestCase):

    def test_has_cuda_compiled_flag(self):
        assert isinstance(CUDA_COMPILED, int)

    def test_parstack(self):
        print('testing %s ' % implementations, end='', flush=True)
        for dtype, precision in [(num.float32, 5), (num.float64, 9)]:
            for i in range(100):
                narrays = random.randint(1, 5)
                arrays = [
                    num.random.random(random.randint(5, 10)).astype(dtype)
                    for j in range(narrays)
                ]
                offsets = num.random.randint(
                    -5, 6, size=narrays).astype(num.int32)
                nshifts = random.randint(1, 10)
                shifts = num.random.randint(
                    -5, 6, size=(nshifts, narrays)).astype(num.int32)
                weights = num.random.random((nshifts, narrays)).astype(dtype)

                for method in (0, 1):
                    for nparallel in range(1, 5):
                        rs, os = [], []
                        for impl in implementations:
                            r, o = parstack(
                                arrays, offsets, shifts, weights,
                                method=method,
                                impl=impl,
                                nparallel=nparallel)
                            rs.append(r)
                            os.append(num.array(o))

                        for r in rs:
                            num.testing.assert_almost_equal(
                                r, rs[0], decimal=precision)
                        for o in os:
                            num.testing.assert_equal(o, os[0])

    def test_parstack_limited(self, runs=10):
        print('testing %s ' % implementations, end='', flush=True)
        dtypes = [(num.float32, 5), (num.float64, 9)]
        for (dtype, precision), run in product(dtypes, range(runs)):
            print('still going (%s, %d/%d) ...' % (
                dtype.__name__, run + 1, runs))
            narrays = random.randint(1, 5)
            arrays = [
                num.random.random(random.randint(5, 10)).astype(dtype)
                for j in range(narrays)
            ]
            offsets = num.random.randint(-5, 6, size=narrays).astype(num.int32)
            nshifts = random.randint(1, 10)
            shifts = num.random.randint(
                -5, 6, size=(nshifts, narrays)).astype(num.int32)
            weights = num.random.random((nshifts, narrays)).astype(dtype)

            for nparallel in range(1, 5):
                r1, o1 = parstack(
                    arrays, offsets, shifts, weights,
                    method=0,
                    nparallel=nparallel,
                    impl='openmp')

                for impl in implementations:
                    r2, o2 = parstack(
                        arrays, offsets, shifts, weights,
                        method=0,
                        lengthout=r1.shape[1],
                        offsetout=o1,
                        impl=impl,
                        nparallel=nparallel)

                    assert o1 == o2
                    num.testing.assert_almost_equal(
                        r1, r2, decimal=precision)

                    n = r1.shape[1]
                    for k in range(n):
                        r3, o3 = parstack(
                            arrays, offsets, shifts, weights,
                            method=0,
                            lengthout=n,
                            offsetout=o1 - k,
                            nparallel=nparallel,
                            impl=impl)

                        assert o3 == o1 - k
                        num.testing.assert_almost_equal(
                            r1[:, :n - k], r3[:, k:], decimal=precision)

                        for k in range(n):
                            r3, o3 = parstack(
                                arrays, offsets, shifts, weights,
                                method=0,
                                lengthout=n,
                                offsetout=o1 + k,
                                nparallel=nparallel,
                                impl=impl)

                            assert o3 == o1 + k
                            num.testing.assert_almost_equal(
                                r1[:, k:], r3[:, :n - k], decimal=precision)

                            for k in range(n):
                                r3, o3 = parstack(
                                    arrays, offsets, shifts, weights,
                                    method=0,
                                    lengthout=n - k,
                                    offsetout=o1,
                                    nparallel=nparallel,
                                    impl=impl)

                                assert o3 == o1
                                num.testing.assert_almost_equal(
                                    r1[:, :n - k], r3[:, :], decimal=precision)

    def test_parstack_cumulative(self):
        print('testing %s ' % implementations, end='', flush=True)
        for dtype, precision in [(num.float32, 5), (num.float64, 9)]:
            for i in range(10):
                narrays = random.randint(1, 5)
                arrays = [
                    num.random.random(random.randint(5, 10)).astype(dtype)
                    for i in range(narrays)
                ]
                offsets = num.random.randint(
                    -5, 6, size=narrays).astype(num.int32)
                nshifts = random.randint(1, 10)
                shifts = num.random.randint(
                    -5, 6, size=(nshifts, narrays)).astype(num.int32)
                weights = num.random.random((nshifts, narrays)).astype(dtype)

                for method in (0,):
                    for nparallel in range(1, 4):
                        for impl in implementations:
                            result, offset = parstack(
                                arrays, offsets, shifts, weights, method,
                                result=None,
                                nparallel=nparallel,
                                impl=impl)

                            result1 = result.copy()
                            for k in range(5):
                                result, offset = parstack(
                                    arrays, offsets, shifts, weights, method,
                                    result=result,
                                    nparallel=nparallel,
                                    impl=impl)

                                num.testing.assert_almost_equal(
                                    result, result1 * (k + 2.),
                                    decimal=precision)

    def _generate_random_samples(
            self, narrays, nshifts, nsamples,
            index_dtype=num.int32, dtype=num.float32):
        if not isinstance(dtype, (list, tuple)):
            dtype = (dtype, dtype,)
        if not isinstance(index_dtype, (list, tuple)):
            index_dtype = (index_dtype, index_dtype,)

        arrays = []
        for iarray in range(narrays):
            arrays.append(num.random.random(
                random.randint(0.5 * nsamples, nsamples)).astype(dtype[0]))

        offsets = num.arange(narrays, dtype=index_dtype[0])
        shifts = num.random.randint(
            -5, 6, size=(nshifts, narrays)).astype(index_dtype[1])
        weights = num.ones((nshifts, narrays), dtype=dtype[1])
        return arrays, shifts, offsets, weights

    @require_cuda
    def test_performance(self, narrays=5000, nshifts=5000, nsamples=100):
        impls_to_test = ['cuda', 'cuda_atomic']
        print('testing %s ' % impls_to_test, end='', flush=True)
        print(narrays, nshifts, nsamples)
        arrays, shifts, offsets, weights = self._generate_random_samples(
            narrays=narrays, nshifts=nshifts, nsamples=100)

        args = (arrays, offsets, shifts, weights,)
        kwargs = dict(
                method=0,
                nparallel=multiprocessing.cpu_count(),
                target_block_threads=256)

        (r, o), t = measure(parstack, 1, *args, impl='openmp', **kwargs)
        print('openmp time: %.6f' % t)
        for impl in impls_to_test:
            (r2, o2), t2 = measure(parstack, 1, *args, impl=impl, **kwargs)
            print('%s time: %.6f' % (impl, t2))
            assert r.shape == r2.shape
            num.testing.assert_almost_equal(r, r2, decimal=4)

    @require_cuda
    def test_parstack_kernel_parameters(self, verbose=False):
        for dtype, precision in [(num.float32, 5), (num.float64, 9)]:
            for setting in product(*[[100, 500, 5000] for _ in range(3)]):
                narrays, nshifts, nsamples = setting
                arrays, shifts, offsets, weights = \
                    self._generate_random_samples(narrays=narrays,
                                                  nshifts=nshifts,
                                                  nsamples=100,
                                                  dtype=dtype)
                lengths = num.array([a.size for a in arrays], dtype=num.int)
                offsetout, lengthout = get_offset_and_length(
                    arrays, lengths, offsets, shifts)

                # compute the kernel launch parameters
                grid, blocks, shared_mem = parstack_kernel_parameters(
                    narrays, nshifts, nsamples, lengthout, offsetout,
                    target_block_threads=256)
                if verbose:
                    print('----')
                    print(
                        'problem size:',
                        setting,
                        'grid:',
                        grid,
                        'blocks:',
                        blocks,
                        'shared mem:',
                        shared_mem)
            assert num.prod(blocks) * 8 < 48 * 1024

    def benchmark(self, plot=False, data_gen='random'):
        from datetime import datetime
        print('testing %s ' % implementations, end='', flush=True)

        plot = plot or 'PLOT_BENCHMARK' in os.environ
        time = datetime.now().strftime('%d_%m_%Y_%H_%M_%S')
        longest_impl_name = 5 + max([len(impl) for impl in implementations])

        _bench_size = 3
        _narrays = (100, 500, 5000, 8_000)[:_bench_size]
        _nshifts = (100, 500, 5000, 8_000)[:_bench_size]
        _nsamples = (100, 500, 5000, 8_000)[:_bench_size]

        for dtype, precision in [(num.float32, 2), (num.float64, 9)]:
            for method in (0, 1):
                results = defaultdict(dict)
                settings = list(product(
                    _narrays, _nshifts, _nsamples
                ))
                for setting in settings:
                    narrays, nshifts, nsamples = setting
                    config = dict(
                        narrays=narrays, nshifts=nshifts, nsamples=nsamples)

                    print('==========')
                    print('type', dtype.__name__, 'method', method, '\t'.join(
                        ['%s=%d' % c for c in config.items()]))
                    print('==========')

                    warmup = dict(numpy=0, omp=0, cuda=2, cuda_atomic=2)
                    nrepeats = dict(numpy=1, omp=3, cuda=3, cuda_atomic=3)

                    arrays = []
                    for iarray in range(narrays):
                        data = num.arange(nsamples, dtype=dtype)
                        if data_gen == 'random':
                            data = num.random.random(
                                random.randint(0.5 * nsamples, nsamples)
                            ).astype(dtype)
                        arrays.append(data)

                    offsets = num.arange(narrays, dtype=num.int32)
                    shifts = num.zeros((nshifts, narrays), dtype=num.int32)
                    shifts = num.random.randint(
                        -5, 6, size=(nshifts, narrays)).astype(num.int32)
                    weights = num.ones((nshifts, narrays), dtype=dtype)

                    cpu_threads = multiprocessing.cpu_count()
                    confs = [('numpy', 1, 1)]
                    if TEST_CUDA:
                        # cuda_atomic is agnostic to thread block sizes
                        confs.append(('cuda_atomic', cpu_threads, 256))
                        for cuda_threads in [2**i for i in range(5, 11)]:
                            confs.append(('cuda', cpu_threads, cuda_threads))
                    for nparallel in range(
                            0, cpu_threads + 1, cpu_threads // 4):
                        confs.append(('openmp', max(1, nparallel), 1))

                    temp_res = []
                    reference = None
                    for impl, nparallel, cuda_threads in confs:
                        measure(parstack, warmup.get(impl, 0),
                                arrays, offsets, shifts, weights, method=0,
                                impl=impl, nparallel=nparallel,
                                target_block_threads=cuda_threads)

                        rpt = nrepeats.get(impl, 1)
                        (r, o), t = measure(parstack, rpt,
                                            arrays, offsets, shifts,
                                            weights, method=0, impl=impl,
                                            nparallel=nparallel,
                                            target_block_threads=cuda_threads)
                        temp_res.append((r, impl))
                        if impl == 'numpy':
                            reference = t

                        ndigits = 2
                        score = nsamples * nshifts / t / 1e6
                        speedup = 1 if reference is None else round(
                            reference / t, ndigits)
                        print('\t'.join(['%s=%s' % metric for metric in dict(
                            impl=str(impl).ljust(longest_impl_name),
                            nparallel=str(nparallel).ljust(2),
                            cuda_threads=str(cuda_threads).ljust(4),
                            score=str(
                                round(
                                    score,
                                    ndigits)).ljust(
                                3 +
                                1 +
                                ndigits),
                            speedup=str(speedup).ljust(5 + 1 + ndigits),
                            t=str(round(t, 5))
                        ).items()]))

                        if impl not in results[setting]:
                            results[setting][impl] = t
                        results[setting][impl] = min(t, results[setting][impl])

                    for r, _ in temp_res:
                        num.testing.assert_almost_equal(
                            r, temp_res[0][0], decimal=precision)

                print('==========')
                print('TYPE', dtype.__name__, 'METHOD', method, 'SUMMARY')
                print('==========')
                benchmarked = set()

                # compute average speedups
                speedups = defaultdict(list)
                for setting, res in results.items():
                    for impl, t in res.items():
                        speedups[impl].append(res['numpy'] / t)
                for impl, sups in speedups.items():
                    benchmarked.add(impl)
                    print(impl.ljust(longest_impl_name),
                          '\tavg speedup over numpy: %s x' % (
                              str(round(sum(sups) / len(sups), 3))))
                print('==========')

                # fastest implementations for specific problem sizes
                winners = defaultdict(list)
                for setting, res in results.items():
                    fastest = sorted(res.items(), key=lambda x: x[1])
                    winner, _ = fastest[0]
                    winners[winner].append(setting)
                for impl in benchmarked:
                    settings_won = winners[impl]
                    print(impl.ljust(longest_impl_name),
                          '\twon %d/%d:\t' % (
                              len(settings_won), len(settings)), settings_won)
                print('==========')
                if plot:
                    self._plot_benchmark_results(
                        results,
                        filename='bm_parstack_%s_%s_method_%d.pdf' % (
                            time, dtype.__name__, method))

    def _plot_benchmark_results(self, results, filename='bm_parstack.pdf'):
        import matplotlib.pyplot as plt

        impl = defaultdict(list)
        for setting, res in results.items():
            for imp, t in res.items():
                impl[imp].append(t)
        del impl['numpy']  # exclude numpy because it is much slower

        samples = len(results)
        bars = len(impl)
        fig, ax = plt.subplots()
        x = (bars + 1) * num.arange(samples)  # the label locations

        for idx, (imp, values) in enumerate(impl.items()):
            ax.bar(x + idx + 0.5, values, 1, label=imp)

        ax.set_ylabel('time (s)')
        ax.set_xlabel('narrays, nshifts, nsamples')
        ax.set_title(filename)
        fig.set_size_inches(20, 10)
        ax.set_xticks(x + bars / 2)
        ax.set_xticklabels(results.keys(), rotation=90)
        ax.legend()
        fig.tight_layout()

        test_base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(test_base_dir, '../benchmark')
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, filename)
        plt.savefig(output_file)
        print('saved results to ', output_file)

    @unittest.skip('needs manual inspection')
    @require_gui
    def _off_test_synthetic(self):
        from pyrocko import gf

        km = 1000.
        nstations = 10
        edepth = 5*km
        store_id = 'crust2_d0'

        swin = 2.
        lwin = 9.*swin
        ks = 1.0
        kl = 1.0
        kd = 3.0

        engine = gf.get_engine()
        snorths = (num.random.random(nstations)-1.0) * 50*km
        seasts = (num.random.random(nstations)-1.0) * 50*km
        targets = []
        for istation, (snorths, seasts) in enumerate(zip(snorths, seasts)):
            targets.append(
                gf.Target(
                    quantity='displacement',
                    codes=('', 's%03i' % istation, '', 'Z'),
                    north_shift=float(snorths),
                    east_shift=float(seasts),
                    store_id=store_id,
                    interpolation='multilinear'))

        source = gf.DCSource(
            north_shift=50*km,
            east_shift=50*km,
            depth=edepth)

        store = engine.get_store(store_id)

        response = engine.process(source, targets)
        trs = []

        station_traces = defaultdict(list)
        station_targets = defaultdict(list)
        for source, target, tr in response.iter_results():
            tp = store.t('any_P', source, target)
            t = tp - 5 * tr.deltat + num.arange(11) * tr.deltat
            if False:
                gauss = trace.Trace(
                    tmin=t[0],
                    deltat=tr.deltat,
                    ydata=num.exp(-((t-tp)**2)/((2*tr.deltat)**2)))

                tr.ydata[:] = 0.0
                tr.add(gauss)

            trs.append(tr)
            station_traces[target.codes[:3]].append(tr)
            station_targets[target.codes[:3]].append(target)

        station_stalta_traces = {}
        for nsl, traces in station_traces.items():
            etr = None
            for tr in traces:
                sqr_tr = tr.copy(data=False)
                sqr_tr.ydata = tr.ydata**2
                if etr is None:
                    etr = sqr_tr
                else:
                    etr += sqr_tr

            autopick.recursive_stalta(swin, lwin, ks, kl, kd, etr)
            etr.set_codes(channel='C')

            station_stalta_traces[nsl] = etr

        trace.snuffle(trs + list(station_stalta_traces.values()))
        deltat = trs[0].deltat

        nnorth = 50
        neast = 50

        size = 200*km

        north = num.linspace(-size, size, nnorth)
        north2 = num.repeat(north, neast)
        east = num.linspace(-size, size, neast)
        east2 = num.tile(east, nnorth)
        depth = 5*km

        def tcal(target, i):
            try:
                return store.t(
                    'any_P',
                    gf.Location(
                        north_shift=north2[i],
                        east_shift=east2[i],
                        depth=depth),
                    target)

            except gf.OutOfBounds:
                return 0.0

        nsls = sorted(station_stalta_traces.keys())

        tts = num.fromiter((tcal(station_targets[nsl][0], i)
                            for i in range(nnorth*neast)
                            for nsl in nsls), dtype=num.float)

        arrays = [
            station_stalta_traces[nsl].ydata.astype(num.float) for nsl in nsls]
        offsets = num.array(
            [int(round(station_stalta_traces[nsl].tmin / deltat))
             for nsl in nsls], dtype=num.int32)
        shifts = -num.array(
            [int(round(tt / deltat))
             for tt in tts], dtype=num.int32).reshape(
                 nnorth * neast, nstations)
        weights = num.ones((nnorth * neast, nstations))

        print(shifts[25 * neast + 25] * deltat)

        print(offsets.dtype, shifts.dtype, weights.dtype)

        print('stack start')
        mat, ioff = parstack(arrays, offsets, shifts, weights, 1)
        print('stack stop')

        mat = num.reshape(mat, (nnorth, neast))

        from matplotlib import pyplot as plt

        fig = plt.figure()

        axes = fig.add_subplot(1, 1, 1, aspect=1.0)

        axes.contourf(east/km, north/km, mat)

        axes.plot(
            g(targets, 'east_shift')/km,
            g(targets, 'north_shift')/km, '^')
        axes.plot(source.east_shift/km, source.north_shift / km, 'o')
        plt.show()

    def test_checks_index_data_type(self):
        print('testing %s ' % implementations, end='', flush=True)
        for dtypes in product(*[[num.int32, num.int64]] * 2):
            arrays, shifts, offsets, weights = self._generate_random_samples(
                narrays=100, nshifts=100, nsamples=100, index_dtype=dtypes)

            for impl, method in product(implementations, (0, 1)):
                if not all([dt == num.int32 for dt in dtypes]):
                    with self.assertRaises(ValueError):
                        parstack(arrays, offsets, shifts, weights,
                                 method=method, impl=impl)
                else:
                    parstack(arrays, offsets, shifts, weights,
                             method=method, impl=impl)

    def test_checks_input_data_type(self):
        print('testing %s ' % implementations, end='', flush=True)
        for dtypes in product(*[[num.float32, num.float64]] * 2):
            arrays, shifts, offsets, weights = self._generate_random_samples(
                narrays=100, nshifts=100, nsamples=100, dtype=dtypes)

            for impl, method in product(implementations, (0, 1)):
                if any([dt != dtypes[0] for dt in dtypes]):
                    # raises exception when mixing up float and double
                    with self.assertRaises(ValueError):
                        parstack(arrays, offsets, shifts, weights,
                                 method=method, impl=impl)
                else:
                    # result should be of the same data type
                    r, _ = parstack(arrays, offsets, shifts, weights,
                                    method=method, impl=impl)
                    self.assertEqual(r.dtype, dtypes[0])

    def test_limited(self):
        print('testing %s ' % implementations, end='', flush=True)
        for dtype, precision in [(num.float32, 6), (num.float64, 9)]:
            for impl in implementations:
                arrays = [
                    num.array([0, 0, 0, 0, 0, 0, 0, 1, 0, -1, 0],
                              dtype=dtype),
                    num.array([0, 0, 0, 0, 0, 0, 1, 0, -1, 0, 0],
                              dtype=dtype),
                    num.array([0, 0, 0, 0, 0, 1, 0, -1, 0, 0, 0],
                              dtype=dtype)]

                offsets = num.array([0, 0, 0], dtype=num.int32)
                shifts = -num.array([
                    [8, 7, 6],
                    [7, 6, 5],
                    [6, 5, 4]], dtype=num.int32)

                weights = num.ones((3, 3), dtype=dtype)
                lengths = num.array([a.size for a in arrays], dtype=num.int)
                ioff_total, nsamples_total = get_offset_and_length(
                    arrays, lengths, offsets, shifts)
                mat, ioff = parstack(
                    arrays, offsets, shifts, weights, method=0, impl=impl)
                mat0, ioff = parstack(
                    arrays, offsets, shifts, weights, method=0, impl=impl)

                neach = 3
                for ioff in range(0, nsamples_total, 3):
                    mat, ioff_check = parstack(
                        arrays, offsets, shifts, weights, 0,
                        nparallel=1,
                        impl=impl,
                        offsetout=ioff_total + ioff,
                        lengthout=neach)

                    assert ioff_total + ioff == ioff_check

                    num.testing.assert_almost_equal(
                        mat0[:, ioff:ioff + neach], mat, decimal=precision)


if __name__ == '__main__':
    util.setup_logging('test_parstack', 'debug')
    util.setup_logging('test_limited', 'debug')
    util.setup_logging('test_parstack_cumulative', 'debug')
    util.setup_logging('test_parstack_limited', 'debug')
    unittest.main()
