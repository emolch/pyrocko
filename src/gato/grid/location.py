# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from pyrocko import orthodrome as od
from pyrocko.moment_tensor import euler_to_matrix
from pyrocko.model.location import Location
from pyrocko.guts import Float, List
from pyrocko.guts_array import Array
from pyrocko.squirrel.model import CodesNSLCE
from .base import Grid, GridSnap, grid_coordinates
from ..error import GatoError

guts_prefix = 'gato'

d2r = num.pi / 180.
NA = num.newaxis


def distances_3d(grid_a, grid_b):
    a = grid_a.get_nodes('ecef')
    b = grid_b.get_nodes('ecef')
    return num.sqrt(
        num.sum((a[:, NA, :] - b[NA, :, :])**2, 2))


def distances_surface(grid_a, grid_b):
    a = grid_a.get_nodes('latlondepth')
    b = grid_b.get_nodes('latlondepth')

    return od.distance_proj(
        a[:, NA, 0],
        a[:, NA, 1],
        b[NA, :, 0],
        b[NA, :, 1])


def distances_projected(normal_ecef, grid_a, grid_b):
    a = grid_a.get_nodes('ecef')
    b = grid_b.get_nodes('ecef')

    a_proj = a - num.dot(a, normal_ecef)[:, NA] * normal_ecef[NA, :]
    b_proj = b - num.dot(b, normal_ecef)[:, NA] * normal_ecef[NA, :]

    return num.sqrt(
        num.sum((a_proj[:, NA, :] - b_proj[NA, :, :])**2, 2))


class LocationGrid(Grid):
    '''
    Base class for location grids.
    '''


