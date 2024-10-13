# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel memory cacheing.
'''

import logging
import threading

from pyrocko.guts import Object, Int

logger = logging.getLogger('psq.cache')


class ContentCacheStats(Object):
    '''
    Information about cache state.
    '''
    nentries = Int.T(
        help='Number of items in the cache.')
    naccessors = Int.T(
        help='Number of accessors currently holding references to cache '
             'items.')


class ContentCache(object):

    '''
    Simple memory cache for file contents.

    Squirrel manages data in small entities: nuts. Only the meta-data for each
    nut is stored in the database, content data has to be read from file. This
    cache helps to speed up data access for typical seismological access
    patterns.

    Content data for stations, channels and instrument responses is small in
    size but slow to parse so it makes sense to cache these indefinitely once
    read. Also, it is usually inefficient to read a single station from a
    station file, so it is better to cache the contents of the complete file
    even if only one station is requested (it is likely that other stations
    from that file will be used anyway).

    Content data for waveforms is large in size and we usually want to free the
    memory allocated for them after processing. Typical processing schemes
    require batches of waveforms to be available together (e.g.
    cross-correlations between pairs of stations) and there may be overlap
    between successive batches (e.g. sliding window processing schemes).

    This cache implementation uses named accessors and batch window counting
    for flexible content caching. Loaded contents are held in memory as long as
    an accessor is holding a reference to it. For each accessor a batch counter
    is maintained, which starts at 0 and is incremented using calls to
    :py:meth:`advance_accessor`. Content accesses are tracked with calls to
    :py:meth:`get`, which sets a "last access" attribute on the cached item to
    the current value of the batch counter (each accessor has its own last
    access attribute on the items it uses). References to items which have
    not been accessed during the latest batch by the accessor in question are
    released during :py:meth:`advance_accessor`. :py:meth:`put` inserts new
    items into the cache. :py:meth:`has` checks if there already is content
    cached for a given item. To remove all references held by a given accessor,
    :py:meth:`clear_accessor` can be called.

    **Example usage**

    For meta-data content to be cached indefinitely, no calls to
    :py:meth:`advance_accessor` or :py:meth:`clear_accessor` should be made.
    For waveform content one would call :py:meth:`advance_accessor` after each
    move of a sliding window or :py:meth:`clear_accessor` after each processed
    event. For a process requiring data from two independent positions of
    extraction, e.g. for cross-correlations between all possible pairs of a set
    of events, two separate accessor names could be used.
    '''

    def __init__(self):
        self._entries = {}
        self._accessor_ticks = {}
        self._lock = threading.RLock()

    def _prune_outdated(self, path, segment, nut_mtime):
        with self._lock:
            try:
                cache_mtime = self._entries[path, segment][0]
            except KeyError:
                return

            if cache_mtime != nut_mtime:
                logger.debug('Forgetting (outdated): %s %s' % (path, segment))
                self._entries.pop((path, segment), None)

    def put(self, nut):
        '''
        Insert a new/updated item into cache.

        :param nut:
            Content item with attached data object.
        :type nut:
            :py:class:`~pyrocko.squirrel.model.Nut`
        '''
        with self._lock:
            path, segment, element, mtime = nut.key
            self._prune_outdated(path, segment, nut.file_mtime)
            if (path, segment) not in self._entries:
                self._entries[path, segment] = nut.file_mtime, {}, {}

            self._entries[path, segment][1][element] = nut

    def get(self, nut, accessor='default', model='squirrel'):
        '''
        Get a content item and track its access.

        :param nut:
            Content item.
        :type nut:
            :py:class:`~pyrocko.squirrel.model.Nut`

        :param accessor:
            Name of accessing consumer. Giving a new name initializes a new
            accessor.
        :type accessor:
            str

        :returns:
            Content data object
        '''
        with self._lock:
            path, segment, element, mtime = nut.key
            entry = self._entries[path, segment]

            if accessor not in self._accessor_ticks:
                self._accessor_ticks[accessor] = 0

            entry[2][accessor] = self._accessor_ticks[accessor]
            el = entry[1][element]

            if model == 'squirrel':
                return el.content
            elif model.endswith('+'):
                return el.content, el.raw_content[model[:-1]]
            else:
                return el.raw_content[model]

    def has(self, nut):
        '''
        Check if item's content is currently in cache.

        :param nut:
            Content item.
        :type nut:
            :py:class:`~pyrocko.squirrel.model.Nut`

        :returns:
            :py:class:`bool`

        '''
        path, segment, element, nut_mtime = nut.key

        with self._lock:
            try:
                entry = self._entries[path, segment]
                cache_mtime = entry[0]
                entry[1][element]
            except KeyError:
                return False

            return cache_mtime == nut_mtime

    def advance_accessor(self, accessor='default'):
        '''
        Increment batch counter of an accessor.

        :param accessor:
            Name of accessing consumer. Giving a new name initializes a new
            accessor.
        :type accessor:
            str
        '''

        with self._lock:
            if accessor not in self._accessor_ticks:
                self._accessor_ticks[accessor] = 0

            ta = self._accessor_ticks[accessor]

            delete = []
            for path_segment, entry in self._entries.items():
                t = entry[2].get(accessor, ta)
                if t < ta:
                    entry[2].pop(accessor, None)
                    if not entry[2]:
                        delete.append(path_segment)

            for path_segment in delete:
                logger.debug(
                    'Forgetting (clear): %s %s' % path_segment)
                self._entries.pop(path_segment, None)

            self._accessor_ticks[accessor] += 1

    def clear_accessor(self, accessor='default'):
        '''
        Clear all references held by an accessor.

        :param accessor:
            Name of accessing consumer.
        :type accessor:
            str
        '''
        with self._lock:
            delete = []
            for path_segment, entry in self._entries.items():
                entry[2].pop(accessor, None)
                if not entry[2]:
                    delete.append(path_segment)

            for path_segment in delete:
                logger.debug('Forgetting (clear): %s %s' % path_segment)
                self._entries.pop(path_segment, None)

            self._accessor_ticks.pop(accessor, None)

    def clear(self):
        '''
        Empty the cache.
        '''
        with self._lock:
            for accessor in list(self._accessor_ticks.keys()):
                self.clear_accessor(accessor)

            self._entries = {}
            self._accessor_ticks = {}

    def get_stats(self):
        '''
        Get information about cache state.

        :returns: :py:class:`ContentCacheStats` object.
        '''
        with self._lock:
            return ContentCacheStats(
                nentries=len(self._entries),
                naccessors=len(self._accessor_ticks))
