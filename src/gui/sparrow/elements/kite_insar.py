# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import copy
import logging
try:
    from kite import Scene
except ImportError:
    Scene = None

import numpy as num

from pyrocko import geometry, cake
from pyrocko.guts import Bool, String, List, Float
from pyrocko.gui.qt_compat import qw, qc
from pyrocko.gui.vtk_util import TrimeshPipe, faces_to_cells

from .. import common

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

    def y(self):
        # TODO how to handle N given in m
        frame = self._scene.frame
        y = num.zeros(frame.rows + 1)
        y[0] = frame.N[0] - 0.5 * frame.dN
        y[1:] = frame.N + 0.5 * frame.dN
        y += frame.llLat
        return y

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

        assert nlat > 1 and nlon > 1
        assert data_center.shape == (nlat-1, nlon-1)

        ele = num.zeros((nlat, nlon))
        ele[:-1, :-1] = data_center #* 100000.
        vertices, faces = geometry.topo_to_mesh(
            lat_edge, lon_edge, ele, cake.earthradius)

        self._raw_vertices = vertices

        if cells_cache is not None:
            if id(faces) not in cells_cache:
                cells_cache[id(faces)] = faces_to_cells(faces)

            cells = cells_cache[id(faces)]
        else:
            cells = faces_to_cells(faces)

        data_center = data_center.flatten()

        TrimeshPipe.__init__(
            self, vertices,
            cells=cells, values=data_center, **kwargs)


class KiteSceneElement(ElementState):
    visible = Bool.T(default=True)
    filename = String.T()
    scene = None


class KiteState(ElementState):
    visible = Bool.T(default=True)
    scenes = List.T(KiteSceneElement.T(), default=[])
    opacity = Float.T(default=1.0)
    cpt = CPTState.T(default=CPTState.D())

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
        self.talkie_connect(state, ['visible', 'scenes', 'opacity'], self.update)

        self.cpt_handler.bind_state(state.cpt, self.update)

    def unbind_state(self):
        self.cpt_handler.unbind_state()
        Element.unbind_state(self)

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
            for mesh in self._meshes.values():
                self._parent.remove_actor(mesh.actor)

            self._meshes.clear()
            self._cells.clear()

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self.cpt_handler.remove_cbar_pipe()
            self._parent.update_view()
            self._parent = None

    def _load_scene_from_fn(self, fn):
        try:
            scene = Scene.load(fn)
        except ImportError:
            qw.QMessageBox.warning(
                self._parent, 'Import Error',
                'Could not load Kite scene from %s' % fn)
            return

        if scene.frame.spacing != 'degree':
            logger.warning(
                'Sparrow requires Scene spacing in degrees. '
                'Skipped %s', fn)

            return

        return scene

    def open_load_scene_dialog(self, *args):
        caption = 'Select one or more Kite scenes to open'

        fns, _ = qw.QFileDialog.getOpenFileNames(
            self._parent, caption,
            filter='YAML file (*.yml *.yaml)',
            options=common.qfiledialog_options)

        for fname in fns:
            scene = self._load_scene_from_fn(fname)

            if scene is None:
                continue

            logger.debug('Adding Kite scene %s', fname)

            scene_element = KiteSceneElement(filename=fname)
            scene_element.scene = scene
            self._state.add_scene(scene_element)

        self.update()

    def clear_scenes(self, *args):
        logger.debug('Clearing all loaded Kite scenes')

        for mesh in self._meshes.values():
            self._parent.remove_actor(mesh.actor)

        self._meshes.clear()
        self._state.scenes = []

        self.cpt_handler.remove_cbar_pipe()
        self.update()

    def update_cpt(self):
        self.cpt_handler.update_cpt()
        self.cpt_handler.update_cbar("Displacement [m]")

    def update(self, *args):
        state = self._state

        for mesh in self._meshes.values():
            self._parent.remove_actor(mesh.actor)

        if state.visible:
            for scene_element in state.scenes:
                logger.debug('Drawing Kite scene')

                if scene_element.scene is None:
                    scene_element.scene = self._load_scene_from_fn(
                        scene_element.filename)

                scene = scene_element.scene

                k = (scene, state.cpt.cpt_name)
                if k not in self._meshes:
                    scene_tile = SceneTileAdapter(scene)
                    cpt = copy.deepcopy(
                        self.cpt_handler._cpts[state.cpt.cpt_name])

                    mesh = KiteMeshPipe(
                        scene_tile,
                        cells_cache=None,
                        cpt=cpt,
                        backface_culling=False)

                    values = scene_tile.data.flatten()
                    self.cpt_handler._values = values

                    mesh.set_shading('phong')
                    
                    self._meshes[k] = mesh
                    
                mesh = self._meshes[k]
                mesh.set_opacity(state.opacity)
                self.update_cpt()
                mesh.set_lookuptable(self.cpt_handler._lookuptable)

                if scene_element.visible:
                    self._parent.add_actor(mesh.actor)

        else:
            self.cpt_handler.remove_cbar_pipe()

        self._parent.update_view()

    def _get_controls(self):

        state = self._state

        if not self._controls:
            from ..state import state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            pb_load = qw.QPushButton('Add Scene')
            pb_load.clicked.connect(self.open_load_scene_dialog)
            layout.addWidget(pb_load, 0, 1)

            pb_clear = qw.QPushButton('Clear Scenes')
            pb_clear.clicked.connect(self.clear_scenes)
            layout.addWidget(pb_clear, 0, 2)

            # opacity
            if False:
                layout.addWidget(qw.QLabel('Opacity'), 1, 0)

                slider = qw.QSlider(qc.Qt.Horizontal)
                slider.setSizePolicy(
                    qw.QSizePolicy(
                        qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
                slider.setMinimum(0)
                slider.setMaximum(1000)
                layout.addWidget(slider, 1, 1)

                state_bind_slider(self, state, 'opacity', slider, factor=0.001)

            # color maps
            self.cpt_handler.cpt_controls(
                self._parent, state.cpt, layout)

            layout.addWidget(qw.QFrame(), 2, 0, 1, 3)

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
