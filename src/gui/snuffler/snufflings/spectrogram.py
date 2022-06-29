import math
import logging
import numpy as num
from matplotlib.colors import LinearSegmentedColormap
from matplotlib import cm

from pyrocko import plot, trace
from pyrocko.gui.snuffling import Snuffling, Param, Choice

logger = logging.getLogger('pyrocko.gui.snufflings.spectrogram')


def to01(c):
    return c[0]/255., c[1]/255., c[2]/255.


def desat(c, a):
    cmean = (c[0] + c[1] + c[2]) / 3.
    return tuple(cc*a + cmean*(1.0-a) for cc in c)


name_to_taper = {
    'Hanning': num.hanning,
    'Hamming': num.hamming,
    'Blackman': num.blackman,
    'Bartlett': num.bartlett}

cmap_colors = [plot.tango_colors[x] for x in [
    'skyblue1', 'chameleon1', 'butter1', 'orange1', 'scarletred1', 'plum3']]

name_to_cmap = {
    'spectro': LinearSegmentedColormap.from_list(
        'spectro', [desat(to01(c), 0.8) for c in cmap_colors])}


def get_cmap(name):
    if name in name_to_cmap:
        return name_to_cmap[name]
    else:
        return cm.get_cmap(name)


def downsample_plan(n, n_max):
    n_mean = (n-1) // n_max + 1
    n_new = n // n_mean
    return n_new, n_mean


