# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import os
import base64

import numpy as num

from pyrocko.plot import automap, mpl_get_cmap_names, mpl_get_cmap
from pyrocko.guts import String, Float, StringChoice, Bool
from pyrocko.plot import AutoScaler, AutoScaleMode
from pyrocko.dataset import topo

from pyrocko.gui.talkie import (TalkieRoot, TalkieConnectionOwner,
                                has_computed, computed)

from pyrocko.gui.qt_compat import qc, qw
from pyrocko.gui.vtk_util import cpt_to_vtk_lookuptable, ColorbarPipe


from .. import common
from ..state import \
    state_bind_combobox, state_bind, state_bind_checkbox, state_bind_slider


mpl_cmap_blacklist = [
    "prism", "flag",
    "Accent", "Dark2",
    "Paired", "Pastel1", "Pastel2",
    "Set1", "Set2", "Set3",
    "tab10", "tab20", "tab20b", "tab20c"
]


def get_mpl_cmap_choices():
    names = mpl_get_cmap_names()
    for cmap_name in mpl_cmap_blacklist:
        try:
            names.remove(cmap_name)
            names.remove("%s_r" % cmap_name)
        except ValueError:
            pass

    return names


def random_id():
    return base64.urlsafe_b64encode(os.urandom(16)).decode('ascii')


class ElementState(TalkieRoot):

    element_id = String.T()

    def __init__(self, **kwargs):
        if 'element_id' not in kwargs:
            kwargs['element_id'] = random_id()

        TalkieRoot.__init__(self, **kwargs)


class Element(TalkieConnectionOwner):
    def __init__(self):
        TalkieConnectionOwner.__init__(self)
        self._parent = None
        self._state = None

    def remove(self):
        if self._parent and self._state:
            self._parent.state.elements.remove(self._state)

    def set_parent(self, parent):
        self._parent = parent

    def unset_parent(self):
        print(self)
        raise NotImplementedError

    def bind_state(self, state):
        self._state = state

    def unbind_state(self):
        self.talkie_disconnect_all()
        self._state = None

    def update_visibility(self, visible):
        self._state.visible = visible

    def get_title_label(self):
        title_label = common.MyDockWidgetTitleBarLabel(self.get_name())

        def update_label(*args):
            title_label.set_slug(self._state.element_id)

        self.talkie_connect(
            self._state, 'element_id', update_label)

        update_label()
        return title_label

    def get_title_control_remove(self):
        button = common.MyDockWidgetTitleBarButton('\u2716')
        button.setStatusTip('Remove Element')
        button.clicked.connect(self.remove)
        return button

    def get_title_control_visible(self):
        assert hasattr(self._state, 'visible')

        button = common.MyDockWidgetTitleBarButtonToggle('\u2b53', '\u2b54')
        button.setStatusTip('Toggle Element Visibility')
        button.toggled.connect(self.update_visibility)

        def set_button_checked(*args):
            button.blockSignals(True)
            button.set_checked(self._state.visible)
            button.blockSignals(False)

        set_button_checked()

        self.talkie_connect(
            self._state, 'visible', set_button_checked)

        return button


class CPTChoice(StringChoice):

    choices = ['slip_colors'] + get_mpl_cmap_choices()


class ColorBarPositionChoice(StringChoice):
    choices = ['bottom-left', 'bottom-right', 'top-left', 'top-right']


@has_computed
class CPTState(ElementState):
    cpt_name = String.T(default=CPTChoice.choices[0])
    cpt_mode = String.T(default=AutoScaleMode.choices[1])
    cpt_scale_min = Float.T(optional=True)
    cpt_scale_max = Float.T(optional=True)
    cpt_revert = Bool.T(default=False)
    cbar_show = Bool.T(default=True)
    cbar_position = ColorBarPositionChoice.T(default='bottom-right')
    cbar_annotation_lightness = Float.T(default=1.0)
    cbar_annotation_fontsize = Float.T(default=0.03)
    cbar_height = Float.T(default=1.)
    cbar_width = Float.T(default=1.)

    @computed(['cpt_name', 'cpt_revert'])
    def effective_cpt_name(self):
        if self.cpt_revert:
            return '%s_r' % self.cpt_name
        else:
            return self.cpt_name


