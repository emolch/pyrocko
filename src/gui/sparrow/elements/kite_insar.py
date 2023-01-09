# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import copy
import logging
try:
    from kite import Scene
except ImportError as e:
    print(e)
    Scene = None

import numpy as num

from pyrocko import geometry, cake
from pyrocko.guts import Bool, String, List
from pyrocko.gui.qt_compat import qw
from pyrocko.gui.vtk_util import TrimeshPipe, faces_to_cells

from .. import common

from .topo import TopoMeshPipe
from .base import Element, ElementState, CPTHandler, CPTState

logger = logging.getLogger('kite_scene')
guts_prefix = 'sparrow'

km = 1e3
d2r = num.pi/180.


class SceneTileAdapter(object):

    def __init__(self, scene):
        self._scene = scene

    def x(self):
        # TODO how to handle E given in m
        frame = self._scene.frame
        x = num.zeros(frame.cols + 1)
        x[0] = frame.E[0] - 0.5 * frame.dE
        x[1:] = frame.E + 0.5 * frame.dE
        x += frame.llLon
        return x
        # return self._scene.frame.E + self._scene.frame.llLon

    def y(self):
        # TODO how to handle N given in m
        frame = self._scene.frame
        y = num.zeros(frame.rows + 1)
        y[0] = frame.N[0] - 0.5 * frame.dN
        y[1:] = frame.N + 0.5 * frame.dN
        y += frame.llLat
        return y
        # return self._scene.frame.N + self._scene.frame.llLat

    @property
    def data(self):
        disp = self._scene.displacement
        disp[num.isnan(disp)] = None
        return disp


class KiteMeshPipe(TrimeshPipe):
    def __init__(self, tile, cells_cache=None, **kwargs):
        lat_edge = tile.y()
        lon_edge = tile.x()
        data_center = tile.data

        nlat = lat_edge.size
        nlon = lon_edge.size
        nvertices = nlat * nlon

        assert nlat > 1 and nlon > 1
        assert data_center.shape == (nlat-1, nlon-1)

        rtp = num.empty((nvertices, 3))
        rtp[:, 0] = 1.0
        rtp[:, 1] = (num.repeat(lat_edge, nlon) + 90.) * d2r
        rtp[:, 2] = num.tile(lon_edge, nlat) * d2r
        vertices = geometry.rtp2xyz(rtp)

        faces = geometry.topo_to_faces_quad(nlat, nlon)

        self._tile = tile
        self._raw_vertices = vertices

        if cells_cache is not None:
            if id(faces) not in cells_cache:
                cells_cache[id(faces)] = faces_to_cells(faces)

            cells = cells_cache[id(faces)]
        else:
            cells = faces_to_cells(faces)

        data_center = data_center.flatten()

        TrimeshPipe.__init__(
            self, self._raw_vertices,
            cells=cells, values=data_center, **kwargs)


class KiteSceneElement(ElementState):
    visible = Bool.T(default=True)
    filename = String.T()
    scene = None


class KiteState(ElementState):
    visible = Bool.T(default=True)
    scenes = List.T(KiteSceneElement.T(), default=[])
    cpt = CPTState.T(default=CPTState.D(cpt_name='seismic'))

    def create(self):
        element = KiteElement()
        return element

    def add_scene(self, scene):
        self.scenes.append(scene)

    def remove_scene(self, scene):
        if scene in self.scenes:
            self.scenes.remove(scene)


class KiteElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._controls = None
        self._meshes = {}
        self._cells = {}
        self.cpt_handler = CPTHandler()

    def bind_state(self, state):
        Element.bind_state(self, state)
        for var in ['visible', 'scenes']:
            self.register_state_listener3(self.update, state, var)

        self.cpt_handler.bind_state(state.cpt, self.update)

    def unbind_state(self):
        self.cpt_handler.unbind_state()
        self._listeners = []
        self._state = None

    def get_name(self):
        return 'Kite InSAR Scenes'

    def set_parent(self, parent):
        if Scene is None:
            qw.QMessageBox.warning(
                parent, 'Import Error',
                'Software package Kite is needed to display InSAR scenes!')
            return

        self._parent = parent
        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=True,
            remove=self.remove)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            for mesh in self._meshes:
                self._parent.remove_actor(mesh.actor)

            self._meshes.clear()
            self._cells.clear()

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def open_load_scene_dialog(self, *args):
        caption = 'Select one or more Kite scenes to open'

        fns, _ = qw.QFileDialog.getOpenFileNames(
            self._parent, caption,
            filter='YAML file (*.yml *.yaml)',
            options=common.qfiledialog_options)

        for fname in fns:
            try:
                scene = Scene.load(fname)
            except ImportError:
                qw.QMessageBox.warning(
                    self._parent, 'Import Error',
                    'Could not load Kite scene from %s' % fname)
                return

            if scene.frame.spacing != 'degree':
                logger.warning(
                    'Sparrow requires Scene spacing in degrees. '
                    'Skipped %s', fname)

                continue

            logger.info('Adding Kite scene %s', fname)

            scene_element = KiteSceneElement(filename=fname)
            scene_element.scene = scene
            self._state.add_scene(scene_element)

        self.update()

    def clear_scenes(self, *args):
        logger.info('Clearing all loaded Kite scenes')

        for mesh in self._meshes.values():
            self._parent.remove_actor(mesh.actor)

        self._meshes.clear()
        self._state.scenes = []

        self.update()

    def update(self, *args):
        state = self._state

        for mesh in self._meshes.values():
            self._parent.remove_actor(mesh.actor)

        if self._state.visible:
            for scene_element in state.scenes:
                logger.info('Drawing Kite scene')
                scene = scene_element.scene
                scene_tile = SceneTileAdapter(scene)

                k = (scene_tile, state.cpt.cpt_name)

                if k not in self._meshes:
                    # TODO handle different limits of multiples scenes?!

                    cpt = copy.deepcopy(
                        self.cpt_handler._cpts[state.cpt.cpt_name])

                    mesh = KiteMeshPipe(
                        scene_tile,
                        cells_cache=None,
                        cpt=cpt,
                        backface_culling=False)

                    values = scene_tile.data.flatten()
                    self.cpt_handler._values = values
                    self.cpt_handler.update_cpt()

                    mesh.set_shading('phong')
                    mesh.set_lookuptable(self.cpt_handler._lookuptable)

                    self._meshes[k] = mesh
                else:
                    mesh = self._meshes[k]
                    self.cpt_handler.update_cpt()

                if scene_element.visible:
                    self._parent.add_actor(mesh.actor)

        self._parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_checkbox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            pb_load = qw.QPushButton('Add Scene')
            pb_load.clicked.connect(self.open_load_scene_dialog)
            layout.addWidget(pb_load, 0, 1)

            pb_clear = qw.QPushButton('Clear Scenes')
            pb_clear.clicked.connect(self.clear_scenes)
            layout.addWidget(pb_clear, 0, 2)

            self.cpt_handler.cpt_controls(
                self._parent, self._state.cpt, layout)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 4, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            layout.addWidget(qw.QFrame(), 5, 0, 1, 3)

            self._controls = frame

            self._update_controls()

        return self._controls

    def _update_controls(self):
        self.cpt_handler._update_cpt_combobox()
        self.cpt_handler._update_cptscale_lineedit()


__all__ = [
    'KiteState',
    'KiteElement'
]
