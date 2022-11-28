# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko import table, geometry, cake
from pyrocko.guts import Bool, Float
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.dataset.volcanoes import Volcanoes
from pyrocko.gui.vtk_util import ScatterPipe

from .base import Element, ElementState

guts_prefix = 'sparrow'

km = 1e3
COLOR_HOLOCENE = (0.98, 0.26, .32)
COLOR_PLEISTOCENE = (1., .41, .28)


def volcanoes_to_points(volcanoes):
    coords = num.zeros((len(volcanoes), 3))

    for i, v in enumerate(volcanoes):
        coords[i, :] = v.lat, v.lon, -v.elevation - 10*km

    station_table = table.Table()

    station_table.add_col(('coords', '', ('lat', 'lon', 'depth')), coords)

    return geometry.latlondepth2xyz(
        station_table.get_col('coords'),
        planetradius=cake.earthradius)


def volcanoes_to_color(volcanoes):
    colors = []
    for v in volcanoes:
        if v.age == 'holocene':
            colors.append(COLOR_HOLOCENE)
        else:
            colors.append(COLOR_PLEISTOCENE)
    return num.array(colors)


class VolcanoesState(ElementState):
    visible = Bool.T(default=True)
    size = Float.T(default=3.0)

    def create(self):
        element = VolcanoesElement()
        return element


class VolcanoesElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._pipe = None
        self._controls = None
        self._volcanoes = None

    def bind_state(self, state):
        Element.bind_state(self, state)
        for var in ['visible', 'size']:
            self.register_state_listener3(self.update, state, var)

    def get_name(self):
        return 'Volcanoes'

    def set_parent(self, parent):
        self._parent = parent
        if not self._volcanoes:
            self._volcanoes = Volcanoes()

        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=True,
            remove=self.remove)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if not self._parent:
            return
        self._parent.remove_actor(self._pipe.actor)
        self._pipe = None

        self._parent.remove_panel(self._controls)
        self._controls = None

        self._parent.update_view()
        self._parent = None

    def update(self, *args):
        state = self._state

        if state.visible:
            if self._pipe is None:
                points = volcanoes_to_points(self._volcanoes.volcanoes)
                self._pipe = ScatterPipe(points)

                colors = volcanoes_to_color(self._volcanoes.volcanoes)
                self._pipe.set_colors(colors)

            self._pipe.set_size(state.size)
            self._pipe.set_symbol('sphere')
            self._parent.add_actor(self._pipe.actor)

        else:
            self._parent.remove_actor(self._pipe.actor)

        self._parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_checkbox, state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            layout.addWidget(qw.QLabel('Size'), 0, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(10)
            slider.setSingleStep(1)
            slider.setPageStep(1)
            layout.addWidget(slider, 0, 1)
            state_bind_slider(self, self._state, 'size', slider)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 1, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            layout.addWidget(qw.QFrame(), 2, 0, 1, 2)

            self._controls = frame

        return self._controls


__all__ = [
    'VolcanoesElement',
    'VolcanoesState'
]
