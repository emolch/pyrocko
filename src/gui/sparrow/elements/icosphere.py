# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import math

from pyrocko.guts import Int, StringChoice, Bool, Float
from pyrocko.gui.qt_compat import qw, qc

from .. import common
from pyrocko.gui.vtk_util import TrimeshPipe
from .base import Element, ElementState
from pyrocko import icosphere
from pyrocko.geometry import r2d
from pyrocko.color import Color

km = 1000.

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
    color = Color.T(default=Color.D('aluminium5'))

    ambient = Float.T(default=0.0)
    diffuse = Float.T(default=1.0)
    specular = Float.T(default=0.0)

    opacity = Float.T(default=1.0)
    depth = Float.T(default=30.0*km)

    def create(self):
        element = IcosphereElement()
        return element


class IcosphereElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._mesh = None
        self._controls = None
        self._params = None

    def get_name(self):
        return 'Icosphere'

    def bind_state(self, state):
        Element.bind_state(self, state)
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'level')
        state.add_listener(upd, 'base')
        state.add_listener(upd, 'kind')
        state.add_listener(upd, 'smooth')
        state.add_listener(upd, 'color')
        state.add_listener(upd, 'ambient')
        state.add_listener(upd, 'diffuse')
        state.add_listener(upd, 'specular')
        state.add_listener(upd, 'depth')
        state.add_listener(upd, 'opacity')

    def set_parent(self, parent):
        Element.set_parent(self, parent)
        upd = self.update
        self._listeners.append(upd)
        self._parent.state.add_listener(upd, 'dip')

        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=True,
            remove=self.remove)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._mesh:
                self._parent.remove_actor(self._mesh.actor)
                self._mesh = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def update(self, *args):
        state = self._state

        params = state.level, state.base, state.kind, state.smooth

        if self._mesh and (params != self._params or not state.visible):
            self._parent.remove_actor(self._mesh.actor)
            self._mesh = None

        if state.visible and not self._mesh:
            vertices, faces = icosphere.sphere(
                state.level, state.base, state.kind, radius=1.0,
                triangulate=False)

            self._vertices = vertices
            self._depth = 0.0

            self._mesh = TrimeshPipe(vertices, faces, smooth=state.smooth)
            self._params = params

            self._parent.add_actor(self._mesh.actor)

        if self._parent.state.distance < 2.0:
            angle = 180. - math.acos(self._parent.state.distance / 2.0)*r2d

            opacity = min(
                1.0,
                max(0., (angle+5. - self._parent.state.dip) / 10.))
        else:
            opacity = 1.0

        opacity *= state.opacity

        if self._mesh:
            if self._depth != state.depth:
                radius = (self._parent.planet_radius - state.depth) \
                    / self._parent.planet_radius

                self._mesh.set_vertices(self._vertices * radius)
                self._depth = state.depth

            self._mesh.set_opacity(opacity)
            self._mesh.set_color(state.color)
            self._mesh.set_ambient(state.ambient)
            self._mesh.set_diffuse(state.diffuse)
            self._mesh.set_specular(state.specular)

        self._parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_slider, \
                state_bind_combobox, state_bind_checkbox, \
                state_bind_combobox_color, state_bind_lineedit

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

            layout.addWidget(qw.QLabel('Color'), 3, 0)

            cb = common.strings_to_combobox(
                ['black', 'aluminium6', 'aluminium5', 'aluminium4',
                 'aluminium3', 'aluminium2', 'aluminium1', 'white',
                 'scarletred2', 'orange2', 'skyblue2', 'plum2'])

            layout.addWidget(cb, 3, 1)
            state_bind_combobox_color(
                self, self._state, 'color', cb)

            def add_slider(title, param, irow):
                layout.addWidget(qw.QLabel(title), irow, 0)

                slider = qw.QSlider(qc.Qt.Horizontal)
                slider.setSizePolicy(
                    qw.QSizePolicy(
                        qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
                slider.setMinimum(0)
                slider.setMaximum(1000)
                layout.addWidget(slider, irow, 1)

                state_bind_slider(
                    self, state, param, slider, factor=0.001)

            add_slider('Opacity', 'opacity', 4)
            add_slider('Ambient', 'ambient', 5)
            add_slider('Diffuse', 'diffuse', 6)
            add_slider('Specular', 'specular', 7)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 8, 0)
            state_bind_checkbox(self, state, 'visible', cb)

            cb = qw.QCheckBox('Smooth')
            layout.addWidget(cb, 8, 1)
            state_bind_checkbox(self, state, 'smooth', cb)

            layout.addWidget(qw.QLabel('Depth [km]'), 9, 0)
            le = qw.QLineEdit()
            layout.addWidget(le, 9, 1)
            state_bind_lineedit(
                self, state, 'depth', le,
                from_string=lambda s: float(s)*1000.,
                to_string=lambda v: str(v/1000.))

            layout.addWidget(qw.QFrame(), 10, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'IcosphereElement',
    'IcosphereState',
    'IcosphereKindChoice',
    'IcosphereBaseChoice']
