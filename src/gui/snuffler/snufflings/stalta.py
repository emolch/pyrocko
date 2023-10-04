# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from ..snuffling import Param, Snuffling, Switch, Choice
from ..marker import Marker
from pyrocko import trace

h = 3600.

scalingmethods = ('[0-1]', '[-1/ratio,1]', '[-1/ratio,1] clipped to [0,1]')
scalingmethod_map = dict([(m, i+1) for (i, m) in enumerate(scalingmethods)])


class DetectorSTALTA(Snuffling):

    def help(self):
        return '''
<html>
<head>
<style type="text/css">
    body { margin-left:10px };
</style>
</head>
<body>
<h1 align="center">STA/LTA</h1>
<p>
Detect onsets automatically using the Short-Time-Average/Long-Time-Average
ratio.<br/>
This snuffling uses the method:
<a href="http://emolch.github.io/pyrocko/v0.3/trace.html#pyrocko.trace.\
Trace.sta_lta_centered" style="text-decoration:none">
    <pre>pyrocko.trace.Trace.sta_lta_centered</pre>
</a></p>
<p>
<b>Parameters:</b><br />
    <b>&middot; Highpass [Hz]</b>
        - Apply high pass filter before analysing.<br />
    <b>&middot; Lowpass [Hz]</b>
        - Apply low pass filter before analysing.<br />
    <b>&middot; Short Window [s]</b>
        -  Window length of the short window.<br />
    <b>&middot; Ratio</b>
        -  Long window length is the short window length times the
           <b>Ratio</b>.<br />
    <b>&middot; Level</b>
        -  Define a trigger threshold. A marker is added where STA/LTA
           ratios exceed this threshold. <br />
    <b>&middot; Processing Block length</b>
        -  Subdivide dataset in blocks for analysis. <br />
    <b>&middot; Show trigger level traces </b>
        -  Add level traces showing the STA/LTA ration for each
           trace.<br />
    <b>&middot; Apply to full dataset</b>
        -  If marked entire loaded dataset will be analyzed. <br />
    <b>&middot; Scaling/Normalization method</b>
        -  Select how output of the STA/LTA should be scaled.</ br>
</p>
<p>
A helpfull description of how to tune the STA/LTA's parameters can be found
in the the following ebook chapter by Amadej Trnkoczy: <a
href="http://ebooks.gfz-potsdam.de/pubman/item/escidoc:4097:3/component/\
escidoc:4098/IS_8.1_rev1.pdf">Understanding
and parameter setting of STA/LTA trigger algorithm</a>
</p>
</body>
</html>
'''

    def setup(self):

        self.set_name('STA LTA Detector')

        self.add_parameter(Param(
            'Highpass [Hz]', 'highpass', None, 0.001, 1000.,
            low_is_none=True))

        self.add_parameter(Param(
            'Lowpass [Hz]', 'lowpass', None, 0.001, 1000.,
            high_is_none=True))

        self.add_parameter(Param(
            'Short Window [s]', 'swin', 30., 0.01, 2*h))
        self.add_parameter(Param(
            'Ratio',  'ratio', 3., 1.1, 20.))
        self.add_parameter(Param(
            'Level', 'level', 0.5, 0., 1.))
        self.add_parameter(Switch(
            'Show trigger level traces', 'show_level_traces', False))
        self.add_parameter(Choice(
            'Variant', 'variant', 'centered', ['centered', 'right']))
        self.add_parameter(Choice(
            'Scaling/Normalization method', 'scalingmethod', '[0-1]',
            scalingmethods))
        self.add_parameter(
            Switch('Detect on sum trace', 'apply_to_sum', False))

        self.add_trigger(
            'Copy passband from Main', self.copy_passband)

        self.set_live_update(False)

    def panel_visibility_changed(self, visible):
        viewer = self.get_viewer()
        if visible:
            viewer.pile_has_changed_signal.connect(self.adjust_controls)
            self.adjust_controls()

        else:
            viewer.pile_has_changed_signal.disconnect(self.adjust_controls)

    def adjust_controls(self):
        viewer = self.get_viewer()
        dtmin, dtmax = viewer.content_deltat_range()
        maxfreq = 0.5/dtmin
        minfreq = (0.5/dtmax)*0.001
        self.set_parameter_range('lowpass', minfreq, maxfreq)
        self.set_parameter_range('highpass', minfreq, maxfreq)

    def copy_passband(self):
        viewer = self.get_viewer()
        self.set_parameter('lowpass', viewer.lowpass)
        self.set_parameter('highpass', viewer.highpass)

    def call(self):
        '''
        Main work routine of the snuffling.
        '''

        self.cleanup()

        swin, ratio = self.swin, self.ratio
        lwin = swin * ratio
        tpad = lwin

        data_pile = self.get_pile()

        viewer = self.get_viewer()
        deltat_min = viewer.content_deltat_range()[0]

        tinc = max(lwin * 2., 500000. * deltat_min)

        show_level_traces = self.show_level_traces

        nsamples_added = [0]

        def update_sample_count(traces):
            for tr in traces:
                nsamples_added[0] += tr.data_len()

        markers = []

        for batch in self.chopper_selected_traces(
                tinc=tinc, tpad=tpad,
                want_incomplete=False,
                fallback=True,
                style='batch',
                mode='visible',
                progress='Calculating STA/LTA',
                responsive=True,
                marker_selector=lambda marker: marker.tmin != marker.tmax,
                trace_selector=lambda x: not (x.meta and x.meta.get(
                    'tabu', False))):

            sumtrace = None
            isum = 0
            for tr in batch.traces:
                if self.lowpass is not None:
                    tr.lowpass(4, self.lowpass, nyquist_exception=True)

                if self.highpass is not None:
                    tr.highpass(4, self.highpass, nyquist_exception=True)

                sta_lta = {
                    'centered': tr.sta_lta_centered,
                    'right': tr.sta_lta_right}[self.variant]

                sta_lta(
                    swin, lwin,
                    scalingmethod=scalingmethod_map[self.scalingmethod])

                tr.chop(batch.tmin, batch.tmax)

                if not self.apply_to_sum:
                    markers.extend(trace_to_pmarkers(tr, self.level, swin))

                tr.set_codes(location='cg')
                tr.meta = {'tabu': True}

                if sumtrace is None:
                    ny = int((tr.tmax - tr.tmin) / data_pile.deltatmin)
                    sumtrace = trace.Trace(
                        deltat=data_pile.deltatmin,
                        tmin=tr.tmin,
                        ydata=num.zeros(ny))

                    sumtrace.set_codes(
                        network='', station='SUM',
                        location='cg', channel='')

                    sumtrace.meta = {'tabu': True}

                sumtrace.add(tr, left=None, right=None)
                isum += 1

            if sumtrace is not None:
                sumtrace.ydata /= float(isum)
                if self.apply_to_sum:
                    markers.extend(
                        trace_to_pmarkers(sumtrace, self.level, swin,
                                          [('*', '*', '*', '*')]))

                if show_level_traces:
                    update_sample_count([sumtrace])
                    self.add_trace(sumtrace)

            self.add_markers(markers)
            markers = []

            if show_level_traces:
                update_sample_count(batch.traces)
                self.add_traces(batch.traces)

            if show_level_traces and nsamples_added[0] > 10000000:
                self.error(
                    'Limit reached. Turning off further display of level '
                    'traces to prevent memory exhaustion.')

                show_level_traces = False


def trace_to_pmarkers(tr, level, swin, nslc_ids=None):
    markers = []
    tpeaks, apeaks = tr.peaks(level, swin)
    for t, a in zip(tpeaks, apeaks):
        ids = nslc_ids or [tr.nslc_id]
        mark = Marker(ids, t, t, )
        print(mark, a)
        markers.append(mark)

    return markers


def __snufflings__():
    return [DetectorSTALTA()]
