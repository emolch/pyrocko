import logging
import math
import hashlib
from functools import cache

import numpy as num

import matplotlib.pyplot as plt

from pyrocko import util, guts, guts_array, plot
from pyrocko.squirrel import model, error
from . import base

logger = logging.getLogger('psq.ops.spectrogram')


def is_pow2(x):
    return round(math.log(x) / math.log(2.0), 7) % 1.0 == 0.0


def antialiasing_taper(n, corner=0.9):
    h = num.ones(n)
    f = num.arange(n) / (n-1)
    mask = f > corner
    h[mask] *= (0.5 + 0.5 * num.cos(
        (f[mask] - corner) / (1.0 - corner) * num.pi))**2
    # h[mask] = 0.0
    return h


def cos_taper(x):
    return 0.5 - 0.5 * num.cos(x)


class Pow2Windowing(guts.Object):
    nblock = guts.Int.T(default=1024)
    nlevels = guts.Int.T(default=4)
    weighting_exponent = guts.Int.T(default=2)

    def __init__(self, **kwargs):
        guts.Object.__init__(self, **kwargs)
        if not is_pow2(self.nblock):
            raise ValueError(
                'Pow2Windowing: `nblock` must be a power of 2.')

        self.nfrequencies = self.nblock // 2 + 1
        self.taper_td = num.hanning(self.nblock)
        self.taper_fd_2 = antialiasing_taper(self.nfrequencies // 2 + 1, 0.9)
        self.taper_td_2_inv_center = 1.0 \
            / num.hanning(self.nblock // 2)[
                self.nblock // 8: 3 * self.nblock // 8]

    def hash(self):
        return hashlib.sha256(b'%i,%i' % (self.nblock, self.nlevels))

    def time_increment(self, deltat, ilevel=0):
        if ilevel < 0:
            ilevel = self.nlevels + ilevel

        if not (0 <= ilevel < self.nlevels):
            raise ValueError(
                'Pow2Windowing: invalid `ilevel`: %i' % ilevel)

        return deltat * (self.nblock // 2) * 2**ilevel

    def time_min(self, deltat, tmin):
        tinc = self.time_increment(deltat, -1)
        return math.floor(tmin / tinc) * tinc

    def time_max(self, deltat, tmax):
        tinc = self.time_increment(deltat, -1)
        return math.ceil(tmax / tinc) * tinc

    def iwindow_range(self, deltat, tmin, tmax, ilevel):
        tinc = self.time_increment(deltat, ilevel)
        imin = int(math.floor(tmin / tinc))
        imax = int(math.ceil(tmax / tinc))
        return num.arange(imin, imax+1)

    def frequencies_and_weights(self, deltat):
        eps1 = 1e-4
        eps2 = 1e-7
        nfrequencies = self.nfrequencies
        nfrequencies_all \
            = nfrequencies + nfrequencies // 2 * (self.nlevels - 1)

        frequencies_all = num.zeros(nfrequencies_all)
        ifmin = 0
        for ilevel in range(self.nlevels-1, -1, -1):
            if ilevel == self.nlevels-1:
                ifmax = ifmin + nfrequencies
                fmin_fill = 0.0
            else:
                ifmax = ifmin + nfrequencies // 2
                df = 1.0 / (deltat*self.nblock * 2**ilevel)
                fmin_fill = df * ((nfrequencies // 2) + 1)

            fmax = (0.5 / deltat) / 2**ilevel
            frequencies_all[ifmin:ifmax] = num.linspace(
                fmin_fill, fmax, ifmax - ifmin)

            ifmin = ifmax

        log_frequencies_all = num.zeros_like(frequencies_all)
        log_frequencies_all[1:] = num.log(frequencies_all[1:])

        norm_log_frequencies_all = \
            (log_frequencies_all[1:] - log_frequencies_all[1]) \
            / (log_frequencies_all[-1] - log_frequencies_all[1])

        weights = num.zeros((self.nlevels, frequencies_all.size))
        for ilevel in range(self.nlevels):
            fmin = 1.0 / (deltat*self.nblock * 2**ilevel)
            fmax = (0.5 / deltat) / 2**ilevel
            fmask = num.logical_and(
                fmin < frequencies_all, frequencies_all < fmax)

            # weights[ilevel, fmask] = cos_taper(
            #     num.sqrt((frequencies_all[fmask] - fmin) / (fmax - fmin))
            #     * 2.0 * num.pi)** self.weighting_exponent

            weights[ilevel, fmask] = cos_taper(
                (log_frequencies_all[fmask] - num.log(fmin))
                / (num.log(fmax) - num.log(fmin)) * 2.0 * num.pi) \
                ** self.weighting_exponent

            if ilevel == 0:
                weights[ilevel, 1:] += cos_taper(
                    norm_log_frequencies_all*num.pi)**2 * eps1

            if ilevel == self.nlevels - 1:
                weights[ilevel, 1:] += cos_taper(
                    (1.0 - norm_log_frequencies_all)*num.pi)**2 * eps1

        weights += eps2
        weights /= num.sum(weights, axis=0)[num.newaxis, :]

        return frequencies_all, weights


def make_block(ilevel, windowing, samples_td):
    taper_td = windowing.taper_td
    taper_fd_2 = windowing.taper_fd_2
    taper_td_2_inv_center = windowing.taper_td_2_inv_center
    nblock = windowing.nblock
    dmean = num.mean(samples_td*taper_td)
    samples_fd = num.fft.rfft((samples_td-dmean) * taper_td)
    nf = samples_fd.size
    samples_td_2 = num.fft.irfft(samples_fd[:nf//2 + 1] * taper_fd_2) / 2
    samples_td_2_center = samples_td_2[nblock//8:3*nblock//8]
    samples_td_2_center *= taper_td_2_inv_center
    samples_td_2_center += dmean
    samples_out = num.abs(samples_fd)
    num.log(samples_out, out=samples_out)
    samples_out *= 2.0  # power-spectrum
    samples_out += num.log(2**ilevel)
    return (samples_out, samples_td_2_center)


class Stats(guts.Object):
    min = guts.Float.T()
    p10 = guts.Float.T()
    median = guts.Float.T()
    p90 = guts.Float.T()
    max = guts.Float.T()

    @classmethod
    def make(cls, data):
        min, p10, median, p90, max = num.nanpercentile(
            data, [0., 10., 50., 90., 100.])

        return cls(min=min, p10=p10, median=median, p90=p90, max=max)


class Spectrogram(guts.Object):

    times = guts_array.Array.T(
        serialize_as='npy',
        shape=(None,))

    frequencies = guts_array.Array.T(
        serialize_as='npy',
        shape=(None,))

    values = guts_array.Array.T(
        serialize_as='npy',
        shape=(None, None))

    stats__ = Stats.T(optional=True)

    def post_init(self):
        if self.values.shape != (self.times.size, self.frequencies.size):
            raise guts.ValidationError(
                'Shape mismatch: size(times) = %i, size(frequencies) = %i, '
                'shape(values) = (%i, %i), but should be (%i, %i)' % (
                    (self.times.size, self.frequencies.size)
                    + self.values.shape
                    + (self.times.size, self.frequencies.size)))

        self._stats = None

    @property
    def stats(self):
        if self._stats is None:
            self._stats = Stats.make(self.values)

        return self._stats

    @stats.setter
    def stats(self, stats):
        self._stats = stats

    def mpl_draw(self, axes, fslice=slice(1, None), **kwargs):
        return axes.pcolormesh(
            self.times,
            self.frequencies[fslice],
            self.values[:, fslice].T,
            **kwargs)

    def plot(self, fslice=slice(1, None), **kwargs):
        fig = plt.figure(figsize=(60, 20))
        axes = fig.add_subplot(1, 1, 1)
        self.mpl_draw(axes, fslice=fslice, **kwargs)
        plot.mpl_time_axis(axes)
        plt.show()

    def crop(self, tslice=slice(None, None), fslice=slice(None, None)):
        return Spectrogram(
            times=self.times[tslice],
            frequencies=self.frequencies[fslice],
            values=self.values[tslice, fslice])

    def resample_band(self, fmin, fmax, nf, registration='cell'):

        if registration == 'cell':
            log_frequencies_out = num.linspace(
                num.log(fmin), num.log(fmax), nf+1)

        elif registration == 'node':
            d_log_f = num.log(fmin + (fmax - fmin) / nf) - num.log(fmin)
            log_frequencies_out = num.linspace(
                num.log(fmin)-0.5*d_log_f,
                num.log(fmax)+0.5*d_log_f,
                nf+1)

        log_frequencies = num.log(self.frequencies)
        iok = num.where(num.logical_and(
            log_frequencies[0] <= log_frequencies_out,
            log_frequencies_out <= log_frequencies[-1]))[0]

        fslice = slice(iok[0], iok[-1]+1)
        fslice_out = slice(iok[0], iok[-1])
        print(fslice, fslice_out)

        d_log_frequencies_half = num.diff(log_frequencies) * 0.5
        int_values = num.zeros_like(self.values)
        num.cumsum(
            (self.values[:, 1:] + self.values[:, :-1])
            * d_log_frequencies_half[num.newaxis, :],
            axis=1,
            out=int_values[:, 1:])

        i = num.searchsorted(log_frequencies, log_frequencies_out[fslice])

        w1 = (log_frequencies_out[fslice] - log_frequencies[i-1]) \
            / (log_frequencies[i] - log_frequencies[i-1])

        w0 = 1.0 - w1

        int_values_out = int_values[:, i-1] * w0[num.newaxis, :] \
            + int_values[:, i] * w1[num.newaxis, :]

        values_out = num.full((self.values.shape[0], nf), num.nan)
        values_out[:, fslice_out] = num.diff(int_values_out, axis=1) \
            / num.diff(log_frequencies_out[fslice])[num.newaxis, :]

        frequencies_out = num.exp(
            0.5 * (log_frequencies_out[1:] + log_frequencies_out[:-1]))

        return Spectrogram(
            times=self.times,
            frequencies=frequencies_out,
            values=values_out)


class SpectrogramGroup(guts.Object):
    codes = model.CodesNSLCE.T()
    tmin = guts.Timestamp.T()
    tmax = guts.Timestamp.T()
    deltat = guts.Float.T()
    windowing = Pow2Windowing.T()
    levels = guts.List.T(Spectrogram.T())

    def get_multi_spectrogram(self):
        frequencies, weights = self.windowing.frequencies_and_weights(
            self.deltat)

        times = self.levels[0].times
        spectrogram = num.zeros((times.size, frequencies.size))
        nfcut = frequencies.size

        for ilevel, level in enumerate(self.levels):
            index_f = num.floor(
                frequencies[:nfcut]
                / level.frequencies[1]).astype(int)

            if False:
                index_t = num.round((
                    times - level.times[0])
                    / (level.times[1] - level.times[0])).astype(int)

                spectrogram[:, :nfcut] \
                    += level.values[index_t][:, index_f] \
                    * weights[ilevel, :nfcut][num.newaxis, :]

            else:
                deltat = level.times[1] - level.times[0]
                index_t = num.clip(
                    num.floor((times - level.times[0]) / deltat).astype(int),
                    0, times.size-2)

                w1 = cos_taper(
                    num.pi * (times - level.times[index_t])
                    / (level.times[index_t+1] - level.times[index_t]))

                print(num.min(w1), num.max(w1))
                w0 = 1.0 - w1

                spectrogram[:, :nfcut] \
                    += w0[:, num.newaxis] \
                    * level.values[index_t][:, index_f] \
                    * weights[ilevel, :nfcut][num.newaxis, :]

                spectrogram[:, :nfcut] \
                    += w1[:, num.newaxis] \
                    * level.values[index_t+1][:, index_f] \
                    * weights[ilevel, :nfcut][num.newaxis, :]

            nfcut -= self.windowing.nfrequencies // 2

        return Spectrogram(
            times=times,
            frequencies=frequencies,
            values=spectrogram)

    def get_frequency_range(self):
        return (
            1.0 / (self.deltat * self.windowing.nblock * 2**(
                self.windowing.nlevels-1)),
            0.5 / self.deltat)

    def fill_template(self, path):
        return path.format(
            codes=self.codes.safe_str,
            tmin=util.time_to_str(self.tmin, '%Y-%m-%dT%H-%M-%S'),
            tmax=util.time_to_str(self.tmax, '%Y-%m-%dT%H-%M-%S'))

    def plot_construction(
            self,
            path='spectrogram_{codes}_{tmin}_{tmax}_construction.png'):

        fig = plt.figure(figsize=(60, 20))
        axes_over = fig.add_subplot(3, 1, 2)
        axes_over.set_xscale('log')

        fslice = slice(2, None)
        levels = [
            level.crop(fslice=fslice)
            for level in self.levels]

        vmin = min(level.stats.p10 for level in levels)
        vmax = max(level.stats.max for level in levels)

        for ilevel, level in enumerate(levels):

            axes = fig.add_subplot(3, self.windowing.nlevels + 1, ilevel+1)
            level.mpl_draw(axes, vmin=vmin, vmax=vmax)
            axes.set_ylim(*self.get_frequency_range())
            plot.mpl_time_axis(axes)
            axes.set_yscale('log')

            mean_amps = num.mean(level.values, axis=0)
            axes_over.plot(level.frequencies, mean_amps)

        spectrogram = self.get_multi_spectrogram() \
            .crop(fslice=fslice)

        axes = fig.add_subplot(
            3, self.windowing.nlevels + 1, self.windowing.nlevels + 1)
        spectrogram.mpl_draw(axes, vmin=vmin, vmax=vmax)
        axes.set_ylim(*self.get_frequency_range())
        plot.mpl_time_axis(axes)
        axes.set_yscale('log')

        mean_amps = num.mean(spectrogram.values, axis=0)
        axes_over.plot(
            spectrogram.frequencies,
            mean_amps, color='black', zorder=10)

        frequencies, weights = self.windowing.frequencies_and_weights(
            self.deltat)

        axes_weights = fig.add_subplot(3, 1, 3)
        axes_weights.set_xscale('log')

        for ilevel in range(self.windowing.nlevels):
            axes_weights.plot(
                frequencies[fslice], weights[ilevel, fslice])

        axes_weights.plot(
            frequencies[fslice], num.sum(weights, axis=0)[fslice])

        fig.savefig(self.fill_template(path))


class MultiSpectrogramOperator(base.Operator):

    windowing = Pow2Windowing.T()
    restitute = guts.Bool.T(default=True)

    @property
    def kind_requires(self):
        return ('waveform', 'response')

    @cache
    def get_block(self, deltat, kind_codes_id, ilevel, iwindow):

        if ilevel == 0:
            tmin_window = iwindow * self.windowing.time_increment(
                deltat, ilevel)
            tmax_window = tmin_window + self.windowing.nblock * deltat

            trs = self._input.get_waveforms(
                tmin=tmin_window,
                tmax=tmax_window,
                kind_codes_ids=[kind_codes_id],
                want_incomplete=False)

            ntraces = len(trs)
            assert ntraces <= 1
            if ntraces:
                tr = trs[0]
                nblock = self.windowing.nblock
                assert tr.ydata.size == nblock
                return make_block(ilevel, self.windowing, tr.ydata)

            else:
                return make_block(
                    ilevel, self.windowing, num.zeros(self.windowing.nblock))

        else:

            blocks = [
                self.get_block(deltat, kind_codes_id, ilevel - 1, iwin)
                for iwin in range(iwindow*2-1, iwindow*2+4)]

            nblock = self.windowing.nblock

            samples = num.concatenate(
                [blocks[0][1][nblock//8:]]
                + [block[1] for block in blocks[1:4]]
                + [blocks[-1][1][:-nblock//8]])

            return make_block(ilevel, self.windowing, samples)

    def get_spectrogram_groups(
            self,
            obj=None,
            tmin=None,
            tmax=None,
            codes=None,
            nsamples_limit=None,
            **kwargs):

        tmin, tmax, codes = model.get_selection_args(
            model.CHANNEL, obj, tmin, tmax, None, codes)

        if None in (tmin, tmax):
            raise ValueError('No time span given.')

        info = self._input.get_codes_info('waveform', codes=codes)
        groups = []

        for pattern, kind_codes_id, codes, deltat in info:
            nsamples_required = int(round((tmax - tmin) / deltat))
            if nsamples_limit is not None \
                    and nsamples_required > nsamples_limit:
                print('skipped')
                continue

            if self.restitute:
                try:
                    resp = self._input \
                        .get_response(codes=codes, tmin=tmin, tmax=tmax) \
                        .get_effective('velocity')

                except error.SquirrelError as e:
                    logger.error(e)
                    continue

            levels = []
            for ilevel in range(self.windowing.nlevels):
                iwindows = self.windowing.iwindow_range(
                    deltat, tmin, tmax, ilevel)

                nwindows = iwindows.size
                nfrequencies = self.windowing.nfrequencies
                values = num.zeros(
                    (nwindows, nfrequencies))

                for i in range(nwindows):
                    values[i, :] = self.get_block(
                        deltat, kind_codes_id, ilevel, iwindows[i])[0]

                times = (0.5 + iwindows) \
                    * self.windowing.time_increment(deltat, ilevel)

                frequency_delta = 1.0 \
                    / (deltat * self.windowing.nblock * 2**ilevel)

                frequencies = num.arange(nfrequencies) * frequency_delta

                if self.restitute:
                    values[:, 1:] -= 2.0 * num.log(num.abs(resp.evaluate(
                        frequencies[1:])))[num.newaxis, :]

                levels.append(Spectrogram(
                    times=times,
                    frequencies=frequencies,
                    values=values))

            groups.append(SpectrogramGroup(
                codes=codes,
                tmin=tmin,
                tmax=tmax,
                deltat=deltat,
                windowing=self.windowing,
                levels=levels))

        return groups


__all__ = [
    'Pow2Windowing',
    'Spectrogram',
    'SpectrogramGroup',
    'MultiSpectrogramOperator',
]
