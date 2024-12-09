# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Multi-component waveform data model.
'''

import logging
from functools import partialmethod
from collections import defaultdict

import numpy as num
import numpy.ma as ma
from scipy import signal

from . import trace, util
from .trace import Trace, AboveNyquist, _get_cached_filter_coeffs
from .guts import Object, Float, Timestamp, List, Int
from .guts_array import Array
from .squirrel import \
    CodesNSLCE, SensorGrouping, Grouping

from .squirrel.operators.base import ReplaceComponentTranslation

logger = logging.getLogger('pyrocko.multitrace')


class MultiTrace(Object):
    '''
    Container for multi-component waveforms with common time span and sampling.

    Instances of this class can be used to efficiently represent
    multi-component waveforms of a single sensor or of a sensor array. The data
    samples are stored in a single 2D array where the first index runs over
    components and the second index over time. Metadata contains sampling rate,
    start-time and :py:class:`~pyrocko.squirrel.model.CodesNSLCE` identifiers
    for the contained traces.

    The :py:gattr:`data` is held as a NumPy :py:class:`numpy.ma.MaskedArray`
    where missing or invalid data is masked.

    :param traces:
        If given, construct multi-trace from given single-component waveforms
        (see :py:func:`~pyrocko.trace.get_traces_data_as_array`) and ignore
        any other arguments.
    :type traces:
        :py:class:`list` of :py:class:`~pyrocko.trace.Trace`
    '''

    codes = List.T(
        CodesNSLCE.T(),
        help='List of codes identifying the components.')
    nsamples = Int.T(
        help='Number of samples.')
    data = Array.T(
        optional=True,
        shape=(None, None),
        help='Array containing the data samples indexed as '
             '``(icomponent, isample)``.')
    spectrum = Array.T(
        optional=True,
        shape=(None, None),
        dtype=complex,
        help='Array containing the spectral coefficients indexed as '
             '``(icomponent, ifrequency)``.')
    tmin = Timestamp.T(
        default=Timestamp.D('1970-01-01 00:00:00'),
        help='Start time.')
    deltat = Float.T(
        default=1.0,
        help='Sampling interval [s]')

    def __init__(
            self,
            traces=None,
            assemble='concatenate',
            data=None,
            nsamples=None,
            codes=None,
            tmin=None,
            deltat=None):

        util.experimental_feature_used('pyrocko.multitrace')

        if traces is not None:
            if len(traces) == 0:
                data = ma.zeros((0, 0))
            else:
                if assemble == 'merge':
                    data, codes, tmin, deltat \
                        = trace.merge_traces_data_as_array(traces)

                elif assemble == 'concatenate':
                    data = ma.array(trace.get_traces_data_as_array(traces))
                    codes = [tr.codes for tr in traces]
                    tmin = traces[0].tmin
                    deltat = traces[0].deltat

        if nsamples is not None and data is not None \
                and data.shape[1] != nsamples:

            raise ValueError(
                'MultiTrace construction: mismatch between expected number of '
                'samples and number of samples in data array.')

        self.ntraces, nsamples = data.shape

        if codes is None:
            codes = [CodesNSLCE()] * self.ntraces

        if len(codes) != self.ntraces:
            raise ValueError(
                'MultiTrace construction: mismatch between number of traces '
                'and number of codes given.')

        if deltat is None:
            deltat = self.T.deltat.default()

        if tmin is None:
            tmin = self.T.tmin.default()

        Object.__init__(
            self,
            codes=codes,
            data=data,
            tmin=tmin,
            nsamples=nsamples,
            deltat=deltat)

    @property
    def summary_codes(self):
        if self.codes:
            if len(self.codes) == 1:
                return str(self.codes[0])
            elif len(self.codes) == 2:
                return '%s, %s' % (self.codes[0], self.codes[-1])
            else:
                return '%s, ..., %s' % (self.codes[0], self.codes[-1])
        else:
            return 'None'

    @property
    def summary_entries(self):
        return (
            self.__class__.__name__,
            str(self.data.shape[0]),
            str(self.data.shape[1]),
            str(self.data.dtype),
            str(self.deltat),
            util.time_to_str(self.tmin),
            util.time_to_str(self.tmax),
            self.summary_codes)

    @property
    def summary(self):
        '''
        Textual summary of the waveform's metadata attributes.
        '''
        return util.fmt_summary(
            self.summary_entries, (10, 5, 7, 10, 10, 25, 25, 50))

    def __len__(self):
        '''
        Get number of components.
        '''
        return self.ntraces

    def __getitem__(self, i):
        '''
        Get single component waveform (shared data).

        :param i:
            Component index.
        :type i:
            int
        '''
        return self.get_trace(i)

    def copy(self, data='copy'):
        '''
        Create a copy

        :param data:
            ``'copy'`` to deeply copy the data, or ``'reference'`` to create
            a shallow copy, referencing the original data.
        :type data:
            str
        '''

        if isinstance(data, str):
            assert data in ('copy', 'reference')
            data = self.data.copy() if data == 'copy' else self.data
        else:
            assert isinstance(data, ma.MaskedArray)

        return MultiTrace(
            data=data,
            codes=list(self.codes),
            tmin=self.tmin,
            deltat=self.deltat)

    def chopper(self, tinc):
        nwindows = int(num.floor((self.tmax - self.tmin) / tinc)) + 1
        nsamples = int(num.floor(tinc / self.deltat))
        for iwindow in range(nwindows):
            istart = int(num.floor((iwindow * tinc) / self.deltat))
            iend = istart + nsamples
            yield MultiTrace(
                data=self.data[:, istart:iend],
                codes=self.codes,
                tmin=self.tmin + istart * self.deltat,
                deltat=self.deltat)

    @property
    def tmax(self):
        '''
        End time (time of last sample, read-only).
        '''
        return self.tmin + (self.nsamples - 1) * self.deltat

    def get_trace(self, i, span=slice(None)):
        '''
        Get single component waveform (shared data).

        :param i:
            Component index.
        :type i:
            int
        '''

        network, station, location, channel, extra = self.codes[i]
        return Trace(
            network=network,
            station=station,
            location=location,
            channel=channel,
            extra=extra,
            tmin=self.tmin + (span.start or 0) * self.deltat,
            deltat=self.deltat,
            ydata=self.data.data[i, span])

    def iter_valid_traces(self):
        if self.data.mask is ma.nomask:
            yield from self
        else:
            for irow, row in enumerate(
                    ma.notmasked_contiguous(self.data, axis=1)):
                for slice in row:
                    yield self.get_trace(irow, slice)

    def get_traces(self):
        return list(self)

    def get_valid_traces(self):
        return list(self.iter_valid_traces())

    def snuffle(self, what='valid'):
        '''
        Show in Snuffler.
        '''

        assert what in ('valid', 'raw')

        if what == 'valid':
            trace.snuffle(self.get_valid_traces())
        else:
            trace.snuffle(list(self))

    def bleed(self, t):

        nt = int(num.round(abs(t)/self.deltat))
        if nt < 1:
            return

        if self.data.mask is ma.nomask:
            self.data.mask = ma.make_mask_none(self.data.shape)

        for irow, row in enumerate(ma.notmasked_contiguous(self.data, axis=1)):
            for span in row:
                self.data.mask[irow, span.start:span.start+nt] = True
                self.data.mask[irow, max(0, span.stop-nt):span.stop] = True

        self.data.mask[:, :nt] = True
        self.data.mask[:, -nt:] = True

    def set_data(self, data):
        if data is self.data:
            return

        assert data.shape == self.data.shape

        if isinstance(data, ma.MaskedArray):
            self.data = data
        else:
            data = ma.MaskedArray(data)
            data.mask = self.data.mask
            self.data = data

    def apply(self, f):
        self.set_data(f(self.data))

    def reduce(self, f, codes):
        data = f(self.data)
        if data.ndim == 1:
            data = data[num.newaxis, :]
        if isinstance(codes, CodesNSLCE):
            codes = [codes]
        assert data.ndim == 2
        assert data.shape[1] == self.data.shape[1]
        assert len(codes) == data.shape[0]
        self.codes = codes
        if isinstance(data, ma.MaskedArray):
            self.data = data
        else:
            self.data = ma.MaskedArray(data)

    def nyquist_check(
            self,
            frequency,
            intro='Corner frequency',
            warn=True,
            raise_exception=False):

        '''
        Check if a given frequency is above the Nyquist frequency of the trace.

        :param intro:
            String used to introduce the warning/error message.
        :type intro:
            str

        :param warn:
            Whether to emit a warning message.
        :type warn:
            bool

        :param raise_exception:
            Whether to raise :py:exc:`~pyrocko.trace.AboveNyquist`.
        :type raise_exception:
            bool
        '''

        if frequency >= 0.5/self.deltat:
            message = '%s (%g Hz) is equal to or higher than nyquist ' \
                      'frequency (%g Hz). (%s)' \
                % (intro, frequency, 0.5/self.deltat, self.summary)
            if warn:
                logger.warning(message)
            if raise_exception:
                raise AboveNyquist(message)

    def lfilter(self, b, a, demean=True):
        '''
        Filter waveforms with :py:func:`scipy.signal.lfilter`.

        Sample data is converted to type :py:class:`float`, possibly demeaned
        and filtered using :py:func:`scipy.signal.lfilter`.

        :param b:
            Numerator coefficients.
        :type b:
            float

        :param a:
            Denominator coefficients.
        :type a:
            float

        :param demean:
            Subtract mean before filttering.
        :type demean:
            bool
        '''

        def filt(data):
            data = data.astype(num.float64)
            if demean:
                data -= num.mean(data, axis=1)[:, num.newaxis]

            return signal.lfilter(b, a, data)

        self.apply(filt)

    def lowpass(self, order, corner, nyquist_warn=True,
                nyquist_exception=False, demean=True):

        '''
        Filter waveforms using a Butterworth lowpass.

        Sample data is converted to type :py:class:`float`, possibly demeaned
        and filtered using :py:func:`scipy.signal.lfilter`. Filter coefficients
        are generated with :py:func:`scipy.signal.butter`.

        :param order:
            Order of the filter.
        :type order:
            int

        :param corner:
            Corner frequency of the filter [Hz].
        :type corner:
            float

        :param demean:
            Subtract mean before filtering.
        :type demean:
            bool

        :param nyquist_warn:
            Warn if corner frequency is greater than Nyquist frequency.
        :type nyquist_warn:
            bool

        :param nyquist_exception:
            Raise :py:exc:`pyrocko.trace.AboveNyquist` if corner frequency is
            greater than Nyquist frequency.
        :type nyquist_exception:
            bool
        '''

        self.nyquist_check(
            corner, 'Corner frequency of lowpass', nyquist_warn,
            nyquist_exception)

        (b, a) = _get_cached_filter_coeffs(
            order, [corner*2.0*self.deltat], btype='low')

        if len(a) != order+1 or len(b) != order+1:
            logger.warning(
                'Erroneous filter coefficients returned by '
                'scipy.signal.butter(). Should downsample before filtering.')

        self.lfilter(b, a, demean=demean)

    def highpass(self, order, corner, nyquist_warn=True,
                 nyquist_exception=False, demean=True):

        '''
        Filter waveforms using a Butterworth highpass.

        Sample data is converted to type :py:class:`float`, possibly demeaned
        and filtered using :py:func:`scipy.signal.lfilter`. Filter coefficients
        are generated with :py:func:`scipy.signal.butter`.

        :param order:
            Order of the filter.
        :type order:
            int

        :param corner:
            Corner frequency of the filter [Hz].
        :type corner:
            float

        :param demean:
            Subtract mean before filtering.
        :type demean:
            bool

        :param nyquist_warn:
            Warn if corner frequency is greater than Nyquist frequency.
        :type nyquist_warn:
            bool

        :param nyquist_exception:
            Raise :py:exc:`~pyrocko.trace.AboveNyquist` if corner frequency is
            greater than Nyquist frequency.
        :type nyquist_exception:
            bool
        '''

        self.nyquist_check(
            corner, 'Corner frequency of highpass', nyquist_warn,
            nyquist_exception)

        (b, a) = _get_cached_filter_coeffs(
            order, [corner*2.0*self.deltat], btype='high')

        if len(a) != order+1 or len(b) != order+1:
            logger.warning(
                'Erroneous filter coefficients returned by '
                'scipy.signal.butter(). Should downsample before filtering.')

        self.lfilter(b, a, demean=demean)

    def smooth(self, t, window=num.hanning):
        n = (int(num.round(t / self.deltat)) // 2) * 2 + 1
        taper = window(n)

        def multiply_taper(frequency_delta, ntrans, spectrum):
            taper_pad = num.zeros(ntrans)
            taper_pad[:n//2+1] = taper[n//2:]
            taper_pad[-n//2+1:] = taper[:n//2]
            taper_fd = num.fft.rfft(taper_pad)
            spectrum *= taper_fd[num.newaxis, :]
            return spectrum

        self.apply_via_fft(
            multiply_taper,
            ntrans_min=n)

    def whiten(self, deltaf, window=num.hanning):

        def smooth(frequency_delta, ntrans, spectrum):
            n = (int(num.round(deltaf / frequency_delta)) // 2) * 2 + 1
            taper = window(n)
            amp_spec = num.abs(spectrum)
            amp_spec_smooth = signal.fftconvolve(
                amp_spec, taper[num.newaxis, :], mode='same', axes=1)

            spectrum /= amp_spec_smooth
            return spectrum

        self.apply_via_fft(smooth)

    def normalize(self, deltat, window=num.hanning):
        rms = self.get_rms(grouping=Grouping())
        rms.smooth(deltat)
        self.data /= rms.data

    def apply_via_fft(self, f, ntrans_min=0):
        frequency_delta, ntrans, spectrum = self.get_spectrum(ntrans_min)
        spectrum = f(frequency_delta, ntrans, spectrum)
        data_new = num.fft.irfft(spectrum)[:, :self.nsamples]
        self.set_data(data_new)

    def get_spectrum(self, ntrans_min=0):
        ntrans = trace.nextpow2(max(ntrans_min, self.nsamples))
        data = ma.filled(self.data.astype(num.float64), 0.0)
        spectrum = num.fft.rfft(data, ntrans)
        frequency_delta = 1.0 / (self.deltat * ntrans)
        return frequency_delta, ntrans, spectrum

    def get_cross_spectrum(self, ntrans_min=0):
        frequency_delta, ntrans, spectrum = self.get_spectrum(ntrans_min)
        return (
            frequency_delta,
            ntrans,
            num.einsum('ik,jk->ijk', spectrum, num.conj(spectrum)))

    def get_codes_grouped(self, grouping):
        groups = defaultdict(list)
        for irow, codes in enumerate(self.codes):
            groups[grouping.key(codes)].append(irow)

        return groups

    def get_energy(
            self,
            grouping=SensorGrouping(),
            translation=ReplaceComponentTranslation(),
            postprocessing=None):

        groups = self.get_codes_grouped(grouping)

        data = self.data.astype(num.float64)
        data **= 2
        data3 = num.ma.empty((len(groups), self.nsamples))
        codes = []
        for irow_out, irows_in in enumerate(groups.values()):
            data3[irow_out, :] = data[irows_in, :].sum(axis=0)
            codes.append(CodesNSLCE(
                translation.translate(
                    self.codes[irows_in[0]]).safe_str.format(component='G')))

        if data3.mask is ma.nomask:
            data3.mask = ma.make_mask_none(data3.shape)

        data3.mask |= data3.data == 0
        data3.data[data3.mask] = 1.0

        energy = MultiTrace(
            data=data3,
            codes=codes,
            tmin=self.tmin,
            deltat=self.deltat)

        if postprocessing is not None:
            energy.apply(postprocessing)

        return energy

    get_rms = partialmethod(
        get_energy,
        postprocessing=lambda data: num.sqrt(data, out=data))

    get_log_rms = partialmethod(
        get_energy,
        postprocessing=lambda data: num.multiply(
            num.log(
                signal.filtfilt([0.5, 0.5], [1], data),
                out=data),
            0.5,
            out=data))

    get_log10_rms = partialmethod(
        get_energy,
        postprocessing=lambda data: num.multiply(
            num.log(
                signal.filtfilt([0.5, 0.5], [1], data),
                out=data),
            0.5 / num.log(10.0),
            out=data))


def correlate(a, b, mode='valid', normalization=None, use_fft=False):

    if isinstance(a, Trace) and isinstance(b, Trace):
        return trace.correlate(
            a, b, mode=mode, normalization=normalization, use_fft=use_fft)

    elif isinstance(a, Trace) and isinstance(b, MultiTrace):
        return MultiTrace([
            trace.correlate(
                a, b_,
                mode=mode, normalization=normalization, use_fft=use_fft)
            for b_ in b])

    elif isinstance(a, MultiTrace) and isinstance(b, Trace):
        return MultiTrace([
            trace.correlate(
                a_, b,
                mode=mode, normalization=normalization, use_fft=use_fft)
            for a_ in a])

    elif isinstance(a, MultiTrace) and isinstance(b, MultiTrace):
        return MultiTrace([
            trace.correlate(
                a_, b_,
                mode=mode, normalization=normalization, use_fft=use_fft)

            for a_ in a for b_ in b])
