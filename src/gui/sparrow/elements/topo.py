# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

from pyrocko.guts import Bool, Float
from pyrocko import cake, plot, util
from pyrocko.dataset import topo
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.gui.vtk_util import TrimeshPipe
from .base import Element, ElementState
from pyrocko import geometry

from .. import common

guts_prefix = 'sparrow'


class TopoState(ElementState):
    visible = Bool.T(default=True)
    exaggeration = Float.T(default=1.0)

    def create(self):
        element = TopoElement()
        element.bind_state(self)
        return element


class TopoElement(Element):

    def __init__(self):
        Element.__init__(self)
        self.parent = None
        self.mesh = None
        self._controls = None

        # region = (-180., 180, -90, 90)
        # self._tile = topo.get('ETOPO1_D8', region)
        self._visible = False
        self._active_meshes = {}
        self._meshes = {}

    def get_name(self):
        return 'Topography'

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'exaggeration')
        self._state = state

    def set_parent(self, parent):
        self.parent = parent

        upd = self.update
        self._listeners.append(upd)
        self.parent.state.add_listener(upd, 'distance')
        self.parent.state.add_listener(upd, 'lat')
        self.parent.state.add_listener(upd, 'lon')

        self.parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def select_dems(self, delta, region):
        if not self.parent:
            return

        _, size_y = self.parent.renwin.GetSize()

        dmin = 2.0 * delta / (0.5 * size_y)
        dmax = 2.0 * delta / (0.05 * size_y)

        return [
            topo.select_dem_names(k, dmin, dmax, topo.positive_region(region))
            for k in ['ocean', 'land']]

    def update(self, *args):

        tstate = self._state
        pstate = self.parent.state
        delta = min(10., pstate.distance * geometry.r2d * 0.5)

        step = plot.nice_value(delta / 4.)
        lat_min, lat_max, lon_min, lon_max, lon_closed = common.cover_region(
            pstate.lat, pstate.lon, delta, step)

        if lon_closed:
            lon_max = 180.

        region = lon_min, lon_max, lat_min, lat_max

        dems_ocean, dems_land = self.select_dems(delta, region)
        print('topo', region, dems_ocean, dems_land)

        lat_majors = util.arange2(lat_min, lat_max, step)
        lon_majors = util.arange2(lon_min, lon_max, step)

        wanted = set()
        for ilat, lat in enumerate(lat_majors):
            for ilon, lon in enumerate(lon_majors):
                region = topo.positive_region((lon, lon+step, lat, lat+step))

                for demname in dems_land[:1] + dems_ocean[:1]:
                    k = (step, demname, region)
                    if k not in self._meshes:
                        print('load topo', k)
                        t = topo.get(demname, region)
                        vertices, faces = geometry.topo_to_mesh(
                            t.y(), t.x(), t.data*tstate.exaggeration,
                            cake.earthradius)

                        self._meshes[k] = t, TrimeshPipe(
                            vertices, faces, smooth=True)

                    wanted.add(k)
                    break

        unwanted = set()
        for k in self._active_meshes:
            if k not in wanted:
                unwanted.add(k)

        for k in unwanted:
            self.parent.remove_actor(self._active_meshes[k].actor)
            del self._active_meshes[k]

        for k in wanted:
            if k not in self._active_meshes:
                m = self._meshes[k][1]
                self._active_meshes[k] = m
                self.parent.add_actor(m.actor)

        if False:
            if tstate.visible:
                if self.mesh is None:
                    t = self._tile
                    vertices, faces = geometry.topo_to_mesh(
                        t.y(), t.x(), t.data*tstate.exaggeration,
                        cake.earthradius)

                    self.mesh = TrimeshPipe(vertices, faces, smooth=True)

                else:
                    t = self._tile
                    vertices = geometry.topo_to_vertices(
                        t.y(), t.x(), t.data*tstate.exaggeration,
                        cake.earthradius)

                    self.mesh.set_vertices(vertices)

                if not self._visible and tstate.visible:
                    self.parent.add_actor(self.mesh.actor)
                    self._visible = tstate.visible

                if self._visible and not tstate.visible:
                    self.parent.remove_actor(self.mesh.actor)
                    self._visible = tstate.visible

        self.parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            layout.addWidget(qw.QLabel('Exaggeration'), 0, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Minimum))
            slider.setMinimum(0)
            slider.setMaximum(5)
            # slider.setSingleStep(1)
            # slider.setPageStep(1)
            layout.addWidget(slider, 0, 1)

            state_bind_slider(self, state, 'exaggeration', slider)

        self._controls = frame

        return self._controls


__all__ = [
    'TopoElement',
    'TopoState',
]
