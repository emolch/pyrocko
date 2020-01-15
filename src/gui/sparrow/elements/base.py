# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import os

import numpy as num

from pyrocko import automap
from pyrocko.guts import Object, String, Tuple
from pyrocko.plot import AutoScaler, AutoScaleMode
from pyrocko.dataset import topo

from pyrocko.gui.talkie import TalkieRoot
from pyrocko.gui.qt_compat import qc, qw, fnpatch
from pyrocko.gui.vtk_util import cpt_to_vtk_lookuptable

from .. import common
from ..state import state_bind_combobox, state_bind


class ElementState(TalkieRoot):
    pass


class Element(object):
    def __init__(self):
        self._listeners = []
        self._parent = None
        self._state = None

    def register_state_listener(self, listener):
        self._listeners.append(listener)  # keep listeners alive

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
            except Exception as e:
                pass

        self._listeners = []
        self._state = None


class CPTChoice(Object):
    choices = ['slip_colors']


class CPTState(ElementState):
    cpt_name = String.T(default=CPTChoice.choices[0])
    cpt_mode = String.T(default=AutoScaleMode.choices[1])
    cpt_scale = Tuple.T(default=(None, None))


def bind_state_cpt(state, update_function):
    for state_attr in ['cpt_name', 'cpt_mode', 'cpt_scale']:
        state.add_listener(update_function, state_attr)


def open_cpt_load_dialog(self):
    caption = 'Select one *.cpt file to open'

    fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
        self._parent, caption, options=common.qfiledialog_options))

    if fns:
        load_cpt_file(self, fns[0])


def load_cpt_file(owner, path):
    cpt_name = 'USR' + os.path.basename(path).split('.')[0]
    owner._cpts.update([(cpt_name, automap.read_cpt(path))])

    owner._state.cpt_name = cpt_name

    _update_cpt_combobox(owner)
    update_cpt(owner)


def _update_cptscale_lineedit(owner):
    le = owner._cpt_scale_lineedit
    if le is not None:
        le.clear()

        owner._cptscale_to_lineedit(owner._state, le)


def _cptscale_to_lineedit(self, state, widget):
    sel = widget.selectedText() == widget.text()

    crange = (None, None)
    if self._lookuptable is not None:
        crange = self._lookuptable.GetRange()

    if all(state.cpt_scale):
        crange = state.cpt_scale

    fmt = ', '.join(['%s' if item is None else '%g' for item in crange])

    widget.setText(fmt % crange)

    if sel:
        widget.selectAll()


def _lineedit_to_cptscale(widget, state):
    s = str(widget.text())
    s = s.replace(',', ' ')

    crange = tuple((float(i) for i in s.split()))
    crange = tuple((
        crange[0],
        crange[0]+0.01 if crange[0] >= crange[1] else crange[1]))

    try:
        state.cpt_scale = crange
    except Exception:
        raise ValueError(
            'need two numerical values: <vmin>, <vmax>')


def _update_cpt_combobox(owner):
    from pyrocko import config
    conf = config.config()

    cb = owner._cpt_combobox

    if cb is not None:
        cb.clear()

        for s in CPTChoice.choices:
            if s not in owner._cpts:
                owner._cpts.update([(s, automap.read_cpt(topo.cpt(s)))])

        cpt_dir = conf.colortables_dir
        if os.path.isdir(cpt_dir):
            for f in [
                    f for f in os.listdir(cpt_dir)
                    if f.lower().endswith('.cpt')]:

                s = 'USR' + os.path.basename(f).split('.')[0]
                owner._cpts.update(
                    [(s, automap.read_cpt(os.path.join(cpt_dir, f)))])

        for i, (s, cpt) in enumerate(owner._cpts.items()):
            cb.insertItem(i, s, qc.QVariant(owner._cpts[s]))
            cb.setItemData(i, qc.QVariant(s), qc.Qt.ToolTipRole)

    cb.setCurrentIndex(cb.findText(owner._state.cpt_name))


def update_cpt(owner):
    state = owner._state

    if owner._autoscaler is None:
        owner._autoscaler = AutoScaler()

    if owner._cpt_scale_lineedit:
        if state.cpt_mode == 'off':
            owner._cpt_scale_lineedit.setEnabled(True)
        else:
            owner._cpt_scale_lineedit.setEnabled(False)

            if any(state.cpt_scale):
                state.cpt_scale = (None, None)

    if state.cpt_name is not None and owner._values is not None:
        vscale = (num.nanmin(owner._values), num.nanmax(owner._values))

        vmin, vmax = None, None
        if state.cpt_scale != (None, None):
            vmin, vmax = state.cpt_scale
        else:
            vmin, vmax, _ = owner._autoscaler.make_scale(
                vscale, override_mode=state.cpt_mode)

        owner._cpts[state.cpt_name].scale(vmin, vmax)
        cpt = owner._cpts[state.cpt_name]

        vtk_cpt = cpt_to_vtk_lookuptable(cpt)

        owner._lookuptable = vtk_cpt
        _update_cptscale_lineedit(owner)


def cpt_controls(owner, state, layout):
    iy = layout.rowCount() + 1

    layout.addWidget(qw.QLabel('Color Map:'), iy, 0)

    cb = common.CPTComboBox()
    layout.addWidget(cb, iy, 1)
    state_bind_combobox(
        owner, state, 'cpt_name', cb)

    owner._cpt_combobox = cb
    owner._update_cpt_combobox = _update_cpt_combobox.__get__(owner)

    owner.open_cpt_load_dialog = open_cpt_load_dialog.__get__(owner)

    pb = qw.QPushButton('Load CPT')
    layout.addWidget(pb, iy, 2)
    pb.clicked.connect(owner.open_cpt_load_dialog)

    iy += 1
    layout.addWidget(qw.QLabel('Color Scaling:'), iy, 0)

    cb = common.string_choices_to_combobox(AutoScaleMode)
    layout.addWidget(cb, iy, 1)
    state_bind_combobox(
        owner, state, 'cpt_mode', cb)

    owner._cptscale_to_lineedit = _cptscale_to_lineedit.__get__(owner)

    le = qw.QLineEdit()
    le.setEnabled(False)
    layout.addWidget(le, iy, 2)
    state_bind(
        owner, state,
        ['cpt_scale'], _lineedit_to_cptscale,
        le, [le.editingFinished, le.returnPressed],
        owner._cptscale_to_lineedit)

    owner._cpt_scale_lineedit = le
