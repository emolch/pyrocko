# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
NOAA `ETOPO1 <https://www.ngdc.noaa.gov/mgg/global/>`_ Global Relief Map.
'''

import zipfile
import os.path as op

import numpy as num

from . import tile, dataset

try:
    range = xrange
except NameError:
    pass

citation = '''
Amante, C. and B.W. Eakins, 2009. ETOPO1 1 Arc-Minute Global Relief Model:
Procedures, Data Sources and Analysis. NOAA Technical Memorandum NESDIS
NGDC-24. National Geophysical Data Center, NOAA. doi:10.7289/V5C8276M
'''

__doc__ += '''

.. rubric:: Citation
''' + citation


class ETOPO1(dataset.TiledGlobalDataset):
    '''
    ETOPO1 as a tiled global dataset.
    '''

    def __init__(
            self,
            name='ETOPO1',
            data_dir=op.join(op.dirname(__file__), 'data', 'ETOPO1'),
            base_fn='etopo1_ice_g_i2',
            raw_data_url=('https://mirror.pyrocko.org/www.ngdc.noaa.gov/mgg'
                          '/global/relief/ETOPO1/data/ice_surface/'
                          'grid_registered/binary/%s.zip')):

        dataset.TiledGlobalDataset.__init__(
            self,
            name,
            21601, 10801, 1351, 1351,
            num.dtype('<i2'),
            data_dir=data_dir,
            citation=citation)

        self.base_fn = base_fn
        self.raw_data_url = raw_data_url

    def download(self):
        fpath = op.join(self.data_dir, '%s.zip' % self.base_fn)
        if not op.exists(fpath):
            self.download_file(
                self.raw_data_url % self.base_fn, fpath)

        self.make_tiles()

    def make_tiles(self):
        fpath = op.join(self.data_dir, '%s.zip' % self.base_fn)

        zipf = zipfile.ZipFile(fpath, 'r')
        rawdata = zipf.read('%s.bin' % self.base_fn)
        zipf.close()
        data = num.frombuffer(rawdata, dtype=self.dtype)
        assert data.size == self.nx * self.ny
        data = data.reshape((self.ny, self.nx))[::-1]

        for ity in range(self.ntilesy):
            for itx in range(self.ntilesx):
                tiledata = data[ity*(self.nty-1):(ity+1)*(self.nty-1)+1,
                                itx*(self.ntx-1):(itx+1)*(self.ntx-1)+1]

                fn = '%s.%02i.%02i.bin' % (self.base_fn, ity, itx)
                fpath = op.join(self.data_dir, fn)
                with open(fpath, 'w') as f:
                    tiledata.tofile(f)

    def get_tile(self, itx, ity):
        assert 0 <= itx < self.ntilesx
        assert 0 <= ity < self.ntilesy

        fn = '%s.%02i.%02i.bin' % (self.base_fn, ity, itx)
        fpath = op.join(self.data_dir, fn)
        if not op.exists(fpath):
            self.download()

        with open(fpath, 'r') as f:
            data = num.fromfile(f, dtype=self.dtype)

        assert data.size == self.ntx*self.nty
        data = data.reshape((self.ntx, self.nty))

        return tile.Tile(
            self.xmin + itx*self.stx,
            self.ymin + ity*self.sty,
            self.dx, self.dx, data)
