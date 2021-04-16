# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import

import numpy as num
from io import BytesIO
from base64 import b64decode, b64encode
import binascii

from .guts import TBase, Object, ValidationError, literal, newstr


try:
    unicode
except NameError:
    unicode = str


restricted_dtype_map = {
    num.dtype('float64'): '<f8',
    num.dtype('float32'): '<f4',
    num.dtype('int64'): '<i8',
    num.dtype('int32'): '<i4',
    num.dtype('int16'): '<i2',
    num.dtype('int8'): '<i1'}

restricted_dtype_map_rev = dict(
    (v, k) for (k, v) in restricted_dtype_map.items())


def array_equal(a, b):
    return a.dtype == b.dtype \
        and a.shape == b.shape \
        and num.all(a == b)


class Array(Object):

    dummy_for = num.ndarray

    class __T(TBase):
        def __init__(
                self,
                shape=None,
                dtype=None,
                serialize_as='table',
                serialize_dtype=None,
                *args, **kwargs):

            TBase.__init__(self, *args, **kwargs)
            self.shape = shape
            self.dtype = dtype
            assert serialize_as in (
                'table', 'base64', 'list', 'npy',
                'base64+meta', 'base64-compat')
            self.serialize_as = serialize_as
            self.serialize_dtype = serialize_dtype

        def is_default(self, val):
            if self._default is None:
                return val is None
            elif val is None:
                return False
            else:
                return array_equal(self._default, val)

        def regularize_extra(self, val):
            if isinstance(val, (str, newstr)):
                ndim = None
                if self.shape:
                    ndim = len(self.shape)

                if self.serialize_as == 'table':
                    val = num.loadtxt(
                        BytesIO(val.encode('utf-8')),
                        dtype=self.dtype, ndmin=ndim)

                elif self.serialize_as == 'base64':
                    data = b64decode(val)
                    val = num.fromstring(
                        data, dtype=self.serialize_dtype).astype(self.dtype)

                elif self.serialize_as == 'base64-compat':
                    try:
                        data = b64decode(val)
                        val = num.fromstring(
                            data,
                            dtype=self.serialize_dtype).astype(self.dtype)
                    except binascii.Error:
                        val = num.loadtxt(
                            BytesIO(val.encode('utf-8')),
                            dtype=self.dtype, ndmin=ndim)

                elif self.serialize_as == 'npy':
                    data = b64decode(val)
                    try:
                        val = num.load(BytesIO(data), allow_pickle=False)
                    except TypeError:
                        # allow_pickle only available in newer NumPy
                        val = num.load(BytesIO(data))

            elif isinstance(val, dict):
                if self.serialize_as == 'base64+meta':
                    if not sorted(val.keys()) == ['data', 'dtype', 'shape']:
                        raise ValidationError(
                            'array in format "base64+meta" must have keys '
                            '"data", "dtype", and "shape"')

                    shape = val['shape']
                    if not isinstance(shape, list):
                        raise ValidationError('invalid shape definition')

                    for n in shape:
                        if not isinstance(n, int):
                            raise ValidationError('invalid shape definition')

                    serialize_dtype = val['dtype']
                    allowed = list(restricted_dtype_map_rev.keys())
                    if self.serialize_dtype is not None:
                        allowed.append(self.serialize_dtype)

                    if serialize_dtype not in allowed:
                        raise ValidationError(
                            'only the following dtypes are allowed: %s'
                            % ', '.join(sorted(allowed)))

                    data = val['data']
                    if not isinstance(data, (str, newstr)):
                        raise ValidationError(
                            'data must be given as a base64 encoded string')

                    data = b64decode(data)

                    dtype = self.dtype or \
                        restricted_dtype_map_rev[serialize_dtype]

                    val = num.fromstring(
                        data, dtype=serialize_dtype).astype(dtype)

                    if val.size != num.product(shape):
                        raise ValidationError('size/shape mismatch')

                    val = val.reshape(shape)

            else:
                val = num.asarray(val, dtype=self.dtype)

            return val

        def validate_extra(self, val):
            if not isinstance(val, num.ndarray):
                raise ValidationError(
                    'object is not of type numpy.ndarray: %s' % type(val))
            if self.dtype is not None and self.dtype != val.dtype:
                raise ValidationError(
                    'array not of required type: need %s, got %s' % (
                        self.dtype, val.dtype))

            if self.shape is not None:
                la, lb = len(self.shape), len(val.shape)
                if la != lb:
                    raise ValidationError(
                        'array dimension mismatch: need %i, got %i' % (
                            la, lb))

                for a, b in zip(self.shape, val.shape):
                    if a is not None:
                        if a != b:
                            raise ValidationError(
                                'array shape mismatch: need %s, got: %s' % (
                                    self.shape, val.shape))

        def to_save(self, val):
            if self.serialize_as == 'table':
                out = BytesIO()
                num.savetxt(out, val, fmt='%12.7g')
                return literal(out.getvalue().decode('utf-8'))
            elif self.serialize_as == 'base64' \
                    or self.serialize_as == 'base64-compat':
                data = val.astype(self.serialize_dtype).tostring()
                return literal(b64encode(data).decode('utf-8'))
            elif self.serialize_as == 'list':
                if self.dtype == num.complex:
                    return [repr(x) for x in val]
                else:
                    return val.tolist()
            elif self.serialize_as == 'npy':
                out = BytesIO()
                try:
                    num.save(out, val, allow_pickle=False)
                except TypeError:
                    # allow_pickle only available in newer NumPy
                    num.save(out, val)

                return literal(b64encode(out.getvalue()).decode('utf-8'))

            elif self.serialize_as == 'base64+meta':
                serialize_dtype = self.serialize_dtype or \
                    restricted_dtype_map[val.dtype]

                data = val.astype(serialize_dtype).tostring()

                return dict(
                    dtype=serialize_dtype,
                    shape=val.shape,
                    data=literal(b64encode(data).decode('utf-8')))


__all__ = ['Array']
