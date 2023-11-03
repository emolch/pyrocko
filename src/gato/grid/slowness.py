# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------


import numpy as num

from pyrocko.guts import Float
from pyrocko.moment_tensor import euler_to_matrix
from .base import Grid, GridSnap, grid_coordinates
from ..error import GatoError

guts_prefix = 'gato'

d2r = num.pi / 180.


class SlownessGrid(Grid):
    pass


class CartesianSlownessGrid(SlownessGrid):
    '''
    Regular cartesian slowness grid with optional rotation.

    Unrotated coordinate system is NED (north-east-down).

    3D-indexing is ordered from sz (slow dimension) to sx (fast dimension)
    ``f[iz, iy, ix]``. 1D-indexing uses :py:func:`numpy.unravel_index` on
    ``(nz, ny, nx)``.

    If any attribute is changed after initialization, :py:meth:`update` must
    be called.
    '''

    azimuth = Float.T(
        default=0.0,
        help='Angle of x against north [deg].')
    dip = Float.T(
        default=0.0,
        help='Angle of y against horizontal [deg], rotation around x')
    sx_min = Float.T(
        default=0.0,
        help='Sx axis minimum [s/m].')
    sx_max = Float.T(
        default=0.0,
        help='Sx axis maximum [s/m].')
    sy_min = Float.T(
        default=0.0,
        help='Sy axis minimum [s/m].')
    sy_max = Float.T(
        default=0.0,
        help='Sy axis maximum [s/m].')
    sz_min = Float.T(
        default=0.0,
        help='Sz axis minimum [s/m].')
    sz_max = Float.T(
        default=0.0,
        help='Sz axis maximum [s/m].')
    sx_delta = Float.T(
        default=1.0,
        help='Sx axis spacing [s/m].')
    sy_delta = Float.T(
        default=1.0,
        help='Sy axis spacing [s/m].')
    sz_delta = Float.T(
        default=1.0,
        help='Sz axis spacing [s/m].')
    snap = GridSnap.T(
        default='both',
        help='Flag to indicate how grid inconsistencies are handled.')

    @classmethod
    def from_smax_2d(cls, s_max, s_delta):
        return cls(
            sx_min=-s_max,
            sx_max=s_max,
            sx_delta=s_delta,
            sy_min=-s_max,
            sy_max=s_max,
            sy_delta=s_delta)

    def update(self):
        self.clear_cached()
        self._x = grid_coordinates(
            self.sx_min, self.sx_max, self.sx_delta, self.snap)
        self._y = grid_coordinates(
            self.sy_min, self.sy_max, self.sy_delta, self.snap)
        self._z = grid_coordinates(
            self.sz_min, self.sz_max, self.sz_delta, self.snap)
        self._nx = self._x.size
        self._ny = self._y.size
        self._nz = self._z.size

    def clear_cached(self):
        self._xyz = None
        self._ned = None

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

        return self._ned

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
            Coordinate system: ``'xyz'``, unrotated coordinate system,
            ``'ned'``: rotated coordinate system in ``(north, east, down)``.
        :type system:
            str

        :returns:
            Point coordinates in requested coordinate system.
        :rtype:
            :py:class:`numpy.ndarray` of shape ``(size, 3)``, where size is the
            number of nodes
        '''

        if system == 'ned':
            return self._get_ned()

        elif system == 'xyz':
            return self._get_xyz()

        else:
            raise GatoError(
                'Coordinate system not supported for %s: %s' % (
                    self.__class__.__name__ + '.get_nodes', system))

    def get_coords(self, system):
        if system == 'xyz':
            return self._x, self._y, self._z
        else:
            raise GatoError(
                'Coordinate system not supported for %s: %s' % (
                    self.__class__.__name__ + '.get_coords', system))


class SphericalSlownessGrid(SlownessGrid):
    '''
    Regular (3D) slowness grid in spherical coordinates with optional rotation.

    Unrotated coordinate system is NED (north-east-down).

    3D-indexing is ordered from sr (slow dimension) via stheta to sphi
    (fast dimension) ``f[ir, itheta, iphi]``. 1D-indexing uses
    :py:func:`numpy.unravel_index` on ``(nr, ntheta, nphi)``.

    If any attribute is changed after initialization, :py:meth:`update` must
    be called.
    '''

    azimuth = Float.T(
        default=0.0,
        help='Angle of 0. azimuth direction against north [deg].')
    sr_min = Float.T(
        default=0.0,
        help='Sr axis minimum [s/m].')
    sr_max = Float.T(
        default=0.0,
        help='Sr axis maximum [s/m].')
    stheta_min = Float.T(
        default=0.0,
        help='Lower angle limit of incidence angle [deg].')
    stheta_max = Float.T(
        default=0.0,
        help='Upper angle limit of incidence angle [deg].')
    sphi_min = Float.T(
        default=-180.0,
        help='Lower angle limit of azimuth angle [deg].')
    sphi_max = Float.T(
        default=180.0,
        help='Upper angle limit of azimuth angle [deg].')
    sr_delta = Float.T(
        default=1.0,
        help='Sr axis spacing [s/m].')
    stheta_delta = Float.T(
        default=1.0,
        help='Angle spacing in incidence [deg].')
    sphi_delta = Float.T(
        default=1.0,
        help='Angle spacing in azimuth [deg].')
    snap = GridSnap.T(
        default='both',
        help='Flag to indicate how grid inconsistencies are handled.')

    def update(self):
        self.clear_cached()
        self._r = grid_coordinates(
            self.sr_min, self.sr_max, self.sr_delta, self.snap)
        self._phi = grid_coordinates(
            self.sphi_min, self.sphi_max,
            self.sphi_delta, self.snap)
        self._theta = grid_coordinates(
            self.stheta_min, self.stheta_max,
            self.stheta_delta, self.snap)
        self._nr = self._r.size
        self._nphi = self._phi.size
        self._ntheta = self._theta.size

    def clear_cached(self):
        self._xyz = None
        self._ned = None
        self._rtp = None

    def _get_rtp(self):
        ''' gets nodes in order phi, theta, radius, angles are in radian '''
        if self._rtp is None:
            r2, theta2, phi2 = [v.flatten() for v in num.meshgrid(
                self._r, self._theta, self._phi, indexing='ij')]

            self._rtp = num.vstack([phi2, theta2, r2]).T

        return self._rtp

    def _get_xyz(self):

        if self._xyz is None:
            rtp = self._get_rtp()
            x2 = rtp[:, 2] * num.sin(rtp[:, 1]*d2r) * num.cos(rtp[:, 0]*d2r)
            y2 = rtp[:, 2] * num.sin(rtp[:, 1]*d2r) * num.sin(rtp[:, 0]*d2r)
            z2 = rtp[:, 2] * num.cos(rtp[:, 1]*d2r)

            self._xy = num.vstack([x2, y2, z2]).T

        return self._xyz

    def _get_ned(self):

        if self._ned is None:
            rtp = self._get_rtp()
            n2 = rtp[:, 2] * num.sin(rtp[:, 1]*d2r) \
                * num.cos((rtp[:, 0] - self.azimuth)*d2r)
            e2 = rtp[:, 2] * num.sin(rtp[:, 1]*d2r) \
                * num.sin((rtp[:, 0] - self.azimuth)*d2r)
            d2 = rtp[:, 2] * num.cos(rtp[:, 1]*d2r)

            self._ned = num.vstack([n2, e2, d2]).T

        return self._ned

    @property
    def shape(self):
        '''
        Logical shape of the grid.
        '''
        return (self._nr, self._ntheta, self._nphi)

    @property
    def size(self):
        '''
        Number of grid nodes.
        '''
        return self._nr * self._nphi * self._ntheta

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
            Coordinate system: ``'xy'``, unrotated coordinate system,
            ``'ne'``: rotated coordinate system in ``(north, east)``,
            ``'rtp'``, spherical coordinates in ``(radius, theta, phi)``.
        :type system:
            str

        :returns:
            Point coordinates in requested coordinate system.
        :rtype:
            :py:class:`numpy.ndarray` of shape ``(size, 2)``, where size is the
            number of nodes
        '''

        if system == 'ned':
            return self._get_ned()

        elif system == 'xyz':
            return self._get_xyz()

        elif system == 'rtp':
            return self._get_rtp()

        else:
            raise GatoError(
                'Coordinate system not supported for %s: %s' % (
                    self.__class__.__name__, system))


__all__ = [
    'SlownessGrid',
    'CartesianSlownessGrid',
    'SphericalSlownessGrid',
]
