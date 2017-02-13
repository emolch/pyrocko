
import errno
import time
import os
import struct
import math
import shutil
import fcntl
import copy
import logging
import re

import numpy as num
from scipy import signal

from pyrocko import util, spit
from pyrocko.gf import meta
from pyrocko.gf import store_ext

logger = logging.getLogger('pyrocko.gf.store')

# gf store endianness
E = '<'

gf_dtype = num.dtype(num.float32)
gf_dtype_store = num.dtype(E + 'f4')

gf_dtype_nbytes_per_sample = 4

gf_store_header_dtype = [
    ('nrecords', E + 'u8'),
    ('deltat', E + 'f4'),
]

gf_store_header_fmt = E + 'Qf'
gf_store_header_fmt_size = struct.calcsize(gf_store_header_fmt)

gf_record_dtype = num.dtype([
    ('data_offset', E + 'u8'),
    ('itmin', E + 'i4'),
    ('nsamples', E + 'u4'),
    ('begin_value', E + 'f4'),
    ('end_value', E + 'f4'),
])


def valid_string_id(s):
    return re.match(meta.StringID.pattern, s)


def check_string_id(s):
    if not valid_string_id(s):
        raise ValueError('invalid name %s' % s)

# - data_offset
#
# Data file offset of first sample in bytes (the seek value).
# Special values:
#
#  0x00 - missing trace
#  0x01 - zero trace (GF trace is physically zero)
#  0x02 - short trace of 1 or 2 samples (no need for data allocation)
#
# - itmin
#
# Time of first sample of the trace as a multiple of the sampling interval. All
# GF samples must be evaluated at multiples of the sampling interval with
# respect to a global reference time zero. Must be set also for zero traces.
#
# - nsamples
#
# Number of samples in the GF trace. Should be set to zero for zero traces.
#
# - begin_value, end_value
#
# Values of first and last sample. These values are included in data[]
# redunantly.


class NotMultipleOfSamplingInterval(Exception):
    pass


sampling_check_eps = 1e-5


class GFTrace(object):

    '''
    Green's Function trace class for handling traces from the GF Store.
    '''

    @classmethod
    def from_trace(cls, tr):
        return cls(data=tr.ydata.copy(), tmin=tr.tmin, deltat=tr.deltat)

    def __init__(self, data=None, itmin=None, deltat=1.0,
                 is_zero=False, begin_value=None, end_value=None, tmin=None):

        assert sum((x is None) for x in (tmin, itmin)) == 1, \
            'GFTrace: either tmin or itmin must be given'

        if tmin is not None:
            itmin = int(round(tmin / deltat))
            if abs(itmin*deltat - tmin) > sampling_check_eps*deltat:
                raise NotMultipleOfSamplingInterval(
                    'GFTrace: tmin (%g) is not a multiple of sampling '
                    'interval (%g)' % (tmin, deltat))

        if data is not None:
            data = num.asarray(data, dtype=gf_dtype)
        else:
            data = num.array([], dtype=gf_dtype)

        self.data = data
        self.itmin = itmin
        self.deltat = deltat
        self.is_zero = is_zero
        self.n_records_stacked = 0.
        self.t_stack = 0.
        self.t_optimize = 0.

        if data is not None and data.size > 0:
            if begin_value is None:
                begin_value = data[0]
            if end_value is None:
                end_value = data[-1]

        self.begin_value = begin_value
        self.end_value = end_value

    @property
    def t(self):
        '''
        Time vector of the GF trace.

        :returns: Time vector
        :rtype: :py:class:`numpy.Array`
        '''
        return num.linspace(
            self.itmin*self.deltat,
            (self.itmin+self.data.size-1)*self.deltat, self.data.size)

    def __str__(self, itmin=0):

        if self.is_zero:
            return 'ZERO'

        s = []
        for i in range(itmin, self.itmin + self.data.size):
            if i >= self.itmin and i < self.itmin + self.data.size:
                s.append('%7.4g' % self.data[i-self.itmin])
            else:
                s.append(' '*7)

        return '|'.join(s)


class GFValue(object):

    def __init__(self, value):
        self.value = value
        self.n_records_stacked = 0.
        self.t_stack = 0.
        self.t_optimize = 0.


def make_same_span(tracesdict):

    traces = tracesdict.values()

    nonzero = [tr for tr in traces if not tr.is_zero]
    if not nonzero:
        return dict((k, Zero) for k in tracesdict.keys())

    deltat = nonzero[0].deltat

    itmin = min(tr.itmin for tr in nonzero)
    itmax = max(tr.itmin+tr.data.size for tr in nonzero) - 1

    out = {}
    for k, tr in tracesdict.iteritems():
        n = itmax - itmin + 1
        if tr.itmin != itmin or tr.data.size != n:
            data = num.zeros(n, dtype=gf_dtype)
            if not tr.is_zero:
                lo = tr.itmin-itmin
                hi = lo + tr.data.size
                data[:lo] = tr.data[0]
                data[lo:hi] = tr.data
                data[hi:] = tr.data[-1]

            tr = GFTrace(data, itmin, deltat)

        out[k] = tr

    return out


Zero = GFTrace(is_zero=True, itmin=0)


class StoreError(Exception):
    pass


class CannotCreate(StoreError):
    pass


class CannotOpen(StoreError):
    pass


class DuplicateInsert(StoreError):
    pass


class ShortRead(StoreError):
    def __str__(self):
        return 'unexpected end of data (truncated traces file?)'


class NotAllowedToInterpolate(StoreError):
    def __str__(self):
        return 'not allowed to interpolate'


class NoSuchExtra(StoreError):
    def __init__(self, s):
        StoreError.__init__(self)
        self.value = s

    def __str__(self):
        return 'extra information for key "%s" not found.' % self.value


class NoSuchPhase(StoreError):
    def __init__(self, s):
        StoreError.__init__(self)
        self.value = s

    def __str__(self):
        return 'phase for key "%s" not found. ' \
               'Running "fomosto ttt" may be needed.' % self.value


def remove_if_exists(fn, force=False):
    if os.path.exists(fn):
        if force:
            os.remove(fn)
        else:
            raise CannotCreate('file %s already exists' % fn)


