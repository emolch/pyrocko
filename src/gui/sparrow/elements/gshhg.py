# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num
import vtk

from pyrocko.guts import Bool, StringChoice, Float
from pyrocko.gui.qt_compat import qw, qc
from pyrocko.color import Color


from pyrocko.gui import vtk_util
from .. import common
from .base import Element, ElementState
from pyrocko.dataset.gshhg import Coastlines, Rivers, Borders


guts_prefix = 'sparrow'

gshhg_dataset_mapping = {
    'coastlines': Coastlines,
    'rivers': Rivers,
    'borders': Borders,
}


class GSHHGDatasetChoice(StringChoice):
    choices = ['coastlines', 'borders', 'rivers']


class GSHHGResolutionChoice(StringChoice):
    choices = [
        'crude',
        'low',
        'intermediate',
        'high',
        'full']


class GSHHGPipe(object):
    def __init__(self, dataset, resolution='low', levels=None):

        self.mapper = vtk.vtkDataSetMapper()
        self.plane = vtk.vtkPlane()
        self.plane.SetOrigin(0.0, 0.0, 0.0)
        coll = vtk.vtkPlaneCollection()
        coll.AddItem(self.plane)
        self.mapper.SetClippingPlanes(coll)

        self._polyline_grid = {}
        self._opacity = 1.0
        self._line_width = 1.0
        self._color = Color('white')
        self.set_resolution(dataset, resolution, levels)

        actor = vtk.vtkActor()
        actor.SetMapper(self.mapper)

        prop = actor.GetProperty()
        prop.SetDiffuseColor(1, 1, 1)

        self.prop = prop
        self.actor = actor

    def set_resolution(self, dataset, resolution, levels):
        assert resolution in GSHHGResolutionChoice.choices
        assert dataset in GSHHGDatasetChoice.choices
        assert levels is None or isinstance(levels, tuple)

        if (resolution, levels) not in self._polyline_grid:
            pb = common.get_viewer().progressbars
            if pb:
                mess = 'Loading %s resolution %s' % (resolution, dataset)
                pb.set_status(mess, 0, can_abort=False)

            dataset = gshhg_dataset_mapping[dataset]

            g = getattr(dataset, resolution)()
            g.load_all()

            lines = []
            npoly = len(g.polygons)
            for ipoly, poly in enumerate(g.polygons):
                if pb:
                    pb.set_status(
                        mess, float(ipoly) / npoly * 100., can_abort=False)

                if levels is None or poly.level_no in levels:
                    lines.append(poly.points)

            self._polyline_grid[resolution, levels] \
                = vtk_util.make_multi_polyline(lines_latlon=lines, depth=-200.)

            if pb:
                pb.set_status(mess, 100, can_abort=False)

        vtk_util.vtk_set_input(
            self.mapper, self._polyline_grid[resolution, levels])

    def set_opacity(self, opacity):
        opacity = float(opacity)
        if self._opacity != opacity:
            self.prop.SetOpacity(opacity)
            self._opacity = opacity

    def set_color(self, color):
        if self._color != color:
            self.prop.SetDiffuseColor(color.rgb)
            self._color = color

    def set_line_width(self, width):
        width = float(width)
        if self._line_width != width:
            self.prop.SetLineWidth(width)
            self._line_width = width

    def set_clipping_plane(self, origin, normal):
        self.plane.SetOrigin(*origin)
        self.plane.SetNormal(*normal)


class GSHHGState(ElementState):
    visible = Bool.T(default=True)
    dataset = GSHHGDatasetChoice.T(default='coastlines')
    resolution = GSHHGResolutionChoice.T(default='low')
    opacity = Float.T(default=0.4)
    color = Color.T(default=Color.D('white'))
    line_width = Float.T(default=1.0)

    def create(self):
        element = GSHHGElement()
        return element


class GSHHGElement(Element):

    def __init__(self, levels=None):
        Element.__init__(self)
        self._parent = None
        self._controls = None
        self._lines = None
        self._levels = levels

    def bind_state(self, state):
        Element.bind_state(self, state)
        self.talkie_connect(
            state,
            ['visible', 'resolution', 'opacity', 'color', 'line_width'],
            self.update)

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
            ['lat', 'lon', 'depth', 'distance', 'azimuth', 'dip'],
            self.update_clipping)

        self.update()
        self.update_clipping()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._lines:
                self._parent.remove_actor(self._lines.actor)
                self._lines = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def update(self, *args):
        state = self._state
        if not state.visible and self._lines:
            self._parent.remove_actor(self._lines.actor)

        if state.visible:
            if not self._lines:
                self._lines = GSHHGPipe(
                    dataset=state.dataset,
                    resolution=state.resolution,
                    levels=self._levels)

            self._parent.add_actor(self._lines.actor)
            self._lines.set_resolution(
                state.dataset, state.resolution, self._levels)
            self._lines.set_opacity(state.opacity)
            self._lines.set_color(state.color)
            self._lines.set_line_width(state.line_width)

        self._parent.update_view()

    def update_clipping(self, *args):
        if self._state.visible and self._lines:
            cam = self._parent.camera_params[0]
            origin = cam / num.linalg.norm(cam)**2
            self._lines.set_clipping_plane(origin, cam)

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_combobox, \
                state_bind_slider, state_bind_combobox_color

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            layout.addWidget(qw.QLabel('Resolution'), 0, 0)

            cb = common.string_choices_to_combobox(GSHHGResolutionChoice)
            layout.addWidget(cb, 0, 1)
            state_bind_combobox(self, self._state, 'resolution', cb)

            # opacity

            layout.addWidget(qw.QLabel('Opacity'), 1, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(1000)
            layout.addWidget(slider, 1, 1)

            state_bind_slider(
                self, self._state, 'opacity', slider, factor=0.001)

            # color

            layout.addWidget(qw.QLabel('Color'), 2, 0)

            cb = common.strings_to_combobox(
                ['black', 'white', 'blue', 'red'])

            layout.addWidget(cb, 2, 1)
            state_bind_combobox_color(
                self, self._state, 'color', cb)

            layout.addWidget(qw.QLabel('Line width'), 3, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(100)
            layout.addWidget(slider, 3, 1)
            state_bind_slider(
                self, self._state, 'line_width', slider, factor=0.1)

            layout.addWidget(qw.QFrame(), 5, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'GSHHGElement',
    'GSHHGState']
