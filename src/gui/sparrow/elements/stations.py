# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import time

import numpy as num
from pyrocko.guts import Bool, Float, String, Any, Timestamp, StringChoice
from pyrocko import cake, table
from pyrocko.client import fdsn
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.gui.vtk_util import ScatterPipe
from .. import common
from pyrocko import geometry

from .base import Element, ElementState

guts_prefix = 'sparrow'


class LoadingChoice(StringChoice):
    choices = [choice.upper() for choice in [
        'file',
        'fdsn']]


class FDSNSiteChoice(StringChoice):
    choices = [key.upper() for key in fdsn.g_site_abbr.iterkeys()]


class FDSNStationsState:

    def __init__(self,site=None,tmin=time.time()-3600.,tmax=time.time()):
        self.site = site
        self.tmin = tmin
        self.tmax = tmax


class FileStationsState:

    def __init__(self,file=None):
        self.file = file


class StationsState(ElementState):
    visible = Bool.T(default=False)
    size = Float.T(default=5.0)
    FDSNStationsState = FDSNStationsState()
    FileStationsState = FileStationsState(file=None)

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
        state.add_listener(upd, 'FileStationsState')
        self._state = state

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
            if not self._pipe and self._state.FileStationsState.file:
                self._points = self.file2points()
                self._pipe = ScatterPipe(self._points)
                self._parent.add_actor(self._pipe.actor)

            if not self._pipe and self._state.FDSNStationsState.site:
                self._points = self.fdsn2points()
                self._pipe = ScatterPipe(self._points)
                self._parent.add_actor(self._pipe.actor)

            elif self._pipe:
                self._parent.add_actor(self._pipe.actor)

            self._pipe.set_size(state.size)

        self._parent.update_view()

    def update_stationstate(self,loadingchoice,site=None):
        assert loadingchoice in LoadingChoice.choices

        if loadingchoice=='FILE':
            caption = 'Select one or more files to open'

            fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
                self, caption, options=qfiledialog_options))

            stations = [pyrocko.model.load_stations(str(x)) for x in fns]
            for stat in stations:
                self.add_stations(stat)
            
            self._state.FileStationsState.file = #'/home/mmetz/Documents/MA/data/stations_fdsn'
            
            self._state.visible = True

        elif loadingchoice=='FDSN':
            self._state.FDSNStationsState.site=site
            self._state.visible = True

    def file2points(self):
        from pyrocko.model.station import load_stations

        stations = load_stations(self._state.FileStationsState.file)
        coords = num.zeros((len(stations),3))
        stat_names = num.ndarray(shape=(len(stations),1), dtype=object)
        net_names = num.ndarray(shape=(len(stations),1), dtype=object)

        for ista,station in enumerate(stations):
            coords[ista,:] = [station.lat,station.lon,station.depth]

            stat_names[ista] = station.station
            net_names[ista] = station.network

        stationtable = table.Table()
        Header = [table.Header(name=name) for name in ['Latitude','Longitude','Depth']]
        stationtable.add_cols([table.Header(name=name) for name in
                            ['Latitude','Longitude','Depth','StationID','NetworkID']],
                            [coords,stat_names,net_names],
                            [table.Header(name=name) for name in['Coordinates',None,None]])


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

    def _get_controls(self):
        if not self._controls:
            from ..state \
                import state_bind_combobox, state_bind_checkbox, state_bind_slider

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

            pb = qw.QPushButton('Load from')
            layout.addWidget(pb, 1, 0)
            
            cb1 = common.string_choices_to_combobox(LoadingChoice)
            layout.addWidget(cb1, 1, 1)

            cb2 = common.string_choices_to_combobox(FDSNSiteChoice)
            layout.addWidget(cb2, 2, 1)
            pb.clicked.connect(lambda: 
                self.update_stationstate(
                    str(cb1.currentText()),
                    str(cb2.currentText()).lower()))

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 3, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, 3, 1)
            pb.clicked.connect(self.unset_parent)

            layout.addWidget(qw.QFrame(), 4, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'StationsElement',
    'StationsState',
]