class CartesianLocationGrid(LocationGrid):
    '''
    Regular Cartesian grid anchored at a reference point with optional
    rotation.

    Unrotated coordinate system is NED (north-east-down).

    3D-indexing is ordered from z (slow dimension) to x (fast dimension)
    ``f[iz, iy, ix]``. 1D-indexing uses :py:func:`numpy.unravel_index` on
    ``(nz, ny, nx)``.

    If any attribute is changed after initialization, :py:meth:`update` must
    be called.
    '''

    origin = Location.T(
        help='Anchor point of the grid.')
    azimuth = Float.T(
        default=0.0,
        help='Angle of x against north [deg].')
    dip = Float.T(
        default=0.0,
        help='Angle of y against horizontal [deg], rotation around x')
    x_min = Float.T(
        default=0.0,
        help='X axis minimum [m].')
    x_max = Float.T(
        default=0.0,
        help='X axis maximum [m].')
    y_min = Float.T(
        default=0.0,
        help='Y axis minimum [m].')
    y_max = Float.T(
        default=0.0,
        help='Y axis maximum [m].')
    z_min = Float.T(
        default=0.0,
        help='Z axis minimum [m].')
    z_max = Float.T(
        default=0.0,
        help='Z axis maximum [m].')
    x_delta = Float.T(
        default=1.0,
        help='X axis spacing [m].')
    y_delta = Float.T(
        default=1.0,
        help='Y axis spacing [m].')
    z_delta = Float.T(
        default=1.0,
        help='Z axis spacing [m].')
    snap = GridSnap.T(
        default='both',
        help='Flag to indicate how grid inconsistencies are handled.')

    def update(self):
        self.clear_cached()
        self._x = grid_coordinates(
            self.x_min, self.x_max, self.x_delta, self.snap)
        self._y = grid_coordinates(
            self.y_min, self.y_max, self.y_delta, self.snap)
        self._z = grid_coordinates(
            self.z_min, self.z_max, self.z_delta, self.snap)
        self._nx = self._x.size
        self._ny = self._y.size
        self._nz = self._z.size

    def clear_cached(self):
        self._xyz = None
        self._ned = None
        self._latlondepth = None
        self._ecef = None

    def _get_xyz(self):
        if self._xyz is None:

            z2, y2, x2 = [v.flatten() for v in num.meshgrid(
                self._z, self._y, self._x, indexing='ij')]

            self._xyz = num.vstack([x2, y2, z2]).T

        return self._xyz

    def _get_ned(self):
        if self._ned is None:

            rotmat = euler_to_matrix(self.dip * d2r, self.azimuth * d2r, 0.0)
            self._ned = num.dot(rotmat.T, self._get_xyz().T).T
            # Note: _ned is relative to reference point.

        return self._ned

    def _get_latlondepth(self):
        if self._latlondepth is None:
            ned = self._get_ned()
            lats, lons = od.ne_to_latlon_proj(
                self.origin.lat,
                self.origin.lon,
                self.origin.north_shift + ned[:, 0],
                self.origin.east_shift + ned[:, 1])

            depths = self.origin.depth - self.origin.elevation + ned[:, 2]
            self._latlondepth = num.vstack((lats, lons, depths)).T

        return self._latlondepth

    def _get_ecef(self):
        if self._ecef is None:
            lat, lon, depth = self._get_latlondepth().T
            x, y, z = od.geodetic_to_ecef(lat, lon, -depth)
            self._ecef = num.vstack((x, y, z)).T

        return self._ecef

    @property
    def shape(self):
        '''
        Logical shape of the grid.
        '''
        return (self._nz, self._ny, self._nx)

    @property
    def size(self):
        '''
        Number of grid nodes.
        '''
        return self._nz * self._ny * self._nx

    @property
    def effective_dimension(self):
        '''
        Number of non-flat dimensions.
        '''
        return sum(int(x > 1) for x in self.shape)

    def get_nodes(self, system):
        '''
        Get node coordinates.

        :param system:
            Coordinate system: ``'latlondepth'``, world coordinates as
            ``(latitude, longitude, depth)``, ``'xyz'``, unrotated coordinate
            system, ``'ned'``, rotated coordinate system in ``(north, east,
            down)`` relative to :py:gattr:`origin`.
        :type system:
            str

        :returns:
            Point coordinates in requested coordinate system.
        :rtype:
            :py:class:`numpy.ndarray` of shape ``(size, 3)``, where size is the
            number of nodes
        '''
        if system == 'latlondepth':
            return self._get_latlondepth()

        if system == 'ecef':
            return self._get_ecef()

        elif system == 'ned':
            return self._get_ned()

        elif system == 'xyz':
            return self._get_xyz()

        else:
            raise GatoError(
                'Coordinate system not supported for %s: %s' % (
                    self.__class__.__name__, system))

    def plot(self, values, axes=None, scale=1.0):

        ned = self.get_nodes('ned')
        plt = None
        if axes is None:
            import matplotlib.pyplot as plt
            axes = plt.gca()

        n, e, d = ned.T

        values = values.reshape(self.shape)
        n = n.reshape(self.shape)
        e = e.reshape(self.shape)
        d = d.reshape(self.shape)

        axes.pcolormesh(e[0, :, :]/scale, n[0, :, :]/scale, values[0, :, :])
        if plt:
            plt.show()


