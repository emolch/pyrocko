# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Representation of a geographical location, base class for stations, events,
etc.
'''

import numpy as num
import math

from pyrocko import orthodrome
from pyrocko.guts import Object, Float


guts_prefix = 'pf'

d2r = math.pi / 180.
r2d = 1.0 / d2r
km = 1000.


def latlondepth_to_cartesian(lat, lon, depth):
    return orthodrome.geodetic_to_ecef(lat, lon, -depth)


class Location(Object):
    '''
    Geographical location.

    The location is given by a reference point at the earth's surface
    (:py:attr:`lat`, :py:attr:`lon`, :py:attr:`elevation`) and a cartesian
    offset from this point (:py:attr:`north_shift`, :py:attr:`east_shift`,
    :py:attr:`depth`). The offset corrected lat/lon coordinates of the location
    can be accessed though the :py:attr:`effective_latlon`,
    :py:attr:`effective_lat`, and :py:attr:`effective_lon` properties.
    '''

    lat = Float.T(
        default=0.0,
        optional=True,
        help='Latitude of reference point [deg].')

    lon = Float.T(
        default=0.0,
        optional=True,
        help='Longitude of reference point [deg].')

    north_shift = Float.T(
        default=0.,
        optional=True,
        help='Northward cartesian offset from reference point [m].')

    east_shift = Float.T(
        default=0.,
        optional=True,
        help='Eastward cartesian offset from reference point [m].')

    elevation = Float.T(
        default=0.0,
        optional=True,
        help='Surface elevation, above sea level [m].')

    depth = Float.T(
        default=0.0,
        help='Depth, below surface [m].')

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self._latlon = None

    def __setattr__(self, name, value):
        if name in ('lat', 'lon', 'north_shift', 'east_shift'):
            self.__dict__['_latlon'] = None

        Object.__setattr__(self, name, value)

    @property
    def effective_latlon(self):
        '''
        Property holding the offset-corrected lat/lon pair of the location.
        '''

        if self._latlon is None:
            if self.north_shift == 0.0 and self.east_shift == 0.0:
                self._latlon = self.lat, self.lon
            else:
                self._latlon = tuple(float(x) for x in orthodrome.ne_to_latlon(
                    self.lat, self.lon, self.north_shift, self.east_shift))

        return self._latlon

    @property
    def effective_lat(self):
        '''
        Property holding the offset-corrected latitude of the location.
        '''

        return self.effective_latlon[0]

    @property
    def effective_lon(self):
        '''
        Property holding the offset-corrected longitude of the location.
        '''

        return self.effective_latlon[1]

    def same_origin(self, other):
        '''
        Check whether other location object has the same reference location.
        '''

        return self.lat == other.lat and self.lon == other.lon

    def distance_to(self, other):
        '''
        Compute surface distance [m] to other location object.


        '''

        if self.same_origin(other):
            other_north_shift, other_east_shift = get_offset(other)

            return math.sqrt((self.north_shift - other_north_shift)**2 +
                             (self.east_shift - other_east_shift)**2)

        else:
            slat, slon = self.effective_latlon
            rlat, rlon = get_effective_latlon(other)

            return float(orthodrome.distance_accurate50m_numpy(
                slat, slon, rlat, rlon)[0])

    def distance_3d_to(self, other):
        '''
        Compute 3D distance [m] to other location object.

        All coordinates are transformed to cartesian coordinates if necessary
        then distance is:

        .. math::

            \\Delta = \\sqrt{\\Delta {\\bf x}^2 + \\Delta {\\bf y}^2 + \
                      \\Delta {\\bf z}^2}

        '''

        if self.same_origin(other):
            other_north_shift, other_east_shift = get_offset(other)
            return math.sqrt((self.north_shift - other_north_shift)**2 +
                             (self.east_shift - other_east_shift)**2 +
                             (self.depth - other.depth)**2)

        else:
            slat, slon = self.effective_latlon
            rlat, rlon = get_effective_latlon(other)

            sx, sy, sz = latlondepth_to_cartesian(slat, slon, self.depth)
            rx, ry, rz = latlondepth_to_cartesian(rlat, rlon, other.depth)

            return math.sqrt((sx-rx)**2 + (sy-ry)**2 + (sz-rz)**2)

    def ecef(self):
        lat, lon = self.effective_latlon
        return num.array(
            latlondepth_to_cartesian(lat, lon, -self.elevation + self.depth),
            dtype=float)

    def offset_to(self, other):
        if self.same_origin(other):
            other_north_shift, other_east_shift = get_offset(other)
            return (
                other_north_shift - self.north_shift,
                other_east_shift - self.east_shift)

        else:
            azi, bazi = self.azibazi_to(other)
            dist = self.distance_to(other)
            return dist*math.cos(azi*d2r), dist*math.sin(azi*d2r)

    def azibazi_to(self, other):
        '''
        Compute azimuth and backazimuth to and from other location object.
        '''

        if self.same_origin(other):
            other_north_shift, other_east_shift = get_offset(other)
            azi = r2d * math.atan2(other_east_shift - self.east_shift,
                                   other_north_shift - self.north_shift)

            bazi = azi + 180.
        else:
            slat, slon = self.effective_latlon
            rlat, rlon = get_effective_latlon(other)
            azi, bazi = orthodrome.azibazi(slat, slon, rlat, rlon)

        return float(azi), float(bazi)

    def set_origin(self, lat, lon):
        lat = float(lat)
        lon = float(lon)
        elat, elon = self.effective_latlon
        n, e = orthodrome.latlon_to_ne(lat, lon, elat, elon)
        self.lat = lat
        self.lon = lon
        self.north_shift = float(n)
        self.east_shift = float(e)
        self._latlon = elat, elon  # unchanged

    @property
    def coords5(self):
        return num.array([
            self.lat, self.lon, self.north_shift, self.east_shift, self.depth])


def get_offset(obj):
    try:
        return obj.north_shift, obj.east_shift
    except AttributeError:
        return 0.0, 0.0


def get_effective_latlon(obj):
    try:
        return obj.effective_latlon
    except AttributeError:
        return obj.lat, obj.lon