class Spectrogram(Snuffling):

    '''
    <html>
    <body>
    <h1>Plot spectrogram</h1>
    <p>Plots a basic spectrogram.</p>
    </body>
    </html>
    '''

    def setup(self):
        '''Customization of the snuffling.'''

        self.set_name('Spectrogram')
        self.add_parameter(
            Param('Window length [s]:', 'twin', 100, 0.1, 10000.))

        self.add_parameter(
            Param('Overlap [%]:', 'overlap', 75., 0., 99.))

        self.add_parameter(
            Choice('Taper function', 'taper_name', 'Hanning',
                   ['Hanning', 'Hamming', 'Blackman', 'Bartlett']))

        self.add_parameter(Param(
            'Fmin [Hz]', 'fmin', None, 0.001, 50.,
            low_is_none=True))

        self.add_parameter(Param(
            'Fmax [Hz]', 'fmax', None, 0.001, 50.,
            high_is_none=True))

        self.add_parameter(
            Choice('Color scale', 'color_scale', 'log',
                   ['log', 'sqrt', 'lin']))

        self.add_parameter(
            Choice('Color table', 'ctb_name', 'spectro',
                   ['spectro', 'rainbow']))

        self.set_live_update(False)
        self._tapers = {}
        self.nt_max = 2000
        self.nf_max = 500
        self.iframe = 0

    def get_taper(self, name, n):

        taper_key = (name, n)

        if taper_key not in self._tapers:
            self._tapers[taper_key] = name_to_taper[name](n)

        return self._tapers[taper_key]

    def make_spectrogram(self, tmin, tmax, tinc, tpad, nslc, deltat):

        nt = int(round((tmax - tmin) / tinc))

        nsamples_want = int(
            math.floor((tinc + 2*tpad) / deltat))

        nsamples_want_pad = trace.nextpow2(nsamples_want)
        nf = nsamples_want_pad // 2 + 1
        df = 1.0 / (deltat * nsamples_want_pad)

        if self.fmin is not None:
            ifmin = int(math.ceil(self.fmin / df))
        else:
            ifmin = 0

        if self.fmax is not None:
            ifmax = int(math.floor(self.fmax / df)) + 1
        else:
            ifmax = nf

        nf_show = ifmax - ifmin
        assert nf_show >= 2

        nf_show_ds, nf_mean = downsample_plan(nf_show, self.nf_max)

        amps = num.zeros((nf_show_ds, nt))
        amps.fill(num.nan)

        win = self.get_taper(self.taper_name, nsamples_want)

        for batch in self.chopper_selected_traces(
                tinc=tinc,
                tpad=tpad+deltat,
                want_incomplete=False,
                fallback=True,
                trace_selector=lambda tr: tr.nslc_id == nslc,
                mode='inview',
                style='batch',
                progress='Calculating Spectrogram'):

            for tr in batch.traces:
                if tr.deltat != deltat:
                    self.fail(
                        'Unexpected sampling rate on channel %s.%s.%s.%s: %g'
                        % (tr.nslc_id + (tr.deltat,)))

            trs = batch.traces

            if len(trs) != 1:
                continue

            tr = trs[0]

            if deltat is None:
                deltat = tr.deltat

            else:
                if tr.deltat != deltat:
                    raise Exception('Unexpected sampling rate.')

            tr.chop(tmin - tpad, tr.tmax, inplace=True)
            tr.set_ydata(tr.ydata[:nsamples_want])

            if tr.data_len() != nsamples_want:
                logger.info('incomplete trace')
                continue

            tr.ydata = tr.ydata.astype(num.float64)
            tr.ydata -= tr.ydata.mean()

            tr.ydata *= win

            f, a = tr.spectrum(pad_to_pow2=True)
            assert nf == f.size
            assert (nf-1)*df == f[-1]

            f = f[ifmin:ifmax]
            a = a[ifmin:ifmax]

            a = num.abs(a)
            # a /= self.cached_abs_response(sq.get_response(tr), f)

            a **= 2
            a *= tr.deltat * 2. / (df*num.sum(win**2))

            if nf_mean != 1:
                nf_trim = (nf_show // nf_mean) * nf_mean
                f = num.mean(f[:nf_trim].reshape((-1, nf_mean)), axis=1)
                a = num.mean(a[:nf_trim].reshape((-1, nf_mean)), axis=1)

            tmid = 0.5*(tr.tmax + tr.tmin)

            it = int(round((tmid-tmin)/tinc))
            if it < 0 or nt <= it:
                continue

            amps[:, it] = a
            have_data = True

        if not have_data:
            self.fail(
                'No data could be extracted for channel: %s.%s.%s.%s' % nslc)

        t = tmin + 0.5 * tinc + tinc * num.arange(nt)
        return t, f, amps

    def get_selected_time_range(self):
        markers = self.get_viewer().selected_markers()
        times = []
        for marker in markers:
            times.append(marker.tmin)
            times.append(marker.tmax)

        if times:
            return (min(times), max(times))
        else:
            return self.get_viewer().get_time_range()

    def prescan(self, tinc, tpad):

        tmin, tmax = self.get_selected_time_range()
        nt = int(round((tmax - tmin) / tinc))
        if nt > self.nt_max:
            _, nt_mean = downsample_plan(nt, self.nt_max)
            self.fail(
                'Number of samples in spectrogram time axis: %i. Resulting '
                'image will be unreasonably large. Consider increasing window '
                'length to about %g s.' % (
                    nt, (tinc*nt_mean) / (1.-self.overlap/100.)))

        data = {}
        times = []
        for batch in self.chopper_selected_traces(
                tinc=tinc, tpad=tpad, want_incomplete=False, fallback=True,
                load_data=False, mode='inview', style='batch'):

            times.append(batch.tmin)
            times.append(batch.tmax)

            for tr in batch.traces:
                nslc = tr.nslc_id
                if nslc not in data:
                    data[nslc] = set()

                data[nslc].add(tr.deltat)

        nslcs = sorted(data.keys())
        deltats = [sorted(data[nslc]) for nslc in nslcs]
        return min(times), max(times), nslcs, deltats

    def call(self):
        '''Main work routine of the snuffling.'''

        tpad = self.twin * self.overlap/100. * 0.5
        tinc = self.twin - 2 * tpad

        tmin, tmax, nslcs, deltats = self.prescan(tinc, tpad)

        for nslc, deltats in zip(nslcs, deltats):
            if len(deltats) > 1:
                self.fail(
                    'Multiple sample rates found for channel %s.%s.%s.%s.'
                    % nslc)

        ncols = int(len(nslcs) // 5 + 1)
        nrows = (len(nslcs)-1) // ncols + 1

        frame = self.smartplot_frame(
            'Spectrogram %i' % (self.iframe + 1),
            ['time'] * ncols,
            ['frequency'] * nrows,
            ['psd'])

        self.iframe += 1

        zvalues = []
        for i, nslc in enumerate(nslcs):

            t, f, a = self.make_spectrogram(
                tmin, tmax, tinc, tpad, nslc, deltats[0])

            if self.color_scale == 'log':
                a = num.log(a)
            elif self.color_scale == 'sqrt':
                a = num.sqrt(a)

            icol, irow = i % ncols, i // ncols

            axes = frame.plot.axes(icol, nrows-1-irow)

            min_a = num.nanmin(a)
            max_a = num.nanmax(a)
            mean_a = num.nanmean(a)
            std_a = num.nanstd(a)

            zmin = max(min_a, mean_a - 3.0 * std_a)
            zmax = min(max_a, mean_a + 3.0 * std_a)

            zvalues.append(zmin)
            zvalues.append(zmax)

            c = axes.pcolormesh(
                t, f, a,
                cmap=get_cmap(self.ctb_name),
                shading='gouraud')
            frame.plot.set_color_dim(c, 'psd')

            if self.fmin is not None:
                fmin = self.fmin
            else:
                fmin = 2.0 / self.twin

            if self.fmax is not None:
                fmax = self.fmax
            else:
                fmax = f[-1]

            axes.set_title(
                '.'.join(x for x in nslc if x),
                ha='right',
                va='top',
                x=0.99,
                y=0.9)

            axes.grid(color='black', alpha=0.3)

            plot.mpl_time_axis(axes, 10. / ncols)

        for i in range(len(nslcs), ncols*nrows):
            icol, irow = i % ncols, i // ncols
            axes = frame.plot.axes(icol, nrows-1-irow)
            axes.set_axis_off()

        if self.color_scale == 'log':
            label = 'log PSD'
        elif self.color_scale == 'sqrt':
            label = 'sqrt PSD'
        else:
            label = 'PSD'

        frame.plot.set_label('psd', label)
        frame.plot.colorbar('psd')
        frame.plot.set_lim('time', t[0], t[-1])
        frame.plot.set_lim('frequency', fmin, fmax)
        frame.plot.set_lim('psd', min(zvalues), max(zvalues))
        frame.plot.set_label('time', '')
        frame.plot.set_label('frequency', 'Frequency [Hz]')

        frame.draw()


def __snufflings__():
    '''Returns a list of snufflings to be exported by this module.'''
    return [Spectrogram()]
