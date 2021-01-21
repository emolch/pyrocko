# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import
from . import minmax_ext
from . import cuda

CUDA_COMPILED = minmax_ext.CUDA_COMPILED


def _select_minmax(typ):
    @cuda.resolve_implementation_flag
    def _minmax(*args, **kwargs):
        kwargs['typ'] = typ
        return minmax_ext.minmax(*args, **kwargs)
    return _minmax


argmax_2d = _select_minmax(minmax_ext.ARGMAX)
max_2d = _select_minmax(minmax_ext.MAX)
argmin_2d = _select_minmax(minmax_ext.ARGMIN)
min_2d = _select_minmax(minmax_ext.MIN)

minmax_kernel_parameters = cuda.resolve_implementation_flag(
    minmax_ext.minmax_kernel_parameters
)
