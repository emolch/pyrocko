# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Read and write GSE2.0, GSE2.1, and IMS1.0 files.
'''

import sys
import re
import logging

from . import util
from .io_common import FileLoadError, FileSaveError
from pyrocko.guts import (
    Object, String, StringChoice, Timestamp, Int, Float, List, Bool, Complex,
    ValidationError)

try:
    range = xrange
except NameError:
    pass

logger = logging.getLogger('pyrocko.io.ims')

km = 1000.
nm_per_s = 1.0e-9

g_versions = ('GSE2.0', 'GSE2.1', 'IMS1.0')
g_dialects = ('NOR_NDC', 'USA_DMC')


class SerializeError(Exception):
    '''
    Raised when serialization of an IMS/GSE2 object fails.
    '''
    pass


class DeserializeError(Exception):
    '''
    Raised when deserialization of an IMS/GSE2 object fails.
    '''

    def __init__(self, *args, **kwargs):
        Exception.__init__(self, *args)
        self._line_number = None
        self._line = None
        self._position = kwargs.get('position', None)
        self._format = kwargs.get('format', None)
        self._version_dialect = None

    def set_context(self, line_number, line, version_dialect):
        self._line_number = line_number
        self._line = line
        self._version_dialect = version_dialect

    def __str__(self):
        lst = [Exception.__str__(self)]
        if self._version_dialect is not None:
            lst.append('format version: %s' % self._version_dialect[0])
            lst.append('dialect: %s' % self._version_dialect[1])
        if self._line_number is not None:
            lst.append('line number: %i' % self._line_number)
        if self._line is not None:
            lst.append('line content:\n%s' % (self._line.decode('ascii') or
                                              '*** line is empty ***'))

        if self._position is not None:
            if self._position[1] is None:
                length = max(1, len(self._line or '') - self._position[0])
            else:
                length = self._position[1]

            lst.append(' ' * self._position[0] + '^' * length)

        if self._format is not None:
            i = 0
            f = []
            j = 1
            for element in self._format:
                if element.length != 0:
                    f.append(' ' * (element.position - i))
                    if element.length is not None:
                        f.append(str(j % 10) * element.length)
                        i = element.position + element.length
                    else:
                        f.append(str(j % 10) + '...')
                        i = element.position + 4

                    j += 1

            lst.append(''.join(f))

        return '\n'.join(lst)


def float_or_none(x):
    if x.strip():
        return float(x)
    else:
        return None


def int_or_none(x):
    if x.strip():
        return int(x)
    else:
        return None


def float_to_string(fmt):
    ef = fmt[0]
    assert ef in 'ef'
    ln, d = map(int, fmt[1:].split('.'))
    pfmts = ['%%%i.%i%s' % (ln, dsub, ef) for dsub in range(d, -1, -1)]
    blank = b' ' * ln

    def func(v):
        if v is None:
            return blank

        for pfmt in pfmts:
            s = pfmt % v
            if len(s) == ln:
                return s.encode('ascii')

        raise SerializeError('format="%s", value=%s' % (pfmt, repr(v)))

    return func


def int_to_string(fmt):
    assert fmt[0] == 'i'
    pfmt = '%'+fmt[1:]+'i'
    ln = int(fmt[1:])
    blank = b' ' * ln

    def func(v):
        if v is None:
            return blank

        s = pfmt % v
        if len(s) == ln:
            return s.encode('ascii')
        else:
            raise SerializeError('format="%s", value=%s' % (pfmt, repr(v)))

    return func


def deserialize_string(fmt):
    if fmt.endswith('?'):
        def func(s):
            if s.strip():
                return str(s.rstrip().decode('ascii'))
            else:
                return None
    else:
        def func(s):
            return str(s.rstrip().decode('ascii'))

    return func


def serialize_string(fmt):
    if fmt.endswith('+'):
        more_ok = True
    else:
        more_ok = False

    fmt = fmt.rstrip('?+')

    assert fmt[0] == 'a'
    ln = int(fmt[1:])

    def func(v):
        if v is None:
            v = b''
        else:
            v = v.encode('ascii')

        s = v.ljust(ln)
        if more_ok or len(s) == ln:
            return s
        else:
            raise SerializeError('max string length: %i, value="%s"' % ln, v)

    return func


def rstrip_string(v):
    return v.rstrip()


def x_fixed(expect):
    def func():
        def parse(s):
            if s != expect:
                raise DeserializeError(
                    'expected="%s", value="%s"' % (expect, s))
            return s

        def string(s):
            return expect

        return parse, string

    func.width = len(expect)
    func.help_type = 'Keyword: %s' % expect
    return func


def x_scaled(fmt, factor):
    def func():
        to_string = float_to_string(fmt)

        def parse(s):
            x = float_or_none(s)
            if x is None:
                return None
            else:
                return x * factor

        def string(v):
            if v is None:
                return to_string(None)
            else:
                return to_string(v/factor)

        return parse, string

    func.width = int(fmt[1:].split('.')[0])
    func.help_type = 'float'
    return func


def x_int_angle():
    def string(v):
        if v is None:
            return b'   '
        else:
            return ('%3i' % (int(round(v)) % 360)).encode('ascii')

    return float_or_none, string


x_int_angle.width = 3
x_int_angle.help_type = 'int [0, 360]'


def x_substitute(value):
    def func():
        def parse(s):
            assert s == b''
            return value

        def string(s):
            return b''

        return parse, string

    func.width = 0
    func.help_type = 'Not present in this file version.'
    return func


def fillup_zeros(s, fmt):
    s = s.rstrip()
    if not s:
        return s

    if fmt == '%Y/%m/%d %H:%M:%S.3FRAC':
        return s + '0000/01/01 00:00:00.000'[len(s):]
    elif fmt == '%Y/%m/%d %H:%M:%S.2FRAC':
        return s + '0000/01/01 00:00:00.00'[len(s):]

    return s


def x_date_time(fmt='%Y/%m/%d %H:%M:%S.3FRAC'):
    def parse(s):
        s = str(s.decode('ascii'))
        try:
            s = fillup_zeros(s, fmt)
            return util.str_to_time(s, format=fmt)

        except Exception:
            # iris sets this dummy end dates and they don't fit into 32bit
            # time stamps
            if fmt[:2] == '%Y' and s[:4] in ('2599', '2045'):
                return None

            elif fmt[6:8] == '%Y' and s[6:10] in ('2599', '2045'):
                return None

            raise DeserializeError('expected date, value="%s"' % s)

    def string(s):
        return util.time_to_str(s, format=fmt).encode('ascii')

    return parse, string


x_date_time.width = 23
x_date_time.help_type = 'YYYY/MM/DD HH:MM:SS.FFF'


def x_date():
    return x_date_time(fmt='%Y/%m/%d')


x_date.width = 10
x_date.help_type = 'YYYY/MM/DD'


def x_date_iris():
    return x_date_time(fmt='%m/%d/%Y')


x_date_iris.width = 10
x_date_iris.help_type = 'MM/DD/YYYY'


def x_date_time_no_seconds():
    return x_date_time(fmt='%Y/%m/%d %H:%M')


x_date_time_no_seconds.width = 16
x_date_time_no_seconds.help_type = 'YYYY/MM/DD HH:MM'


def x_date_time_2frac():
    return x_date_time(fmt='%Y/%m/%d %H:%M:%S.2FRAC')


x_date_time_2frac.width = 22
x_date_time_2frac.help_type = 'YYYY/MM/DD HH:MM:SS.FF'


def x_yesno():
    def parse(s):
        if s == b'y':
            return True
        elif s == b'n':
            return False
        else:
            raise DeserializeError('"y" on "n" expected')

    def string(b):
        return [b'n', b'y'][int(b)]

    return parse, string


x_yesno.width = 1
x_yesno.help_type = 'yes/no'


def optional(x_func):

    def func():
        parse, string = x_func()

        def parse_optional(s):
            if s.strip():
                return parse(s)
            else:
                return None

        def string_optional(s):
            if s is None:
                return b' ' * x_func.width
            else:
                return string(s)

        return parse_optional, string_optional

    func.width = x_func.width
    func.help_type = 'optional %s' % x_func.help_type

    return func


class E(object):
    def __init__(self, begin, end, fmt, dummy=False):
        self.advance = 1
        if dummy:
            self.advance = 0

        self.position = begin - 1
        if end is not None:
            self.length = end - begin + 1
        else:
            self.length = None

        self.end = end

        if isinstance(fmt, str):
            t = fmt[0]
            if t in 'ef':
                self.parse = float_or_none
                self.string = float_to_string(fmt)
                ln = int(fmt[1:].split('.')[0])
                self.help_type = 'float'
            elif t == 'a':
                self.parse = deserialize_string(fmt)
                self.string = serialize_string(fmt)
                ln = int(fmt[1:].rstrip('+?'))
                self.help_type = 'string'
            elif t == 'i':
                self.parse = int_or_none
                self.string = int_to_string(fmt)
                ln = int(fmt[1:])
                self.help_type = 'integer'
            else:
                assert False, 'invalid format: %s' % t

            assert self.length is None or ln == self.length, \
                'inconsistent length for pos=%i, fmt=%s' \
                % (self.position, fmt)

        else:
            self.parse, self.string = fmt()
            self.help_type = fmt.help_type


def end_section(line, extra=None):
    if line is None:
        return True

    ul = line.upper()
    return ul.startswith(b'DATA_TYPE') or ul.startswith(b'STOP') or \
        (extra is not None and ul.startswith(extra))


class Section(Object):
    '''
    Base class for top level sections in IMS/GSE2 files.

    Sections as understood by this implementation typically correspond to a
    DATA_TYPE section in IMS/GSE2 but for some types a finer granularity has
    been chosen.
    '''

    handlers = {}  # filled after section have been defined below

    @classmethod
    def read(cls, reader):
        datatype = DataType.read(reader)
        reader.pushback()
        return Section.handlers[
            datatype.type.upper().encode('ascii')].read(reader)

    def write_datatype(self, writer):
        datatype = DataType(
            type=self.keyword.decode('ascii'),
            format=writer.version_dialect[0])
        datatype.write(writer)

    @classmethod
    def read_table(cls, reader, expected_header, block_cls, end=end_section):

        header = reader.readline()
        if not header.upper().startswith(expected_header.upper()):
            raise DeserializeError(
                'invalid table header line, expected:\n'
                '%s\nfound: %s ' % (expected_header, header))

        while True:
            line = reader.readline()
            reader.pushback()
            if end(line):
                break

            yield block_cls.read(reader)

    def write_table(self, writer, header, blocks):
        writer.writeline(header)
        for block in blocks:
            block.write(writer)


def get_versioned(x, version_dialect):
    if isinstance(x, dict):
        for v in (tuple(version_dialect), version_dialect[0], None):
            if v in x:
                return x[v]
    else:
        return x


class Block(Object):
    '''
    Base class for IMS/GSE2 data blocks / lines.

    Blocks as understood by this implementation usually correspond to
    individual logical lines in the IMS/GSE2 file.
    '''

    def values(self):
        return list(self.T.ivals(self))

    @classmethod
    def format(cls, version_dialect):
        return get_versioned(cls._format, version_dialect)

    def serialize(self, version_dialect):
        ivalue = 0
        out = []
        values = self.values()
        for element in self.format(version_dialect):
            if element.length != 0:
                out.append((element.position, element.string(values[ivalue])))
            ivalue += element.advance

        out.sort()

        i = 0
        slist = []
        for (position, s) in out:
            slist.append(b' ' * (position - i))
            slist.append(s)
            i = position + len(s)

        return b''.join(slist)

    @classmethod
    def deserialize_values(cls, line, version_dialect):
        values = []
        for element in cls.format(version_dialect):
            try:
                val = element.parse(
                    line[element.position:element.end])

                if element.advance != 0:
                    values.append(val)
            except Exception:
                raise DeserializeError(
                    'Cannot parse %s' % (
                        element.help_type),
                    position=(element.position, element.length),
                    version=version_dialect[0],
                    dialect=version_dialect[1],
                    format=cls.format(version_dialect))

        return values

    @classmethod
    def validated(cls, *args, **kwargs):
        obj = cls(*args, **kwargs)
        try:
            obj.validate()
        except ValidationError as e:
            raise DeserializeError(str(e))

        return obj

    @classmethod
    def regularized(cls, *args, **kwargs):
        obj = cls(*args, **kwargs)
        try:
            obj.regularize()
        except ValidationError as e:
            raise DeserializeError(str(e))

        return obj

    @classmethod
    def deserialize(cls, line, version_dialect):
        values = cls.deserialize_values(line, version_dialect)
        return cls.validated(**dict(zip(cls.T.propnames, values)))

    @classmethod
    def read(cls, reader):
        line = reader.readline()
        return cls.deserialize(line, reader.version_dialect)

    def write(self, writer):
        s = self.serialize(writer.version_dialect)
        writer.writeline(s)


class FreeFormatLine(Block):
    '''
    Base class for IMS/GSE2 free format lines.
    '''

    @classmethod
    def deserialize_values(cls, line, version_dialect):
        format = cls.format(version_dialect)
        values = line.split(None, len(format)-1)

        values_weeded = []
        for x, v in zip(format, values):
            if isinstance(x, bytes):
                if v.upper() != x:
                    raise DeserializeError(
                        'expected keyword: %s, found %s' % (x, v.upper()))

            else:
                if isinstance(x, tuple):
                    x, (parse, _) = x
                    v = parse(v)

                values_weeded.append((x, v))

        values_weeded.sort()
        return [str(xv[1].decode('ascii')) for xv in values_weeded]

    @classmethod
    def deserialize(cls, line, version_dialect):
        values = cls.deserialize_values(line, version_dialect)
        propnames = cls.T.propnames
        stuff = dict(zip(propnames, values))
        return cls.regularized(**stuff)

    def serialize(self, version_dialect):
        names = self.T.propnames
        props = self.T.properties
        out = []
        for x in self.format(version_dialect):
            if isinstance(x, bytes):
                out.append(x.decode('ascii'))
            else:
                if isinstance(x, tuple):
                    x, (_, string) = x
                    v = string(getattr(self, names[x-1]))
                else:
                    v = getattr(self, names[x-1])

                if v is None:
                    break

                out.append(props[x-1].to_save(v))

        return ' '.join(out).encode('ascii')


class DataType(Block):
    '''
    Representation of a DATA_TYPE line.
    '''

    type = String.T()
    subtype = String.T(optional=True)
    format = String.T()
    subformat = String.T(optional=True)

    @classmethod
    def deserialize(cls, line, version_dialect):
        pat = br'DATA_TYPE +([^ :]+)(:([^ :]+))?( +([^ :]+)(:([^ :]+))?)?'
        m = re.match(pat, line)
        if not m:
            raise DeserializeError('invalid DATA_TYPE line')

        return cls.validated(
            type=str((m.group(1) or b'').decode('ascii')),
            subtype=str((m.group(3) or b'').decode('ascii')),
            format=str((m.group(5) or b'').decode('ascii')),
            subformat=str((m.group(7) or b'').decode('ascii')))

    def serialize(self, version_dialect):
        s = self.type
        if self.subtype:
            s += ':' + self.subtype

        f = self.format
        if self.subformat:
            f += ':' + self.subformat

        return ('DATA_TYPE %s %s' % (s, f)).encode('ascii')

    @classmethod
    def read(cls, reader):
        line = reader.readline()
        datatype = cls.deserialize(line, reader.version_dialect)
        reader.version_dialect[0] = datatype.format
        return datatype

    def write(self, writer):
        s = self.serialize(writer.version_dialect)
        writer.version_dialect[0] = self.format
        writer.writeline(s)


class FTPFile(FreeFormatLine):
    '''
    Representation of an FTP_FILE line.
    '''

    _format = [b'FTP_FILE', 1, 2, 3, 4]

    net_address = String.T()
    login_mode = StringChoice.T(choices=('USER', 'GUEST'), ignore_case=True)
    directory = String.T()
    file = String.T()


class WaveformSubformat(StringChoice):
    choices = ['INT', 'CM6', 'CM8', 'AU6', 'AU8']
    ignore_case = True


class WID2(Block):
    '''
    Representation of a WID2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'WID2'), dummy=True),
        E(6, 28, x_date_time),
        E(30, 34, 'a5'),
        E(36, 38, 'a3'),
        E(40, 43, 'a4'),
        E(45, 47, 'a3'),
        E(49, 56, 'i8'),
        E(58, 68, 'f11.6'),
        E(70, 79, x_scaled('e10.2', nm_per_s)),
        E(81, 87, 'f7.3'),
        E(89, 94, 'a6?'),
        E(96, 100, 'f5.1'),
        E(102, 105, 'f4.1')
    ]

    time = Timestamp.T()
    station = String.T(help='station code (5 characters)')
    channel = String.T(help='channel code (3 characters)')
    location = String.T(
        default='', optional=True,
        help='location code (aux_id, 4 characters)')
    sub_format = WaveformSubformat.T(default='CM6')
    nsamples = Int.T(default=0)
    sample_rate = Float.T(default=1.0)
    calibration_factor = Float.T(
        optional=True,
        help='system sensitivity (m/count) at reference period '
             '(calibration_period)')
    calibration_period = Float.T(
        optional=True,
        help='calibration reference period [s]')
    instrument_type = String.T(
        default='', optional=True, help='instrument type (6 characters)')
    horizontal_angle = Float.T(
        optional=True,
        help='horizontal orientation of sensor, clockwise from north [deg]')
    vertical_angle = Float.T(
        optional=True,
        help='vertical orientation of sensor from vertical [deg]')