class UnstructuredLocationGrid(LocationGrid):
    '''
    Representation of a set of scattered locations.

    This class is useful to represent e.g. sensor locations in a seismic array
    or other collections of locations with irregular structure.
    '''

    origin = Location.T(
        optional=True,
        help='Anchor point of the grid.')

    coordinates = Array.T(
        help='6C-Coordinates of grid nodes as ``(lat, lon, north_shift, '
             'east_shift, depth, elevation)``',
        shape=(None, 6),
        dtype=num.float64,
        serialize_as='npy')

    codes = List.T(
        CodesNSLCE.T(),
        optional=True)

    @classmethod
    def from_locations(cls, locations, ignore_position_duplicates=False):

        if ignore_position_duplicates:
            have = set()

        coordinates = num.zeros((len(locations), 6))

        ilocation = 0
        for location in locations:
            position = (
                location.lat,
                location.lon,
                location.north_shift,
                location.east_shift,
                location.depth,
                location.elevation)

            if ignore_position_duplicates:
                if position in have:
                    continue

                have.add(position)

            coordinates[ilocation, :] = position
            ilocation += 1

        if ignore_position_duplicates:
            coordinates = coordinates[:ilocation, :]

        return cls(coordinates=coordinates)

    def update(self):
        self.clear_cached()

    def clear_cached(self):
        self._latlondepth = None
        self._ecef = None
        self._ned = None

    @property
    def shape(self):
        '''
        Logical shape of the grid.
        '''
        return (self.coordinates.shape[0],)

    @property
    def size(self):
        '''
        Number of grid nodes.
        '''
        return self.coordinates.shape[0]

    def set_origin_to_center(self):
        self.origin = self.get_center()
        self._ned = None

    def get_center(self):
        lld = self._get_latlondepth()
        lat, lon = od.geographic_midpoint(
            lats=lld[:, 0], lons=lld[:, 1])
        depth = num.mean(self.coordinates[:, 4])
        elevation = num.mean(self.coordinates[:, 5])
        return Location(lat=lat, lon=lon, depth=depth, elevation=elevation)

    def get_effective_origin(self):
        if self.origin is not None:
            return self.origin
        else:
            return self.get_center()

    def _get_latlondepth(self):
        if self._latlondepth is None:
            lats, lons = od.ne_to_latlon_proj(
                self.coordinates[:, 0],
                self.coordinates[:, 1],
                self.coordinates[:, 2],
                self.coordinates[:, 3])

            depths = self.coordinates[:, 4] - self.coordinates[:, 5]
            self._latlondepth = num.vstack((lats, lons, depths)).T

        return self._latlondepth

    def _get_ecef(self):
        if self._ecef is None:
            lat, lon, depth = self._get_latlondepth().T
            x, y, z = od.geodetic_to_ecef(lat, lon, -depth)
            self._ecef = num.vstack((x, y, z)).T

        return self._ecef

    def _get_ned(self):
        if self._ned is None:
            lld = self._get_latlondepth()
            origin = self.get_effective_origin()
            ns, es = od.latlon_to_ne_proj(
                origin.lat, origin.lon,
                lld[:, 0], lld[:, 1])

            self._ned = num.vstack(
                (ns, es,
                 lld[:, 2] + origin.elevation - origin.depth)).T

        return self._ned

    def get_nodes(self, system):
        '''
        Get node coordinates.

        :param system:
            Coordinate system: ``'latlondepth'``, world coordinates as
            ``(latitude, longitude, depth)``, ``'ned'``, coordinate system in
            ``(north, east, down)`` relative to :py:gattr:`origin`.
        :type system:
            str

        :returns:
            Point coordinates in requested coordinate system.
        :rtype:
            :py:class:`numpy.ndarray` of shape ``(size, 3)``, where size is the
            number of nodes
        '''
        if system == 'latlondepth':
            return self._get_latlondepth()

        if system == 'ecef':
            return self._get_ecef()

        elif system == 'ned':
            return self._get_ned()

        else:
            raise GatoError(
                'Coordinate system not supported for %s: %s' % (
                    self.__class__.__name__, system))

    def plot(self, values=None, axes=None, scale=1.0):

        ned = self.get_nodes('ned')
        plt = None
        if axes is None:
            import matplotlib.pyplot as plt
            axes = plt.gca()

        n, e, d = ned.T

        if values:
            d = dict(c=values)
        else:
            d = dict(color='black')

        axes.scatter(e/scale, n/scale, **d)
        if plt:
            plt.show()


__all__ = [
    'distances_3d',
    'distances_surface',
    'distances_projected',
    'CartesianLocationGrid',
    'UnstructuredLocationGrid',
]