class BaseStore:

    @staticmethod
    def index_fn_(store_dir):
        return os.path.join(store_dir, 'index')

    @staticmethod
    def data_fn_(store_dir):
        return os.path.join(store_dir, 'traces')

    @staticmethod
    def create(store_dir, deltat, nrecords, force=False):

        try:
            util.ensuredir(store_dir)
        except:
            raise CannotCreate('cannot create directory %s' % store_dir)

        index_fn = BaseStore.index_fn_(store_dir)
        data_fn = BaseStore.data_fn_(store_dir)

        for fn in (index_fn, data_fn):
            remove_if_exists(fn, force)

        with open(index_fn, 'wb') as f:
            f.write(struct.pack(gf_store_header_fmt, nrecords, deltat))
            records = num.zeros(nrecords, dtype=gf_record_dtype)
            records.tofile(f)

        with open(data_fn, 'wb') as f:
            f.write('\0' * 32)

    def __init__(self, store_dir, mode='r', use_memmap=True):
        assert mode in 'rw'
        self.store_dir = store_dir
        self.mode = mode
        self._use_memmap = use_memmap
        self._nrecords = None
        self._deltat = None
        self._f_index = None
        self._f_data = None
        self._end_values = None

    def open(self):
        index_fn = self.index_fn()
        data_fn = self.data_fn()

        if self.mode == 'r':
            fmode = 'rb'
        elif self.mode == 'w':
            fmode = 'r+b'
        else:
            assert False, 'invalid mode: %s' % self.mode

        try:
            self._f_index = open(index_fn, fmode)
            self._f_data = open(data_fn, fmode)
        except:
            self.mode = ''
            raise CannotOpen('cannot open gf store: %s' % self.store_dir)

        if self.mode == 'r':
            try:
                self.cstore = store_ext.store_init(
                    self._f_index.fileno(), self._f_data.fileno())
            except store_ext.StoreExtError, e:
                raise StoreError(str(e))

        while True:
            try:
                dataheader = self._f_index.read(gf_store_header_fmt_size)
                break

            except IOError, e:
                # occasionally got this one on an NFS volume
                if e.errno == errno.EBUSY:
                    time.sleep(0.01)
                else:
                    raise

        nrecords, deltat = struct.unpack(gf_store_header_fmt, dataheader)
        self._nrecords = nrecords
        self._deltat = deltat

        self._load_index()

    def __del__(self):
        if self.mode != '':
            self.close()

    def lock(self):
        if not self._f_index:
            self.open()

        while True:
            try:
                fcntl.lockf(self._f_index, fcntl.LOCK_EX)
                break

            except IOError, e:
                if e.errno == errno.ENOLCK:
                    time.sleep(0.01)
                else:
                    raise

    def unlock(self):
        self._f_data.flush()
        fcntl.lockf(self._f_index, fcntl.LOCK_UN)

    def put(self, irecord, trace):
        self._put(irecord, trace)

    def get_record(self, irecord):
        return self._get_record(irecord)

    def get_span(self, irecord, decimate=1):
        return self._get_span(irecord, decimate=decimate)

    def get(self, irecord, itmin=None, nsamples=None, decimate=1,
            implementation='c'):
        return self._get(irecord, itmin, nsamples, decimate, implementation)

    def sum(self, irecords, delays, weights, itmin=None,
            nsamples=None, decimate=1, implementation='c',
            optimization='enable'):
        return self._sum(irecords, delays, weights, itmin, nsamples, decimate,
                         implementation, optimization)

    def sum_statics(self, irecords, weights, implementation=None,
                    optimization='enable'):
        return self._sum_statics(irecords, weights, implementation,
                                 optimization)

    def irecord_format(self):
        return util.zfmt(self._nrecords)

    def str_irecord(self, irecord):
        return self.irecord_format() % irecord

    def close(self):

        if self.mode == 'w':
            if not self._f_index:
                self.open()
            self._save_index()

        if self._f_data:
            self._f_data.close()
            self._f_data = None

        if self._f_index:
            self._f_index.close()
            self._f_index = None

        self.mode = ''

    def _get_record(self, irecord):
        if not self._f_index:
            self.open()

        return self._records[irecord]

    def _get(self, irecord, itmin, nsamples, decimate, implementation):
        '''Retrieve complete GF trace from storage.'''

        if not self._f_index:
            self.open()

        if not self.mode == 'r':
            raise StoreError('store not open in read mode')

        if implementation == 'c' and decimate == 1:

            if nsamples is None:
                nsamples = -1

            if itmin is None:
                itmin = 0

            try:
                return GFTrace(*store_ext.store_get(
                    self.cstore, int(irecord), int(itmin), int(nsamples)))
            except store_ext.StoreExtError, e:
                raise StoreError(str(e))

        else:
            return self._get_impl_reference(irecord, itmin, nsamples, decimate)

    def _get_impl_reference(self, irecord, itmin, nsamples, decimate):

        if not (0 <= irecord < self._nrecords):
            raise StoreError('invalid record number requested '
                             '(irecord = %i, nrecords = %i)' %
                             (irecord, self._nrecords))

        ipos, itmin_data, nsamples_data, begin_value, end_value = \
            self._records[irecord]

        if None in (itmin, nsamples):
            itmin = itmin_data
            itmax = itmin_data + nsamples_data - 1
            nsamples = nsamples_data
        else:
            itmin = itmin * decimate
            nsamples = nsamples * decimate
            itmax = itmin + nsamples - decimate

        if ipos == 0:
            return None

        elif ipos == 1:
            return GFTrace(is_zero=True, itmin=itmin)

        if decimate == 1:
            ilo = max(itmin, itmin_data) - itmin_data
            ihi = min(itmin+nsamples, itmin_data+nsamples_data) - itmin_data
            data = self._get_data(ipos, begin_value, end_value, ilo, ihi)

            return GFTrace(data, itmin=itmin_data+ilo, deltat=self._deltat,
                           begin_value=begin_value, end_value=end_value)

        else:
            itmax_data = itmin_data + nsamples_data - 1

            # put begin and end to multiples of new sampling rate
            itmin_ext = (max(itmin, itmin_data)/decimate) * decimate
            itmax_ext = -((-min(itmax, itmax_data))/decimate) * decimate
            nsamples_ext = itmax_ext - itmin_ext + 1

            # add some padding for the aa filter
            order = 30
            itmin_ext_pad = itmin_ext - order/2
            itmax_ext_pad = itmax_ext + order/2
            nsamples_ext_pad = itmax_ext_pad - itmin_ext_pad + 1

            itmin_overlap = max(itmin_data, itmin_ext_pad)
            itmax_overlap = min(itmax_data, itmax_ext_pad)

            ilo = itmin_overlap - itmin_ext_pad
            ihi = max(ilo, itmax_overlap - itmin_ext_pad + 1)
            ilo_data = itmin_overlap - itmin_data
            ihi_data = max(ilo_data, itmax_overlap - itmin_data + 1)

            data_ext_pad = num.empty(nsamples_ext_pad, dtype=gf_dtype)
            data_ext_pad[ilo:ihi] = self._get_data(
                ipos, begin_value, end_value, ilo_data, ihi_data)

            data_ext_pad[:ilo] = begin_value
            data_ext_pad[ihi:] = end_value

            b = signal.firwin(order + 1, 1. / decimate, window='hamming')
            a = 1.
            data_filt_pad = signal.lfilter(b, a, data_ext_pad)
            data_deci = data_filt_pad[order:order+nsamples_ext:decimate]
            if data_deci.size >= 1:
                if itmin_ext <= itmin_data:
                    data_deci[0] = begin_value

                if itmax_ext >= itmax_data:
                    data_deci[-1] = end_value

            return GFTrace(data_deci, itmin_ext/decimate,
                           self._deltat*decimate,
                           begin_value=begin_value, end_value=end_value)

    def _get_span(self, irecord, decimate=1):
        '''
        Get temporal extent of GF trace at given index.
        '''

        if not self._f_index:
            self.open()

        assert 0 <= irecord < self._nrecords, \
            'irecord = %i, nrecords = %i' % (irecord, self._nrecords)

        (_, itmin, nsamples, _, _) = self._records[irecord]

        itmax = itmin + nsamples - 1

        if decimate == 1:
            return itmin, itmax
        else:
            return itmin/decimate, -((-itmax)/decimate)

    def _put(self, irecord, trace):
        '''
        Save GF trace to storage.
        '''

        if not self._f_index:
            self.open()

        assert self.mode == 'w'
        assert trace.is_zero or \
            abs(trace.deltat - self._deltat) < 1e-7 * self._deltat
        assert 0 <= irecord < self._nrecords, \
            'irecord = %i, nrecords = %i' % (irecord, self._nrecords)

        if self._records[irecord][0] != 0:
            raise DuplicateInsert('record %i already in store' % irecord)

        if trace.is_zero or num.all(trace.data == 0.0):
            self._records[irecord] = (1, trace.itmin, 0, 0., 0.)
            return

        ndata = trace.data.size

        if ndata > 2:
            self._f_data.seek(0, 2)
            ipos = self._f_data.tell()
            trace.data.astype(gf_dtype_store).tofile(self._f_data)
        else:
            ipos = 2

        self._records[irecord] = (ipos, trace.itmin, ndata,
                                  trace.data[0], trace.data[-1])

    def _sum_impl_alternative(self, irecords, delays, weights, itmin, nsamples,
                              decimate):

        '''
        Sum delayed and weighted GF traces.
        '''

        if not self._f_index:
            self.open()

        assert self.mode == 'r'

        deltat = self._deltat * decimate

        if len(irecords) == 0:
            return Zero

        assert len(irecords) == len(delays)
        assert len(irecords) == len(weights)

        if None in (itmin, nsamples):
            itmin_delayed, itmax_delayed = [], []
            for irecord, delay in zip(irecords, delays):
                itmin, itmax = self._get_span(irecord, decimate=decimate)
                itmin_delayed.append(itmin + delay/deltat)
                itmax_delayed.append(itmax + delay/deltat)

            itmin = int(math.floor(min(itmin_delayed)))
            nsamples = int(math.ceil(max(itmax_delayed))) - itmin + 1

        out = num.zeros(nsamples, dtype=gf_dtype)
        if nsamples == 0:
            return GFTrace(out, itmin, deltat)

        for ii in xrange(len(irecords)):
            irecord = irecords[ii]
            delay = delays[ii]
            weight = weights[ii]

            if weight == 0.0:
                continue

            idelay_floor = int(math.floor(delay/deltat))
            idelay_ceil = int(math.ceil(delay/deltat))

            gf_trace = self._get(
                irecord,
                itmin - idelay_ceil,
                nsamples + idelay_ceil - idelay_floor,
                decimate,
                'reference')

            assert gf_trace.itmin >= itmin - idelay_ceil
            assert gf_trace.data.size <= nsamples + idelay_ceil - idelay_floor

            if gf_trace.is_zero:
                continue

            ilo = gf_trace.itmin - itmin + idelay_floor
            ihi = ilo + gf_trace.data.size + (idelay_ceil-idelay_floor)

            data = gf_trace.data

            if idelay_floor == idelay_ceil:
                out[ilo:ihi] += data * weight
            else:
                if data.size:
                    k = 1
                    if ihi <= nsamples:
                        out[ihi-1] += gf_trace.end_value * \
                            ((idelay_ceil-delay/deltat) * weight)
                        k = 0

                    out[ilo+1:ihi-k] += data[:data.size-k] * \
                        ((delay/deltat-idelay_floor) * weight)
                    k = 1
                    if ilo >= 0:
                        out[ilo] += gf_trace.begin_value * \
                            ((delay/deltat-idelay_floor) * weight)
                        k = 0

                    out[ilo+k:ihi-1] += data[k:] * \
                        ((idelay_ceil-delay/deltat) * weight)

            if ilo > 0 and gf_trace.begin_value != 0.0:
                out[:ilo] += gf_trace.begin_value * weight

            if ihi < nsamples and gf_trace.end_value != 0.0:
                out[ihi:] += gf_trace.end_value * weight

        return GFTrace(out, itmin, deltat)

    def _sum_impl_reference(self, irecords, delays, weights, itmin, nsamples,
                            decimate):

        if not self._f_index:
            self.open()

        if len(irecords) == 0:
            return Zero

        deltat = self._deltat * decimate

        datas = []
        itmins = []
        for i, delay, weight in zip(irecords, delays, weights):
            tr = self._get(i, None, None, decimate, 'reference')

            idelay_floor = int(math.floor(delay/deltat))
            idelay_ceil = int(math.ceil(delay/deltat))

            if idelay_floor == idelay_ceil:
                itmins.append(tr.itmin + idelay_floor)
                datas.append(tr.data.copy()*weight)
            else:
                itmins.append(tr.itmin + idelay_floor)
                datas.append(tr.data.copy()*weight*(idelay_ceil-delay/deltat))
                itmins.append(tr.itmin + idelay_ceil)
                datas.append(tr.data.copy()*weight*(delay/deltat-idelay_floor))

        itmin_all = min(itmins)

        itmax_all = max(itmin_ + data.size for (itmin_, data) in
                        zip(itmins, datas))

        if itmin is not None:
            itmin_all = min(itmin_all, itmin)
        if nsamples is not None:
            itmax_all = max(itmax_all, itmin+nsamples)

        nsamples_all = itmax_all - itmin_all

        arr = num.zeros((len(datas), nsamples_all), dtype=gf_dtype)
        for i, itmin_, data in zip(num.arange(len(datas)), itmins, datas):
            if data.size > 0:
                ilo = itmin_-itmin_all
                ihi = ilo + data.size
                arr[i, :ilo] = data[0]
                arr[i, ilo:ihi] = data
                arr[i, ihi:] = data[-1]

        sum_arr = arr.sum(axis=0)

        if itmin is not None and nsamples is not None:
            ilo = itmin-itmin_all
            ihi = ilo + nsamples
            sum_arr = sum_arr[ilo:ihi]

        else:
            itmin = itmin_all

        return GFTrace(sum_arr, itmin, deltat)

    def _optimize(self, irecords, delays, weights):
        if num.unique(irecords).size == irecords.size:
            return irecords, delays, weights

        deltat = self._deltat

        delays = delays / deltat
        irecords2 = num.repeat(irecords, 2)
        delays2 = num.empty(irecords2.size, dtype=num.float)
        delays2[0::2] = num.floor(delays)
        delays2[1::2] = num.ceil(delays)
        weights2 = num.repeat(weights, 2)
        weights2[0::2] *= 1.0 - (delays - delays2[0::2])
        weights2[1::2] *= (1.0 - (delays2[1::2] - delays)) * \
                          (delays2[1::2] - delays2[0::2])

        delays2 *= deltat

        iorder = num.lexsort((delays2, irecords2))

        irecords2 = irecords2[iorder]
        delays2 = delays2[iorder]
        weights2 = weights2[iorder]

        ui = num.empty(irecords2.size, dtype=num.bool)
        ui[1:] = num.logical_or(num.diff(irecords2) != 0,
                                num.diff(delays2) != 0.)

        ui[0] = 0
        ind2 = num.cumsum(ui)
        ui[0] = 1
        ind1 = num.where(ui)[0]

        irecords3 = irecords2[ind1]
        delays3 = delays2[ind1]
        weights3 = num.bincount(ind2, weights2)

        return irecords3, delays3, weights3

    def _optimize_statics(self, irecords, weights):
        if num.unique(irecords).size == irecords.size:
            return irecords, weights

        iorder = num.argsort(irecords)

        irecords2 = irecords[iorder]
        weights2 = weights[iorder]

        ui = num.empty(irecords2.size, dtype=num.bool)
        ui[1:] = num.diff(irecords2) != 0

        ui[0] = 0
        ind2 = num.cumsum(ui)
        ui[0] = 1
        ind1 = num.where(ui)[0]

        irecords3 = irecords2[ind1]
        weights3 = num.bincount(ind2, weights2)

        return irecords3, weights3

    def _sum(self, irecords, delays, weights, itmin, nsamples, decimate,
             implementation, optimization):

        if not self._f_index:
            self.open()

        t0 = time.time()
        if optimization == 'enable':
            irecords, delays, weights = self._optimize(
                irecords, delays, weights)
        else:
            assert optimization == 'disable'

        t1 = time.time()

        if implementation == 'c' and decimate == 1:
            if delays.size != 0:
                itoffset = int(num.floor(num.min(delays)/self._deltat))
            else:
                itoffset = 0

            if nsamples is None:
                nsamples = -1

            if itmin is None:
                itmin = 0
            else:
                itmin -= itoffset

            try:
                tr = GFTrace(*store_ext.store_sum(
                    self.cstore, irecords.astype(num.uint64),
                    (delays - itoffset*self._deltat).astype(num.float32),
                    weights.astype(num.float32),
                    int(itmin), int(nsamples)))

                tr.itmin += itoffset

            except store_ext.StoreExtError, e:
                raise StoreError(str(e))

        elif implementation == 'alternative':
            tr = self._sum_impl_alternative(irecords, delays, weights,
                                            itmin, nsamples, decimate)

        else:
            tr = self._sum_impl_reference(irecords, delays, weights,
                                          itmin, nsamples, decimate)

        t2 = time.time()

        tr.n_records_stacked = irecords.size
        tr.t_optimize = t1 - t0
        tr.t_stack = t2 - t1

        return tr

    def _sum_statics(self, irecords, weights, implementation, optimization):

        if not self._f_index:
            self.open()

        t0 = time.time()
        if optimization == 'enable':
            irecords, weights = self._optimize_statics(
                irecords, weights)
        else:
            assert optimization == 'disable'

        t1 = time.time()

        value = num.sum(self._end_values[irecords] * weights)
        val = GFValue(value)

        t2 = time.time()

        val.n_records_stacked = irecords.size
        val.t_optimize = t1 - t0
        val.t_stack = t2 - t1

        return val

    def _load_index(self):
        if self._use_memmap:
            records = num.memmap(
                self._f_index, dtype=gf_record_dtype,
                offset=gf_store_header_fmt_size,
                mode=('r', 'r+')[self.mode == 'w'])

        else:
            self._f_index.seek(gf_store_header_fmt_size)
            records = num.fromfile(self._f_index, dtype=gf_record_dtype)

        assert len(records) == self._nrecords

        self._records = records

        self._end_values = self._records['end_value']

    def _save_index(self):
        self._f_index.seek(0)
        self._f_index.write(struct.pack(gf_store_header_fmt, self._nrecords,
                                        self._deltat))

        if self._use_memmap:
            del self._records
        else:
            self._f_index.seek(gf_store_header_fmt_size)
            self._records.tofile(self._f_index)
            self._f_index.flush()

    def _get_data(self, ipos, begin_value, end_value, ilo, ihi):
        if ihi - ilo > 0:
            if ipos == 2:
                data_orig = num.empty(2, dtype=gf_dtype)
                data_orig[0] = begin_value
                data_orig[1] = end_value
                return data_orig[ilo:ihi]
            else:
                self._f_data.seek(
                    int(ipos + ilo*gf_dtype_nbytes_per_sample))
                arr = num.fromfile(
                    self._f_data, gf_dtype_store, ihi-ilo).astype(gf_dtype)

                if arr.size != ihi-ilo:
                    raise ShortRead()
                return arr
        else:
            return num.empty((0,), dtype=gf_dtype)

    def index_fn(self):
        return BaseStore.index_fn_(self.store_dir)

    def data_fn(self):
        return BaseStore.data_fn_(self.store_dir)

    def count_special_records(self):
        if not self._f_index:
            self.open()

        return num.histogram(self._records['data_offset'],
                             bins=[0, 1, 2, 3, num.uint64(-1)])[0]

    @property
    def size_index(self):
        return os.stat(self.index_fn()).st_size

    @property
    def size_data(self):
        return os.stat(self.data_fn()).st_size

    @property
    def size_index_and_data(self):
        return self.size_index + self.size_data

    @property
    def size_index_and_data_human(self):
        return util.human_bytesize(self.size_index_and_data)

    def stats(self):
        counter = self.count_special_records()

        stats = dict(
            total=self._nrecords,
            inserted=(counter[1] + counter[2] + counter[3]),
            empty=counter[0],
            short=counter[2],
            zero=counter[1],
            size_data=self.size_data,
            size_index=self.size_index,
        )

        return stats

    stats_keys = 'total inserted empty short zero size_data size_index'.split()


