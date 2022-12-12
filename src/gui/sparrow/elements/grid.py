# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

import vtk

from pyrocko import util, plot
from pyrocko.guts import Bool, Float
from pyrocko.gui.qt_compat import qw
from pyrocko.color import Color


from pyrocko.gui import vtk_util
from .base import Element, ElementState
from .. import common
from pyrocko.geometry import r2d, d2r

km = 1000.

guts_prefix = 'sparrow'


def nice_value_circle(step):
    step = plot.nice_value(step)
    if step > 30.:
        return 30.

    return step


def ticks(vmin, vmax, vstep):
    vmin = num.floor(vmin / vstep) * vstep
    vmax = num.ceil(vmax / vstep) * vstep
    n = int(round((vmax - vmin) / vstep))
    return vmin + num.arange(n+1) * vstep


class LatLonGrid(object):
    def __init__(self, r, step_major, step_minor, lat, lon, delta, depth):

        lat_min, lat_max, lon_min, lon_max, lon_closed = common.cover_region(
            lat, lon, delta, step_major, avoid_poles=True)

        if delta < 30.:
            step_major_lon = nice_value_circle(step_major/num.cos(lat*d2r))
        else:
            step_major_lon = step_major

        lat_majors = ticks(lat_min, lat_max, step_major)
        lon_majors = ticks(lon_min, lon_max, step_major_lon)

        lat_minors = util.arange2(lat_min, lat_max, step_minor)

        if lon_closed:
            lon_minors = util.arange2(-180., 180., step_minor)
        else:
            lon_minors = util.arange2(lon_min, lon_max, step_minor)

        lines = []
        for lat_major in lat_majors:
            points = num.zeros((lon_minors.size, 2))
            points[:, 0] = lat_major
            points[:, 1] = lon_minors
            lines.append(points)

        for lon_major in lon_majors:
            points = num.zeros((lat_minors.size, 2))
            points[:, 0] = lat_minors
            points[:, 1] = lon_major
            lines.append(points)

        polyline_grid = vtk_util.make_multi_polyline(
            lines_latlon=lines, depth=depth)

        mapper = vtk.vtkDataSetMapper()
        vtk_util.vtk_set_input(mapper, polyline_grid)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        prop = actor.GetProperty()
        self.prop = prop

        prop.SetOpacity(0.15)

        self._color = None
        self.set_color(Color('white'))

        self.actor = actor

    def set_color(self, color):
        if self._color is None or self._color != color:
            self.prop.SetDiffuseColor(color.rgb)
            self._color = color


class GridState(ElementState):
    visible = Bool.T(default=True)
    color = Color.T(default=Color.D('white'))
    depth = Float.T(default=-1.0*km)

    def create(self):
        element = GridElement()
        return element


class GridElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._controls = None
        self._grid = None
        self._stepsizes = self.get_stepsizes(10.)

    def get_name(self):
        return 'Grid'

    def bind_state(self, state):
        Element.bind_state(self, state)
        self.register_state_listener3(self.update, state, 'visible')
        self.register_state_listener3(self.update, state, 'color')
        self.register_state_listener3(self.update, state, 'depth')

    def set_parent(self, parent):
        Element.set_parent(self, parent)
        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=True,
            remove=self.remove)

        for var in ['distance', 'lat', 'lon']:
            self.register_state_listener3(self.update, self._parent.state, var)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._grid:
                self._parent.remove_actor(self._grid.actor)
                self._grid = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def get_stepsizes(self, distance):
        factor = 10.
        step_major = nice_value_circle(min(10.0, factor * distance))
        step_minor = min(1.0, step_major)
        return step_major, step_minor

    def update(self, *args):
        state = self._state
        pstate = self._parent.state

        stepsizes = self.get_stepsizes(pstate.distance)
        if self._grid:
            self._parent.remove_actor(self._grid.actor)
            self._grid = None

        if state.visible and not self._grid:
            delta = pstate.distance * r2d * 0.5
            self._grid = LatLonGrid(
                1.0, stepsizes[0], stepsizes[1], pstate.lat, pstate.lon, delta,
                state.depth)
            self._parent.add_actor(self._grid.actor)

        if self._grid:
            self._grid.set_color(state.color)

        self._parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_checkbox, \
                state_bind_combobox_color, state_bind_lineedit

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            # color

            layout.addWidget(qw.QLabel('Color'), 0, 0)

            cb = common.strings_to_combobox(
                ['black', 'white'])

            layout.addWidget(cb, 0, 1)
            state_bind_combobox_color(self, self._state, 'color', cb)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 1, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            layout.addWidget(qw.QLabel('Depth [km]'), 2, 0)
            le = qw.QLineEdit()
            layout.addWidget(le, 2, 1)
            state_bind_lineedit(
                self, self._state, 'depth', le,
                from_string=lambda s: float(s)*1000.,
                to_string=lambda v: str(v/1000.))

            layout.addWidget(qw.QFrame(), 3, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'GridElement',
    'GridState']
