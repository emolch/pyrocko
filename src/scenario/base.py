# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Base classes for the scenario generators.
'''

import math
import hashlib
import logging

import numpy as num

from pyrocko.guts import Object, Int, Bool, Float
from pyrocko import orthodrome as od
from pyrocko.dataset import gshhg, topo
from .error import ScenarioError, LocationGenerationError

logger = logging.getLogger('pyrocko.scenario.base')

guts_prefix = 'pf.scenario'

km = 1000.
d2r = num.pi/180.
N = 10000000

coastlines = None


def get_gsshg():
    global coastlines
    if coastlines is None:
        logger.debug('Initialising GSHHG database.')
        coastlines = gshhg.GSHHG.intermediate()
    return coastlines


def is_on_land(lat, lon, method='coastlines'):
    if method == 'topo':
        elevation = topo.elevation(lat, lon)
        if elevation is None:
            return False
        else:
            return topo.elevation(lat, lon) > 0.

    elif method == 'coastlines':
        is_land = get_gsshg().is_point_on_land(lat, lon)
        logger.debug(
            'Testing %.4f %.4f: %s' % (lat, lon, 'dry' if is_land else 'wet'))

        return is_land


def random_lat(rstate, lat_min=-90., lat_max=90.):
    lat_min_ = 0.5*(math.sin(lat_min * math.pi/180.)+1.)
    lat_max_ = 0.5*(math.sin(lat_max * math.pi/180.)+1.)
    return math.asin(rstate.uniform(lat_min_, lat_max_)*2.-1.)*180./math.pi


def random_latlon(rstate, avoid_water, ntries, label):
    for itry in range(ntries):
        logger.debug('%s: try %i' % (label, itry))
        lat = random_lat(rstate)
        lon = rstate.uniform(-180., 180.)
        if not avoid_water or is_on_land(lat, lon):
            return lat, lon

    if avoid_water:
        sadd = ' (avoiding water)'

    raise LocationGenerationError('Could not generate location%s.' % sadd)


def random_uniform(rstate, xmin, xmax, xdefault):
    if None in (xmin, xmax):
        return xdefault
    else:
        return rstate.uniform(xmin, xmax)


class Generator(Object):
    '''
    Base class for random object generators in :py:mod:`pyrocko.scenario`.
    '''
    seed = Int.T(
        optional=True,
        help='Random seed for a reproducible scenario.')

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self._seed = None
        self._parent = None
        self.update_hierarchy()
        self._retry_offset = 0

    def retry(self):
        self.clear()
        self._retry_offset += 1
        for val in self.T.ivals(self):
            if isinstance(val, Generator):
                val.retry()

    def clear(self):
        self._seed = None

    def hash(self):
        return hashlib.sha1(
            (self.dump() + '\n\n%i' % self._retry_offset).encode('utf8'))\
            .hexdigest()

    def get_seed_offset(self):
        return int(self.hash(), base=16) % N

    def update_hierarchy(self, parent=None):
        self._parent = parent
        for val in self.T.ivals(self):
            if isinstance(val, Generator):
                val.update_hierarchy(parent=self)
            elif isinstance(val, list):
                for el in val:
                    if isinstance(el, Generator):
                        el.update_hierarchy(parent=self)

    def get_root(self):
        if self._parent is None:
            return self
        else:
            return self._parent.get_root()

    def get_seed(self):
        if self._seed is None:
            if self.seed is None:
                if self._parent is not None:
                    self._seed = self._parent.get_seed()
                else:
                    self._seed = num.random.randint(N)
            elif self.seed == 0:
                self._seed = num.random.randint(N)
            else:
                self._seed = self.seed

        return self._seed + self.get_seed_offset()

    def get_rstate(self, i):
        return num.random.RandomState(int(self.get_seed() + i))

    def get_center_latlon(self):
        return self._parent.get_center_latlon()

    def get_radius(self):
        return self._parent.get_radius()

    def get_stations(self):
        return []


class LocationGenerator(Generator):
    '''
    Base class for generators providing random locations.
    '''

    avoid_water = Bool.T(
        default=True,
        help='Set whether wet areas should be avoided.')
    center_lat = Float.T(
        optional=True,
        help='Center latitude for the random locations in [deg].')
    center_lon = Float.T(
        optional=True,
        help='Center longitude for the random locations in [deg].')
    radius = Float.T(
        optional=True,
        help='Radius for distribution of random locations [m].')
    ntries = Int.T(
        default=10,
        help='Maximum number of tries to find a location satisifying all '
             'given constraints')
    north_shift_min = Float.T(
        optional=True,
        help='If given, lower bound of random northward cartesian offset [m].')
    north_shift_max = Float.T(
        optional=True,
        help='If given, upper bound of random northward cartesian offset [m].')
    east_shift_min = Float.T(
        optional=True,
        help='If given, lower bound of random eastward cartesian offset [m].')
    east_shift_max = Float.T(
        optional=True,
        help='If given, upper bound of random eastward cartesian offset [m].')
    depth_min = Float.T(
        optional=True,
        help='If given, minimum depth [m].')
    depth_max = Float.T(
        optional=True,
        help='If given, maximum depth [m].')

    def __init__(self, **kwargs):
        Generator.__init__(self, **kwargs)
        self._center_latlon = None

    def clear(self):
        Generator.clear(self)
        self._center_latlon = None

    def get_center_latlon(self):
        if (self.center_lat is None) != (self.center_lon is None):
            raise ScenarioError(
                'Set both: lat and lon, or neither of them (in %s).'
                % self.__class__.__name__)

        if self._center_latlon is None:

            if self.center_lat is not None and self.center_lon is not None:
                self._center_latlon = self.center_lat, self.center_lon

            else:
                if self._parent:
                    self._center_latlon = self._parent.get_center_latlon()
                else:
                    rstate = self.get_rstate(0)
                    self._center_latlon = random_latlon(
                        rstate, self.avoid_water, self.ntries,
                        self.__class__.__name__)

        return self._center_latlon

    def get_radius(self):
        if self.radius is not None:
            return self.radius
        elif self._parent is not None:
            return self._parent.get_radius()
        else:
            return None

    def get_latlon(self, i):
        rstate = self.get_rstate((i+1)*3+0)
        for itry in range(self.ntries):
            logger.debug('%s: try %i' % (self.__class__.__name__, itry))
            radius = self.get_radius()
            if radius is None:
                lat = random_lat(rstate)
                lon = rstate.uniform(-180., 180.)
            elif radius == 0.0:
                lat, lon = self.get_center_latlon()
            else:
                lat_center, lon_center = self.get_center_latlon()
                while True:
                    north = rstate.uniform(-radius, radius)
                    east = rstate.uniform(-radius, radius)
                    if math.sqrt(north**2 + east**2) <= radius:
                        break

                lat, lon = od.ne_to_latlon(lat_center, lon_center, north, east)

            if not self.avoid_water or is_on_land(lat, lon):
                logger.debug('location ok: %g, %g' % (lat, lon))
                return lat, lon

        if self.avoid_water:
            sadd = ' (avoiding water)'

        raise LocationGenerationError('Could not generate location%s.' % sadd)

    def get_cartesian_offset(self, i):
        rstate = self.get_rstate((i+1)*3+1)
        north_shift = random_uniform(
            rstate, self.north_shift_min, self.north_shift_max, 0.0)
        east_shift = random_uniform(
            rstate, self.east_shift_min, self.east_shift_max, 0.0)

        return north_shift, east_shift

    def get_depth(self, i):
        rstate = self.get_rstate((i+1)*3+1)
        return random_uniform(
            rstate, self.depth_min, self.depth_max, 0.0)

    def get_coordinates(self, i):
        lat, lon = self.get_latlon(i)
        north_shift, east_shift = self.get_cartesian_offset(i)
        depth = self.get_depth(i)
        return lat, lon, north_shift, east_shift, depth
