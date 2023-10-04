# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
'''
Interface to use CRUST2.0 model by Laske, Masters and Reif.

All functions defined in this module return SI units (m, m/s, kg/m^3).

.. rubric:: Citation

If you use this model, please refer to the
`REM web site <http://igppweb.ucsd.edu/~gabi/rem.html>`_  or cite:

Bassin, C., Laske, G. and Masters, G., The Current Limits of Resolution for
Surface Wave Tomography in North America, EOS Trans AGU, 81, F897, 2000. A
description of CRUST 5.1 can be found in: Mooney, Laske and Masters, Crust
5.1: a global crustal model at 5x5 degrees, JGR, 103, 727-747, 1998.

.. rubric:: Usage

::

    >>> from pyrocko import crust2x2
    >>> p = crust2x2.get_profile(10., 20.)
    >>> print p
    type, name:              G2, Archean 0.5 km seds.
    elevation:                           529
    crustal thickness:                 38500
    average vp, vs, rho:              6460.7          3665.1          2867.5
    mantle ave. vp, vs, rho:            8200            4700            3400

              0            3810            1940             920   ice
              0            1500               0            1020   water
            500            2500            1200            2100   soft sed.
              0            4000            2100            2400   hard sed.
          12500            6200            3600            2800   upper crust
          13000            6400            3600            2850   middle crust
          13000            6800            3800            2950   lower crust
    >>> print p.get_weeded()
    [[     0.    500.    500.  13000.  13000.  26000.  26000.  39000.  39000.]
     [  2500.   2500.   6200.   6200.   6400.   6400.   6800.   6800.   8200.]
     [  1200.   1200.   3600.   3600.   3600.   3600.   3800.   3800.   4700.]
     [  2100.   2100.   2800.   2800.   2850.   2850.   2950.   2950.   3400.]]


.. rubric:: Constants

============== ==============
Layer id       Layer name
============== ==============
LICE           ice
LWATER         water
LSOFTSED       soft sediments
LHARDSED       hard sediments
LUPPERCRUST    upper crust
LMIDDLECRUST   middle crust
LLOWERCRUST    lower crust
LBELOWCRUST    below crust
============== ==============

'''

import os
import copy
import math
from io import StringIO

import numpy as num


LICE, LWATER, LSOFTSED, LHARDSED, LUPPERCRUST, LMIDDLECRUST, \
    LLOWERCRUST, LBELOWCRUST = list(range(8))