class OUT2(Block):
    '''
    Representation of an OUT2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'OUT2'), dummy=True),
        E(6, 28, x_date_time),
        E(30, 34, 'a5'),
        E(36, 38, 'a3'),
        E(40, 43, 'a4'),
        E(45, 55, 'f11.3')
    ]

    time = Timestamp.T()
    station = String.T(help='station code (5 characters)')
    channel = String.T(help='channel code (3 characters)')
    location = String.T(
        default='', optional=True,
        help='location code (aux_id, 4 characters)')
    duration = Float.T()


class DLY2(Block):
    '''
    Representation of a DLY2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'DLY2'), dummy=True),
        E(6, 28, x_date_time),
        E(30, 34, 'a5'),
        E(36, 38, 'a3'),
        E(40, 43, 'a4'),
        E(45, 55, 'f11.3')
    ]

    time = Timestamp.T()
    station = String.T(help='station code (5 characters)')
    channel = String.T(help='channel code (3 characters)')
    location = String.T(
        default='', optional=True,
        help='location code (aux_id, 4 characters)')
    queue_duration = Float.T(help='duration of queue [s]')


class DAT2(Block):
    '''
    Representation of a DAT2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'DAT2'), dummy=True)
    ]

    raw_data = List.T(String.T())

    @classmethod
    def read(cls, reader):
        line = reader.readline()
        dat2 = cls.deserialize(line, reader.version_dialect)
        while True:
            line = reader.readline()
            if line.upper().startswith(b'CHK2 '):
                reader.pushback()
                break
            else:
                if reader._load_data:
                    dat2.raw_data.append(line.strip())

        return dat2

    def write(self, writer):
        Block.write(self, writer)
        for line in self.raw_data:
            writer.writeline(line)


class STA2(Block):
    '''
    Representation of a STA2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'STA2'), dummy=True),
        E(6, 14, 'a9'),
        E(16, 24, 'f9.5'),
        E(26, 35, 'f10.5'),
        E(37, 48, 'a12'),
        E(50, 54, x_scaled('f5.3', km)),
        E(56, 60, x_scaled('f5.3', km))
    ]

    # the standard requires lat, lon, elevation and depth, we define them as
    # optional, however

    network = String.T(help='network code (9 characters)')
    lat = Float.T(optional=True)
    lon = Float.T(optional=True)
    coordinate_system = String.T(default='WGS-84')
    elevation = Float.T(optional=True, help='elevation [m]')
    depth = Float.T(optional=True, help='emplacement depth [m]')


