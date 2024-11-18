# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from typing import Dict, Tuple
import logging
from os.path import commonprefix
from pyrocko.trace import Trace, NoData
from pyrocko import obspy_compat as compat

from ..snuffling import Param, Snuffling, Choice, Switch
from ..marker import PhaseMarker

try:
    import seisbench.models as sbm
    from seisbench.models import WaveformModel
    import torch
    from obspy import Stream
except ImportError:
    sbm = None
    Stream = None


HOUR = 3600.0
logger = logging.getLogger(__name__)

ML_NETWORKS = (
    'PhaseNet', 'EQTransformer', 'GPD', 'LFEDetect'
)
TRAINED_MODELS = (
    'original', 'ethz', 'instance', 'scedc', 'stead', 'geofon',
    'neic', 'cascadia', 'cms', 'jcms', 'jcs', 'jms', 'mexico',
    'nankai', 'san_andreas'
)

MODEL_CACHE: Dict[Tuple[str, str], "WaveformModel"] = {}


def get_blinding_samples(model: "WaveformModel") -> Tuple[int, int]:
    try:
        return model.default_args["blinding"]
    except KeyError:
        return model._annotate_args["blinding"][1]


class SeisBenchDetector(Snuffling):
    network: str
    training_model: str

    p_threshold: float
    s_threshold: float
    scale_factor: float

    show_annotation_traces: bool
    use_predefined_filters: bool

    def __init__(self, *args, **kwargs):
        Snuffling.__init__(self, *args, **kwargs)
        self.training_model = 'original'
        try:
            from seisbench.util.annotations import PickList
            self.old_method: str = ""
            self.old_network: str = ""
            self.pick_list: PickList | None = PickList()

        except ImportError:
            self.old_method = ""
            self.old_network = ""
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
<h1 align="center">SeisBench: ML Picker</h1>
<p>
    Automatic detection of P- and S-Phases in the given traces, using various
    pre-trained ML models from SeisBench.<br/>
<p>
<b>Parameters:</b><br />
    <b>&middot; P threshold</b>
    - Define a trigger threshold for the P-Phase detection <br />
    <b>&middot; S threshold</b>
    - Define a trigger threshold for the S-Phase detection <br />
    <b>&middot; Detection method</b>
    - Choose the pretrained model, used for detection. <br />
    <b>&middot; Rescaling</b>
    - Factor to stretch and compress the waveforms before inference <br />
</p>
<p>
    <span style="color:red">P-Phases</span> are marked with red markers, <span
    style="color:green>S-Phases</span> with green markers.
<p>
    More information about SeisBench can be found <a
    href="https://seisbench.readthedocs.io/en/stable/index.html">on the
    SeisBench website</a>.
