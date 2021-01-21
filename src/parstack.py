# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import
import numpy as num

from . import parstack_ext
from . import cuda

try:
    range = xrange
except NameError:
    pass

CUDA_COMPILED = parstack_ext.CUDA_COMPILED

parstack_kernel_parameters = cuda.resolve_implementation_flag(
        parstack_ext.parstack_kernel_parameters)

check_parstack_implementation_compatibility = cuda.resolve_implementation_flag(
        parstack_ext.check_parstack_implementation_compatibility)


@cuda.resolve_implementation_flag
def parstack(arrays, offsets, shifts, weights,
             method=0,
             lengthout=-1,
             offsetout=0,
             result=None,
             impl='openmp',
             nparallel=None,
             target_block_threads=256):

    if nparallel is None:
        import multiprocessing
        nparallel = multiprocessing.cpu_count()

    narrays = offsets.size
    assert(len(arrays) == narrays)
    nshifts = shifts.size // narrays
    assert shifts.shape == (nshifts, narrays)
    shifts = num.reshape(shifts, (nshifts*narrays))
    assert weights.shape == (nshifts, narrays)
    weights = num.reshape(weights, (nshifts*narrays))

    if (offsets.dtype != num.int32):
        raise ValueError('offsets must be int32, got %s. ' % offsets.dtype)
    if (shifts.dtype != num.int32):
        raise ValueError('shifts must be int32, got %s. ' % shifts.dtype)

    dtype_mismatch = [
            array.dtype for array in arrays if array.dtype != weights.dtype]
    if len(dtype_mismatch) > 0:
        raise ValueError('arrays and weights must have the same data type. '
                         'Got %s and %s' % (dtype_mismatch[0], weights.dtype))

    if (result is not None and result.dtype != weights.dtype):
        raise ValueError('result and arrays must have the same data type. '
                         'Got %s and %s' % (result.dtype, weigths.dtype))

    parstack_impl = parstack_ext.parstack
    if impl == cuda.IMPL_NP:
        parstack_impl = parstack_numpy

    result, offset = parstack_impl(
        arrays, offsets, shifts, weights,
        method=method,
        lengthout=lengthout,
        offsetout=offsetout,
        result=result,
        impl=impl,
        nparallel=nparallel,
        target_block_threads=target_block_threads)

    if method == 0:
        nsamps = result.size // nshifts
        result = result.reshape((nshifts, nsamps))

    return result, offset


def get_offset_and_length(arrays, lengths, offsets, shifts):
    narrays = offsets.size
    nshifts = shifts.size // narrays
    if shifts.ndim == 2:
        shifts = num.reshape(shifts, (nshifts*narrays))

    imin = offsets[0] + shifts[0]
    imax = imin + lengths[0]
    for iarray in range(len(arrays)):
        istarts = offsets[iarray] + shifts[iarray::narrays]
        iends = istarts + lengths[iarray]
        imin = min(imin, num.amin(istarts))
        imax = max(imax, num.amax(iends))

    return imin, imax - imin


def parstack_numpy(
        arrays,
        offsets,
        shifts,
        weights,
        method,
        lengthout,
        offsetout,
        result,
        impl,
        nparallel,
        target_block_threads):

    # impl and nparallel are ignored here

    narrays = offsets.size

    lengths = num.array([a.size for a in arrays], dtype=num.int)
    if lengthout < 0:
        imin, nsamp = get_offset_and_length(arrays, lengths, offsets, shifts)
    else:
        nsamp = lengthout
        imin = offsetout

    nshifts = shifts.size // narrays
    if result is None:
        result = num.zeros(nsamp*nshifts, dtype=weights.dtype)
    elif method == 0:
        result = result.flatten()

    for ishift in range(nshifts):
        for iarray in range(narrays):
            istart = offsets[iarray] + shifts[ishift*narrays + iarray]
            weight = weights[ishift*narrays + iarray]
            istart_r = ishift*nsamp + istart - imin
            jstart = max(0, imin - istart)
            jstop = max(jstart, min(nsamp - istart + imin, lengths[iarray]))
            result[istart_r+jstart:istart_r+jstop] += \
                arrays[iarray][jstart:jstop] * weight

    if method == 0:
        return result, imin
    elif method == 1:
        return num.amax(result.reshape((nshifts, nsamp)), axis=1), imin
