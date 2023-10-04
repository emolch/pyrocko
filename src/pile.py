# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Waveform archive lookup, data loading and caching infrastructure.

.. note::

    This module has been superseded by :py:mod:`~pyrocko.squirrel` but will
    remain available for backwards compatibility.
'''

import os
import logging
import time
import copy
import re
import sys
import operator
import math
import hashlib
try:
    import cPickle as pickle
except ImportError:
    import pickle


from . import avl
from . import trace, io, util
from . import config
from .trace import degapper


is_windows = sys.platform.startswith('win')
show_progress_force_off = False
version_salt = 'v1-'


def ehash(s):
    return hashlib.sha1((version_salt + s).encode('utf8')).hexdigest()


def cmp(a, b):
    return int(a > b) - int(a < b)


def sl(s):
    return [str(x) for x in sorted(s)]


class Counter(dict):

    def __missing__(self, k):
        return 0

    def update(self, other):
        for k, v in other.items():
            self[k] += v

    def subtract(self, other):
        for k, v in other.items():
            self[k] -= v
            if self[k] <= 0:
                del self[k]

    def subtract1(self, k):
        self[k] -= 1
        if self[k] <= 0:
            del self[k]


def fix_unicode_copy(counter, func):
    counter_new = Counter()
    for k in counter:
        counter_new[func(k)] = counter[k]
    return counter_new


pjoin = os.path.join
logger = logging.getLogger('pyrocko.pile')


def avl_remove_exact(avltree, element):
    ilo, ihi = avltree.span(element)
    for i in range(ilo, ihi):
        if avltree[i] is element:
            avltree.remove_at(i)
            return i

    raise ValueError(
        'avl_remove_exact(avltree, element): element not in avltree')


def cmpfunc(key):
    if isinstance(key, str):
        # special cases; these run about 50% faster than the generic one on
        # Python 2.5
        if key == 'tmin':
            return lambda a, b: cmp(a.tmin, b.tmin)
        if key == 'tmax':
            return lambda a, b: cmp(a.tmax, b.tmax)

        key = operator.attrgetter(key)

    return lambda a, b: cmp(key(a), key(b))


g_dummys = {}


def get_dummy(key):
    if key not in g_dummys:
        class Dummy(object):
            def __init__(self, k):
                setattr(self, key, k)

        g_dummys[key] = Dummy

    return g_dummys[key]


class TooMany(Exception):
    def __init__(self, n):
        Exception.__init__(self)
        self.n = n


class Sorted(object):
    def __init__(self, values=[], key=None):
        self._set_key(key)
        self._avl = avl.new(values, self._cmp)

    def _set_key(self, key):
        self._key = key
        self._cmp = cmpfunc(key)
        if isinstance(key, str):
            self._dummy = get_dummy(key)

    def __getstate__(self):
        state = list(self._avl.iter()), self._key
        return state

    def __setstate__(self, state):
        it, key = state
        self._set_key(key)
        self._avl = avl.from_iter(iter(it), len(it))

    def insert(self, value):
        self._avl.insert(value)

    def remove(self, value):
        return avl_remove_exact(self._avl, value)

    def remove_at(self, i):
        return self._avl.remove_at(i)

    def insert_many(self, values):
        for value in values:
            self._avl.insert(value)

    def remove_many(self, values):
        for value in values:
            avl_remove_exact(self._avl, value)

    def __iter__(self):
        return iter(self._avl)

    def with_key_in(self, kmin, kmax):
        omin, omax = self._dummy(kmin), self._dummy(kmax)
        ilo, ihi = self._avl.span(omin, omax)
        return self._avl[ilo:ihi]

    def with_key_in_limited(self, kmin, kmax, nmax):
        omin, omax = self._dummy(kmin), self._dummy(kmax)
        ilo, ihi = self._avl.span(omin, omax)
        if ihi - ilo > nmax:
            raise TooMany(ihi - ilo)

        return self._avl[ilo:ihi]

    def index(self, value):
        ilo, ihi = self._avl.span(value)
        for i in range(ilo, ihi):
            if self._avl[i] is value:
                return i

        raise ValueError('element is not in avl tree')

    def min(self):
        return self._avl.min()

    def max(self):
        return self._avl.max()

    def __len__(self):
        return len(self._avl)

    def __getitem__(self, i):
        return self._avl[i]


class TracesFileCache(object):
    '''
    Manages trace metainformation cache.

    For each directory with files containing traces, one cache file is
    maintained to hold the trace metainformation of all files which are
    contained in the directory.
    '''

    caches = {}

    def __init__(self, cachedir):
        '''
        Create new cache.

        :param cachedir: directory to hold the cache files.
        '''

        self.cachedir = cachedir
        self.dircaches = {}
        self.modified = set()
        util.ensuredir(self.cachedir)

    def get(self, abspath):
        '''
        Try to get an item from the cache.

        :param abspath: absolute path of the object to retrieve

        :returns: a stored object is returned or None if nothing could be
            found.
        '''

        dircache = self._get_dircache_for(abspath)
        if abspath in dircache:
            return dircache[abspath]
        return None

    def put(self, abspath, tfile):
        '''
        Put an item into the cache.

        :param abspath: absolute path of the object to be stored
        :param tfile: object to be stored
        '''

        cachepath = self._dircachepath(abspath)
        # get lock on cachepath here
        dircache = self._get_dircache(cachepath)
        dircache[abspath] = tfile
        self.modified.add(cachepath)

    def dump_modified(self):
        '''
        Save any modifications to disk.
        '''

        for cachepath in self.modified:
            self._dump_dircache(self.dircaches[cachepath], cachepath)
            # unlock

        self.modified = set()

    def clean(self):
        '''
        Weed out missing files from the disk caches.
        '''

        self.dump_modified()

        for fn in os.listdir(self.cachedir):
            if len(fn) == 40:
                cache = self._load_dircache(pjoin(self.cachedir, fn))
                self._dump_dircache(cache, pjoin(self.cachedir, fn))

    def _get_dircache_for(self, abspath):
        return self._get_dircache(self._dircachepath(abspath))

    def _get_dircache(self, cachepath):
        if cachepath not in self.dircaches:
            if os.path.isfile(cachepath):
                self.dircaches[cachepath] = self._load_dircache(cachepath)
            else:
                self.dircaches[cachepath] = {}

        return self.dircaches[cachepath]

    def _dircachepath(self, abspath):
        cachefn = ehash(os.path.dirname(abspath))
        return pjoin(self.cachedir, cachefn)

    def _load_dircache(self, cachefilename):

        with open(cachefilename, 'rb') as f:
            cache = pickle.load(f)

        # weed out files which no longer exist
        for fn in list(cache.keys()):
            if not os.path.isfile(fn):
                del cache[fn]

        time_float = util.get_time_float()

        for v in cache.values():
            v.trees_from_content(v.traces)
            for tr in v.traces:
                tr.file = v
                # fix Py2 codes to not include unicode when the cache file
                # was created with Py3
                if not isinstance(tr.station, str):
                    tr.prune_from_reuse_cache()
                    tr.set_codes(
                        str(tr.network),
                        str(tr.station),
                        str(tr.location),
                        str(tr.channel))

                tr.tmin = time_float(tr.tmin)
                tr.tmax = time_float(tr.tmax)

            v.data_use_count = 0
            v.data_loaded = False
            v.fix_unicode_codes()

        return cache

    def _dump_dircache(self, cache, cachefilename):

        if not cache:
            if os.path.exists(cachefilename):
                os.remove(cachefilename)
            return

        # make a copy without the parents and the binsearch trees
        cache_copy = {}
        for fn in cache.keys():
            trf = copy.copy(cache[fn])
            trf.parent = None
            trf.by_tmin = None
            trf.by_tmax = None
            trf.by_tlen = None
            trf.by_mtime = None
            trf.data_use_count = 0
            trf.data_loaded = False
            traces = []
            for tr in trf.traces:
                tr = tr.copy(data=False)
                tr.ydata = None
                tr.meta = None
                tr.file = trf
                traces.append(tr)

            trf.traces = traces

            cache_copy[fn] = trf

        tmpfn = cachefilename+'.%i.tmp' % os.getpid()
        with open(tmpfn, 'wb') as f:
            pickle.dump(cache_copy, f, protocol=2)

        if is_windows and os.path.exists(cachefilename):
            # windows doesn't allow to rename over existing file
            os.unlink(cachefilename)

        os.rename(tmpfn, cachefilename)


def get_cache(cachedir):
    '''
    Get global TracesFileCache object for given directory.
    '''
    if cachedir not in TracesFileCache.caches:
        TracesFileCache.caches[cachedir] = TracesFileCache(cachedir)

    return TracesFileCache.caches[cachedir]


def loader(
        filenames, fileformat, cache, filename_attributes,
        show_progress=True, update_progress=None):

    if show_progress_force_off:
        show_progress = False

    class Progress(object):
        def __init__(self, label, n):
            self._label = label
            self._n = n
            self._bar = None
            if show_progress:
                self._bar = util.progressbar(label, self._n)

            if update_progress:
                update_progress(label, 0, self._n)

        def update(self, i):
            if self._bar:
                if i < self._n-1:
                    self._bar.update(i)
                else:
                    self._bar.finish()
                    self._bar = None

            abort = False
            if update_progress:
                abort = update_progress(self._label, i, self._n)

            return abort

        def finish(self):
            if self._bar:
                self._bar.finish()
                self._bar = None

    if not filenames:
        logger.warning('No files to load from')
        return

    regex = None
    if filename_attributes:
        regex = re.compile(filename_attributes)

    try:
        progress = Progress('Looking at files', len(filenames))

        failures = []
        to_load = []
        for i, filename in enumerate(filenames):
            try:
                abspath = os.path.abspath(filename)

                substitutions = None
                if regex:
                    m = regex.search(filename)
                    if not m:
                        raise FilenameAttributeError(
                            "Cannot get attributes with pattern '%s' "
                            "from path '%s'" % (filename_attributes, filename))

                    substitutions = {}
                    for k in m.groupdict():
                        if k in ('network', 'station', 'location', 'channel'):
                            substitutions[k] = m.groupdict()[k]

                mtime = os.stat(filename)[8]
                tfile = None
                if cache:
                    tfile = cache.get(abspath)

                mustload = (
                    not tfile or
                    (tfile.format != fileformat and fileformat != 'detect') or
                    tfile.mtime != mtime or
                    substitutions is not None)

                to_load.append(
                    (mustload, mtime, abspath, substitutions, tfile))

            except (OSError, FilenameAttributeError) as xerror:
                failures.append(abspath)
                logger.warning(xerror)

            abort = progress.update(i+1)
            if abort:
                progress.update(len(filenames))
                return

        progress.update(len(filenames))

        to_load.sort(key=lambda x: x[2])

        nload = len([1 for x in to_load if x[0]])
        iload = 0

        count_all = False
        if nload < 0.01*len(to_load):
            nload = len(to_load)
            count_all = True

        if to_load:
            progress = Progress('Scanning files', nload)

            for (mustload, mtime, abspath, substitutions, tfile) in to_load:
                try:
                    if mustload:
                        tfile = TracesFile(
                            None, abspath, fileformat,
                            substitutions=substitutions, mtime=mtime)

                        if cache and not substitutions:
                            cache.put(abspath, tfile)

                        if not count_all:
                            iload += 1

                    if count_all:
                        iload += 1

                except (io.FileLoadError, OSError) as xerror:
                    failures.append(abspath)
                    logger.warning(xerror)
                else:
                    yield tfile

                abort = progress.update(iload+1)
                if abort:
                    break

            progress.update(nload)

        if failures:
            logger.warning(
                'The following file%s caused problems and will be ignored:\n' %
                util.plural_s(len(failures)) + '\n'.join(failures))

        if cache:
            cache.dump_modified()
    finally:
        progress.finish()


def tlen(x):
    return x.tmax-x.tmin


class TracesGroup(object):

    '''
    Trace container base class.

    Base class for Pile, SubPile, and TracesFile, i.e. anything containing
    a collection of several traces. A TracesGroup object maintains lookup sets
    of some of the traces meta-information, as well as a combined time-range
    of its contents.
    '''

    def __init__(self, parent):
        self.parent = parent
        self.empty()
        self.nupdates = 0
        self.abspath = None

    def set_parent(self, parent):
        self.parent = parent

    def get_parent(self):
        return self.parent

    def empty(self):
        self.networks, self.stations, self.locations, self.channels, \
            self.nslc_ids, self.deltats = [Counter() for x in range(6)]
        self.by_tmin = Sorted([], 'tmin')
        self.by_tmax = Sorted([], 'tmax')
        self.by_tlen = Sorted([], tlen)
        self.by_mtime = Sorted([], 'mtime')
        self.tmin, self.tmax = None, None
        self.deltatmin, self.deltatmax = None, None

    def trees_from_content(self, content):
        self.by_tmin = Sorted(content, 'tmin')
        self.by_tmax = Sorted(content, 'tmax')
        self.by_tlen = Sorted(content, tlen)
        self.by_mtime = Sorted(content, 'mtime')
        self.adjust_minmax()

    def fix_unicode_codes(self):
        for net in self.networks:
            if isinstance(net, str):
                return

        self.networks = fix_unicode_copy(self.networks, str)
        self.stations = fix_unicode_copy(self.stations, str)
        self.locations = fix_unicode_copy(self.locations, str)
        self.channels = fix_unicode_copy(self.channels, str)
        self.nslc_ids = fix_unicode_copy(
            self.nslc_ids, lambda k: tuple(str(x) for x in k))

    def add(self, content):
        '''
        Add content to traces group and update indices.

        Accepts :py:class:`pyrocko.trace.Trace` objects and
        :py:class:`pyrocko.pile.TracesGroup` objects.
        '''

        if isinstance(content, (trace.Trace, TracesGroup)):
            content = [content]

        for c in content:

            if isinstance(c, TracesGroup):
                self.networks.update(c.networks)
                self.stations.update(c.stations)
                self.locations.update(c.locations)
                self.channels.update(c.channels)
                self.nslc_ids.update(c.nslc_ids)
                self.deltats.update(c.deltats)

                self.by_tmin.insert_many(c.by_tmin)
                self.by_tmax.insert_many(c.by_tmax)
                self.by_tlen.insert_many(c.by_tlen)
                self.by_mtime.insert_many(c.by_mtime)

            elif isinstance(c, trace.Trace):
                self.networks[c.network] += 1
                self.stations[c.station] += 1
                self.locations[c.location] += 1
                self.channels[c.channel] += 1
                self.nslc_ids[c.nslc_id] += 1
                self.deltats[c.deltat] += 1

                self.by_tmin.insert(c)
                self.by_tmax.insert(c)
                self.by_tlen.insert(c)
                self.by_mtime.insert(c)

        self.adjust_minmax()

        self.nupdates += 1
        self.notify_listeners('add', content)

        if self.parent is not None:
            self.parent.add(content)

    def remove(self, content):
        '''
        Remove content to traces group and update indices.
        '''
        if isinstance(content, (trace.Trace, TracesGroup)):
            content = [content]

        for c in content:

            if isinstance(c, TracesGroup):
                self.networks.subtract(c.networks)
                self.stations.subtract(c.stations)
                self.locations.subtract(c.locations)
                self.channels.subtract(c.channels)
                self.nslc_ids.subtract(c.nslc_ids)
                self.deltats.subtract(c.deltats)

                self.by_tmin.remove_many(c.by_tmin)
                self.by_tmax.remove_many(c.by_tmax)
                self.by_tlen.remove_many(c.by_tlen)
                self.by_mtime.remove_many(c.by_mtime)

            elif isinstance(c, trace.Trace):
                self.networks.subtract1(c.network)
                self.stations.subtract1(c.station)
                self.locations.subtract1(c.location)
                self.channels.subtract1(c.channel)
                self.nslc_ids.subtract1(c.nslc_id)
                self.deltats.subtract1(c.deltat)

                self.by_tmin.remove(c)
                self.by_tmax.remove(c)
                self.by_tlen.remove(c)
                self.by_mtime.remove(c)

        self.adjust_minmax()

        self.nupdates += 1
        self.notify_listeners('remove', content)

        if self.parent is not None:
            self.parent.remove(content)

    def relevant(self, tmin, tmax, group_selector=None, trace_selector=None):
        '''
        Return list of :py:class:`pyrocko.trace.Trace` objects where given
        arguments ``tmin`` and ``tmax`` match.

        :param tmin: start time
        :param tmax: end time
        :param group_selector: lambda expression taking group dict of regex
            match object as a single argument and which returns true or false
            to keep or reject a file (default: ``None``)
        :param trace_selector: lambda expression taking group dict of regex
            match object as a single argument and which returns true or false
            to keep or reject a file (default: ``None``)
        '''

        if not self.by_tmin or not self.is_relevant(
                tmin, tmax, group_selector):

            return []

        return [tr for tr in self.by_tmin.with_key_in(tmin-self.tlenmax, tmax)
                if tr.is_relevant(tmin, tmax, trace_selector)]

    def adjust_minmax(self):
        if self.by_tmin:
            self.tmin = self.by_tmin.min().tmin
            self.tmax = self.by_tmax.max().tmax
            t = self.by_tlen.max()
            self.tlenmax = t.tmax - t.tmin
            self.mtime = self.by_mtime.max().mtime
            deltats = list(self.deltats.keys())
            self.deltatmin = min(deltats)
            self.deltatmax = max(deltats)
        else:
            self.tmin = None
            self.tmax = None
            self.tlenmax = None
            self.mtime = None
            self.deltatmin = None
            self.deltatmax = None

    def notify_listeners(self, what, content):
        pass

    def get_update_count(self):
        return self.nupdates

    def overlaps(self, tmin, tmax):
        return self.tmin is not None \
            and tmax >= self.tmin and self.tmax >= tmin

    def is_relevant(self, tmin, tmax, group_selector=None):
        if self.tmin is None or self.tmax is None:
            return False
        return tmax >= self.tmin and self.tmax >= tmin and (
            group_selector is None or group_selector(self))


class MemTracesFile(TracesGroup):

    '''
    This is needed to make traces without an actual disc file to be inserted
    into a Pile.
    '''

    def __init__(self, parent, traces):
        TracesGroup.__init__(self, parent)
        self.add(traces)
        self.mtime = time.time()

    def add(self, traces):
        if isinstance(traces, trace.Trace):
            traces = [traces]

        for tr in traces:
            tr.file = self

        TracesGroup.add(self, traces)

    def load_headers(self, mtime=None):
        pass

    def load_data(self):
        pass

    def use_data(self):
        pass

    def drop_data(self):
        pass

    def reload_if_modified(self):
        return False

    def iter_traces(self):
        for tr in self.by_tmin:
            yield tr

    def get_traces(self):
        return list(self.by_tmin)

    def gather_keys(self, gather, selector=None):
        keys = set()
        for tr in self.by_tmin:
            if selector is None or selector(tr):
                keys.add(gather(tr))

        return keys

    def __str__(self):

        s = 'MemTracesFile\n'
        s += 'file mtime: %s\n' % util.time_to_str(self.mtime)
        s += 'number of traces: %i\n' % len(self.by_tmin)
        s += 'timerange: %s - %s\n' % (
            util.time_to_str(self.tmin), util.time_to_str(self.tmax))
        s += 'networks: %s\n' % ', '.join(sl(self.networks.keys()))
        s += 'stations: %s\n' % ', '.join(sl(self.stations.keys()))
        s += 'locations: %s\n' % ', '.join(sl(self.locations.keys()))
        s += 'channels: %s\n' % ', '.join(sl(self.channels.keys()))
        s += 'deltats: %s\n' % ', '.join(sl(self.deltats.keys()))
        return s


class TracesFile(TracesGroup):
    def __init__(
            self, parent, abspath, format,
            substitutions=None, mtime=None):

        TracesGroup.__init__(self, parent)
        self.abspath = abspath
        self.format = format
        self.traces = []
        self.data_loaded = False
        self.data_use_count = 0
        self.substitutions = substitutions
        self.load_headers(mtime=mtime)
        self.mtime = mtime

    def load_headers(self, mtime=None):
        logger.debug('loading headers from file: %s' % self.abspath)
        if mtime is None:
            self.mtime = os.stat(self.abspath)[8]

        def kgen(tr):
            return (tr.mtime, tr.tmin, tr.tmax) + tr.nslc_id

        self.remove(self.traces)
        ks = set()
        for tr in io.load(self.abspath,
                          format=self.format,
                          getdata=False,
                          substitutions=self.substitutions):

            k = kgen(tr)
            if k not in ks:
                ks.add(k)
                self.traces.append(tr)
                tr.file = self

        self.add(self.traces)

        self.data_loaded = False
        self.data_use_count = 0

    def load_data(self, force=False):
        file_changed = False
        if not self.data_loaded or force:
            logger.debug('loading data from file: %s' % self.abspath)

            def kgen(tr):
                return (tr.mtime, tr.tmin, tr.tmax) + tr.nslc_id

            traces_ = io.load(self.abspath, format=self.format, getdata=True,
                              substitutions=self.substitutions)

            # prevent adding duplicate snippets from corrupt mseed files
            k_loaded = set()
            traces = []
            for tr in traces_:
                k = kgen(tr)
                if k not in k_loaded:
                    k_loaded.add(k)
                    traces.append(tr)

            k_current_d = dict((kgen(tr), tr) for tr in self.traces)
            k_current = set(k_current_d)
            k_new = k_loaded - k_current
            k_delete = k_current - k_loaded
            k_unchanged = k_current & k_loaded

            for tr in self.traces[:]:
                if kgen(tr) in k_delete:
                    self.remove(tr)
                    self.traces.remove(tr)
                    tr.file = None
                    file_changed = True

            for tr in traces:
                if kgen(tr) in k_new:
                    tr.file = self
                    self.traces.append(tr)
                    self.add(tr)
                    file_changed = True

            for tr in traces:
                if kgen(tr) in k_unchanged:
                    ctr = k_current_d[kgen(tr)]
                    ctr.ydata = tr.ydata

            self.data_loaded = True

        if file_changed:
            logger.debug('reloaded (file may have changed): %s' % self.abspath)

        return file_changed

    def use_data(self):
        if not self.data_loaded:
            raise Exception('Data not loaded')
        self.data_use_count += 1

    def drop_data(self):
        if self.data_loaded:
            if self.data_use_count == 1:
                logger.debug('forgetting data of file: %s' % self.abspath)
                for tr in self.traces:
                    tr.drop_data()

                self.data_loaded = False

            self.data_use_count -= 1
        else:
            self.data_use_count = 0

    def reload_if_modified(self):
        mtime = os.stat(self.abspath)[8]
        if mtime != self.mtime:
            logger.debug(
                'mtime=%i, reloading file: %s' % (mtime, self.abspath))

            self.mtime = mtime
            if self.data_loaded:
                self.load_data(force=True)
            else:
                self.load_headers()

            return True

        return False

    def iter_traces(self):
        for tr in self.traces:
            yield tr

    def gather_keys(self, gather, selector=None):
        keys = set()
        for tr in self.by_tmin:
            if selector is None or selector(tr):
                keys.add(gather(tr))

        return keys

    def __str__(self):
        s = 'TracesFile\n'
        s += 'abspath: %s\n' % self.abspath
        s += 'file mtime: %s\n' % util.time_to_str(self.mtime)
        s += 'number of traces: %i\n' % len(self.traces)
        s += 'timerange: %s - %s\n' % (
            util.time_to_str(self.tmin), util.time_to_str(self.tmax))
        s += 'networks: %s\n' % ', '.join(sl(self.networks.keys()))
        s += 'stations: %s\n' % ', '.join(sl(self.stations.keys()))
        s += 'locations: %s\n' % ', '.join(sl(self.locations.keys()))
        s += 'channels: %s\n' % ', '.join(sl(self.channels.keys()))
        s += 'deltats: %s\n' % ', '.join(sl(self.deltats.keys()))
        return s


class FilenameAttributeError(Exception):
    pass


class SubPile(TracesGroup):
    def __init__(self, parent):
        TracesGroup.__init__(self, parent)
        self.files = []
        self.empty()

    def add_file(self, file):
        self.files.append(file)
        file.set_parent(self)
        self.add(file)

    def remove_file(self, file):
        self.files.remove(file)
        file.set_parent(None)
        self.remove(file)

    def remove_files(self, files):
        for file in files:
            self.files.remove(file)
            file.set_parent(None)
        self.remove(files)

    def gather_keys(self, gather, selector=None):
        keys = set()
        for file in self.files:
            keys |= file.gather_keys(gather, selector)

        return keys

    def iter_traces(
            self,
            load_data=False,
            return_abspath=False,
            group_selector=None,
            trace_selector=None):

        for file in self.files:

            if group_selector and not group_selector(file):
                continue

            must_drop = False
            if load_data:
                file.load_data()
                file.use_data()
                must_drop = True

            for tr in file.iter_traces():
                if trace_selector and not trace_selector(tr):
                    continue

                if return_abspath:
                    yield file.abspath, tr
                else:
                    yield tr

            if must_drop:
                file.drop_data()

    def iter_files(self):
        for file in self.files:
            yield file

    def reload_modified(self):
        modified = False
        for file in self.files:
            modified |= file.reload_if_modified()

        return modified

    def __str__(self):
        s = 'SubPile\n'
        s += 'number of files: %i\n' % len(self.files)
        s += 'timerange: %s - %s\n' % (
            util.time_to_str(self.tmin), util.time_to_str(self.tmax))
        s += 'networks: %s\n' % ', '.join(sl(self.networks.keys()))
        s += 'stations: %s\n' % ', '.join(sl(self.stations.keys()))
        s += 'locations: %s\n' % ', '.join(sl(self.locations.keys()))
        s += 'channels: %s\n' % ', '.join(sl(self.channels.keys()))
        s += 'deltats: %s\n' % ', '.join(sl(self.deltats.keys()))
        return s


class Batch(object):
    '''
    Batch of waveforms from window wise data extraction.

    Encapsulates state and results yielded for each window in window wise
    waveform extraction with the :py:meth:`Pile.chopper` method (when the
    `style='batch'` keyword argument set).

    *Attributes:*

    .. py:attribute:: tmin

        Start of this time window.

    .. py:attribute:: tmax

        End of this time window.

    .. py:attribute:: i

        Index of this time window in sequence.

    .. py:attribute:: n

        Total number of time windows in sequence.

    .. py:attribute:: traces

        Extracted waveforms for this time window.
    '''

    def __init__(self, tmin, tmax, i, n, traces):
        self.tmin = tmin
        self.tmax = tmax
        self.i = i
        self.n = n
        self.traces = traces


class Pile(TracesGroup):
    '''
    Waveform archive lookup, data loading and caching infrastructure.
    '''

    def __init__(self):
        TracesGroup.__init__(self, None)
        self.subpiles = {}
        self.open_files = {}
        self.listeners = []
        self.abspaths = set()

    def add_listener(self, obj):
        self.listeners.append(util.smart_weakref(obj))

    def notify_listeners(self, what, content):
        for ref in self.listeners:
            obj = ref()
            if obj:
                obj(what, content)

    def load_files(
            self, filenames,
            filename_attributes=None,
            fileformat='mseed',
            cache=None,
            show_progress=True,
            update_progress=None):

        load = loader(
            filenames, fileformat, cache, filename_attributes,
            show_progress=show_progress,
            update_progress=update_progress)

        self.add_files(load)

    def add_files(self, files):
        for file in files:
            self.add_file(file)

    def add_file(self, file):
        if file.abspath is not None and file.abspath in self.abspaths:
            logger.warning('File already in pile: %s' % file.abspath)
            return

        if file.deltatmin is None:
            logger.warning('Sampling rate of all traces are zero in file: %s' %
                           file.abspath)
            return

        subpile = self.dispatch(file)
        subpile.add_file(file)
        if file.abspath is not None:
            self.abspaths.add(file.abspath)

    def remove_file(self, file):
        subpile = file.get_parent()
        if subpile is not None:
            subpile.remove_file(file)
        if file.abspath is not None:
            self.abspaths.remove(file.abspath)

    def remove_files(self, files):
        subpile_files = {}
        for file in files:
            subpile = file.get_parent()
            if subpile not in subpile_files:
                subpile_files[subpile] = []

            subpile_files[subpile].append(file)

        for subpile, files in subpile_files.items():
            subpile.remove_files(files)
            for file in files:
                if file.abspath is not None:
                    self.abspaths.remove(file.abspath)

    def dispatch_key(self, file):
        dt = int(math.floor(math.log(file.deltatmin)))
        return dt

    def dispatch(self, file):
        k = self.dispatch_key(file)
        if k not in self.subpiles:
            self.subpiles[k] = SubPile(self)

        return self.subpiles[k]

    def get_deltats(self):
        return list(self.deltats.keys())

    def chop(
            self, tmin, tmax,
            group_selector=None,
            trace_selector=None,
            snap=(round, round),
            include_last=False,
            load_data=True):

        chopped = []
        used_files = set()

        traces = self.relevant(tmin, tmax, group_selector, trace_selector)
        if load_data:
            files_changed = False
            for tr in traces:
                if tr.file and tr.file not in used_files:
                    if tr.file.load_data():
                        files_changed = True

                    if tr.file is not None:
                        used_files.add(tr.file)

            if files_changed:
                traces = self.relevant(
                    tmin, tmax, group_selector, trace_selector)

        for tr in traces:
            if not load_data and tr.ydata is not None:
                tr = tr.copy(data=False)
                tr.ydata = None

            try:
                chopped.append(tr.chop(
                    tmin, tmax,
                    inplace=False,
                    snap=snap,
                    include_last=include_last))

            except trace.NoData:
                pass

        return chopped, used_files

    def _process_chopped(
            self, chopped, degap, maxgap, maxlap, want_incomplete, wmax, wmin,
            tpad):

        chopped.sort(key=lambda a: a.full_id)
        if degap:
            chopped = degapper(chopped, maxgap=maxgap, maxlap=maxlap)

        if not want_incomplete:
            chopped_weeded = []
            for tr in chopped:
                emin = tr.tmin - (wmin-tpad)
                emax = tr.tmax + tr.deltat - (wmax+tpad)
                if (abs(emin) <= 0.5*tr.deltat and abs(emax) <= 0.5*tr.deltat):
                    chopped_weeded.append(tr)

                elif degap:
                    if (0. < emin <= 5. * tr.deltat and
                            -5. * tr.deltat <= emax < 0.):

                        tr.extend(
                            wmin-tpad,
                            wmax+tpad-tr.deltat,
                            fillmethod='repeat')

                        chopped_weeded.append(tr)

            chopped = chopped_weeded

        for tr in chopped:
            tr.wmin = wmin
            tr.wmax = wmax

        return chopped

    def chopper(
            self,
            tmin=None, tmax=None, tinc=None, tpad=0.,
            group_selector=None, trace_selector=None,
            want_incomplete=True, degap=True, maxgap=5, maxlap=None,
            keep_current_files_open=False, accessor_id=None,
            snap=(round, round), include_last=False, load_data=True,
            style=None):

        '''
        Get iterator for shifting window wise data extraction from waveform
        archive.

        :param tmin: start time (default uses start time of available data)
        :param tmax: end time (default uses end time of available data)
        :param tinc: time increment (window shift time) (default uses
            ``tmax-tmin``)
        :param tpad: padding time appended on either side of the data windows
            (window overlap is ``2*tpad``)
        :param group_selector: filter callback taking :py:class:`TracesGroup`
            objects
        :param trace_selector: filter callback taking
            :py:class:`pyrocko.trace.Trace` objects
        :param want_incomplete: if set to ``False``, gappy/incomplete traces
            are discarded from the results
        :param degap: whether to try to connect traces and to remove gaps and
            overlaps
        :param maxgap: maximum gap size in samples which is filled with
            interpolated samples when ``degap`` is ``True``
        :param maxlap: maximum overlap size in samples which is removed when
            ``degap`` is ``True``
        :param keep_current_files_open: whether to keep cached trace data in
            memory after the iterator has ended
        :param accessor_id: if given, used as a key to identify different
            points of extraction for the decision of when to release cached
            trace data (should be used when data is alternately extracted from
            more than one region / selection)
        :param snap: replaces Python's :py:func:`round` function which is used
            to determine indices where to start and end the trace data array
        :param include_last: whether to include last sample
        :param load_data: whether to load the waveform data. If set to
            ``False``, traces with no data samples, but with correct
            meta-information are returned
        :param style: set to ``'batch'`` to yield waveforms and information
            about the chopper state as :py:class:`Batch` objects. By default
            lists of :py:class:`pyrocko.trace.Trace` objects are yielded.
        :returns: iterator providing extracted waveforms for each extracted
            window. See ``style`` argument for details.
        '''
        if tmin is None:
            if self.tmin is None:
                logger.warning("Pile's tmin is not set - pile may be empty.")
                return
            tmin = self.tmin + tpad

        if tmax is None:
            if self.tmax is None:
                logger.warning("Pile's tmax is not set - pile may be empty.")
                return
            tmax = self.tmax - tpad

        if not self.is_relevant(tmin-tpad, tmax+tpad, group_selector):
            return

        if accessor_id not in self.open_files:
            self.open_files[accessor_id] = set()

        open_files = self.open_files[accessor_id]

        if tinc is None:
            tinc = tmax - tmin
            nwin = 1
        else:
            eps = tinc * 1e-6
            if tinc != 0.0:
                nwin = int(((tmax - eps) - tmin) / tinc) + 1
            else:
                nwin = 1

        for iwin in range(nwin):
            wmin, wmax = tmin+iwin*tinc, min(tmin+(iwin+1)*tinc, tmax)

            chopped, used_files = self.chop(
                wmin-tpad, wmax+tpad, group_selector, trace_selector, snap,
                include_last, load_data)

            for file in used_files - open_files:
                # increment datause counter on newly opened files
                file.use_data()

            open_files.update(used_files)

            processed = self._process_chopped(
                chopped, degap, maxgap, maxlap, want_incomplete, wmax, wmin,
                tpad)

            if style == 'batch':
                yield Batch(
                    tmin=wmin,
                    tmax=wmax,
                    i=iwin,
                    n=nwin,
                    traces=processed)

            else:
                yield processed

            unused_files = open_files - used_files

            while unused_files:
                file = unused_files.pop()
                file.drop_data()
                open_files.remove(file)

        if not keep_current_files_open:
            while open_files:
                file = open_files.pop()
                file.drop_data()

    def all(self, *args, **kwargs):
        '''
        Shortcut to aggregate :py:meth:`chopper` output into a single list.
        '''

        alltraces = []
        for traces in self.chopper(*args, **kwargs):
            alltraces.extend(traces)

        return alltraces

    def iter_all(self, *args, **kwargs):
        for traces in self.chopper(*args, **kwargs):
            for tr in traces:
                yield tr

    def chopper_grouped(self, gather, progress=None, *args, **kwargs):
        keys = self.gather_keys(gather)
        if len(keys) == 0:
            return

        outer_group_selector = None
        if 'group_selector' in kwargs:
            outer_group_selector = kwargs['group_selector']

        outer_trace_selector = None
        if 'trace_selector' in kwargs:
            outer_trace_selector = kwargs['trace_selector']

        # the use of this gather-cache makes it impossible to modify the pile
        # during chopping
        gather_cache = {}
        pbar = None
        try:
            if progress is not None:
                pbar = util.progressbar(progress, len(keys))

            for ikey, key in enumerate(keys):
                def tsel(tr):
                    return gather(tr) == key and (
                        outer_trace_selector is None
                        or outer_trace_selector(tr))

                def gsel(gr):
                    if gr not in gather_cache:
                        gather_cache[gr] = gr.gather_keys(gather)

                    return key in gather_cache[gr] and (
                        outer_group_selector is None
                        or outer_group_selector(gr))

                kwargs['trace_selector'] = tsel
                kwargs['group_selector'] = gsel

                for traces in self.chopper(*args, **kwargs):
                    yield traces

                if pbar:
                    pbar.update(ikey+1)

        finally:
            if pbar:
                pbar.finish()

    def gather_keys(self, gather, selector=None):
        keys = set()
        for subpile in self.subpiles.values():
            keys |= subpile.gather_keys(gather, selector)

        return sorted(keys)

    def iter_traces(
            self,
            load_data=False,
            return_abspath=False,
            group_selector=None,
            trace_selector=None):

        '''
        Iterate over all traces in pile.

        :param load_data: whether to load the waveform data, by default empty
            traces are yielded
        :param return_abspath: if ``True`` yield tuples containing absolute
            file path and :py:class:`pyrocko.trace.Trace` objects
        :param group_selector: filter callback taking :py:class:`TracesGroup`
            objects
        :param trace_selector: filter callback taking
            :py:class:`pyrocko.trace.Trace` objects

        Example; yields only traces, where the station code is 'HH1'::

            test_pile = pile.make_pile('/local/test_trace_directory')
            for t in test_pile.iter_traces(
                    trace_selector=lambda tr: tr.station=='HH1'):

                print t
        '''

        for subpile in self.subpiles.values():
            if not group_selector or group_selector(subpile):
                for tr in subpile.iter_traces(load_data, return_abspath,
                                              group_selector, trace_selector):
                    yield tr

    def iter_files(self):
        for subpile in self.subpiles.values():
            for file in subpile.iter_files():
                yield file

    def reload_modified(self):
        modified = False
        for subpile in self.subpiles.values():
            modified |= subpile.reload_modified()

        return modified

    def get_tmin(self):
        return self.tmin

    def get_tmax(self):
        return self.tmax

    def get_deltatmin(self):
        return self.deltatmin

    def get_deltatmax(self):
        return self.deltatmax

    def is_empty(self):
        return self.tmin is None and self.tmax is None

    def __str__(self):
        if self.tmin is not None and self.tmax is not None:
            tmin = util.time_to_str(self.tmin)
            tmax = util.time_to_str(self.tmax)
            s = 'Pile\n'
            s += 'number of subpiles: %i\n' % len(self.subpiles)
            s += 'timerange: %s - %s\n' % (tmin, tmax)
            s += 'networks: %s\n' % ', '.join(sl(self.networks.keys()))
            s += 'stations: %s\n' % ', '.join(sl(self.stations.keys()))
            s += 'locations: %s\n' % ', '.join(sl(self.locations.keys()))
            s += 'channels: %s\n' % ', '.join(sl(self.channels.keys()))
            s += 'deltats: %s\n' % ', '.join(sl(self.deltats.keys()))

        else:
            s = 'empty Pile'

        return s

    def snuffle(self, **kwargs):
        '''
        Visualize it.

        :param stations: list of :py:class:`pyrocko.model.station.Station`
            objects or ``None``
        :param events: list of :py:class:`pyrocko.model.event.Event` objects or
            ``None``
        :param markers: list of :py:class:`pyrocko.gui.snuffler.marker.Marker`
            objects or ``None``
        :param ntracks: float, number of tracks to be shown initially
            (default: 12)
        :param follow: time interval (in seconds) for real time follow mode or
            ``None``
        :param controls: bool, whether to show the main controls (default:
            ``True``)
        :param opengl: bool, whether to use opengl (default: ``False``)
        '''

        from pyrocko.gui.snuffler.snuffler import snuffle
        snuffle(self, **kwargs)


def make_pile(
        paths=None, selector=None, regex=None,
        fileformat='mseed',
        cachedirname=None, show_progress=True):

    '''
    Create pile from given file and directory names.

    :param paths: filenames and/or directories to look for traces. If paths is
        ``None`` ``sys.argv[1:]`` is used.
    :param selector: lambda expression taking group dict of regex match object
        as a single argument and which returns true or false to keep or reject
        a file
    :param regex: regular expression which filenames have to match
    :param fileformat: format of the files ('mseed', 'sac', 'kan',
        'from_extension', 'detect')
    :param cachedirname: loader cache is stored under this directory. It is
        created as neccessary.
    :param show_progress: show progress bar and other progress information
    '''

    if show_progress_force_off:
        show_progress = False

    if isinstance(paths, str):
        paths = [paths]

    if paths is None:
        paths = sys.argv[1:]

    if cachedirname is None:
        cachedirname = config.config().cache_dir

    fns = util.select_files(
        paths, include=regex, selector=selector, show_progress=show_progress)

    cache = get_cache(cachedirname)
    p = Pile()
    p.load_files(
        sorted(fns),
        cache=cache,
        fileformat=fileformat,
        show_progress=show_progress)

    return p


class Injector(trace.States):

    def __init__(
            self, pile,
            fixation_length=None,
            path=None,
            format='from_extension',
            forget_fixed=False):

        trace.States.__init__(self)
        self._pile = pile
        self._fixation_length = fixation_length
        self._format = format
        self._path = path
        self._forget_fixed = forget_fixed

    def set_fixation_length(self, length):
        '''
        Set length after which the fixation method is called on buffer traces.

        The length should be given in seconds. Give None to disable.
        '''
        self.fixate_all()
        self._fixation_length = length   # in seconds

    def set_save_path(
            self,
            path='dump_%(network)s.%(station)s.%(location)s.%(channel)s_'
                 '%(tmin)s_%(tmax)s.mseed'):

        self.fixate_all()
        self._path = path

    def inject(self, trace):
        logger.debug('Received a trace: %s' % trace)

        buf = self.get(trace)
        if buf is None:
            trbuf = trace.copy()
            buf = MemTracesFile(None, [trbuf])
            self._pile.add_file(buf)
            self.set(trace, buf)

        else:
            self._pile.remove_file(buf)
            trbuf = buf.get_traces()[0]
            buf.remove(trbuf)
            trbuf.append(trace.ydata)
            buf.add(trbuf)
            self._pile.add_file(buf)
            self.set(trace, buf)

        trbuf = buf.get_traces()[0]
        if self._fixation_length is not None:
            if trbuf.tmax - trbuf.tmin > self._fixation_length:
                self._fixate(buf, complete=False)

    def fixate_all(self):
        for state in list(self._states.values()):
            self._fixate(state[-1])

        self._states = {}

    def free(self, buf):
        self._fixate(buf)

    def _fixate(self, buf, complete=True):
        trbuf = buf.get_traces()[0]
        del_state = True
        if self._path:
            if self._fixation_length is not None:
                ttmin = trbuf.tmin
                ytmin = util.year_start(ttmin)
                n = int(math.floor((ttmin - ytmin) / self._fixation_length))
                tmin = ytmin + n*self._fixation_length
                traces = []
                t = tmin
                while t <= trbuf.tmax:
                    try:
                        traces.append(
                            trbuf.chop(
                                t,
                                t+self._fixation_length,
                                inplace=False,
                                snap=(math.ceil, math.ceil)))

                    except trace.NoData:
                        pass
                    t += self._fixation_length

                if abs(traces[-1].tmax - (t - trbuf.deltat)) < \
                        trbuf.deltat/100. or complete:

                    self._pile.remove_file(buf)

                else:  # reinsert incomplete last part
                    new_trbuf = traces.pop()
                    self._pile.remove_file(buf)
                    buf.remove(trbuf)
                    buf.add(new_trbuf)
                    self._pile.add_file(buf)
                    del_state = False

            else:
                traces = [trbuf]
                self._pile.remove_file(buf)

            fns = io.save(traces, self._path, format=self._format)

            if not self._forget_fixed:
                self._pile.load_files(
                    fns, show_progress=False, fileformat=self._format)

        if del_state:
            del self._states[trbuf.nslc_id]

    def __del__(self):
        self.fixate_all()
