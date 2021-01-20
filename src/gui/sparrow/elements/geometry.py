# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import logging

from pyrocko.guts import Bool, String, load, StringChoice, Float
from pyrocko.geometry import arr_vertices, arr_faces
from pyrocko.gui.qt_compat import qw, qc, fnpatch
from pyrocko.gui.vtk_util import TrimeshPipe, ColorbarPipe, OutlinesPipe

from pyrocko.model import Geometry

from . import base
from .. import common


logger = logging.getLogger('geometry')

guts_prefix = 'sparrow'

km = 1e3


class CPTChoices(StringChoice):

    choices = ['slip_colors', 'seismic', 'jet', 'hot_r', 'gist_earth_r']


class GeometryState(base.ElementState):
    opacity = Float.T(default=1.0)
    visible = Bool.T(default=True)
    geometry = Geometry.T(default=None, optional=True)
    display_parameter = String.T(default='slip')
    time = Float.T(default=0., optional=True)
    cpt = base.CPTState.T(default=base.CPTState.D())

    def create(self):
        element = GeometryElement()
        return element


class GeometryElement(base.Element):

    def __init__(self):
        self._listeners = []
        self._parent = None
        self._state = None
        self._controls = None

        self._pipe = None
        self._cbar_pipe = None
        self._outlines_pipe = []

        self.cpt_handler = base.CPTHandler()

    def remove(self):
        if self._parent and self._state:
            self._parent.state.elements.remove(self._state)

    def init_pipeslots(self):
        if not self._pipe:
            self._pipe.append([])

    def remove_pipes(self):
        if self._pipe is not None:
            self._parent.remove_actor(self._pipe.actor)

        if self._cbar_pipe is not None:
            self._parent.remove_actor(self._cbar_pipe.actor)

        if len(self._outlines_pipe) > 0:
            for pipe in self._outlines_pipe:
                self._parent.remove_actor(pipe.actor)

        self._pipe = None
        self._cbar_pipe = None
        self._outlines_pipe = []

    def set_parent(self, parent):
        self._parent = parent
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)

        update = self.update
        self._listeners.append(update)
        self._parent.state.add_listener(update, 'tmin')
        self._parent.state.add_listener(update, 'tmax')
        self._parent.state.add_listener(update, 'lat')
        self._parent.state.add_listener(update, 'lon')

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
        base.Element.bind_state(self, state)
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'geometry')
        state.add_listener(upd, 'display_parameter')
        state.add_listener(upd, 'time')
        state.add_listener(upd, 'opacity')
        self.cpt_handler.bind_state(state.cpt, upd)

    def unbind_state(self):
        for listener in self._listeners:
            try:
                listener.release()
            except Exception:
                pass

        self.cpt_handler.unbind_state()
        self._state = None

    def get_cpt_name(self, cpt, display_parameter):
        return '{}_{}'.format(cpt, display_parameter)

    def update_cpt(self, state):

        values = state.geometry.get_property(state.display_parameter)
        # TODO Check
        # if values.ndim == 2:
        #     values = values.sum(1)

        self.cpt_handler._values = values
        self.cpt_handler.update_cpt()

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
        props = loaded_geometry.properties.get_col_names(sub_headers=False)

        if props:
            if self._state.display_parameter not in props:
                self._state.display_parameter = props[0]
        else:
            raise ValueError(
                'Imported geometry contains no property to be displayed!')

        self._parent.remove_panel(self._controls)
        self._controls = None
        self._state.geometry = loaded_geometry

        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)

        self.update()

    def get_values(self, geom):
        values = geom.get_property(self._state.display_parameter)

        if geom.event is not None:
            ref_time = geom.event.time
        else:
            ref_time = 0.

        if len(values.shape) == 2:
            tmin = self._parent.state.tmin
            tmax = self._parent.state.tmax
            if tmin is not None:
                ref_tmin = tmin - ref_time
                ref_idx_min = geom.time2idx(ref_tmin)
            else:
                ref_idx_min = geom.time2idx(self._state.time)

            if tmax is not None:
                ref_tmax = tmax - ref_time
                ref_idx_max = geom.time2idx(ref_tmax)
            else:
                ref_idx_max = geom.time2idx(self._state.time)

            if ref_idx_min == ref_idx_max:
                out = values[:, ref_idx_min]
            elif ref_idx_min > ref_idx_max:
                out = values[:, ref_idx_min]
            elif ref_idx_max < ref_idx_min:
                out = values[:, ref_idx_max]
            else:
                # TODO CHECK
                # out = values[:, ref_idx_min:ref_idx_max].sum(1)
                out = values[:, ref_idx_max]
        else:
            out = values.ravel()
        return out

    def update_view(self, *args):
        pstate = self._parent.state
        geom = self._state.geometry

        if geom.event:
            pstate.lat = geom.event.lat
            pstate.lon = geom.event.lon

        self.update()

    def update(self, *args):

        state = self._state

        if state.geometry and self._controls:
            self._update_controls()
            # base.update_cpt(self)
            self.update_cpt(state)

            if state.visible:
                # cpt_name = self.get_cpt_name(
                # state.cpt, state.display_parameter)
                geo = state.geometry
                values = self.get_values(geo)
                lut = self.cpt_handler._lookuptable
                if not isinstance(self._pipe, TrimeshPipe):
                    vertices = arr_vertices(geo.get_vertices('xyz'))
                    faces = arr_faces(geo.get_faces())
                    self._pipe = TrimeshPipe(
                        vertices, faces,
                        values=values,
                        lut=lut,
                        backface_culling=False)
                    self._cbar_pipe = ColorbarPipe(
                        lut=lut, cbar_title=state.display_parameter)
                    self._parent.add_actor(self._pipe.actor)
                    self._parent.add_actor(self._cbar_pipe.actor)

                    if geo.outlines:
                        self._outlines_pipe.append(OutlinesPipe(
                            geo, color=(1., 1., 1.), cs='latlondepth'))
                        self._parent.add_actor(
                            self._outlines_pipe[-1].actor)
                        self._outlines_pipe.append(OutlinesPipe(
                            geo, color=(0.6, 0.6, 0.6), cs='latlon'))
                        self._parent.add_actor(
                            self._outlines_pipe[-1].actor)

                else:
                    self._pipe.set_values(values)
                    self._pipe.set_lookuptable(lut)
                    self._pipe.set_opacity(self._state.opacity)

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
            layout.setAlignment(qc.Qt.AlignTop)
            frame.setLayout(layout)

            # load geometry
            pb = qw.QPushButton('Load')
            layout.addWidget(pb, 0, 0)

            pb.clicked.connect(self.open_file_load_dialog)

            # property choice
            il = 1
            if state.geometry:

                pb = qw.QPushButton('Move to')
                layout.addWidget(pb, 0, 1)
                pb.clicked.connect(self.update_view)

                props = []
                for prop in state.geometry.properties.get_col_names(
                        sub_headers=False):
                    props.append(prop)

                layout.addWidget(qw.QLabel('Display parameter'), il, 0)
                cb = qw.QComboBox()

                unique_props = list(set(props))
                for i, s in enumerate(unique_props):
                    cb.insertItem(i, s)

                layout.addWidget(cb, il, 1)
                state_bind_combobox(self, state, 'display_parameter', cb)

                # color maps
                self.cpt_handler.cpt_controls(
                    self._parent, self._state.cpt, layout)

                # times slider
                il = layout.rowCount() + 1
                slider = qw.QSlider(qc.Qt.Horizontal)
                slider.setSizePolicy(
                    qw.QSizePolicy(
                        qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))

                slider.setMinimum(state.geometry.times.min())
                slider.setMaximum(state.geometry.times.max())
                slider.setSingleStep(state.geometry.deltat)
                slider.setPageStep(state.geometry.deltat)

                time_label = qw.QLabel('Time')
                layout.addWidget(time_label, il, 0)
                layout.addWidget(slider, il, 1)

                state_bind_slider(
                    self, state, 'time', slider, dtype=int)

                self._time_label = time_label
                self._time_slider = slider

                il += 1
                slider_opacity = qw.QSlider(qc.Qt.Horizontal)
                slider_opacity.setSizePolicy(
                    qw.QSizePolicy(
                        qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
                slider_opacity.setMinimum(0)
                slider_opacity.setMaximum(1000)

                opacity_label = qw.QLabel('Opacity')
                layout.addWidget(opacity_label, il, 0)
                layout.addWidget(slider_opacity, il, 1)

                state_bind_slider(
                    self, state, 'opacity', slider_opacity, factor=0.001)

                self._opacity_label = opacity_label
                self._opacity_slider = slider_opacity

                il += 1
                pb = qw.QPushButton('Remove')
                layout.addWidget(pb, il, 1)
                pb.clicked.connect(self.remove)

                # visibility
                cb = qw.QCheckBox('Show')
                layout.addWidget(cb, il, 0)
                state_bind_checkbox(self, state, 'visible', cb)

                il += 1
                layout.addWidget(qw.QFrame(), il, 0, 1, 3)

                self.cpt_handler._update_cpt_combobox()
                self.cpt_handler._update_cptscale_lineedit()

            self._controls = frame

            self._update_controls()

        return self._controls

    def _update_controls(self):
        state = self._state
        if state.geometry:
            values = state.geometry.get_property(state.display_parameter)

            if values.ndim == 2:
                self._time_label.setVisible(True)
                self._time_slider.setVisible(True)
                self._opacity_label.setVisible(True)
                self._opacity_slider.setVisible(True)
            else:
                self._time_label.setVisible(False)
                self._time_slider.setVisible(False)
                self._opacity_label.setVisible(False)
                self._opacity_slider.setVisible(False)


__all__ = [
    'GeometryElement',
    'GeometryState'
]
