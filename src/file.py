# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
IO library for simple binary files.
'''

# The container format:
# * A file consists of records.
# * A record consists of a record header a record payload, and possibly
#   padding.
# * A record header consists of a label, a version, the record size, the
#   payload size, a hash, and a record type.
# * A record payload consists of a sequence of record entries.
# * A record entry consists of a key, a type, and a value.

from struct import unpack, pack
from io import BytesIO
import numpy as num
try:
    from hashlib import sha1
except ImportError:
    from sha import new as sha1

try:
    from os import SEEK_CUR
except ImportError:
    SEEK_CUR = 1

from . import util

try:
    range = xrange
except NameError:
    pass


size_record_header = 64
no_hash = '\0' * 20

numtypes = {
    '@i2': (num.int16, '>i2'),
    '@i4': (num.int32, '>i4'),
    '@i8': (num.int64, '>i8'),
    '@u2': (num.uint16, '>u2'),
    '@u4': (num.uint32, '>u4'),
    '@u8': (num.uint64, '>u8'),
    '@f4': (num.float32, '>f4'),
    '@f8': (num.float64, '>f8'),
}

numtype2type = dict([(v[0], k) for (k, v) in numtypes.items()])


def packer(fmt):
    return ((lambda x: pack('>'+fmt, x)), (lambda x: unpack('>'+fmt, x)[0]))


def unpack_array(fmt, data):
    return num.frombuffer(
        data, dtype=numtypes[fmt][1]).astype(numtypes[fmt][0])


def pack_array(fmt, data):
    return data.astype(numtypes[fmt][1]).tobytes()


def array_packer(fmt):
    return ((lambda x: pack_array(fmt, x)), (lambda x: unpack_array(fmt, x)))


def encoding_packer(enc):
    return ((lambda x: x.encode(enc)), (lambda x: str(x.decode(enc))))


def noop(x):
    return x


def time_to_str_ns(x):
    return util.time_to_str(x, format=9).encode('utf-8')


def str_to_time(x):
    return util.str_to_time(str(x.decode('utf8')))


castings = {
    'i2': packer('h'),
    'i4': packer('i'),
    'i8': packer('q'),
    'u2': packer('H'),
    'u4': packer('I'),
    'u8': packer('Q'),
    'f4': packer('f'),
    'f8': packer('d'),
    'string': encoding_packer('utf-8'),
    'time_string': (time_to_str_ns, str_to_time),
    '@i2': array_packer('@i2'),
    '@i4': array_packer('@i4'),
    '@i8': array_packer('@i8'),
    '@u2': array_packer('@u2'),
    '@u4': array_packer('@u4'),
    '@u8': array_packer('@u8'),
    '@f4': array_packer('@f4'),
    '@f8': array_packer('@f8'),
}


def pack_value(type, value):
    try:
        return castings[type][0](value)
    except Exception as e:
        raise FileError(
            'Packing value failed (type=%s, value=%s, error=%s).' %
            (type, str(value)[:500], e))


def unpack_value(type, value):
    try:
        return castings[type][1](value)
    except Exception as e:
        raise FileError(
            'Unpacking value failed (type=%s, error=%s).' % (type, e))


class FileError(Exception):
    pass


class NoDataAvailable(Exception):
    pass


class WrongRecordType(Exception):
    pass


class MissingRecordValue(Exception):
    pass


class Record(object):
    def __init__(
            self, parent, mode, size_record, size_payload, hash, type, format,
            do_hash):

        self.mode = mode
        self.size_record = size_record
        self.size_payload = size_payload
        self.hash = hash
        self.type = type
        if mode == 'w':
            self.size_payload = 0
            self.hash = None
            self._out = BytesIO()
        else:
            self.size_remaining = self.size_record - size_record_header
            self.size_padding = self.size_record - size_record_header - \
                self.size_payload

        self._f = parent._f
        self._parent = parent
        self._hasher = None
        self.format = format
        if do_hash and (self.mode == 'w' or self.hash):
            self._hasher = sha1()
        self._closed = False

    def read(self, n=None):

        assert not self._closed
        assert self.mode == 'r'

        if n is None:
            n = self.size_payload

        n = min(n, self.size_remaining - self.size_padding)
        data = self._f.read(n)
        self.size_remaining -= len(data)

        if len(data) != n:
            raise FileError('Read returned less data than expected.')

        if self._hasher:
            self._hasher.update(data)

        return data

    def write(self, data):
        assert not self._closed
        assert self.mode == 'w'
        self._out.write(data)
        if self._hasher:
            self._hasher.update(data)

        self.size_payload += len(data)

    def seek(self, n, whence):
        assert not self._closed
        assert self.mode == 'r'
        assert whence == SEEK_CUR
        assert n >= 0

        n = min(n, self.size_remaining - self.size_padding)
        self._f.seek(n, whence)
        self._hasher = None
        self.size_remaining -= n

    def skip(self, n):
        self.seek(n, SEEK_CUR)

    def close(self):
        if self._closed:
            return

        if self.mode == 'r':
            if self._hasher and self._hasher.digest() != self.hash:
                self.read(self.size_remaining)
                raise FileError(
                    'Hash computed from record data does not match value '
                    'given in header.')
            else:
                self.seek(self.size_remaining, SEEK_CUR)

            if self.size_padding:
                self._f.seek(self.size_padding, SEEK_CUR)
        else:
            if self.size_record is not None and \
                    self.size_payload > self.size_record - size_record_header:

                raise FileError(
                    'Too much data to fit into size-limited record.')

            if self.size_record is None:
                self.size_record = self.size_payload + size_record_header

            self.size_padding = self.size_record - self.size_payload - \
                size_record_header

            if self._hasher is not None:
                self.hash = self._hasher.digest()

            self._parent.write_record_header(
                self.size_record, self.size_payload, self.hash, self.type)

            self._f.write(self._out.getvalue())
            self._out.close()
            self._f.write(b'\0' * self.size_padding)

        self._closed = True
        self._parent = None
        self._f = None

    def entries(self):

        sizes = []
        sum = 0
        while sum < self.size_payload:
            size = unpack('>Q', self.read(8))[0]
            sum += size + 8
            sizes.append(size)

        n = len(sizes) // 3
        keys = []
        keys = [str(self.read(sizes[j]).decode('ascii'))
                for j in range(n)]
        types = [str(self.read(sizes[j]).decode('ascii'))
                 for j in range(n, 2*n)]
        for key, type, j in zip(keys, types, range(2*n, 3*n)):
            yield key, type, sizes[j]

    def unpack(self, exclude=None):

        d = {}
        for key, type, size in self.entries():
            if self.format[key] != type:
                FileError('Record value in unexpected format.')

            if not exclude or key not in exclude:
                d[key] = unpack_value(type, self.read(size))
            else:
                self.skip(size)
                d[key] = None

        for key in self.format:
            if key not in d:
                raise FileError('Missing record entry: %s.' % key)

        return d

    def pack(self, d):
        for key in self.format:
            if key not in d:
                raise MissingRecordValue()

        keys = []
        types = []
        values = []
        for key in d.keys():
            if key in self.format:
                type = self.format[key]
                if isinstance(type, tuple):
                    type = self._parent.get_type(key, d[key])

                keys.append(key.encode('ascii'))
                types.append(type.encode('ascii'))
                values.append(pack_value(type, d[key]))

        sizes = [len(x) for x in keys+types+values]

        self.write(pack('>%iQ' % len(sizes), *sizes))
        for x in keys+types+values:
            self.write(x)


class File(object):

    def __init__(
            self, f,
            type_label='TEST',
            version='0000',
            record_formats={}):

        assert len(type_label) == 4
        assert len(version) == 4

        self._file_type_label = type_label
        self._file_version = version
        self._record_formats = record_formats
        self._current_record = None
        self._f = f

    def read_record_header(self):
        data = self._f.read(size_record_header)

        if len(data) == 0:
            raise NoDataAvailable()

        if len(data) != size_record_header:
            raise FileError('Read returned less data than expected.')

        label, version, size_record, size_payload, hash, type = unpack(
            '>4s4sQQ20s20s', data)

        label = str(label.decode('ascii'))
        version = str(version.decode('ascii'))
        type = str(type.rstrip().decode('ascii'))

        if label != self._file_type_label:
            raise FileError('record file type label missing.')

        if version != self._file_version:
            raise FileError('file version %s not supported.' % version)

        type = type.rstrip()

        if hash == no_hash:
            hash = None

        return size_record, size_payload, hash, type

    def write_record_header(self, size_record, size_payload, hash, type):
        if hash is None:
            hash = no_hash
        data = pack(
            '>4s4sQQ20s20s',
            self._file_type_label.encode('ascii'),
            self._file_version.encode('ascii'),
            size_record,
            size_payload,
            hash,
            type.encode('ascii').ljust(20)[:20])

        self._f.write(data)

    def next_record(self, check_hash=False):
        if self._current_record:
            self._current_record.close()

        size_record, size_payload, hash, type = self.read_record_header()
        format = self._record_formats[type]
        self._current_record = Record(
            self, 'r', size_record, size_payload, hash, type, format,
            check_hash)

        return self._current_record

    def add_record(self, type, size_record=None, make_hash=False):
        if self._current_record:
            self._current_record.close()

        format = self._record_formats[type]
        self._current_record = Record(
            self, 'w', size_record, 0, None, type, format, make_hash)
        return self._current_record

    def close(self):
        if self._current_record:
            self._current_record.close()
