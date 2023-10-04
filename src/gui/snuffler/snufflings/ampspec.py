# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from ..snuffling import Snuffling, Param, Switch
import numpy as num
from matplotlib import cm


def window(freqs, fc, b):
    w = num.zeros(len(freqs))
    if fc == 0.:
        w[freqs == 0.0] = 1.
        return w
    mask = num.logical_and(freqs != 0.0, freqs != fc)
    T = num.log10(freqs[mask]/fc)*b
    w[mask] = (num.sin(T)/T)**4
    w[freqs == fc] = 1.
    w /= num.sum(w)
    return w


class AmpSpec(Snuffling):

    def help(self):
        return '''
<html>
<head>
<style type="text/css">
    body { margin-left:10px };
</style>
<body>
<h1 align="center">Plot Amplitude Spectrum</h1>
<p>
When smoothing is activated, a smoothing algorithm is applied as
proposed
by Konno and Ohmachi, (1998). </p>
<p style='font-family:courier'>
    Konno, K. and Omachi, T. (1998). Ground-motion characteristics
    estimated from spectral ratio between horizontal and vertical
    components of microtremor, Bull. Seism. Soc. Am., 88, 228-241
</p>
</body>
</html>
        '''

    def setup(self):
        '''Customization of the snuffling.'''

        self.set_name('Plot Amplitude Spectrum')
        self.add_parameter(Switch('Smoothing', 'want_smoothing', False))
        self.add_parameter(Param('Smoothing band width', 'b', 40., 1., 100.))
        self.set_live_update(False)
        self._wins = {}

    def call(self):
        '''Main work routine of the snuffling.'''

        all = []
        for traces in self.chopper_selected_traces(fallback=True):
            for trace in traces:
                all.append(trace)

        colors = iter(cm.Accent(num.linspace(0., 1., len(all))))
        if self.want_smoothing:
            alpha = 0.2
            additional = 'and smoothing'
        else:
            alpha = 1.
            additional = ''

        flimits = []
        alimits = []
        pblabel = 'Calculating amplitude spectra %s' % additional
        pb = self.get_viewer().parent().get_progressbars()
        pb.set_status(pblabel, 0)
        num_traces = len(all)
        maxval = float(num_traces)
        plot_data = []
        plot_data_supplement = []
        for i_tr, tr in enumerate(all):
            val = i_tr/maxval*100.
            pb.set_status(pblabel, val)

            tr.ydata = tr.ydata.astype(float)
            tr.ydata -= tr.ydata.mean()
            f, a = tr.spectrum()
            flimits.append(f[1])
            flimits.append(f[-1])
            absa = num.abs(a)
            labsa = num.log(absa)
            stdabsa = num.std(labsa)
            meanabsa = num.mean(labsa)
            lamin, lamax = meanabsa - 5*stdabsa, meanabsa + 5*stdabsa
            alimits.append(num.exp(lamin))
            alimits.append(num.exp(lamax))
            c = next(colors)
            plot_data.append((f, num.abs(a)))
            plot_data_supplement.append((c, alpha, '.'.join(tr.nslc_id)))
            if self.want_smoothing:
                smoothed = self.konnoohmachi(num.abs(a), f, self.b)
                plot_data.append((f, num.abs(smoothed)))
                plot_data_supplement.append((c, 1., '.'.join(tr.nslc_id)))
            self.get_viewer().update()

        pb.set_status(pblabel, 100.)

        fig = self.figure(name='Amplitude Spectra')
        p = fig.add_subplot(111)
        args = ('c', 'alpha', 'label')
        for d, s in zip(plot_data, plot_data_supplement):
            p.plot(*d, **dict(zip(args, s)))

        p.set_xscale('log')
        p.set_yscale('log')

        amin, amax = num.min(alimits), num.max(alimits)
        p.set_ylim(amin, amax)

        fmin, fmax = num.min(flimits), num.max(flimits)
        p.set_xlim(fmin, fmax)

        p.set_xlabel('Frequency [Hz]')
        p.set_ylabel('Counts')

        handles, labels = p.get_legend_handles_labels()
        leg_dict = dict(zip(labels, handles))
        if num_traces > 1:
            p.legend(list(leg_dict.values()), list(leg_dict.keys()),
                     loc=2,
                     borderaxespad=0.,
                     bbox_to_anchor=((1.05, 1.)))
            fig.subplots_adjust(right=0.8,
                                left=0.1)
        else:
            p.set_title(list(leg_dict.keys())[0], fontsize=16)
            fig.subplots_adjust(right=0.9,
                                left=0.1)
        fig.canvas.draw()

    def konnoohmachi(self, amps, freqs, b=20):
        smooth = num.zeros(len(freqs), dtype=freqs.dtype)
        amps = num.array(amps)
        for i, fc in enumerate(freqs):
            fkey = tuple((b, fc, freqs[0], freqs[1], freqs[-1]))
            if fkey in self._wins.keys():
                win = self._wins[fkey]
            else:
                win = window(freqs, fc, b)
                self._wins[fkey] = win
            smooth[i] = num.sum(win*amps)

        return smooth


def __snufflings__():
    '''
    Returns a list of snufflings to be exported by this module.
    '''

    return [AmpSpec()]
