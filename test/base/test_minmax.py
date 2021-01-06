from __future__ import division, print_function, absolute_import
import unittest
import itertools
import multiprocessing
from itertools import product
import numpy as num
from ..common import measure, require_cuda
from ..common import implementations as _implementations

from pyrocko import util
from pyrocko.minmax import (
    CUDA_COMPILED,
    max_2d,
    min_2d,
    argmax_2d,
    argmin_2d,
    minmax_kernel_parameters,
)

# remove unimplemented
implementations = set(_implementations) - {"cuda_atomic", "numpy"}


class MinMaxTestCase(unittest.TestCase):
    def test_has_cuda_compiled_flag(self):
        assert isinstance(CUDA_COMPILED, int)

    @require_cuda
    def test_minmax_kernel_parameters(self, verbose=False):
        for setting in product(*[[100, 500, 5000] for _ in range(2)]):
            nx, ny = setting
            grid, blocks, shared_mem = minmax_kernel_parameters(
                nx, ny, axis=0, impl="cuda", target_block_threads=256
            )
            assert num.prod(blocks) * 8 < 48 * 1024

    def test_minmax(self, benchmark=False):
        print("testing %s " % implementations, end="", flush=True)

        def log(*msg):
            if benchmark:
                print(*msg)

        samples = []
        for sx, sy in product(*[[20, 100, 500, 1000, 5000] for _ in range(2)]):
            samples += [
                100_000 * num.random.random((sx, sy)).astype(num.double),
                num.ones((sx, sy), dtype=num.double),
                (5 * num.random.random((sx, sy)))
                .astype(num.int64)
                .astype(num.double),
                num.array(
                    [num.arange(sx).astype(num.double) for _ in range(sy)]
                ),
            ]

        variants = [
            ("argmax", argmax_2d, num.argmax),
            ("argmin", argmin_2d, num.argmin),
            ("max", max_2d, num.amax),
            ("min", min_2d, num.amin),
        ]
        nparallel = multiprocessing.cpu_count()
        for name, variant, reference_impl in variants:
            for sample, axis in itertools.product(samples, [0, 1]):
                log("=====", name, sample.shape, axis)
                results = []

                reference, dur = measure(reference_impl, 2, sample, axis=axis)
                log("reference: %.5f" % dur)

                for impl in implementations:
                    kwargs = dict(
                        axis=axis,
                        nparallel=nparallel,
                        impl=impl,
                        target_block_threads=256,
                    )
                    measure(variant, 2, sample, **kwargs)  # warmup
                    result, dur = measure(variant, 2, sample, **kwargs)
                    log("%s: %.5f" % (impl, dur))
                    results.append(result)

                for result in results:
                    assert result.shape == reference.shape
                    num.testing.assert_almost_equal(
                        result, reference, decimal=9
                    )


if __name__ == "__main__":
    util.setup_logging("test_minmax", "debug")
    unittest.main()