class Crust2Profile(object):
    '''
    Representation of a CRUST2.0 key profile.
    '''

    layer_names = (
        'ice', 'water', 'soft sed.', 'hard sed.', 'upper crust',
        'middle crust', 'lower crust', 'mantle')

    def __init__(self, ident, name, vp, vs, rho, thickness, elevation):
        self._ident = ident
        self._name = name
        self._vp = vp
        self._vs = vs
        self._rho = rho
        self._thickness = thickness
        self._crustal_thickness = None
        self._elevation = elevation

    def get_weeded(self, include_waterlayer=False):
        '''
        Get layers used in the profile.

        :param include_waterlayer: include water layer if ``True``. Default is
            ``False``

        :returns: NumPy array with rows ``depth``, ``vp``, ``vs``, ``density``
        '''
        depth = 0.
        layers = []
        for ilayer, thickness, vp, vs, rho in zip(
                range(8),
                self._thickness,
                self._vp[:-1],
                self._vs[:-1],
                self._rho[:-1]):

            if thickness == 0.0:
                continue

            if not include_waterlayer and ilayer == LWATER:
                continue

            layers.append([depth, vp, vs, rho])
            layers.append([depth+thickness, vp, vs, rho])
            depth += thickness

        layers.append([
            depth,
            self._vp[LBELOWCRUST],
            self._vs[LBELOWCRUST],
            self._rho[LBELOWCRUST]])

        return num.array(layers).T

    def get_layer(self, ilayer):
        '''
        Get parameters for a layer.

        :param ilayer: id of layer
        :returns: thickness, vp, vs, density
        '''

        if ilayer == LBELOWCRUST:
            thickness = num.Inf
        else:
            thickness = self._thickness[ilayer]

        return thickness, self._vp[ilayer], self._vs[ilayer], self._rho[ilayer]

    def set_elevation(self, elevation):
        self._elevation = elevation

    def set_layer_thickness(self, ilayer, thickness):
        self._thickness[ilayer] = thickness

    def elevation(self):
        return self._elevation

    def __str__(self):

        vvp, vvs, vrho, vthi = self.averages()

        return '''type, name:              %s, %s
elevation:               %15.5g
crustal thickness:       %15.5g
average vp, vs, rho:     %15.5g %15.5g %15.5g
mantle ave. vp, vs, rho: %15.5g %15.5g %15.5g

%s''' % (self._ident, self._name, self._elevation, vthi, vvp, vvs, vrho,
         self._vp[LBELOWCRUST], self._vs[LBELOWCRUST], self._rho[LBELOWCRUST],
         '\n'.join([
             '%15.5g %15.5g %15.5g %15.5g   %s' % x
             for x in zip(
                 self._thickness, self._vp[:-1], self._vs[:-1], self._rho[:-1],
                 Crust2Profile.layer_names)]))

    def crustal_thickness(self):
        '''
        Get total crustal thickness.

        Takes into account ice layer.
        Does not take into account water layer.
        '''

        return num.sum(self._thickness[3:]) + self._thickness[LICE]

    def averages(self):
        '''
        Get crustal averages for vp, vs, density and total crustal thickness.

        Takes into account ice layer.
        Does not take into account water layer.
        '''

        vthi = self.crustal_thickness()
        vvp = num.sum(self._thickness[3:] / self._vp[3:-1]) + \
            self._thickness[LICE] / self._vp[LICE]
        vvs = num.sum(self._thickness[3:] / self._vs[3:-1]) + \
            self._thickness[LICE] / self._vs[LICE]
        vrho = num.sum(self._thickness[3:] * self._rho[3:-1]) + \
            self._thickness[LICE] * self._rho[LICE]

        vvp = vthi / vvp
        vvs = vthi / vvs
        vrho = vrho / vthi

        return vvp, vvs, vrho, vthi


def _sa2arr(sa):
    return num.array([float(x) for x in sa], dtype=float)


def _wrap(x, mi, ma):
    if mi <= x and x <= ma:
        return x

    return x - math.floor((x-mi)/(ma-mi)) * (ma-mi)


def _clip(x, mi, ma):
    return min(max(mi, x), ma)


