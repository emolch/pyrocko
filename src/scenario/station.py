# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, division, print_function

import numpy as num
from pyrocko import model
from pyrocko.guts import Int, String, List, Float, Bool

from pyrocko.model.station import load_stations
from pyrocko.io import stationxml
from pyrocko.orthodrome import distance_accurate50m_numpy, \
    geographic_midpoint_locations

from .base import LocationGenerator

guts_prefix = 'pf.scenario'
km = 1e3
d2r = num.pi / 180.


class StationGenerator(LocationGenerator):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._stations = None

    def get_stations(self):
        raise NotImplementedError

    @property
    def nstations(self):
        return len(self.get_stations())

    def has_stations(self):
        if not self.get_stations():
            return False
        return True

    def clear(self):
        super().clear()
        self._stations = None

    def get_distance_range(self, sources):
        dists = []
        for source in sources:
            for station in self.get_stations():
                dists.append(
                    source.distance_to(station))

        return num.min(dists), num.max(dists)

    def ensure_data(self, engine, sources, path, tmin=None, tmax=None):
        return []

    def add_map_artists(self, engine, sources, automap):
        automap.add_stations(self.get_stations())


class ImportStationGenerator(StationGenerator):

    stations_paths = List.T(
        optional=True,
        help='List of files with station coordinates in Pyrocko format.')

    stations_stationxml_paths = List.T(
        optional=True,
        help='List of files with station coordinates in StationXML format.')

    stations = List.T(
        model.Station.T(),
        optional=True,
        help='List of Pyrocko stations.')

    def get_center_latlon(self):
        stations = self.get_stations()
        if not stations:
            return self._parent.get_center_latlon()

        return geographic_midpoint_locations(self.get_stations())

    def get_radius(self):
        stations = self.get_stations()
        if not stations:
            return self._parent.get_radius()

        clat, clon = self.get_center_latlon()
        radii = distance_accurate50m_numpy(
                clat, clon,
                [st.effective_lat for st in stations],
                [st.effective_lon for st in stations])

        return float(radii.max())

    def get_stations(self):
        if self._stations is None:

            stations = []

            if self.stations_paths:
                for filename in self.stations_paths:
                    stations.extend(
                        load_stations(filename))

            if self.stations_stationxml_paths:
                for filename in self.stations_stationxml_paths:
                    sxml = stationxml.load_xml(filename=filename)
                    stations.extend(
                        sxml.cko_stations())

            if self.stations:
                stations.extend(self.stations)

            self._stations = stations

        return self._stations

    def nsl(self, istation):
        stations = self.get_stations()
        return stations[istation].nsl()


class CircleStationGenerator(StationGenerator):

    radius = Float.T(
        default=100*km,
        help='Radius of the station circle in km.')

    azi_start = Float.T(
        default=0.,
        help='Start azimuth of circle [deg]. '
             'Default is a full circle, 0 - 360 deg')

    azi_end = Float.T(
        default=360.,
        help='End azimuth of circle [deg]. '
             'Default is a full circle, 0 - 360 deg')

    nstations = Int.T(
        default=10,
        help='Number of evenly spaced stations.')

    network_name = String.T(
        default='CI',
        help='Network name.')

    channels = List.T(
        default=['BHE', 'BHN', 'BHZ'],
        help='Seismic channels to generate. Default: BHN, BHE, BHZ.')

    shift_circle = Bool.T(
        default=False,
        help='Rotate circle away by half a station distance.')

    def get_stations(self):
        if self._stations is None:
            if self.channels:
                channels = [model.station.Channel(c) for c in self.channels]
            else:
                channels = None

            azimuths = num.linspace(
                self.azi_start*d2r, self.azi_end*d2r,
                self.nstations, endpoint=False)

            if self.shift_circle:
                swath = (self.azi_end - self.azi_start)*d2r
                azimuths += swath / self.nstations / 2.

            lat, lon = self.get_center_latlon()

            stations = []
            for istation, azi in enumerate(azimuths):
                net, sta, loc = self.nsl(istation)

                station = model.Station(
                    net, sta, loc,
                    lat=lat,
                    lon=lon,
                    north_shift=num.cos(azi) * self.radius,
                    east_shift=num.sin(azi) * self.radius,
                    channels=channels)

                stations.append(station)

            self._stations = stations

        return self._stations

    def nsl(self, istation):
        return self.network_name, 'S%03i' % (istation + 1), ''

    def get_radius(self):
        return self.radius

    def clear(self):
        super().clear()
        self._stations = None


class RandomStationGenerator(StationGenerator):

    nstations = Int.T(
        default=10,
        help='Number of randomly distributed stations.')

    network_name = String.T(
        default='CO',
        help='Network name')

    channels = List.T(
        optional=True,
        default=['BHE', 'BHN', 'BHZ'],
        help='Seismic channels to generate. Default: BHN, BHE, BHZ')

    def nsl(self, istation):
        return self.network_name, 'S%03i' % (istation + 1), '',

    def get_stations(self):
        if self._stations is None:

            if self.channels:
                channels = [model.station.Channel(c) for c in self.channels]
            else:
                channels = None

            stations = []
            for istation in range(self.nstations):
                lat, lon, north_shift, east_shift, depth = map(
                    float, self.get_coordinates(istation))

                net, sta, loc = self.nsl(istation)
                station = model.Station(
                    net, sta, loc,
                    lat=lat,
                    lon=lon,
                    north_shift=north_shift,
                    east_shift=east_shift,
                    depth=depth,
                    channels=channels)

                stations.append(station)

            self._stations = stations

        return self._stations
