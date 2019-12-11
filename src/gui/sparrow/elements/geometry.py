# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import logging

from pyrocko.guts import Object, Bool, List, String, load, StringChoice, Float
from pyrocko.geometry import arr_vertices, arr_faces
from pyrocko.gui.qt_compat import qw, qc, fnpatch
from pyrocko.gui.vtk_util import TrimeshPipe, ColorbarPipe, cpt_to_vtk_lookuptable
from pyrocko.model import Geometry
from pyrocko import automap
from pyrocko.dataset import topo
from .base import Element, ElementState
from .. import common


logger = logging.getLogger('geometry')

guts_prefix = 'sparrow'

km = 1e3


class CPTChoices(StringChoice):

    choices = ['slip_colors']


class GeometryState(ElementState):

    visible = Bool.T(default=False)
    geometries = List.T(Geometry.T(), default=[])
    display_parameter = String.T(default='slip')
    cpt = CPTChoices.T(default='slip_colors')
    time = Float.T(default=0., optional=True)

    def create(self):
        element = GeometryElement()
        element.bind_state(self)
        return element


class GeometryElement(Element):

    def __init__(self):
        self._listeners = []
        self._parent = None
        self._state = None
        self._controls = None
        self._pipe = []
        self._cbar_pipe = None
        self._cpt_name = None
        self._lookuptables = {}

    def remove(self):
        if self._parent and self._state:
            self._parent.state.elements.remove(self._state)

    def init_pipeslots(self):
        if not self._pipe:
            for _ in self._state.geometries:
                self._pipe.append([])

    def remove_pipes(self):
        for pipe in self._pipe:
            if not isinstance(pipe, list):
                self._parent.remove_actor(pipe.actor)

        if self._cbar_pipe is not None:
            self._parent.remove_actor(self._cbar_pipe.actor)

        self._cbar_pipe = None

        self.init_pipeslots()

    def set_parent(self, parent):
        self._parent = parent
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._pipe:
                self.remove_pipes()

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'geometries')
        state.add_listener(upd, 'display_parameter')
        state.add_listener(upd, 'cpt')
        state.add_listener(upd, 'time')
        self._state = state
        self.init_pipeslots()

    def unbind_state(self):
        for listener in self._listeners:
            try:
                listener.release()
            except Exception as e:
                pass

        self._listeners = []
        self._state = None

    def get_cpt_name(self, cpt, display_parameter):
        return '{}_{}'.format(cpt, display_parameter)

    def update_cpt(self, state):

        cpt_name = self.get_cpt_name(state.cpt, state.display_parameter)
        if cpt_name not in self._lookuptables:
            vmins = []
            vmaxs = []
            for geom in state.geometries:
                values = geom.get_property(state.display_parameter)
                vmins.append(values.min())
                vmaxs.append(values.max())

            cpt = automap.read_cpt(topo.cpt(state.cpt))
            cpt.scale(min(vmins), min(vmaxs))

            vtk_cpt = cpt_to_vtk_lookuptable(cpt)
            vtk_cpt.SetNanColor(0.0, 0.0, 0.0, 0.0)

            self._lookuptables[cpt_name] = vtk_cpt

    def get_name(self):
        return 'Geometry'

    def open_file_load_dialog(self):
        caption = 'Select one file containing a geometry to open'
        fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options))

        if fns:
            self.load_file(str(fns[0]))
        else:
            return

    def load_file(self, path):

        loaded_geometry = load(filename=path)

        self._parent.remove_panel(self._controls)
        self._controls = None
        self._state.geometries.append(loaded_geometry)

        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)

        self.update()

    def get_values(self, geom, state):
        values = geom.get_property(state.display_parameter)
        if len(values.shape) == 2:
            idx = geom.time2idx(state.time)
            values = values[:, idx]
        return values

    def update(self, *args):

        state = self._state
        self.init_pipeslots()

        if state.geometries:
            self.update_cpt(state)

        if state.visible:
            cpt_name = self.get_cpt_name(
                state.cpt, state.display_parameter)
            for i, geo in enumerate(state.geometries):
                values = self.get_values(geo, state)
                lut = self._lookuptables[cpt_name]
                if not isinstance(self._pipe[i], TrimeshPipe):
                    vertices = arr_vertices(geo.vertices.get_col('xyz'))
                    faces = arr_faces(geo.faces.get_col('faces'))
                    self._pipe[i] = TrimeshPipe(
                            vertices, faces,
                            values=values,
                            lut=lut)
                    self._cbar_pipe = ColorbarPipe(lut=lut, cbar_title=state.display_parameter)
                    self._parent.add_actor(self._pipe[i].actor)
                    self._parent.add_actor(self._cbar_pipe.actor)
                else:
                    self._pipe[i].set_values(values)
                    self._pipe[i].set_lookuptable(lut)

                    self._cbar_pipe.set_lookuptable(lut)
                    self._cbar_pipe.set_title(state.display_parameter)
        else:
            if self._pipe:
                self.remove_pipes()

        self._parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_checkbox, state_bind_combobox, \
                                state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            # load geometrie
            pb = qw.QPushButton('Load')
            layout.addWidget(pb, 0, 0)
            pb.clicked.connect(self.open_file_load_dialog)

            # property choice
            layout.addWidget(qw.QLabel('Display parameter'), 1, 0)
            cb = qw.QComboBox()
            if state.geometries:
                props = []
                for geom in state.geometries:
                    for prop in geom.properties.get_col_names(
                            sub_headers=False):
                        props.append(prop)

                unique_props = list(set(props))
                for i, s in enumerate(unique_props):
                    cb.insertItem(i, s)

                layout.addWidget(cb, 1, 1)
                state_bind_combobox(self, state, 'display_parameter', cb)

                # times slider
                values = geom.get_property(state.display_parameter)
                if len(values.shape) == 2:
                    slider = qw.QSlider(qc.Qt.Horizontal)
                    slider.setSizePolicy(
                        qw.QSizePolicy(
                            qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))

                    slider.setMinimum(geom.times.min())
                    slider.setMaximum(geom.times.max())
                    slider.setSingleStep(geom.deltat)
                    slider.setPageStep(geom.deltat)

                    layout.addWidget(qw.QLabel('Time'), 2, 0)
                    layout.addWidget(slider, 2, 1)

                    state_bind_slider(
                        self, state, 'time', slider, dtype=int)

                pb = qw.QPushButton('Remove')
                layout.addWidget(pb, 4, 1)
                pb.clicked.connect(self.remove)

            # color maps
            cb = common.string_choices_to_combobox(CPTChoices)
            layout.addWidget(qw.QLabel('CPT'), 3, 0)
            layout.addWidget(cb, 3, 1)
            state_bind_combobox(self, state, 'cpt', cb)

            # visibility
            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 4, 0)
            state_bind_checkbox(self, state, 'visible', cb)


            self._controls = frame

        return self._controls


__all__ = [
    'GeometryElement',
    'GeometryState'
]