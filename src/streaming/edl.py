# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Live stream reader for Earth Data EDL data loggers.
'''

import struct
import collections
import time
import logging
import calendar
import numpy as num

from pyrocko import trace, util

logger = logging.getLogger('pyrocko.streaming.edl')


def hexdump(chars, sep=' ', width=16):
    while chars:
        line = chars[:width]
        chars = chars[width:]
        line = line.ljust(width, '\000')
        print('%s%s%s' % (
            sep.join('%02x' % ord(c) for c in line),
            sep, quotechars(line)))


def quotechars(chars):
    return ''.join(['.', c][c.isalnum()] for c in chars)


MINBLOCKSIZE = 192


class NotAquiring(Exception):
    pass


class ReadError(Exception):
    pass


class ReadTimeout(ReadError):
    pass


class ReadUnexpected(ReadError):
    pass


class GPSError(Exception):
    pass


class NoGPS(GPSError):
    pass


class NoGPSTime(GPSError):
    pass


class GPSTimeNotUTC(GPSError):
    pass


block_def = {}

block_def['MOD\0'] = '''
        identifier 4s
        size_of_mod I
        device_id 12s
        version 6s
        space1 1s
        serial_no 4s
        space2 1s
        test_pattern 8s
        block_count I
        ncomps H
        sample_rate H
        bytes_per_sample H
        filter_type 2s
        decimation3 H
        decimation4 H
        plldata h
        gain_g 1s
        gain B
        gain_component1 I
        gain_component2 I
        gain_component3 I
        offset_component1 I
        offset_component2 I
        offset_component3 I
        supply_voltage H
        supply_current H
        temp_sensor_voltage H
        supply_voltage_remote H
        user_input1 H
        user_input2 H
        user_input3 H
        not_used H
        coupling 2s
        reserved1 I
        reserved2 I
        reserved3 I
        gps_status_flags H
        gps_message_block_count I
        gps_message 72s
'''.split()

block_def['MDE\0'] = '''
        identifier 4s
        size_of_mde I
        serial_no 8s
        decimation5 H
        decimation6 H
        decimation7 H
        gain_component4 I
        gain_component5 I
        gain_component6 I
        offset_component4 I
        offset_component5 I
        offset_component6 I
        temperature1 H
        temperature2 H
        temperature3 H
        temperature4 H
        temperature5 H
        temperature6 H
        gps_message 129s
        pad 1s
'''.split()

block_def['SUM\0'] = '''
        identifier 4s
        size_of_sum I
        reserved H
        checksum_lo B
        checksum_hi B
'''.split()

block_def['DAT\0'] = '''
        identifier 4s
        size_of_dat I
'''.split()


def make_block_classes():

    Blocks = {}
    for k in block_def.keys():
        fmt = '<'+''.join(block_def[k][1::2])
        fmt_len = struct.calcsize(fmt)
        Block = collections.namedtuple('Block'+k[:3], block_def[k][::2])
        Blocks[k] = (fmt, fmt_len, Block)

    return Blocks


Blocks = make_block_classes()


gps_fmt = {}
# gps altitude message
gps_fmt['AL'] = '''
    type 2 str
    time_of_day 5 float
    altitude 6 float
    vertical_velocity 4 float
    source_flag 1 int
    age_flag 1 int
'''

# gps position velocity message
gps_fmt['PV'] = '''
    type 2 str
    time_of_day 5 float
    latitude 8 lat_float
    longitude 9 lon_float
    speed_mph 3 float
    heading 3 float
    source_flag 1 int
    age_flag 1 int
'''

# gps status message
gps_fmt['ST'] = '''
    type 2 str
    tracking_status_code 2 hex_int
    nibble1 1 hex_int
    nibble2 1 hex_int
    machine_id 2 hex_int
    nibble3 1 hex_int
    nibble4 1 hex_int
    reserved 2 str
'''

# gps time date message
gps_fmt['TM'] = '''
    type 2 str
    hours 2 int
    minutes 2 int
    seconds 5 seconds_float
    day 2 int
    month 2 int
    year 4 int
    gps_utc_time_offset 2 int
    current_fix_source 1 int
    number_usable_svs 2 int
    gps_utc_offset_flag 1 int
    reserved 5 str
