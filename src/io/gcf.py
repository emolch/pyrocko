# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for the `Güralp GCF
<https://www.guralp.com/customer-support/common-questions/other-data-formats/data-formats/gcf>`_
format.
'''

import sys
import struct
import re
import numpy as num

from io import StringIO
from collections import namedtuple

from pyrocko import util, trace
from .io_common import FileLoadError


g_guralp_zero = None


def get_guralp_zero():
    global g_guralp_zero
    if g_guralp_zero is None:
        g_guralp_zero = util.str_to_time('1989-11-17 00:00:00')

    return g_guralp_zero


class GCFLoadError(FileLoadError):
    pass


class EOF(Exception):
    pass


Header = namedtuple(
    'Header',
    '''
    block_type
    system_id
    stream_id
    instrument_type
    time
    gain
    ttl
    sample_rate
    compression
    nrecords
    '''.split())


def read(f, n, eof_ok=False):
    data = f.read(n)
    if eof_ok and len(data) == 0:
        raise EOF()

    if len(data) != n:
        raise GCFLoadError('Unexpected end of file')

    return data


def read_header(f, endianness='>'):
    e = endianness
    data = read(f, 16, eof_ok=True)

    isystem_id, istream_id = struct.unpack(e+'II', data[:8])
    ex = isystem_id & 0x80000000
    if ex:
        ex2 = isystem_id & (1 << 30)
        if ex2:
            system_id = util.base36encode(isystem_id & (2**21 - 1))
        else:
            system_id = util.base36encode(isystem_id & (2**26 - 1))

        instrument_type = (isystem_id >> 26) & 0b1
        gain = [None, 1, 2, 4, 8, 16, 32, 64][(isystem_id >> 27) & 0b111]
    else:

        system_id = util.base36encode(isystem_id)
        instrument_type = None
        gain = None

    stream_id = util.base36encode(istream_id)

    i_day_second = struct.unpack(e+'I', data[8:12])[0]
    iday = i_day_second >> 17
    isecond = i_day_second & 0x1ffff
    time = (iday*24*60*60) + get_guralp_zero() + isecond

    ittl, israte, compression, nrecords = struct.unpack(e+'BBBB', data[12:])
    if nrecords > 250:
        raise FileLoadError('Header indicates too many records in block.')

    if israte == 0:
        if compression == 4 and stream_id[-2:] == '00':
            block_type = 'status_block'

        elif compression == 4 and stream_id[-2:] == '01':
            block_type = 'unified_status_block'

        elif compression == 4 and stream_id[-2:] == 'SM':
            block_type = 'strong_motion_block'

        elif stream_id[-2:] == 'CD':
            block_type = 'cd_status_block'

        elif compression == 4 and stream_id[-2:] == 'BP':
            block_type = 'byte_pipe_block'

        elif stream_id[-2:] == 'IB':
            block_type = 'information_block'

        else:
            raise FileLoadError('Unexpected block type found.')

        return Header(block_type, system_id, stream_id, instrument_type,
                      time, gain, ittl, 0.0, compression, nrecords)
    else:
        block_type = 'data_block'

        if not re.match(r'^([ZNEXC][0-9A-CG-S]|M[0-9A-F])$', stream_id[-2:]):
            raise FileLoadError('Unexpected data stream ID')

        sample_rate_tab = {
            157: (0.1, None),
            161: (0.125, None),
            162: (0.2, None),
            164: (0.25, None),
            167: (0.5, None),
            171: (400., 8),
            174: (500., 2),
            176: (1000., 4),
            179: (2000., 8),
            181: (4000., 16)}

        if israte in sample_rate_tab:
            sample_rate, tfod = sample_rate_tab[israte]
        else:
            sample_rate = float(israte)
            tfod = None

        if tfod is not None:
            toff = (compression >> 4) // tfod
            compression = compression & 0b1111
            time += toff

        if compression not in (1, 2, 4):
            raise GCFLoadError(
                'Unsupported compression code: %i' % compression)

        return Header(block_type, system_id, stream_id, instrument_type,
                      time, gain, ittl, sample_rate, compression, nrecords)


def read_data(f, h, endianness='>'):
    e = endianness
    data = read(f, 1024 - 16)
    first = struct.unpack(e+'i', data[0:4])[0]
    dtype = {1: e+'i4', 2: e+'i2', 4: e+'i1'}
    if h.compression not in dtype:
        raise GCFLoadError('Unsupported compression code: %i' % h.compression)

    nsamples = h.compression * h.nrecords
    difs = num.frombuffer(data[4:4+h.nrecords*4], dtype=dtype[h.compression],
                          count=nsamples)
    samples = difs.astype(num.int32)
    samples[0] += first
    samples = num.cumsum(samples, dtype=num.int32)
    last = struct.unpack(e+'i', data[4+h.nrecords*4:4+h.nrecords*4+4])[0]
    if last != samples[-1]:
        raise GCFLoadError('Checksum error occured')

    return samples


def read_status(f, h):
    data = read(f, 1024 - 16)
    return data[:h.nrecords*4]


def iload(filename, load_data=True):
    traces = {}

    with open(filename, 'rb') as f:
        try:
            while True:
                h = read_header(f)
                if h.block_type == 'data_block':
                    deltat = 1.0 / h.sample_rate
                    if load_data:
                        samples = read_data(f, h)
                        tmax = None
                    else:
                        f.seek(1024 - 16, 1)
                        samples = None
                        tmax = h.time + (
                            h.nrecords * h.compression - 1) * deltat

                    nslc = ('', h.system_id, '', h.stream_id)

                    if nslc in traces:
                        tr = traces[nslc]
                        if abs((tr.tmax + tr.deltat) - h.time) < deltat*0.0001:
                            if samples is not None:
                                tr.append(samples)
                            else:
                                tr.tmax = tmax

                        else:
                            del traces[nslc]
                            yield tr

                    if nslc not in traces:
                        traces[nslc] = trace.Trace(
                            *nslc,
                            tmin=h.time,
                            deltat=deltat,
                            ydata=samples,
                            tmax=tmax)

                else:
                    f.seek(1024 - 16, 1)

        except EOF:
            for tr in traces.values():
                yield tr


def detect(first512):
    # does not work properly, produces too many false positives
    # difficult to improve due to the very compact GCF header
    try:
        if len(first512) < 512:
            return False

        f = StringIO(first512)
        read_header(f)
        return True

    except Exception:
        return False


if __name__ == '__main__':
    util.setup_logging('warn')

    all_traces = []
    for fn in sys.argv[1:]:
        if detect(open(fn, 'rb').read(512)):
            print(fn)
            all_traces.extend(iload(fn))

    trace.snuffle(all_traces)