class CHK2(Block):
    '''
    Representation of a CHK2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'CHK2'), dummy=True),
        E(6, 13, 'i8')
    ]

    checksum = Int.T()


class EID2(Block):
    '''
    Representation of an EID2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'EID2'), dummy=True),
        E(6, 13, 'a8'),
        E(15, 23, 'a9'),
    ]

    event_id = String.T(help='event ID (8 characters)')
    bulletin_type = String.T(help='bulletin type (9 characters)')


class BEA2(Block):
    '''
    Representation of a BEA2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'BEA2'), dummy=True),
        E(6, 17, 'a12'),
        E(19, 23, 'f5.1'),
        E(25, 29, 'f5.1')]

    beam_id = String.T(help='beam ID (12 characters)')
    azimuth = Float.T()
    slowness = Float.T()


class Network(Block):
    '''
    Representation of an entry in a NETWORK section.
    '''

    _format = [
        E(1, 9, 'a9'),
        E(11, None, 'a64+')]

    network = String.T(help='network code (9 characters)')
    description = String.T(help='description')


class Station(Block):
    '''
    Representation of an entry in a STATION section.
    '''

    _format = {
        None: [
            E(1, 9, 'a9'),
            E(11, 15, 'a5'),
            E(17, 20, 'a4'),
            E(22, 30, 'f9.5'),
            E(32, 41, 'f10.5'),
            E(43, 54, 'a12'),
            E(56, 60, x_scaled('f5.3', km)),
            E(62, 71, x_date),
            E(73, 82, optional(x_date))
        ],
        'GSE2.0': [
            E(0, -1, x_substitute('')),
            E(1, 5, 'a5'),
            E(7, 10, 'a4'),
            E(12, 20, 'f9.5'),
            E(22, 31, 'f10.5'),
            E(32, 31, x_substitute('WGS-84')),
            E(33, 39, x_scaled('f7.3', km)),
            E(41, 50, x_date),
            E(52, 61, optional(x_date))]}

    _format['IMS1.0', 'USA_DMC'] = list(_format[None])
    _format['IMS1.0', 'USA_DMC'][-2:] = [
        E(62, 71, x_date_iris),
        E(73, 82, optional(x_date_iris))]

    network = String.T(help='network code (9 characters)')
    station = String.T(help='station code (5 characters)')
    type = String.T(
        help='station type (4 characters) '
             '(1C: single component, 3C: three-component, '
             'hfa: high frequency array, lpa: long period array)')
    lat = Float.T()
    lon = Float.T()
    coordinate_system = String.T(default='WGS-84')
    elevation = Float.T(help='elevation [m]')
    tmin = Timestamp.T()
    tmax = Timestamp.T(optional=True)


class Channel(Block):
    '''
    Representation of an entry in a CHANNEL section.
    '''

    _format = {
        None: [
            E(1, 9, 'a9'),
            E(11, 15, 'a5'),
            E(17, 19, 'a3'),
            E(21, 24, 'a4'),
            E(26, 34, 'f9.5'),
            E(36, 45, 'f10.5'),
            E(47, 58, 'a12'),
            E(60, 64, x_scaled('f5.3', km)),
            E(66, 70, x_scaled('f5.3', km)),
            E(72, 77, 'f6.1'),
            E(79, 83, 'f5.1'),
            E(85, 95, 'f11.6'),
            E(97, 102, 'a6'),
            E(105, 114, x_date),
            E(116, 125, optional(x_date))],
        'GSE2.0': [
            E(0, -1, x_substitute('')),
            E(1, 5, 'a5'),
            E(7, 9, 'a3'),
            E(11, 14, 'a4'),
            E(16, 24, 'f9.5'),
            E(26, 35, 'f10.5'),
            E(32, 31, x_substitute('WGS-84')),
            E(37, 43, x_scaled('f7.3', km)),
            E(45, 50, x_scaled('f6.3', km)),
            E(52, 57, 'f6.1'),
            E(59, 63, 'f5.1'),
            E(65, 75, 'f11.6'),
            E(77, 83, 'a7'),
            E(85, 94, x_date),
            E(96, 105, optional(x_date))]}

    # norsar plays its own game...
    _format['GSE2.0', 'NOR_NDC'] = list(_format['GSE2.0'])
    _format['GSE2.0', 'NOR_NDC'][-2:] = [
        E(85, 100, x_date_time_no_seconds),
        E(102, 117, optional(x_date_time_no_seconds))]

    # also iris plays its own game...
    _format['IMS1.0', 'USA_DMC'] = list(_format[None])
    _format['IMS1.0', 'USA_DMC'][-2:] = [
        E(105, 114, x_date_iris),
        E(116, 125, optional(x_date_iris))]

    network = String.T(help='network code (9 characters)')
    station = String.T(help='station code (5 characters)')
    channel = String.T(help='channel code (3 characters)')
    location = String.T(
        default='', optional=True,
        help='location code (aux_id, 4 characters)')
    lat = Float.T(optional=True)
    lon = Float.T(optional=True)
    coordinate_system = String.T(default='WGS-84')
    elevation = Float.T(optional=True, help='elevation [m]')
    depth = Float.T(optional=True, help='emplacement depth [m]')
    horizontal_angle = Float.T(
        optional=True,
        help='horizontal orientation of sensor, clockwise from north [deg]')
    vertical_angle = Float.T(
        optional=True,
        help='vertical orientation of sensor from vertical [deg]')
    sample_rate = Float.T()
    instrument_type = String.T(
        default='', optional=True, help='instrument type (6 characters)')
    tmin = Timestamp.T()
    tmax = Timestamp.T(optional=True)


class BeamGroup(Block):
    '''
    Representation of an entry in a BEAM group table.
    '''

    _format = [
        E(1, 8, 'a8'),
        E(10, 14, 'a5'),
        E(16, 18, 'a3'),
        E(20, 23, 'a4'),
        E(25, 27, 'i3'),
        E(29, 37, 'f9.5')]

    beam_group = String.T(help='beam group (8 characters)')
    station = String.T(help='station code (5 characters)')
    channel = String.T(help='channel code (3 characters)')
    location = String.T(
        default='', optional=True,
        help='location code (aux_id, 4 characters)')
    weight = Int.T(
        optional=True,
        help='weight used for this component when the beam was formed')
    delay = Float.T(
        optional=True,
        help='beam delay for this component [s] '
             '(used for meabs formed by non-plane waves)')


class BeamType(StringChoice):
    choices = ['inc', 'coh']
    ignore_case = True


class FilterType(StringChoice):
    choices = ['BP', 'LP', 'HP', 'BR']
    ignore_case = True


class BeamParameters(Block):
    '''
    Representation of an entry in a BEAM parameters table.
    '''

    _format = [
        E(1, 12, 'a12'),
        E(14, 21, 'a8'),
        E(23, 25, 'a3'),
        E(27, 27, x_yesno),
        E(29, 33, 'f5.1'),
        E(35, 39, 'f5.3'),  # standard says f5.1 -999.0 is vertical beam
        E(41, 48, 'a8'),
        E(50, 55, 'f6.2'),
        E(57, 62, 'f6.2'),
        E(64, 65, 'i2'),
        E(67, 67, x_yesno),
        E(69, 70, 'a2'),
        E(72, 81, x_date),
        E(83, 92, optional(x_date))]

    beam_id = String.T()
    beam_group = String.T()
    type = BeamType.T()
    is_rotated = Bool.T(help='rotation flag')
    azimuth = Float.T(
        help='azimuth used to steer the beam [deg] (clockwise from North)')
    slowness = Float.T(
        help='slowness used to steer the beam [s/deg]')
    phase = String.T(
        help='phase used to set the beam slowness for origin-based beams '
             '(8 characters)')
    filter_fmin = Float.T(
        help='low frequency cut-off for the beam filter [Hz]')
    filter_fmax = Float.T(
        help='high frequency cut-off for the beam filter [Hz]')
    filter_order = Int.T(
        help='order of the beam filter')
    filter_is_zero_phase = Bool.T(
        help='flag to indicate zero-phase filtering')
    filter_type = FilterType.T(
        help='type of filtering')
    tmin = Timestamp.T(
        help='start date of beam use')
    tmax = Timestamp.T(
        optional=True,
        help='end date of beam use')


class OutageReportPeriod(Block):
    '''
    Representation of a the report period of an OUTAGE section.
    '''

    _format = [
        E(1, 18, x_fixed(b'Report period from'), dummy=True),
        E(20, 42, x_date_time),
        E(44, 45, x_fixed(b'to'), dummy=True),
        E(47, 69, x_date_time)]

    tmin = Timestamp.T()
    tmax = Timestamp.T()


class Outage(Block):
    '''
    Representation of an entry in the OUTAGE section table.
    '''
    _format = [
        E(1, 9, 'a9'),
        E(11, 15, 'a5'),
        E(17, 19, 'a3'),
        E(21, 24, 'a4'),
        E(26, 48, x_date_time),
        E(50, 72, x_date_time),
        E(74, 83, 'f10.3'),
        E(85, None, 'a48+')]

    network = String.T(help='network code (9 characters)')
    station = String.T(help='station code (5 characters)')
    channel = String.T(help='channel code (3 characters)')
    location = String.T(
        default='', optional=True,
        help='location code (aux_id, 4 characters)')
    tmin = Timestamp.T()
    tmax = Timestamp.T()
    duration = Float.T()
    comment = String.T()


class CAL2(Block):
    '''
    Representation of a CAL2 line.
    '''

    _format = {
        None: [
            E(1, 4, x_fixed(b'CAL2'), dummy=True),
            E(6, 10, 'a5'),
            E(12, 14, 'a3'),
            E(16, 19, 'a4'),
            E(21, 26, 'a6'),
            E(28, 42, x_scaled('e15.8', nm_per_s)),  # standard: e15.2
            E(44, 50, 'f7.3'),
            E(52, 62, 'f11.5'),
            E(64, 79, x_date_time_no_seconds),
            E(81, 96, optional(x_date_time_no_seconds))],
        'GSE2.0': [
            E(1, 4, x_fixed(b'CAL2'), dummy=True),
            E(6, 10, 'a5'),
            E(12, 14, 'a3'),
            E(16, 19, 'a4'),
            E(21, 26, 'a6'),
            E(28, 37, x_scaled('e10.4', nm_per_s)),
            E(39, 45, 'f7.3'),
            E(47, 56, 'f10.5'),
            E(58, 73, x_date_time_no_seconds),
            E(75, 90, optional(x_date_time_no_seconds))]}

    station = String.T(help='station code (5 characters)')
    channel = String.T(help='channel code (3 characters)')
    location = String.T(
        default='', optional=True,
        help='location code (aux_id, 4 characters)')
    instrument_type = String.T(
        default='', optional=True, help='instrument type (6 characters)')
    calibration_factor = Float.T(
        help='system sensitivity (m/count) at reference period '
             '(calibration_period)')
    calibration_period = Float.T(help='calibration reference period [s]')
    sample_rate = Float.T(help='system output sample rate [Hz]')
    tmin = Timestamp.T(help='effective start date and time')
    tmax = Timestamp.T(optional=True, help='effective end date and time')
    comments = List.T(String.T(optional=True))

    @classmethod
    def read(cls, reader):
        lstart = reader.current_line_number()
        line = reader.readline()
        obj = cls.deserialize(line, reader.version_dialect)
        while True:
            line = reader.readline()
            # make sure all comments are read
            if line is None or not line.startswith(b' '):
                reader.pushback()
                break

            obj.append_dataline(line, reader.version_dialect)

        obj.comments.extend(reader.get_comments_after(lstart))
        return obj

    def write(self, writer):
        s = self.serialize(writer.version_dialect)
        writer.writeline(s)
        for c in self.comments:
            writer.writeline((' (%s)' % c).encode('ascii'))


class Units(StringChoice):
    choices = ['V', 'A', 'C']
    ignore_case = True


class Stage(Block):
    '''
    Base class for IMS/GSE2 response stages.

    Available response stages are :py:class:`PAZ2`, :py:class:`FAP2`,
    :py:class:`GEN2`, :py:class:`DIG2`, and :py:class:`FIR2`.

    '''

    stage_number = Int.T(help='stage sequence number')

    @classmethod
    def read(cls, reader):
        lstart = reader.current_line_number()
        line = reader.readline()
        obj = cls.deserialize(line, reader.version_dialect)

        while True:
            line = reader.readline()
            if line is None or not line.startswith(b' '):
                reader.pushback()
                break

            obj.append_dataline(line, reader.version_dialect)

        obj.comments.extend(reader.get_comments_after(lstart))

        return obj

    def write(self, writer):
        line = self.serialize(writer.version_dialect)
        writer.writeline(line)
        self.write_datalines(writer)
        for c in self.comments:
            writer.writeline((' (%s)' % c).encode('ascii'))

    def write_datalines(self, writer):
        pass


class PAZ2Data(Block):
    '''
    Representation of the complex numbers in PAZ2 sections.
    '''

    _format = [
        E(2, 16, 'e15.8'),
        E(18, 32, 'e15.8')]

    real = Float.T()
    imag = Float.T()


class PAZ2(Stage):
    '''
    Representation of a PAZ2 line.
    '''

    _format = {
        None: [
            E(1, 4, x_fixed(b'PAZ2'), dummy=True),
            E(6, 7, 'i2'),
            E(9, 9, 'a1'),
            E(11, 25, 'e15.8'),
            E(27, 30, 'i4'),
            E(32, 39, 'f8.3'),
            E(41, 43, 'i3'),
            E(45, 47, 'i3'),
            E(49, None, 'a25+')],
        ('IMS1.0', 'USA_DMC'): [
            E(1, 4, x_fixed(b'PAZ2'), dummy=True),
            E(6, 7, 'i2'),
            E(9, 9, 'a1'),
            E(11, 25, 'e15.8'),
            E(27, 30, 'i4'),
            E(32, 39, 'f8.3'),
            E(40, 42, 'i3'),
            E(44, 46, 'i3'),
            E(48, None, 'a25+')]}

    output_units = Units.T(
        help='output units code (V=volts, A=amps, C=counts)')
    scale_factor = Float.T(help='scale factor [ouput units/input units]')
    decimation = Int.T(optional=True, help='decimation')
    correction = Float.T(optional=True, help='group correction applied [s]')
    npoles = Int.T(help='number of poles')
    nzeros = Int.T(help='number of zeros')
    description = String.T(default='', optional=True, help='description')

    poles = List.T(Complex.T())
    zeros = List.T(Complex.T())

    comments = List.T(String.T(optional=True))

    def append_dataline(self, line, version_dialect):
        d = PAZ2Data.deserialize(line, version_dialect)
        v = complex(d.real, d.imag)
        i = len(self.poles) + len(self.zeros)

        if i < self.npoles:
            self.poles.append(v)
        elif i < self.npoles + self.nzeros:
            self.zeros.append(v)
        else:
            raise DeserializeError(
                'more poles and zeros than expected')

    def write_datalines(self, writer):
        for pole in self.poles:
            PAZ2Data(real=pole.real, imag=pole.imag).write(writer)
        for zero in self.zeros:
            PAZ2Data(real=zero.real, imag=zero.imag).write(writer)


class FAP2Data(Block):
    '''
    Representation of the data tuples in FAP2 section.
    '''

    _format = [
        E(2, 11, 'f10.5'),
        E(13, 27, 'e15.8'),
        E(29, 32, 'i4')]

    frequency = Float.T()
    amplitude = Float.T()
    phase = Float.T()


class FAP2(Stage):
    '''
    Representation of a FAP2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'FAP2'), dummy=True),
        E(6, 7, 'i2'),
        E(9, 9, 'a1'),
        E(11, 14, 'i4'),
        E(16, 23, 'f8.3'),
        E(25, 27, 'i3'),
        E(29, 53, 'a25')]

    output_units = Units.T(
        help='output units code (V=volts, A=amps, C=counts)')
    decimation = Int.T(optional=True, help='decimation')
    correction = Float.T(help='group correction applied [s]')
    ntrip = Int.T(help='number of frequency, amplitude, phase triplets')
    description = String.T(default='', optional=True, help='description')

    frequencies = List.T(Float.T(), help='frequency [Hz]')
    amplitudes = List.T(
        Float.T(), help='amplitude [input untits/output units]')
    phases = List.T(Float.T(), help='phase delay [degrees]')

    comments = List.T(String.T(optional=True))

    def append_dataline(self, line, version_dialect):
        d = FAP2Data.deserialize(line, version_dialect)
        self.frequencies.append(d.frequency)
        self.amplitudes.append(d.amplitude)
        self.phases.append(d.phase)

    def write_datalines(self, writer):
        for frequency, amplitude, phase in zip(
                self.frequencies, self.amplitudes, self.phases):

            FAP2Data(
                frequency=frequency,
                amplitude=amplitude,
                phase=phase).write(writer)