'''


def latlon_float(s):
    return int(s) / 100000.


def seconds_float(s):
    return int(s) / 1000.


def hex_int(s):
    return int(s, 16)


convert_functions = {
    'int': int,
    'float': float,
    'lat_float': latlon_float,
    'lon_float': latlon_float,
    'seconds_float': seconds_float,
    'str': str,
    'hex_int': hex_int}


class GPSFormat_(object):
    def __init__(self, name, fmt):

        nn = 0
        names = []
        items = []
        for line in fmt.strip().splitlines():
            toks = line.split()
            n = int(toks[1])
            items.append((nn, nn+n, convert_functions[toks[2]]))
            names.append(toks[0])
            nn += n

        self.items = items
        self.Message = collections.namedtuple('GPSMessage'+k, names)

    def unpack(self, s):
        return self.Message(
            *(converter(s[begin:end])
              for (begin, end, converter) in self.items))


GPSFormat = {}
for k in gps_fmt.keys():
    GPSFormat[k] = GPSFormat_(k, gps_fmt[k])


def portnames():
    try:
        # needs serial >= v2.6
        from serial.tools.list_ports import comports
        names = sorted(x[0] for x in comports())

    except Exception:
        # may only work on some linuxes
        from glob import glob
        names = sorted(glob('/dev/ttyS*') + glob('/dev/ttyUSB*'))

    return names


def unpack_block(data):
    block_type = data[:4]

    if block_type not in Blocks:
        return None

    fmt, fmt_len, Block = Blocks[block_type]

    if len(data) < fmt_len:
        raise ReadError('block size too short')

    return Block(*struct.unpack(fmt, data[:fmt_len])), data[fmt_len:]


def unpack_values(ncomps, bytes_per_sample, data):
    if bytes_per_sample == 4:
        return num.frombuffer(data, dtype=num.dtype('<i4'))

    # 3-byte mode is broken:
    # elif bytes_per_sample == 3:
    #     b1 = num.frombuffer(data, dtype=num.dtype('<i1'))
    #     b4 = num.zeros(len(data)/4, dtype=num.dtype('<i4'))
    #     b4.view(dtype='<i2')[::2] = b1.view(dtype='<i2')
    #     b4.view(dtype='<i1')[2::4] = b1[i::3]
    #     return b4.astype(num.int32)

    else:
        raise ReadError('unimplemented bytes_per_sample setting')


class TimeEstimator(object):
    def __init__(self, nlookback):
        self._nlookback = nlookback
        self._queue = []
        self._t0 = None
        self._n = 0
        self._deltat = None

    def insert(self, deltat, nadd, t):

        if self._deltat is None or self._deltat != deltat:
            self.reset()
            self._deltat = deltat

        if self._t0 is None and t is not None:
            self._t0 = int(round(t/self._deltat))*self._deltat

        if t is None:
            self._n += nadd
            if self._t0:
                return self._t0 + (self._n-nadd)*self._deltat
            else:
                return None

        self._queue.append((self._n, t))
        self._n += nadd

        while len(self._queue) > self._nlookback:
            self._queue.pop(0)

        ns, ts = num.array(self._queue, dtype=float).T

        tpredicts = self._t0 + ns * self._deltat

        terrors = ts - tpredicts
        mterror = num.median(terrors)
        print(mterror / deltat, '+-', num.std(terrors) / deltat)

        if num.abs(mterror) > 0.75*deltat and \
                len(self._queue) == self._nlookback:

            t0 = self._t0 + mterror
            self._queue[:] = []
            self._t0 = int(round(t0/self._deltat))*self._deltat

        return self._t0 + (self._n-nadd)*self._deltat

    def reset(self):
        self._queue[:] = []
        self._n = 0
        self._t0 = None

    def __len__(self):
        return len(self._queue)


class GPSRecord(object):
    def __init__(self, al, pv, st, tm):
        self._al = al
        self._pv = pv
        self._st = st
        self._tm = tm

    @property
    def time(self):
        if not self._st.tracking_status_code == 0:
            raise NoGPSTime()

        if not self._tm.gps_utc_offset_flag:
            raise GPSTimeNotUTC()

        tm = self._tm
        return util.to_time_float(calendar.timegm((
            tm.year, tm.month, tm.day, tm.hours, tm.minutes, tm.seconds)))

    @property
    def latitude(self):
        return self._pv.latitude

    @property
    def longitude(self):
        return self._pv.longitude

    @property
    def altitude(self):
        return self._al.altitude

    def __str__(self):
        try:
            stime = util.time_to_str(self.time)
        except GPSError:
            stime = '?'
        return '''%s %s %s %s''' % (
            stime, self.latitude, self.longitude, self.altitude)


def stime_none_aware(t):
    if t is None:
        return '?'
    else:
        return util.time_to_str(t)


class Record(object):
    def __init__(self, mod, mde, dat, sum, values):
        self._mod = mod
        self._mde = mde
        self._dat = dat
        self._sum = sum
        self._values = values
        self._approx_system_time = None
        self._approx_gps_time = None
        self._gps = None

    def set_approx_times(
            self, approx_system_time, approx_gps_time, measured_system_time):

        self._approx_system_time = approx_system_time
        self._approx_gps_time = approx_gps_time
        self._measured_system_time = measured_system_time

    @property
    def time(self):
        if self._mod.reserved1 != 0:
            return float(self._mod.reserved1)

        return self._approx_system_time

    @property
    def traces(self):
        traces = []
        for i in range(self._mod.ncomps):
            tr = trace.Trace(
                '', 'ed', '', 'p%i' % i,
                deltat=float(self._mod.ncomps)/self._mod.sample_rate,
                tmin=self.time,
                ydata=self._values[i::3])

            traces.append(tr)

        traces.extend(self.traces_delays())

        return traces

    def traces_delays(self):
        traces = []
        for name, val in (
                ('gp', self.gps_time_or_none),
                ('sm', self._measured_system_time),
                ('sp', self._approx_system_time)):

            if val is not None:
                tr = trace.Trace(
                    '', 'ed', name, 'del',
                    deltat=1.0,
                    tmin=self.time,
                    ydata=num.array([val - self.time]))

                traces.append(tr)

        return traces

    def _gps_messages(self):
        for line in self._mde.gps_message.splitlines():
            if len(line) > 4 and line[0] == '>' and line.rstrip()[-1] == '<':
                yield GPSFormat[line[2:4]].unpack(line[2:])

    @property
    def gps(self):
        if self._mod.block_count != self._mod.gps_message_block_count:
            raise NoGPS()

        if self._gps is not None:
            return self._gps

        kwargs = {}
        for mess in self._gps_messages():
            kwargs[mess.type.lower()] = mess

        if sorted(kwargs.keys()) == ['al', 'pv', 'st', 'tm']:
            self._gps = GPSRecord(**kwargs)
            return self._gps
        else:
            raise NoGPS()

    @property
    def gps_time_or_none(self):
        try:
            return self.gps.time
        except GPSError:
            return None

    def __str__(self):
        return '\n'.join([
            '%s' % str(x) for x in (self._mod, self._mde)]) + '\n'

    def str_times(self):
        return '''--- Record ---
