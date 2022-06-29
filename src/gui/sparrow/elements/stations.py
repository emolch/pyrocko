# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import time

import numpy as num
from pyrocko.guts import Bool, Float
from pyrocko import cake
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.gui.vtk_util import ScatterPipe
from pyrocko import geometry

from .base import Element, ElementState

guts_prefix = 'sparrow'


class StationsState(ElementState):
    visible = Bool.T(default=True)
    size = Float.T(default=5.0)

    @classmethod
    def get_name(self):
        return 'Stations'

    def create(self):
        element = StationsElement()
        element.bind_state(self)
        return element


class StationsElement(Element):

    def __init__(self):
        Element.__init__(self)
        self.parent = None
        self._pipe = None
        self._controls = None

        from pyrocko.client import fdsn

        now = time.time()
        tmin = now-3600.
        tmax = now
        sx = fdsn.station(
            site='iris', format='text', level='channel', channel='??Z',
            startbefore=tmin, endafter=tmax)

        stations = sx.get_pyrocko_stations()

        latlondepth = num.array([(s.lat, s.lon, 0.) for s in stations])
        self._points = geometry.latlondepth2xyz(
            latlondepth,
            planetradius=cake.earthradius)

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'size')
        self._state = state

    def get_name(self):
        return 'Stations'

    def set_parent(self, parent):
        self.parent = parent
        self.parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def update(self, *args):
        state = self._state

        if self._pipe and not state.visible:
            self.parent.remove_actor(self._pipe.actor)

        if state.visible:
            if not self._pipe:
                self._pipe = ScatterPipe(self._points)
                self.parent.add_actor(self._pipe.actor)

        self._pipe.set_size(state.size)

        self.parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state \
                import state_bind_checkbox, state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            layout.addWidget(qw.QLabel('Size'), 0, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Minimum))
            slider.setMinimum(0)
            slider.setMaximum(10)
            slider.setSingleStep(0.5)
            slider.setPageStep(0.5)
            layout.addWidget(slider, 0, 1)
            state_bind_slider(self, state, 'size', slider)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 0, 2)
            state_bind_checkbox(self, state, 'visible', cb)

        self._controls = frame

        return self._controls


__all__ = [
    'StationsElement',
    'StationsState',
]
