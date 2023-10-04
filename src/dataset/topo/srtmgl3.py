# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
NASA Shuttle Radar Topography Mission Global 30 arc second (`SRTMGL3 <https://lpdaac.usgs.gov/dataset_discovery/measures/measures_products_table/srtmgl3_v003>`_) topography data.
'''  # noqa

import zipfile
import os.path as op
import os
import re
# from pyrocko.util import urlopen

import numpy as num

from pyrocko import util, config
from . import tile, dataset

citation = '''
Farr, T. G., and M. Kobrick, 2000, Shuttle Radar Topography Mission produces a
wealth of data. Eos Trans. AGU, 81:583-585.

Farr, T. G. et al., 2007, The Shuttle Radar Topography Mission, Rev. Geophys.,
45, RG2004, doi:10.1029/2005RG000183. (Also available online at
http://www2.jpl.nasa.gov/srtm/SRTM_paper.pdf)

Kobrick, M., 2006, On the toes of giants-How SRTM was born, Photogramm. Eng.
Remote Sens., 72:206-210.

Rosen, P. A. et al., 2000, Synthetic aperture radar interferometry, Proc. IEEE,
88:333-382.
'''

__doc__ += '''
.. rubric:: Citation

''' + citation


class AuthenticationRequired(Exception):
    pass


class SRTMGL3(dataset.TiledGlobalDataset):
    '''

    '''

    def __init__(
            self,
            name='SRTMGL3',
            data_dir=op.join(op.dirname(__file__), 'data', 'SRTMGL3'),
            raw_data_url='https://mirror.pyrocko.org/e4ftl01.cr.usgs.gov/'
                         'MEASURES/SRTMGL3.003/2000.02.11'):

        dataset.TiledGlobalDataset.__init__(
            self,
            name,
            432001, 216001, 1201, 1201,
            num.dtype('>i2'),
            data_dir=data_dir,
            citation=citation,
            region=(-180., 180., -60., 60.))

        self.raw_data_url = raw_data_url
        self._available_tilenames = None
        self.config = config.config()

    def tilename(self, itx, ity):
        itx -= 180
        ity -= 90
        if ity >= 0:
            s = 'N%02i' % ity
        else:
            s = 'S%02i' % -ity

        if itx >= 0:
            s += 'E%03i' % itx
        else:
            s += 'W%03i' % -itx

        return s

    def available_tilenames(self):
        if self._available_tilenames is None:
            fpath = op.join(self.data_dir, 'available.list')
            if not op.exists(fpath) or os.stat(fpath).st_size == 0:
                util.ensuredirs(fpath)
                # remote structure changed, we would have to clawl through
                # many pages. Now keeping tile index here:
                self.download_file(
                    'https://mirror.pyrocko.org/e4ftl01.cr.usgs.gov/'
                    'MEASURES/SRTMGL3.003/2000.02.11/available.list', fpath)

                # url = self.raw_data_url + '/'
                # f = urlopen(url)
                # data = f.read().decode()
                # available = re.findall(
                #     r'([NS]\d\d[EW]\d\d\d)\.SRTMGL3\.hgt', data)
                #
                # f.close()
                #
                # with open(fpath, 'w') as f:
                #     f.writelines('%s\n' % s for s in available)

            with open(fpath, 'r') as f:
                available = [
                    s.strip() for s in f.readlines()
                    if re.match(r'^[NS]\d\d[EW]\d\d\d$', s.strip())]

            self._available_tilenames = set(available)

        return self._available_tilenames

    def tilefilename(self, tilename):
        return tilename + '.SRTMGL3.hgt.zip'

    def tilepath(self, tilename):
        fn = self.tilefilename(tilename)
        return op.join(self.data_dir, fn)

    def download_tile(self, tilename):
        fpath = self.tilepath(tilename)
        fn = self.tilefilename(tilename)
        url = self.raw_data_url + '/' + fn
        try:
            # we have to follow the oauth redirect here...
            self.download_file(url, fpath)
        except Exception as e:
            raise e

    def download(self):
        for tn in self.available_tilenames():
            fpath = self.tilepath(tn)
            if not op.exists(fpath):
                self.download_tile(tn)

    def get_tile(self, itx, ity):
        tn = self.tilename(itx, ity)
        if tn not in self.available_tilenames():
            return None
        else:
            fpath = self.tilepath(tn)
            if not op.exists(fpath):
                self.download_tile(tn)

            zipf = zipfile.ZipFile(fpath, 'r')
            rawdata = zipf.read(tn + '.hgt')
            zipf.close()
            data = num.frombuffer(rawdata, dtype=self.dtype)
            assert data.size == self.ntx * self.nty
            data = data.reshape(self.nty, self.ntx)[::-1, ::]
            return tile.Tile(
                self.xmin + itx*self.stx,
                self.ymin + ity*self.sty,
                self.dx, self.dx, data)


if __name__ == '__main__':
    import sys

    util.setup_logging('pyrocko.topo.srtmgl3', 'info')

    if len(sys.argv) != 2:
        sys.exit('usage: python -m pyrocko.topo.srtmgl3 download')

    if sys.argv[1] == 'download':
        srtmgl3 = SRTMGL3()
        srtmgl3.download()
