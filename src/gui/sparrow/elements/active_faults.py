# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko.guts import Bool, Float
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.dataset.active_faults import ActiveFaults
from pyrocko.gui import vtk_util
from pyrocko import plot
import vtk

from .base import Element, ElementState

guts_prefix = 'sparrow'

km = 1e3


def color(x):
    return num.array(plot.to01(plot.color(x)), dtype=num.float)


fault_color_themes = {
    'light': {
        'Normal': color('skyblue1'),
        'Reverse': color('scarletred1'),
        'SS': color('chameleon1'),
        'Sinistral': color('plum1'),
        'Dextral': color('plum1'),
        None: color('chocolate1')},
    'dark': {
        'Normal': color('skyblue3'),
        'Reverse': color('scarletred3'),
        'SS': color('chameleon3'),
        'Sinistral': color('plum3'),
        'Dextral': color('plum3'),
        None: color('chocolate3')},
    'uniform_light': {
        None: color('chocolate1')},
    'uniform_dark': {
        None: color('chocolate3')}}


class ActiveFaultsState(ElementState):
    visible = Bool.T(default=True)
    size = Float.T(default=3.0)
    color_by_slip_type = Bool.T(default=False)

    def create(self):
        element = ActiveFaultsElement()
        element.bind_state(self)
        return element


class FaultlinesPipe(object):
    def __init__(self, faults):

        self._opacity = 1.0
        self._faults = faults

        slip_types = sorted(set(f.slip_type for f in faults.active_faults))
        self._slip_types = slip_types

        self._actors = {}
        for slip_type in slip_types:
            mapper = vtk.vtkDataSetMapper()

            lines = [
                f.get_surface_line()
                for f in faults.active_faults
                if f.slip_type == slip_type]

            grid = vtk_util.make_multi_polyline(
                lines_latlon=lines, depth=-100.)

            vtk_util.vtk_set_input(mapper, grid)

            actor = vtk.vtkActor()
            actor.SetMapper(mapper)

            self._actors[slip_type] = actor

        self._theme = ''
        self.set_color_theme('uniform_light')

    def set_color_theme(self, theme):

        if self._theme != theme:

            colors = fault_color_themes[theme]
            default_color = colors[None]

            for slip_type in self._slip_types:
                actor = self._actors[slip_type]
                prop = actor.GetProperty()
                prop.SetDiffuseColor(*colors.get(slip_type, default_color))

            self._theme = theme

    def set_opacity(self, opacity):
        opacity = float(opacity)
        if self._opacity != opacity:
            for actor in self._actors.values():
                actor.getProperty().SetOpacity(opacity)

            self._opacity = opacity

    def get_actors(self):
        return [self._actors[slip_type] for slip_type in self._slip_types]


class ActiveFaultsElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._state = None
        self._pipe = None
        self._controls = None
        self._active_faults = None
        self._listeners = []

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
            if not self._pipe:
                self._pipe = FaultlinesPipe(self._active_faults)

        if state.color_by_slip_type:
            self._pipe.set_color_theme('light')
        else:
            self._pipe.set_color_theme('uniform_light')

        if state.visible:
            for actor in self._pipe.get_actors():
                self._parent.add_actor(actor)

        else:
            for actor in self._pipe.get_actors():
                self._parent.remove_actor(actor)

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
