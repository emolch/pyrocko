# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, division

import numpy as num
import logging
import os
import math
import signal

from pyrocko import trace, cake, gf
from pyrocko.ahfullgreen import add_seismogram, Impulse, Gauss
from pyrocko.moment_tensor import MomentTensor, symmat6

km = 1000.

guts_prefix = 'pf'

logger = logging.getLogger('pyrocko.fomosto.ahfullgreen')

# how to call the programs
program_bins = {
    'ahfullgreen': 'ahfullgreen',
}

components = 'r t z'.split()


def example_model():
    material = cake.Material(vp=3000., vs=1000., rho=3000., qp=200., qs=100.)
    layer = cake.HomogeneousLayer(
        ztop=0., zbot=30*km, m=material, name='fullspace')
    mod = cake.LayeredModel()
    mod.append(layer)
    return mod


class AhfullgreenError(gf.store.StoreError):
    pass


def make_traces(material, source_mech, deltat, norths, easts,
                source_depth, receiver_depth):

    if isinstance(source_mech, MomentTensor):
        m6 = source_mech.m6()
        f = (0., 0., 0.)
    elif isinstance(source_mech, tuple):
        m6 = (0., 0., 0., 0., 0., 0.)
        f = source_mech

    npad = 120

    traces = []
    for i_distance, (north, east) in enumerate(zip(norths, easts)):
        d3d = math.sqrt(
            north**2 + east**2 + (receiver_depth - source_depth)**2)

        tmin = (math.floor(d3d / material.vp / deltat) - npad) * deltat
        tmax = (math.ceil(d3d / material.vs / deltat) + npad) * deltat
        ns = int(round((tmax - tmin) / deltat))

        outx = num.zeros(ns)
        outy = num.zeros(ns)
        outz = num.zeros(ns)

        x = (north, east, receiver_depth-source_depth)

        add_seismogram(
            material.vp, material.vs, material.rho, material.qp, material.qs,
            x, f, m6, 'displacement',
            deltat, tmin, outx, outy, outz,
            stf=Gauss(tau=1.))

        for i_comp, o in enumerate((outx, outy, outz)):
            comp = components[i_comp]
            tr = trace.Trace('', '%04i' % i_distance, '', comp,
                             tmin=tmin, ydata=o, deltat=deltat,
                             meta=dict(
                                 distance=math.sqrt(north**2 + east**2),
                                 azimuth=0.))

            traces.append(tr)

    return traces


