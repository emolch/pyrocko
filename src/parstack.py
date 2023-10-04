# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Fast weight-delay-and-sum implementation for seismic array processing and
migration.
'''

import numpy as num

from . import parstack_ext

try:
    range = xrange
except NameError:
    pass


def parstack(arrays, offsets, shifts, weights, method,
             lengthout=-1,
             offsetout=0,
             result=None,
             nparallel=None,
             dtype=num.float64,
             impl='openmp'):

    if nparallel is None:
        import multiprocessing
        nparallel = multiprocessing.cpu_count()

    narrays = offsets.size
    assert len(arrays) == narrays
    nshifts = shifts.size // narrays
    assert shifts.shape == (nshifts, narrays)
    shifts = num.reshape(shifts, (nshifts*narrays))
    assert weights.shape == (nshifts, narrays)
    weights = num.reshape(weights, (nshifts*narrays))

    weights = weights.astype(dtype, copy=False)
    arrays = [arr.astype(dtype, copy=False) for arr in arrays]

    if impl == 'openmp':
        parstack_impl = parstack_ext.parstack
    elif impl == 'numpy':
        parstack_impl = parstack_numpy

    result, offset = parstack_impl(
        arrays, offsets, shifts, weights, method,
        lengthout, offsetout, result, nparallel)

    if method == 0:
        nsamps = result.size // nshifts
        result = result.reshape((nshifts, nsamps))

    return result, offset


def get_offset_and_length(arrays, offsets, shifts):
    narrays = offsets.size
    nshifts = shifts.size // narrays
    if shifts.ndim == 2:
        shifts = num.reshape(shifts, (nshifts*narrays))

    lengths = num.array([a.size for a in arrays], dtype=int)
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
        nparallel):

    # nparallel is ignored here

    narrays = offsets.size

    lengths = num.array([a.size for a in arrays], dtype=int)
    if lengthout < 0:
        imin, nsamp = get_offset_and_length(arrays, offsets, shifts)
    else:
        nsamp = lengthout
        imin = offsetout

    nshifts = shifts.size // narrays
    result = num.zeros(nsamp*nshifts, dtype=float)

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


def argmax(a, nparallel=1):
    '''
    Same as numpys' argmax for 2 dimensional arrays along axis 0
    but more memory efficient and twice as fast.
    '''

    return parstack_ext.argmax(a, nparallel)