def remake_dir(dpath, force):
    if os.path.exists(dpath):
        if force:
            shutil.rmtree(dpath)
        else:
            raise CannotCreate('directory %s already exists' % dpath)

    os.mkdir(dpath)


class MakeTimingParamsFailed(StoreError):
    pass


class Store(BaseStore):

    '''
    Green's function disk storage and summation machine.

    The `Store` can be used to efficiently store, retrieve, and sum Green's
    function traces. A `Store` contains many 1D time traces sampled at even
    multiples of a global sampling rate, where each time trace has an
    individual start and end time.  The traces are treated as having repeating
    end points, so the functions they represent can be non-constant only
    between begin and end time. It provides capabilities to retrieve decimated
    traces and to extract parts of the traces. The main purpose of this class
    is to provide a fast, easy to use, and flexible machanism to compute
    weighted delay-and-sum stacks with many Green's function traces involved.

    Individual Green's functions are accessed through a single integer index at
    low level. On top of that, various indexing schemes can be implemented by
    providing a mapping from physical coordinates to the low level index `i`.
    E.g. for a problem with cylindrical symmetry, one might define a mapping
    from the coordinates (`receiver_depth`, `source_depth`, `distance`) to the
    low level index. Index translation is done in the
    :py:class:`pyrocko.gf.meta.Config` subclass object associated with the
    Store. It is accessible through the store's :py:attr:`config` attribute,
    and contains all meta information about the store, including physical
    extent, geometry, sampling rate, and information about the type of the
    stored Green's functions. Information about the underlying earth model
    can also be found there.

    A GF store can also contain tabulated phase arrivals. In basic cases, these
    can be created with the :py:meth:`make_ttt` and evaluated with the
    :py:func:`t` methods.

    .. attribute:: config

        The :py:class:`pyrocko.gf.meta.Config` derived object associated with
        the store which contains all meta information about the store and
        provides the high-level to low-level index mapping.

    .. attribute:: store_dir

        Path to the store's data directory.

    .. attribute:: mode

        The mode in which the store is opened: ``'r'``: read-only, ``'w'``:
        writeable.
    '''

    @staticmethod
    def create(store_dir, config, force=False, extra=None):
        '''
        Create new GF store.

        Creates a new GF store at path ``store_dir``. The layout of the GF is
        defined with the parameters given in ``config``, which should be an
        object of a subclass of :py:class:`pyrocko.gf.meta.Config`. This
        function will refuse to overwrite an existing GF store, unless
        ``force`` is set  to ``True``. If more information, e.g. parameters
        used for the modelling code, earth models or other, should be saved
        along with the GF store, these may be provided though a dict given to
        ``extra``. The keys of this dict must be names and the values must be
        *guts* type objects.

        :param store_dir: GF Store path
        :type store_dir: string
        :param config: GF Store Config
        :type config: :py:class:`pyrocko.gf.meta.Config`
        :param force: Force overwrite, defaults to False
        :type force: bool, optional
        :param extra: Extra information, defaults to None
        :type extra: dict, optional
        '''

        Store.create_editables(store_dir, config, force=force, extra=extra)
        Store.create_dependants(store_dir, force=force)

    @staticmethod
    def create_editables(store_dir, config, force=False, extra=None):
        try:
            util.ensuredir(store_dir)
        except:
            raise CannotCreate('cannot create directory %s' % store_dir)

        fns = []

        config_fn = os.path.join(store_dir, 'config')
        remove_if_exists(config_fn, force)
        meta.dump(config, filename=config_fn)

        fns.append(config_fn)

        for sub_dir in ['extra']:
            dpath = os.path.join(store_dir, sub_dir)
            remake_dir(dpath, force)

        if extra:
            for k, v in extra.iteritems():
                check_string_id(k)
                fn = os.path.join(store_dir, 'extra', k)
                remove_if_exists(fn, force)
                meta.dump(v, filename=fn)

                fns.append(fn)

        return fns

    @staticmethod
    def create_dependants(store_dir, force=False):
        config_fn = os.path.join(store_dir, 'config')
        config = meta.load(filename=config_fn)

        BaseStore.create(store_dir, config.deltat, config.nrecords,
                         force=force)

        for sub_dir in ['decimated']:
            dpath = os.path.join(store_dir, sub_dir)
            remake_dir(dpath, force)

    def __init__(self, store_dir, mode='r', use_memmap=True):
        BaseStore.__init__(self, store_dir, mode=mode, use_memmap=use_memmap)
        config_fn = os.path.join(store_dir, 'config')
        if not os.path.isfile(config_fn):
            raise StoreError(
                'directory "%s" does not seem to contain a GF Store '
                '("config" file not found)' % store_dir)

        self.config = meta.load(filename=config_fn)
        self._decimated = {}
        self._extra = {}
        self._phases = {}
        for decimate in range(2, 9):
            if os.path.isdir(self._decimated_store_dir(decimate)):
                self._decimated[decimate] = None

    def save_config(self, make_backup=False):
        config_fn = os.path.join(self.store_dir, 'config')
        if make_backup:
            os.rename(config_fn, config_fn + '~')

        meta.dump(self.config, filename=config_fn)

    def get_extra(self, key):
        '''
        Get extra information stored under given key.
        '''

        check_string_id(key)
        x = self._extra
        if key not in x:
            fn = os.path.join(self.store_dir, 'extra', key)
            if not os.path.exists(fn):
                raise NoSuchExtra(key)

            x[key] = meta.load(filename=fn)

        return x[key]

    def upgrade(self):
        '''
        Upgrade store config and files to latest Pyrocko version.
        '''
        fns = [os.path.join(self.store_dir, 'config')]
        for key in self.extra_keys():
            fns.append(os.path.join(self.store_dir, 'extra', key))

        i = 0
        for fn in fns:
            i += util.pf_upgrade(fn)

        return i

    def extra_keys(self):
        return [x for x in os.listdir(os.path.join(self.store_dir, 'extra'))
                if valid_string_id(x)]

    def put(self, args, trace):
        '''
        Insert trace into GF store.

        Store a single GF trace at (high-level) index ``args``.

        :param args: :py:class:`pyrocko.gf.meta.Config` index tuple, e.g.
            ``(source_depth, distance, component)`` as in
            :py:class:`pyrocko.gf.meta.ConfigTypeA`.
        :type args: tuple
        :returns: GF Trace at ``args``
        :rtype: :py:class:`pyrocko.gf.store.GFTrace`
        '''

        irecord = self.config.irecord(*args)
        self._put(irecord, trace)

    def get_record(self, args):
        irecord = self.config.irecord(*args)
        return self._get_record(irecord)

    def str_irecord(self, args):
        return BaseStore.str_irecord(self, self.config.irecord(*args))

    def get(self, args, itmin=None, nsamples=None, decimate=1,
            interpolation='nearest_neighbor', implementation='c'):
        '''
        Retrieve GF trace from store.

        Retrieve a single GF trace from the store at (high-level) index
        ``args``. By default, the full trace is retrieved. Given ``itmin`` and
        ``nsamples``, only the selected portion of the trace is extracted. If
        ``decimate`` is an integer in the range [2,8], the trace is decimated
        on the fly or, if available, the trace is read from a decimated version
        of the GF store.

        :param args: :py:class:`pyrocko.gf.meta.Config` index tuple, e.g.
            ``(source_depth, distance, component)`` as in
            :py:class:`pyrocko.gf.meta.ConfigTypeA`.
        :type args: tuple
        :param itmin: Start time index (start time is ``itmin * dt``),
            defaults to None
        :type itmin: integer, optional
        :param nsamples: Number of samples, defaults to None
        :type nsamples: integer, optional
        :param decimate: Decimatation factor, defaults to 1
        :type decimate: integer, optional
        :param interpolation: Interpolation method
            ``['nearest_neighbor', 'multilinear', 'off']``, defaults to
            ``'nearest_neighbor'``
        :type interpolation: str, optional
        :param implementation: Implementation mode, defaults to ``'c'``
        :type implementation: str, optional

        :returns: GF Trace at ``args``
        :rtype: :py:class:`pyrocko.gf.store.GFTrace`
        '''

        store, decimate = self._decimated_store(decimate)
        if interpolation == 'nearest_neighbor':
            irecord = store.config.irecord(*args)
            tr = store._get(irecord, itmin, nsamples, decimate,
                            implementation)

        elif interpolation == 'off':
            irecords, weights = store.config.vicinity(*args)
            if len(irecords) != 1:
                raise NotAllowedToInterpolate()
            else:
                tr = store._get(irecords[0], itmin, nsamples, decimate,
                                implementation)

        elif interpolation == 'multilinear':
            tr = store._sum(irecords, num.zeros(len(irecords)), weights,
                            itmin, nsamples, decimate, implementation,
                            'disable')

        # to prevent problems with rounding errors (BaseStore saves deltat
        # as a 4-byte floating point value, value from YAML config is more
        # accurate)
        tr.deltat = self.config.deltat * decimate
        return tr

    def sum(self, args, delays, weights, itmin=None, nsamples=None,
            decimate=1, interpolation='nearest_neighbor', implementation='c',
            optimization='enable'):
        '''
        Sum delayed and weighted GF traces.

        Calculate sum of delayed and weighted GF traces. ``args`` is a tuple of
        arrays forming the (high-level) indices of the GF traces to be
        selected.  Delays and weights for the summation are given in the arrays
        ``delays`` and ``weights``. ``itmin`` and ``nsamples`` can be given to
        restrict to computation to a given time interval.  If ``decimate`` is
        an integer in the range [2,8], decimated traces are used in the
        summation.

        :param args: :py:class:`pyrocko.gf.meta.Config` index tuple, e.g.
            ``(source_depth, distance, component)`` as in
            :py:class:`pyrocko.gf.meta.ConfigTypeA`.
        :type args: tuple
        :param delays: Delay times
        :type delays: :py:class:`numpy.Array`
        :param weights: Trace weights
        :type weights: :py:class:`numpy.Array`
        :param itmin: Start time index (start time is ``itmin * dt``),
            defaults to None
        :type itmin: integer, optional
        :param nsamples: Number of samples, defaults to None
        :type nsamples: integer, optional
        :param decimate: Decimatation factor, defaults to 1
        :type decimate: integer, optional
        :param interpolation: Interpolation method
            ``['nearest_neighbor', 'multilinear', 'off']``, defaults to
            ``'nearest_neighbor'``
        :type interpolation: str, optional
        :param implementation: Implementation mode ``['c', 'alternative']``
            where ``'alternative'`` uses a Python implementation, defaults to
            `'c'`
        :type implementation: str, optional
        :param optimization: Optimization mode ``['enable', 'disable']``,
            defaults to ``'enable'``
        :type optimization: str, optional
        :returns: Stacked GF Trace.
        :rtype: :py:class:`pyrocko.gf.store.GFTrace`
        '''

        store, decimate_ = self._decimated_store(decimate)

        if interpolation == 'nearest_neighbor':
            irecords = store.config.irecords(*args)
        else:
            assert interpolation == 'multilinear'
            irecords, ip_weights = store.config.vicinities(*args)
            neach = irecords.size / args[0].size
            weights = num.repeat(weights, neach) * ip_weights
            delays = num.repeat(delays, neach)

        tr = store._sum(irecords, delays, weights, itmin, nsamples, decimate_,
                        implementation, optimization)

        # to prevent problems with rounding errors (BaseStore saves deltat
        # as a 4-byte floating point value, value from YAML config is more
        # accurate)
        tr.deltat = self.config.deltat * decimate
        return tr

    def sum_statics(
            self, args, weights,
            decimate=1, interpolation='nearest_neighbor', implementation='c',
            optimization='enable'):

        if interpolation == 'nearest_neighbor':
            irecords = self.config.irecords(*args)
        else:
            assert interpolation == 'multilinear'
            irecords, ip_weights = self.config.vicinities(*args)
            neach = irecords.size / args[0].size
            weights = num.repeat(weights, neach) * ip_weights

        return self._sum_statics(
            irecords, weights, implementation, optimization)

    def make_decimated(self, decimate, config=None, force=False,
                       show_progress=False):
        '''
        Create decimated version of GF store.

        Create a downsampled version of the GF store. Downsampling is done for
        the integer factor ``decimate`` which should be in the range [2,8].  If
        ``config`` is ``None``, all traces of the GF store are decimated and
        held available (i.e. the index mapping of the original store is used),
        otherwise, a different spacial stepping can be specified by giving a
        modified GF store configuration in ``config`` (see :py:meth:`create`).
        Decimated GF sub-stores are created under the ``decimated``
        subdirectory within the GF store directory. Holding available decimated
        versions of the GF store can save computation time, IO bandwidth, or
        decrease memory footprint at the cost of increased disk space usage,
        when computation are done for lower frequency signals.

        :param decimate: Decimate factor
        :type decimate: integer
        :param config: GF Store config object, defaults to None
        :type config: :py:class:`pyrocko.gf.meta.Config`, optional
        :param force: Force overwrite, defaults to False
        :type force: bool, optional
        :param show_progress: Show progress, defaults to False
        :type show_progress: bool, optional
        '''

        if not self._f_index:
            self.open()

        if not (2 <= decimate <= 8):
            raise StoreError('decimate argument must be in the range [2,8]')

        assert self.mode == 'r'

        if config is None:
            config = self.config

        config = copy.deepcopy(config)
        config.sample_rate = self.config.sample_rate / decimate

        if decimate in self._decimated:
            del self._decimated[decimate]

        store_dir = self._decimated_store_dir(decimate)
        if os.path.exists(store_dir):
            if force:
                shutil.rmtree(store_dir)
            else:
                raise CannotCreate('store already exists at %s' % store_dir)

        store_dir_incomplete = store_dir + '-incomplete'
        Store.create(store_dir_incomplete, config, force=force)

        decimated = Store(store_dir_incomplete, 'w')
        if show_progress:
            pbar = util.progressbar('decimating store', self.config.nrecords)

        for i, args in enumerate(decimated.config.iter_nodes()):
            tr = self.get(args, decimate=decimate)
            decimated.put(args, tr)

            if show_progress:
                pbar.update(i+1)

        if show_progress:
            pbar.finish()

        decimated.close()

        shutil.move(store_dir_incomplete, store_dir)

        self._decimated[decimate] = None

    def stats(self):
        stats = BaseStore.stats(self)
        stats['decimated'] = sorted(self._decimated.keys())
        return stats

    stats_keys = BaseStore.stats_keys + ['decimated']

    def check(self, show_progress=False):
        if show_progress:
            pbar = util.progressbar('checking store', self.config.nrecords)

        problems = 0
        for i, args in enumerate(self.config.iter_nodes()):
            tr = self.get(args)
            if tr and not tr.is_zero:
                if not tr.begin_value == tr.data[0]:
                    logger.warn('wrong begin value for trace at %s '
                                '(data corruption?)' % str(args))
                    problems += 1
                if not tr.end_value == tr.data[-1]:
                    logger.warn('wrong end value for trace at %s '
                                '(data corruption?)' % str(args))
                    problems += 1
                if not num.all(num.isfinite(tr.data)):
                    logger.warn('nans or infs in trace at %s' % str(args))
                    problems += 1

            if show_progress:
                pbar.update(i+1)

        if show_progress:
            pbar.finish()

        return problems

    def check_earthmodels(self, config):
        if config.earthmodel_receiver_1d.profile('z')[-1] not in\
                config.earthmodel_1d.profile('z'):
            logger.warn('deepest layer of earthmodel_receiver_1d not '
                        'found in earthmodel_1d')

    def _decimated_store_dir(self, decimate):
        return os.path.join(self.store_dir, 'decimated', str(decimate))

    def _decimated_store(self, decimate):
        if decimate == 1 or decimate not in self._decimated:
            return self, decimate
        else:
            store = self._decimated[decimate]
            if store is None:
                store = Store(self._decimated_store_dir(decimate), 'r')
                self._decimated[decimate] = store

            return store, 1

    def _phase_filename(self, phase_id):
        check_string_id(phase_id)

        fn = os.path.join(self.store_dir, 'phases', phase_id + '.phase')
        if not os.path.isfile(fn):
            raise NoSuchPhase(phase_id)

        return fn

    def get_stored_phase(self, phase_id):
        """Get stored phase from GF STore

        :returns: Phase information
        :rtype: :py:class:`pyrocko.spit.SPTree`
        """
        if phase_id not in self._phases:
            fn = self._phase_filename(phase_id)
            spt = spit.SPTree(filename=fn)
            self._phases[phase_id] = spt

        return self._phases[phase_id]

    def get_phase(self, phase_def):
        provider, phase_def = phase_def.split(':', 1)

        if provider == 'stored':
            return self.get_stored_phase(phase_def)

        elif provider == 'vel':
            vel = float(phase_def) * 1000.

            def evaluate(args):
                return self.config.get_distance(args) / vel

            return evaluate

        elif provider == 'vel_surface':
            vel = float(phase_def) * 1000.

            def evaluate(args):
                return self.config.get_surface_distance(args) / vel

            return evaluate

        elif provider in ('cake', 'iaspei'):
            from pyrocko import cake
            mod = self.config.earthmodel_1d
            if provider == 'cake':
                phases = [cake.PhaseDef(phase_def)]
            else:
                phases = cake.PhaseDef.classic(phase_def)

            def evaluate(args):
                if isinstance(args, num.ndarray):
                    if args.shape[1] == 2:
                        zr = num.empty(args.shape[0])
                        zr[:] = self.config.receiver_depth
                        zs, x = args.T
                    elif args.shape[1] == 3:
                        zr, zs, x = args.T
                    else:
                        assert False

                    n = len(args)
                    t = num.empty(n)
                    if phases:
                        for i in xrange(n):
                            tmp = []
                            rays = mod.arrivals(
                                phases=phases,
                                distances=[x[i]*cake.m2d],
                                zstart=zs[i],
                                zstop=zr[i])

                            for ray in rays:
                                tmp.append(ray.t)

                            if tmp:
                                t[i] = min(tmp)
                            else:
                                t[i] = num.nan
                    return t

                else:
                    if len(args) == 2:
                        zr, zs, x = (self.config.receiver_depth,) + args
                    elif len(args) == 3:
                        zr, zs, x = args
                    else:
                        assert False

                    t = []
                    if phases:
                        rays = mod.arrivals(
                            phases=phases,
                            distances=[x*cake.m2d],
                            zstart=zs,
                            zstop=zr)

                        for ray in rays:
                            t.append(ray.t)

                    if t:
                        return min(t)
                    else:
                        return None

            return evaluate

        raise StoreError('unsupported phase provider: %s' % provider)

    def t(self, timing, *args):
        '''
        Compute interpolated phase arrivals.

        **Examples:**

        If ``test_store`` is of :py:class:`pyrocko.gf.meta.ConfigTypeA`::

            test_store.t('p', (1000, 10000))
            test_store.t('last{P|Pdiff}', (1000, 10000)) # The latter arrival
                                                         # of P or diffracted
                                                         # P phase

        If ``test_store`` is of :py:class:`pyrocko.gf.meta.ConfigTypeB`::

            test_store.t('S', (1000, 1000, 10000))
            test_store.t('first{P|p|Pdiff|sP}', (1000, 1000, 10000)) # The
                        `                                # first arrival of
                                                         # the given phases is
                                                         # selected

        :param timing: Timing string as described above
        :type timing: string or :py:class:`pyrocko.gf.meta.Timing`
        :param \*args: :py:class:`pyrocko.gf.meta.Config` index tuple, e.g.
            ``(source_depth, distance, component)`` as in
            :py:class:`pyrocko.gf.meta.ConfigTypeA`.
        :type \*args: tuple
        :returns: Phase arrival according to ``timing``
        :rtype: float or None
        '''

        if len(args) == 1:
            args = args[0]
        else:
            args = self.config.make_indexing_args1(*args)

        if not isinstance(timing, meta.Timing):
            timing = meta.Timing(timing)

        return timing.evaluate(self.get_phase, args)

    def make_timing_params(self, begin, end, snap_vred=True):

        '''
        Compute tight parameterized time ranges to include given timings.

        Calculates appropriate time ranges to cover given begin and end timings
        over all GF points in the store. A dict with the following keys is
        returned:

        * ``'tmin'``: time [s], minimum of begin timing over all GF points
        * ``'tmax'``: time [s], maximum of end timing over all GF points
        * ``'vred'``, ``'tmin_vred'``: slope [m/s] and offset [s] of reduction
          velocity [m/s] appropriate to catch begin timing over all GF points
        * ``'tlenmax_vred'``: maximum time length needed to cover all end
          timings, when using linear slope given with (``vred``, ``tmin_vred``)
          as start
        '''

        data = []
        for args in self.config.iter_nodes(level=-1):
            tmin = self.t(begin, args)
            tmax = self.t(end, args)
            x = self.config.get_surface_distance(args)
            data.append((x, tmin, tmax))

        xs, tmins, tmaxs = num.array(data, dtype=num.float).T

        i = num.nanargmin(tmins)
        if not num.isfinite(i):
            raise MakeTimingParamsFailed('determination of time window failed')

        tminmin = tmins[i]
        x_tminmin = xs[i]
        dx = (xs - x_tminmin)
        dx = num.where(dx != 0.0, dx, num.nan)
        s = (tmins - tminmin) / dx
        sred = num.min(num.abs(s[num.isfinite(s)]))

        deltax = self.config.distance_delta

        if snap_vred:
            tdif = sred*deltax
            tdif2 = self.config.deltat * math.floor(tdif / self.config.deltat)
            sred = tdif2/self.config.distance_delta

        tmin_vred = tminmin - sred*x_tminmin
        if snap_vred:
            xe = x_tminmin - int(x_tminmin / deltax) * deltax
            tmin_vred = float(
                self.config.deltat *
                math.floor(tmin_vred / self.config.deltat) - xe * sred)

        tlenmax_vred = num.nanmax(tmax - (tmin_vred + sred*x))
        if sred != 0.0:
            vred = 1.0/sred
        else:
            vred = 0.0

        return dict(
            tmin=tminmin,
            tmax=num.nanmax(tmaxs),
            tmin_vred=tmin_vred,
            tlenmax_vred=tlenmax_vred,
            vred=vred)

    def make_ttt(self, force=False):
        '''Compute travel time tables.

        Travel time tables are computed using the 1D earth model defined in
        :py:attr:`pyrocko.gf.meta.Config.earthmodel_1d` for each defined phase
        in :py:attr:`pyrocko.gf.meta.Config.tabulated_phases`. The accuracy of
        the tablulated times is adjusted to the sampling rate of the store.
        '''

        from pyrocko import cake
        config = self.config

        if not config.tabulated_phases:
            return

        mod = config.earthmodel_1d

        if config.earthmodel_receiver_1d:
            self.check_earthmodels(config)

        if not mod:
            raise StoreError('no earth model found')

        for pdef in config.tabulated_phases:

            phase_id = pdef.id
            phases = pdef.phases
            horvels = pdef.horizontal_velocities

            fn = os.path.join(self.store_dir, 'phases', '%s.phase' % phase_id)

            if os.path.exists(fn) and not force:
                logger.info('file already exists: %s' % fn)
                continue

            def evaluate(args):

                if len(args) == 2:
                    zr, zs, x = (config.receiver_depth,) + args
                elif len(args) == 3:
                    zr, zs, x = args
                else:
                    assert False

                t = []
                if phases:
                    rays = mod.arrivals(
                        phases=phases,
                        distances=[x*cake.m2d],
                        zstart=zs,
                        zstop=zr)

                    for ray in rays:
                        t.append(ray.t)

                for v in horvels:
                    t.append(x/(v*1000.))

                if t:
                    return min(t)
                else:
                    return None

            logger.info('making travel time table for phasegroup "%s"' %
                        phase_id)

            ip = spit.SPTree(
                f=evaluate,
                ftol=config.deltat*0.5,
                xbounds=num.transpose((config.mins, config.maxs)),
                xtols=config.deltas)

            util.ensuredirs(fn)
            ip.dump(fn)

    def statics(
            self, source, receiver, components,
            interpolation='nearest_neighbor', optimization='enable'):

        out = [None] * len(components)
        for (component, args, _, weights) in \
                self.config.make_sum_params(source, receiver):

            if component in components:
                gval = self.sum_statics(
                    args, weights,
                    interpolation=interpolation,
                    optimization=optimization)

                out[components.index(component)] = gval.value

        return out

    def seismogram(self, source, receiver, components, deltat=None,
                   itmin=None, nsamples=None,
                   interpolation='nearest_neighbor', optimization='enable'):

        out = {}

        if deltat is None:
            decimate = 1
        else:
            decimate = int(round(deltat/self.config.deltat))
            if abs(deltat / (decimate * self.config.deltat) - 1.0) > 0.001:
                raise StoreError(
                    'unavailable decimation ratio target.deltat / store.deltat'
                    ' = %g / %g' % (deltat, self.config.deltat))

        for (component, args, delays, weights) in \
                self.config.make_sum_params(source, receiver):

            if component in components:
                gtr = self.sum(args, delays, weights,
                               decimate=decimate,
                               itmin=itmin, nsamples=nsamples,
                               interpolation=interpolation,
                               optimization=optimization)

                out[component] = gtr

        return out


__all__ = '''
gf_dtype
NotMultipleOfSamplingInterval
GFTrace
StoreError
CannotCreate
CannotOpen
DuplicateInsert
NotAllowedToInterpolate
NoSuchExtra
NoSuchPhase
BaseStore
Store
'''.split()
