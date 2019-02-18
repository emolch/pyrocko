# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import math
import numpy as num

from pyrocko.guts import Bool, Float, StringChoice
from pyrocko import cake, util, automap
from pyrocko.dataset import topo
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.gui.vtk_util import TrimeshPipe, faces_to_cells, \
    cpt_to_vtk_lookuptable

from .base import Element, ElementState
from pyrocko import geometry

from .. import common

guts_prefix = 'sparrow'


class TopoMeshPipe(TrimeshPipe):

    def __init__(self, tile, cells_cache, mask_ocean=False, **kwargs):

        vertices, faces = geometry.topo_to_mesh(
            tile.y(), tile.x(), tile.data,
            cake.earthradius)

        self._exaggeration = 1.0
        self._tile = tile
        self._raw_vertices = vertices

        centers = geometry.face_centers(vertices, faces)

        altitudes = (geometry.vnorm(centers) - 1.0) * cake.earthradius
        if mask_ocean:
            altitudes[altitudes <= 1.0] = None

        if id(faces) not in cells_cache:
            cells_cache[id(faces)] = faces_to_cells(faces)

        cells = cells_cache[id(faces)]

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

    def create(self):
        element = TopoElement()
        element.bind_state(self)
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
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'exaggeration')
        state.add_listener(upd, 'opacity')
        state.add_listener(upd, 'smooth')
        state.add_listener(upd, 'cpt')
        self._state = state

    def unbind_state(self):
        self._listeners.clear()

    def set_parent(self, parent):
        self._parent = parent

        upd = self.update
        self._listeners.append(upd)
        self._parent.state.add_listener(upd, 'distance')
        self._parent.state.add_listener(upd, 'lat')
        self._parent.state.add_listener(upd, 'lon')

        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
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

        if delta > 20.:
            return ['ETOPO1_D8'], ['ETOPO1_D8']

        _, size_y = self._parent.renwin.GetSize()

        dmin = 2.0 * delta * 1.0 / float(size_y)  # [deg]
        dmax = 2.0 * delta * 20.0 / float(size_y)

        return [
            topo.select_dem_names(
                k, dmin, dmax, topo.positive_region(region), mode='highest')

            for k in ['ocean', 'land']]

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

        step = max(1./8., min(2**round(math.log(delta) / math.log(2.)), 10.))
        lat_min, lat_max, lon_min, lon_max, lon_closed = common.cover_region(
            pstate.lat, pstate.lon, delta*1.0, step)

        if lon_closed:
            lon_max = 180.

        region = lon_min, lon_max, lat_min, lat_max

        dems_ocean, dems_land = self.select_dems(delta, region)

        lat_majors = util.arange2(lat_min, lat_max-step, step)
        lon_majors = util.arange2(lon_min, lon_max-step, step)

        wanted = set()
        if visible:
            for ilat, lat in enumerate(lat_majors):
                for ilon, lon in enumerate(lon_majors):
                    lon = ((lon + 180.) % 360.) - 180.

                    region = topo.positive_region((lon, lon+step, lat, lat+step))

                    for demname in dems_land[:1] + dems_ocean[:1]:
                        k = (step, demname, region)
                        if k not in self._meshes:
                            tile = topo.get(demname, region)
                            if not tile:
                                continue

                            self._meshes[k] = TopoMeshPipe(
                                tile,
                                cells_cache=self._cells,
                                mask_ocean=demname.startswith('SRTM'),
                                smooth=self._state.smooth,
                                lut=self._lookuptables[self._state.cpt])

                        wanted.add(k)
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
            self._active_meshes[k].set_lookuptable(
                self._lookuptables[self._state.cpt])

        # print(len(self._meshes), len(self._active_meshes))

        self._parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_slider, state_bind_checkbox, \
                state_bind_combobox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            # exaggeration

            layout.addWidget(qw.QLabel('Exaggeration'), 0, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(2000)
            layout.addWidget(slider, 0, 1)

            state_bind_slider(self, state, 'exaggeration', slider, factor=0.01)

            # opacity

            layout.addWidget(qw.QLabel('Opacity'), 1, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(1000)
            layout.addWidget(slider, 1, 1)

            state_bind_slider(self, state, 'opacity', slider, factor=0.001)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 2, 0)
            state_bind_checkbox(self, state, 'visible', cb)

            cb = qw.QCheckBox('Smooth')
            layout.addWidget(cb, 2, 1)
            state_bind_checkbox(self, state, 'smooth', cb)

            cb = common.string_choices_to_combobox(TopoCPTChoice)
            layout.addWidget(qw.QLabel('CPT'), 3, 0)
            layout.addWidget(cb, 3, 1)
            state_bind_combobox(self, state, 'cpt', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, 4, 1)
            pb.clicked.connect(self.unset_parent)

            layout.addWidget(qw.QFrame(), 5, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'TopoElement',
    'TopoState',
]
