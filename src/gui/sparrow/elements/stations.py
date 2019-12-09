# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko.guts import \
    Object, Bool, Float, StringChoice, Timestamp, String, List

from pyrocko import cake, table, model, geometry
from pyrocko.client import fdsn
from pyrocko.gui.qt_compat import qw, qc, fnpatch

from pyrocko.gui.vtk_util import ScatterPipe
from .. import common

from .base import Element, ElementState

guts_prefix = 'sparrow'


def stations_to_points(stations):
    coords = num.zeros((len(stations), 3))

    for i, s in enumerate(stations):
        coords[i, :] = s.lat, s.lon, -s.elevation

    station_table = table.Table()

    station_table.add_col(('coords', '', ('lat', 'lon', 'depth')), coords)

    return geometry.latlondepth2xyz(
        station_table.get_col('coords'),
        planetradius=cake.earthradius)


class FDSNSiteChoice(StringChoice):
    choices = [key.upper() for key in fdsn.g_site_abbr.keys()]


class StationSelection(Object):
    pass


class FDSNStationSelection(StationSelection):
    site = String.T()
    tmin = Timestamp.T()
    tmax = Timestamp.T()

    def get_stations(self):
        return fdsn.station(
            site=self.site,
            format='text',
            level='channel',
            startbefore=self.tmin,
            endafter=self.tmax
        ).get_pyrocko_stations()


class FileStationSelection(StationSelection):
    paths = List.T(String.T())

    def get_stations(self):
        from pyrocko.io import stationxml

        stations = []
        for path in self.paths:
            if path.split('.')[-1].lower() in ['xml']:
                stxml = stationxml.load_xml(filename=path)
                stations.extend(stxml.get_pyrocko_stations())

            else:
                stations.extend(model.load_stations(path))

        return stations


class StationsState(ElementState):
    visible = Bool.T(default=True)
    size = Float.T(default=5.0)
    station_selection = StationSelection.T(optional=True)

    @classmethod
    def get_name(cls):
        return 'Stations'

    def create(self):
        element = StationsElement()
        element.bind_state(self)
        return element


class StationsElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._pipe = None
        self._state = None
        self._controls = None
        self._points = num.array([])

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'size')
        state.add_listener(upd, 'station_selection')
        self._state = state
        self._current_selection = None

    def unbind_state(self):
        self._listeners = []

    def get_name(self):
        return 'Stations'

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
                self._current_selection is not state.station_selection:

            self._parent.remove_actor(self._pipe.actor)
            self._pipe = None

        if self._pipe and not state.visible:
            self._parent.remove_actor(self._pipe.actor)
            self._pipe.set_size(state.size)

        if state.visible:
            if self._current_selection is not state.station_selection:
                stations = state.station_selection.get_stations()
                points = stations_to_points(stations)
                self._pipe = ScatterPipe(points)
                self._parent.add_actor(self._pipe.actor)
            elif self._pipe:
                self._parent.add_actor(self._pipe.actor)

            if self._pipe:
                self._pipe.set_size(state.size)

        self._parent.update_view()
        self._current_selection = state.station_selection

    def open_file_load_dialog(self):
        caption = 'Select one or more files to open'

        fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options))

        self._state.station_selection = FileStationSelection(
            paths=[str(fn) for fn in fns])

    def open_fdsn_load_dialog(self):
        dialog = qw.QDialog(self._parent)
        dialog.setWindowTitle('Get stations from FDSN web service')

        layout = qw.QHBoxLayout(dialog)

        layout.addWidget(qw.QLabel('Site'))

        sites = [key.upper() for key in fdsn.g_site_abbr.keys()]

        cb = qw.QComboBox()
        for i, s in enumerate(sites):
            cb.insertItem(i, s)

        layout.addWidget(cb)

        pb = qw.QPushButton('Cancel')
        pb.clicked.connect(dialog.reject)
        layout.addWidget(pb)

        pb = qw.QPushButton('Ok')
        pb.clicked.connect(dialog.accept)
        layout.addWidget(pb)

        dialog.exec_()

        site = str(cb.currentText()).lower()

        vstate = self._parent.state

        if dialog.result() == qw.QDialog.Accepted:
            self._state.station_selection = FDSNStationSelection(
                site=site,
                tmin=vstate.tmin,
                tmax=vstate.tmax)

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
            pb_fdsn = qw.QPushButton('FDSN')

            layout.addWidget(lab, 1, 0)
            layout.addWidget(pb_file, 1, 1)
            layout.addWidget(pb_fdsn, 1, 2)

            pb_file.clicked.connect(self.open_file_load_dialog)
            pb_fdsn.clicked.connect(self.open_fdsn_load_dialog)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 2, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, 2, 1)
            pb.clicked.connect(self.remove)

            layout.addWidget(qw.QFrame(), 3, 0, 1, 3)

            self._controls = frame

        return self._controls


__all__ = [
    'StationsElement',
    'StationsState',
]
