# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, division

import math
import logging
import os.path as op

import numpy as num

from . import tile
from ..util import get_download_callback
from pyrocko import util

try:
    range = xrange
except NameError:
    pass

logger = logging.getLogger('pyrocko.dataset.topo.dataset')


class TiledGlobalDataset(object):

    def __init__(self, name, nx, ny, ntx, nty, dtype, data_dir=None,
                 citation=None, region=None):

        # dataset geometry (including overlap/endpoints)
        self.nx = int(nx)
        self.ny = int(ny)
        self.xmin = -180.
        self.xmax = 180.
        self.ymin = -90.
        self.ymax = 90.
        self.dx = (self.xmax-self.xmin) / (self.nx - 1)
        self.dy = (self.ymax-self.ymin) / (self.ny - 1)

        # tile geometry (including overlap)
        self.ntx = int(ntx)
        self.nty = int(nty)
        self.stx = (self.ntx - 1) * self.dx
        self.sty = (self.nty - 1) * self.dy

        self.ntilesx = (self.nx - 1) // (self.ntx - 1)
        self.ntilesy = (self.ny - 1) // (self.nty - 1)

        self.name = name
        self.dtype = dtype
        self.data_dir = data_dir
        self.citation = citation
        if region is not None:
            self.region = self.positive_region(region)
        else:
            self.region = None

    def covers(self, region):
        if self.region is None:
            return True

        a = self.region
        b = self.positive_region(region)
        return ((
            (a[0] <= b[0] and b[1] <= b[1]) or
            (a[0] <= b[0]+360. and b[1]+360 <= a[1]))
            and a[2] <= b[2] and b[3] <= a[3])

    def is_suitable(self, region, dmin, dmax):
        d = 360. / (self.nx - 1)
        return self.covers(region) and dmin <= d <= dmax

    def download_file(self, url, fpath, username=None, password=None):
        # TODO: Add logstring
        util.download_file(
            url, fpath, username, password,
            status_callback=get_download_callback(
                'Downloading %s topography...' % self.__class__.__name__))

    def x(self):
        return self.xmin + num.arange(self.nx) * self.dx

    def y(self):
        return self.ymin + num.arange(self.ny) * self.dy

    def positive_region(self, region):
        xmin, xmax, ymin, ymax = [float(x) for x in region]

        assert -180. - 360. <= xmin < 180.
        assert -180. < xmax <= 180. + 360.
        assert -90. <= ymin < 90.
        assert -90. < ymax <= 90.

        if xmax < xmin:
            xmax += 360.

        if xmin < -180.:
            xmin += 360.
            xmax += 360.

        return (xmin, xmax, ymin, ymax)

    def tile_indices(self, region):
        xmin, xmax, ymin, ymax = self.positive_region(region)
        itxmin = int(math.floor((xmin - self.xmin) / self.stx))
        itxmax = int(math.ceil((xmax - self.xmin) / self.stx))
        if itxmin == itxmax:
            itxmax += 1
        itymin = int(math.floor((ymin - self.ymin) / self.sty))
        itymax = int(math.ceil((ymax - self.ymin) / self.sty))
        if itymin == itymax:
            if itymax != self.ntilesy:
                itymax += 1
            else:
                itymin -= 1

        indices = []
        for ity in range(itymin, itymax):
            for itx in range(itxmin, itxmax):
                indices.append((itx % self.ntilesx, ity))

        return indices

    def get_tile(self, itx, ity):
        return None

    def get(self, region):
        if len(region) == 2:
            x, y = region
            t = self.get((x, x, y, y))
            if t is not None:
                return t.get(x, y)
            else:
                return None

        indices = self.tile_indices(region)
        tiles = []
        for itx, ity in indices:
            t = self.get_tile(itx, ity)
            if t:
                tiles.append(t)

        return tile.combine(tiles, region)

    def get_with_repeat(self, region):
        xmin, xmax, ymin, ymax = region
        ymin2 = max(-90., ymin)
        ymax2 = min(90., ymax)
        region2 = xmin, xmax, ymin2, ymax2
        t = self.get(region2)
        if t is not None and region2 != region:
            t.yextend_with_repeat(ymin, ymax)

        return t


class DecimatedTiledGlobalDataset(TiledGlobalDataset):

    def __init__(self, name, base, ndeci, data_dir=None, ntx=None, nty=None):

        assert ndeci % 2 == 0
        assert (base.nx - 1) % ndeci == 0
        assert (base.ny - 1) % ndeci == 0

        nx = (base.nx - 1) // ndeci + 1
        ny = (base.ny - 1) // ndeci + 1

        if ntx is None:
            ntx = base.ntx

        if nty is None:
            nty = base.nty

        assert (nx - 1) % (ntx - 1) == 0
        assert (ny - 1) % (nty - 1) == 0

        if data_dir is None:
            data_dir = op.join(base.data_dir, 'decimated_%i' % ndeci)

        TiledGlobalDataset.__init__(self, name, nx, ny, ntx, nty, base.dtype,
                                    data_dir=data_dir, citation=base.citation,
                                    region=base.region)

        self.base = base
        self.ndeci = ndeci

    def make_tile(self, itx, ity, fpath):
        nh = self.ndeci // 2
        xmin = self.xmin + itx*self.stx - self.base.dx * nh
        xmax = self.xmin + (itx+1)*self.stx + self.base.dx * nh
        ymin = self.ymin + ity*self.sty - self.base.dy * nh
        ymax = self.ymin + (ity+1)*self.sty + self.base.dy * nh

        t = self.base.get_with_repeat((xmin, xmax, ymin, ymax))
        if t is not None:
            t.decimate(self.ndeci)

        util.ensuredirs(fpath)
        with open(fpath, 'w') as f:
            if t is not None:
                t.data.tofile(f)

    def make_if_needed(self, itx, ity):
        assert 0 <= itx < self.ntilesx
        assert 0 <= ity < self.ntilesy

        fn = '%02i.%02i.bin' % (ity, itx)
        fpath = op.join(self.data_dir, fn)
        if not op.exists(fpath):
            logger.info('making decimated tile: %s (%s)' % (fn, self.name))
            self.make_tile(itx, ity, fpath)

    def get_tile(self, itx, ity):
        assert 0 <= itx < self.ntilesx
        assert 0 <= ity < self.ntilesy

        self.make_if_needed(itx, ity)

        fn = '%02i.%02i.bin' % (ity, itx)
        fpath = op.join(self.data_dir, fn)
        with open(fpath, 'r') as f:
            data = num.fromfile(f, dtype=self.dtype)

        if data.size == 0:
            return None

        assert data.size == self.ntx*self.nty
        data = data.reshape((self.ntx, self.nty))

        return tile.Tile(
            self.xmin + itx*self.stx,
            self.ymin + ity*self.sty,
            self.dx, self.dx, data)

    def make_all_missing(self):
        for ity in range(self.ntilesy):
            for itx in range(self.ntilesx):
                self.make_if_needed(itx, ity)