class GEN2Data(Block):
    '''
    Representation of a data tuple in GEN2 section.
    '''

    _format = [
        E(2, 12, 'f11.5'),
        E(14, 19, 'f6.3')]

    corner = Float.T(help='corner frequency [Hz]')
    slope = Float.T(help='slope above corner [dB/decate]')


class GEN2(Stage):
    '''
    Representation of a GEN2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'GEN2'), dummy=True),
        E(6, 7, 'i2'),
        E(9, 9, 'a1'),
        E(11, 25, x_scaled('e15.8', nm_per_s)),
        E(27, 33, 'f7.3'),
        E(35, 38, 'i4'),
        E(40, 47, 'f8.3'),
        E(49, 51, 'i3'),
        E(53, 77, 'a25')]

    output_units = Units.T(
        help='output units code (V=volts, A=amps, C=counts)')
    calibration_factor = Float.T(
        help='system sensitivity (m/count) at reference period '
             '(calibration_period)')
    calibration_period = Float.T(help='calibration reference period [s]')
    decimation = Int.T(optional=True, help='decimation')
    correction = Float.T(help='group correction applied [s]')
    ncorners = Int.T(help='number of corners')
    description = String.T(default='', optional=True, help='description')

    corners = List.T(Float.T(), help='corner frequencies [Hz]')
    slopes = List.T(Float.T(), help='slopes above corners [dB/decade]')

    comments = List.T(String.T(optional=True))

    def append_dataline(self, line, version_dialect):
        d = GEN2Data.deserialize(line, version_dialect)
        self.corners.append(d.corner)
        self.slopes.append(d.slope)

    def write_datalines(self, writer):
        for corner, slope in zip(self.corners, self.slopes):
            GEN2Data(corner=corner, slope=slope).write(writer)


class DIG2(Stage):
    '''
    Representation of a DIG2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'DIG2'), dummy=True),
        E(6, 7, 'i2'),
        E(9, 23, 'e15.8'),
        E(25, 35, 'f11.5'),
        E(37, None, 'a25+')]

    sensitivity = Float.T(help='sensitivity [counts/input units]')
    sample_rate = Float.T(help='digitizer sample rate [Hz]')
    description = String.T(default='', optional=True, help='description')

    comments = List.T(String.T(optional=True))


