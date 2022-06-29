# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko import table, geometry, cake
from pyrocko.guts import Bool, Float
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.dataset.tectonics import PeterBird2003
from pyrocko.gui import vtk_util
import vtk
from matplotlib.pyplot import cm

from .base import Element, ElementState

guts_prefix = 'sparrow'

km = 1e3
COLOR_PLATES = (0.1, 0.0, .0)


def plates_to_points(plates):
    num_all_nodes = 0
    for plate in plates:
        num_all_nodes = num_all_nodes + len(plate.points)
    coords = num.zeros((num_all_nodes, 3))
    x = []
    y = []

    for plate in plates:
        num_nodes = len(plate.points)
        for i in range(0, num_nodes):
            x.append(plate.points[i][0])
            y.append(plate.points[i][1])
    for i in range(0, num_all_nodes):
        coords[i, :] = x[i], y[i], -10*km
    station_table = table.Table()

    station_table.add_col(('coords', '', ('lat', 'lon', 'depth')), coords)

    return geometry.latlondepth2xyz(
        station_table.get_col('coords'),
        planetradius=cake.earthradius)


def plates_to_color(plates):
    colors = []
    colors_iter_map = iter(cm.terrain(num.linspace(0, 1, len(plates))))
    for plate in plates:
        color = next(colors_iter_map)
        colors.append(color)
    return num.array(colors)


class PlatesBoundsState(ElementState):
    visible = Bool.T(default=True)
    opacity = Float.T(default=1.0)
    color_by_slip_type = Bool.T(default=False)
    lines = Bool.T(default=True)

    def create(self):
        element = PlatesBoundsElement()
        return element


class PlatelinesPipe(object):
    def __init__(self, plates=None):

        self.mapper = vtk.vtkDataSetMapper()
        self._polyline_grid = {}
        self._opacity = 1.0
        self.plates = plates

        actor = vtk.vtkActor()
        actor.SetMapper(self.mapper)

        prop = actor.GetProperty()
        prop.SetDiffuseColor(1, 1, 1)

        self.prop = prop
        self.actor = actor

    def plate_to_lines(self, plate):
        lines = []
        poly = []
        num_nodes = len(plate.points)
        for i in range(0, num_nodes):
            poly.append((plate.points[i][0], plate.points[i][1]))
        lines.append(num.asarray(poly))

        self._polyline_grid[0] = vtk_util.make_multi_polyline(
            lines_latlon=lines, depth=-100.)
        vtk_util.vtk_set_input(self.mapper, self._polyline_grid[0])

    def set_opacity(self, opacity):
        opacity = float(opacity)
        if self._opacity != opacity:
            self.prop.SetOpacity(opacity)
            self._opacity = opacity


class PlatesBoundsElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._state = None
        self._pipe = None
        self._controls = None
        self._plates = None
        self._listeners = []
        self._plate_line = None
        self._plate_lines = []

    def bind_state(self, state):
        Element.bind_state(self, state)
        self._listeners.append(
            state.add_listener(self.update, 'visible'))
        self._listeners.append(
            state.add_listener(self.update, 'opacity'))

    def unbind_state(self):
        self._listerners = []

    def get_name(self):
        return 'Plate bounds'

    def set_parent(self, parent):
        self._parent = parent
        if not self._plates:
            PB = PeterBird2003()
            self._plates = PB.get_plates()

        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._plate_lines:
            for i, plate in enumerate(self._plate_lines):
                self._parent.remove_actor(plate.actor)

            self._pipe = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def update(self, *args):

        state = self._state
        if state.visible:
            colors = plates_to_color(self._plates)
            for i, plate in enumerate(self._plates):
                self._plate_line = PlatelinesPipe(plates=plate)
                self._plate_line.plate_to_lines(plate)
                self._parent.add_actor(self._plate_line.actor)
                prop = self._plate_line.actor.GetProperty()
                prop.SetDiffuseColor(colors[i][0:3])
                self._plate_line.set_opacity(state.opacity)
                self._plate_lines.append(self._plate_line)
        if not state.visible and self._plate_lines:
            for i, plate in enumerate(self._plate_lines):
                self._parent.remove_actor(plate.actor)

        self._parent.update_view()

    def _get_controls(self):
        if self._controls is None:
            from ..state import state_bind_checkbox, state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            layout.setAlignment(qc.Qt.AlignTop)
            frame.setLayout(layout)

            layout.addWidget(qw.QLabel('Opacity'), 0, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(10)
            slider.setSingleStep(1)
            slider.setPageStep(1)
            layout.addWidget(slider, 0, 1)
            state_bind_slider(self, self._state, 'opacity', slider)

            cb = qw.QCheckBox('Show')

            layout.addWidget(cb, 1, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, 1, 1)
            pb.clicked.connect(self.remove)

            self._controls = frame

        return self._controls


__all__ = [
    'PlatesBoundsElement',
    'PlatesBoundsState'
]
