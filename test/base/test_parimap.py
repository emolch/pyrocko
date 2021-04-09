from __future__ import division, print_function, absolute_import

import random
import time
import tempfile
import os
try:
    import fcntl
except ImportError:
    fcntl = None
import unittest
import errno
from pyrocko import util
from pyrocko.parimap import parimap


class Crash(Exception):
    pass


def imapemulation(function, *iterables):
    iterables = list(map(iter, iterables))
    while True:
        args = []
        for it in iterables:
            try:
                args.append(next(it))
            except StopIteration:
                return

        if function is None:
            yield tuple(args)
        else:
            yield function(*args)


def work_parimap(x, y, pshared):
    icrash = pshared['icrash']

    if x == icrash:
        raise Crash(str((x, y)))

    a = random.random()
    if a > 0.5:
        time.sleep((a*0.01)**2)

    return x+y


def work_locks(x, pshared):
    fn = pshared['fn']
    assert os.path.exists(fn)
    with open(fn, 'a+') as f:
        while True:
            try:
                fcntl.lockf(f, fcntl.LOCK_EX)
                break
            except IOError as e:
                if e.errno == errno.ENOLCK:
                    time.sleep(0.01)
                    pass
                else:
                    raise

        f.seek(0)
        assert '' == f.read()
        f.write('%s' % x)
        f.flush()
        # time.sleep(0.01)
        f.seek(0)
        f.truncate(0)
        fcntl.lockf(f, fcntl.LOCK_UN)


class ParimapTestCase(unittest.TestCase):

    def test_parimap(self):

        # random.seed(0)

        n = 1000

        for i in range(5):
            nprocs = random.randint(1, 10)
            nx = random.randint(0, n)
            ny = random.randint(0, n)
            icrash = random.randint(0, n)

            # print 'testing %i %i %i %i...' % (nprocs, nx, ny, icrash)

            I1 = parimap(
                work_parimap, range(nx), range(ny),
                pshared=dict(icrash=icrash),
                nprocs=nprocs,
                eprintignore=Crash)

            I2 = imapemulation(
                work_parimap, range(nx), range(ny),
                [dict(icrash=icrash)]*n)

            while True:

                exc1, exc2 = None, None
                res1, res2 = None, None
                end1, end2 = None, None
                try:
                    res1 = next(I1)
                except StopIteration:
                    end1 = True
                except Crash as e1:
                    exc1 = e1

                try:
                    res2 = next(I2)
                except StopIteration:
                    end2 = True
                except Crash as e2:
                    exc2 = e2

                assert res1 == res2, str((res1, res2))
                assert type(exc1) == type(exc2)
                assert end1 == end2

                if end1 or end2:
                    break

    @unittest.skipUnless(fcntl, 'fcntl not supported on this platform')
    def test_locks(self):

        fos, fn = tempfile.mkstemp()  # (dir='/try/with/nfs/mounted/dir')
        f = open(fn, 'w')
        f.close()

        for x in parimap(
                work_locks, range(100), pshared={'fn': fn}, nprocs=10,
                eprintignore=()):
            pass

        os.close(fos)
        os.remove(fn)


if __name__ == '__main__':
    util.setup_logging('test_parimap', 'warning')
    unittest.main()
