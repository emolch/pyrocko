# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

import vtk

from pyrocko import util, plot
from pyrocko.guts import Bool
from pyrocko.gui.qt_compat import qw


from pyrocko.gui import vtk_util
from .base import Element, ElementState
from .. import common
from pyrocko.geometry import r2d

guts_prefix = 'sparrow'


class LatLonGrid(object):
    def __init__(self, r, step_major, step_minor, lat, lon, delta):

        lat_min, lat_max, lon_min, lon_max, lon_closed = common.cover_region(
            lat, lon, delta, step_major)

        lat_majors = util.arange2(lat_min, lat_max, step_major)
        lon_majors = util.arange2(lon_min, lon_max, step_major)

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

        polyline_grid = vtk_util.make_multi_polyline(lines_latlon=lines)

        mapper = vtk.vtkDataSetMapper()
        vtk_util.vtk_set_input(mapper, polyline_grid)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        prop = actor.GetProperty()
        prop.SetDiffuseColor(1, 1, 1)
        prop.SetOpacity(0.1)

        self.actor = actor


class GridState(ElementState):
    visible = Bool.T(default=True)

    def create(self):
        element = GridElement()
        element.bind_state(self)
        return element


class GridElement(Element):

    def __init__(self):
        Element.__init__(self)
        self.parent = None
        self._controls = None
        self._grid = None
        self._stepsizes = self.get_stepsizes(10.)

    def get_name(self):
        return 'Grid'

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        self._state = state

    def set_parent(self, parent):
        self.parent = parent
        self.parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)

        upd = self.update
        self._listeners.append(upd)
        self.parent.state.add_listener(upd, 'distance')
        self.parent.state.add_listener(upd, 'lat')
        self.parent.state.add_listener(upd, 'lon')

        self.update()

    def get_stepsizes(self, distance):
        factor = 10.
        step_major = plot.nice_value(min(10.0, factor * distance))
        step_minor = min(1.0, step_major)
        return step_major, step_minor

    def update(self, *args):
        state = self._state
        pstate = self.parent.state

        stepsizes = self.get_stepsizes(pstate.distance)
        if self._grid:
            self.parent.remove_actor(self._grid.actor)
            self._grid = None

        if state.visible and not self._grid:
            delta = pstate.distance * r2d * 0.5
            self._grid = LatLonGrid(
                1.0, stepsizes[0], stepsizes[1], pstate.lat, pstate.lon, delta)
            self.parent.add_actor(self._grid.actor)

        self.parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_checkbox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 0, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            layout.addWidget(qw.QFrame(), 1, 0)

        self._controls = frame

        return self._controls


__all__ = [
    'GridElement',
    'GridState']
