# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
'''SAC IO library for Python'''
from __future__ import absolute_import

import struct
import logging
import math
import numpy as num

from calendar import timegm
from time import gmtime

from pyrocko import trace, util
from pyrocko.util import reuse
from .io_common import FileLoadError

logger = logging.getLogger('pyrocko.io.sac')


def fixdoublefloat(x):
    f = 10**math.floor(math.log10(x)) / 1000000.
    return round(x/f)*f


class SacError(Exception):
    pass


def nonetoempty(s):
    if s is None:
        return ''
    else:
        return s.strip()


class SacFile(object):
    nbytes_header = 632
    header_num_format = {'little': '<70f40i', 'big': '>70f40i'}

    header_keys = '''
delta depmin depmax scale odelta b e o a internal0 t0 t1 t2 t3 t4 t5 t6 t7 t8
t9 f resp0 resp1 resp2 resp3 resp4 resp5 resp6 resp7 resp8 resp9 stla stlo stel
stdp evla evlo evel evdp mag user0 user1 user2 user3 user4 user5 user6 user7
user8 user9 dist az baz gcarc internal1 internal2 depmen cmpaz cmpinc xminimum
xmaximum yminimum ymaximum unused0 unused1 unused2 unused3 unused4 unused5
unused6 nzyear nzjday nzhour nzmin nzsec nzmsec nvhdr norid nevid npts
internal3 nwfid nxsize nysize unused7 iftype idep iztype unused8 iinst istreg
ievreg ievtyp iqual isynth imagtyp imagsrc unused9 unused10 unused11 unused12
unused13 unused14 unused15 unused16 leven lpspol lovrok lcalda unused17 kstnm
kevnm khole ko ka kt0 kt1 kt2 kt3 kt4 kt5 kt6 kt7 kt8 kt9 kf kuser0 kuser1
kuser2 kcmpnm knetwk kdatrd kinst
'''.split()

    header_enum_symbols = '''
itime irlim iamph ixy iunkn idisp ivel iacc ib iday io ia it0 it1 it2 it3 it4
it5 it6 it7 it8 it9 iradnv itannv iradev itanev inorth ieast ihorza idown iup
illlbb iwwsn1 iwwsn2 ihglp isro inucl ipren ipostn iquake ipreq ipostq ichem
iother igood iglch idrop ilowsn irldta ivolts ixyz imb ims iml imw imd imx
ineic ipde iisc ireb iusgs ibrk icaltech illnl ievloc ijsop iuser iunknown iqb
iqb1 iqb2 iqbx iqmt ieq ieq1 ieq2 ime iex inu inc io_ il ir it iu
'''.split()

    enum_header_vars = 'iftype idep iztype imagtype imagsrc ievtyp iqual ' \
        'isynth'.split()

    header_num2name = dict(
        [(a+1, b) for (a, b) in enumerate(header_enum_symbols)])
    header_name2num = dict(
        [(b, a+1) for (a, b) in enumerate(header_enum_symbols)])
    header_types = 'f'*70 + 'i'*35 + 'l'*5 + 'k'*23
    undefined_value = {'f': -12345.0, 'i': -12345, 'l': None, 'k': '-12345'}
    ldefaults = {
        'leven': 1, 'lpspol': 0, 'lovrok': 1, 'lcalda': 1, 'unused17': 0}

    t_lookup = dict(zip(header_keys, header_types))

    u_lookup = dict()
    for k in header_keys:
        u_lookup[k] = undefined_value[t_lookup[k]]

    def ndatablocks(self):
        '''Get number of data blocks for this file's type.'''
        nblocks = {
            'itime': 1, 'irlim': 2, 'iamph': 2, 'ixy': 2, 'ixyz': 3
        }[SacFile.header_num2name[self.iftype]]

        if nblocks == 1 and not self.leven:
            nblocks = 2  # not sure about this...

        return nblocks

    def val_or_none(self, k, v):
        '''Replace SAC undef flags with None.'''
        if SacFile.u_lookup[k] == v:
            return None
        else:
            return v

    def get_ref_time(self):
        '''Get reference time as standard Unix timestamp.'''

        if None in (self.nzyear, self.nzjday, self.nzhour, self.nzmin,
                    self.nzsec, self.nzmsec):
            raise SacError('Not all header values for reference time are set.')

        return util.to_time_float(timegm(
            (self.nzyear, 1, self.nzjday,
             self.nzhour, self.nzmin, self.nzsec))) + self.nzmsec/1000.

    def set_ref_time(self, timestamp):
        '''
        Set all header values defining reference time based on standard Unix
        timestamp.
        '''

        secs = math.floor(timestamp)
        msec = int(round((timestamp-secs)*1000.))
        if msec == 1000:
            secs += 1
            msec = 0

        t = gmtime(secs)
        self.nzyear, self.nzjday, self.nzhour, self.nzmin, self.nzsec = \
            t[0], t[7], t[3], t[4], t[5]
        self.nzmsec = msec

    def val_for_file(self, k, v):
        '''
        Convert attribute value to the form required when writing it to the
        SAC file.
        '''

        t = SacFile.t_lookup[k]
        if v is None:
            if t == 'l':
                return SacFile.ldefaults[k]
            v = SacFile.u_lookup[k]
        if t == 'f':
            return float(v)
        elif t == 'i':
            return int(v)
        elif t == 'l':
            if v:
                return 1
            return 0
        elif t == 'k':
            ln = 8
            if k == 'kevnm':
                ln = 16   # only this header val has different length
            return v.ljust(ln)[:ln]

    def __init__(self, *args, **kwargs):
        if 'from_trace' in kwargs:
            self.clear()
            trace = kwargs['from_trace']
            if trace.meta:
                for (k, v) in trace.meta.items():
                    if k in SacFile.header_keys:
                        setattr(self, k, v)

            self.knetwk = trace.network
            self.kstnm = trace.station
            self.khole = trace.location
            self.kcmpnm = trace.channel
            self.set_ref_time(trace.tmin)
            self.delta = trace.deltat
            self.data = [trace.ydata.copy()]
            self.npts = trace.ydata.size
            self.b = 0.0
            self.e = self.b + (self.npts-1)*self.delta

        elif args:
            self.read(*args, **kwargs)
        else:
            self.clear()

    def clear(self):
        '''Empty file record.'''

        for k in SacFile.header_keys:
            self.__dict__[k] = None

        # set the required attributes
        self.nvhdr = 6
        self.iftype = SacFile.header_name2num['itime']
        self.leven = True
        self.delta = 1.0
        self.npts = 0
        self.b = 0.0
        self.e = 0.0
        self.data = [num.arange(0, dtype=num.float32)]

    def check(self):
        '''Check the required header variables to have reasonable values.'''
        if self.iftype not in [SacFile.header_name2num[x] for x in
                               ('itime', 'irlim', 'iamph', 'ixy', 'ixyz')]:
            raise SacError('Unknown SAC file type: %i.' % self.iftype)
        if self.nvhdr < 1 or 20 < self.nvhdr:
            raise SacError('Unreasonable SAC header version number found.')
        if self.npts < 0:
            raise SacError(
                'Negative number of samples specified in NPTS header.')
        if self.leven not in (0, 1, -12345):
            raise SacError('Header value LEVEN must be either 0 or 1.')
        if self.leven and self.delta <= 0.0:
            raise SacError(
                'Header value DELTA should be positive for evenly spaced '
                'samples')
        if self.e is not None and self.b > self.e:
            raise SacError(
                'Beginning value of independent variable greater than its '
                'ending value.')
        if self.nvhdr != 6:
            logging.warn(
                'This module has only been tested with SAC header version 6.'
                'This file has header version %i. '
                'It might still work though...' % self.nvhdr)

    def read(self, filename, load_data=True, byte_sex='try'):
        '''
        Read SAC file.

        filename -- Name of SAC file.
        load_data -- If True, the data is read, otherwise only read headers.
        byte_sex -- Endianness: 'try', 'little' or 'big'
        '''

        nbh = SacFile.nbytes_header

        # read in all data
        with open(filename, 'rb') as f:
            if load_data:
                filedata = f.read()
            else:
                filedata = f.read(nbh)

        if len(filedata) < nbh:
            raise SacError('File too short to be a SAC file: %s' % filename)

        # possibly try out different endiannesses
        if byte_sex == 'try':
            sexes = ('little', 'big')
        else:
            sexes = (byte_sex,)

        for isex, sex in enumerate(sexes):
            format = SacFile.header_num_format[sex]
            nbn = struct.calcsize(format)
            hv = list(struct.unpack(format, filedata[:nbn]))

            strings = str(filedata[nbn:nbh].decode('ascii'))
            hv.append(strings[:8].rstrip())
            hv.append(strings[8:24].rstrip())
            for i in range(len(strings[24:])//8):
                hv.append(strings[24+i*8:24+(i+1)*8].rstrip())

            self.header_vals = hv
            for k, v in zip(SacFile.header_keys, self.header_vals):
                vn = self.val_or_none(k, v)
                if isinstance(vn, str):
                    ipos = vn.find('\x00')
                    if ipos != -1:
                        vn = vn[:ipos]

                    self.__dict__[k] = vn.rstrip()
                else:
                    self.__dict__[k] = vn

            if self.leven == -12345:
                self.leven = True

            self.data = []
            try:
                self.check()
                break
            except SacError as e:
                if isex == len(sexes)-1:
                    raise e

        self.delta = fixdoublefloat(self.delta)

        if byte_sex == 'try':
            logger.debug(
                'This seems to be a %s endian SAC file: %s' % (sex, filename))

        # possibly get data
        if load_data:
            nblocks = self.ndatablocks()
            nbb = self.npts*4  # word length is always 4 bytes in sac files
            for iblock in range(nblocks):
                if len(filedata) < nbh+(iblock+1)*nbb:
                    raise SacError('File is incomplete.')

                if sex == 'big':
                    dtype = num.dtype('>f4')
                else:
                    dtype = num.dtype('<f4')

                self.data.append(num.array(num.fromstring(
                    filedata[nbh+iblock*nbb:nbh+(iblock+1)*nbb],
                    dtype=dtype),
                    dtype=num.float))

            if len(filedata) > nbh+nblocks*nbb:
                logger.warning(
                    'Unused data (%i bytes) at end of SAC file: %s (npts=%i)'
                    % (len(filedata) - nbh+nblocks*nbb, filename, self.npts))

    def write(self, filename, byte_sex='little'):
        '''Write SAC file.'''

        self.check()

        # create header data
        format = SacFile.header_num_format[byte_sex]
        numerical_values = []
        string_values = []
        for k in SacFile.header_keys:
            v = self.__dict__[k]
            vv = self.val_for_file(k, v)
            if SacFile.t_lookup[k] == 'k':
                string_values.append(vv)
            else:
                numerical_values.append(vv)

        header_data = struct.pack(format, *numerical_values)
        header_data += bytes(''.join(string_values).encode('ascii'))

        # check that enough data is available
        nblocks = self.ndatablocks()
        if len(self.data) != nblocks:
            raise SacError(
                'Need %i data blocks for file type %s.'
                % (nblocks, SacFile.header_num2name[self.iftype]))

        for fdata in self.data:
            if len(fdata) != self.npts:
                raise SacError(
                    'Data length (%i) does not match NPTS header value (%i)'
                    % (len(fdata), self.npts))

        # dump data to file
        with open(filename, 'wb') as f:
            f.write(header_data)
            for fdata in self.data:
                f.write(fdata.astype(num.float32).tostring())

    def __str__(self):
        str = ''
        for k in SacFile.header_keys:
            v = self.__dict__[k]
            if v is not None:
                if k in SacFile.enum_header_vars:
                    if v in SacFile.header_num2name:
                        v = SacFile.header_num2name[v]
                str += '%s: %s\n' % (k, v)

        return str

    def to_trace(self):

        assert self.iftype == SacFile.header_name2num['itime']
        assert self.leven

        tmin = self.get_ref_time() + self.b
        tmax = tmin + self.delta*(self.npts-1)

        data = None
        if self.data:
            data = self.data[0]

        meta = {}
        exclude = ('b', 'e', 'knetwk', 'kstnm', 'khole', 'kcmpnm', 'delta',
                   'nzyear', 'nzjday', 'nzhour', 'nzmin', 'nzsec', 'nzmsec')

        for k in SacFile.header_keys:
            if k in exclude:
                continue
            v = self.__dict__[k]
            if v is not None:
                meta[reuse(k)] = v

        return trace.Trace(
            nonetoempty(self.knetwk)[:2],
            nonetoempty(self.kstnm)[:5],
            nonetoempty(self.khole)[:2],
            nonetoempty(self.kcmpnm)[:3],
            tmin,
            tmax,
            self.delta,
            data,
            meta=meta)


def iload(filename, load_data=True):

    try:
        sacf = SacFile(filename, load_data=load_data)
        tr = sacf.to_trace()
        yield tr

    except (OSError, SacError) as e:
        raise FileLoadError(e)


def detect(first512):

    if len(first512) < 512:  # SAC header is 632 bytes long
        return False

    for sex in 'little', 'big':
        format = SacFile.header_num_format[sex]
        nbn = struct.calcsize(format)

        hv = list(struct.unpack(format, first512[:nbn]))
        iftype, nvhdr, npts, leven, delta, e, b = [
            hv[i] for i in (85, 76, 79, 105, 0, 6, 5)]

        if iftype not in [SacFile.header_name2num[x] for x in (
                'itime', 'irlim', 'iamph', 'ixy', 'ixyz')]:
            continue
        if nvhdr < 1 or 20 < nvhdr:
            continue
        if npts < 0:
            continue
        if leven not in (0, 1, -12345):
            continue
        if leven and delta <= 0.0:
            continue
        if e != -12345.0 and b > e:
            continue

        return True

    return False
