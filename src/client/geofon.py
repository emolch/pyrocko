# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Client to get earthquake catalog information from
`GEOFON <http://geofon.gfz-potsdam.de/>`_.
'''

import time
import re
import logging
import json

from pyrocko import model, util
from pyrocko.moment_tensor import MomentTensor, symmat6
from .base_catalog import EarthquakeCatalog, NotFound

from pyrocko.util import urlopen

logger = logging.getLogger('pyrocko.client.geofon')

km = 1000.


class Geofon(EarthquakeCatalog):
    '''
    Access the GEOFON earthquake catalog.
    '''
    def __init__(self, get_moment_tensors=True):
        self.events = {}
        self._get_moment_tensors = get_moment_tensors

    def flush(self):
        self.events = {}

    def iter_event_names(
            self,
            time_range=None,
            nmax=1000,
            magmin=None,
            latmin=-90.,
            latmax=90.,
            lonmin=-180.,
            lonmax=180.):

        logger.debug('In Geofon.iter_event_names(...)')

        dmin = time.strftime('%Y-%m-%d', time.gmtime(time_range[0]))
        dmax = time.strftime('%Y-%m-%d', time.gmtime(time_range[1]+24*60*60))

        if magmin is None:
            magmin = ''
        else:
            magmin = '%g' % magmin

        ipage = 1
        while True:
            url = ('http://geofon.gfz-potsdam.de/eqinfo/list.php?' + '&'.join([
                'page=%i' % ipage,
                'datemin=%s' % dmin,
                'datemax=%s' % dmax,
                'latmin=%g' % latmin,
                'latmax=%g' % latmax,
                'lonmin=%g' % lonmin,
                'lonmax=%g' % lonmax,
                'magmin=%s' % magmin,
                'fmt=geojson',
                'nmax=%i' % nmax]))

            logger.debug('Opening URL: %s' % url)
            page = urlopen(url).read()
            logger.debug('Received page (%i bytes)' % len(page))
            events = self._parse_events_page(page)
            for ev in events:
                if ev.moment_tensor is True:
                    ev.moment_tensor = self.get_mt(ev)

            if not events:
                break

            for ev in events:
                if time_range[0] <= ev.time and ev.time <= time_range[1]:
                    self.events[ev.name] = ev
                    yield ev.name

            ipage += 1

    def get_event(self, name):
        logger.debug('In Geofon.get_event("%s")' % name)

        if name not in self.events:
            url = 'http://geofon.gfz-potsdam.de/eqinfo/event.php' \
                  '?id=%s&fmt=geojson' % name
            logger.debug('Opening URL: %s' % url)
            page = urlopen(url).read()
            logger.debug('Received page (%i bytes)' % len(page))

            try:
                ev = self._parse_event_page(page)
                self.events[name] = ev

            except NotFound:
                raise NotFound(url)  # reraise with url

        ev = self.events[name]

        if ev.moment_tensor is True:
            ev.moment_tensor = self.get_mt(ev)

        return ev

    def get_mt(self, ev):
        syear = time.strftime('%Y', time.gmtime(ev.time))
        url = 'http://geofon.gfz-potsdam.de/data/alerts/%s/%s/mt.txt' % (
            syear, ev.name)

        try:
            logger.debug('Opening URL: %s' % url)
            page = urlopen(url).read()
            logger.debug('Received page (%i bytes)' % len(page))
        except util.HTTPError:
            logger.warning('No MT found for event "%s".' % ev.name)
            return None

        return self._parse_mt_page(page)

    def _parse_mt_page(self, page):
        d = {}
        for k in 'Scale', 'Mrr', 'Mtt', 'Mpp', 'Mrt', 'Mrp', 'Mtp':
            r = k.encode('ascii')+br'\s*=?\s*(\S+)'
            m = re.search(r, page)
            if m:
                s = m.group(1).replace(b'10**', b'1e')
                d[k.lower()] = float(s)

        m = symmat6(*(d[x] for x in 'mrr mtt mpp mrt mrp mtp'.split()))
        m *= d['scale']
        mt = MomentTensor(m_up_south_east=m)

        return mt

    def _parse_events_page(self, page, limit=None):
        j = json.loads(page.decode('utf-8'))
        events = []
        for ifeature, feature in enumerate(j['features']):
            ev = self._json_feature_to_event(feature)
            events.append(ev)
            if limit and ifeature + 1 == limit:
                break

        return events

    def _parse_event_page(self, page):
        return self._parse_events_page(page, limit=1)[0]

    def _json_feature_to_event(self, feature):
        name = feature['id']
        lon, lat, depth = feature['geometry']['coordinates']
        depth *= 1000.
        properties = feature['properties']
        magnitude = properties['mag']
        magnitude_type = properties['magType']
        region = properties['place']
        tevent = util.str_to_time(properties['time'].replace('T', ' '))

        if ((properties.get('hasMT', 'no') == 'yes')
                or properties['magType'] == 'Mw') and self._get_moment_tensors:

            moment_tensor = True  # flag for caller to query MT
        else:
            moment_tensor = None

        status = properties['status'][:1]
        tags = []
        if status in 'AMC':
            tags.append('geofon_status:%s' % status)

        category = properties.get('evtype', '')
        if re.match(r'^[a-zA-Z0-9]+$', category):
            tags.append('geofon_category:%s' % category)

        ev = model.Event(
            lat=float(lat),
            lon=float(lon),
            time=tevent,
            name=name,
            depth=float(depth),
            magnitude=float(magnitude),
            magnitude_type=str(magnitude_type),
            region=str(region),
            moment_tensor=moment_tensor,
            catalog='GEOFON',
            tags=tags)

        return ev
