# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

from pyrocko.plot import automap, gmtpy
from pyrocko.dataset.topo import tile
from pyrocko.guts import String
from pyrocko.dataset import topo
from pyrocko.gui.qt_compat import qw, qc, fnpatch

from pyrocko.gui.vtk_util import cpt_to_vtk_lookuptable

from .base import Element
from .topo import TopoMeshPipe, TopoCPTChoice, TopoState

from .. import common

guts_prefix = 'sparrow'


def load_tile(path):
    lon, lat, z = gmtpy.loadgrd(path)
    return tile.Tile(lon[0], lat[0], lon[1] - lon[0], lat[1] - lat[0],  z)


class CustomTopoState(TopoState):
    path = String.T(optional=True)

    def create(self):
        element = CustomTopoElement()
        element.bind_state(self)
        return element


class CustomTopoElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._controls = None
        self._visible = False
        self._mesh = None
        self._lookuptables = {}
        self._path_loaded = None

    def get_name(self):
        return 'Custom Topography'

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'exaggeration')
        state.add_listener(upd, 'opacity')
        state.add_listener(upd, 'smooth')
        state.add_listener(upd, 'cpt')

        state.add_listener(upd, 'path')

        self._state = state

    def unbind_state(self):
        self._listeners.clear()
        self._state = None

    def set_parent(self, parent):
        self._parent = parent

        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._mesh is not None:
                self._parent.remove_actor(self._mesh.actor)

            self._mesh = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

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

        visible = self._state.visible

        self.update_cpt(self._state.cpt)

        if visible:
            if self._path_loaded is None and self._state.path is not None or \
                    self._state.path != self._path_loaded:

                if self._mesh:
                    self._parent.remove_actor(self._mesh.actor)
                    self._mesh = None

                t = load_tile(self._state.path)
                self._path_loaded = self._state.path
                self._mesh = TopoMeshPipe(
                    t,
                    mask_ocean=False,
                    smooth=self._state.smooth,
                    lut=self._lookuptables[self._state.cpt])

                self._parent.add_actor(self._mesh.actor)

        if not visible and self._mesh:
            self._parent.remove_actor(self._mesh.actor)

        if self._mesh:
            if visible:
                self._parent.add_actor(self._mesh.actor)

            self._mesh.set_exaggeration(self._state.exaggeration)
            self._mesh.set_opacity(self._state.opacity)
            self._mesh.set_smooth(self._state.smooth)
            self._mesh.set_lookuptable(
                self._lookuptables[self._state.cpt])

        self._parent.update_view()

    def open_file_dialog(self):
        caption = 'Select a file to open'

        fn, _ = fnpatch(qw.QFileDialog.getOpenFileName(
            self._parent, caption, options=common.qfiledialog_options))

        if fn:
            self._state.path = str(fn)

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_slider, state_bind_checkbox, \
                state_bind_combobox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            lab = qw.QLabel('Load from:')
            pb_file = qw.QPushButton('File')

            layout.addWidget(lab, 0, 0)
            layout.addWidget(pb_file, 0, 1)

            pb_file.clicked.connect(self.open_file_dialog)

            # exaggeration

            layout.addWidget(qw.QLabel('Exaggeration'), 1, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(2000)
            layout.addWidget(slider, 1, 1)

            state_bind_slider(self, state, 'exaggeration', slider, factor=0.01)

            # opacity

            layout.addWidget(qw.QLabel('Opacity'), 2, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(1000)
            layout.addWidget(slider, 2, 1)

            state_bind_slider(self, state, 'opacity', slider, factor=0.001)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 3, 0)
            state_bind_checkbox(self, state, 'visible', cb)

            cb = qw.QCheckBox('Smooth')
            layout.addWidget(cb, 3, 1)
            state_bind_checkbox(self, state, 'smooth', cb)

            cb = common.string_choices_to_combobox(TopoCPTChoice)
            layout.addWidget(qw.QLabel('CPT'), 4, 0)
            layout.addWidget(cb, 4, 1)
            state_bind_combobox(self, state, 'cpt', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, 5, 1)
            pb.clicked.connect(self.remove)

            layout.addWidget(qw.QFrame(), 6, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'CustomTopoElement',
    'CustomTopoState',
]
