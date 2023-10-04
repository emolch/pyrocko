# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Client to get earthquake catalog information from
`GlobalCMT <http://www.globalcmt.org/>`_.
'''

import time
import calendar
import re
import logging

from pyrocko import model, util
from pyrocko.moment_tensor import MomentTensor
from pyrocko.util import Request, urlopen
from .base_catalog import EarthquakeCatalog


import numpy as num


logger = logging.getLogger('pyrocko.client.globalcmt')

km = 1000.


class Anon(object):
    pass


class GlobalCMT(EarthquakeCatalog):
    '''
    Client to get earthquake catalog information from
    `GlobalCMT <http://www.globalcmt.org/>`_.
    '''

    def __init__(self):
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
            lonmax=180.,
            depthmin=0.,
            depthmax=1000*km):

        yearbeg, monbeg, daybeg = time.gmtime(time_range[0])[:3]
        yearend, monend, dayend = time.gmtime(time_range[1])[:3]

        url = 'http://www.globalcmt.org/cgi-bin/globalcmt-cgi-bin/CMT5/form?' \
            + '&'.join([
                'itype=ymd',
                'yr=%i' % yearbeg, 'mo=%i' % monbeg, 'day=%i' % daybeg,
                'otype=ymd',
                'oyr=%i' % yearend, 'omo=%i' % monend, 'oday=%i' % dayend,
                'jyr=1976', 'jday=1', 'ojyr=1976', 'ojday=1', 'nday=1',
                'lmw=%g' % magmin, 'umw=%g' % magmax,
                'lms=0', 'ums=10',
                'lmb=0', 'umb=10',
                'llat=%g' % latmin, 'ulat=%g' % latmax,
                'llon=%g' % lonmin, 'ulon=%g' % lonmax,
                'lhd=%g' % (depthmin/km), 'uhd=%g' % (depthmax/km),
                'lts=-9999', 'uts=9999',
                'lpe1=0', 'upe1=90',
                'lpe2=0', 'upe2=90',
                'list=5'])

        while True:
            logger.debug('Opening URL: %s' % url)
            req = Request(url)
            page = urlopen(req).read()
            logger.debug('Received page (%i bytes)' % len(page))

            events, more = self._parse_events_page(page)

            for ev in events:
                self.events[ev.name] = ev

            for ev in events:
                if time_range[0] <= ev.time and ev.time <= time_range[1]:
                    yield ev.name

            if more:
                url = more.decode('ascii')
            else:
                break

    def get_event(self, name):
        if name not in self.events:
            t = self._name_to_date(name)
            for name2 in self.iter_event_names(
                    time_range=(t-24*60*60, t+2*24*60*60)):

                if name2 == name:
                    break

        return self.events[name]

    def _parse_events_page(self, page):

        lines = page.splitlines()
        state = 0

        events = []

        def complete(data):
            try:
                t = util.to_time_float(
                    calendar.timegm((
                        data.year, data.month, data.day,
                        data.hour, data.minute, data.seconds)))

                m = num.array(
                    [data.mrr, data.mrt, data.mrp,
                     data.mrt, data.mtt, data.mtp,
                     data.mrp, data.mtp, data.mpp],
                    dtype=float).reshape(3, 3)

                m *= 10.0**(data.exponent-7)
                mt = MomentTensor(m_up_south_east=m)
                ev = model.Event(
                    lat=data.lat,
                    lon=data.lon,
                    time=t,
                    name=data.eventname,
                    depth=data.depth_km*1000.,
                    magnitude=float(mt.moment_magnitude()),
                    duration=data.half_duration * 2.,
                    region=data.region.rstrip(),
                    catalog=data.catalog)

                ev.moment_tensor = mt
                events.append(ev)

            except AttributeError:
                pass

        catalog = 'gCMT'

        data = None
        more = None
        for line in lines:
            if state == 0:

                m = re.search(br'<a href="([^"]+)">More solutions', line)
                if m:
                    more = m.group(1)

                m = re.search(br'From Quick CMT catalog', line)
                if m:
                    catalog = 'gCMT-Q'

                m = re.search(br'Event name:\s+(\S+)', line)
                if m:
                    if data:
                        complete(data)

                    data = Anon()
                    data.eventname = str(m.group(1).decode('ascii'))
                    data.catalog = catalog

                if data:
                    m = re.search(br'Region name:\s+([^<]+)', line)
                    if m:
                        data.region = str(m.group(1).decode('ascii'))

                    m = re.search(
                        br'Date \(y/m/d\): (\d\d\d\d)/(\d+)/(\d+)', line)

                    if m:
                        data.year, data.month, data.day = (
                            int(m.group(1)), int(m.group(2)), int(m.group(3)))

                    m = re.search(br'Timing and location information', line)
                    if m:
                        state = 1

            if state == 1:
                toks = line.split()
                if toks and toks[0] == b'CMT':
                    data.hour, data.minute = [int(x) for x in toks[1:3]]
                    data.seconds, data.lat, data.lon, data.depth_km = [
                        float(x) for x in toks[3:]]

                m = re.search(br'Assumed half duration:\s+(\S+)', line)
                if m:
                    data.half_duration = float(m.group(1))

                m = re.search(br'Mechanism information', line)
                if m:
                    state = 2

            if state == 2:
                m = re.search(br'Exponent for moment tensor:\s+(\d+)', line)
                if m:
                    data.exponent = int(m.group(1))

                toks = line.split()
                if toks and toks[0] == b'CMT':
                    data.mrr, data.mtt, data.mpp, \
                        data.mrt, data.mrp, data.mtp = [
                            float(x) for x in toks[1:]]

                m = re.search(br'^Eigenvector:', line)
                if m:
                    state = 0

        if data is not None:
            complete(data)

        return events, more

    def _name_to_date(self, name):

        if len(name) == 7:
            y, m, d = time.strptime(name[:6], '%m%d%y')[:3]
            if y > 2005:
                y -= 100

        else:
            y, m, d = time.strptime(name[:8], '%Y%m%d')[:3]

        t = util.to_time_float(
            calendar.timegm((y, m, d, 0, 0, 0)))
        return t
