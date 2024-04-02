# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel client to access FDSN web services for seismic waveforms and metadata.
'''

import time
import os
import copy
import logging
import tempfile
import importlib.util
from collections import defaultdict
try:
    import cPickle as pickle
except ImportError:
    import pickle
import os.path as op
from .base import Source, Constraint
from ..model import make_waveform_promise_nut, ehash, InvalidWaveform, \
    order_summary, WaveformOrder, g_tmin, g_tmax, g_tmin_queries, \
    codes_to_str_abbreviated, CodesNSLCE
from ..database import ExecuteGet1Error
from pyrocko.squirrel.error import SquirrelError
from pyrocko.client import fdsn

from pyrocko import util, trace, io
from pyrocko.io.io_common import FileLoadError
from pyrocko.io import stationxml
from pyrocko import progress
from pyrocko import has_paths

from pyrocko.guts import Object, String, Timestamp, List, Tuple, Int, Dict, \
    Duration, Bool, clone, dump_all_spickle


guts_prefix = 'squirrel'

logger = logging.getLogger('psq.client.fdsn')

g_sites_not_supporting = {
    'startbefore': ['geonet'],
    'includerestricted': ['geonet', 'ncedc', 'scedc']}

g_keys_conflicting_post_codes = {
    'network', 'station', 'location', 'channel', 'minlatitude', 'maxlatitude',
    'minlongitude', 'maxlongitude', 'latitude', 'longitude', 'minradius',
    'maxradius'}


def make_task(*args):
    return progress.task(*args, logger=logger)


def diff(fn_a, fn_b):
    try:
        if os.stat(fn_a).st_size != os.stat(fn_b).st_size:
            return True

    except OSError:
        return True

    with open(fn_a, 'rb') as fa:
        with open(fn_b, 'rb') as fb:
            while True:
                a = fa.read(1024)
                b = fb.read(1024)
                if a != b:
                    return True

                if len(a) == 0 or len(b) == 0:
                    return False


def move_or_keep(fn_temp, fn):
    if op.exists(fn):
        if diff(fn, fn_temp):
            os.rename(fn_temp, fn)
            status = 'updated'
        else:
            os.unlink(fn_temp)
            status = 'upstream unchanged'

    else:
        os.rename(fn_temp, fn)
        status = 'new'

    return status


class Archive(Object):

    def add(self):
        raise NotImplementedError()


class MSeedArchive(Archive):
    template = String.T(default=op.join(
        '%(tmin_year)s',
        '%(tmin_month)s',
        '%(tmin_day)s',
        'trace_%(network)s_%(station)s_%(location)s_%(channel)s'
        + '_%(block_tmin_us)s_%(block_tmax_us)s.mseed'))

    def __init__(self, **kwargs):
        Archive.__init__(self, **kwargs)
        self._base_path = None

    def set_base_path(self, path):
        self._base_path = path

    def add(self, order, trs):
        path = op.join(self._base_path, self.template)
        fmt = '%Y-%m-%d_%H-%M-%S.6FRAC'
        return io.save(trs, path, overwrite=True, additional=dict(
            block_tmin_us=util.time_to_str(order.tmin, format=fmt),
            block_tmax_us=util.time_to_str(order.tmax, format=fmt)))


def combine_selections(selection):
    out = []
    last = None
    for this in selection:
        if last and this[:4] == last[:4] and this[4] == last[5]:
            last = last[:5] + (this[5],)
        else:
            if last:
                out.append(last)

            last = this

    if last:
        out.append(last)

    return out


def orders_sort_key(order):
    return (order.codes, order.tmin)


def orders_to_selection(orders, pad=1.0):
    selection = []
    nslc_to_deltat = {}
    for order in sorted(orders, key=orders_sort_key):
        selection.append(
            order.codes.nslc + (order.tmin, order.tmax))
        nslc_to_deltat[order.codes.nslc] = order.deltat

    selection = combine_selections(selection)
    selection_padded = []
    for (net, sta, loc, cha, tmin, tmax) in selection:
        deltat = nslc_to_deltat[net, sta, loc, cha]
        selection_padded.append((
            net, sta, loc, cha, tmin-pad*deltat, tmax+pad*deltat))

    return selection_padded


def codes_to_selection(codes_list, tmin, tmax):
    if codes_list is None:
        return None

    selection = []
    for codes in sorted(codes_list):
        selection.append(
           codes.nslc + (tmin, tmax))

    return selection


class ErrorEntry(Object):
    time = Timestamp.T()
    order = WaveformOrder.T()
    kind = String.T()
    details = String.T(optional=True)


class ErrorAggregate(Object):
    site = String.T()
    kind = String.T()
    details = String.T()
    entries = List.T(ErrorEntry.T())
    codes = List.T(CodesNSLCE.T())
    time_spans = List.T(Tuple.T(2, Timestamp.T()))

    def __str__(self):
        codes = [str(x) for x in self.codes]
        scodes = '\n' + util.ewrap(codes, indent='    ') if codes else '<none>'
        tss = self.time_spans
        sspans = '\n' + util.ewrap(('%s - %s' % (
            util.time_to_str(ts[0]), util.time_to_str(ts[1])) for ts in tss),
            indent='   ')

        return ('FDSN "%s": download error summary for "%s" (%i)\n%s  '
                'Codes:%s\n  Time spans:%s') % (
            self.site,
            self.kind,
            len(self.entries),
            '  Details: %s\n' % self.details if self.details else '',
            scodes,
            sspans)


class ErrorLog(Object):
    site = String.T()
    entries = List.T(ErrorEntry.T())
    checkpoints = List.T(Int.T())

    def append_checkpoint(self):
        self.checkpoints.append(len(self.entries))

    def append(self, time, order, kind, details=''):
        entry = ErrorEntry(time=time, order=order, kind=kind, details=details)
        self.entries.append(entry)

    def iter_aggregates(self):
        by_kind_details = defaultdict(list)
        for entry in self.entries:
            by_kind_details[entry.kind, entry.details].append(entry)

        kind_details = sorted(by_kind_details.keys())

        for kind, details in kind_details:
            entries = by_kind_details[kind, details]
            codes = sorted(set(entry.order.codes for entry in entries))
            selection = orders_to_selection(entry.order for entry in entries)
            time_spans = sorted(set(row[-2:] for row in selection))
            yield ErrorAggregate(
                site=self.site,
                kind=kind,
                details=details,
                entries=entries,
                codes=codes,
                time_spans=time_spans)

    def summarize_recent(self):
        ioff = self.checkpoints[-1] if self.checkpoints else 0
        recent = self.entries[ioff:]
        kinds = sorted(set(entry.kind for entry in recent))
        if recent:
            return '%i error%s (%s)' % (
                len(recent), util.plural_s(recent), '; '.join(kinds))
        else:
            return ''


class Aborted(SquirrelError):
    pass


class FDSNSource(Source, has_paths.HasPaths):

    '''
    Squirrel data-source to transparently get data from FDSN web services.

    Attaching an :py:class:`FDSNSource` object to a
    :py:class:`~pyrocko.squirrel.base.Squirrel` allows the latter to download
    station and waveform data from an FDSN web service should the data not
    already happen to be available locally.
    '''

    site = String.T(
        help='FDSN site url or alias name (see '
             ':py:mod:`pyrocko.client.fdsn`).')

    query_args = Dict.T(
        String.T(), String.T(),
        optional=True,
        help='Common query arguments, which are appended to all queries.')

    codes = List.T(
        CodesNSLCE.T(),
        optional=True,
        help='List of codes patterns to query via POST parameters.')

    expires = Duration.T(
        optional=True,
        help='Expiration time [s]. Information older than this will be '
             'refreshed. This only applies to station-metadata. Waveforms do '
             'not expire. If set to ``None`` neither type of data  expires.')

    cache_path = String.T(
        optional=True,
        help='Directory path where any downloaded waveforms and station '
             'meta-data are to be kept. By default the Squirrel '
             "environment's cache directory is used.")

    shared_waveforms = Bool.T(
        default=False,
        help='If ``True``, waveforms are shared with other FDSN sources in '
             'the same Squirrel environment. If ``False``, they are kept '
             'separate.')

    user_credentials = Tuple.T(
        2, String.T(),
        optional=True,
        help='User and password for FDSN servers requiring password '
             'authentication')

    auth_token = String.T(
        optional=True,
        help='Authentication token to be presented to the FDSN server.')

    auth_token_path = String.T(
        optional=True,
        help='Path to file containing the authentication token to be '
             'presented to the FDSN server.')

    hotfix_module_path = has_paths.Path.T(
        optional=True,
        help='Path to Python module to locally patch metadata errors.')

    def __init__(self, site, query_args=None, codes=None, **kwargs):
        if codes:
            codes = [CodesNSLCE(codes_) for codes_ in codes]

        if codes is not None and query_args is not None:
            conflicting = g_keys_conflicting_post_codes \
                & set(query_args.keys())

            if conflicting:
                raise SquirrelError(
                    'Cannot use %s in `query_args` when `codes` are also '
                    'given.' % ' or '.join("'%s'" % k for k in conflicting))

        Source.__init__(
            self, site=site, query_args=query_args, codes=codes, **kwargs)

        self._constraint = None
        self._hash = self.make_hash()
        self._source_id = 'client:fdsn:%s' % self._hash
        self._error_infos = []

    def describe(self):
        return self._source_id

    def make_hash(self):
        s = self.site
        s += 'notoken' \
            if (self.auth_token is None and self.auth_token_path is None) \
            else 'token'

        if self.user_credentials is not None:
            s += self.user_credentials[0]
        else:
            s += 'nocred'

        if self.query_args is not None:
            s += ','.join(
                '%s:%s' % (k, self.query_args[k])
                for k in sorted(self.query_args.keys()))
        else:
            s += 'noqueryargs'

        if self.codes is not None:
            s += 'post_codes:' + ','.join(
                codes.safe_str for codes in self.codes)

        return ehash(s)

    def get_hash(self):
        return self._hash

    def get_auth_token(self):
        if self.auth_token:
            return self.auth_token

        elif self.auth_token_path is not None:
            try:
                with open(self.auth_token_path, 'rb') as f:
                    return f.read().decode('ascii')

            except OSError as e:
                raise FileLoadError(
                    'Cannot load auth token file (%s): %s'
                    % (str(e), self.auth_token_path))

        else:
            raise Exception(
                'FDSNSource: auth_token and auth_token_path are mutually '
                'exclusive.')

    def setup(self, squirrel, check=True):
        self._cache_path = op.join(
            self.cache_path or squirrel._cache_path, 'fdsn')

        util.ensuredir(self._cache_path)
        self._load_constraint()
        self._archive = MSeedArchive()
        waveforms_path = self._get_waveforms_path()
        util.ensuredir(waveforms_path)
        self._archive.set_base_path(waveforms_path)

        squirrel.add(
            self._get_waveforms_path(),
            check=check)

        fn = self._get_channels_path()
        if os.path.exists(fn):
            squirrel.add(fn)

        squirrel.add_virtual(
            [], virtual_paths=[self._source_id])

        responses_path = self._get_responses_path()
        if os.path.exists(responses_path):
            squirrel.add(
                responses_path, kinds=['response'], exclude=r'\.temp$')

        self._hotfix_module = None

    def _hotfix(self, query_type, sx):
        if self.hotfix_module_path is None:
            return

        if self._hotfix_module is None:
            module_path = self.expand_path(self.hotfix_module_path)
            spec = importlib.util.spec_from_file_location(
                'hotfix_' + self._hash, module_path)
            self._hotfix_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self._hotfix_module)

        hook = getattr(
            self._hotfix_module, 'stationxml_' + query_type + '_hook')

        return hook(sx)

    def _get_constraint_path(self):
        return op.join(self._cache_path, self._hash, 'constraint.pickle')

    def _get_channels_path(self):
        return op.join(self._cache_path, self._hash, 'channels.stationxml')

    def _get_responses_path(self, nslc=None):
        dirpath = op.join(
            self._cache_path, self._hash, 'responses')

        if nslc is None:
            return dirpath
        else:
            return op.join(
                dirpath, 'response_%s_%s_%s_%s.stationxml' % nslc)

    def _get_waveforms_path(self):
        if self.shared_waveforms:
            return op.join(self._cache_path, 'waveforms')
        else:
            return op.join(self._cache_path, self._hash, 'waveforms')

    def _log_meta(self, message, target=logger.info):
        log_prefix = 'FDSN "%s" metadata:' % self.site
        target(' '.join((log_prefix, message)))

    def _log_responses(self, message, target=logger.info):
        log_prefix = 'FDSN "%s" responses:' % self.site
        target(' '.join((log_prefix, message)))

    def _log_info_data(self, *args):
        log_prefix = 'FDSN "%s" waveforms:' % self.site
        logger.info(' '.join((log_prefix,) + args))

    def _str_expires(self, t, now):
        if t is None:
            return 'expires: never'
        else:
            expire = 'expires' if t > now else 'expired'
            return '%s: %s' % (
                expire,
                util.time_to_str(t, format='%Y-%m-%d %H:%M:%S'))

    def update_channel_inventory(self, squirrel, constraint=None):
        if constraint is None:
            constraint = Constraint()

        expiration_time = self._get_channels_expiration_time()
        now = time.time()

        log_target = logger.info
        if self._constraint and self._constraint.contains(constraint) \
                and (expiration_time is None or now < expiration_time):

            status = 'using cached'

        else:
            if self._constraint:
                constraint_temp = copy.deepcopy(self._constraint)
                constraint_temp.expand(constraint)
                constraint = constraint_temp

            try:
                channel_sx = self._do_channel_query(constraint)

                channel_sx.created = None  # timestamp would ruin diff

                fn = self._get_channels_path()
                util.ensuredirs(fn)
                fn_temp = fn + '.%i.temp' % os.getpid()

                dump_all_spickle([channel_sx], filename=fn_temp)
                # channel_sx.dump_xml(filename=fn_temp)

                status = move_or_keep(fn_temp, fn)

                if status == 'upstream unchanged':
                    squirrel.get_database().silent_touch(fn)

                self._constraint = constraint
                self._dump_constraint()

            except OSError as e:
                status = 'update failed (%s)' % str(e)
                log_target = logger.error

        expiration_time = self._get_channels_expiration_time()
        self._log_meta(
            '%s (%s)' % (status, self._str_expires(expiration_time, now)),
            target=log_target)

        fn = self._get_channels_path()
        if os.path.exists(fn):
            squirrel.add(fn)

    def _do_channel_query(self, constraint):
        extra_args = {}

        tmin = constraint.tmin \
            if constraint.tmin is not None and constraint.tmin != g_tmin \
            else g_tmin_queries

        tmax = constraint.tmax \
            if constraint.tmax is not None and constraint.tmax != g_tmax \
            else g_tmax

        if self.site in g_sites_not_supporting['startbefore']:
            ktmin = 'starttime'
            ktmax = 'endtime'
        else:
            ktmin = 'endafter'
            ktmax = 'startbefore'

        if self.codes is None:
            extra_args[ktmin] = tmin
            extra_args[ktmax] = tmax

        if self.site not in g_sites_not_supporting['includerestricted']:
            extra_args.update(
                includerestricted=(
                    self.user_credentials is not None
                    or self.auth_token is not None
                    or self.auth_token_path is not None))

        if self.query_args is not None:
            extra_args.update(self.query_args)

        self._log_meta('querying...')

        try:
            channel_sx = fdsn.station(
                site=self.site,
                format='text',
                level='channel',
                selection=codes_to_selection(self.codes, tmin, tmax),
                **extra_args)

            self._hotfix('channel', channel_sx)

            return channel_sx

        except fdsn.EmptyResult:
            return stationxml.FDSNStationXML(source='dummy-empty-result')

        except fdsn.DownloadError as e:
            raise SquirrelError(str(e))

    def _load_constraint(self):
        fn = self._get_constraint_path()
        if op.exists(fn):
            with open(fn, 'rb') as f:
                self._constraint = pickle.load(f)
        else:
            self._constraint = None

    def _dump_constraint(self):
        with open(self._get_constraint_path(), 'wb') as f:
            pickle.dump(self._constraint, f, protocol=2)

    def _get_expiration_time(self, path):
        if self.expires is None:
            return None

        try:
            t = os.stat(path)[8]
            return t + self.expires

        except OSError:
            return 0.0

    def _get_channels_expiration_time(self):
        return self._get_expiration_time(self._get_channels_path())

    def update_waveform_promises(self, squirrel, constraint):
        from ..base import gaps
        cpath = os.path.abspath(self._get_channels_path())

        ctmin = constraint.tmin
        ctmax = constraint.tmax

        nuts = squirrel.iter_nuts(
            'channel',
            path=cpath,
            codes=constraint.codes,
            tmin=ctmin,
            tmax=ctmax)

        coverages = squirrel.get_coverage(
            'waveform',
            codes=constraint.codes if constraint.codes else None,
            tmin=ctmin,
            tmax=ctmax)

        codes_to_avail = defaultdict(list)
        for coverage in coverages:
            for tmin, tmax, _ in coverage.iter_spans():
                codes_to_avail[coverage.codes].append((tmin, tmax))

        def sgaps(nut):
            for tmin, tmax in gaps(
                    codes_to_avail[nut.codes],
                    max(ctmin, nut.tmin) if ctmin is not None else nut.tmin,
                    min(ctmax, nut.tmax) if ctmax is not None else nut.tmax):

                subnut = clone(nut)
                subnut.tmin = tmin
                subnut.tmax = tmax

                if subnut.deltat is None:
                    continue

                # ignore 1-sample gaps produced by rounding errors
                if subnut.tmax - subnut.tmin < 2*subnut.deltat:
                    continue

                yield subnut

        def wanted(nuts):
            for nut in nuts:
                for nut in sgaps(nut):
                    yield nut

        path = self._source_id
        squirrel.add_virtual(
            (make_waveform_promise_nut(
                file_path=path,
                **nut.waveform_promise_kwargs) for nut in wanted(nuts)),
            virtual_paths=[path])

    def remove_waveform_promises(self, squirrel, from_database='selection'):
        '''
        Remove waveform promises from live selection or global database.

        :param from_database:
            Remove from live selection ``'selection'`` or global database
            ``'global'``.
        '''

        path = self._source_id
        if from_database == 'selection':
            squirrel.remove(path)
        elif from_database == 'global':
            squirrel.get_database().remove(path)
        else:
            raise ValueError(
                'Values allowed for from_database: ("selection", "global")')

    def _get_user_credentials(self):
        d = {}
        if self.user_credentials is not None:
            d['user'], d['passwd'] = self.user_credentials

        if self.auth_token is not None or self.auth_token_path is not None:
            d['token'] = self.get_auth_token()

        return d

    def download_waveforms(
            self, orders, success, batch_add, error_permanent,
            error_temporary):

        elog = ErrorLog(site=self.site)
        orders.sort(key=orders_sort_key)
        neach = 20
        i = 0
        task = make_task(
            'FDSN "%s" waveforms: downloading' % self.site, len(orders))

        while i < len(orders):
            orders_now = orders[i:i+neach]
            selection_now = orders_to_selection(orders_now)
            nsamples_estimate = sum(
                order.estimate_nsamples() for order in orders_now)

            nsuccess = 0
            elog.append_checkpoint()
            self._log_info_data(
                'downloading, %s' % order_summary(orders_now))

            all_paths = []
            with tempfile.TemporaryDirectory() as tmpdir:
                try:
                    data = fdsn.dataselect(
                        site=self.site, selection=selection_now,
                        **self._get_user_credentials())

                    now = time.time()

                    path = op.join(tmpdir, 'tmp.mseed')
                    with open(path, 'wb') as f:
                        nread = 0
                        while True:
                            buf = data.read(1024)
                            nread += len(buf)
                            if not buf:
                                break
                            f.write(buf)

                            # abort if we get way more data than expected
                            if nread > max(
                                    1024 * 1000,
                                    nsamples_estimate * 4 * 10):

                                raise Aborted('Too much data received.')

                    trs = io.load(path)

                    by_nslc = defaultdict(list)
                    for tr in trs:
                        by_nslc[tr.nslc_id].append(tr)

                    for order in orders_now:
                        trs_order = []
                        err_this = None
                        for tr in by_nslc[order.codes.nslc]:
                            try:
                                order.validate(tr)
                                trs_order.append(tr.chop(
                                    order.tmin, order.tmax, inplace=False))

                            except trace.NoData:
                                err_this = (
                                    'empty result', 'empty sub-interval')

                            except InvalidWaveform as e:
                                err_this = ('invalid waveform', str(e))

                        if len(trs_order) == 0:
                            if err_this is None:
                                err_this = ('empty result', '')

                            elog.append(now, order, *err_this)
                            if order.is_near_real_time():
                                error_temporary(order)
                            else:
                                error_permanent(order)
                        else:
                            def tsame(ta, tb):
                                return abs(tb - ta) < 2 * order.deltat

                            if len(trs_order) != 1 \
                                    or not tsame(
                                        trs_order[0].tmin, order.tmin) \
                                    or not tsame(
                                        trs_order[0].tmax, order.tmax):

                                if err_this:
                                    elog.append(
                                        now, order,
                                        'partial result, %s' % err_this[0],
                                        err_this[1])
                                else:
                                    elog.append(now, order, 'partial result')

                            paths = self._archive.add(order, trs_order)
                            all_paths.extend(paths)

                            nsuccess += 1
                            success(order, trs_order)

                except fdsn.EmptyResult:
                    now = time.time()
                    for order in orders_now:
                        elog.append(now, order, 'empty result')
                        if order.is_near_real_time():
                            error_temporary(order)
                        else:
                            error_permanent(order)

                except Aborted as e:
                    now = time.time()
                    for order in orders_now:
                        elog.append(now, order, 'aborted', str(e))
                        error_permanent(order)

                except (util.HTTPError, fdsn.DownloadError) as e:
                    now = time.time()
                    for order in orders_now:
                        elog.append(now, order, 'http error', str(e))
                        error_temporary(order)

            emessage = elog.summarize_recent()

            self._log_info_data(
                '%i download%s %ssuccessful' % (
                    nsuccess,
                    util.plural_s(nsuccess),
                    '(partially) ' if emessage else '')
                + (', %s' % emessage if emessage else ''))

            if all_paths:
                batch_add(all_paths)

            i += neach
            task.update(i)

        for agg in elog.iter_aggregates():
            logger.warning(str(agg))

        task.done()

    def _do_response_query(self, selection):
        extra_args = {}

        if self.site not in g_sites_not_supporting['includerestricted']:
            extra_args.update(
                includerestricted=(
                    self.user_credentials is not None
                    or self.auth_token is not None
                    or self.auth_token_path is not None))

        self._log_responses('querying...')

        try:
            response_sx = fdsn.station(
                site=self.site,
                level='response',
                selection=selection,
                **extra_args)

            self._hotfix('response', response_sx)
            return response_sx

        except fdsn.EmptyResult:
            return stationxml.FDSNStationXML(source='dummy-empty-result')

        except fdsn.DownloadError as e:
            raise SquirrelError(str(e))

    def update_response_inventory(self, squirrel, constraint):
        cpath = os.path.abspath(self._get_channels_path())
        nuts = squirrel.iter_nuts(
            'channel', path=cpath, codes=constraint.codes)

        tmin = g_tmin_queries
        tmax = g_tmax

        selection = []
        now = time.time()
        have = set()
        status = defaultdict(list)
        for nut in nuts:
            nslc = nut.codes.nslc
            if nslc in have:
                continue
            have.add(nslc)

            fn = self._get_responses_path(nslc)
            expiration_time = self._get_expiration_time(fn)
            if os.path.exists(fn) \
                    and (expiration_time is None or now < expiration_time):
                status['using cached'].append(nslc)
            else:
                selection.append(nslc + (tmin, tmax))

        dummy = stationxml.FDSNStationXML(source='dummy-empty')
        neach = 100
        i = 0
        fns = []
        while i < len(selection):
            selection_now = selection[i:i+neach]
            i += neach

            try:
                sx = self._do_response_query(selection_now)
            except Exception as e:
                status['update failed (%s)' % str(e)].extend(
                    entry[:4] for entry in selection_now)
                continue

            sx.created = None  # timestamp would ruin diff

            by_nslc = dict(stationxml.split_channels(sx))

            for entry in selection_now:
                nslc = entry[:4]
                response_sx = by_nslc.get(nslc, dummy)
                try:
                    fn = self._get_responses_path(nslc)
                    fn_temp = fn + '.%i.temp' % os.getpid()

                    util.ensuredirs(fn_temp)

                    dump_all_spickle([response_sx], filename=fn_temp)
                    # response_sx.dump_xml(filename=fn_temp)

                    status_this = move_or_keep(fn_temp, fn)

                    if status_this == 'upstream unchanged':
                        try:
                            squirrel.get_database().silent_touch(fn)
                        except ExecuteGet1Error:
                            pass

                    status[status_this].append(nslc)
                    fns.append(fn)

                except OSError as e:
                    status['update failed (%s)' % str(e)].append(nslc)

        for k in sorted(status):
            if k.find('failed') != -1:
                log_target = logger.error
            else:
                log_target = logger.info

            self._log_responses(
                '%s: %s' % (
                    k, codes_to_str_abbreviated(
                        CodesNSLCE(tup) for tup in status[k])),
                target=log_target)

        if fns:
            squirrel.add(fns, kinds=['response'])


__all__ = [
    'FDSNSource',
]
