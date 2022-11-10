# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num
import vtk

from pyrocko.guts import Bool, StringChoice, Float
from pyrocko.gui.qt_compat import qw, qc
from pyrocko.color import Color


from pyrocko.gui import vtk_util
from .. import common
from .base import Element, ElementState

guts_prefix = 'sparrow'


class CoastlineResolutionChoice(StringChoice):
    choices = [
        'crude',
        'low',
        'intermediate',
        'high',
        'full']


class CoastlinesPipe(object):
    def __init__(self, resolution='low'):

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
        self.set_resolution(resolution)

        actor = vtk.vtkActor()
        actor.SetMapper(self.mapper)

        prop = actor.GetProperty()
        prop.SetDiffuseColor(1, 1, 1)

        self.prop = prop
        self.actor = actor

    def set_resolution(self, resolution):
        assert resolution in CoastlineResolutionChoice.choices

        if resolution not in self._polyline_grid:
            pb = common.get_app().get_progressbars()
            if pb:
                mess = 'Loading %s resolution coastlines' % resolution
                pb.set_status(mess, 0, can_abort=False)

            from pyrocko.dataset.gshhg import GSHHG
            g = getattr(GSHHG, resolution)()

            lines = []
            npoly = len(g.polygons)
            for ipoly, poly in enumerate(g.polygons):
                if pb:
                    pb.set_status(
                        mess, float(ipoly) / npoly * 100., can_abort=False)

                lines.append(poly.points)

            self._polyline_grid[resolution] = vtk_util.make_multi_polyline(
                lines_latlon=lines, depth=-200.)

            if pb:
                pb.set_status(mess, 100, can_abort=False)

        vtk_util.vtk_set_input(self.mapper, self._polyline_grid[resolution])

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


class CoastlinesState(ElementState):
    visible = Bool.T(default=True)
    resolution = CoastlineResolutionChoice.T(default='low')
    opacity = Float.T(default=0.4)
    color = Color.T(default=Color.D('white'))
    line_width = Float.T(default=1.0)

    def create(self):
        element = CoastlinesElement()
        return element


class CoastlinesElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._controls = None
        self._coastlines = None

    def get_name(self):
        return 'Coastlines'

    def bind_state(self, state):
        Element.bind_state(self, state)
        upd = self.update
        self._listeners = [upd]
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'resolution')
        state.add_listener(upd, 'opacity')
        state.add_listener(upd, 'color')
        state.add_listener(upd, 'line_width')

    def unbind_state(self):
        self._listeners = []

    def set_parent(self, parent):
        self._parent = parent
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)

        upd = self.update_clipping
        self._listeners.append(upd)

        self._parent.state.add_listener(upd, 'lat')
        self._parent.state.add_listener(upd, 'lon')
        self._parent.state.add_listener(upd, 'depth')
        self._parent.state.add_listener(upd, 'distance')
        self._parent.state.add_listener(upd, 'azimuth')
        self._parent.state.add_listener(upd, 'dip')

        self.update()
        self.update_clipping()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._coastlines:
                self._parent.remove_actor(self._coastlines.actor)
                self._coastlines = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def update(self, *args):
        state = self._state
        if not state.visible and self._coastlines:
            self._parent.remove_actor(self._coastlines.actor)

        if state.visible:
            if not self._coastlines:
                self._coastlines = CoastlinesPipe(resolution=state.resolution)

            self._parent.add_actor(self._coastlines.actor)
            self._coastlines.set_resolution(state.resolution)
            self._coastlines.set_opacity(state.opacity)
            self._coastlines.set_color(state.color)
            self._coastlines.set_line_width(state.line_width)

        self._parent.update_view()

    def update_clipping(self, *args):
        if self._state.visible and self._coastlines:
            cam = self._parent.camera_params[0]
            origin = cam / num.linalg.norm(cam)**2
            self._coastlines.set_clipping_plane(origin, cam)

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_combobox, \
                state_bind_checkbox, state_bind_slider, \
                state_bind_combobox_color

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            layout.addWidget(qw.QLabel('Resolution'), 0, 0)

            cb = common.string_choices_to_combobox(CoastlineResolutionChoice)
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
                ['black', 'white'])

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

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 4, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, 4, 1)
            pb.clicked.connect(self.remove)

            layout.addWidget(qw.QFrame(), 5, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'CoastlinesElement',
    'CoastlinesState']
