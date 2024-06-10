from typing import cast
import numpy as num
from ..snuffling import Param, Snuffling, Choice, Switch
from ..marker import Marker
from pyrocko.pile import Batch
from pyrocko.util import str_to_time
from obspy import Stream
from pyrocko import obspy_compat as compat
from pyrocko.trace import Trace

from seisbench.util.annotations import PickList
import os

# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

h = 3600.

detectionmethods = ('original', 'ethz', 'instance', 'scedc', 'stead', 'geofon', 'neic')


class DeepDetector(Snuffling):
    old_method: str = 'original'
    pick_list: PickList = PickList()
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
                'original',
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
            'Export picks', 
            self.export_picks
        )

        self.set_live_update(True)

    def get_default_threshold(self, phase: str) -> float:
        import seisbench.models as sbm
        if self.detectionmethod is 'original':
            return 0.3
        else:
            model = sbm.PhaseNet.from_pretrained(self.detectionmethod)
            if phase == 'S':
                return model.default_args['S_threshold']
            elif phase == 'P':
                return model.default_args['P_threshold']
            
    def set_default_thresholds(self) -> None:
        if self.detectionmethod is 'original':
            self.set_parameter('p_threshold', 0.3)
            self.set_parameter('s_threshold', 0.3)
        else:
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

        for traces in self.chopper_selected_traces(
            fallback=True,
            mode='all',
            progress='Calculating PhaseNet detections...',
            responsive=True,

        ):

            if self.use_predefined_filters:
                traces = [self.apply_filter(tr) for tr in traces]
            for i in range(len(traces)):
                traces[i].set_codes(location='cg')
                traces[i].meta = {'tabu': True}
            stream = Stream([compat.to_obspy_trace(tr) for tr in traces])
            print(stream)
            output_classify = model.classify(
                stream,
                P_threshold=self.p_threshold,
                S_threshold=self.s_threshold,
            )

            output_annotation = model.annotate(
                stream,
                P_threshold=self.p_threshold,
                S_threshold=self.s_threshold,
            )

            offset = output_annotation[0].stats.starttime - stream[0].stats.starttime

            data_pile = self.get_pile()
            
            if self.show_annotation_traces:
                for i in range(3):
                    ano_trace = Trace(
                            deltat=data_pile.deltatmin,
                            tmin=traces[0].tmin + offset,
                            ydata=output_annotation[i].data)
                    if output_annotation[i].stats.channel[-1] != "N":
                        channel = output_annotation[i].stats.channel
                        
                        ano_trace.set_codes(
                                network='', station='',
                                location='cg', channel=channel)
                        
                        ano_trace.add(ano_trace, left=None, right=None)

                        ano_trace.meta = {'tabu': True}
                        self.add_trace(ano_trace)



            print('########### Picks ###########')
            self.pick_list = output_classify.picks
            print(self.pick_list)
            markers = []
            for pick in output_classify.picks:
                t = str(pick.start_time).replace('T', ' ').replace('%fZ', 'OPTFRAC')
                t = str_to_time(t)
                if pick.phase == 'P':
                    markers.append(Marker(('*','*','*','*'), t, t, kind=0))
                elif pick.phase == 'S':
                    markers.append(Marker(('*','*','*','*'), t, t, kind=1))

                self.add_markers(markers)
                markers = []

        self.adjust_thresholds()

    def adjust_thresholds(self) -> None:
        method = self.get_parameter_value('detectionmethod')
        if method != self.old_method:
            self.set_default_thresholds()
            self.old_method = method
        
    def apply_filter(self, tr: Trace) -> Trace:
        viewer = self.get_viewer()
        if viewer.lowpass is not None:
            tr.lowpass(4, viewer.lowpass, nyquist_exception=False)
        if viewer.highpass is not None:
            tr.highpass(4, viewer.highpass, nyquist_exception=False)
        return tr
    
    def export_picks(self) -> None:
        current_path = os.getcwd()
        output_file = os.path.join(current_path, 'output_file.txt')
        with open(output_file, 'w') as f:
            f.write(self.pick_list.__str__())


def __snufflings__():
    return [DeepDetector()]