class Crust2(object):
    '''
    Access CRUST2.0 model.

        :param directory: Directory with the data files which contain the
            CRUST2.0 model data. If this is set to ``None``, builtin CRUST2.0
            files are used.
    '''

    fn_keys = 'CNtype2_key.txt'
    fn_elevation = 'CNelevatio2.txt'
    fn_map = 'CNtype2.txt'

    nlo = 180
    nla = 90

    _instance = None

    def __init__(self, directory=None):

        self.profile_keys = []
        self._directory = directory
        self._typemap = None
        self._load_crustal_model()

    def get_profile(self, *args, **kwargs):
        '''
        Get crustal profile at a specific location or raw profile for given
        key.

        Get profile for location ``(lat, lon)``, or raw profile for given
        string key.

        :rtype: instance of :py:class:`Crust2Profile`
        '''

        lat = kwargs.pop('lat', None)
        lon = kwargs.pop('lon', None)

        if len(args) == 2:
            lat, lon = args

        if lat is not None and lon is not None:
            return self._typemap[self._indices(float(lat), float(lon))]
        else:
            return self._raw_profiles[args[0]]

    def _indices(self, lat, lon):
        lat = _clip(lat, -90., 90.)
        lon = _wrap(lon, -180., 180.)
        dlo = 360./Crust2.nlo
        dla = 180./Crust2.nla
        cola = 90.-lat
        ilat = _clip(int(cola/dla), 0, Crust2.nla-1)
        ilon = int((lon+180.)/dlo) % Crust2.nlo
        return ilat, ilon

    def _load_crustal_model(self):

        if self._directory is not None:
            path_keys = os.path.join(self._directory, Crust2.fn_keys)
            f = open(path_keys, 'r')
        else:
            from .crust2x2_data import decode, type2_key, type2, elevation

            f = StringIO(decode(type2_key))

        # skip header
        for i in range(5):
            f.readline()

        profiles = {}
        while True:
            line = f.readline()
            if not line:
                break
            ident, name = line.split(None, 1)
            line = f.readline()
            vp = _sa2arr(line.split()) * 1000.
            line = f.readline()
            vs = _sa2arr(line.split()) * 1000.
            line = f.readline()
            rho = _sa2arr(line.split()) * 1000.
            line = f.readline()
            toks = line.split()
            thickness = _sa2arr(toks[:-2]) * 1000.

            assert ident not in profiles

            profiles[ident] = Crust2Profile(
                ident.strip(), name.strip(), vp, vs, rho, thickness, 0.0)

        f.close()

        self._raw_profiles = profiles
        self.profile_keys = sorted(profiles.keys())

        if self._directory is not None:
            path_map = os.path.join(self._directory, Crust2.fn_map)
            f = open(path_map, 'r')
        else:
            f = StringIO(decode(type2))

        f.readline()  # header

        amap = {}
        for ila, line in enumerate(f):
            keys = line.split()[1:]
            for ilo, key in enumerate(keys):
                amap[ila, ilo] = copy.deepcopy(profiles[key])

        f.close()

        if self._directory is not None:
            path_elevation = os.path.join(self._directory, Crust2.fn_elevation)
            f = open(path_elevation, 'r')

        else:
            f = StringIO(decode(elevation))

        f.readline()
        for ila, line in enumerate(f):
            for ilo, s in enumerate(line.split()[1:]):
                p = amap[ila, ilo]
                p.set_elevation(float(s))
                if p.elevation() < 0.:
                    p.set_layer_thickness(LWATER, -p.elevation())

        f.close()

        self._typemap = amap

    @staticmethod
    def instance():
        '''
        Get the global default Crust2 instance.
        '''

        if Crust2._instance is None:
            Crust2._instance = Crust2()

        return Crust2._instance


def get_profile_keys():
    '''
    Get list of all profile keys.
    '''

    crust2 = Crust2.instance()
    return list(crust2.profile_keys)


def get_profile(*args, **kwargs):
    '''
    Get Crust2x2 profile for given location or profile key.

    Get profile for (lat,lon) or raw profile for given string key.
    '''

    crust2 = Crust2.instance()
    return crust2.get_profile(*args, **kwargs)


def plot_crustal_thickness(crust2=None, filename='crustal_thickness.pdf'):
    '''
    Create a quick and dirty plot of the crustal thicknesses defined in
    CRUST2.0.
    '''

    if crust2 is None:
        crust2 = Crust2.instance()

    def func(lat, lon):
        return crust2.get_profile(lat, lon).crustal_thickness(),

    plot(func, filename, zscaled_unit='km', zscaled_unit_factor=0.001)


def plot_vp_belowcrust(crust2=None, filename='vp_below_crust.pdf'):
    '''
    Create a quick and dirty plot of vp below the crust, as defined in
    CRUST2.0.
    '''

    if crust2 is None:
        crust2 = Crust2.instance()

    def func(lat, lon):
        return crust2.get_profile(lat, lon).get_layer(LBELOWCRUST)[1]

    plot(func, filename, zscaled_unit='km/s', zscaled_unit_factor=0.001)


def plot(func, filename, **kwargs):
    nlats, nlons = 91, 181
    lats = num.linspace(-90., 90., nlats)
    lons = num.linspace(-180., 180., nlons)

    vecfunc = num.vectorize(func, [float])
    latss, lonss = num.meshgrid(lats, lons)
    thickness = vecfunc(latss, lonss)

    from pyrocko.plot import gmtpy
    cm = gmtpy.cm
    marg = (1.5*cm, 2.5*cm, 1.5*cm, 1.5*cm)
    p = gmtpy.Simple(
        width=20*cm, height=10*cm, margins=marg,
        with_palette=True, **kwargs)

    p.density_plot(gmtpy.tabledata(lons, lats, thickness.T))
    p.save(filename)
