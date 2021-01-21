# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import
from . import cuda_ext

CUDA_COMPILED = cuda_ext.CUDA_COMPILED
CUDA_DEBUG = cuda_ext.CUDA_DEBUG

IMPL_NP = cuda_ext.IMPL_NP
IMPL_OMP = cuda_ext.IMPL_OMP
IMPL_CUDA = cuda_ext.IMPL_CUDA
IMPL_CUDA_THRUST = cuda_ext.IMPL_CUDA_THRUST
IMPL_CUDA_ATOMIC = cuda_ext.IMPL_CUDA_ATOMIC

_implementation_aliases = dict(
    omp=IMPL_OMP,
    openmp=IMPL_OMP,
    np=IMPL_NP,
    numpy=IMPL_NP,
    cuda=IMPL_CUDA,
    cuda_thrust=IMPL_CUDA_THRUST,
    thrust=IMPL_CUDA_THRUST,
    cuda_atomic=IMPL_CUDA_ATOMIC,
    atomic=IMPL_CUDA_ATOMIC,
)


def resolve_implementation_flag(func):
    def wrapper(*args, **kwargs):
        if 'impl' in kwargs:
            impl = kwargs['impl']
            if isinstance(impl, str):
                impl_flag = _implementation_aliases.get(impl.lower(), None)
                if impl_flag is None:
                    raise ValueError('Unknown implementation: %s.' % impl)
                kwargs['impl'] = impl_flag
        return func(*args, **kwargs)

    return wrapper
