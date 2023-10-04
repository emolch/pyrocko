# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Client to get earthquake catalog information from
`USGS <https://earthquake.usgs.gov/>`_.
'''

import time
import logging

from pyrocko import util, model
from pyrocko.util import urlopen_ssl_check
from .base_catalog import EarthquakeCatalog

logger = logging.getLogger('pyrocko.client.usgs')

km = 1000.


class USGS(EarthquakeCatalog):
    '''
    Client to get earthquake catalog information from
    `USGS <https://earthquake.usgs.gov/>`_.
    '''

    def __init__(self, catalog=None):
        self.catalog = catalog
        self.events = {}

    def flush(self):
        self.events = {}

    def iter_event_names(
            self,
            time_range=None,
            magmin=0.,
            magmax=10.,
            latmin=-90.,
            latmax=90.,
            lonmin=-180.,
            lonmax=180.):

        yearbeg, monbeg, daybeg = time.gmtime(time_range[0])[:3]
        yearend, monend, dayend = time.gmtime(time_range[1])[:3]

        p = []
        a = p.append
        a('format=geojson')
        if self.catalog is not None:
            a('catalog=%s' % self.catalog.lower())

        a('starttime=%s' % util.time_to_str(
            time_range[0], format='%Y-%m-%dT%H:%M:%S'))

        a('endtime=%s' % util.time_to_str(
            time_range[1], format='%Y-%m-%dT%H:%M:%S'))

        if latmin != -90.:
            a('minlatitude=%g' % latmin)
        if latmax != 90.:
            a('maxlatitude=%g' % latmax)
        if lonmin != -180.:
            a('minlongitude=%g' % lonmin)
        if lonmax != 180.:
            a('maxlongitude=%g' % lonmax)
        if magmin != 0.:
            a('minmagnitude=%g' % magmin)
        if magmax != 10.:
            a('maxmagnitude=%g' % magmax)

        url = 'https://earthquake.usgs.gov/fdsnws/event/1/query?' + '&'.join(p)

        logger.debug('Opening URL: %s' % url)
        page = urlopen_ssl_check(url).read()
        logger.debug('Received page (%i bytes)' % len(page))

        events = self._parse_events_page(page)

        for ev in events:
            self.events[ev.name] = ev

        for ev in events:
            if time_range[0] <= ev.time and ev.time <= time_range[1]:
                yield ev.name

    def _parse_events_page(self, page):

        import json
        doc = json.loads(page.decode('utf-8'))

        events = []
        for feat in doc['features']:
            props = feat['properties']
            geo = feat['geometry']
            lon, lat, depth = [float(x) for x in geo['coordinates']]
            t = util.str_to_time('1970-01-01 00:00:00') + \
                props['time'] * 0.001

            if props['mag'] is not None:
                mag = float(props['mag'])
            else:
                mag = None

            if props['place'] is not None:
                region = props['place'].encode('ascii', 'replace').decode()
            else:
                region = None

            catalog = str(props['net'].upper())
            name = 'USGS-%s-' % catalog + util.time_to_str(
                t, format='%Y-%m-%d_%H-%M-%S.3FRAC')

            ev = model.Event(
                lat=lat,
                lon=lon,
                time=t,
                name=name,
                depth=depth*1000.,
                magnitude=mag,
                region=region,
                catalog=catalog)

            events.append(ev)

        return events

    def get_event(self, name):
        if name not in self.events:
            t = self._name_to_date(name)
            for name2 in self.iter_event_names(
                    time_range=(t-24*60*60, t+24*60*60)):

                if name2 == name:
                    break

        return self.events[name]

    def _name_to_date(self, name):
        ds = name[-23:]
        t = util.str_to_time(ds, format='%Y-%m-%d_%H-%M-%S.3FRAC')
        return t
