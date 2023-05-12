# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import logging
import numpy as num

from pyrocko.guts import Bool, String, load, Float
from pyrocko.geometry import arr_vertices, arr_faces
from pyrocko.gui.qt_compat import qw, qc
from pyrocko.gui.vtk_util import TrimeshPipe, ColorbarPipe, OutlinesPipe, Color
from pyrocko.orthodrome import geographic_midpoint

from pyrocko.model import Geometry

from . import base
from .. import common


logger = logging.getLogger('geometry')

guts_prefix = 'sparrow'

km = 1e3


class GeometryState(base.ElementState):
    opacity = Float.T(default=1.0)
    visible = Bool.T(default=True)
    geometry = Geometry.T(default=None, optional=True)
    display_parameter = String.T(default="")
    time = Float.T(default=0., optional=True)
    cpt = base.CPTState.T(default=base.CPTState.D())
    color = Color.T(default=Color.D('white'))
    line_width = Float.T(default=1.0)

    def create(self):
        element = GeometryElement()
        return element


class GeometryElement(base.Element):

    def __init__(self):
        base.Element.__init__(self)
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
            self.get_title_label(),
            self._get_controls(),
            visible=True,
            title_controls=[
                self.get_title_control_remove(),
                self.get_title_control_visible()])

        self.talkie_connect(
            self._parent.state,
            ['tmin', 'tmax', 'lat', 'lon'],
            self.update)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._pipe or self._cbar_pipe or self._outlines_pipe:
                self.remove_pipes()

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def bind_state(self, state):
        base.Element.bind_state(self, state)

        self.talkie_connect(
            state,
            ['visible', 'geometry', 'display_parameter', 'time',
             'opacity', 'color', 'line_width'],
            self.update)

        self.cpt_handler.bind_state(state.cpt, self.update)

    def unbind_state(self):
        self.cpt_handler.unbind_state()
        base.Element.unbind_state(self)

    def get_cpt_name(self, cpt, display_parameter):
        return '{}_{}'.format(cpt, display_parameter)

    def update_cpt(self, state):

        if len(state.display_parameter) != 0:
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
        fns, _ = qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options)

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

        self._parent.remove_panel(self._controls)
        self._controls = None
        self._state.geometry = loaded_geometry

        self._parent.add_panel(
            self.get_title_label(),
            self._get_controls(),
            visible=True,
            title_controls=[
                self.get_title_control_remove(),
                self.get_title_control_visible()])

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

        if geom.no_faces() > 0:
            latlon = geom.get_vertices('latlon')
            pstate.lat, pstate.lon = geographic_midpoint(
                latlon[:, 0],
                latlon[:, 1])
        elif geom.outlines:
            latlon = num.concatenate([
                outline.get_col('latlon') for outline in geom.outlines
            ])
            pstate.lat, pstate.lon = geographic_midpoint(
                latlon[:, 0],
                latlon[:, 1])
        elif geom.event:
            pstate.lat = geom.event.lat
            pstate.lon = geom.event.lon
        else:
            raise ValueError('Geometry Element has no location information.')

        self.update()

    def clear(self):
        self._parent.remove_panel(self._controls)
        self._controls = None
        self._state.geometry = None

        self._parent.add_panel(
            self.get_title_label(),
            self._get_controls(),
            visible=True,
            title_controls=[
                self.get_title_control_remove(),
                self.get_title_control_visible()])

        self.update()

    def update_outlines(self, geo):
        state = self._state
        if len(self._outlines_pipe) == 0:
            for cs in ['latlondepth']:
                outline_pipe = OutlinesPipe(
                    geo, color=state.color, cs=cs)
                outline_pipe.set_line_width(state.line_width)
                self._outlines_pipe.append(outline_pipe)
                self._parent.add_actor(
                    self._outlines_pipe[-1].actor)

        else:
            for outline_pipe in self._outlines_pipe:
                outline_pipe.set_color(state.color)
                outline_pipe.set_line_width(state.line_width)

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
                lut = self.cpt_handler._lookuptable
                no_faces = geo.no_faces()
                if no_faces:
                    values = self.get_values(geo)
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
                    else:
                        self._pipe.set_values(values)
                        self._pipe.set_lookuptable(lut)
                        self._pipe.set_opacity(self._state.opacity)

                        self._cbar_pipe.set_lookuptable(lut)
                        self._cbar_pipe.set_title(state.display_parameter)

                if geo.outlines:
                    self.update_outlines(geo)
            else:
                self.remove_pipes()

        else:
            self.remove_pipes()

        self._parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_combobox, \
                state_bind_slider, state_bind_combobox_color

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            layout.setAlignment(qc.Qt.AlignTop)
            frame.setLayout(layout)

            # load geometry
            il = 0
            if not state.geometry:
                pb = qw.QPushButton('Load')
                layout.addWidget(pb, il, 0)
                pb.clicked.connect(self.open_file_load_dialog)

            # property choice
            else:
                props = []
                for prop in state.geometry.properties.get_col_names(
                        sub_headers=False):
                    props.append(prop)

                layout.addWidget(qw.QLabel('Display Parameter'), il, 0)
                cb = qw.QComboBox()

                unique_props = list(set(props))
                for i, s in enumerate(unique_props):
                    cb.insertItem(i, s)

                layout.addWidget(cb, il, 1)
                state_bind_combobox(self, state, 'display_parameter', cb)

                if state.geometry.no_faces != 0:
                    # color maps
                    self.cpt_handler.cpt_controls(
                        self._parent, self._state.cpt, layout)

                    il += 1
                    layout.addWidget(qw.QFrame(), il, 0, 1, 3)

                    self.cpt_handler._update_cpt_combobox()
                    self.cpt_handler._update_cptscale_lineedit()

                # times slider
                if state.geometry.times is not None:
                    il = layout.rowCount() + 1
                    slider = qw.QSlider(qc.Qt.Horizontal)
                    slider.setSizePolicy(
                        qw.QSizePolicy(
                            qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))

                    def iround(x):
                        return int(round(x))

                    slider.setMinimum(iround(state.geometry.times.min()))
                    slider.setMaximum(iround(state.geometry.times.max()))
                    slider.setSingleStep(iround(state.geometry.deltat))
                    slider.setPageStep(iround(state.geometry.deltat))

                    time_label = qw.QLabel('Time')
                    layout.addWidget(time_label, il, 0)
                    layout.addWidget(slider, il, 1)

                    state_bind_slider(
                        self, state, 'time', slider, dtype=int)

                    self._time_label = time_label
                    self._time_slider = slider

                il = layout.rowCount() + 1
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

                # color
                il += 1
                layout.addWidget(qw.QLabel('Color'), il, 0)

                cb = common.strings_to_combobox(
                    ['black', 'white', 'blue', 'red'])

                layout.addWidget(cb, il, 1)
                state_bind_combobox_color(self, state, 'color', cb)

                # linewidth outline
                il += 1
                layout.addWidget(qw.QLabel('Line Width'), il, 0)

                slider = qw.QSlider(qc.Qt.Horizontal)
                slider.setSizePolicy(
                    qw.QSizePolicy(
                        qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
                slider.setMinimum(0)
                slider.setMaximum(100)
                layout.addWidget(slider, il, 1)
                state_bind_slider(
                    self, state, 'line_width', slider, factor=0.1)

                # Clear scene
                il += 1
                pb = qw.QPushButton('Clear')
                layout.addWidget(pb, il, 1)
                pb.clicked.connect(self.clear)

                # Change view to source
                pb = qw.QPushButton('Move To')
                layout.addWidget(pb, il, 2)
                pb.clicked.connect(self.update_view)

            self._controls = frame

            self._update_controls()

        return self._controls

    def _update_controls(self):
        state = self._state
        if state.geometry:
            if len(state.display_parameter) != 0:
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
