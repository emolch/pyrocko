# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for GSE1 files.
'''

import sys
import numpy as num

from .io_common import FileLoadError
from pyrocko import util, trace


class GSE1LoadError(FileLoadError):
    pass


class EOF(Exception):
    pass


def read_xw01(f):
    line = f.readline()
    if not line[:4] == 'XW01':
        raise GSE1LoadError(
            '"XW01" marker not found, maybe this is not a GSE1 file')

    f.readline()


def read_wid1(f):
    line = f.readline()
    if not line.strip():
        raise EOF()

    (wid1, stmin, imilli, nsamples, sta, channel_id, channel_name, sample_rate,
        system_type, data_format, diff_flag) = util.unpack_fixed(
        'a4,x1,a17,x1,i3,x1,i8,x1,a6,x1,a8,x1,a2,x1,f11,x1,a6,x1,a4,x1,i1',
        line[:80])

    if wid1 != 'WID1':
        raise GSE1LoadError('"WID1" marker expected but not found.')

    tmin = util.str_to_time(stmin, format='%Y%j %H %M %S') + 0.001*imilli

    line = f.readline()
    (gain, units, calib_period, lat, lon, elevation, depth, beam_azimuth,
        beam_slowness, horizontal_orientation) = util.unpack_fixed(
        'f9,i1,f7,x1,f9,x1,f9,x1,f9,x1,f9,x1,f7,x1,f7,x1,f6', line[:80])

    return (tmin, nsamples, sta, channel_id, channel_name, sample_rate,
            system_type, data_format, diff_flag, gain, units, calib_period,
            lat, lon, elevation, depth, beam_azimuth, beam_slowness,
            horizontal_orientation)


def read_dat1_chk1(f, data_format, diff_flag, nsamples):
    dat1 = f.readline()[:4]
    if dat1 != 'DAT1':
        raise GSE1LoadError('"DAT1" marker expected but not found.')

    if data_format == 'INTV' and diff_flag == 0:
        samples = []
        while len(samples) < nsamples:
            samples.extend(map(float, f.readline().split()))

        data = num.array(samples[:nsamples], dtype=int)

    else:
        raise GSE1LoadError(
            'GSE1 data format %s with differencing=%i not supported.' %
            (data_format, diff_flag))

    line = f.readline()
    if not line.startswith('CHK1'):
        raise GSE1LoadError('"CHK1" marker expected but not found.')

    t = line.split()
    try:
        checksum = int(t[1])
    except Exception:
        raise GSE1LoadError('could not parse CHK1 section')

    f.readline()

    return data, checksum


def skip_dat1_chk1(f, data_format, diff_flag, nsamples):
    dat1 = f.readline()[:4]
    if dat1 != 'DAT1':
        raise GSE1LoadError('"DAT1" marker expected but not found.')

    while True:
        if f.readline().startswith('CHK1'):
            break

    f.readline()


def iload(filename, load_data=True):
    with open(filename, 'r') as f:
        read_xw01(f)
        try:
            while True:
                h = read_wid1(f)
                (tmin, nsamples, sta, chid, cha, sample_rate, _, data_format,
                    diff_flag, gain) = h[:10]

                deltat = 1.0/sample_rate
                if load_data:
                    ydata, checksum = read_dat1_chk1(
                        f, data_format, diff_flag, nsamples)
                    tmax = None
                else:
                    skip_dat1_chk1(f, data_format, diff_flag, nsamples)
                    ydata = None
                    tmax = tmin + (nsamples-1)*deltat

                yield trace.Trace(
                    '', sta, '', cha,
                    tmin=tmin,
                    tmax=tmax,
                    deltat=deltat,
                    ydata=ydata)

        except EOF:
            pass


def detect(first512):
    lines = first512.splitlines()
    if len(lines) >= 5 and \
            lines[0].startswith(b'XW01') and lines[2].startswith(b'WID1') and \
            lines[4].startswith(b'DAT1'):
        return True

    return False


if __name__ == '__main__':
    all_traces = []
    for fn in sys.argv[1:]:
        all_traces.extend(iload(fn))

    trace.snuffle(all_traces)
