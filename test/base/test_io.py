from __future__ import division, print_function, absolute_import

import os
import unittest
import numpy as num
import time
import tempfile
import random
from functools import wraps
from random import choice as rc
from os.path import join as pjoin
import shutil

from pyrocko import io, guts
from pyrocko.io import FileLoadError, FileSaveError
from pyrocko.io import mseed, trace, util, suds, quakeml

from .. import common

abc = 'abcdefghijklmnopqrstuvwxyz'
NTF = tempfile.NamedTemporaryFile
op = os.path


def rn(n):
    return ''.join([random.choice(abc) for i in range(n)])


def get_random_trace(nsamples, code='12', deltat=0.01,
                     dtype=num.int32, limit=None):
    assert isinstance(nsamples, int)
    try:
        info = num.iinfo(dtype)
        data = num.random.randint(
            info.min, info.max, size=nsamples).astype(dtype)
    except ValueError:
        info = num.finfo(num.float32)
        data = num.random.uniform(
            info.min + 1., info.max - 1., size=nsamples)\
            .astype(dtype)

    if limit is not None:
        data[data < limit] = -abs(limit)
        data[data > limit] = abs(limit)

    return trace.Trace(
        code, code, code, code,
        ydata=data, deltat=deltat)


def random_traces(nsamples, code='12', deltat=0.01,
                  dtypes=(num.int8, num.int32, num.float32, num.float64),
                  limit=None):
    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            for dtype in dtypes:
                tr = get_random_trace(nsamples, code, deltat, dtype, limit)
                func(*(args + (tr,)), **kwargs)

        return wrapper

    return decorator


