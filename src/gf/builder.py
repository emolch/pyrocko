# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Common base for Green's function store builders (:py:mod:`~pyrocko.fomosto`).
'''

import os
import signal
import errno
from os.path import join as pjoin
import numpy as num

from collections import defaultdict
from pyrocko.parimap import parimap
from pyrocko import util
from . import store


def int_arr(*args):
    return num.array(args, dtype=int)


class Interrupted(store.StoreError):
    def __str__(self):
        return 'Interrupted.'


g_builders = {}


def work_block(args):
    # previously this was a implemented as a classmethod __work_block but it
    # caused problems on Conda Python 3.8 on OSX.
    try:
        cls, store_dir, step, iblock, shared, force = args
        if (store_dir, step) not in g_builders:
            g_builders[store_dir, step] = cls(
                store_dir, step, shared, force=force)

        builder = g_builders[store_dir, step]
        builder.work_block(iblock)
    except KeyboardInterrupt:
        raise Interrupted()
    except IOError as e:
        if e.errno == errno.EINTR:
            raise Interrupted()
        else:
            raise

    return store_dir, step, iblock


def cleanup():
    for k in list(g_builders):
        g_builders[k].cleanup()
        del g_builders[k]


class Builder(object):
    nsteps = 1

    def __init__(self, gf_config, step, block_size=None, force=False):
        if block_size is None:
            if len(gf_config.ns) == 3:
                block_size = (10, 1, 10)
            elif len(gf_config.ns) == 2:
                block_size = (1, 10)
            else:
                assert False

        self.step = step
        self.force = force
        self.gf_config = gf_config
        self.warnings = defaultdict(int)
        self._block_size = int_arr(*block_size)

    def cleanup(self):
        pass

    @property
    def nblocks(self):
        return num.prod(self.block_dims)

    @property
    def block_dims(self):
        return (self.gf_config.ns-1) // self._block_size + 1

    def warn(self, msg):
        self.warnings[msg] += 1

    def log_warnings(self, index, logger):
        for warning, noccur in self.warnings.items():
            msg = 'block {}: ' + warning
            logger.warning(msg.format(index, noccur))

        self.warnings = defaultdict(int)

    def all_block_indices(self):
        return num.arange(self.nblocks)

    def get_block(self, index):
        dims = self.block_dims
        iblock = num.unravel_index(index, dims)
        ibegins = iblock * self._block_size
        iends = num.minimum(ibegins + self._block_size, self.gf_config.ns)
        return ibegins, iends

    def get_block_extents(self, index):
        ibegins, iends = self.get_block(index)
        begins = self.gf_config.mins + ibegins * self.gf_config.deltas
        ends = self.gf_config.mins + (iends-1) * self.gf_config.deltas
        return begins, ends, iends - ibegins

    @classmethod
    def build(cls, store_dir, force=False, nworkers=None, continue_=False,
              step=None, iblock=None):
        if step is None:
            steps = list(range(cls.nsteps))
        else:
            steps = [step]

        if iblock is not None and step is None and cls.nsteps != 1:
            raise store.StoreError('--step option must be given')

        done = set()
        status_fn = pjoin(store_dir, '.status')

        if not continue_ and iblock in (None, -1) and step in (None, 0):
            store.Store.create_dependants(store_dir, force)

        if iblock is None:
            if not continue_:
                with open(status_fn, 'w') as status:
                    pass
            else:
                if iblock is None:
                    try:
                        with open(status_fn, 'r') as status:
                            for line in status:
                                done.add(tuple(int(x) for x in line.split()))
                    except IOError:
                        raise store.StoreError('nothing to continue')

        shared = {}
        for step in steps:
            builder = cls(store_dir, step, shared, force=force)
            if not (0 <= step < builder.nsteps):
                raise store.StoreError('invalid step: %i' % (step+1))

            if iblock in (None, -1):
                iblocks = [x for x in builder.all_block_indices()
                           if (step, x) not in done]
            else:
                if not (0 <= iblock < builder.nblocks):
                    raise store.StoreError(
                        'invalid block index %i' % (iblock+1))

                iblocks = [iblock]

            if iblock == -1:
                for i in iblocks:
                    c = ['fomosto', 'build']
                    if not os.path.samefile(store_dir, '.'):
                        c.append("'%s'" % store_dir)

                    if builder.nsteps != 1:
                        c.append('--step=%i' % (step+1))

                    c.append('--block=%i' % (i+1))

                    print(' '.join(c))

                return

            builder.cleanup()
            del builder

            original = signal.signal(signal.SIGINT, signal.SIG_IGN)
            try:
                for x in parimap(
                        work_block,
                        [(cls, store_dir, step, i, shared, force)
                         for i in iblocks],
                        nprocs=nworkers,
                        eprintignore=(Interrupted, store.StoreError),
                        startup=util.setup_logging,
                        startup_args=util.subprocess_setup_logging_args(),
                        cleanup=cleanup):

                    store_dir, step, i = x
                    with open(status_fn, 'a') as status:
                        status.write('%i %i\n' % (step, i))

            finally:
                signal.signal(signal.SIGINT, original)

        os.remove(status_fn)


__all__ = ['Builder']
