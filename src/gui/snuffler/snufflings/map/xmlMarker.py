# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

from pyrocko.guts import Object, String, Float, List


class XMLEventMarker(Object):
    xmltagname = 'eventmarker'
    active = String.T(default='no', xmlstyle='attribute')
    eventname = String.T(default='')
    latitude = Float.T(optional=False)
    longitude = Float.T(optional=False)
    origintime = String.T(default='')
    magnitude = Float.T(optional=False, default=0.0)
    depth = Float.T(optional=False)


class EventMarkerList(Object):
    xmltagname = 'eventmarkerlist'
    events = List.T(XMLEventMarker.T())


class XMLStationMarker(Object):
    xmltagname = 'stationmarker'
    active = String.T(default='no', xmlstyle='attribute')
    nsl = String.T()
    latitude = Float.T(optional=False)
    longitude = Float.T(optional=False)


class StationMarkerList(Object):
    xmltagname = 'stationmarkerlist'
    stations = List.T(XMLStationMarker.T())


class MarkerLists(Object):
    xmltagname = 'markerlists'
    station_marker_list = StationMarkerList.T()
    event_marker_list = EventMarkerList.T()