class SymmetryFlag(StringChoice):
    choices = ['A', 'B', 'C']
    ignore_case = True


class FIR2Data(Block):
    '''
    Representation of a line of coefficients in a FIR2 section.
    '''

    _format = [
        E(2, 16, 'e15.8'),
        E(18, 32, 'e15.8'),
        E(34, 48, 'e15.8'),
        E(50, 64, 'e15.8'),
        E(66, 80, 'e15.8')]

    factors = List.T(Float.T())

    def values(self):
        return self.factors + [None]*(5-len(self.factors))

    @classmethod
    def deserialize(cls, line, version_dialect):
        factors = [v for v in cls.deserialize_values(line, version_dialect)
                   if v is not None]
        return cls.validated(factors=factors)


class FIR2(Stage):
    '''
    Representation of a FIR2 line.
    '''

    _format = [
        E(1, 4, x_fixed(b'FIR2'), dummy=True),
        E(6, 7, 'i2'),
        E(9, 18, 'e10.2'),
        E(20, 23, 'i4'),
        E(25, 32, 'f8.3'),
        E(34, 34, 'a1'),
        E(36, 39, 'i4'),
        E(41, None, 'a25+')]

    gain = Float.T(help='filter gain (relative factor, not in dB)')
    decimation = Int.T(optional=True, help='decimation')
    correction = Float.T(help='group correction applied [s]')
    symmetry = SymmetryFlag.T(
        help='symmetry flag (A=asymmetric, B=symmetric (odd), '
             'C=symmetric (even))')
    nfactors = Int.T(help='number of factors')
    description = String.T(default='', optional=True, help='description')

    comments = List.T(String.T(optional=True))

    factors = List.T(Float.T())

    def append_dataline(self, line, version_dialect):
        d = FIR2Data.deserialize(line, version_dialect)
        self.factors.extend(d.factors)

    def write_datalines(self, writer):
        i = 0
        while i < len(self.factors):
            FIR2Data(factors=self.factors[i:i+5]).write(writer)
            i += 5


class Begin(FreeFormatLine):
    '''
    Representation of a BEGIN line.
    '''

    _format = [b'BEGIN', 1]
    version = String.T(optional=True)

    @classmethod
    def read(cls, reader):
        line = reader.readline()
        obj = cls.deserialize(line, reader.version_dialect)
        reader.version_dialect[0] = obj.version
        return obj

    def write(self, writer):
        FreeFormatLine.write(self, writer)
        writer.version_dialect[0] = self.version


class MessageType(StringChoice):
    choices = ['REQUEST', 'DATA', 'SUBSCRIPTION']
    ignore_case = True


class MsgType(FreeFormatLine):
    _format = [b'MSG_TYPE', 1]
    type = MessageType.T()


class MsgID(FreeFormatLine):
    '''
    Representation of a MSG_ID line.
    '''

    _format = [b'MSG_ID', 1, 2]
    msg_id_string = String.T()
    msg_id_source = String.T(optional=True)

    @classmethod
    def read(cls, reader):
        line = reader.readline()
        obj = cls.deserialize(line, reader.version_dialect)
        if obj.msg_id_source in g_dialects:
            reader.version_dialect[1] = obj.msg_id_source

        return obj

    def write(self, writer):
        FreeFormatLine.write(self, writer)
        if self.msg_id_source in g_dialects:
            writer.version_dialect[1] = self.msg_id_source


class RefID(FreeFormatLine):
    '''
    Representation of a REF_ID line.
    '''

    _format = {
        None: [b'REF_ID', 1, 2, 'PART', 3, 'OF', 4],
        'GSE2.0': [b'REF_ID', 1]}

    msg_id_string = String.T()
    msg_id_source = String.T(optional=True)
    sequence_number = Int.T(optional=True)
    total_number = Int.T(optional=True)

    def serialize(self, version_dialect):
        out = ['REF_ID', self.msg_id_string]
        if self.msg_id_source:
            out.append(self.msg_id_source)
            i = self.sequence_number
            n = self.total_number
            if i is not None and n is not None:
                out.extend(['PART', str(i), 'OF', str(n)])

        return ' '.join(out).encode('ascii')


class LogSection(Section):
    '''
    Representation of a DATA_TYPE LOG section.
    '''

    keyword = b'LOG'
    lines = List.T(String.T())

    @classmethod
    def read(cls, reader):
        DataType.read(reader)
        lines = []
        while True:
            line = reader.readline()
            if end_section(line):
                reader.pushback()
                break
            else:
                lines.append(str(line.decode('ascii')))

        return cls(lines=lines)

    def write(self, writer):
        self.write_datatype(writer)
        for line in self.lines:
            ul = line.upper()
            if ul.startswith('DATA_TYPE') or ul.startswith('STOP'):
                line = ' ' + line

            writer.writeline(str.encode(line))


class ErrorLogSection(LogSection):
    '''
    Representation of a DATA_TYPE ERROR_LOG section.
    '''

    keyword = b'ERROR_LOG'


class FTPLogSection(Section):
    '''
    Representation of a DATA_TYPE FTP_LOG section.
    '''

    keyword = b'FTP_LOG'
    ftp_file = FTPFile.T()

    @classmethod
    def read(cls, reader):
        DataType.read(reader)
        ftp_file = FTPFile.read(reader)
        return cls(ftp_file=ftp_file)

    def write(self, writer):
        self.write_datatype(writer)
        self.ftp_file.write(writer)


