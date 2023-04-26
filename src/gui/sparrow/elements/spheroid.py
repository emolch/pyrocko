# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from pyrocko.guts import Int, Float, Bool
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.gui.vtk_util import TrimeshPipe
from .base import Element, ElementState
from pyrocko import icosphere, moment_tensor as pmt, orthodrome as od, cake
from pyrocko.geometry import d2r

guts_prefix = 'sparrow'


class SpheroidState(ElementState):
    level = Int.T(default=4)
    visible = Bool.T(default=True)
    opacity = Float.T(default=1.0)
    lat = Float.T(default=0.0)
    lon = Float.T(default=0.0)
    depth = Float.T(default=0.0)
    a = Float.T(default=10000.)
    b = Float.T(default=10000.)
    c = Float.T(default=10000.)
    azimuth = Float.T(default=0.0)
    dip = Float.T(default=0.0)

    def create(self):
        element = SpheroidElement()
        return element


class SpheroidElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._mesh = None
        self._controls = None
        self._params = None
        self._opacity = None

    def get_name(self):
        return 'Spheroid'

    def bind_state(self, state):
        Element.bind_state(self, state)
        self.talkie_connect(
            state,
            ['visible', 'level', 'opacity', 'lat', 'lon', 'depth', 'a', 'b',
             'c', 'azimuth', 'dip'],
            self.update)

    def set_parent(self, parent):
        Element.set_parent(self, parent)

        self._parent.add_panel(
            self.get_title_label(),
            self._get_controls(),
            visible=True,
            title_controls=[
                self.get_title_control_remove(),
                self.get_title_control_visible()])

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
            self._opacity = None
            self._params = None

    def update(self, *args):
        state = self._state

        params = (state.level,)

        if self._mesh and (params != self._params or not state.visible):
            self._parent.remove_actor(self._mesh.actor)
            self._mesh = None

        if state.visible and not self._mesh:
            vertices, faces = icosphere.sphere(
                state.level, 'icosahedron', 'kind1',
                radius=1.0,
                triangulate=False)

            self._vertices0 = vertices
            self._mesh = TrimeshPipe(vertices, faces, smooth=True)
            self._params = params

            self._parent.add_actor(self._mesh.actor)

        s = num.array(
            [state.c, state.b, state.a]) / cake.earthradius

        if self._mesh:
            vertices = self._vertices0 * s[num.newaxis, :]
            bc = num.array(
                [[1, 0, 0], [0, 0, 1], [0, 1, 0]], dtype=num.float64)
            rot = num.dot(
                bc,
                num.dot(
                    pmt.euler_to_matrix(-d2r*state.azimuth, -d2r*state.dip, 0),
                    bc.T))
            vertices = num.dot(rot, vertices.T).T
            vertices[:, 0] += 1.0 - state.depth / cake.earthradius
            rot = od.rot_to_00(state.lat, state.lon).T
            vertices = num.dot(rot, vertices.T).T

            self._mesh.set_vertices(vertices)
            self._mesh.prop.SetColor(0.8, 0.2, 0.1)

        if self._mesh and self._opacity != state.opacity:
            self._mesh.set_opacity(state.opacity)
            self._opacity = state.opacity
        else:
            self._opacity = None

        self._parent.update_view()

    def move_here(self):
        pstate = self._parent.state
        state = self._state
        state.lat = pstate.lat
        state.lon = pstate.lon

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            iy = 0
            for (param, vmin, vmax) in [
                    ('lat', -90., 90.),
                    ('lon', -180., 180.),
                    ('depth', -10000., 100000.),
                    ('a', 100., 100000.),
                    ('b', 100., 100000.),
                    ('c', 100., 100000.),
                    ('azimuth', -180., 180.),
                    ('dip', -90., 90.),
                    ('opacity', 0., 1.)]:

                layout.addWidget(qw.QLabel(param.capitalize()), iy, 0)

                slider = qw.QSlider(qc.Qt.Horizontal)
                slider.setSizePolicy(qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))

                slider.setMinimum(int(round(vmin * 100.)))
                slider.setMaximum(int(round(vmax * 100.)))
                layout.addWidget(slider, iy, 1)

                state_bind_slider(self, state, param, slider, factor=0.01)
                iy += 1

            pb = qw.QPushButton('Move Here')
            layout.addWidget(pb, iy, 0)
            pb.clicked.connect(self.move_here)

            iy += 1

            layout.addWidget(qw.QFrame(), iy, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'SpheroidElement',
    'SpheroidState']
