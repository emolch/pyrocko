# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko import table, geometry, cake
from pyrocko.guts import Bool, Float
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.dataset.active_faults import ActiveFaults
from pyrocko.gui.vtk_util import ScatterPipe
from pyrocko.gui import vtk_util
import vtk
from matplotlib.pyplot import cm

from .base import Element, ElementState

guts_prefix = 'sparrow'

km = 1e3
COLOR_FAULTS_NORMAL = (0.5, 0.3, .22)
COLOR_FAULTS_REVERSE = (0.9, 0.3, .92)
COLOR_FAULTS = (0.1, 0.0, .0)
COLOR_FAULTS_SS = (0.3, 0.0, .62)


def faults_to_color_slip_type(faults):
    colors = []
    for f in faults.active_faults:
        num_nodes = len(f.lat)
        if f.slip_type == "Reverse":
            for i in range(0, num_nodes):
                colors.append(COLOR_FAULTS_REVERSE)
        elif f.slip_type == "Normal":
            for i in range(0, num_nodes):
                colors.append(COLOR_FAULTS_NORMAL)
        elif f.slip_type == "Unkown":
            for i in range(0, num_nodes):
                colors.append(COLOR_FAULTS)
        else:
            for i in range(0, num_nodes):
                colors.append(COLOR_FAULTS_SS)
    return num.array(colors)


def faults_to_color(faults):
    colors = []
    for f in faults.active_faults:
        colors.append(COLOR_FAULTS)
    return num.array(colors)


class ActiveFaultsState(ElementState):
    visible = Bool.T(default=True)
    size = Float.T(default=3.0)
    color_by_slip_type = Bool.T(default=False)

    def create(self):
        element = ActiveFaultsElement()
        element.bind_state(self)
        return element


class FaultlinesPipe(object):
    def __init__(self, fault=None):

        self.mapper = vtk.vtkDataSetMapper()
        self._polyline_grid = {}
        self._opacity = 1.0
        self.fault = fault

        actor = vtk.vtkActor()
        actor.SetMapper(self.mapper)

        prop = actor.GetProperty()
        prop.SetDiffuseColor(1, 1, 1)

        self.prop = prop
        self.actor = actor

    def fault_to_lines(self, f):
        lines = []
        poly = []
        num_nodes = len(f.lat)
        for i in range(0, num_nodes):
            pp = (f.lat[i], f.lon[i], f.upper_seis_depth)
            poly.append(pp)
        lines.append(num.asarray(poly))

        self._polyline_grid[0] = vtk_util.make_multi_polyline(
            lines_latlon=lines, depth=-100.)

        vtk_util.vtk_set_input(self.mapper, self._polyline_grid[0])

    def set_opacity(self, opacity):
        opacity = float(opacity)
        if self._opacity != opacity:
            self.prop.SetOpacity(opacity)
            self._opacity = opacity


class ActiveFaultsElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._state = None
        self._pipe = None
        self._controls = None
        self._active_faults = None
        self._listeners = []
        self._fault_lines = []

    def bind_state(self, state):
        self._listeners.append(
            state.add_listener(self.update, 'visible'))
        self._listeners.append(
            state.add_listener(self.update, 'size'))
        self._listeners.append(
            state.add_listener(self.update, 'color_by_slip_type'))
        self._state = state

    def get_name(self):
        return 'Active Faults'

    def set_parent(self, parent):
        self._parent = parent
        if not self._active_faults:
            self._active_faults = ActiveFaults()

        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def update(self, *args):

        state = self._state
        if state.visible:
            if state.color_by_slip_type is True:
                colors = faults_to_color_slip_type(self._active_faults)
            else:
                colors = faults_to_color(self._active_faults)
            for i, fault in enumerate(self._active_faults.active_faults):
                self._fault_line = FaultlinesPipe(fault=fault)
                self._fault_line.fault_to_lines(fault)
                self._parent.add_actor(self._fault_line.actor)
                prop = self._fault_line.actor.GetProperty()
                prop.SetDiffuseColor(colors[i][0:3])
                self._fault_lines.append(self._fault_line)

        if not state.visible and self._fault_lines:
                for i, fault in enumerate(self._fault_lines):
                    self._parent.remove_actor(fault.actor)

        self._parent.update_view()

    def _get_controls(self):
        if self._controls is None:
            from ..state import state_bind_checkbox, state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            layout.addWidget(qw.QLabel('Size'), 0, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(10)
            slider.setSingleStep(0.5)
            slider.setPageStep(1)
            layout.addWidget(slider, 0, 1)
            state_bind_slider(self, self._state, 'size', slider)

            cb = qw.QCheckBox('Show')
            cb_color_slip_type = qw.QCheckBox('Color by slip type')

            layout.addWidget(cb, 1, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            layout.addWidget(cb_color_slip_type, 2, 0)
            state_bind_checkbox(self, self._state, 'color_by_slip_type',
                                cb_color_slip_type)

            self._controls = frame

        return self._controls


__all__ = [
    'ActiveFaultsElement',
    'ActiveFaultsState'
]