</p>
</body>
</html>'''

    def setup(self) -> None:
        self.set_name('SeisBench: ML Picker')
        self.add_parameter(
            Choice(
                'Network',
                'network',
                default='PhaseNet',
                choices=ML_NETWORKS,
            )
        )

        self.add_parameter(
            Choice(
                'Training model',
                'training_model',
                default='original',
                choices=TRAINED_MODELS,
            )
        )

        self.add_parameter(
            Param(
                'P threshold',
                'p_threshold',
                default=self.get_default_threshold('P'),
                minimum=0.0,
                maximum=1.0,
            )
        )
        self.add_parameter(
            Param(
                'S threshold', 's_threshold',
                default=self.get_default_threshold('S'),
                minimum=0.0,
                maximum=1.0,
            )
        )

        self.add_parameter(
            Switch(
                'Show annotation traces', 'show_annotation_traces',
                default=False
            )
        )
        self.add_parameter(
            Switch(
                'Use pre-defined filters', 'use_predefined_filters',
                default=True
            )
        )
        self.add_parameter(
            Param(
                'Rescaling factor', 'scale_factor',
                default=1.0,
                minimum=0.1,
                maximum=10.0
            )
        )

        self.set_live_update(True)

    def get_default_threshold(self, phase: str) -> float:
        if sbm is None or self.training_model == 'original':
            return 0.3

        else:
            model = self.get_model(self.network, self.training_model)
            if phase == 'S':
                return model.default_args['S_threshold']
            elif phase == 'P':
                return model.default_args['P_threshold']

    def get_model(self, network: str, model: str) -> WaveformModel:
        if sbm is None:
            raise ImportError(
                'SeisBench is not installed. Install to use this plugin.')
        key = (network, model)
        if key in MODEL_CACHE:
            return MODEL_CACHE[key]
        seisbench_model = eval(f'sbm.{network}.from_pretrained("{model}")')
        try:
            seisbench_model = seisbench_model.to('cuda')
        except (RuntimeError, AssertionError):
            logger.info('CUDA not available, using CPU')

        seisbench_model.eval()
        try:
            seisbench_model = torch.compile(
                seisbench_model, mode='max-autotune')
        except RuntimeError:
            logger.info('Torch compile failed')

        MODEL_CACHE[key] = seisbench_model
        return seisbench_model

    def set_default_thresholds(self) -> None:
        if self.training_model == 'original':
            self.set_parameter('p_threshold', 0.3)
            self.set_parameter('s_threshold', 0.3)
        elif self.training_model in TRAINED_MODELS[-8:]:
            self.set_parameter('p_threshold', 0.3)
            self.set_parameter('s_threshold', 0.3)
        else:
            self.set_parameter('p_threshold', self.get_default_threshold('P'))
            self.set_parameter('s_threshold', self.get_default_threshold('S'))

    def content_changed(self) -> None:
        if self._live_update:
            self.call()

    def panel_visibility_changed(self, visible: bool) -> None:
        if visible:
            self._connect_signals()
        else:
            self._disconnect_signals()

    def _connect_signals(self) -> None:
        viewer = self.get_viewer()
        viewer.pile_has_changed_signal.connect(self.content_changed)
        viewer.frequency_filter_changed.connect(self.content_changed)

    def _disconnect_signals(self) -> None:
        viewer = self.get_viewer()
        viewer.pile_has_changed_signal.disconnect(self.content_changed)
        viewer.frequency_filter_changed.disconnect(self.content_changed)

    def call(self) -> None:
        self.cleanup()
        self.get_viewer().clean_update()
        self.adjust_thresholds()

        model = self.get_model(self.network, self.training_model)

        tinc = 300.0
        tpad = 1.0

        tpad_filter = 0.0
        if self.use_predefined_filters:
            fmin = self.get_viewer().highpass
            tpad_filter = 0.0 if fmin is None else 2.0/fmin

        for batch in self.chopper_selected_traces(
            tinc=tinc,
            tpad=tpad + tpad_filter,
            fallback=True,
            mode='visible',
            progress='Calculating SeisBench detections...',
            responsive=True,
            style='batch',
        ):
            traces: list[Trace] = []
            for trace in batch.traces:
                if trace.meta and trace.meta.get('tabu', False):
                    continue
                traces.append(trace)

            if not traces:
                continue

            wmin, wmax = batch.tmin, batch.tmax

            if self.use_predefined_filters:
                traces = [self.apply_filter(tr, tpad_filter) for tr in traces]

            stream = Stream([compat.to_obspy_trace(tr) for tr in traces])
            tr_starttimes: Dict[str, float] = {}
            if self.scale_factor != 1:
                for tr in stream:
                    tr.stats.sampling_rate /= self.scale_factor
                    s = tr.stats
                    tr_nsl = '.'.join((s.network, s.station, s.location))
                    tr_starttimes[tr_nsl] = s.starttime.timestamp

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

                if self.scale_factor != 1:
                    for tr in output_annotation:
                        tr.stats.sampling_rate *= self.scale_factor
                        blinding_samples = max(get_blinding_samples(model))
                        # 100 Hz is the native sampling rate of the model
                        blinding_seconds = (blinding_samples / 100.0) * \
                            (1.0 - 1.0 / self.scale_factor)
                        tr.stats.starttime -= blinding_seconds

                annotated_traces = []
                for tr in compat.to_pyrocko_traces(output_annotation):
                    if tr.channel.endswith('N'):
                        continue
                    tr = tr.copy()
                    tr.chop(wmin, wmax)
                    tr.meta = {'tabu': True, 'annotation': True}
                    annotated_traces.append(tr)

                self._disconnect_signals()
                self.add_traces(annotated_traces)
                self._connect_signals()

            self.pick_list = output_classify.picks

            def get_channel(trace_id: str) -> str:
                network, station, location = trace_id.split('.')
                nsl = (network, station, location)
                return commonprefix(
                    [tr.channel for tr in traces if tr.nslc_id[:-1] == nsl]) \
                    + '*'

            markers = []
            for pick in output_classify.picks:

                tpeak = pick.peak_time.timestamp
                if self.scale_factor != 1:
                    tr_starttime = tr_starttimes[pick.trace_id]
                    tpeak = tr_starttime + \
                        (pick.peak_time.timestamp - tr_starttime) \
                        / self.scale_factor

                if wmin <= tpeak < wmax:
                    codes = tuple(pick.trace_id.split('.')) + \
                                  (get_channel(pick.trace_id),)
                    markers.append(PhaseMarker(
                        [codes],
                        tmin=tpeak,
                        tmax=tpeak,
                        kind=0 if pick.phase == 'P' else 1,
                        phasename=pick.phase,
                        incidence_angle=pick.peak_value,
                    ))

            self.add_markers(markers)

    def adjust_thresholds(self) -> None:
        method = self.get_parameter_value('training_model')
        network = self.get_parameter_value('network')

        if method != self.old_method or network != self.old_network:
            if (network == 'LFEDetect') \
                    and (method not in TRAINED_MODELS[-8:]):
                logger.info(
                    'The selected model is not compatible with LFEDetect '
                    'please select a model from the last 8 models in the '
                    'list. Default is cascadia.')
                self.set_parameter('training_model', 'cascadia')
            elif (network != 'LFEDetect') \
                    and (method in TRAINED_MODELS[-8:]):
                logger.info(
                    'The selected model is not compatible with the selected '
                    'network. Default is original.')
                self.set_parameter('training_model', 'original')
            self.set_default_thresholds()
            self.old_method = method
            self.old_network = network

    def apply_filter(self, tr: Trace, tcut: float) -> Trace:
        viewer = self.get_viewer()
        if viewer.lowpass is not None:
            tr.lowpass(4, viewer.lowpass, nyquist_exception=False)
        if viewer.highpass is not None:
            tr.highpass(4, viewer.highpass, nyquist_exception=False)
        try:
            tr.chop(tr.tmin + tcut, tr.tmax - tcut)
        except NoData:
            pass
        return tr


def __snufflings__():
    return [SeisBenchDetector()]
