from typing import cast
import numpy as num
from ..snuffling import Param, Snuffling, Choice, Switch
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
        <span style="color:red">P-Phases</span> are marked with red markers, 
        <span style="color:green>S-Phases</span>  with green markers.
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
            Choice(
                'Detection method',
                'detectionmethod',
                'ethz',
                detectionmethods,
            )
        )   

        self.add_parameter(
            Param(
                'P threshold',
                'p_threshold',
                self.get_default_threshold('P'),
                0.,
                1.,
            )
        )

        self.add_parameter(
            Param(
                'S threshold',
                's_threshold',
                self.get_default_threshold('S'),
                0.,
                1.,
            )
        )

        self.add_parameter(
            Switch(
                'Show annotation traces', 'show_annotation_traces', 
                False
            )
        )
        
        self.add_parameter(
            Switch(
                'Use predefined filters', 'use_predefined_filters', 
                True
            )
        )

        self.add_trigger(
            'Set defaul thresholds', 
            self.set_default_thresholds
        )

        self.set_live_update(True)

    def get_default_threshold(self, phase: str) -> float:
        import seisbench.models as sbm
        model = sbm.PhaseNet.from_pretrained(self.detectionmethod)
        if phase == 'S':
            return model.default_args['S_threshold']
        elif phase == 'P':
            return model.default_args['P_threshold']
        
    def set_default_thresholds(self) -> None:
        self.set_parameter('p_threshold', self.get_default_threshold('P'))
        self.set_parameter('s_threshold', self.get_default_threshold('S'))

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

        viewer = self.get_viewer()
        deltat_min = viewer.content_deltat_range()[0]
        window = 1
        tinc = max(window * 2., 500000. * deltat_min)

        for traces in self.chopper_selected_traces(
            fallback=True,
            mode='all',
            progress='Calculating PhaseNet detections...',
            responsive=True,

        ):

            if self.use_predefined_filters:
                traces = [self.apply_filter(tr) for tr in traces]
            stream = Stream([compat.to_obspy_trace(tr) for tr in traces])
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

def __snufflings__():
    return [DeepDetector()]