# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from pyrocko import table, geometry, cake
from pyrocko.guts import Bool, Float
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.dataset.geonames import \
    get_countries_region, get_cities_region
from pyrocko.gui.vtk_util import ScatterPipe, TextPipe

from .base import Element, ElementState

guts_prefix = 'sparrow'

km = 1e3


CITIES_ORIENTATION = (0, -45, 45)
COUNTRIES_ORIENTATION = (0, 0, 0)


def locations_to_points(locations):
    locations = [loc for loc in locations if loc.lat is not None]
    coords = num.zeros((len(locations), 3))

    for i, v in enumerate(locations):
        coords[i, :] = v.lat, v.lon, 0 - 10*km

    loc_table = table.Table()
    loc_table.add_col(('coords', '', ('lat', 'lon', 'depth')), coords)

    points = geometry.latlondepth2xyz(
        loc_table.get_col('coords'),
        planetradius=cake.earthradius)
    return points, locations


def cities_to_color(cities, lightness):
    return num.full((len(cities), 3), lightness)


class GeonamesState(ElementState):
    visible = Bool.T(default=True)
    show_cities = Bool.T(default=False)
    show_country_names = Bool.T(default=False)
    marker_size_cities = Float.T(default=3.0)
    label_size_cities = Float.T(default=0.01)
    label_size_countries = Float.T(default=0.01)
    lightness_cities = Float.T(default=0.9)
    lightness_countries = Float.T(default=0.9)

    def create(self):
        element = GeonamesElement()
        return element


class GeonamesElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._cities_pipe = None
        self._cities_label_pipe = None
        self._countries_pipe = None
        self._controls = None
        self._countries = None
        self._cities = None

    def bind_state(self, state):
        Element.bind_state(self, state)
        self.talkie_connect(
            state,
            ['visible', 'show_cities',
             'show_country_names', 'marker_size_cities',
             'label_size_countries', 'label_size_cities',
             'lightness_countries', 'lightness_cities'],
            self.update)

    def get_name(self):
        return 'Geonames'

    def set_parent(self, parent):
        self._parent = parent
        if not self._countries:
            self._countries = get_countries_region(
                minpop=1e6, minarea=8000)

        if not self._cities:
            self._cities = get_cities_region(minpop=1e6)

        self._parent.add_panel(
            self.get_title_label(),
            self._get_controls(),
            visible=True,
            title_controls=[
                self.get_title_control_remove(),
                self.get_title_control_visible()])

        self.update()

    def remove_cities(self):
        if self._cities_pipe is not None:
            self._parent.remove_actor(self._cities_pipe.actor)
            self._cities_pipe = None

        if self._cities_label_pipe is not None:
            for act in self._cities_label_pipe.actor:
                self._parent.remove_actor(act)
            self._cities_label_pipe = None

    def remove_countries(self):
        if self._countries_pipe is not None:
            for act in self._countries_pipe.actor:
                self._parent.remove_actor(act)
            self._countries_pipe = None

    def unset_parent(self):
        self.unbind_state()
        if not self._parent:
            return

        self.remove_cities()
        self.remove_countries()

        self._parent.remove_panel(self._controls)
        self._controls = None

        self._parent.update_view()
        self._parent = None

    def update_cities(self):
        state = self._state

        if state.show_cities:
            points, _ = locations_to_points(self._cities)
            colors = cities_to_color(self._cities, state.lightness_cities)
            if self._cities_pipe is None:
                self._cities_pipe = ScatterPipe(points)
                self._cities_pipe.set_colors(colors)
                self._parent.add_actor(self._cities_pipe.actor)

            self._cities_pipe.set_size(state.marker_size_cities)
            self._cities_pipe.set_symbol('sphere')
            self._cities_pipe.set_colors(colors)

            if self._cities_label_pipe is None:
                camera = self._parent.ren.GetActiveCamera()
                labels = [c.asciiname for c in self._cities]
                self._cities_label_pipe = TextPipe(
                    points, labels, camera=camera)

                for actor in self._cities_label_pipe.actor:
                    self._parent.add_actor(actor)

            self._cities_label_pipe.set_label_size(state.label_size_cities)
            lightness = state.lightness_cities
            self._cities_label_pipe.set_colors(
                (lightness, lightness, lightness))
            self._cities_label_pipe.set_orientation(CITIES_ORIENTATION)
        else:
            self.remove_cities()

    def update_countries(self):
        state = self._state

        if state.show_country_names:
            points, countries = locations_to_points(self._countries)
            if self._countries_pipe is None:
                camera = self._parent.ren.GetActiveCamera()
                labels = [c.name for c in countries]
                self._countries_pipe = TextPipe(
                    points, labels, camera=camera)

                for actor in self._countries_pipe.actor:
                    self._parent.add_actor(actor)

            self._countries_pipe.set_label_size(state.label_size_countries)
            lightness = state.lightness_countries
            self._countries_pipe.set_colors(
                (lightness, lightness, lightness))
            self._countries_pipe.set_orientation(COUNTRIES_ORIENTATION)
        else:
            self.remove_countries()

    def update(self, *args):
        state = self._state

        if state.visible:
            self.update_cities()
            self.update_countries()
        else:
            self.remove_cities()
            self.remove_countries()

        self._parent.update_view()

    def _get_controls(self):
        state = self._state
        if not self._controls:
            from ..state import state_bind_slider, state_bind_checkbox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            # Cities
            il = 0
            layout.addWidget(qw.QLabel('Cities'), il, 0)

            chb = qw.QCheckBox('show')
            layout.addWidget(chb, il, 1)
            state_bind_checkbox(self, state, 'show_cities', chb)

            # Marker size
            il += 1
            layout.addWidget(qw.QLabel('Marker size'), il, 1)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(20)
            slider.setSingleStep(1)
            slider.setPageStep(1)
            layout.addWidget(slider, il, 2)
            state_bind_slider(self, state, 'marker_size_cities', slider)

            # Label size
            il += 1
            layout.addWidget(qw.QLabel('Label size'), il, 1)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0.1)
            slider.setMaximum(3000)
            layout.addWidget(slider, il, 2)
            state_bind_slider(
                self, state, 'label_size_cities', slider, factor=0.00001)

            # Lightness
            il += 1
            layout.addWidget(qw.QLabel('Lightness'), il, 1)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(1000)
            layout.addWidget(slider, il, 2)

            state_bind_slider(
                self, state, 'lightness_cities', slider, factor=0.001)

            # Countries
            il += 1
            layout.addWidget(qw.QLabel('Countries'), il, 0)

            chb = qw.QCheckBox('show')
            layout.addWidget(chb, il, 1)
            state_bind_checkbox(self, state, 'show_country_names', chb)

            # Label size
            il += 1
            layout.addWidget(qw.QLabel('Label size'), il, 1)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0.1)
            slider.setMaximum(3000)
            layout.addWidget(slider, il, 2)
            state_bind_slider(
                self, state, 'label_size_countries',
                slider, factor=0.00001)

            # Lightness
            il += 1
            layout.addWidget(qw.QLabel('Lightness'), il, 1)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(1000)
            layout.addWidget(slider, il, 2)

            state_bind_slider(
                self, state, 'lightness_countries', slider, factor=0.001)

            self._controls = frame

        return self._controls


__all__ = [
    'GeonamesElement',
    'GeonamesState'
]
