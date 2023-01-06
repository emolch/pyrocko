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

from pyrocko import automap
from pyrocko.guts import Bool, String, List
from pyrocko.gui.qt_compat import qw
from pyrocko.dataset import topo
from pyrocko.gui.vtk_util import cpt_to_vtk_lookuptable

from .. import common

from .topo import TopoMeshPipe
from .base import Element, ElementState, CPTHandler, CPTState

logger = logging.getLogger('kite_scene')
guts_prefix = 'sparrow'

km = 1e3


class SceneTileAdapter(object):

    def __init__(self, scene):
        self._scene = scene

        # import matplotlib.pyplot as plt
        # coords = scene.frame.coordinates
        # scat = plt.scatter(coords[:, 0], coords[:, 1], self.data)
        # x = num.tile(self.x(), self.y().shape[0])
        # y = num.repeat(self.y(), self.x().shape[0])
        # x = self.x()
        # y = self.y()
        # scat = plt.pcolormesh(x, y, self.data)
        # plt.colorbar(scat)
        # plt.show()
        # print(self._scene.frame.coordinates)

    def x(self):
        # TODO how to handle E given in m
        # return num.arange(5) * 2.
        return self._scene.frame.E + self._scene.frame.llLon

    def y(self):
        # TODO how to handle N given in m
        # return num.arange(10) * 2.
        return self._scene.frame.N + self._scene.frame.llLat

    @property
    def data(self):
        # import numpy as num
        # data = num.ones((self.y().shape[0], self.x().shape[0]))
        # # data = num.ones_like(self._scene.displacement)
        # x = num.linspace(-10, 10, data.shape[1])
        # y = num.linspace(-10, 10, data.shape[0])
        # xx, yy = num.meshgrid(x, y)
        # dist = num.sqrt(xx**2 + yy**2)

        # data = num.exp(-dist)
        # return data
        return self._scene.displacement


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
            logger.info('adding Kite scene %s', fname)

            scene_element = KiteSceneElement(filename=fname)
            scene_element.scene = scene
            self._state.add_scene(scene_element)

        self.update()

    def update(self, *args):
        from scipy.signal import convolve2d
        state = self._state

        for mesh in self._meshes.values():
            self._parent.remove_actor(mesh.actor)

        if self._state.visible:
            for scene_element in state.scenes:
                logger.info('drawing scene')
                scene = scene_element.scene
                scene_tile = SceneTileAdapter(scene)

                k = (scene_tile, state.cpt.cpt_name)

                if k not in self._meshes:
                    # TODO handle different limits of multiples scenes?!

                    cpt = copy.deepcopy(
                        self.cpt_handler._cpts[state.cpt.cpt_name])

                    mesh = TopoMeshPipe(
                        scene_tile,
                        cells_cache=None,
                        cpt=cpt,
                        # lut=lut,
                        backface_culling=False)

                    values = scene_tile.data.flatten()
                    self.cpt_handler._values = values
                    self.cpt_handler.update_cpt()

                    mask = num.ones((2, 2))
                    mesh.set_values(convolve2d(
                        scene_tile.data, mask, 'valid').flatten() / len(mask))

                    mesh.set_shading('phong')

                    self._meshes[k] = mesh
                else:
                    # TODO Somehow buggy
                    mesh = self._meshes[k]

                    values = k[0].data.flatten()
                    self.cpt_handler._values = values
                    self.cpt_handler.update_cpt()

                # self.cpt_handler.update_cpt()

                if scene_element.visible:
                    self._parent.add_actor(mesh.actor)
                # else:
                #     self._parent.remove_actor(mesh.actor)

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

            self.cpt_handler.cpt_controls(
                self._parent, self._state.cpt, layout)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 4, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            # layout.addWidget(qw.QFrame(), 3, 0, 1, 2)

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
