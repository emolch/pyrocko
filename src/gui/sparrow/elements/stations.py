# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num
from pyrocko.guts import \
    Object, Bool, Float, StringChoice, Timestamp, String, List

from pyrocko import cake, table, model
from pyrocko.client import fdsn
from pyrocko.gui.qt_compat import qw, qc, fnpatch

from pyrocko.gui.vtk_util import ScatterPipe
from .. import common
from pyrocko import geometry

from .base import Element, ElementState

guts_prefix = 'sparrow'


def stations_to_points(stations):
    # coords = num.zeros((len(stations), 3))
    statable = table.Table()

    keys = stations[0].__dict__
    statable.add_cols(
        [table.Header(name=name) for name in keys.iterkeys()],
        [num.array([station.__dict__[key] for station in stations])
            .astype(object) for key in keys],
        [i for i in len(keys) * [None]])

    # for attr in stations[0].iterkeys():

    # stationtable.add_cols(
    #     [table.Header(name=name) for name in
    #         ['Latitude', 'Longitude', 'Depth', 'StationID', 'NetworkID']],
    #     [coords, stat_names, net_names],
    #     [table.Header(name=name) for name in['Coordinates', None, None]])

    latlondepth = num.array([
        statable.get_col('lat').astype(float),
        statable.get_col('lon').astype(float),
        statable.get_col('elevation').astype(float)])
    print(latlondepth)
    return geometry.latlondepth2xyz(
        latlondepth,
        planetradius=cake.earthradius)


class LoadingChoice(StringChoice):
    choices = [choice.upper() for choice in [
        'file',
        'fdsn']]


class FDSNSiteChoice(StringChoice):
    choices = [key.upper() for key in fdsn.g_site_abbr.iterkeys()]


class StationSelection(Object):
    pass


class FDSNStationSelection(StationSelection):
    site = String.T()
    tmin = Timestamp.T()
    tmax = Timestamp.T()

    def get_stations(self):
        return [fdsn.station(
            site=self.site,
            format='text',
            level='channel',
            channel='??Z',
            startbefore=self.tmin,
            endafter=self.tmax
        ).get_pyrocko_stations()]


class FileStationSelection(StationSelection):
    paths = List.T(String.T())

    def get_stations(self):
        stations = [model.load_stations(str(path)) for path in self.paths]
        return [station for sublist in stations for station in sublist]


class StationsState(ElementState):
    visible = Bool.T(default=False)
    size = Float.T(default=5.0)
    station_selection = StationSelection.T(optional=True)

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
        self._parent = None
        self._pipe = None
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

        if self._pipe and not state.visible:
            self._parent.remove_actor(self._pipe.actor)
            self._pipe.set_size(state.size)

        if state.visible:
            if self._current_selection is not state.station_selection:
                stations = state.station_selection.get_stations()
                points = stations_to_points(stations)
                print(points)
                self._pipe = ScatterPipe(points)
                self._parent.add_actor(self._pipe.actor)

            if self._pipe:
                self._pipe.set_size(state.size)

        self._parent.update_view()

    def update_stationstate(self, loadingchoice, site=None):
        assert loadingchoice in LoadingChoice.choices

        if loadingchoice == 'FILE':
            caption = 'Select one or more files to open'

            fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
                self, caption, options=common.qfiledialog_options))
            self._state.station_selection = FDSNStationSelection(
                paths=[fn for fn in fns])

            # stations = [model.load_stations(str(x)) for x in fns]
            # for stat in stations:
            #     self.add_stations(stat)

            self._state.visible = True

        elif loadingchoice == 'FDSN':
            self._state.FDSNStationsState.site = site
            self._state.visible = True

    def file2points(self):
        stations = model.load_stations(self._state.FileStationsState.file)
        coords = num.zeros((len(stations), 3))
        stat_names = num.ndarray(shape=(len(stations), 1), dtype=object)
        net_names = num.ndarray(shape=(len(stations), 1), dtype=object)

        for ista, station in enumerate(stations):
            coords[ista, :] = [station.lat, station.lon, station.depth]

            stat_names[ista] = station.station
            net_names[ista] = station.network

        stationtable = table.Table()

        stationtable.add_cols(
            [table.Header(name=name) for name in
                ['Latitude', 'Longitude', 'Depth', 'StationID', 'NetworkID']],
            [coords, stat_names, net_names],
            [table.Header(name=name) for name in['Coordinates', None, None]])

        self._points = geometry.latlondepth2xyz(
            stationtable.get_col_group('Coordinates'),
            planetradius=cake.earthradius)

        return self._points

    def fdsn2points(self):
        fdsnstate = self._state.FDSNStationsState

        tmin = fdsnstate.tmin
        tmax = fdsnstate.tmax
        sx = fdsn.station(
            site=fdsnstate.site, format='text', level='channel', channel='??Z',
            startbefore=tmin, endafter=tmax)

        stations = sx.get_pyrocko_stations()

        latlondepth = num.array([(s.lat, s.lon, 0.) for s in stations])
        self._points = geometry.latlondepth2xyz(
            latlondepth,
            planetradius=cake.earthradius)

        return self._points

    def open_file_load_dialog(self):
        caption = 'Select one or more files to open'

        fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options))

        self._state.station_selection = FileStationSelection(
            paths=[str(fn) for fn in fns])

    def open_fdsn_load_dialog(self):
        pass

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
            pb.clicked.connect(self.unset_parent)

            layout.addWidget(qw.QFrame(), 3, 0, 1, 3)

        self._controls = frame

        return self._controls


__all__ = [
    'StationsElement',
    'StationsState',
]
