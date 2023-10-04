# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Event data access interface (*deprecated*).
'''

from pyrocko import model, response

import logging
import copy
import pickle

logger = logging.getLogger('pyrocko.io.eventdata')


class NoRestitution(Exception):
    pass


class FileNotFound(Exception):

    def __init__(self, s):
        self.s = s

    def __str__(self):
        return 'File not found: %s' % self.s


class Problems(object):
    def __init__(self):
        self._problems = {}

    def add(self, kind, nslct):
        if kind not in self._problems:
            self._problems[kind] = set()
        problem = self._problems[kind]
        problem.add(nslct)

    def dump(self, fn):
        f = open(fn, 'wb')
        pickle.dump(self._problems, f)
        f.close()

    def load(self, fn):
        f = open(fn, 'rb')
        self._problems = pickle.load(f)
        f.close()

    def mapped(self, mapping=lambda nslct: nslct[:3]):
        p = {}
        for kind, problem in self._problems.items():
            nsl = set()
            for nslct in problem:
                nsl.add(mapping(nslct))
            p[kind] = nsl

        return p


class EventDataAccess(object):
    '''
    Abstract base class for event data access (see rdseed.py).
    '''

    def __init__(self, events=None, stations=None, datapile=None):

        self._pile = datapile
        self._events = events

        if stations is None:
            self._stations = None
        else:
            self._stations = {}
            for station in stations:
                self._stations[station.nsl()] = station

        self._problems = Problems()

    def get_pile(self):
        return self._pile

    def get_pyrocko_events(self):
        '''
        Extract :py:class:`~pyrocko.model.event.Event` instances from the
        volume.
        '''

        if not self._events:
            self._events = self._get_events_from_file()
        return self._events

    def get_pyrocko_station(self, tr, relative_event=None):
        '''
        Get station information for a given trace.

        :param tr: :py:class:`~pyrocko.trace.Trace` instance

        :returns: :py:class:`~pyrocko.model.station.Station` objects.
        '''

        self._update_stations()
        s = copy.deepcopy(self._stations[tr.nslc_id[:3]])
        if relative_event is not None:
            s.set_event_relative_data(relative_event)
        return s

    def get_pyrocko_channel(self, tr):
        '''
        Get channel information for a given trace.

        :param tr: :py:class:`~pyrocko.trace.Trace` instance

        :returns: :py:class:`~pyrocko.model.station.Channel` objects.
        '''
        sta = self.get_station(tr)
        return sta.get_channel(tr.channel)

    def get_pyrocko_stations(self):
        '''
        Exctract a list of :py:class:`~pyrocko.model.station.Station`
        instances.
        '''
        return list(self._get_stations().values())

    def _get_stations(self, relative_event=None):
        self._update_stations()
        stations = copy.deepcopy(self._stations)
        if relative_event is not None:
            for s in stations.values():
                s.set_event_relative_data(relative_event)

        return stations

    def _update_stations(self):
        if not self._stations:
            self._stations = {}
            for station in self._get_stations_from_file():
                self._stations[station.nsl()] = station
            self._insert_channel_descriptions(self._stations)

    def _insert_channel_descriptions(self, stations):
        pile = self.get_pile()
        nslc_ids = pile.gather_keys(
            lambda tr: (tr.network, tr.station, tr.location, tr.channel))

        for nslc in nslc_ids:
            if nslc[:3] not in stations:
                logger.warning(
                    'No station description for trace %s.%s.%s.%s' % nslc)
                continue

            sta = stations[nslc[:3]]
            try:
                sta.add_channel(self._get_channel_description_from_file(nslc))
            except FileNotFound:
                logger.warning(
                    'No channel description for trace %s.%s.%s.%s' % nslc)

    def _get_channel_description_from_file(self, nslc):
        return model.Channel(nslc[3], None, None, 1.)

    def iter_traces(self, group_selector=None, trace_selector=None):

        for traces in self.get_pile().chopper_grouped(
                gather=lambda tr: (tr.network, tr.station, tr.location),
                group_selector=group_selector,
                trace_selector=trace_selector):

            yield traces

    def problems(self):
        return self._problems

    def _redundant_channel_weeder(self, redundant_channel_priorities, nslcs):

        if redundant_channel_priorities is None:
            return []

        # n=network,s=station,l=location,c=channel
        # channels by station
        by_nsl = {}
        for nslc in nslcs:
            nsl = nslc[:3]
            if nsl not in by_nsl:
                by_nsl[nsl] = []

            by_nsl[nsl].append(nslc)

        # figure out what items to remove
        to_delete = []
        for ((h1, h2), (l1, l2)) in redundant_channel_priorities:
            for nsl, nslcs in by_nsl.items():
                channels = [nslc[3] for nslc in nslcs]
                if h1 in channels and \
                        h2 in channels and \
                        l1 in channels and \
                        l2 in channels:

                    to_delete.append(nslc[:3] + (l1,))
                    to_delete.append(nslc[:3] + (l2,))

        return to_delete

    def get_restitution(self, tr, allowed_methods):
        if 'integration' in allowed_methods:
            response.IntegrationResponse()
        else:
            raise Exception('only "integration" restitution method is allowed')
