from typing import cast
import numpy as num
from ..snuffling import Param, Snuffling, Switch, Choice
from ..marker import Marker
from pyrocko.pile import Batch
from pyrocko.util import str_to_time
from obspy import Stream
from pyrocko import obspy_compat as compat
from pyrocko.trace import Trace

# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

h = 3600.

detectionmethods = ('ethz', 'instance', 'scedc', 'stead', 'geofon', 'neic')


class DeepDetector(Snuffling):
    def help(self) -> str:
        return '''
        <html>
        <head>
        <style type="text/css">
            body { margin-left:10px };
        </style>
        </head>
        <body>
        <h1 align="center">PhaseNet Picker</h1>
        <p>
        Automatic detection of P- and S-Phases in the given traces, using PhaseNet.<br/>
        <p>
        <b>Parameters:</b><br />
            <b>&middot; P threshold</b>
                -  Define a trigger threshold for the P-Phase detection <br />
            <b>&middot; S threshold</b>
                -  Define a trigger threshold for the S-Phase detection <br />
            <b>&middot; Detection method</b>
                -  Choose the pretrained model, used for detection. <br />
        </p>
        <p>
        More information about PhaseNet can be found 
        <a href="https://seisbench.readthedocs.io/en/stable/index.html">on the seisbench website</a>.
        </p>
        </body>
        </html>
        '''

    def setup(self) -> None:

        self.set_name('PhaseNet Detector')

        self.add_parameter(
            Param(
                'P threshold',
                'p_threshold',
                0.5,
                0.,
                1.,
            )
        )

        self.add_parameter(
            Param(
                'S threshold',
                's_threshold',
                0.5,
                0.,
                1.,
            )
        )

        self.add_parameter(
            Choice(
                'Detection method',
                'detectionmethod',
                'ethz',
                detectionmethods,
            )
        )

        self.set_live_update(False)

    def panel_visibility_changed(self, visible: bool) -> None:
        viewer = self.get_viewer()
        if visible:
            viewer.pile_has_changed_signal.connect(self.adjust_controls)
            self.adjust_controls()
        else:
            viewer.pile_has_changed_signal.disconnect(self.adjust_controls)

    def adjust_controls(self) -> None:
        viewer = self.get_viewer()
        dtmin, dtmax = viewer.content_deltat_range()
        maxfreq = 0.5 / dtmin
        minfreq = (0.5 / dtmax) * 0.001
        self.set_parameter_range('lowpass', minfreq, maxfreq)
        self.set_parameter_range('highpass', minfreq, maxfreq)

    def call(self) -> None:
        " Main method "
        import seisbench.models as sbm

        self.cleanup()
        model = sbm.PhaseNet.from_pretrained(self.detectionmethod)

        for batch in self.chopper_selected_traces(
            want_incomplete=False,
            fallback=True,
            style='batch',
            mode='all',
            progress='Calculating PhaseNet detections...',
            responsive=True,
            marker_selector=lambda marker: marker.tmin != marker.tmax,
            trace_selector=lambda x: not (x.meta and x.meta.get('tabu', False)),
        ):
            batch = cast(Batch, batch)
            traces = batch.traces
            
            for tr in traces:
                tr = self.apply_filter(tr)
                stream = Stream(compat.to_obspy_trace(tr))
                output = model.classify(
                    stream,
                    P_threshold=self.p_threshold,
                    S_threshold=self.s_threshold,
                )
                print('########### Picks ###########')
                print(output.picks)
                markers = []
                for pick in output.picks:
                    t = str(pick.start_time).replace('T', ' ').replace('%fZ', 'OPTFRAC')
                    t = str_to_time(t)
                    if pick.phase == 'P':
                        markers.append(Marker(('*','*','*','*'), t, t, kind=0))
                    elif pick.phase == 'S':
                        markers.append(Marker(('*','*','*','*'), t, t, kind=1))

                    self.add_markers(markers)
                    markers = []

    def apply_filter(self, tr: Trace) -> Trace:
        viewer = self.get_viewer()
        if viewer.lowpass is not None:
            tr.lowpass(4, viewer.lowpass, nyquist_exception=False)
        if viewer.highpass is not None:
            tr.highpass(4, viewer.highpass, nyquist_exception=False)
        return tr

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
    return [DeepDetector()]