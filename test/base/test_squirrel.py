
import time
import math
import os
import copy
import pickle
import unittest
import tempfile
import shutil
import os.path as op
import logging
from collections import defaultdict

import numpy as num

from .. import common
from pyrocko import squirrel, util, pile, io, trace, model as pmodel
from pyrocko import progress
from pyrocko.parimap import parimap
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO


progress.g_force_viewer_off = True


logger = logging.getLogger('test_squirrel.py')


class SquirrelTestCase(unittest.TestCase):
    tempdirs = []

    test_files = [
        ('test1.mseed', 'mseed'),
        ('test2.mseed', 'mseed'),
        ('test1.sac', 'sac'),
        ('test1.stationxml', 'stationxml'),
        ('test2.stationxml', 'stationxml'),
        ('test1.stations', 'pyrocko_stations'),
        ('test1.cube', 'datacube'),
        ('events2.txt', 'pyrocko_events')]

    @classmethod
    def setUpClass(cls):
        cls.tempdirs.append(tempfile.mkdtemp())
        cls.tempdir = cls.tempdirs[0]

    @classmethod
    def tearDownClass(cls):
        for i in range(10):
            try:
                for d in cls.tempdirs:
                    if os.path.exists(d):
                        shutil.rmtree(d)

                break

            except Exception:
                # trying to prevent random fails on windows
                time.sleep(1)

    def test_nslce_codes(self):

        C = squirrel.CodesNSLCE

        for invalid in [
                '', 'sta', 'net.sta', 'net.sta.loc',
                'net.sta.loc.cha.ext.ext']:

            with self.assertRaises(squirrel.CodesError):
                C(invalid)

        for invalid in [
                ('n.n', 's', 'l', 'c'),
                ('n.n', 's', 'l', 'c', 'e')]:

            with self.assertRaises(squirrel.CodesError):
                C(*invalid)

        for valid in [
                'net.sta.loc.cha',
                '...',
                'net.sta.loc.cha.ext']:

            c = C(valid)
            assert (c.network, c.station, c.location, c.channel, c.extra) \
                == c.as_tuple()

            assert str(c) == valid
            assert C(valid) is C(*c.as_tuple())
            assert C(valid) == C(*c.as_tuple())
            assert C(valid) is C(**c.as_dict())
            assert C(valid) == C(**c.as_dict())
            d1 = c.replace(station='sta2')
            d2 = C(c.network, 'sta2', c.location, c.channel, c.extra)
            assert d1 is d2
            assert d1 == d2
            assert d1 is copy.deepcopy(d2)
            assert d1 is copy.copy(d2)
            assert d1 is pickle.loads(pickle.dumps(d2))

        sta = squirrel.Channel(
            codes='net.sta.loc.cha',
            lat=11.,
            lon=12.,
            depth=1000.)

        assert sta.codes is C('net.sta.loc.cha')

    def test_detect(self):
        for (fn, format) in SquirrelTestCase.test_files:
            fpath = common.test_data_file(fn)
            self.assertEqual(format, squirrel.detect_format(fpath))

        fpath = op.join(self.tempdir, 'emptyfile')
        with open(fpath, 'wb'):
            pass

        with self.assertRaises(squirrel.FormatDetectionFailed):
            squirrel.detect_format(fpath)

        with self.assertRaises(squirrel.FormatDetectionFailed):
            squirrel.detect_format('nonexist')

    def test_load(self):
        ii = 0
        for (fn, format) in SquirrelTestCase.test_files:
            fpath = common.test_data_file(fn)
            for nut in squirrel.iload(fpath, content=[]):
                ii += 1

        assert ii == 425

        ii = 0
        database = squirrel.Database()
        for (fn, _) in SquirrelTestCase.test_files:
            fpath = common.test_data_file(fn)
            for nut in squirrel.iload(fpath, content=[], database=database):
                ii += 1

        assert ii == 425

        ii = 0
        for (fn, _) in SquirrelTestCase.test_files:
            fpath = common.test_data_file(fn)
            for nut in squirrel.iload(fpath, content=[], database=database):
                ii += 1

        ii = 0
        for (fn, _) in SquirrelTestCase.test_files:
            fpath = common.test_data_file(fn)
            for nut in squirrel.iload(fpath, database=database):
                ii += 1

        assert ii == 425

        fpaths = [
            common.test_data_file(fn)
            for (fn, _) in SquirrelTestCase.test_files]

        ii = 0
        for nut in squirrel.iload(fpaths, content=[], database=database):
            ii += 1

        assert ii == 425

        fpath = op.join(self.tempdir, 'emptyfile')
        with open(fpath, 'wb'):
            pass

        ii = 0
        for nut in squirrel.iload(fpath):
            ii += 1

        assert ii == 0

        with self.assertRaises(squirrel.UnknownFormat):
            for nut in squirrel.iload(fpath, format='nonexist'):
                pass

    def test_squirrel(self):
        db_path = os.path.join(self.tempdir, 'test.squirrel')
        for kinds in [None, 'waveform', ['station', 'channel']]:
            for persistent in [None, 'my_selection1', 'my_selection2']:
                sq = squirrel.Squirrel(database=db_path, persistent=persistent)
                for (fn, format) in SquirrelTestCase.test_files[:]:
                    fpath = common.test_data_file(fn)
                    sq.add(fpath, kinds=kinds)

                sq.get_stats()
                if kinds is not None:
                    if isinstance(kinds, str):
                        kinds_ = [kinds]
                    else:
                        kinds_ = kinds

                    for k in sq.get_kinds():
                        assert k in kinds_

                all_codes = set()
                for k in sq.get_kinds():
                    for codes in sq.get_codes(k):
                        all_codes.add(codes)

                assert all_codes == set(sq.get_codes())

                all_kinds = set()
                for c in sq.get_codes():
                    for kind in sq.get_kinds(c):
                        all_kinds.add(kind)

                assert all_kinds == set(sq.get_kinds())

                counts = sq.get_counts()
                for k in counts:
                    assert set(counts[k]) == set(sq.get_counts(k))

                db = sq.get_database()
                counts = db.get_counts()
                for k in counts:
                    assert set(counts[k]) == set(db.get_counts(k))

                if persistent is not None:
                    sq._delete()
                else:
                    del sq

        from pyrocko.squirrel import database as dbm
        dbm.close_database(db)

    def test_dig_undig(self):
        nuts = []
        for path in 'abcde':
            path = 'virtual:' + path
            for file_element in range(2):
                nuts.append(squirrel.Nut(
                    file_path=path,
                    file_format='test',
                    file_segment=0,
                    file_element=file_element,
                    kind_id=squirrel.to_kind_id('undefined')))

        database = squirrel.Database()
        database.dig(nuts)

        data = defaultdict(list)
        for path in 'abcde':
            path = 'virtual:' + path
            nuts2 = database.undig(path)
            for nut in nuts2:
                data[nut.file_path].append(nut.file_element)

        for path in 'abcde':
            path = 'virtual:' + path
            self.assertEqual([0, 1], sorted(data[path]))

        data = defaultdict(list)
        for path in 'ac':
            path = 'virtual:' + path
            nuts2 = database.undig(path)
            for nut in nuts2:
                data[nut.file_path].append(nut.file_element)

        for path in 'ac':
            path = 'virtual:' + path
            self.assertEqual([0, 1], sorted(data[path]))

        data = defaultdict(list)
        for fn, nuts3 in database.undig_all():
            for nut in nuts3:
                data[nut.file_path].append(nut.file_element)

        for path in 'abcde':
            path = 'virtual:' + path
            self.assertEqual([0, 1], sorted(data[path]))

    def test_add_update(self):

        tempdir = os.path.join(self.tempdir, 'test_add_update')

        def make_files(vers):
            trs = [
                trace.Trace(
                    station='%02i' % i,
                    tmin=float(vers),
                    deltat=1.0,
                    ydata=num.array([vers, vers], dtype=num.int32))
                for i in range(2)]

            return io.save(trs, op.join(tempdir, 'traces_%(station)s.mseed'))

        try:
            database = squirrel.Database(log_statements=True)

            sq = squirrel.Squirrel(database=database)

            assert sq.get_nfiles() == 0
            assert sq.get_nnuts() == 0
            assert sq.get_total_size() == 0

            fns = make_files(0)
            sq.add(fns)
            assert sq.get_nfiles() == 2
            assert sq.get_nnuts() == 2
            sq.add(fns)
            assert sq.get_nfiles() == 2
            assert sq.get_nnuts() == 2

            assert sq.get_time_span() == (0., 2.)

            f = StringIO()
            sq.print_tables(stream=f)
            database.print_tables(stream=f)

            time.sleep(1.1)  # make sure modification time is different
            fns = make_files(1)
            sq.add(fns, check=False)
            assert sq.get_nfiles() == 2
            assert sq.get_nnuts() == 2

            assert sorted(sq.get_codes()) == [
                ('', '00', '', '', ''), ('', '01', '', '', '')]
            assert list(sq.iter_kinds()) == ['waveform']

            assert len(sq.get_nuts('waveform', tmin=-10., tmax=10.)) == 2
            assert len(sq.get_nuts('waveform', tmin=-1., tmax=0.)) == 0
            assert len(sq.get_nuts('waveform', tmin=0., tmax=1.)) == 2
            assert len(sq.get_nuts('waveform', tmin=1., tmax=2.)) == 2
            assert len(sq.get_nuts('waveform', tmin=2., tmax=3.)) == 0
            assert len(sq.get_nuts('waveform', tmin=-1., tmax=0.5)) == 2
            assert len(sq.get_nuts('waveform', tmin=0.5, tmax=1.5)) == 2
            assert len(sq.get_nuts('waveform', tmin=0.2, tmax=0.7)) == 2

            sq.add(fns, check=True)
            assert sq.get_nfiles() == 2
            assert sq.get_nnuts() == 2

            assert sorted(sq.get_codes()) == [
                ('', '00', '', '', ''), ('', '01', '', '', '')]
            assert list(sq.iter_kinds()) == ['waveform']

            assert len(sq.get_nuts('waveform', tmin=0., tmax=1.)) == 0
            assert len(sq.get_nuts('waveform', tmin=1., tmax=2.)) == 2
            assert len(sq.get_nuts('waveform', tmin=2., tmax=3.)) == 2
            assert len(sq.get_nuts('waveform', tmin=3., tmax=4.)) == 0

            shutil.rmtree(tempdir)

            sq.add(fns, check=True)
            assert sq.get_nfiles() == 2
            assert sq.get_nnuts() == 0

            assert list(sq.iter_codes()) == []
            assert list(sq.iter_kinds()) == []

            assert len(sq.get_nuts('waveform', tmin=-10., tmax=10.)) == 0

            time.sleep(1.1)  # make sure modification time is different
            fns = make_files(2)
            sq.add(fns)
            assert sq.get_nfiles() == 2
            assert sq.get_nnuts() == 2

            time.sleep(1.1)  # make sure modification time is different
            fns = make_files(3)
            assert len(sq.get_nuts('waveform', tmin=1., tmax=2.)) == 0
            assert len(sq.get_nuts('waveform', tmin=2., tmax=3.)) == 2
            assert len(sq.get_nuts('waveform', tmin=3., tmax=4.)) == 2
            assert len(sq.get_nuts('waveform', tmin=4., tmax=5.)) == 0
            sq.reload()
            assert len(sq.get_nuts('waveform', tmin=2., tmax=3.)) == 0
            assert len(sq.get_nuts('waveform', tmin=3., tmax=4.)) == 2
            assert len(sq.get_nuts('waveform', tmin=4., tmax=5.)) == 2
            assert len(sq.get_nuts('waveform', tmin=5., tmax=6.)) == 0

            time.sleep(1.1)  # make sure modification time is different
            fns = make_files(4)
            # late detection
            for tr in sq.get_waveforms():
                assert abs(tr.tmin - 4.) < 1e-6

            for nut in sq.get_nuts('waveform'):
                assert abs(nut.tmin - 4.) < 1e-6

            sq.remove(fns)
            assert sq.get_nfiles() == 0
            assert sq.get_nnuts() == 0

        finally:
            shutil.rmtree(tempdir)

    def test_chop_suey(self):
        tmin_t = util.stt('2000-01-01 00:00:00')
        tmin_e = util.stt('2001-01-01 00:00:00')

        nt = 3
        nf = 10
        deltat = 0.5

        ne = 2

        all_nuts = []
        for it in range(nt):
            path = 'virtual:test_chop_suey_%i' % it
            tmin = tmin_t + (it*nf) * deltat
            tmax = tmin_t + ((it+1)*nf) * deltat
            tmin_seconds, tmin_offset = squirrel.model.tsplit(tmin)
            tmax_seconds, tmax_offset = squirrel.model.tsplit(tmax)
            all_nuts.append(squirrel.Nut(
                file_path=path,
                file_format='virtual',
                tmin_seconds=tmin_seconds,
                tmin_offset=tmin_offset,
                tmax_seconds=tmax_seconds,
                tmax_offset=tmax_offset,
                deltat=deltat,
                kind_id=squirrel.to_kind_id('undefined')))

        for ie in range(ne):
            path = 'virtual:test_chop_suey_%i' % (nt+ie)
            tmin = tmax = tmin_e + nt*nf*deltat + ie*deltat
            tmin_seconds, tmin_offset = squirrel.model.tsplit(tmin)
            tmax_seconds, tmax_offset = squirrel.model.tsplit(tmax)
            all_nuts.append(squirrel.Nut(
                file_path=path,
                file_format='virtual',
                tmin_seconds=tmin_seconds,
                tmin_offset=tmin_offset,
                tmax_seconds=tmax_seconds,
                tmax_offset=tmax_offset,
                kind_id=squirrel.to_kind_id('undefined')))

        squirrel.io.backends.virtual.add_nuts(all_nuts)
        database = squirrel.Database()
        sq = squirrel.Squirrel(database=database)

        sq.add(
            ('virtual:test_chop_suey_%i' % it for it in range(nt+ne)),
            check=False)

        for it in range(-1, nt+1):
            tmin = tmin_t + (it*nf) * deltat
            tmax = tmin_t + ((it+1)*nf) * deltat
            # open - open
            assert len(sq.get_nuts(tmin=tmin, tmax=tmax)) == int(0 <= it < nt)
            # closed - open
            assert len(sq.get_nuts(tmin=tmin, tmax=tmin)) == int(0 <= it < nt)

        for ie in range(-1, ne+1):
            tmin = tmin_e + nt*nf*deltat + ie*deltat
            tmax = tmin_e + nt*nf*deltat + (ie+1)*deltat
            # open - closed
            assert len(sq.get_nuts(tmin=tmin, tmax=tmax)) == int(0 <= ie < ne)
            # closed - closed
            assert len(sq.get_nuts(tmin=tmin, tmax=tmin)) == int(0 <= ie < ne)

    def test_chop(self):
        self.run_chop()

    def benchmark_chop(self):
        bench = self.run_chop(100000, ne=10)
        print(bench)

    def run_chop(self, nt=100, ne=10):

        tmin_g = util.stt('2000-01-01 00:00:00')
        tmax_g = util.stt('2020-01-01 00:00:00')

        txs = num.sort(num.random.uniform(tmin_g, tmax_g, nt+1))
        txs[0] = tmin_g
        txs[-1] = tmax_g

        kind = 'undefined'

        all_nuts = []
        for it in range(nt):
            path = 'virtual:test_chop_%i' % it
            tmin = txs[it]
            tmax = txs[it+1] - 10.
            tmin_seconds, tmin_offset = squirrel.model.tsplit(tmin)
            tmax_seconds, tmax_offset = squirrel.model.tsplit(tmax)
            for file_element in range(ne):
                all_nuts.append(squirrel.Nut(
                    file_path=path,
                    file_format='virtual',
                    file_segment=0,
                    file_element=file_element,
                    codes=squirrel.CodesX('c%02i' % file_element),
                    tmin_seconds=tmin_seconds,
                    tmin_offset=tmin_offset,
                    tmax_seconds=tmax_seconds,
                    tmax_offset=tmax_offset,
                    deltat=[0.5, 1.0][file_element % 2],
                    kind_id=squirrel.to_kind_id(kind)))

        squirrel.io.backends.virtual.add_nuts(all_nuts)

        db_file_path = os.path.join(self.tempdir, 'squirrel_benchmark_chop.db')
        if os.path.exists(db_file_path):
            os.unlink(db_file_path)

        filldb = not os.path.exists(db_file_path)

        database = squirrel.Database(db_file_path)

        bench = common.Benchmark('test_chop (%i x %i)' % (nt, ne))

        if filldb:
            with bench.run('init db'):
                database.dig(all_nuts)

        with bench.run('undig all'):
            it = 0
            for fn, nuts in database.undig_all():
                it += 1

            assert it == nt

        with bench.run('add to squirrel'):
            sq = squirrel.Squirrel(database=database)
            sq.add(
                ('virtual:test_chop_%i' % it for it in range(nt)),
                check=False)

        with bench.run('get time span'):
            tmin, tmax = sq.get_time_span()

        with bench.run('get codes'):
            for codes in sq.iter_codes():
                pass

        with bench.run('get total size'):
            sq.get_total_size()

        expect = []
        nwin = 100
        tinc = 24 * 3600.

        with bench.run('undig span naiv'):
            for iwin in range(nwin):
                tmin = tmin_g + iwin * tinc
                tmax = tmin_g + (iwin+1) * tinc

                expect.append(
                    len(list(sq.iter_nuts(
                        kind, tmin=tmin, tmax=tmax, naiv=True))))
                assert expect[-1] >= 10

        with bench.run('undig span'):
            for iwin in range(nwin):
                tmin = tmin_g + iwin * tinc
                tmax = tmin_g + (iwin+1) * tinc

                assert len(sq.get_nuts(
                    kind, tmin=tmin, tmax=tmax)) == expect[iwin]

        with bench.run('get deltat span'):
            assert sq.get_deltat_span(kind) == (0.5, 1.0)

        with bench.run('get coverage'):
            for codes in sq.get_codes():
                sq.get_coverage(kind, None, None, codes, limit=10)

        sq._conn.execute(sq._sql('DROP INDEX %(db)s.%(coverage)s_time'))
        with bench.run('get coverage (no index)'):
            for codes in sq.get_codes():
                sq.get_coverage(kind, None, None, codes, limit=10)

        return bench

    def test_coverage(self):

        def val_at(ref, t):
            cr_last = 0
            for tr, cr in ref:
                if t < tr:
                    return cr_last

                cr_last = cr

            return cr_last

        def assert_coverage_equal(ref, part):
            for tp, cp in part:
                assert val_at(ref, tp) == cp

        def iter_qtranges():
            for qtmin in [None, -1., 0., 1., 5., 10., 15., 20., 25., 30.]:
                for qtmax in [None, -1., 0., 1., 5., 10., 15., 20., 25., 30.]:
                    if None in (qtmin, qtmax) or qtmin <= qtmax:
                        yield qtmin, qtmax

        tempdir = os.path.join(self.tempdir, 'test_coverage')
        try:
            for deci in [1, 2]:
                nsamples = 1000
                trs = []
                for sta, tmin1, tmin2 in [
                            ('a', 0.0, 0.0),
                            ('b', 0.0, 5.0),
                            ('c', 0.0, 10.0),
                            ('d', 0.0, 15.0)]:

                    tr1 = trace.Trace(
                        station=sta,
                        tmin=tmin1,
                        deltat=0.01,
                        ydata=num.zeros(nsamples, dtype=num.int32))

                    tr2 = trace.Trace(
                        station=sta,
                        tmin=tmin2,
                        deltat=0.01*deci,
                        ydata=num.zeros(nsamples//deci, dtype=num.int32))

                    trs.append(tr1)
                    trs.append(tr2)

                fns = io.save(
                    trs,
                    op.join(tempdir, 'data.mseed'),
                    check_overlaps=False)

                database = squirrel.Database()
                sq = squirrel.Squirrel(database=database)
                sq.add(fns)
                changes_ref = {}
                for qtmin, qtmax in iter_qtranges():

                    coverages = sq.get_coverage(
                        'waveform', tmin=qtmin, tmax=qtmax)

                    if deci == 1:
                        assert len(coverages) == 4

                    if deci == 2:
                        assert len(coverages) == 8

                    for coverage in coverages:
                        k = coverage.codes, coverage.deltat
                        changes = coverage.changes
                        if k not in changes_ref:
                            changes_ref[k] = changes
                        else:
                            assert_coverage_equal(changes_ref[k], changes)

                # sq.snuffle()

        finally:
            shutil.rmtree(tempdir)

    def test_long_cover(self):

        tmin = util.str_to_time('2021-01-01 00:00:00')

        d = 24*60*60.
        deltat = 1./200.
        n = int(round(d / deltat))
        tempdir = os.path.join(self.tempdir, 'test_long_coverage')

        for iday in range(3):
            ydata = num.random.randint(-2**31, 2**31-1, n, dtype=num.int32)
            tr = trace.Trace(
                '', 'STA', '', 'HHZ',
                tmin=tmin + iday * d,
                deltat=deltat,
                ydata=ydata)

            io.save(tr, os.path.join(tempdir, 'data-%03i.mseed' % iday))

        database = squirrel.Database()
        sq = squirrel.Squirrel(database=database)
        sq.add(tempdir)

        assert 2 == len(
            sq.get_coverage(
                'waveform', tmin, tmin + 3*d)[0].changes)

    def test_loading(self):
        self.run_loading()

    def benchmark_loading(self):
        bench = self.run_loading(hours=24, with_pile=False)
        print(bench)

    def run_loading(self, with_pile=False, hours=1):
        dir = op.join(self.tempdir, 'testdataset_d_%i' % hours)

        if not os.path.exists(dir):
            common.make_dataset(dir, tinc=36., tlen=hours*common.H)

        fns = sorted(util.select_files([dir], show_progress=False))

        bench = common.Benchmark('test_loading (%i files)' % len(fns))
        if with_pile:
            cachedirname = tempfile.mkdtemp('testcache', dir=self.tempdir)

            with bench.run('pile, initial scan'):
                pile.make_pile(
                    fns, fileformat='detect', cachedirname=cachedirname,
                    show_progress=False)

            with bench.run('pile, rescan'):
                pile.make_pile(
                    fns, fileformat='detect', cachedirname=cachedirname,
                    show_progress=False)

            shutil.rmtree(cachedirname)

        with bench.run('plain load baseline'):
            ii = 0
            for fn in fns:
                for tr in io.load(fn, getdata=False):
                    ii += 1

        with bench.run('iload, without db'):
            ii = 0
            for nut in squirrel.iload(fns, content=[]):
                ii += 1

            assert ii == len(fns)

        db_file_path = op.join(self.tempdir, 'db.squirrel')
        if os.path.exists(db_file_path):
            os.unlink(db_file_path)
        database = squirrel.Database(db_file_path)
        s = database.get_stats()
        assert s.nfiles == 0
        assert s.nnuts == 0
        assert s.kinds == []

        with bench.run('iload, with db'):
            ii = 0
            for nut in squirrel.iload(fns, content=[], database=database):
                ii += 1

            assert ii == len(fns)

        with bench.run('iload, rescan'):
            ii = 0
            for nut in squirrel.iload(fns, content=[], database=database):
                ii += 1

            assert ii == len(fns)

        with bench.run('iload, rescan, no mtime check'):
            ii = 0
            for nut in squirrel.iload(fns, content=[], database=database,
                                      check=False):
                ii += 1

            assert ii == len(fns)

        sel = database.new_selection(fns)

        with bench.run('iload, skip unchanged, files are new'):
            ii = 0
            for nut in squirrel.iload(sel, content=[],
                                      skip_unchanged=True, check=True):
                ii += 1

            assert ii == len(fns)

        sel._set_file_states_known()

        with bench.run('iload, skip unchanged, files are known and unchanged'):
            ii = 0
            for nut in squirrel.iload(sel, content=[],
                                      skip_unchanged=True, check=True):
                ii += 1

            assert ii == 0

        with bench.run('iload, skip unchanged (no check), '
                       'files are known and unchanged'):
            ii = 0
            for nut in squirrel.iload(sel, content=[],
                                      skip_unchanged=True, check=False):
                ii += 1

            assert ii == 0

        del sel

        with bench.run('undig'):
            ii = 0
            for fn, nuts in database.undig_many(fns):
                ii += 1

            assert ii == len(fns)

        with bench.run('stats'):
            s = database.get_stats()
            assert s.nfiles == len(fns)
            assert s.nnuts == len(fns)
            assert s.kinds == ['waveform']
            for kind in s.kinds:
                for codes in s.codes:
                    assert s.counts[kind][codes] == len(fns) // 30

        with bench.run('add to squirrel'):
            sq = squirrel.Squirrel(database=database)
            sq.add(fns)

        with bench.run('stats'):
            s = sq.get_stats()
            assert s.nfiles == len(fns)
            assert s.nnuts == len(fns)
            assert s.kinds == ['waveform']
            for kind in s.kinds:
                for codes in s.codes:
                    assert s.counts[kind][codes] == len(fns) // 30

        with bench.run('get deltat span'):
            sq.get_deltat_span('waveform')

        return bench

    def test_sub_squirrel(self):

        try:
            tempdir = os.path.join(self.tempdir, 'test_sub_squirrel')

            def make_files(vers, name):
                tr = trace.Trace(
                    tmin=float(vers),
                    deltat=1.0,
                    ydata=num.array([vers, vers], dtype=num.int32))

                return io.save(tr, op.join(tempdir, '%s.mseed' % name))

            database = squirrel.Database()
            sq = squirrel.Squirrel(database=database)

            fns1 = make_files(0, '1')
            fns2 = make_files(0, '2')
            fns3 = make_files(0, '3')

            sq.add(fns1)

            sq2 = squirrel.Squirrel(database=sq.get_database())
            sq2.add(fns2)
            del sq2

            sq.add(fns3)

        finally:
            shutil.rmtree(tempdir)

    @common.require_internet
    def test_fdsn_source(self):
        tmin = util.str_to_time('2018-01-01 00:00:00')
        tmax = util.str_to_time('2018-01-01 02:00:00')
        database = squirrel.Database()
        try:
            sq = squirrel.Squirrel(database=database)
            tempdir = os.path.join(self.tempdir, 'test_fdsn_source')
            sq.add_fdsn(
                'geofon',
                dict(
                    network='GE',
                    station='EIL,BOAB,PUL',
                    channel='LH?'),
                cache_path=tempdir)

            sq.update(tmin=tmin, tmax=tmax)

            assert len(sq.get_stations()) == 3
            assert len(sq.get_channels()) == 9

            sq.update_waveform_promises(tmin=tmin, tmax=tmax)
            for trs in sq.pile.chopper(
                    tmin=tmin, tmax=tmax, include_last=True,
                    trace_selector=lambda tr: tr.station == 'EIL'):

                assert len(trs) == 3
                for tr in trs:
                    assert tr.tmin == tmin
                    assert tr.tmax == tmax

            nnuts = sq.get_nnuts()

            sq = squirrel.Squirrel(database=database)
            sq.add_fdsn(
                'geofon',
                dict(
                    network='GE',
                    station='EIL,BOAB,PUL',
                    channel='LH?'),
                expires=1000.,
                cache_path=tempdir)

            assert sq.get_nnuts() == nnuts
            sq.update(tmin=tmin, tmax=tmax)
            assert sq.get_nnuts() == nnuts

            sq = squirrel.Squirrel(database=database)
            sq.add_fdsn(
                'geofon',
                dict(
                    network='GE',
                    station='EIL,BOAB,PUL',
                    channel='LH?'),
                expires=0.,
                cache_path=tempdir)

            assert sq.get_nnuts() == nnuts
            sq.update(tmin=tmin, tmax=tmax)
            assert sq.get_nnuts() == nnuts

        finally:
            shutil.rmtree(tempdir)

    @common.require_internet
    def test_restitution(self):
        # 1994 Bolivia earthquake
        tmin = util.str_to_time('1994-06-09 00:00:00')
        tmax = util.str_to_time('1994-06-09 03:00:00')
        database = squirrel.Database()
        try:
            sq = squirrel.Squirrel(database=database)
            tempdir = os.path.join(self.tempdir, 'test_restitution')
            sq.add_fdsn(
                'bgr',
                dict(
                    network='GR',
                    station='BFO',
                    channel='LH?'),
                cache_path=tempdir)

            sq.update(tmin=tmin, tmax=tmax)
            sq.update_waveform_promises(tmin=tmin, tmax=tmax)
            sq.update_responses()

            sq.add_operator(squirrel.Restitution(quantity='displacement'))
            sq.add_operator(squirrel.Restitution(quantity='velocity'))
            sq.add_operator(squirrel.Restitution(quantity='acceleration'))
            sq.update_operator_mappings()

            traces = []
            for extra in ['Rd', 'Rv', 'Ra']:
                traces.extend(
                    sq.get_waveforms(
                        tmin=tmin, tmax=tmax,
                        codes=('GR', 'BFO', '', 'LHZ', extra),
                        operator_params=squirrel.RestitutionParameters(
                            frequency_min=0.002,
                            frequency_max=10.0)))

            traces.extend(
                sq.get_waveforms(
                    tmin=tmin, tmax=tmax,
                    codes=('GR', 'BFO', '', 'LHZ', '')))

            # trace.snuffle(traces)

        finally:
            shutil.rmtree(tempdir)

    @common.require_internet
    def test_promises(self):
        # 1994 Bolivia earthquake
        tmin = util.str_to_time('1994-06-09 00:00:00')
        tmax = util.str_to_time('1994-06-09 03:00:00')
        database = squirrel.Database()
        tempdir = os.path.join(self.tempdir, 'test_promises')
        try:
            def make_squirrel():
                sq = squirrel.Squirrel(database=database)
                sq.add_fdsn(
                    'bgr',
                    dict(
                        network='GR',
                        station='BFO',
                        channel='LH?'),
                    cache_path=tempdir)
                return sq

            sq = make_squirrel()
            sq.update(tmin=tmin, tmax=tmax)
            sq.update_waveform_promises(tmin=tmin, tmax=tmax)
            nuts = sq.get_nuts(kind='waveform_promise')
            assert len(nuts) == 3
            del sq

            sq = make_squirrel()
            nuts = sq.get_nuts(kind='waveform_promise')
            assert len(nuts) == 3
            sq.remove_waveform_promises(from_database='selection')
            nuts = sq.get_nuts(kind='waveform_promise')
            assert len(nuts) == 0
            del sq

            sq = make_squirrel()
            nuts = sq.get_nuts(kind='waveform_promise')
            assert len(nuts) == 3
            sq.remove_waveform_promises(from_database='global')
            nuts = sq.get_nuts(kind='waveform_promise')
            assert len(nuts) == 0
            del sq

            sq = make_squirrel()
            nuts = sq.get_nuts(kind='waveform_promise')
            assert len(nuts) == 0
            del sq

        finally:
            shutil.rmtree(tempdir)

    def test_stations(self):
        fpath = common.test_data_file('test1.stationxml')
        database = squirrel.Database()
        sq = squirrel.Squirrel(database=database)
        sq.add(fpath)
        stations = sq.get_stations()
        assert len(stations) == 3
        stations = sq.get_stations(model='pyrocko')
        assert len(stations) == 2
        stations = sq.get_stations(
            model='pyrocko', codes='GE.EIL.*')
        assert len(stations) == 2
        stations = sq.get_stations(
            model='pyrocko', codes='GE.EIL.')
        assert len(stations) == 2
        stations = sq.get_stations(
            model='pyrocko', codes=squirrel.CodesNSL('GE.EIL.'))
        assert len(stations) == 2
        stations = sq.get_stations(
            model='pyrocko', codes=squirrel.CodesNSLCE('GE.EIL..BHZ'))
        assert len(stations) == 2
        stations = sq.get_stations(model='stationxml')
        assert len(stations) == 3

    def test_responses(self):
        fpath = common.test_data_file('test1.stationxml')
        database = squirrel.Database()
        sq = squirrel.Squirrel(database=database)
        sq.add(fpath)
        responses = sq.get_responses()
        assert len(responses) == 12

        responses = sq.get_responses(model='stationxml')
        assert len(responses) == 12

    def test_events(self):
        fpath = common.test_data_file('events2.txt')
        database = squirrel.Database()
        sq = squirrel.Squirrel(database=database)
        sq.add(fpath)
        events = sq.get_events()
        events2 = pmodel.load_events(fpath)
        assert len(events) == len(events2)

    @common.require_internet
    def test_catalog_source(self):
        tmin = util.str_to_time('2017-01-01 00:00:00')
        tmax = util.str_to_time('2017-01-03 00:00:00')
        tmax2 = util.str_to_time('2017-01-06 00:00:00')

        database = squirrel.Database()
        try:
            tempdir = os.path.join(self.tempdir, 'test_catalog')
            sq = squirrel.Squirrel(database=database)
            sq.add_catalog(
                'geofon', cache_path=tempdir, query_args={'magmin': 6.0})
            sq.update(tmin=tmin, tmax=tmax)
            assert len(sq.get_events()) == 1
            sq.update(tmin=tmin, tmax=tmax2)
            assert len(sq.get_events()) == 3

        finally:
            shutil.rmtree(tempdir)

    def test_fake_pile(self):
        database = squirrel.Database()
        sq = squirrel.Squirrel(database=database)
        assert len(list(sq.pile.chopper())) == 0
        assert sq.pile.tmin is None
        assert sq.pile.tmax is None
        assert sq.pile.get_tmin() is None
        assert sq.pile.get_tmax() is None
        assert not sq.pile.is_relevant(0., 1.)
        assert sq.pile.is_empty()

        fpath = common.test_data_file('test1.mseed')
        sq.pile.load_files(fpath)

        assert not sq.pile.is_empty()

        assert sq.pile.tmin is not None
        assert sq.pile.tmax is not None
        assert sq.pile.get_tmin() is not None
        assert sq.pile.get_tmax() is not None

        assert list(sq.pile.networks) == ['']
        assert list(sq.pile.stations) == ['LGG01']
        assert list(sq.pile.locations) == ['']
        assert list(sq.pile.channels) == ['BHZ']

        assert len(list(sq.pile.chopper())[0]) == 1
        assert len(list(sq.pile.chopper(want_incomplete=False))[0]) == 1
        assert len(list(sq.pile.chopper(load_data=False))[0]) == 1

        tmin, tmax = sq.pile.tmin, sq.pile.tmax
        assert len(list(sq.pile.chopper(
            tmin=tmin-10., tmax=tmax+10, want_incomplete=False))[0]) == 0
        assert len(list(sq.pile.chopper(
            tmin=0., tmax=10.))) == 0
        assert len(list(sq.pile.chopper(
            tmin=tmin-10., tmax=tmax+10, want_incomplete=False))[0]) == 0
        assert len(list(sq.pile.chopper(
            tmin=tmin+10., tmax=tmax-10, want_incomplete=False))[0]) == 1

        # assert len(list(sq.pile.iter_traces())) == 1
        sq.pile.reload_modified()

        assert list(sq.pile.gather_keys(
            gather=lambda tr: tr.station,
            selector=lambda tr: tr.channel == 'BHZ')) == ['LGG01']

    def make_many_files(
            self, nfiles, nsamples, networks, stations, channels, tmin):

        def rc(ll, i):
            return ll[(i // 3) % len(ll)]

        traces = []
        deltat = 1.0
        for i in range(nfiles):
            ctmin = tmin+i*nsamples*deltat

            data = num.ones(nsamples)
            traces.append(
                trace.Trace(
                    rc(networks, i), rc(stations, i), '', rc(channels, i),
                    ctmin, None, deltat, data))

        datadir = tempfile.mkdtemp(dir=self.tempdir)
        fnt = os.path.join(
            datadir,
            'data',
            '%(network)s-%(station)s-%(location)s-%(channel)s-%(tmin)s.mseed')

        io.save(traces, fnt, format='mseed')
        return datadir

    def test_chopper(self):

        nfiles = 200
        nsamples = 1000

        stations = ['S%02i' % i for i in range(10)]
        channels = ['C%01i' % i for i in range(3)]
        networks = ['xx']

        tmin = 1234567890
        datadir = self.make_many_files(
            nfiles, nsamples, networks, stations, channels, tmin)

        squirrel.init_environment(datadir)

        try:
            work = [
                (ijob, datadir, nfiles, nsamples, tmin, (None, 1))
                for ijob in range(12)]

            tstart = time.time()
            for ijob in parimap(do_chopper, work, nprocs=4):
                logger.info('Done with job %i after %i s.' % (
                    ijob, time.time() - tstart))

        finally:
            shutil.rmtree(datadir)

    def test_chopper_single(self):

        nfiles = 100
        nsamples = 100

        stations = ['S%02i' % i for i in range(10)]
        channels = ['C%01i' % i for i in range(3)]
        networks = ['xx']

        tmin = 1234567890.
        datadir = self.make_many_files(
            nfiles, nsamples, networks, stations, channels, tmin)

        squirrel.init_environment(datadir)

        try:
            for (grouping, mult) in [
                    (None, 1),
                    (squirrel.NetworkGrouping(), 1),
                    (squirrel.StationGrouping(), 10),
                    (squirrel.ChannelGrouping(), 30),
                    (squirrel.SensorGrouping(), 10)]:

                do_chopper(
                    (0, datadir, nfiles, nsamples, tmin, (grouping, mult)))

        finally:
            shutil.rmtree(datadir)

    def test_add_waveforms(self):
        traces = []

        ntraces = 10
        nsamples = 3600
        deltat = 1.0
        tmin = util.str_to_time('2020-01-01 00:00:00')
        for itrace in range(ntraces):
            ctmin = tmin+itrace*nsamples*deltat
            data = num.ones(nsamples)
            traces.append(
                trace.Trace(
                    'N', 'STA', '', 'Z',
                    tmin=ctmin, deltat=deltat, ydata=data))

        tmax = traces[-1].tmax

        database = squirrel.Database()
        sq = squirrel.Squirrel(database=database)
        handle = sq.add_volatile_waveforms(traces)
        for tr in sq.get_waveforms(include_last=True):
            assert tr.tmin == tmin and tr.tmax == tmax

        sq.remove(handle)
        assert len(sq.get_waveforms(tmin=tmin, tmax=tmax)) == 0


def do_chopper(params):
    ijob, datadir, nfiles, nsamples, tmin, (grouping, mult) = params

    sq = squirrel.Squirrel(datadir, persistent='bla')
    sq.add(os.path.join(datadir, 'data'))

    ntr = 0
    for tr in sq.get_waveforms(uncut=True):
        ntr += 1
        assert tr.data_len() == nsamples

    assert ntr == nfiles

    trs = sq.get_waveforms(tmin=tmin+10, tmax=tmin+200)
    for tr in trs:
        assert num.all(tr.get_ydata() == num.ones(190))

    trs = sq.get_waveforms(tmin=tmin-100, tmax=tmin+100)
    for tr in trs:
        assert len(tr.get_ydata()) == 100

    codes = sq.get_codes(kind='waveform')

    s = 0
    tinc = 122.
    sq_tmin, sq_tmax = sq.get_time_span('waveform')
    nbatches = 0
    for batch in sq.chopper_waveforms(
            tmin=None,
            tmax=sq_tmax+1.,
            tinc=tinc,
            degap=False,
            codes=codes,
            grouping=grouping):

        for tr in batch.traces:
            s += num.sum(tr.ydata)

        nbatches += 1

    assert nbatches == int(math.ceil(nsamples * nfiles / tinc)) * mult

    assert int(round(s)) == nfiles*nsamples

    database = sq.get_database()
    del sq

    from pyrocko.squirrel import database as dbm
    dbm.close_database(database)

    return ijob


if __name__ == '__main__':
    unittest.main()
