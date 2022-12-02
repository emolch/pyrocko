import vtk
import numpy as num

from pyrocko.gui.qt_compat import qw
from pyrocko import orthodrome as od
from pyrocko.gui import vtk_util
from pyrocko.guts import Bool
from pyrocko.color import Color
from .. import common

from .base import Element, ElementState


def cross3d_flat(a=1., b=0.5):
    lines_ned = []
    for i in range(2):
        for s in (-1., 1.):
            line = num.zeros((2, 3))
            line[0, i] = s*a
            line[1, i] = s*b
            lines_ned.append(line)

    return lines_ned


def cross3d(a=1., b=0.5):
    lines_ned = []
    for i in range(3):
        for s in (-1., 1.):
            line = num.zeros((2, 3))
            line[0, i] = s*a
            line[1, i] = s*b
            lines_ned.append(line)

    return lines_ned


class Crosshair(object):
    def __init__(self):

        self.mapper_surface = vtk.vtkDataSetMapper()
        self.mapper_position = vtk.vtkDataSetMapper()

        self.actor_surface = vtk.vtkActor()
        self.actor_surface.SetMapper(self.mapper_surface)

        self.actor_position = vtk.vtkActor()
        self.actor_position.SetMapper(self.mapper_position)

        self._color = None
        self.set_color(Color('white'))

    def get_actors(self):
        return [self.actor_surface, self.actor_position]

    def make_multi_polyline(self, lat, lon, depth, size):
        objs = []
        lines_ned = cross3d_flat()
        lines_lld = []
        for line_ned in lines_ned:
            line_ned_sized = size * line_ned
            line_lld = num.zeros(line_ned.shape)
            line_lld[:, :2] = num.vstack(
                od.ne_to_latlon(
                    lat, lon, line_ned_sized[:, 0], line_ned_sized[:, 1])).T

            line_lld[:, 2] = line_ned_sized[:, 2]
            lines_lld.append(line_lld)

        mpl_surface = vtk_util.make_multi_polyline(
            lines_latlondepth=lines_lld)

        lines_ned = cross3d()
        lines_lld = []
        for line_ned in lines_ned:
            line_ned_sized = size * line_ned
            line_lld = num.zeros(line_ned.shape)
            line_lld[:, :2] = num.vstack(
                od.ne_to_latlon(
                    lat, lon, line_ned_sized[:, 0], line_ned_sized[:, 1])).T

            line_lld[:, 2] = depth + line_ned_sized[:, 2]
            lines_lld.append(line_lld)

        mpl_position = vtk_util.make_multi_polyline(
            lines_latlondepth=lines_lld)

        return [mpl_surface, mpl_position]

    def set_geometry(self, lat, lon, depth, size):
        mpl_surface, mpl_position = self.make_multi_polyline(lat, lon, depth, size)
        vtk_util.vtk_set_input(self.mapper_surface, mpl_surface)
        vtk_util.vtk_set_input(self.mapper_position, mpl_position)
        prop = self.actor_surface.GetProperty().SetOpacity(
            min(1.0, abs(depth) / size) * 0.5)

    def set_color(self, color):
        if self._color is None or self._color != color:
            for actor in self.get_actors():
                prop = actor.GetProperty()
                prop.SetDiffuseColor(color.rgb)

            self._color = color


class CrosshairState(ElementState):
    visible = Bool.T(default=False)
    color = Color.T(default=Color.D('white'))

    def __init__(self, *args, **kwargs):
        ElementState.__init__(self, *args, **kwargs)
        self.is_connected = False

    def create(self):
        element = CrosshairElement()
        return element


class CrosshairElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._controls = None
        self._crosshair = None

    def get_name(self):
        return 'Crosshair'

    def bind_state(self, state):
        Element.bind_state(self, state)
        self.register_state_listener3(self.update, state, 'visible')
        self.register_state_listener3(self.update, state, 'color')

    def set_parent(self, parent):
        Element.set_parent(self, parent)
        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=False,
            remove=self.remove)

        upd = self.update
        self._listeners.append(upd)
        self._parent.state.add_listener(upd, 'distance')
        self._parent.state.add_listener(upd, 'lat')
        self._parent.state.add_listener(upd, 'lon')

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._crosshair:
                self._parent.remove_actor(self._crosshair.actor)
                self._crosshair = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def update(self, *args):
        state = self._state
        pstate = self._parent.state

        if state.visible:
            if not self._crosshair:
                self._crosshair = Crosshair()
                for actor in self._crosshair.get_actors():
                    self._parent.add_actor(actor)

            size = pstate.distance * 100.*1000.
            self._crosshair.set_geometry(
                pstate.lat, pstate.lon, pstate.depth, size)
            self._crosshair.set_color(state.color)

        else:
            if self._crosshair:
                for actor in self._crosshair.get_actors():
                    self._parent.remove_actor(actor)

                self._crosshair = None

        self._parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_checkbox, \
                state_bind_combobox_color

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            # color

            layout.addWidget(qw.QLabel('Color'), 0, 0)

            cb = common.strings_to_combobox(
                ['black', 'white', 'scarletred2'])

            layout.addWidget(cb, 0, 1)
            state_bind_combobox_color(self, self._state, 'color', cb)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 1, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            layout.addWidget(qw.QFrame(), 2, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'CrosshairElement',
    'CrosshairState']
