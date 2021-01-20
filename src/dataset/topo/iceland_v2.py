# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import zipfile
import os.path as op
import re

import numpy as num

from pyrocko import util
from . import tile, dataset

citation = '''
ISL.zip from http://www.viewfinderpanoramas.org/dem3.html
'''


class IcelandV2(dataset.TiledGlobalDataset):

    def __init__(
            self,
            name='IcelandV2',
            data_dir=op.join(op.dirname(__file__), 'Icelandv2'),
            raw_data_url='http://www.viefinderpanoramas.org/dem3/ISL.zip'):

        dataset.TiledGlobalDataset.__init__(
            self,
            name,
            432001, 216001, 1201, 1201,
            num.dtype('>i2'),
            data_dir=data_dir,
            citation=citation,
            region=(-25., -13., 63., 67.))

        self.raw_data_url = raw_data_url
        self._available_tilenames = None

    def tilename(self, itx, ity):
        itx -= 180
        ity -= 90
        if ity >= 0:
            s = 'n%02i' % ity
        else:
            s = 's%02i' % -ity

        if itx >= 0:
            s += 'e%03i' % itx
        else:
            s += 'w%03i' % -itx

        return s

    def available_tilenames(self):
        if self._available_tilenames is None:
            fpath = op.join(self.data_dir, 'available.list')
            if op.exists(fpath):
                with open(fpath, 'r') as f:
                    available = [op.splitext(s.strip())[0] for s in f.readlines()]

            self._available_tilenames = set(available)

        return self._available_tilenames

    def tilefilename(self, tilename):
        return tilename + '.hgt'

    def tilepath(self, tilename):
        fn = self.tilefilename(tilename)
        return op.join(self.data_dir, fn)

    def download_tile(self, tilename):
        raise NotImplemented()

    def download(self):
        for tn in self.available_tilenames():
            fpath = self.tilepath(tn)
            if not op.exists(fpath):
                self.download_tile(tn)

    def get_tile(self, itx, ity):
        tn = self.tilename(itx, ity)
        print('tn', tn)
        if tn not in self.available_tilenames():
            return None
        else:
            fpath = self.tilepath(tn)
            if not op.exists(fpath):
                self.download_tile(tn)

            f = open(fpath, 'rb')
            rawdata = f.read()
            f.close()
            data = num.frombuffer(rawdata, dtype=self.dtype)
            assert data.size == self.ntx * self.nty
            data = data.reshape(self.nty, self.ntx)[::-1, ::]
            return tile.Tile(
                self.xmin + itx*self.stx,
                self.ymin + ity*self.sty,
                self.dx, self.dx, data)

if __name__ == '__main__':
    from pyrocko.topo import etopo1, comparison

    iceland_v2 = IcelandV2()
    reg = (-18., -17., 64., 65.)
    #reg = (-25., -10., 62., 67.)

    t = iceland_v2.get(reg)
    print(t)

    comparison(reg, dems=[iceland_v2, etopo1])

