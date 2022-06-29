# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

from pyrocko.gui.snuffler import snuffling as sn
from pyrocko import obspy_compat as oc


class ObsPyStreamSnuffling(sn.Snuffling):
    '''
    Snuffling to fiddle with an ObsPy stream.
    '''

    def __init__(self, obspy_stream=None, *args, **kwargs):
        sn.Snuffling.__init__(self, *args, **kwargs)
        self.obspy_stream_orig = obspy_stream
        self.obspy_stream = obspy_stream.copy()

    def setup(self):
        self.set_name('ObsPy Stream Fiddler')

        if len(self.obspy_stream_orig) != 0:
            fmax = 0.5/min(
                tr.stats.delta for tr in self.obspy_stream_orig)
            fmin = fmax / 1000.
        else:
            fmin = 0.001
            fmax = 1000.

        self.add_parameter(
            sn.Param(
                'Highpass', 'highpass_corner', None, fmin, fmax,
                low_is_none=True))
        self.add_parameter(
            sn.Param(
                'Lowpass', 'lowpass_corner', None, fmin, fmax,
                high_is_none=True))

    def init_gui(self, *args, **kwargs):
        sn.Snuffling.init_gui(self, *args, **kwargs)
        pyrocko_traces = oc.to_pyrocko_traces(self.obspy_stream_orig)
        self.add_traces(pyrocko_traces)

    def call(self):
        try:
            obspy_stream = self.obspy_stream_orig.copy()
            if None not in (self.highpass_corner, self.lowpass_corner):
                obspy_stream.filter(
                    'bandpass',
                    freqmin=self.highpass_corner,
                    freqmax=self.lowpass_corner)

            elif self.lowpass_corner is not None:
                obspy_stream.filter(
                    'lowpass',
                    freq=self.lowpass_corner)

            elif self.highpass_corner is not None:
                obspy_stream.filter(
                    'highpass',
                    freq=self.highpass_corner)

            self.cleanup()
            pyrocko_traces = oc.to_pyrocko_traces(obspy_stream)
            self.add_traces(pyrocko_traces)
            self.obspy_stream = obspy_stream

        except Exception:
            raise  # logged by caller

    def get_obspy_stream(self):
        return self.obspy_stream