class IOTestCase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='pyrocko')

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def testWriteRead(self):
        now = time.time()
        n = 10
        deltat = 0.1

        networks = [rn(2) for i in range(5)]

        traces1 = [
            trace.Trace(
                rc(networks), rn(4), rn(2), rn(3),
                tmin=now+i*deltat*n*2,
                deltat=deltat,
                ydata=num.arange(n, dtype=num.int32),
                mtime=now)

            for i in range(3)]

        for format in ('mseed', 'sac', 'yaff', 'gse2'):
            fns = io.save(
                traces1,
                pjoin(
                    self.tmpdir,
                    '%(network)s_%(station)s_%(location)s_%(channel)s'),
                format=format)

            for fn in fns:
                assert io.detect_format(fn) == format

            traces2 = []
            for fn in fns:
                traces2.extend(io.load(fn, format='detect'))

            for tr in traces1:
                assert tr in traces2, 'failed for format %s' % format

            for fn in fns:
                os.remove(fn)

    def testWriteText(self):
        networks = [rn(2) for i in range(5)]
        deltat = 0.1
        tr = trace.Trace(
            rc(networks), rn(4), rn(2), rn(3),
            tmin=time.time()+deltat,
            deltat=deltat,
            ydata=num.arange(100, dtype=num.int32),
            mtime=time.time())
        io.save(
            tr,
            pjoin(
                self.tmpdir,
                '%(network)s_%(station)s_%(location)s_%(channel)s'),
            format='text')

    def testReadEmpty(self):
        tempfn = os.path.join(self.tmpdir, 'empty')
        with open(tempfn, 'wb'):
            pass

        try:
            list(mseed.iload(tempfn))
        except FileLoadError as e:
            assert str(e).find('No SEED data detected') != -1

    def testReadSac(self):
        fpath = common.test_data_file('test1.sac')
        tr = io.load(fpath, format='sac')[0]
        assert tr.meta['cmpaz'] == 0.0
        assert tr.meta['cmpinc'] == 0.0

    def testReadSac2(self):
        fpath = common.test_data_file('test2.sac')
        tr = io.load(fpath, format='sac')[0]
        assert tr.location == ''

    def testLongCode(self):
        c = '1234567'
        tr = trace.Trace(c, c, c, c, ydata=num.zeros(10))
        try:
            io.save(tr, 'test.mseed')
        except mseed.CodeTooLong as e:
            assert isinstance(e, mseed.CodeTooLong)

    @random_traces(nsamples=1000)
    def testMSeedRecordLength(self, tr):
        for exp in range(8, 20):
            tempfn = os.path.join(self.tmpdir, 'reclen')
            io.save(tr, tempfn, record_length=2**exp)
            assert os.stat(tempfn).st_size / 2**exp % 1. == 0.
            tr2 = io.load(tempfn)[0]
            assert tr == tr2

    @random_traces(nsamples=10000, limit=2**27)
    def testMSeedSTEIM(self, tr):

        fn1 = os.path.join(self.tmpdir, 'steim1')
        fn2 = os.path.join(self.tmpdir, 'steim2')
        fn3 = os.path.join(self.tmpdir, 'steimX')

        io.save(tr, fn1, steim=1)
        tr1 = io.load(fn1)[0]

        io.save(tr, fn2, steim=2)
        tr2 = io.load(fn2)[0]

        assert tr == tr1
        assert tr == tr2
        assert tr1 == tr2

        for steim in (0, 3):
            with self.assertRaises(FileSaveError):
                io.save(tr, fn3, steim=steim)

    def testMSeedDetect(self):
        fpath = common.test_data_file('test2.mseed')
        io.load(fpath, format='detect')

    def testReadSEGY(self):
        fpath = common.test_data_file('test2.segy')
        i = 0
        for tr in io.load(fpath, format='segy'):
            assert tr.meta['orfield_num'] == 1111
            i += 1

        assert i == 24

    def testReadGSE1(self):
        fpath = common.test_data_file('test1.gse1')
        i = 0
        for tr in io.load(fpath, format='detect'):
            i += 1

        assert i == 19

    def testReadSUDS(self):
        fpath = common.test_data_file('test.suds')
        i = 0
        for tr in io.load(fpath, format='detect'):
            i += 1

        assert i == 251

        stations = suds.load_stations(fpath)

        assert len(stations) == 91

    def testReadCSS(self):
        wfpath = common.test_data_file('test_css1.w')  # noqa
        fpath = common.test_data_file('test_css.wfdisc')
        i = 0
        for tr in io.load(fpath, format='css'):
            i += 1

        assert i == 1

    def testReadSeisan(self):
        fpath = common.test_data_file('test.seisan_waveform')
        i = 0
        for tr in io.load(fpath, format='seisan'):
            i += 1

        assert i == 39

    def testReadKan(self):
        fpath = common.test_data_file('01.kan')
        i = 0
        for tr in io.load(fpath, format='kan'):
            i += 1

        assert i == 1

    def testReadGcf(self):
        fpath = common.test_data_file('test.gcf')

        i = 0
        for tr in io.load(fpath, format='gcf'):
            i += 1

        assert i == 1

    def testReadQuakeML(self):

        fpath = common.test_data_file('test.quakeml')
        qml = quakeml.QuakeML.load_xml(filename=fpath)
        events = qml.get_pyrocko_events()
        assert len(events) == 1
        e = events[0]
        assert e.lon == -116.9945
        assert e.lat == 33.986
        assert e.depth == 17300
        assert e.time == util.stt("1999-04-02 17:05:10.500")

        fpath = common.test_data_file('example-catalog.xml')
        qml = quakeml.QuakeML.load_xml(filename=fpath)
        events = qml.get_pyrocko_events()
        assert len(events) == 2
        assert events[0].moment_tensor is not None

        s = qml.dump_xml(ns_ignore=True)
        qml2 = quakeml.QuakeML.load_xml(string=s)
        qml3 = guts.load_xml(string=s)
        assert qml2.dump_xml() == qml3.dump_xml()

    def testReadQuakeML2(self):
        for fn in ['usgs.quakeml', 'isc.quakeml']:
            fpath = common.test_data_file(fn)
            qml = quakeml.QuakeML.load_xml(filename=fpath)
            s = qml.dump_xml()

            qml2 = quakeml.QuakeML.load_xml(string=s)
            s2 = qml2.dump_xml()
            assert len(s) == len(s2)

    def testReadStationXML(self):
        from pyrocko.io import stationxml  # noqa

        fpath = common.test_data_file('test1.stationxml')
        sx = guts.load_xml(filename=fpath)
        s = sx.dump_xml(ns_ignore=True)
        sx2 = guts.load_xml(string=s)
        assert sx.dump_xml() == sx2.dump_xml()


if __name__ == "__main__":
    util.setup_logging('test_io', 'warning')
    unittest.main()