class CPTHandler(Element):

    def __init__(self):

        Element.__init__(self)
        self._cpts = {}
        self._autoscaler = None
        self._lookuptable = None
        self._cpt_combobox = None
        self._values = None
        self._state = None
        self._cpt_scale_lineedit = None
        self._cbar_pipe = None

    def bind_state(self, cpt_state, update_function):
        for state_attr in [
                'effective_cpt_name', 'cpt_mode',
                'cpt_scale_min', 'cpt_scale_max',
                'cbar_show', 'cbar_position',
                'cbar_annotation_lightness',
                'cbar_annotation_fontsize',
                'cbar_height', 'cbar_width']:

            self.talkie_connect(
                cpt_state, state_attr, update_function)

        self._state = cpt_state

    def unbind_state(self):
        Element.unbind_state(self)
        self._cpts = {}
        self._lookuptable = None
        self._values = None
        self._autoscaler = None

    def open_cpt_load_dialog(self):
        caption = 'Select one *.cpt file to open'

        fns, _ = qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options)

        if fns:
            self.load_cpt_file(fns[0])

    def load_cpt_file(self, path):
        cpt_name = 'USR' + os.path.basename(path).split('.')[0]
        self._cpts.update([(cpt_name, automap.read_cpt(path))])

        self._state.cpt_name = cpt_name

        self._update_cpt_combobox()
        self.update_cpt()

    def _update_cpt_combobox(self):
        from pyrocko import config
        conf = config.config()

        if self._cpt_combobox is None:
            raise ValueError('CPT combobox needs init before updating!')

        cb = self._cpt_combobox

        if cb is not None:
            cb.clear()

            for s in CPTChoice.choices:
                if s not in self._cpts:
                    try:
                        cpt = automap.read_cpt(topo.cpt(s))
                    except Exception:
                        cmap = mpl_get_cmap(s)
                        cpt = automap.CPT.from_numpy(cmap(range(256))[:, :-1])

                    self._cpts.update([(s, cpt)])

            cpt_dir = conf.colortables_dir
            if os.path.isdir(cpt_dir):
                for f in [
                        f for f in os.listdir(cpt_dir)
                        if f.lower().endswith('.cpt')]:

                    s = 'USR' + os.path.basename(f).split('.')[0]
                    self._cpts.update(
                        [(s, automap.read_cpt(os.path.join(cpt_dir, f)))])

            for i, (s, cpt) in enumerate(self._cpts.items()):
                if s[-2::] != "_r":
                    cb.insertItem(i, s, qc.QVariant(self._cpts[s]))
                    cb.setItemData(i, qc.QVariant(s), qc.Qt.ToolTipRole)

        cb.setCurrentIndex(cb.findText(self._state.effective_cpt_name))

    def _update_cptscale_lineedit(self):
        le = self._cpt_scale_lineedit
        if le is not None:
            le.clear()

            self._cptscale_to_lineedit(self._state, le)

    def _cptscale_to_lineedit(self, state, widget):
        # sel = widget.selectedText() == widget.text()

        crange = (None, None)
        if self._lookuptable is not None:
            crange = self._lookuptable.GetRange()

        if state.cpt_scale_min is not None and state.cpt_scale_max is not None:
            crange = state.cpt_scale_min, state.cpt_scale_max

        fmt = ', '.join(['%s' if item is None else '%g' for item in crange])

        widget.setText(fmt % crange)

        # if sel:
        #     widget.selectAll()

    def update_cpt(self, mask_zeros=False):
        state = self._state

        if self._autoscaler is None:
            self._autoscaler = AutoScaler()

        if self._cpt_scale_lineedit:
            if state.cpt_mode == 'off':
                self._cpt_scale_lineedit.setEnabled(True)
            else:
                self._cpt_scale_lineedit.setEnabled(False)

                if state.cpt_scale_min is not None:
                    state.cpt_scale_min = None

                if state.cpt_scale_max is not None:
                    state.cpt_scale_max = None

        if state.effective_cpt_name is not None and self._values is not None:
            if self._values.size == 0:
                vscale = (0., 1.)
            else:
                vscale = (num.nanmin(self._values), num.nanmax(self._values))

            vmin, vmax = None, None
            if None not in (state.cpt_scale_min, state.cpt_scale_max):
                vmin, vmax = state.cpt_scale_min, state.cpt_scale_max
            else:
                vmin, vmax, _ = self._autoscaler.make_scale(
                    vscale, override_mode=state.cpt_mode)

            self._cpts[state.effective_cpt_name].scale(vmin, vmax)
            cpt = self._cpts[state.effective_cpt_name]
            vtk_lut = cpt_to_vtk_lookuptable(cpt, mask_zeros=mask_zeros)
            vtk_lut.SetNanColor(0.0, 0.0, 0.0, 0.0)

            self._lookuptable = vtk_lut
            self._update_cptscale_lineedit()

        elif state.effective_cpt_name and self._values is None:
            raise ValueError('No values passed to colormapper!')

    def update_cbar(self, display_parameter):

        state = self._state
        lut = self._lookuptable

        if state.cbar_show and lut:
            sx, sy = 1, 1
            off = 0.08 * sy
            pos = {
                'top-left': (off, sy/2 + off, 0, 2),
                'top-right': (sx - off, sy/2 + off, 2, 2),
                'bottom-left': (off, off, 0, 0),
                'bottom-right': (sx - off, off, 2, 0)}
            x, y, _, _ = pos[state.cbar_position]

            if not isinstance(self._cbar_pipe, ColorbarPipe):
                self._cbar_pipe = ColorbarPipe(
                    parent_pipe=self._parent,
                    lut=lut,
                    cbar_title=display_parameter,
                    position=(x, y))
                self._parent.add_actor(self._cbar_pipe.actor)
            else:
                self._cbar_pipe.set_lookuptable(lut)
                self._cbar_pipe.set_title(display_parameter)
                self._cbar_pipe._set_position(x, y)

            sx, sy = self._parent.gui_state.size
            fontsize = round(state.cbar_annotation_fontsize*sy)
            lightness = 0.9 * state.cbar_annotation_lightness
            self._cbar_pipe._format_text(
                lightness=lightness, fontsize=fontsize)

            height_px = int(round(sy / 3 * state.cbar_height))
            width_px = int(round(50 * state.cbar_width))
            self._cbar_pipe._format_size(height_px, width_px)

        else:
            self.remove_cbar_pipe()

    def remove_cbar_pipe(self):
        if self._cbar_pipe is not None:
            self._parent.remove_actor(self._cbar_pipe.actor)

        self._cbar_pipe = None

    def cpt_controls(self, parent, state, layout):
        self._parent = parent

        iy = layout.rowCount() + 1

        layout.addWidget(qw.QLabel('Color Map'), iy, 0)

        cb = common.CPTComboBox()
        layout.addWidget(cb, iy, 1)
        state_bind_combobox(
            self, state, 'cpt_name', cb)

        self._cpt_combobox = cb

        pb = qw.QPushButton('Load CPT')
        layout.addWidget(pb, iy, 2)
        pb.clicked.connect(self.open_cpt_load_dialog)

        iy += 1
        layout.addWidget(qw.QLabel('Color Scaling'), iy, 0)

        cb = common.string_choices_to_combobox(AutoScaleMode)
        layout.addWidget(cb, iy, 1)
        state_bind_combobox(
            self, state, 'cpt_mode', cb)

        le = qw.QLineEdit()
        le.setEnabled(False)
        layout.addWidget(le, iy, 2)
        state_bind(
            self, state,
            ['cpt_scale_min', 'cpt_scale_max'], _lineedit_to_cptscale,
            le, [le.editingFinished, le.returnPressed],
            self._cptscale_to_lineedit)

        self._cpt_scale_lineedit = le

        iy += 1
        cb = qw.QCheckBox('Revert')
        layout.addWidget(cb, iy, 1)
        state_bind_checkbox(self, state, 'cpt_revert', cb)

        # color bar
        iy += 1
        layout.addWidget(qw.QLabel('Color Bar'), iy, 0)

        chb = qw.QCheckBox('show')
        layout.addWidget(chb, iy, 1)
        state_bind_checkbox(self, state, 'cbar_show', chb)

        cb = common.string_choices_to_combobox(
            ColorBarPositionChoice)
        layout.addWidget(cb, iy, 2)
        state_bind_combobox(
            self, self._state, 'cbar_position', cb)

        # cbar text
        iy += 1
        layout.addWidget(qw.QLabel('Lightness'), iy, 1)

        slider = qw.QSlider(qc.Qt.Horizontal)
        slider.setSizePolicy(
            qw.QSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
        slider.setMinimum(0)
        slider.setMaximum(1000)
        layout.addWidget(slider, iy, 2)

        state_bind_slider(
            self,
            self._state,
            'cbar_annotation_lightness',
            slider,
            factor=0.001)

        iy += 1
        layout.addWidget(qw.QLabel('Fontsize'), iy, 1)

        slider = qw.QSlider(qc.Qt.Horizontal)
        slider.setSizePolicy(
            qw.QSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
        slider.setMinimum(0)
        slider.setMaximum(100)
        layout.addWidget(slider, iy, 2)

        state_bind_slider(
            self,
            self._state,
            'cbar_annotation_fontsize',
            slider,
            factor=0.001)

        # cbar size
        iy += 1
        layout.addWidget(qw.QLabel('Height'), iy, 1)

        slider = qw.QSlider(qc.Qt.Horizontal)
        slider.setSizePolicy(
            qw.QSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
        slider.setMinimum(1)
        slider.setMaximum(200)
        layout.addWidget(slider, iy, 2)

        state_bind_slider(
            self,
            self._state,
            'cbar_height',
            slider,
            factor=0.01)

        iy += 1
        layout.addWidget(qw.QLabel('Width'), iy, 1)

        slider = qw.QSlider(qc.Qt.Horizontal)
        slider.setSizePolicy(
            qw.QSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
        slider.setMinimum(1)
        slider.setMaximum(200)
        layout.addWidget(slider, iy, 2)

        state_bind_slider(
            self,
            self._state,
            'cbar_width',
            slider,
            factor=0.01)


def _lineedit_to_cptscale(widget, cpt_state):
    s = str(widget.text())
    s = s.replace(',', ' ')

    crange = tuple((float(i) for i in s.split()))
    crange = tuple((
        crange[0],
        crange[0]+0.01 if crange[0] >= crange[1] else crange[1]))

    try:
        cpt_state.cpt_scale_min, cpt_state.cpt_scale_max = crange
    except Exception:
        raise ValueError(
            'need two numerical values: <vmin>, <vmax>')


__all__ = [
    'Element',
    'ElementState',
    'random_id',
]