Time GPS:    %s (estimated)   %s (measured)
Time system: %s (estimated)   %s (measured)
''' % tuple([stime_none_aware(t) for t in (
            self._approx_gps_time,
            self.gps_time_or_none,
            self._approx_system_time,
            self._measured_system_time)])


class Reader(object):

    def __init__(self, port=0, timeout=2., baudrate=115200, lookback=30):
        if isinstance(port, int):
            self._port = portnames()[port]
        else:
            self._port = str(port)

        self._timeout = float(timeout)
        self._baudrate = int(baudrate)
        self._serial = None
        self._buffer = ''
        self._irecord = 0

        self._time_estimator_system = TimeEstimator(lookback)
        self._time_estimator_gps = TimeEstimator(lookback)

    def running(self):
        return self._serial is not None

    def assert_running(self):
        if not self.running():
            raise NotAquiring()

    def start(self):
        self.stop()

        import serial
        self._serial = serial.Serial(
            port=self._port,
            baudrate=self._baudrate,
            timeout=self._timeout)

        self._sync_on_mod()

    def _sync_on_mod(self):
        self._fill_buffer(MINBLOCKSIZE)

        while self._buffer[:4] != 'MOD\0':
            imark = self._buffer.find('MOD\0')
            if imark != -1:
                self._buffer = self._buffer[imark:]
            else:
                self._buffer = self._buffer[-4:]

            self._fill_buffer(MINBLOCKSIZE)

    def _fill_buffer(self, minlen):
        if len(self._buffer) >= minlen:
            return

        nread = minlen-len(self._buffer)
        try:
            data = self._serial.read(nread)
            hexdump(data)

        except Exception:
            raise ReadError()

        if len(data) != nread:
            self.stop()
            raise ReadTimeout()
        self._buffer += data

    def _read_block(self, need_block_type=None):
        self.assert_running()
        self._fill_buffer(8)
        block_type, block_len = struct.unpack('<4sI', self._buffer[:8])
        if need_block_type is not None and block_type != need_block_type:
            raise ReadUnexpected()

        block_len += 8
        self._fill_buffer(block_len)
        block_data = self._buffer
        self._buffer = ''
        return unpack_block(block_data)

    def read_record(self):
        self._irecord += 1
        mod, _ = self._read_block('MOD\0')
        measured_system_time = time.time() - 4.0
        mde, _ = self._read_block('MDE\0')
        dat, values_data = self._read_block('DAT\0')
        sum, _ = self._read_block('SUM\0')
        values = unpack_values(mod.ncomps, mod.bytes_per_sample, values_data)
        deltat = 1./mod.sample_rate * mod.ncomps
        r = Record(mod, mde, dat, sum, values)
        approx_system_time = self._time_estimator_system.insert(
            deltat, values.size//mod.ncomps, measured_system_time)

        try:
            gpstime = r.gps.time
        except GPSError:
            gpstime = None

        approx_gps_time = self._time_estimator_gps.insert(
            deltat, values.size//mod.ncomps, gpstime)

        r.set_approx_times(
            approx_system_time, approx_gps_time, measured_system_time)

        return r

    def stop(self):
        if not self.running():
            return

        self._serial.close()
        self._serial = None
        self._buffer = ''
        self._time_estimator_system.reset()
        self._time_estimator_gps.reset()


class EDLHamster(object):
    def __init__(self, *args, **kwargs):
        self.reader = Reader(*args, **kwargs)

    def acquisition_start(self):
        self.reader.start()

    def acquisition_stop(self):
        self.reader.stop()

    def process(self):
        rec = self.reader.read_record()
        self.got_record(rec)

    def got_record(self, rec):
        for tr in rec.traces:
            self.got_trace(tr)

    def got_trace(self, tr):
        logger.info('Got trace from EDL: %s' % tr)
