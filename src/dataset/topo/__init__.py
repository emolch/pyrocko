# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Multiresolution topography and bathymetry datasets.

This module provides access to gridded topography data from the following
sources:

* NOAA `ETOPO1 <https://www.ngdc.noaa.gov/mgg/global/>`_ Global Relief Map.
* NASA Shuttle Radar Topography Mission Global 30 arc second (`SRTMGL3
  <https://lpdaac.usgs.gov/dataset_discovery/measures/measures_products_table/srtmgl3_v003>`_)
  topography data.

'''

import math
import os.path as op

from pyrocko import config, util
from .srtmgl3 import SRTMGL3, AuthenticationRequired  # noqa
from .etopo1 import ETOPO1
from . import dataset, tile
from pyrocko.plot.cpt import get_cpt_path as cpt  # noqa

positive_region = tile.positive_region

earthradius = 6371000.0
r2d = 180./math.pi
d2r = 1./r2d
km = 1000.
d2m = d2r*earthradius
m2d = 1./d2m

topo_data_dir = config.config().topo_dir

_srtmgl3 = SRTMGL3(
    name='SRTMGL3',
    data_dir=op.join(topo_data_dir, 'SRTMGL3'))

_srtmgl3_d2 = dataset.DecimatedTiledGlobalDataset(
    name='SRTMGL3_D2',
    base=_srtmgl3,
    ndeci=2,
    data_dir=op.join(topo_data_dir, 'SRTMGL3_D2'))

_srtmgl3_d4 = dataset.DecimatedTiledGlobalDataset(
    name='SRTMGL3_D4',
    base=_srtmgl3_d2,
    ndeci=2,
    data_dir=op.join(topo_data_dir, 'SRTMGL3_D4'))

_srtmgl3_d8 = dataset.DecimatedTiledGlobalDataset(
    name='SRTMGL3_D8',
    base=_srtmgl3_d4,
    ndeci=2,
    ntx=1001,
    nty=1001,
    data_dir=op.join(topo_data_dir, 'SRTMGL3_D8'))

_etopo1 = ETOPO1(
    name='ETOPO1',
    data_dir=op.join(topo_data_dir, 'ETOPO1'))

_etopo1_d2 = dataset.DecimatedTiledGlobalDataset(
    name='ETOPO1_D2',
    base=_etopo1,
    ndeci=2,
    data_dir=op.join(topo_data_dir, 'ETOPO1_D2'))

_etopo1_d4 = dataset.DecimatedTiledGlobalDataset(
    name='ETOPO1_D4',
    base=_etopo1_d2,
    ndeci=2,
    data_dir=op.join(topo_data_dir, 'ETOPO1_D4'))

_etopo1_d8 = dataset.DecimatedTiledGlobalDataset(
    name='ETOPO1_D8',
    base=_etopo1_d4,
    ndeci=2,
    data_dir=op.join(topo_data_dir, 'ETOPO1_D8'))

_srtmgl3_all = [
    _srtmgl3,
    _srtmgl3_d2,
    _srtmgl3_d4,
    _srtmgl3_d8]

_etopo1_all = [
    _etopo1,
    _etopo1_d2,
    _etopo1_d4,
    _etopo1_d8]

_dems = _srtmgl3_all + _etopo1_all


def make_all_missing_decimated():
    for dem in _dems:
        if isinstance(dem, dataset.DecimatedTiledGlobalDataset):
            dem.make_all_missing()


def comparison(region, dems=_dems):
    import matplotlib.pyplot as plt

    west, east, south, north = tile.positive_region(region)

    fig = plt.gcf()

    for idem, dem_ in enumerate(dems):
        fig.add_subplot(len(dems), 1, idem+1)
        t = dem_.get(region)
        if t:
            plt.pcolormesh(t.x(), t.y(), t.data)
            plt.title(dem_.name)
            plt.xlim(west, east)
            plt.ylim(south, north)

    plt.show()


class UnknownDEM(Exception):
    pass


def dem_names():
    return [dem.name for dem in _dems]


def dem(dem_name):
    for dem in _dems:
        if dem.name == dem_name:
            return dem

    raise UnknownDEM(dem_name)


def get(dem_name, region):
    return dem(dem_name).get(region)


def elevation(lat, lon):
    '''
    Get elevation at given point.

    Tries to use SRTMGL3, falls back to ETOPO01 if not available.
    '''

    for dem in ['SRTMGL3', 'ETOPO1']:
        r = get(dem, (lon, lat))
        if r is not None and r != 0:
            return r


def select_dem_names(kind, dmin, dmax, region, mode='highest'):
    assert kind in ('land', 'ocean')
    assert mode in ('highest', 'lowest')

    step = -1 if mode == 'lowest' else 1

    ok = []
    if kind == 'land':
        for dem in _srtmgl3_all[::step]:
            if dem.is_suitable(region, dmin, dmax):
                ok.append(dem.name)
                break

    for dem in _etopo1_all[::step]:
        if dem.is_suitable(region, dmin, dmax):
            ok.append(dem.name)
            break

    return ok


if __name__ == '__main__':
    # comparison((-180., 180., -90, 90), dems=[_etopo1_d8])
    util.setup_logging('topo', 'info')
    comparison((30, 31, 30, 31), dems=[_srtmgl3, _srtmgl3_d2])
