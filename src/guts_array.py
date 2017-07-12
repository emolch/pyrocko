from pyrocko import guts
from pyrocko.guts import TBase, Object, ValidationError
import numpy as num
from cStringIO import StringIO
from base64 import b64decode


class literal(str):
    pass


def literal_presenter(dumper, data):
    return dumper.represent_scalar(
        'tag:yaml.org,2002:str', str(data), style='|')


guts.SafeDumper.add_representer(literal, literal_presenter)


restricted_dtype_map = {
    num.dtype('float64'): '<f8',
    num.dtype('float32'): '<f4',
    num.dtype('int64'): '<i8',
    num.dtype('int32'): '<i4',
    num.dtype('int16'): '<i2',
    num.dtype('int8'): '<i1'}

restricted_dtype_map_rev = dict(
    (v, k) for (k, v) in restricted_dtype_map.iteritems())


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
            assert serialize_as in ('table', 'base64', 'list', 'npy',
                                    'base64+meta')
            self.serialize_as = serialize_as
            self.serialize_dtype = serialize_dtype

        def regularize_extra(self, val):
            if isinstance(val, basestring):
                ndim = None
                if self.shape:
                    ndim = len(self.shape)

                if self.serialize_as == 'table':
                    val = num.loadtxt(
                        StringIO(str(val)), dtype=self.dtype, ndmin=ndim)

                elif self.serialize_as == 'base64':
                    data = b64decode(val)
                    val = num.fromstring(
                        data, dtype=self.serialize_dtype).astype(self.dtype)

                elif self.serialize_as == 'npy':
                    data = b64decode(val)
                    try:
                        val = num.load(StringIO(str(data)), allow_pickle=False)
                    except TypeError:
                        # allow_pickle only available in newer NumPy
                        val = num.load(StringIO(str(data)))

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
                    if not isinstance(data, basestring):
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
                out = StringIO()
                num.savetxt(out, val, fmt='%12.7g')
                return literal(out.getvalue())
            elif self.serialize_as == 'base64':
                data = val.astype(self.serialize_dtype).tostring()
                return literal(data.encode('base64'))
            elif self.serialize_as == 'list':
                if self.dtype == num.complex:
                    return [repr(x) for x in val]
                else:
                    return val.tolist()
            elif self.serialize_as == 'npy':
                out = StringIO()
                try:
                    num.save(out, val, allow_pickle=False)
                except TypeError:
                    # allow_pickle only available in newer NumPy
                    num.save(out, val)

                return literal(out.getvalue().encode('base64'))

            elif self.serialize_as == 'base64+meta':
                serialize_dtype = self.serialize_dtype or \
                    restricted_dtype_map[val.dtype]

                data = val.astype(serialize_dtype).tostring()

                return dict(
                    dtype=serialize_dtype,
                    shape=val.shape,
                    data=literal(data.encode('base64')))


__all__ = ['Array']
