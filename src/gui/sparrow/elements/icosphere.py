# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import math

from pyrocko.guts import Int, StringChoice, Bool
from pyrocko.gui.qt_compat import qw, qc

from .. import common
from pyrocko.gui.vtk_util import TrimeshPipe
from .base import Element, ElementState
from pyrocko import icosphere
from pyrocko.geometry import r2d

guts_prefix = 'sparrow'


class IcosphereBaseChoice(StringChoice):
    choices = ['icosahedron', 'tetrahedron', 'tcube']


class IcosphereKindChoice(StringChoice):
    choices = ['kind1', 'kind2']


class IcosphereState(ElementState):
    base = IcosphereBaseChoice.T(default='icosahedron')
    kind = IcosphereKindChoice.T(default='kind1')
    level = Int.T(default=0)
    visible = Bool.T(default=True)
    smooth = Bool.T(default=False)

    def create(self):
        element = IcosphereElement()
        element.bind_state(self)
        return element


class IcosphereElement(Element):

    def __init__(self):
        Element.__init__(self)
        self.parent = None
        self._mesh = None
        self._controls = None
        self._params = None
        self._opacity = None

    def get_name(self):
        return 'Icosphere'

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'level')
        state.add_listener(upd, 'base')
        state.add_listener(upd, 'kind')
        state.add_listener(upd, 'smooth')
        self._state = state

    def set_parent(self, parent):
        self.parent = parent
        upd = self.update
        self._listeners.append(upd)
        self.parent.state.add_listener(upd, 'dip')

        self.parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def update(self, *args):
        state = self._state

        params = state.level, state.base, state.kind, state.smooth

        if self._mesh and (params != self._params or not state.visible):
            self.parent.remove_actor(self._mesh.actor)
            self._mesh = None

        if state.visible and not self._mesh:
            vertices, faces = icosphere.sphere(
                state.level, state.base, state.kind, radius=0.98,
                triangulate=False)

            self._mesh = TrimeshPipe(vertices, faces, smooth=state.smooth)
            self._params = params

            self.parent.add_actor(self._mesh.actor)

        if self.parent.state.distance < 2.0:
            angle = 180. - math.acos(self.parent.state.distance / 2.0)*r2d

            opacity = min(
                1.0,
                max(0., (angle+5. - self.parent.state.dip) / 10.))
        else:
            opacity = 1.0

        if self._mesh and self._opacity != opacity:
            self._mesh.set_opacity(opacity)
            self._opacity = opacity
        else:
            self._opacity = None

        self.parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_slider, \
                state_bind_combobox, state_bind_checkbox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(5)
            slider.setSingleStep(1)
            slider.setPageStep(1)

            layout.addWidget(qw.QLabel('Level'), 0, 0)
            layout.addWidget(slider, 0, 1)

            state_bind_slider(self, state, 'level', slider, dtype=int)

            cb = common.string_choices_to_combobox(IcosphereBaseChoice)
            layout.addWidget(qw.QLabel('Base'), 1, 0)
            layout.addWidget(cb, 1, 1)
            state_bind_combobox(self, state, 'base', cb)

            cb = common.string_choices_to_combobox(IcosphereKindChoice)
            layout.addWidget(qw.QLabel('Kind'), 2, 0)
            layout.addWidget(cb, 2, 1)
            state_bind_combobox(self, state, 'kind', cb)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 3, 0)
            state_bind_checkbox(self, state, 'visible', cb)

            cb = qw.QCheckBox('Smooth')
            layout.addWidget(cb, 3, 1)
            state_bind_checkbox(self, state, 'smooth', cb)

            layout.addWidget(qw.QFrame(), 4, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'IcosphereElement',
    'IcosphereState',
    'IcosphereKindChoice',
    'IcosphereBaseChoice']
