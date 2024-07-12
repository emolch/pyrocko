# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Client to get earthquake catalog information from
`ISC <http://www.isc.ac.uk/>`_.
'''

import logging
import re

from pyrocko import util
from pyrocko.util import urlopen
from pyrocko.io import quakeml
from .base_catalog import EarthquakeCatalog

logger = logging.getLogger('pyrocko.client.isc')

km = 1000.


class ISCError(Exception):
    pass


class ISCBlocked(ISCError):
    pass


class ISC(EarthquakeCatalog):
    '''
    Interfacing the catalog of the Internation Seismological Centre (ISC).
    '''

    def __init__(self, catalog=None):
        self.events = {}

    def flush(self):
        self.events = {}

    def append_time_params(self, a, time_range):
        date_start_s, tstart_s = util.time_to_str(
            time_range[0], format='%Y-%m-%d %H:%M:%S').split()
        date_end_s, tend_s = util.time_to_str(
            time_range[1], format='%Y-%m-%d %H:%M:%S').split()
        date_start_s = date_start_s.split('-')
        date_end_s = date_end_s.split('-')

        a('start_year=%s' % date_start_s[0])
        a('start_month=%s' % date_start_s[1])
        a('start_day=%s' % date_start_s[2])
        a('start_time=%s' % tstart_s)

        a('end_year=%s' % date_end_s[0])
        a('end_month=%s' % date_end_s[1])
        a('end_day=%s' % date_end_s[2])
        a('end_time=%s' % tend_s)

    def iter_event_names(
            self,
            time_range=None,
            magmin=None,
            magmax=None,
            latmin=-90.,
            latmax=90.,
            lonmin=-180.,
            lonmax=180.):
        p = []
        a = p.append

        a('out_format=CATQuakeML')
        a('request=REVIEWED')
        a('searchshape=RECT')

        self.append_time_params(a, time_range)

        if magmin:
            a('min_mag=%g' % magmin)
        if magmax:
            a('max_mag=%g' % magmax)

        a('bot_lat=%g' % latmin)
        a('top_lat=%g' % latmax)
        a('left_lon=%g' % lonmin)
        a('right_lon=%g' % lonmax)
        url = 'http://www.isc.ac.uk/cgi-bin/web-db-v4?' + '&'.join(p)

        logger.debug('Opening URL: %s' % url)
        page = urlopen(url).read().decode()
        logger.debug('Received page (%i bytes)' % len(page))

        if 'The search could not be run due to problems' in page:
            logger.warning('%s\nurl: %s' % (page, url))
            return
        elif 'No events were found.' in page:
            logger.info('No events were found.')
            events = []
        else:
            try:
                data = quakeml.QuakeML.load_xml(string=page)
            except Exception:
                if page[:500].find(
                        'Please try again in a few minutes') != -1:

                    raise ISCBlocked(
                        'Apparently, we have queried ISC too eagerly:\n'
                        + '-' * 79 + '\n' + page + '\n' + '-' * 79)
                else:
                    raise ISCError(
                        "Couldn't parse XML results from ISC:\n"
                        + '-' * 79 + '\n' + page + '\n' + '-' * 79)

            events = data.get_pyrocko_events()

        for ev in events:
            self.events[ev.name] = ev

        for ev in events:
            if time_range[0] <= ev.time and ev.time <= time_range[1]:
                yield ev.name

    def get_event(self, name):
        if name not in self.events:
            t = self._name_to_date(name)
            for name2 in self.iter_event_names(
                    time_range=(t-24*60*60, t+24*60*60)):

                if name2 == name:
                    break

        return self.events[name]

    def get_phase_markers(self, time_range, station_codes, phases):
        '''
        Download phase picks from ISC catalog and return them as a list
        of `pyrocko.gui.PhaseMarker` instances.

        :param time_range: Tuple with (tmin tmax)
        :param station_codes: List with ISC station codes
            (see http://www.isc.ac.uk/cgi-bin/stations?lista).
            If `station_codes` is 'global', query all ISC stations.
        :param phases: List of seismic phases. (e.g. ['P', 'PcP']
        '''

        p = []
        a = p.append

        a('out_format=QuakeML')
        a('request=STNARRIVALS')
        if station_codes == 'global':
            a('stnsearch=GLOBAL')
        else:
            a('stnsearch=STN')
            a('sta_list=%s' % ','.join(station_codes))

        a('phaselist=%s' % ','.join(phases))

        self.append_time_params(a, time_range)

        url = 'http://www.isc.ac.uk/cgi-bin/web-db-v4?' + '&'.join(p)

        logger.debug('Opening URL: %s' % url)
        page = urlopen(url)
        page = page.read().decode()

        if 'No stations were found.' in page:
            logger.info('No stations were found.')
            return []

        logger.debug('Received page (%i bytes)' % len(page))
        if -1 != page.find(
                'Sorry, but your request cannot be processed at the present '
                'time'):
            raise ISCBlocked(
                'Apparently, we have queried ISC too eagerly:\n'
                + '-' * 79 + '\n' + re.sub(r'<[^>]+>', ' ', page)
                + '\n' + '-' * 79)

        data = quakeml.QuakeML.load_xml(string=page)

        markers = data.get_pyrocko_phase_markers()
        markers = self.replace_isc_codes(markers)

        return markers

    def replace_isc_codes(self, markers):
        for m in markers:
            new_nslc_ids = []
            for (n, s, l_, c) in m.get_nslc_ids():
                l_ = l_.replace('--', '')
                c = c.replace('???', '*')
                new_nslc_ids.append((n, s, l_, c))
            m.nslc_ids = new_nslc_ids

        return markers

    def _name_to_date(self, name):
        ds = name[-23:]
        t = util.str_to_time(ds, format='%Y-%m-%d_%H-%M-%S.3FRAC')
        return t
