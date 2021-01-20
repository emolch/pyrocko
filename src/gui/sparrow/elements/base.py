# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import os
import base64

import numpy as num

from pyrocko import automap
from pyrocko.guts import String, Tuple, StringChoice
from pyrocko.plot import AutoScaler, AutoScaleMode
from pyrocko.dataset import topo

from pyrocko.gui.talkie import TalkieRoot
from pyrocko.gui.qt_compat import qc, qw, fnpatch
from pyrocko.gui.vtk_util import cpt_to_vtk_lookuptable

from .. import common
from ..state import state_bind_combobox, state_bind


def random_id():
    return base64.urlsafe_b64encode(os.urandom(16)).decode('ascii')


class ElementState(TalkieRoot):

    element_id = String.T()

    def __init__(self, **kwargs):
        if 'element_id' not in kwargs:
            kwargs['element_id'] = random_id()

        TalkieRoot.__init__(self, **kwargs)


class Element(object):
    def __init__(self):
        self._listeners = []
        self._parent = None
        self._state = None

    def register_state_listener(self, listener):
        self._listeners.append(listener)  # keep listeners alive

    def register_state_listener3(self, listener, state, path):
        self.register_state_listener(state.add_listener(listener, path))

    def remove(self):
        if self._parent and self._state:
            self._parent.state.elements.remove(self._state)

    def set_parent(self, parent):
        self._parent = parent

    def unset_parent(self):
        self._parent = None

    def bind_state(self, state):
        self._state = state

    def unbind_state(self):
        for listener in self._listeners:
            try:
                listener.release()
            except Exception:
                pass

        self._listeners = []
        self._state = None


class CPTChoice(StringChoice):
    choices = ['slip_colors', 'seismic', 'jet', 'hot_r', 'gist_earth_r']


class CPTState(ElementState):
    cpt_name = String.T(default=CPTChoice.choices[0])
    cpt_mode = String.T(default=AutoScaleMode.choices[1])
    cpt_scale = Tuple.T(default=(None, None))


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

    def bind_state(self, cpt_state, update_function):
        for state_attr in ['cpt_name', 'cpt_mode', 'cpt_scale']:
            cpt_state.add_listener(update_function, state_attr)

        self._state = cpt_state

    def unbind_state(self):
        self._cpts = {}
        self._lookuptable = None
        self._values = None
        self._autoscaler = None

    def open_cpt_load_dialog(self):
        caption = 'Select one *.cpt file to open'

        fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options))

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
                        from matplotlib import pyplot as plt
                        cmap = plt.cm.get_cmap(s)
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
                cb.insertItem(i, s, qc.QVariant(self._cpts[s]))
                cb.setItemData(i, qc.QVariant(s), qc.Qt.ToolTipRole)

        cb.setCurrentIndex(cb.findText(self._state.cpt_name))

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

        if all(state.cpt_scale):
            crange = state.cpt_scale

        fmt = ', '.join(['%s' if item is None else '%g' for item in crange])

        widget.setText(fmt % crange)

        # if sel:
        #     widget.selectAll()

    def update_cpt(self):
        state = self._state

        if self._autoscaler is None:
            self._autoscaler = AutoScaler()

        if self._cpt_scale_lineedit:
            if state.cpt_mode == 'off':
                self._cpt_scale_lineedit.setEnabled(True)
            else:
                self._cpt_scale_lineedit.setEnabled(False)

                if any(state.cpt_scale):
                    state.cpt_scale = (None, None)

        if state.cpt_name is not None and self._values is not None:
            vscale = (num.nanmin(self._values), num.nanmax(self._values))

            vmin, vmax = None, None
            if state.cpt_scale != (None, None):
                vmin, vmax = state.cpt_scale
            else:
                vmin, vmax, _ = self._autoscaler.make_scale(
                    vscale, override_mode=state.cpt_mode)

            self._cpts[state.cpt_name].scale(vmin, vmax)
            cpt = self._cpts[state.cpt_name]

            vtk_cpt = cpt_to_vtk_lookuptable(cpt)

            self._lookuptable = vtk_cpt
            self._update_cptscale_lineedit()

        elif state.cpt_name and self._values is None:
            raise ValueError('No values passed to colormapper!')

    def cpt_controls(self, parent, state, layout):
        self._parent = parent

        iy = layout.rowCount() + 1

        layout.addWidget(qw.QLabel('Color Map:'), iy, 0)

        cb = common.CPTComboBox()
        layout.addWidget(cb, iy, 1)
        state_bind_combobox(
            self, state, 'cpt_name', cb)

        self._cpt_combobox = cb

        pb = qw.QPushButton('Load CPT')
        layout.addWidget(pb, iy, 2)
        pb.clicked.connect(self.open_cpt_load_dialog)

        iy += 1
        layout.addWidget(qw.QLabel('Color Scaling:'), iy, 0)

        cb = common.string_choices_to_combobox(AutoScaleMode)
        layout.addWidget(cb, iy, 1)
        state_bind_combobox(
            self, state, 'cpt_mode', cb)

        le = qw.QLineEdit()
        le.setEnabled(False)
        layout.addWidget(le, iy, 2)
        state_bind(
            self, state,
            ['cpt_scale'], _lineedit_to_cptscale,
            le, [le.editingFinished, le.returnPressed],
            self._cptscale_to_lineedit)

        self._cpt_scale_lineedit = le


def _lineedit_to_cptscale(widget, cpt_state):
    s = str(widget.text())
    s = s.replace(',', ' ')

    crange = tuple((float(i) for i in s.split()))
    crange = tuple((
        crange[0],
        crange[0]+0.01 if crange[0] >= crange[1] else crange[1]))

    try:
        cpt_state.cpt_scale = crange
    except Exception:
        raise ValueError(
            'need two numerical values: <vmin>, <vmax>')


__all__ = [
    'Element',
    'ElementState',
    'random_id',
]
