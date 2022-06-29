# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

from pyrocko.gui.snuffler.snuffling import Snuffling
from pyrocko.gui.snuffler.marker import EventMarker

from pyrocko.client import catalog


class GeofonEvents(Snuffling):
    '''
    Get events from GEOFON catalog.
    '''

    def __init__(self, magmin=None):
        self._magmin = magmin
        Snuffling.__init__(self)

    def setup(self):
        '''
        Customization of the snuffling.
        '''

        if self._magmin is None:
            self.set_name('Get GEOFON Events')
        else:
            self.set_name('Get GEOFON Events (> M %g)' % self._magmin)

    def call(self):
        '''
        Main work routine of the snuffling.
        '''

        # get time range visible in viewer
        viewer = self.get_viewer()
        tmin, tmax = viewer.get_time_range()

        # download event information from GEOFON web page
        # 1) get list of event names
        geofon = catalog.Geofon()
        event_names = geofon.get_event_names(
            time_range=(tmin, tmax),
            magmin=self._magmin)

        # 2) get event information and add a marker in the snuffler window
        for event_name in event_names:
            event = geofon.get_event(event_name)
            marker = EventMarker(event)
            self.add_markers([marker])


def __snufflings__():
    '''
    Returns a list of snufflings to be exported by this module.
    '''

    return [
        GeofonEvents(),
        GeofonEvents(magmin=6),
        GeofonEvents(magmin=7),
        GeofonEvents(magmin=8)]
