# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Access to `regional earthquake catalog of Saxony, Germany from the University
of Leipzig <http://home.uni-leipzig.de/collm/auswertung_temp.html>`_.
'''

from pyrocko import util, model
from .base_catalog import EarthquakeCatalog
from pyrocko.util import urlopen

import logging

logger = logging.getLogger('pyrocko.client.saxony')

km = 1000.


class Saxony(EarthquakeCatalog):
    '''
    Access to `regional earthquake catalog of Saxony, Germany from the
    University of Leipzig
    <http://home.uni-leipzig.de/collm/auswertung_temp.html>`_.
    '''

    def __init__(self):
        self._events = None

    def retrieve(self):
        url = 'http://home.uni-leipzig.de/collm/auswertung_temp.html'

        f = urlopen(url)
        text = f.read().decode('ascii')
        sec = 0
        events = {}
        for line in text.splitlines():
            line = line.strip()
            if line == '<PRE>':
                sec += 1
                continue

            if sec == 1 and not line:
                sec += 1
                continue

            if sec == 1:
                t = line.split(' ', 1)
                name = t[0]
                sdate = t[1][0:11]
                stime = t[1][12:22]
                sloc = t[1][23:36]
                sdepth = t[1][37:42]
                smag = t[1][51:55]
                region = t[1][60:]

                sday, smon, syear = sdate.split('-')
                smon = {
                    'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04',
                    'Mai': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08',
                    'Sep': '09', 'Okt': '10', 'Nov': '11', 'Dez': '12'}[smon]

                time = util.str_to_time(
                    '%s-%s-%s %s' % (syear, smon, sday, stime))

                slat, slon = sloc.split(';')

                ev = model.event.Event(
                    time=time,
                    lat=float(slat),
                    lon=float(slon),
                    depth=float(sdepth) * 1000.,
                    magnitude=float(smag),
                    magnitude_type='Ml',
                    name=name,
                    region=region,
                    catalog='Saxony')

                events[name] = ev

        self._events = events

    def iter_event_names(self, time_range=None, **kwargs):
        if self._events is None:
            self.retrieve()

        for name in sorted(self._events.keys()):
            if time_range is not None:
                ev = self._events[name]
                if time_range[0] <= ev.time and ev.time <= time_range[1]:
                    yield name
            else:
                yield name

    def get_event(self, name):
        if self._events is None:
            self.retrieve()

        return self._events[name]
