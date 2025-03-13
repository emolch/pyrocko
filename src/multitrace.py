# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Multi-component waveform data model.
'''

import logging
import re
from functools import partialmethod
from collections import defaultdict

import numpy as num
import numpy.ma as ma
from scipy import signal

from . import trace, util
from .trace import Trace, AboveNyquist, _get_cached_filter_coeffs, costaper
from .guts import Object, Float, Timestamp, List, Int, Dict, String
from .guts_array import Array
from .model.codes import CodesNSLCE

from .squirrel.operators.base import ReplaceComponentTranslation

guts_prefix = 'pf'

logger = logging.getLogger('pyrocko.multitrace')

EMPTY_CODES = CodesNSLCE()


class CarpetStringFiller:

    def __init__(self, carpet, additional={}):
        self.carpet = carpet
        self.codes = carpet.codes
        self.additional = additional

    def __getitem__(self, k):
        if k in ('network', 'station', 'location', 'channel', 'extra'):
            return getattr(self.codes, k)

        method = getattr(self, 'get_' + k, None)
        if method:
            return method()

        return self.additional[k]

    def _filename_safe(self, s):
        return re.sub(r'[^0-9A-Za-z_-]', '_', s)

    def get_network_safe(self):
        return self._filename_safe(self.codes.network)

    def get_station_safe(self):
        return self._filename_safe(self.codes.station)

    def get_location_safe(self):
        return self._filename_safe(self.codes.location)

    def get_channel_safe(self):
        return self._filename_safe(self.codes.channel)

    def get_extra_safe(self):
        return self._filename_safe(self.codes.extra)

    def get_nslce_safe(self):
        return self._filename_safe('.'.join(self.codes))

    def get_nslc_safe(self):
        return self._filename_safe('.'.join(self.codes[:4]))

    def get_network_dsafe(self):
        return self._filename_safe(self.codes.network) or '_'

    def get_station_dsafe(self):
        return self._filename_safe(self.codes.station) or '_'

    def get_location_dsafe(self):
        return self._filename_safe(self.codes.location) or '_'

    def get_channel_dsafe(self):
        return self._filename_safe(self.codes.channel) or '_'

    def get_extra_dsafe(self):
        return self._filename_safe(self.codes.extra) or '_'

    def get_tmin(self):
        return util.time_to_str(
            self.carpet.tmin, format='%Y-%m-%d_%H-%M-%S')

    def get_tmax(self):
        return util.time_to_str(
            self.carpet.tmax, format='%Y-%m-%d_%H-%M-%S')

    def get_tmin_ms(self):
        return util.time_to_str(
            self.carpet.tmin, format='%Y-%m-%d_%H-%M-%S.3FRAC')

    def get_tmax_ms(self):
        return util.time_to_str(
            self.carpet.tmax, format='%Y-%m-%d_%H-%M-%S.3FRAC')

    def get_tmin_us(self):
        return util.time_to_str(
            self.carpet.tmin, format='%Y-%m-%d_%H-%M-%S.6FRAC')

    def get_tmax_us(self):
        return util.time_to_str(
            self.carpet.tmax, format='%Y-%m-%d_%H-%M-%S.6FRAC')

    def get_tmin_year(self):
        return util.time_to_str(self.carpet.tmin, format='%Y')

    def get_tmin_month(self):
        return util.time_to_str(self.carpet.tmin, format='%m')

    def get_tmin_day(self):
        return util.time_to_str(self.carpet.tmin, format='%d')

    def get_tmax_year(self):
        return util.time_to_str(self.carpet.tmax, format='%Y')

    def get_tmax_month(self):
        return util.time_to_str(self.carpet.tmax, format='%m')

    def get_tmax_day(self):
        return util.time_to_str(self.carpet.tmax, format='%d')

    def get_julianday(self):
        return str(util.julian_day_of_year(self.carpet.tmin))

    def get_tmin_jday(self):
        return util.time_to_str(self.carpet.tmin, format='%j')

    def get_tmax_jday(self):
        return util.time_to_str(self.carpet.tmax, format='%j')


class CarpetStats(Object):
    min = Float.T()
    p10 = Float.T()
    median = Float.T()
    p90 = Float.T()
    max = Float.T()

    @classmethod
    def make(cls, data):
        min, p10, median, p90, max = num.nanpercentile(
            data, [0., 10., 50., 90., 100.])

        return cls(min=min, p10=p10, median=median, p90=p90, max=max)


class Carpet(Object):
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

    codes = CodesNSLCE.T(
        default=CodesNSLCE.D(),
        help='Codes identifying the carpet as a whole.')

    component_codes = List.T(
        CodesNSLCE.T(),
        help='List of codes identifying the components.')

    component_axes = Dict.T(
        String.T(),
        Array.T(shape=(None,), serialize_as='base64+meta'),
        help='Auxiliary component coordinate axes.')

    nsamples = Int.T(
        help='Number of samples.')

    # TODO change and implement MaskedArray
    data = Array.T(
        optional=True,
        shape=(None, None),
        serialize_as='base64+meta',
        help='Array containing the data samples indexed as '
             '``(icomponent, isample)``.')

    tmin = Timestamp.T(
        default=Timestamp.D('1970-01-01 00:00:00'),
        help='Start time.')

    deltat = Float.T(
        default=1.0,
        help='Sampling interval [s]')

    stats__ = CarpetStats.T(optional=True)

    def __init__(
            self,
            traces=None,
            assemble='concatenate',
            data=None,
            nsamples=None,
            codes=None,
            component_codes=None,
            component_axes=None,
            tmin=None,
            deltat=None):

        util.experimental_feature_used('pyrocko.carpet')

        if data is not None and not isinstance(data, num.ndarray):
            data = self.T.get_property('data').regularize_extra(data)

        if data is not None and not isinstance(data, ma.MaskedArray):
            data = ma.MaskedArray(data)

        if traces is not None:
            if len(traces) == 0:
                data = ma.zeros((0, 0))
            else:
                if assemble == 'merge':
                    data, component_codes, tmin, deltat \
                        = trace.merge_traces_data_as_array(traces)

                elif assemble == 'concatenate':
                    data = ma.array(trace.get_traces_data_as_array(traces))
                    component_codes = [tr.codes for tr in traces]
                    tmin = traces[0].tmin
                    deltat = traces[0].deltat

        if nsamples is not None and data is not None \
                and data.shape[1] != nsamples:

            raise ValueError(
                'Carpet construction: mismatch between expected number of '
                'samples and number of samples in data array.')

        if data is None:
            if component_codes is None or nsamples is None:
                raise ValueError(
                    'Dataless Carpet must be constructed with '
                    '`component_codes` ' 'and `nsamples` set.')

            self.ncomponents = len(component_codes)
        else:
            self.ncomponents, nsamples = data.shape

        if component_codes is None:
            component_codes = [CodesNSLCE()] * self.ncomponents

        if len(component_codes) != self.ncomponents:
            raise ValueError(
                'Carpet construction: mismatch between number of traces '
                'and number of component codes given.')

        if deltat is None:
            deltat = self.T.deltat.default()

        if tmin is None:
            tmin = self.T.tmin.default()

        if codes is None:
            codes = CodesNSLCE()

        if component_axes is None:
            component_axes = {}

        Object.__init__(
            self,
            codes=codes,
            component_codes=component_codes,
            component_axes=component_axes,
            data=data,
            tmin=tmin,
            nsamples=nsamples,
            deltat=deltat)

    @property
    def stats(self):
        if self._stats is None:
            self._stats = CarpetStats.make(self.data)

        return self._stats

    @stats.setter
    def stats(self, stats):
        self._stats = stats

    @property
    def summary_component_codes(self):
        if all(codes == EMPTY_CODES for codes in self.component_codes):
            return ''
        elif len(self.component_codes) == 1:
            return str(self.component_codes[0])
        elif len(self.component_codes) == 2:
            return '%s, %s' % (
                self.component_codes[0],
                self.component_codes[-1])
        else:
            return '%s, ..., %s' % (
                self.component_codes[0],
                self.component_codes[-1])

    @property
    def summary_entries(self):
        return (
            self.__class__.__name__,
            str(self.ncomponents),
            str(self.nsamples),
            str(self.data.dtype) if self.data is not None else '<unknown>',
            str(self.deltat),
            util.time_to_str(self.tmin),
            util.time_to_str(self.tmax),
            self.summary_component_codes)

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
        return self.ncomponents

    def __getitem__(self, i):
        '''
        Get single component waveform (shared data).

        :param i:
            Component index.
        :type i:
            int
        '''
        return self.get_trace(i)

    def fill_template(self, template, **additional):
        return template.format_map(
            CarpetStringFiller(self, additional=additional))

    def copy(self, data='copy'):
        '''
        Create a copy

        :param data:
            ``'copy'`` to deeply copy the data, or ``'reference'`` to create
            a shallow copy, referencing the original data, or ``'drop'`` to
            create a dataless copy.
        :type data:
            str
        '''

        if isinstance(data, str):
            if data == 'drop':
                data = None
            elif data == 'copy':
                data = self.data.copy()
            elif data == 'reference':
                data = self.data
            else:
                assert False
        else:
            assert isinstance(data, ma.MaskedArray)

        return Carpet(
            data=data,
            codes=self.codes,
            component_codes=list(self.component_codes),
            component_axes=self.component_axes,
            tmin=self.tmin,
            deltat=self.deltat)

    def chop(self, tmin, tmax, snap=(round, round)):
        istart = int(snap[0]((tmin - self.tmin) / self.deltat))
        iend = int(snap[1]((tmax - self.tmin) / self.deltat))

        istart = max(0, istart)
        iend = min(self.nsamples, iend)
        return Carpet(
            data=self.data[:, istart:iend],
            codes=self.codes,
            component_codes=self.component_codes,
            tmin=self.tmin + istart * self.deltat,
            deltat=self.deltat,
            component_axes=self.component_axes)

    def chopper(self, tinc):
        nwindows = int(num.floor((self.tmax - self.tmin) / tinc)) + 1
        nsamples = int(num.floor(tinc / self.deltat))
        for iwindow in range(nwindows):
            istart = int(num.floor((iwindow * tinc) / self.deltat))
            iend = istart + nsamples
            yield Carpet(
                data=self.data[:, istart:iend],
                codes=self.codes,
                component_codes=self.component_codes,
                tmin=self.tmin + istart * self.deltat,
                deltat=self.deltat,
                component_axes=self.component_axes)

    @property
    def tmax(self):
        '''
        End time (time of last sample, read-only).
        '''
        return self.tmin + (self.nsamples - 1) * self.deltat

    @property
    def times(self):
        return self.tmin + num.arange(self.nsamples) * self.deltat

    def get_trace(self, i, span=slice(None)):
        '''
        Get single component waveform (shared data).

        :param i:
            Component index.
        :type i:
            int
        '''

        network, station, location, channel, extra = self.component_codes[i]
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

    def get_component_axis(self, name=None):
        if name is None:
            return num.arange(self.ncomponents)
        else:
            return self.component_axes[name]

    def mpl_draw(
            self,
            axes,
            component_axis=None,
            fslice=slice(1, None),
            **kwargs):

        if component_axis is None:
            ys = num.arange(self.ncomponents)
        else:
            ys = self.component_axes[component_axis]

        return axes.pcolormesh(
            self.times,
            ys[fslice],
            self.data[fslice, :],
            **kwargs)

    def plot(
            self,
            component_axis=None,
            component_axis_scale='linear',
            fslice=slice(1, None),
            path=None, **kwargs):

        from pyrocko import plot
        import matplotlib.pyplot as plt

        fig = plt.figure(figsize=plot.mpl_papersize('a4', 'landscape'))
        axes = fig.add_subplot(1, 1, 1)
        self.mpl_draw(
            axes,
            component_axis=component_axis,
            fslice=fslice, **kwargs)

        axes.set_yscale(component_axis_scale)

        plot.mpl_time_axis(axes)
        if path is None:
            plt.show()
        else:
            fig.savefig(path)

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

    def reduce(self, f, component_codes):
        data = f(self.data)
        if data.ndim == 1:
            data = data[num.newaxis, :]
        if isinstance(component_codes, CodesNSLCE):
            component_codes = [component_codes]
        assert data.ndim == 2
        assert data.shape[1] == self.data.shape[1]
        assert len(component_codes) == data.shape[0]
        self.component_codes = component_codes
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

    def fold(self, t, method=num.mean):
        nfold = max(1, int(num.round(t / self.deltat)))

        itmin = int(round(self.tmin / self.deltat))
        itmax = itmin + self.nsamples

        ibmin = (((itmin - 1) // nfold) + 1) * nfold
        ibmax = ((itmax - 1) // nfold) * nfold

        ibmin -= itmin
        ibmax -= itmin

        if ibmin >= ibmax:
            raise trace.NoData()

        data = self.data[:, ibmin:ibmax].reshape((
            self.ncomponents,
            (ibmax - ibmin) // nfold,
            nfold))

        data = method(data, axis=2)

        return Carpet(
            data=data,
            codes=self.codes,
            component_axes=self.component_axes,
            component_codes=self.component_codes,
            tmin=self.tmin + self.deltat * ibmin,
            deltat=nfold*self.deltat)

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

    def filter_frequency_cos_taper(self, f1, f2, f3, f4):

        def multiply_taper(frequency_delta, ntrans, spectrum):
            taper = costaper(
                f1, f2, f3, f4, spectrum.shape[1], frequency_delta)
            spectrum *= taper[num.newaxis, :]
            return spectrum

        self.apply_via_fft(
            multiply_taper)

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
        from pyrocko.squirrel import Grouping
        rms = self.get_rms(grouping=Grouping())
        rms.smooth(deltat, window=window)
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

    def get_component_codes_grouped(self, grouping):
        groups = defaultdict(list)
        for irow, component_codes in enumerate(self.component_codes):
            groups[grouping.key(component_codes)].append(irow)

        return groups

    def get_energy(
            self,
            grouping=None,
            translation=ReplaceComponentTranslation(),
            postprocessing=None):

        from pyrocko.squirrel import SensorGrouping

        if grouping is None:
            grouping = SensorGrouping()

        groups = self.get_component_codes_grouped(grouping)

        data = self.data.astype(num.float64)
        data **= 2
        data3 = num.ma.empty((len(groups), self.nsamples))
        component_codes = []
        for irow_out, irows_in in enumerate(groups.values()):
            data3[irow_out, :] = data[irows_in, :].sum(axis=0)
            component_codes.append(CodesNSLCE(
                translation.translate(
                    self.component_codes[irows_in[0]]).safe_str.format(
                        component='G')))

        if data3.mask is ma.nomask:
            data3.mask = ma.make_mask_none(data3.shape)

        data3.mask |= data3.data == 0
        data3.data[data3.mask] = 1.0

        energy = Carpet(
            data=data3,
            codes=self.codes,
            component_codes=component_codes,
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

    def crop(self, fslice=slice(None, None)):
        return Carpet(
            tmin=self.tmin,
            deltat=self.deltat,
            codes=self.codes,
            component_codes=self.component_codes[fslice],
            component_axes=dict(
                (k, v[fslice]) for (k, v) in self.component_axes.items()),
            data=self.data[fslice, :])

    def resample_band(
            self, fmin, fmax, nf,
            registration='cell',
            scale='log',
            component_axis='frequency'):

        if scale == 'log':
            log, exp, condition = num.log, num.exp, lambda y: y > 0
        elif scale == 'lin':
            log, exp, condition = lambda y: y, lambda y: y, lambda y: True
        elif isinstance(scale, tuple):
            log, exp, condition = scale
        else:
            raise ValueError(
                'Carpet.resample_band: Scale must be "lin", "log" or a tuple '
                'with scaling, inverse scaling, and condition functions, e.g. '
                '`(log, exp, lambda y: y > 0)`.')

        frequencies = self.component_axes[component_axis]
        if not num.all(num.diff(frequencies) > 0.0):
            raise ValueError(
                'Carpet.resample_band: Component axis must be monotonically '
                'increasing.')

        iok = num.where(condition(frequencies))[0]

        if iok.size < self.ncomponents:
            if iok.size == 0:
                raise ValueError(
                    'Carpet.resample_band: No elements of component axis meet '
                    'scaling condition (e.g. y > 0 for log scaling)')

            self = self.crop(fslice=slice(iok[0], None))
            frequencies = self.component_axes[component_axis]

        if fmin is None:
            fmin = frequencies[0]

        if fmax is None:
            fmax = frequencies[-1]

        if registration == 'cell':
            log_frequencies_out = num.linspace(
                log(fmin), log(fmax), nf+1)

        elif registration == 'node':
            d_log_f = log(fmin + (fmax - fmin) / nf) - log(fmin)
            log_frequencies_out = num.linspace(
                log(fmin)-0.5*d_log_f,
                log(fmax)+0.5*d_log_f,
                nf+1)

        log_frequencies = log(frequencies)
        iok = num.where(num.logical_and(
            log_frequencies[0] <= log_frequencies_out,
            log_frequencies_out <= log_frequencies[-1]))[0]

        fslice = slice(iok[0], iok[-1]+1)
        fslice_out = slice(iok[0], iok[-1])

        d_log_frequencies_half = num.diff(log_frequencies) * 0.5
        int_values = num.zeros_like(self.data)
        num.cumsum(
            (self.data[1:, :] + self.data[:-1, :])
            * d_log_frequencies_half[:, num.newaxis],
            axis=0,
            out=int_values[1:, :])

        i = num.searchsorted(log_frequencies, log_frequencies_out[fslice])

        w1 = (log_frequencies_out[fslice] - log_frequencies[i-1]) \
            / (log_frequencies[i] - log_frequencies[i-1])

        w0 = 1.0 - w1

        int_values_out = int_values[i-1, :] * w0[:, num.newaxis] \
            + int_values[i, :] * w1[:, num.newaxis]

        values_out = num.full((nf, self.data.shape[1]), num.nan)
        values_out[fslice_out, :] = num.diff(int_values_out, axis=0) \
            / num.diff(log_frequencies_out[fslice])[:, num.newaxis]

        frequencies_out = exp(
            0.5 * (log_frequencies_out[1:] + log_frequencies_out[:-1]))

        return Carpet(
            codes=self.codes,
            tmin=self.tmin,
            deltat=self.deltat,
            component_axes={component_axis: frequencies_out},
            data=values_out)


def correlate(a, b, mode='valid', normalization=None, use_fft=False):

    if isinstance(a, Trace) and isinstance(b, Trace):
        return trace.correlate(
            a, b, mode=mode, normalization=normalization, use_fft=use_fft)

    elif isinstance(a, Trace) and isinstance(b, Carpet):
        return Carpet([
            trace.correlate(
                a, b_,
                mode=mode, normalization=normalization, use_fft=use_fft)
            for b_ in b])

    elif isinstance(a, Carpet) and isinstance(b, Trace):
        return Carpet([
            trace.correlate(
                a_, b,
                mode=mode, normalization=normalization, use_fft=use_fft)
            for a_ in a])

    elif isinstance(a, Carpet) and isinstance(b, Carpet):
        return Carpet([
            trace.correlate(
                a_, b_,
                mode=mode, normalization=normalization, use_fft=use_fft)

            for a_ in a for b_ in b])


def join(carpets):
    if not carpets:
        return []
    eps = 1e-4
    carpets = sorted(carpets, key=lambda carpet: (carpet.codes, carpet.tmin))
    groups = []
    for current in carpets:
        lastgroup = groups[-1] if groups else None
        last = lastgroup[-1] if lastgroup else None
        deltat = current.deltat
        if (last
                and last.deltat == deltat
                and abs(last.tmax + deltat - current.tmin) < eps * deltat
                and last.ncomponents == current.ncomponents
                and all(
                    a == b
                    for (a, b)
                    in zip(last.codes, current.codes))
                and last.data.dtype == current.data.dtype):

            lastgroup.append(current)
        else:
            groups.append([current])

    carpets_out = []
    for group in groups:
        if len(group) > 1:
            data = num.hstack([carpet.data for carpet in group])
            carpets_out.append(group[0].copy(data=data))
        else:
            carpets_out.append(group[0])

    return carpets_out
