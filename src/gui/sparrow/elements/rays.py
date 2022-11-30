# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko.guts import Bool, Float
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.dataset.active_faults import ActiveFaults
from pyrocko.gui import vtk_util
from pyrocko import plot, orthodrome as od, model, cake
import vtk

from .base import Element, ElementState

guts_prefix = 'sparrow'

km = 1e3


def color(x):
    return num.array(plot.to01(plot.color(x)), dtype=num.float)


def to_latlondepth(event, station, rays):

    lines = []
    azimuth, _ = event.azibazi_to(station)
    for ray in rays:
        fanz, fanx, _ = ray.zxt_path_subdivided()

        for zs, xs in zip(fanz, fanx):
            lats, lons = od.azidist_to_latlon(
                event.lat, event.lon, azimuth, xs)

            line = num.zeros((xs.size, 3))
            line[:, 0] = lats
            line[:, 1] = lons
            line[:, 2] = zs

            lines.append(line)

    return lines


class RaysState(ElementState):
    visible = Bool.T(default=True)
    line_width = Float.T(default=1.0)
    opacity = Float.T(default=1.0)
    lat = Float.T(default=0.0)
    lon = Float.T(default=0.0)
    depth = Float.T(default=10000.0)

    def create(self):
        element = RaysElement()
        element.bind_state(self)
        return element


class RaysPipe(object):
    def __init__(self, ray_data):

        self._opacity = 1.0
        self._line_width = 1.0
        self._actors = {}

        mapper = vtk.vtkDataSetMapper()
        lines = []
        for event, station, rays in ray_data:
            lines.extend(to_latlondepth(event, station, rays))

        grid = vtk_util.make_multi_polyline(
            lines_latlondepth=lines)

        vtk_util.vtk_set_input(mapper, grid)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        self._actors['ray'] = actor

    def set_opacity(self, opacity):
        opacity = float(opacity)
        if self._opacity != opacity:
            for actor in self._actors.values():
                actor.GetProperty().SetOpacity(opacity)

            self._opacity = opacity

    def set_line_width(self, width):
        width = float(width)
        if self._line_width != width:
            for actor in self._actors.values():
                actor.GetProperty().SetLineWidth(width)

            self._line_width = width

    def get_actors(self):
        return [self._actors[k] for k in sorted(self._actors.keys())]


class RaysElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._state = None
        self._pipe = None
        self._controls = None
        self._active_faults = None
        self._listeners = []
        self._mod = cake.load_model()
        self._stations = model.load_stations('stations.txt')
        self._params = ()

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        for k in [
                'visible', 'line_width', 'opacity',
                'lat', 'lon', 'depth']:

            state.add_listener(upd, k)

        self._state = state

    def unbind_state(self):
        self._listeners = []

    def get_name(self):
        return 'Rays'

    def set_parent(self, parent):
        self._parent = parent
        if not self._active_faults:
            self._active_faults = ActiveFaults()

        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=True,
            remove=self.remove)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._pipe:
                for actor in self._pipe.get_actors():
                    self._parent.remove_actor(actor)

                self._pipe = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def move_here(self):
        pstate = self._parent.state
        state = self._state
        state.lat = pstate.lat
        state.lon = pstate.lon

    def update(self, *args):

        state = self._state
        params = (state.lat, state.lon, state.depth)

        if self._pipe and (params != self._params or not state.visible):
            for actor in self._pipe.get_actors():
                self._parent.remove_actor(actor)

            self._pipe = None

        if state.visible:
            if not self._pipe:
                print('update')

                events = [model.Event(
                    lat=state.lat, lon=state.lon, depth=state.depth)]

                ray_data = []
                for event in events:
                    for station in self._stations:
                        dist = event.distance_to(station)
                        ray_data.append((
                            event,
                            station,
                            self._mod.arrivals(
                                phases=[cake.PhaseDef('P')],
                                distances=[dist*od.m2d],
                                zstart=event.depth,
                                zstop=0.0)))

                self._pipe = RaysPipe(ray_data)
                self._params = params

                for actor in self._pipe.get_actors():
                    self._parent.add_actor(actor)

        if self._pipe:
            self._pipe.set_opacity(state.opacity)
            self._pipe.set_line_width(state.line_width)

        self._parent.update_view()

    def _get_controls(self):
        if self._controls is None:
            from ..state import state_bind_checkbox, state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            layout.setAlignment(qc.Qt.AlignTop)
            frame.setLayout(layout)

            state = self._state

            iy = 0
            for (param, vmin, vmax) in [
                    ('lat', -90., 90.),
                    ('lon', -180., 180.),
                    ('depth', -10000., 100000.),
                    ('line_width', 0., 5.),
                    ('opacity', 0., 1.)]:

                layout.addWidget(qw.QLabel(param.capitalize()), iy, 0)

                slider = qw.QSlider(qc.Qt.Horizontal)
                slider.setSizePolicy(qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))

                slider.setMinimum(int(round(vmin * 100.)))
                slider.setMaximum(int(round(vmax * 100.)))
                layout.addWidget(slider, iy, 1)

                state_bind_slider(self, state, param, slider, factor=0.01)
                iy += 1

            pb = qw.QPushButton('Move Here')
            layout.addWidget(pb, iy, 0)
            pb.clicked.connect(self.move_here)

            iy += 1

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, iy, 0)
            state_bind_checkbox(self, state, 'visible', cb)

            self._controls = frame

        return self._controls


__all__ = [
    'RaysElement',
    'RaysState'
]
