# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko.guts import \
    Object, Bool, Float, StringChoice, String, List

from pyrocko import cake, table, model
from pyrocko.client import fdsn
from pyrocko.gui.qt_compat import qw, qc, fnpatch

from pyrocko.gui.vtk_util import ScatterPipe
from .. import common
from pyrocko import geometry

from .base import Element, ElementState

guts_prefix = 'sparrow'


def events_to_points(events):
    coords = num.zeros((len(events), 3))

    for i, ev in enumerate(events):
        coords[i, :] = ev.lat, ev.lon, ev.depth

    station_table = table.Table()

    station_table.add_cols(
        [table.Header(name=name) for name in
            ['lat', 'lon', 'depth']],
        [coords],
        [table.Header(name=name) for name in['coords']])

    return geometry.latlondepth2xyz(
        station_table.get_col_group('coords'),
        planetradius=cake.earthradius)


class LoadingChoice(StringChoice):
    choices = [choice.upper() for choice in [
        'file',
        'fdsn']]


class FDSNSiteChoice(StringChoice):
    choices = [key.upper() for key in fdsn.g_site_abbr.keys()]


class CatalogSelection(Object):
    pass


class FileCatalogSelection(CatalogSelection):
    paths = List.T(String.T())

    def get_events(self):
        from pyrocko.io import quakeml

        events = []
        for path in self.paths:
            if path.split('.')[-1].lower() in ['xml', 'qml', 'quakeml']:
                qml = quakeml.QuakeML.load_xml(filename=path)
                events.extend(qml.get_pyrocko_events())

            else:
                events.extend(model.load_events(path))

        return events


class CatalogState(ElementState):
    visible = Bool.T(default=True)
    size = Float.T(default=5.0)
    catalog_selection = CatalogSelection.T(optional=True)

    @classmethod
    def get_name(self):
        return 'Catalog'

    def create(self):
        element = CatalogElement()
        element.bind_state(self)
        return element


class CatalogElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._pipe = None
        self._controls = None
        self._points = num.array([])

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'size')
        state.add_listener(upd, 'catalog_selection')
        self._state = state
        self._current_selection = None

    def unbind_state(self):
        self._listeners = []

    def get_name(self):
        return 'Catalog'

    def set_parent(self, parent):
        self._parent = parent
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._pipe:
                self._parent.remove_actor(self._pipe.actor)
                self._pipe = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def update(self, *args):
        state = self._state
        if self._pipe and \
                self._current_selection is not state.catalog_selection:

            self._parent.remove_actor(self._pipe.actor)
            self._pipe = None

        if self._pipe and not state.visible:
            self._parent.remove_actor(self._pipe.actor)
            self._pipe.set_size(state.size)

        if state.visible:
            if self._current_selection is not state.catalog_selection:
                events = state.catalog_selection.get_events()
                points = events_to_points(events)
                self._pipe = ScatterPipe(points)
                self._parent.add_actor(self._pipe.actor)

            if self._pipe:
                self._pipe.set_size(state.size)

        self._parent.update_view()

    def open_file_load_dialog(self):
        caption = 'Select one or more files to open'

        fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options))

        self._state.catalog_selection = FileCatalogSelection(
            paths=[str(fn) for fn in fns])

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
            slider.setSingleStep(0.5)
            slider.setPageStep(0.5)
            layout.addWidget(slider, 0, 1)
            state_bind_slider(self, self._state, 'size', slider)

            lab = qw.QLabel('Load from:')
            pb_file = qw.QPushButton('File')

            layout.addWidget(lab, 1, 0)
            layout.addWidget(pb_file, 1, 1)

            pb_file.clicked.connect(self.open_file_load_dialog)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 2, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, 2, 1)
            pb.clicked.connect(self.unset_parent)

            layout.addWidget(qw.QFrame(), 3, 0, 1, 3)

        self._controls = frame

        return self._controls


__all__ = [
    'CatalogElement',
    'CatalogState',
]