class AhfullGFBuilder(gf.builder.Builder):
    def __init__(self, store_dir, step, shared, block_size=None, force=False):

        self.store = gf.store.Store(store_dir, 'w')

        if block_size is None:
            block_size = (1, 1, 2000)

        if len(self.store.config.ns) == 2:
            block_size = block_size[1:]

        gf.builder.Builder.__init__(
            self, self.store.config, step, block_size=block_size, force=force)

    def cleanup(self):
        self.store.close()

    def work_block(self, index):
        if len(self.store.config.ns) == 2:
            (sz, firstx), (sz, lastx), (ns, nx) = \
                self.get_block_extents(index)

            rz = self.store.config.receiver_depth
        else:
            (rz, sz, firstx), (rz, sz, lastx), (nr, ns, nx) = \
                self.get_block_extents(index)

        logger.info('Starting block %i / %i' %
                    (index+1, self.nblocks))

        dx = self.gf_config.distance_delta

        distances = num.linspace(firstx, firstx + (nx-1)*dx, nx).tolist()

        mmt1 = (MomentTensor(m=symmat6(1, 0, 0, 1, 0, 0)),
                {'r': (0, +1), 't': (3, +1), 'z': (5, +1)})
        mmt2 = (MomentTensor(m=symmat6(0, 0, 0, 0, 1, 1)),
                {'r': (1, +1), 't': (4, +1), 'z': (6, +1)})
        mmt3 = (MomentTensor(m=symmat6(0, 0, 1, 0, 0, 0)),
                {'r': (2, +1), 'z': (7, +1)})
        mmt4 = (MomentTensor(m=symmat6(0, 1, 0, 0, 0, 0)),
                {'r': (8, +1), 'z': (9, +1)})
        mmt0 = (MomentTensor(m=symmat6(1, 1, 1, 0, 0, 0)),
                {'r': (0, +1), 'z': (1, +1)})

        component_scheme = self.store.config.component_scheme

        if component_scheme == 'elastic8':
            gfmapping = [mmt1, mmt2, mmt3]

        elif component_scheme == 'elastic10':
            gfmapping = [mmt1, mmt2, mmt3, mmt4]

        elif component_scheme == 'elastic2':
            gfmapping = [mmt0]

        elif component_scheme == 'elastic5':
            gfmapping = [
                ((1., 1., 0.), {'r': (1, +1), 'z': (4, +1), 't': (2, +1)}),
                ((0., 0., 1.), {'r': (0, +1), 'z': (3, +1)})]

        else:
            raise gf.UnavailableScheme(
                'fomosto backend "ahfullgreen" cannot handle component scheme '
                '"%s"' % component_scheme)

        for source_mech, gfmap in gfmapping:

            rawtraces = make_traces(
                self.store.config.earthmodel_1d.require_homogeneous(),
                source_mech, 1.0/self.store.config.sample_rate,
                distances, num.zeros_like(distances), sz, rz)

            interrupted = []

            def signal_handler(signum, frame):
                interrupted.append(True)

            original = signal.signal(signal.SIGINT, signal_handler)
            self.store.lock()
            duplicate_inserts = 0
            try:
                for itr, tr in enumerate(rawtraces):
                    if tr.channel not in gfmap:
                        logger.debug('%s not in gfmap' % tr.channel)
                        continue

                    x = tr.meta['distance']
                    if x > firstx + (nx-1)*dx:
                        logger.error("x out of range")
                        continue

                    ig, factor = gfmap[tr.channel]

                    if len(self.store.config.ns) == 2:
                        args = (sz, x, ig)
                    else:
                        args = (rz, sz, x, ig)

                    tr = tr.snap()

                    gf_tr = gf.store.GFTrace.from_trace(tr)
                    gf_tr.data *= factor

                    try:
                        self.store.put(args, gf_tr)
                    except gf.store.DuplicateInsert:
                        duplicate_inserts += 1

            finally:
                if duplicate_inserts:
                    logger.warn('%i insertions skipped (duplicates)' %
                                duplicate_inserts)

                self.store.unlock()
                signal.signal(signal.SIGINT, original)

            if interrupted:
                raise KeyboardInterrupt()

        logger.info('Done with block %i / %i' %
                    (index+1, self.nblocks))


def init(store_dir, variant):
    assert variant is None

    modelling_code_id = 'ahfullgreen'

    store_id = os.path.basename(os.path.realpath(store_dir))

    config = gf.meta.ConfigTypeA(
        id=store_id,
        ncomponents=10,
        sample_rate=20.,
        receiver_depth=0*km,
        source_depth_min=1*km,
        source_depth_max=10*km,
        source_depth_delta=1*km,
        distance_min=1*km,
        distance_max=20*km,
        distance_delta=1*km,
        earthmodel_1d=example_model(),
        modelling_code_id=modelling_code_id,
        tabulated_phases=[
            gf.meta.TPDef(
                id='anyP',
                definition='P,p,\\P,\\p'),
            gf.meta.TPDef(
                id='anyS',
                definition='S,s,\\S,\\s')])

    config.validate()
    return gf.store.Store.create_editables(
        store_dir, config=config)


def build(store_dir, force=False, nworkers=None, continue_=False, step=None,
          iblock=None):

    return AhfullGFBuilder.build(
        store_dir, force=force, nworkers=nworkers, continue_=continue_,
        step=step, iblock=iblock)
