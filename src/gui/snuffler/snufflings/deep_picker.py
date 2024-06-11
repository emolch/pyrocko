# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import os

from pyrocko.trace import Trace
from pyrocko import obspy_compat as compat

from ..snuffling import Param, Snuffling, Choice, Switch
from ..marker import PhaseMarker


h = 3600.

detectionmethods = (
    'original', 'ethz', 'instance', 'scedc', 'stead', 'geofon', 'neic')


class DeepDetector(Snuffling):

    def __init__(self, *args, **kwargs):
        Snuffling.__init__(self, *args, **kwargs)
        try:
            from seisbench.util.annotations import PickList
            self.old_method: str = 'original'
            self.pick_list: PickList | None = PickList()

        except ImportError:
            self.old_method = 'original'
            self.pick_list = None

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
    Automatic detection of P- and S-Phases in the given traces, using
    PhaseNet.<br/>
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
    <span style="color:red">P-Phases</span> are marked with red markers, <span
    style="color:green>S-Phases</span>  with green markers.
<p>
    More information about PhaseNet can be found <a
    href="https://seisbench.readthedocs.io/en/stable/index.html">on the
    seisbench website</a>.
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

        self.add_parameter(Param(
            'Block Length [s]', 'block_length', 100., 0.1, 3600.))

        self.add_parameter(Param(
            'Block Padding [s]', 'block_padding', 50., 0.1, 360.))

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
        try:
            import seisbench.models as sbm
        except ImportError:
            return 0.3

        if self.detectionmethod == 'original':
            return 0.3
        else:
            model = sbm.PhaseNet.from_pretrained(self.detectionmethod)
            if phase == 'S':
                return model.default_args['S_threshold']
            elif phase == 'P':
                return model.default_args['P_threshold']

    def set_default_thresholds(self) -> None:
        if self.detectionmethod == 'original':
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
        import seisbench.models as sbm
        from obspy import Stream

        self.cleanup()
        model = sbm.PhaseNet.from_pretrained(self.detectionmethod)

        tinc = self.block_length
        tpad = self.block_padding

        tpad_filter = 0.0
        if self.use_predefined_filters:
            fmin = self.get_viewer().highpass
            tpad_filter = 0.0 if fmin is None else 2.0/fmin

        for batch in self.chopper_selected_traces(
            tinc=tinc,
            tpad=tpad + tpad_filter,
            fallback=True,
            mode='visible',
            progress='Calculating PhaseNet detections...',
            responsive=True,
            style='batch',
        ):

            traces = batch.traces

            if not traces:
                continue

            wmin, wmax = batch.tmin, batch.tmax

            if self.use_predefined_filters:
                traces = [self.apply_filter(tr, tpad_filter) for tr in traces]

            for i in range(len(traces)):
                traces[i].meta = {'tabu': True}

            stream = Stream([compat.to_obspy_trace(tr) for tr in traces])
            output_classify = model.classify(
                stream,
                P_threshold=self.p_threshold,
                S_threshold=self.s_threshold,
            )

            if self.show_annotation_traces:
                output_annotation = model.annotate(
                    stream,
                    P_threshold=self.p_threshold,
                    S_threshold=self.s_threshold,
                )

                traces_raw = compat.to_pyrocko_traces(output_annotation)
                traces = []
                for tr in traces_raw:
                    tr = tr.copy()
                    tr.chop(wmin, wmax)
                    tr.meta = {'tabu': True}
                    traces.append(tr)

                self.add_traces(traces)

            self.pick_list = output_classify.picks

            print('########### Picks ###########')
            print(self.pick_list)

            markers = []
            for pick in output_classify.picks:
                # tmin = pick.start_time.timestamp
                # tmax = pick.end_time.timestamp
                tpeak = pick.peak_time.timestamp
                if wmin <= tpeak < wmax:
                    codes = tuple(pick.trace_id.split('.')) + ('*',)
                    markers.append(PhaseMarker(
                        [codes], tpeak, tpeak, phasename=pick.phase))

            self.add_markers(markers)

        self.adjust_thresholds()

    def adjust_thresholds(self) -> None:
        method = self.get_parameter_value('detectionmethod')
        if method != self.old_method:
            self.set_default_thresholds()
            self.old_method = method

    def apply_filter(self, tr: Trace, tcut: float) -> Trace:
        viewer = self.get_viewer()
        if viewer.lowpass is not None:
            tr.lowpass(4, viewer.lowpass, nyquist_exception=False)
        if viewer.highpass is not None:
            tr.highpass(4, viewer.highpass, nyquist_exception=False)
        tr.chop(tr.tmin + tcut, tr.tmax - tcut)
        return tr

    def export_picks(self) -> None:
        if self.pick_list:
            output_path = self.output_filename(dir=os.getcwd())
            with open(output_path, 'w') as f:
                f.write(self.pick_list.__str__())


def __snufflings__():
    return [DeepDetector()]
