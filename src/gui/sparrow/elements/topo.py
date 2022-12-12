# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import math
import numpy as num

from pyrocko.guts import Bool, Float, StringChoice
from pyrocko import cake, automap, plot
from pyrocko.dataset import topo
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.gui.vtk_util import TrimeshPipe, faces_to_cells, \
    cpt_to_vtk_lookuptable

from .base import Element, ElementState
from .. import state as vstate
from pyrocko import geometry

from .. import common

guts_prefix = 'sparrow'


def ticks(vmin, vmax, vstep):
    vmin = num.floor(vmin / vstep) * vstep
    vmax = num.ceil(vmax / vstep) * vstep
    n = int(round((vmax - vmin) / vstep))
    return vmin + num.arange(n+1) * vstep


def nice_value_circle(step):
    step = plot.nice_value(step)
    if step > 30.:
        return 30.

    return step


class TopoMeshPipe(TrimeshPipe):

    def __init__(
            self, tile, cells_cache=None,
            mask_ocean=False, mask_land=False, **kwargs):

        vertices, faces = geometry.topo_to_mesh(
            tile.y(), tile.x(), tile.data,
            cake.earthradius)

        self._exaggeration = 1.0
        self._tile = tile
        self._raw_vertices = vertices

        centers = geometry.face_centers(vertices, faces)

        altitudes = (geometry.vnorm(centers) - 1.0) * cake.earthradius
        if mask_ocean:
            mask = num.all(tile.data.flatten()[faces] == 0, axis=1)
            altitudes[mask] = None

        if mask_land:
            mask = num.all(tile.data.flatten()[faces] >= 0, axis=1)
            altitudes[mask] = None

        if cells_cache is not None:
            if id(faces) not in cells_cache:
                cells_cache[id(faces)] = faces_to_cells(faces)

            cells = cells_cache[id(faces)]
        else:
            cells = faces_to_cells(faces)

        TrimeshPipe.__init__(
            self, self._raw_vertices, cells=cells, values=altitudes, **kwargs)

    def set_exaggeration(self, exaggeration):
        if self._exaggeration != exaggeration:
            factors = \
                (cake.earthradius + self._tile.data.flatten()*exaggeration) \
                / (cake.earthradius + self._tile.data.flatten())
            self.set_vertices(self._raw_vertices * factors[:, num.newaxis])
            self._exaggeration = exaggeration


class TopoCPTChoice(StringChoice):
    choices = ['light', 'uniform']


class TopoState(ElementState):
    visible = Bool.T(default=True)
    exaggeration = Float.T(default=1.0)
    opacity = Float.T(default=1.0)
    smooth = Bool.T(default=False)
    cpt = TopoCPTChoice.T(default='light')
    shading = vstate.ShadingChoice.T(default='phong')
    resolution_max_factor = Float.T(default=1.0)
    resolution_min_factor = Float.T(default=1.0)
    coverage_factor = Float.T(default=1.0)

    def create(self):
        element = TopoElement()
        return element


class TopoElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self.mesh = None
        self._controls = None

        # region = (-180., 180, -90, 90)
        # self._tile = topo.get('ETOPO1_D8', region)

        self._visible = False
        self._active_meshes = {}
        self._meshes = {}
        self._cells = {}
        self._cpt_name = None
        self._lookuptables = {}

    def get_name(self):
        return 'Topography'

    def bind_state(self, state):
        Element.bind_state(self, state)
        for var in ['visible', 'exaggeration', 'opacity', 'smooth', 'shading',
                    'cpt', 'resolution_min_factor', 'resolution_max_factor',
                    'coverage_factor']:
            self.register_state_listener3(self.update, state, var)

        self._state = state

    def unbind_state(self):
        self._listeners.clear()

    def set_parent(self, parent):
        self._parent = parent

        for var in ['distance', 'lat', 'lon']:
            self.register_state_listener3(
                self.update, self._parent.state, var)

        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=True,
            remove=self.remove)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            for k in self._active_meshes:
                self._parent.remove_actor(self._active_meshes[k].actor)

            self._active_meshes.clear()
            self._meshes.clear()
            self._cells.clear()

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def select_dems(self, delta, region):
        if not self._parent:
            return [], []

        _, size_y = self._parent.renwin.GetSize()

        dmin = 2.0 * delta * 1.0 / float(size_y) \
            / self._state.resolution_max_factor  # [deg]
        dmax = 2.0 * delta * 20.0 \
            * self._state.resolution_min_factor / float(size_y)

        result = [
            topo.select_dem_names(
                k, dmin, dmax, topo.positive_region(region), mode='highest')

            for k in ['ocean', 'land']]

        if not any(result) and delta > 20.:
            return ['ETOPO1_D8'], ['ETOPO1_D8']
        else:
            return result

    def update_cpt(self, cpt_name):
        if cpt_name not in self._lookuptables:
            if cpt_name == 'light':
                topo_cpt_wet = 'light_sea'
                topo_cpt_dry = 'light_land'

            elif cpt_name == 'uniform':
                topo_cpt_wet = 'light_sea_uniform'
                topo_cpt_dry = 'light_land_uniform'

            cpt_wet = automap.read_cpt(topo.cpt(topo_cpt_wet))
            cpt_dry = automap.read_cpt(topo.cpt(topo_cpt_dry))
            cpt_combi = automap.cpt_merge_wet_dry(cpt_wet, cpt_dry)

            lut_combi = cpt_to_vtk_lookuptable(cpt_combi)
            lut_combi.SetNanColor(0.0, 0.0, 0.0, 0.0)

            self._lookuptables[cpt_name] = lut_combi

    def update(self, *args):

        pstate = self._parent.state
        delta = pstate.distance * geometry.r2d * 0.5
        visible = self._state.visible

        self.update_cpt(self._state.cpt)

        step = nice_value_circle(
            max(1./8., min(2**round(math.log(delta) / math.log(2.)), 10.)))

        lat_min, lat_max, lon_min, lon_max, lon_closed = common.cover_region(
            pstate.lat, pstate.lon, delta*self._state.coverage_factor, step)

        if lon_closed:
            lon_max = 180.

        region = lon_min, lon_max, lat_min, lat_max

        dems_ocean, dems_land = self.select_dems(delta, region)

        lat_majors = ticks(lat_min, lat_max-step, step)
        lon_majors = ticks(lon_min, lon_max-step, step)

        wanted = set()
        if visible:
            for ilat, lat in enumerate(lat_majors):
                for ilon, lon in enumerate(lon_majors):
                    lon = ((lon + 180.) % 360.) - 180.

                    region = topo.positive_region(
                        (lon, lon+step, lat, lat+step))

                    for demname in dems_land[:1] + dems_ocean[:1]:
                        mask_ocean = demname.startswith('SRTM') \
                            or demname.startswith('Iceland')

                        mask_land = demname.startswith('ETOPO') \
                            and (dems_land and dems_land[0] != demname)

                        k = (step, demname, region, mask_ocean, mask_land)
                        if k not in self._meshes:
                            tile = topo.get(demname, region)
                            if not tile:
                                continue

                            self._meshes[k] = TopoMeshPipe(
                                tile,
                                cells_cache=self._cells,
                                mask_ocean=mask_ocean,
                                mask_land=mask_land,
                                smooth=self._state.smooth,
                                lut=self._lookuptables[self._state.cpt])

                        wanted.add(k)

                        # prevent adding both, SRTM and ETOPO because
                        # vtk produces artifacts when showing the two masked
                        # meshes (like this, mask_land is never used):
                        break

        unwanted = set()
        for k in self._active_meshes:
            if k not in wanted or not visible:
                unwanted.add(k)

        for k in unwanted:
            self._parent.remove_actor(self._active_meshes[k].actor)
            del self._active_meshes[k]

        for k in wanted:
            if k not in self._active_meshes:
                m = self._meshes[k]
                self._active_meshes[k] = m
                self._parent.add_actor(m.actor)

            self._active_meshes[k].set_exaggeration(self._state.exaggeration)
            self._active_meshes[k].set_opacity(self._state.opacity)
            self._active_meshes[k].set_smooth(self._state.smooth)
            self._active_meshes[k].set_shading(self._state.shading)
            self._active_meshes[k].set_lookuptable(
                self._lookuptables[self._state.cpt])

        self._parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_slider, state_bind_checkbox, \
                state_bind_combobox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            iy = 0

            # exaggeration

            layout.addWidget(qw.QLabel('Exaggeration'), iy, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(2000)
            layout.addWidget(slider, iy, 1)

            state_bind_slider(self, state, 'exaggeration', slider, factor=0.01)

            iy += 1

            # opacity

            layout.addWidget(qw.QLabel('Opacity'), iy, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(1000)
            layout.addWidget(slider, iy, 1)

            state_bind_slider(self, state, 'opacity', slider, factor=0.001)

            iy += 1

            # high resolution

            layout.addWidget(qw.QLabel('High-Res Factor'), iy, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(500)
            slider.setMaximum(4000)
            layout.addWidget(slider, iy, 1)

            state_bind_slider(
                self, state, 'resolution_max_factor', slider, factor=0.001)

            iy += 1

            # low resolution

            layout.addWidget(qw.QLabel('Low-Res Factor'), iy, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(500)
            slider.setMaximum(4000)
            layout.addWidget(slider, iy, 1)

            state_bind_slider(
                self, state, 'resolution_min_factor', slider, factor=0.001)

            iy += 1

            # low resolution

            layout.addWidget(qw.QLabel('Coverage Factor'), iy, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(500)
            slider.setMaximum(4000)
            layout.addWidget(slider, iy, 1)

            state_bind_slider(
                self, state, 'coverage_factor', slider, factor=0.001)

            iy += 1

            cb = common.string_choices_to_combobox(TopoCPTChoice)
            layout.addWidget(qw.QLabel('CPT'), iy, 0)
            layout.addWidget(cb, iy, 1)
            state_bind_combobox(self, state, 'cpt', cb)

            iy += 1

            cb = qw.QCheckBox('Smooth')
            layout.addWidget(cb, iy, 0)
            state_bind_checkbox(self, state, 'smooth', cb)

            cb = common.string_choices_to_combobox(vstate.ShadingChoice)
            layout.addWidget(cb, iy, 1)
            state_bind_combobox(self, state, 'shading', cb)

            iy += 1

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, iy, 0)
            state_bind_checkbox(self, state, 'visible', cb)

            iy += 1

            layout.addWidget(qw.QFrame(), iy, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'TopoElement',
    'TopoState',
]
