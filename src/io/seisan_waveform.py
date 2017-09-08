# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import division, absolute_import, print_function

import sys
import calendar
import numpy as num

from pyrocko import util, trace
from pyrocko.util import unpack_fixed
from .io_common import FileLoadError


class SeisanFileError(Exception):
    pass


def read_file_header(f, npad=4):
    header_infos = []

    nlines = 12
    iline = 0
    while iline < nlines:
        f.read(npad)
        d = f.read(80)
        d = str(d.decode('ascii'))
        f.read(npad)

        if iline == 0:
            net_name, nchannels, ear, doy, mon, day, hr, min, secs, tlen = \
                unpack_fixed(
                    'x1,a29,i3,i3,x1,i3,x1,i2,x1,i2,x1,i2,x1,i2,x1,f6,x1,f9',
                    d)

            year = 1900 + ear
            tmin = util.to_time_float(
                calendar.timegm((year, mon, day, hr, min, secs)))
            header_infos.append(
                (net_name, nchannels, util.time_to_str(tmin)))

            if nchannels > 30:
                nlines += (nchannels - 31)//3 + 1

        if iline >= 2:
            for j in range(3):
                s = d[j*26:(j+1)*26]
                if s.strip():
                    sta1, cha1, cha2, sta2, toffset, tlen = unpack_fixed(
                        'x1,a4,a2,x1,a1,a1,f7,x1,f8', s)

                    sta = sta1 + sta2
                    cha = cha1 + cha2
                    header_infos.append(
                        (sta, cha, toffset, tlen))

        iline += 1
    return header_infos


class EOF(Exception):
    pass


def read_channel_header(f, npad=4):
    x = f.read(npad)
    if len(x) == 0:
        raise EOF()

    d = f.read(1040)
    d = str(d.decode('ascii'))
    f.read(npad)

    sta, cha1, loc1, cha2, ear, loc2, doy, net1, mon, net2, day, hr, min, \
        tflag, secs, rate, nsamples, lat, lon, elevation, gain_flag, \
        sample_bytes, response_flag1, response_flag2 = unpack_fixed(
            'a5,a2,a1,a1,i3,a1,i3,a1,i2,a1,i2,x1,i2,x1,i2,a1,f6,x1,f7,i7,x1,'
            'f8?,x1,f9?,x1,f5?,a1,i1,a1,a1', d[:79])

    gain = 1
    if gain_flag:
        gain = unpack_fixed('f12', d[147:159])

    cha = cha1+cha2
    loc = loc1+loc2
    net = net1+net2
    tmin = util.to_time_float(
        calendar.timegm((1900+ear, mon, day, hr, min, secs)))
    deltat = 1./rate

    return (net, sta, loc, cha,
            tmin, tflag, deltat, nsamples, sample_bytes,
            lat, lon, elevation, gain)


def read_channel_data(
        f, endianness, sample_bytes, nsamples, gain, load_data=True, npad=4):

    if not load_data:
        f.seek(sample_bytes*nsamples + 2*npad, 1)
        return None

    else:
        f.read(npad)
        data = num.fromfile(
            f,
            dtype=num.dtype('%si%i' % (endianness, sample_bytes)),
            count=nsamples).astype('i%i' % sample_bytes)

        f.read(npad)
        data *= gain
        return data


def iload(filename, load_data=True, subformat='l4'):

    try:
        npad = 4
        if subformat is not None:
            try:
                endianness = {'l': '<', 'b': '>'}[subformat[0]]
                if len(subformat) > 1:
                    npad = int(subformat[1:])
            except Exception:
                raise SeisanFileError(
                    'Bad subformat specification: "%s"' % subformat)
        else:
            endianness = '<'

        with open(filename, 'rb') as f:
            try:
                read_file_header(f, npad=npad)

            except util.UnpackError as e:
                raise SeisanFileError(
                    'Error loading header from file %s: %s'
                    % (filename, str(e)))

            try:
                itrace = 0
                while True:
                    try:
                        (net, sta, loc, cha, tmin, tflag, deltat, nsamples,
                         sample_bytes, lat, lon, elevation, gain) \
                            = read_channel_header(f, npad=npad)

                        data = read_channel_data(
                            f, endianness, sample_bytes, nsamples,
                            gain, load_data,
                            npad=npad)

                        tmax = None
                        if data is None:
                            tmax = tmin + (nsamples-1)*deltat

                        t = trace.Trace(
                            net, sta, loc, cha, tmin=tmin, tmax=tmax,
                            deltat=deltat, ydata=data)

                        yield t

                    except util.UnpackError as e:
                        raise SeisanFileError(
                            'Error loading trace %i from file %s: %s' % (
                                itrace, filename, str(e)))

                    itrace += 1

            except EOF:
                pass

    except (OSError, SeisanFileError) as e:
        raise FileLoadError(e)


if __name__ == '__main__':
    fn = sys.argv[1]
    for tr in iload(fn):
        print(tr)
