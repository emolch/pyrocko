# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import logging
try:
    from kite import Scene
except ImportError:
    Scene = None

from pyrocko import automap
from pyrocko.guts import Bool, String, List
from pyrocko.gui.qt_compat import qw, fnpatch
from pyrocko.dataset import topo
from pyrocko.gui.vtk_util import cpt_to_vtk_lookuptable

from .. import common

from .topo import TopoMeshPipe
from .base import Element, ElementState

logger = logging.getLogger('kite_scene')
guts_prefix = 'sparrow'

km = 1e3


class SceneTileAdapter(object):

    def __init__(self, scene):
        self._scene = scene

    def x(self):
        return self._scene.frame.E + self._scene.frame.llLon

    def y(self):
        return self._scene.frame.N + self._scene.frame.llLat

    @property
    def data(self):
        return self._scene.get_elevation()


class KiteSceneElement(ElementState):
    visible = Bool.T(default=True)
    filename = String.T()
    scene = None


class KiteState(ElementState):
    visible = Bool.T(default=True)
    scenes = List.T(KiteSceneElement.T(), default=[])

    def create(self):
        element = KiteElement()
        element.bind_state(self)
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

    def bind_state(self, state):
        self._listeners.append(
            state.add_listener(self.update, 'visible'))
        self._listeners.append(
            state.add_listener(self.update, 'scenes'))
        self._state = state

    def get_name(self):
        return 'Kite InSAR Scenes'

    def set_parent(self, parent):
        if not Scene:
            qw.QMessageBox.warning(
                parent, 'Import Error',
                'Software package Kite is needed to display InSAR scenes!')
            return

        self._parent = parent
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def open_load_scene_dialog(self, *args):
        caption = 'Select one or more Kite scenes to open'

        fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
            self._parent, caption,
            filter='YAML file (*.yml *.yaml)',
            options=common.qfiledialog_options))

        for fname in fns:
            try:
                scene = Scene.load(fname)
            except ImportError:
                return
            logger.info('adding Kite scene %s', fname)

            scene_element = KiteSceneElement(filename=fname)
            scene_element.scene = scene
            self._state.add_scene(scene_element)

        self.update()

    def update(self, *args):
        cpt_displacement = cpt_to_vtk_lookuptable(
            automap.read_cpt(topo.cpt('light_land')))

        if self._state.visible:

            for scene_element in self._state.scenes:
                print('drawing scene')
                scene = scene_element.scene

                if scene_element not in self._meshes:
                    scene_tile = SceneTileAdapter(scene)
                    mesh = TopoMeshPipe(
                        scene_tile,
                        cells_cache=None,
                        lut=cpt_displacement)
                    mesh.set_values(scene.displacement.T)
                    self._meshes[scene_element] = mesh

                mesh = self._meshes[scene_element]
                mesh.set_shading('phong')
                if scene_element.visible:
                    self._parent.add_actor(mesh.actor)
                else:
                    self._parent.remove_actor(mesh.actor)

        self._parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_checkbox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            pb_load = qw.QPushButton('Add Scene')
            pb_load.clicked.connect(self.open_load_scene_dialog)
            layout.addWidget(pb_load, 0, 0)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 1, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            self._controls = frame

        return self._controls


__all__ = [
    'KiteState',
    'KiteElement'
]