class WID2Section(Section):
    '''
    Representation of a WID2/STA2/EID2/BEA2/DAT2/CHK2 group.
    '''

    wid2 = WID2.T()
    sta2 = STA2.T(optional=True)
    eid2s = List.T(EID2.T())
    bea2 = BEA2.T(optional=True)
    dat2 = DAT2.T()
    chk2 = CHK2.T()

    @classmethod
    def read(cls, reader):
        blocks = dict(eid2s=[])
        expect = [(b'WID2 ', WID2, 1)]

        if reader.version_dialect[0] == 'GSE2.0':
            # should not be there in GSE2.0, but BGR puts it there
            expect.append((b'STA2 ', STA2, 0))
        else:
            expect.append((b'STA2 ', STA2, 1))

        expect.extend([
            (b'EID2 ', EID2, 0),
            (b'BEA2 ', BEA2, 0),
            (b'DAT2', DAT2, 1),
            (b'CHK2 ', CHK2, 1)])

        for k, handler, required in expect:
            line = reader.readline()
            reader.pushback()

            if line is None:
                raise DeserializeError('incomplete waveform section')

            if line.upper().startswith(k):
                block = handler.read(reader)
                if k == b'EID2 ':
                    blocks['eid2s'].append(block)
                else:
                    blocks[str(k.lower().rstrip().decode('ascii'))] = block
            else:
                if required:
                    raise DeserializeError('expected %s block' % k)
                else:
                    continue

        return cls(**blocks)

    def write(self, writer):
        self.wid2.write(writer)
        if self.sta2:
            self.sta2.write(writer)
        for eid2 in self.eid2s:
            eid2.write(writer)
        if self.bea2:
            self.bea2.write(writer)

        self.dat2.write(writer)
        self.chk2.write(writer)

    def pyrocko_trace(self, checksum_error='raise'):
        from pyrocko import ims_ext, trace
        assert checksum_error in ('raise', 'warn', 'ignore')

        raw_data = self.dat2.raw_data
        nsamples = self.wid2.nsamples
        deltat = 1.0 / self.wid2.sample_rate
        tmin = self.wid2.time
        if self.sta2:
            net = self.sta2.network
        else:
            net = ''
        sta = self.wid2.station
        loc = self.wid2.location
        cha = self.wid2.channel

        if raw_data:
            ydata = ims_ext.decode_cm6(b''.join(raw_data), nsamples)
            if checksum_error != 'ignore':
                if ims_ext.checksum(ydata) != self.chk2.checksum:
                    mess = 'computed checksum value differs from stored value'
                    if checksum_error == 'raise':
                        raise DeserializeError(mess)
                    elif checksum_error == 'warn':
                        logger.warning(mess)

            tmax = None
        else:
            tmax = tmin + (nsamples - 1) * deltat
            ydata = None

        return trace.Trace(
            net, sta, loc, cha, tmin=tmin, tmax=tmax,
            deltat=deltat,
            ydata=ydata)

    @classmethod
    def from_pyrocko_trace(cls, tr,
                           lat=None, lon=None, elevation=None, depth=None):

        from pyrocko import ims_ext
        ydata = tr.get_ydata()
        raw_data = ims_ext.encode_cm6(ydata)
        return cls(
            wid2=WID2(
                nsamples=tr.data_len(),
                sample_rate=1.0 / tr.deltat,
                time=tr.tmin,
                station=tr.station,
                location=tr.location,
                channel=tr.channel),
            sta2=STA2(
                network=tr.network,
                lat=lat,
                lon=lon,
                elevation=elevation,
                depth=depth),
            dat2=DAT2(
                raw_data=[raw_data[i*80:(i+1)*80]
                          for i in range((len(raw_data)-1)//80 + 1)]),
            chk2=CHK2(
                checksum=ims_ext.checksum(ydata)))


class OUT2Section(Section):
    '''
    Representation of a OUT2/STA2 group.
    '''

    out2 = OUT2.T()
    sta2 = STA2.T()

    @classmethod
    def read(cls, reader):
        out2 = OUT2.read(reader)
        line = reader.readline()
        reader.pushback()
        if line.startswith(b'STA2'):
            # the spec sais STA2 is mandatory but in practice, it is not
            # always there...
            sta2 = STA2.read(reader)
        else:
            sta2 = None

        return cls(out2=out2, sta2=sta2)

    def write(self, writer):
        self.out2.write(writer)
        if self.sta2 is not None:
            self.sta2.write(writer)


class DLY2Section(Section):
    '''
    Representation of a DLY2/STA2 group.
    '''

    dly2 = DLY2.T()
    sta2 = STA2.T()

    @classmethod
    def read(cls, reader):
        dly2 = DLY2.read(reader)
        sta2 = STA2.read(reader)
        return cls(dly2=dly2, sta2=sta2)

    def write(self, writer):
        self.dly2.write(writer)
        self.sta2.write(writer)


class WaveformSection(Section):
    '''
    Representation of a DATA_TYPE WAVEFORM line.

    Any subsequent WID2/OUT2/DLY2 groups are handled as indepenent sections, so
    this type just serves as a dummy to read/write the DATA_TYPE WAVEFORM
    header.
    '''

    keyword = b'WAVEFORM'

    datatype = DataType.T()

    @classmethod
    def read(cls, reader):
        datatype = DataType.read(reader)
        return cls(datatype=datatype)

    def write(self, writer):
        self.datatype.write(writer)


class TableSection(Section):
    '''
    Base class for table style sections.
    '''

    has_data_type_header = True

    @classmethod
    def read(cls, reader):
        if cls.has_data_type_header:
            DataType.read(reader)

        ts = cls.table_setup

        header = get_versioned(ts['header'], reader.version_dialect)
        blocks = list(cls.read_table(
            reader, header, ts['cls'], end=ts.get('end', end_section)))
        return cls(**{ts['attribute']: blocks})

    def write(self, writer):
        if self.has_data_type_header:
            self.write_datatype(writer)

        ts = self.table_setup
        header = get_versioned(ts['header'], writer.version_dialect)
        self.write_table(writer, header, getattr(self, ts['attribute']))


class NetworkSection(TableSection):
    '''
    Representation of a DATA_TYPE NETWORK section.
    '''

    keyword = b'NETWORK'
    table_setup = dict(
        header=b'Net       Description',
        attribute='networks',
        cls=Network)

    networks = List.T(Network.T())


class StationSection(TableSection):
    '''
    Representation of a DATA_TYPE STATION section.
    '''

    keyword = b'STATION'
    table_setup = dict(
        header={
            None: (
                b'Net       Sta   Type  Latitude  Longitude Coord '
                b'Sys     Elev   On Date   Off Date'),
            'GSE2.0': (
                b'Sta   Type  Latitude  Longitude    Elev   On Date   '
                b'Off Date')},
        attribute='stations',
        cls=Station)

    stations = List.T(Station.T())


class ChannelSection(TableSection):
    '''
    Representation of a DATA_TYPE CHANNEL section.
    '''

    keyword = b'CHANNEL'
    table_setup = dict(
        header={
            None: (
                b'Net       Sta  Chan Aux   Latitude Longitude  Coord Sys'
                b'       Elev   Depth   Hang  Vang Sample Rate Inst      '
                b'On Date    Off Date'),
            'GSE2.0': (
                b'Sta  Chan Aux   Latitude  Longitude    '
                b'Elev  Depth   Hang  Vang Sample_Rate Inst       '
                b'On Date   Off Date')},
        attribute='channels',
        cls=Channel)

    channels = List.T(Channel.T())


class BeamSection(Section):
    '''
    Representation of a DATA_TYPE BEAM section.
    '''

    keyword = b'BEAM'
    beam_group_header = b'Bgroup   Sta  Chan Aux  Wgt     Delay'
    beam_parameters_header = b'BeamID       Bgroup Btype R  Azim  Slow '\
                             b'Phase       Flo    Fhi  O Z F    '\
                             b'On Date    Off Date'
    group = List.T(BeamGroup.T())
    parameters = List.T(BeamParameters.T())

    @classmethod
    def read(cls, reader):
        DataType.read(reader)

        def end(line):
            return line.upper().startswith(b'BEAMID')

        group = list(cls.read_table(reader, cls.beam_group_header, BeamGroup,
                                    end))

        parameters = list(cls.read_table(reader, cls.beam_parameters_header,
                                         BeamParameters))

        return cls(group=group, parameters=parameters)

    def write(self, writer):
        self.write_datatype(writer)
        self.write_table(writer, self.beam_group_header, self.group)
        writer.writeline(b'')
        self.write_table(writer, self.beam_parameters_header, self.parameters)


class CAL2Section(Section):
    '''
    Representation of a CAL2 + stages group in a response section.
    '''

    cal2 = CAL2.T()
    stages = List.T(Stage.T())

    @classmethod
    def read(cls, reader):
        cal2 = CAL2.read(reader)
        stages = []
        handlers = {
            b'PAZ2': PAZ2,
            b'FAP2': FAP2,
            b'GEN2': GEN2,
            b'DIG2': DIG2,
            b'FIR2': FIR2}

        while True:
            line = reader.readline()
            reader.pushback()
            if end_section(line, b'CAL2'):
                break

            k = line[:4].upper()
            if k in handlers:
                stages.append(handlers[k].read(reader))
            else:
                raise DeserializeError('unexpected line')

        return cls(cal2=cal2, stages=stages)

    def write(self, writer):
        self.cal2.write(writer)
        for stage in self.stages:
            stage.write(writer)


class ResponseSection(Section):
    '''
    Representation of a DATA_TYPE RESPONSE line.

    Any subsequent CAL2+stages groups are handled as indepenent sections, so
    this type just serves as a dummy to read/write the DATA_TYPE RESPONSE
    header.
    '''

    keyword = b'RESPONSE'

    datatype = DataType.T()

    @classmethod
    def read(cls, reader):
        datatype = DataType.read(reader)
        return cls(datatype=datatype)

    def write(self, writer):
        self.datatype.write(writer)


class OutageSection(Section):
    '''
    Representation of a DATA_TYPE OUTAGE section.
    '''

    keyword = b'OUTAGE'
    outages_header = b'NET       Sta  Chan Aux      Start Date Time'\
                     b'          End Date Time        Duration Comment'
    report_period = OutageReportPeriod.T()
    outages = List.T(Outage.T())

    @classmethod
    def read(cls, reader):
        DataType.read(reader)
        report_period = OutageReportPeriod.read(reader)
        outages = []
        outages = list(cls.read_table(reader, cls.outages_header,
                                      Outage))

        return cls(
            report_period=report_period,
            outages=outages)

    def write(self, writer):
        self.write_datatype(writer)
        self.report_period.write(writer)
        self.write_table(writer, self.outages_header, self.outages)


class BulletinTitle(Block):

    _format = [
        E(1, 136, 'a136')]

    title = String.T()


g_event_types = dict(
    uk='unknown',
    ke='known earthquake',
    se='suspected earthquake',
    kr='known rockburst',
    sr='suspected rockburst',
    ki='known induced event',
    si='suspected induced event',
    km='known mine explosion',
    sm='suspected mine explosion',
    kx='known experimental explosion',
    sx='suspected experimental explosion',
    kn='known nuclear explosion',
    sn='suspected nuclear explosion',
    ls='landslide',
    de='??',
    fe='??',)


class Origin(Block):
    _format = [
        E(1, 22, x_date_time_2frac),
        E(23, 23, 'a1?'),
        E(25, 29, 'f5.2'),
        E(31, 35, 'f5.2'),
        E(37, 44, 'f8.4'),
        E(46, 54, 'f9.4'),
        E(55, 55, 'a1?'),
        E(57, 60, x_scaled('f4.1', km)),
        E(62, 66, x_scaled('f5.1', km)),
        E(68, 70, x_int_angle),
        E(72, 76, x_scaled('f5.1', km)),
        E(77, 77, 'a1?'),
        E(79, 82, x_scaled('f4.1', km)),
        E(84, 87, 'i4'),
        E(89, 92, 'i4'),
        E(94, 96, x_int_angle),
        E(98, 103, 'f6.2'),
        E(105, 110, 'f6.2'),
        E(112, 112, 'a1?'),
        E(114, 114, 'a1?'),
        E(116, 117, 'a2?'),
        E(119, 127, 'a9'),
        E(129, 136, 'a8')]

    time = Timestamp.T(
        help='epicenter date and time')

    time_fixed = StringChoice.T(
        choices=['f'],
        optional=True,
        help='fixed flag, ``"f"`` if fixed origin time solution, '
             '``None`` if not')

    time_error = Float.T(
        optional=True,
        help='origin time error [seconds], ``None`` if fixed origin time')

    residual = Float.T(
        optional=True,
        help='root mean square of time residuals [seconds]')

    lat = Float.T(
        help='latitude')

    lon = Float.T(
        help='longitude')

    lat_lon_fixed = StringChoice.T(
        choices=['f'], optional=True,
        help='fixed flag, ``"f"`` if fixed epicenter solution, '
             '``None`` if not')

    ellipse_semi_major_axis = Float.T(
        optional=True,
        help='semi-major axis of 90% c. i. ellipse or its estimate [m], '
             '``None`` if fixed')

    ellipse_semi_minor_axis = Float.T(
        optional=True,
        help='semi-minor axis of 90% c. i. ellipse or its estimate [m], '
             '``None`` if fixed')

    ellipse_strike = Float.T(
        optional=True,
        help='strike of 90% c. i. ellipse [0-360], ``None`` if fixed')

    depth = Float.T(
        help='depth [m]')

    depth_fixed = StringChoice.T(
        choices=['f', 'd'], optional=True,
        help='fixed flag, ``"f"`` fixed depth station, "d" depth phases, '
             '``None`` if not fixed depth')

    depth_error = Float.T(
        optional=True,
        help='depth error [m], 90% c. i., ``None`` if fixed depth')

    nphases = Int.T(
        optional=True,
        help='number of defining phases')

    nstations = Int.T(
        optional=True,
        help='number of defining stations')

    azimuthal_gap = Float.T(
        optional=True,
        help='gap in azimuth coverage [deg]')

    distance_min = Float.T(
        optional=True,
        help='distance to closest station [deg]')

    distance_max = Float.T(
        optional=True,
        help='distance to furthest station [deg]')

    analysis_type = StringChoice.T(
        optional=True,
        choices=['a', 'm', 'g'],
        help='analysis type, ``"a"`` automatic, ``"m"`` manual, ``"g"`` guess')

    location_method = StringChoice.T(
        optional=True,
        choices=['i', 'p', 'g', 'o'],
        help='location method, ``"i"`` inversion, ``"p"`` pattern, '
             '``"g"`` ground truth, ``"o"`` other')

    event_type = StringChoice.T(
        optional=True,
        choices=sorted(g_event_types.keys()),
        help='event type, ' + ', '.join(
            '``"%s"`` %s' % (k, g_event_types[k])
            for k in sorted(g_event_types.keys())))

    author = String.T(help='author of the origin')
    origin_id = String.T(help='origin identification')


class OriginSection(TableSection):
    has_data_type_header = False

    table_setup = dict(
        header={
            None: (
                b'   Date       Time        Err   RMS Latitude Longitude  '
                b'Smaj  Smin  Az Depth   Err Ndef Nsta Gap  mdist  Mdist '
                b'Qual   Author      OrigID')},
        attribute='origins',
        end=lambda line: end_section(line, b'EVENT'),
        cls=Origin)

    origins = List.T(Origin.T())


class EventTitle(Block):
    _format = [
        E(1, 5, x_fixed(b'Event'), dummy=True),
        E(7, 14, 'a8'),
        E(16, 80, 'a65')]

    event_id = String.T()
    region = String.T()


class EventSection(Section):
    '''
    Groups Event, Arrival, ...
    '''

    event_title = EventTitle.T()
    origin_section = OriginSection.T()

    @classmethod
    def read(cls, reader):
        event_title = EventTitle.read(reader)
        origin_section = OriginSection.read(reader)
        return cls(
            event_title=event_title,
            origin_section=origin_section)

    def write(self, writer):
        self.event_title.write(writer)
        self.origin_section.write(writer)


class EventsSection(Section):
    '''
    Representation of a DATA_TYPE EVENT section.
    '''

    keyword = b'EVENT'

    bulletin_title = BulletinTitle.T()
    event_sections = List.T(EventSection.T())

    @classmethod
    def read(cls, reader):
        DataType.read(reader)
        bulletin_title = BulletinTitle.read(reader)
        event_sections = []
        while True:
            line = reader.readline()
            reader.pushback()
            if end_section(line):
                break

            if line.upper().startswith(b'EVENT'):
                event_sections.append(EventSection.read(reader))

        return cls(
            bulletin_title=bulletin_title,
            event_sections=event_sections,
        )

    def write(self, writer):
        self.write_datatype(writer)
        self.bulletin_title.write(writer)
        for event_section in self.event_sections:
            event_section.write(writer)


class BulletinSection(EventsSection):
    '''
    Representation of a DATA_TYPE BULLETIN section.
    '''

    keyword = b'BULLETIN'


for sec in (
        LogSection, ErrorLogSection, FTPLogSection, WaveformSection,
        NetworkSection, StationSection, ChannelSection, BeamSection,
        ResponseSection, OutageSection, EventsSection, BulletinSection):

    Section.handlers[sec.keyword] = sec

del sec


class MessageHeader(Section):
    '''
    Representation of a BEGIN/MSG_TYPE/MSG_ID/REF_ID group.
    '''

    version = String.T()
    type = String.T()
    msg_id = MsgID.T(optional=True)
    ref_id = RefID.T(optional=True)

    @classmethod
    def read(cls, reader):
        handlers = {
            b'BEGIN': Begin,
            b'MSG_TYPE': MsgType,
            b'MSG_ID': MsgID,
            b'REF_ID': RefID}

        blocks = {}
        while True:
            line = reader.readline()
            reader.pushback()
            ok = False
            for k in handlers:
                if line.upper().startswith(k):
                    blocks[k] = handlers[k].read(reader)
                    ok = True

            if not ok:
                break

        return MessageHeader(
            type=blocks[b'MSG_TYPE'].type,
            version=blocks[b'BEGIN'].version,
            msg_id=blocks.get(b'MSG_ID', None),
            ref_id=blocks.get(b'REF_ID', None))

    def write(self, writer):
        Begin(version=self.version).write(writer)
        MsgType(type=self.type).write(writer)
        if self.msg_id is not None:
            self.msg_id.write(writer)
        if self.ref_id is not None:
            self.ref_id.write(writer)


def parse_ff_date_time(s):
    toks = s.split()
    if len(toks) == 2:
        sdate, stime = toks
    else:
        sdate, stime = toks[0], ''

    stime += '00:00:00.000'[len(stime):]
    return util.str_to_time(
        sdate + ' ' + stime, format='%Y/%m/%d %H:%M:%S.3FRAC')


def string_ff_date_time(t):
    return util.time_to_str(t, format='%Y/%m/%d %H:%M:%S.3FRAC')


class TimeStamp(FreeFormatLine):
    '''
    Representation of a TIME_STAMP line.
    '''

    _format = [b'TIME_STAMP', 1]

    value = Timestamp.T()

    @classmethod
    def deserialize(cls, line, version_dialect):
        (s,) = cls.deserialize_values(line, version_dialect)
        return cls(value=parse_ff_date_time(s))

    def serialize(self, line, version_dialect):
        return (
            'TIME_STAMP %s' % string_ff_date_time(self.value)).encode('ascii')


class Stop(FreeFormatLine):
    '''
    Representation of a STOP line.
    '''

    _format = [b'STOP']

    dummy = String.T(optional=True)


class XW01(FreeFormatLine):
    '''
    Representation of a XW01 line (which is a relict from GSE1).
    '''

    _format = [b'XW01']

    dummy = String.T(optional=True)


re_comment = re.compile(br'^(%(.+)\s*| \((#?)(.+)\)\s*)$')
re_comment_usa_dmc = re.compile(br'^(%(.+)\s*| ?\((#?)(.+)\)\s*)$')


class Reader(object):
    def __init__(self, f, load_data=True, version=None, dialect=None):
        self._f = f
        self._load_data = load_data
        self._current_fpos = None
        self._current_lpos = None  # "physical" line number
        self._current_line = None
        self._readline_count = 0
        self._pushed_back = False
        self._handlers = {
            b'DATA_TYPE ': Section,
            b'WID2 ': WID2Section,
            b'OUT2 ': OUT2Section,
            b'DLY2 ': DLY2Section,
            b'CAL2 ': CAL2Section,
            b'BEGIN': MessageHeader,
            b'STOP': Stop,
            b'XW01': XW01,   # for compatibility with BGR dialect
            b'HANG:': None,  # for compatibility with CNDC
            b'VANG:': None,
        }
        self._comment_lines = []
        self._time_stamps = []
        self.version_dialect = [version, dialect]  # main version, dialect
        self._in_garbage = True

    def tell(self):
        return self._current_fpos

    def current_line_number(self):
        return self._current_lpos - int(self._pushed_back)

    def readline(self):
        if self._pushed_back:
            self._pushed_back = False
            return self._current_line

        while True:
            self._current_fpos = self._f.tell()
            self._current_lpos = self._readline_count + 1
            ln = self._f.readline()
            self._readline_count += 1
            if not ln:
                self._current_line = None
                return None

            lines = [ln.rstrip(b'\n\r')]
            while lines[-1].endswith(b'\\'):
                lines[-1] = lines[-1][:-1]
                ln = self._f.readline()
                self._readline_count += 1
                lines.append(ln.rstrip(b'\n\r'))

            self._current_line = b''.join(lines)

            if self.version_dialect[1] == 'USA_DMC':
                m_comment = re_comment_usa_dmc.match(self._current_line)
            else:
                m_comment = re_comment.match(self._current_line)

            if not self._current_line.strip():
                pass

            elif m_comment:
                comment_type = None
                if m_comment.group(3) == b'#':
                    comment_type = 'ISF'
                elif m_comment.group(4) is not None:
                    comment_type = 'IMS'

                comment = m_comment.group(2) or m_comment.group(4)

                self._comment_lines.append(
                    (self._current_lpos, comment_type,
                     str(comment.decode('ascii'))))

            elif self._current_line[:10].upper() == b'TIME_STAMP':
                self._time_stamps.append(
                    TimeStamp.deserialize(
                        self._current_line, self.version_dialect))

            else:
                return self._current_line

    def get_comments_after(self, lpos):
        comments = []
        i = len(self._comment_lines) - 1
        while i >= 0:
            if self._comment_lines[i][0] <= lpos:
                break

            comments.append(self._comment_lines[i][-1])
            i -= 1

        return comments

    def pushback(self):
        assert not self._pushed_back
        self._pushed_back = True

    def __iter__(self):
        return self

    def next(self):
        return self.__next__()

    def __next__(self):
        try:
            while True:
                line = self.readline()
                if line is None:
                    raise StopIteration()

                ignore = False
                for k in self._handlers:
                    if line.upper().startswith(k):
                        if self._handlers[k] is None:
                            ignore = True
                            break

                        self.pushback()
                        sec = self._handlers[k].read(self)
                        if isinstance(sec, Stop):
                            self._in_garbage = True
                        else:
                            self._in_garbage = False
                        return sec

                if not self._in_garbage and not ignore:
                    raise DeserializeError('unexpected line')

        except DeserializeError as e:
            e.set_context(
                self._current_lpos,
                self._current_line,
                self.version_dialect)
            raise


class Writer(object):

    def __init__(self, f, version='GSE2.1', dialect=None):
        self._f = f
        self.version_dialect = [version, dialect]

    def write(self, section):
        section.write(self)

    def writeline(self, line):
        self._f.write(line.rstrip())
        self._f.write(b'\n')


def write_string(sections):
    from io import BytesIO
    f = BytesIO()
    w = Writer(f)
    for section in sections:
        w.write(section)

    return f.getvalue()


def iload_fh(f, **kwargs):
    '''
    Load IMS/GSE2 records from open file handle.
    '''
    try:
        r = Reader(f, **kwargs)
        for section in r:
            yield section

    except DeserializeError as e:
        raise FileLoadError(e)


def iload_string(s, **kwargs):
    '''
    Read IMS/GSE2 sections from bytes string.
    '''

    from io import BytesIO
    f = BytesIO(s)
    return iload_fh(f, **kwargs)


iload_filename, iload_dirname, iload_glob, iload = util.make_iload_family(
    iload_fh, 'IMS/GSE2', ':py:class:`Section`')


def dump_fh(sections, f):
    '''
    Dump IMS/GSE2 sections to open file handle.
    '''
    try:
        w = Writer(f)
        for section in sections:
            w.write(section)

    except SerializeError as e:
        raise FileSaveError(e)


def dump_string(sections):
    '''
    Write IMS/GSE2 sections to string.
    '''

    from io import BytesIO
    f = BytesIO()
    dump_fh(sections, f)
    return f.getvalue()


if __name__ == '__main__':
    from optparse import OptionParser

    usage = 'python -m pyrocko.ims <filenames>'

    util.setup_logging('pyrocko.ims.__main__', 'warning')

    description = '''
    Read and print IMS/GSE2 records.
    '''

    parser = OptionParser(
        usage=usage,
        description=description,
        formatter=util.BetterHelpFormatter())

    parser.add_option(
        '--version',
        dest='version',
        choices=g_versions,
        help='inial guess for version')

    parser.add_option(
        '--dialect',
        dest='dialect',
        choices=g_dialects,
        help='inial guess for dialect')

    parser.add_option(
        '--load-data',
        dest='load_data',
        action='store_true',
        help='unpack data samples')

    parser.add_option(
        '--out-version',
        dest='out_version',
        choices=g_versions,
        help='output format version')

    parser.add_option(
        '--out-dialect',
        dest='out_dialect',
        choices=g_dialects,
        help='output format dialect')

    (options, args) = parser.parse_args(sys.argv[1:])

    for fn in args:
        with open(fn, 'rb') as f:

            r = Reader(f, load_data=options.load_data,
                       version=options.version, dialect=options.dialect)

            w = None
            if options.out_version is not None:
                w = Writer(
                    sys.stdout, version=options.out_version,
                    dialect=options.out_dialect)

            for sec in r:
                if not w:
                    print(sec)

                else:
                    w.write(sec)

                if isinstance(sec, WID2Section) and options.load_data:
                    tr = sec.pyrocko_trace(checksum_error='warn')
