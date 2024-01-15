# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Interface to the `GSHHG <https://www.soest.hawaii.edu/pwessel/gshhg/>`_
(coastlines, rivers and borders) database.

The Global Self-consistent Hierarchical High-resolution Geography Database
(GSHHG) is a collection of polygons representing land, lakes, rivers and
political borders.

If the database is not already available, it will be downloaded
automatically on first use.

For more information about GSHHG, see
http://www.soest.hawaii.edu/pwessel/gshhg/.

.. rubric:: Citation

If you use this dataset, please cite

Wessel, P., and W. H. F. Smith, A Global Self-consistent, Hierarchical,
High-resolution Shoreline Database, J. Geophys. Res., 101, #B4, pp. 8741-8743,
1996.

'''

import logging
import io
import struct
import time
import numpy as num

from os import path

from pyrocko import config, orthodrome
from .util import get_download_callback


logger = logging.getLogger('pyrocko.dataset.gshhg')
config = config.config()

km = 1e3
micro_deg = 1e-6


def split_region_0_360(wesn):
    west, east, south, north = wesn
    if west < 0.:
        if east <= 0:
            return [(west+360., east+360., south, north)]
        else:
            return [(west+360., 360., south, north),
                    (0., east, south, north)]
    else:
        return [wesn]


def is_valid_bounding_box(wesn):
    '''
    Check if a given bounding box meets the GSHHG conventions.

    :param wesn: bounding box as (west, east, south, north) in [deg]
    '''

    w, e, s, n = wesn

    return (
        w <= e
        and s <= n
        and -90.0 <= s <= 90.
        and -90. <= n <= 90.
        and -180. <= w < 360.
        and -180. <= e < 360.)


def is_valid_polygon(points):
    '''
    Check if polygon points meet the GSHHG conventions.

    :param points: Array of (lat, lon) pairs, shape (N, 2).
    '''

    lats = points[:, 0]
    lons = points[:, 1]

    return (
        num.all(-90. <= lats)
        and num.all(lats <= 90.)
        and num.all(-180. <= lons)
        and num.all(lons < 360.))


def points_in_bounding_box(points, wesn, tolerance=0.1):
    '''
    Check which points are contained in a given bounding box.

    :param points: Array of (lat lon) pairs, shape (N, 2) [deg].
    :param wesn: Region tuple (west, east, south, north) [deg]
    :param tolerance: increase the size of the test bounding box by
        *tolerance* [deg] on every side (Some GSHHG polygons have a too tight
        bounding box).

    :returns: Bool array of shape (N,).
    '''
    points_wrap = points.copy()
    points_wrap[:, 1] %= 360.

    mask = num.zeros(points_wrap.shape[0], dtype=bool)
    for w, e, s, n in split_region_0_360(wesn):
        mask = num.logical_or(
            mask,
            num.logical_and(
                num.logical_and(
                    w-tolerance <= points_wrap[:, 1],
                    points_wrap[:, 1] <= e+tolerance),
                num.logical_and(
                    s-tolerance <= points_wrap[:, 0],
                    points_wrap[:, 0] <= n+tolerance)))

    return mask


def point_in_bounding_box(point, wesn, tolerance=0.1):
    '''
    Check whether point is contained in a given bounding box.

    :param points: Array of (lat lon) pairs, shape (N, 2) [deg].
    :param wesn: Region tuple (west, east, south, north) [deg]
    :param tolerance: increase the size of the test bounding box by
        *tolerance* [deg] on every side (Some GSHHG polygons have a too tight
        bounding box).

    :rtype: bool
    '''

    lat, lon = point
    lon %= 360.
    for w, e, s, n in split_region_0_360(wesn):
        if (w-tolerance <= lon
                and lon <= e+tolerance
                and s-tolerance <= lat
                and lat <= n+tolerance):

            return True

    return False


def bounding_boxes_overlap(wesn1, wesn2):
    '''
    Check whether two bounding boxes intersect.

    :param wesn1:
        Region tuple ``(west, east, south, north)`` [deg]
    :type wesn1:
        :py:class:`tuple` of 4 :py:class:`float`

    :param wesn2:
        Region tuple ``(west, east, south, north)`` [deg]
    :type wesn2:
        :py:class:`tuple` of 4 :py:class:`float`

    :rtype: bool
    '''
    for w1, e1, s1, n1 in split_region_0_360(wesn1):
        for w2, e2, s2, n2 in split_region_0_360(wesn2):
            if w2 <= e1 and w1 <= e2 and s2 <= n1 and s1 <= n2:
                return True

    return False


def is_polygon_in_bounding_box(points, wesn, tolerance=0.1):
    return num.all(points_in_bounding_box(points, wesn, tolerance=tolerance))


def bounding_box_covering_points(points):
    lats = points[:, 0]
    lat_min, lat_max = num.min(lats), num.max(lats)

    lons = points[:, 1]
    lons = lons % 360.
    lon_min, lon_max = num.min(lons), num.max(lons)
    if lon_max - lon_min < 180.:
        return lon_min, lon_max, lat_min, lat_max

    lons = (lons - 180.) % 360. - 180.
    lon_min, lon_max = num.min(lons), num.max(lons)
    if lon_max - lon_min < 180.:
        return lon_min, lon_max, lat_min, lat_max

    return (-180., 180., lat_min, lat_max)


LEVELS = {
    'rivers': [
        'DOUBLE_LINED_RIVERS',
        'PERMANENT_MAJOR_RIVERS',
        'ADDITIONAL_MAJOR_RIVERS',
        'ADDITIONAL_RIVERS',
        'MINOR_RIVERS',
        'INTERMITTENT_RIVERS-MAJOR',
        'INTERMITTENT_RIVERS-ADDITIONAL',
        'INTERMITTENT_RIVERS-MINOR',
        'MAJOR_CANALS',
        'MINOR_CANALS',
        'IRRIGATION_CANALS'],
    'coastlines': [
        'LAND',
        'LAKE',
        'ISLAND_IN_LAKE',
        'POND_IN_ISLAND_IN_LAKE',
        'ANTARCTIC_ICE_FRONT',
        'ANTARCTIC_GROUNDING_LINE'],
    'borders': [
        'NATIONAL_BOUNDARIES',
        'STATE_BOUNDARIES_WITHIN_THE_AMERICAS',
        'MARINE_BOUNDARIES']}


class Polygon(object):
    '''
    Representation of a GSHHG polygon.
    '''

    RIVER_NOT_SET = 0

    SOURCE = ['CIA_WDBII', 'WVS', 'AC']

    def __init__(self, data_type, gshhg_file, offset, *attr):
        '''
        Initialise a GSHHG polygon

        :param gshhg_file:
            GSHHG binary file
        :type gshhg_file:
            file handle

        :param offset:
            This polygon's offset in binary file
        :type offset:
            int

        :param attr:
            Polygon attributes
             ``(pid, npoints, _flag, west, east, south, north,
              area, area_full, container, ancestor)``.
              See :file:`gshhg.h` for details.
        :type attr:
            tuple
        '''
        self.data_type = data_type
        (self.pid, self.npoints, self._flag,
         self.west, self.east, self.south, self.north,
         self.area, self.area_full, self.container, self.ancestor) = attr

        self.west *= micro_deg
        self.east *= micro_deg
        self.south *= micro_deg
        self.north *= micro_deg

        self.level_no = (self._flag & 255)
        if self.data_type == 'rivers':
            # there seems to be a bug in the current version of GSHHG
            self.level_no = [
                0, 1, 2, 3, 4, -1, 5, 6, 7, -1, 8, 9, -1, 10][self.level_no]
        else:
            self.level_no -= 1

        self.version = (self._flag >> 8) & 255

        cross = (self._flag >> 16) & 3
        self.greenwhich_crossed = True if cross == 1 or cross == 3 else False
        self.dateline_crossed = True if cross == 2 or cross == 3 else False

        self.source = self.SOURCE[(self._flag >> 24) & 1]
        if self.level_no >= 5:
            self.source = self.SOURCE[2]

        self.river = (self._flag >> 25) & 1

        scale = 10.**(self._flag >> 26)
        self.area /= scale
        self.area_full /= scale

        self._points = None
        self._file = gshhg_file
        self._offset = offset

    @property
    def level(self):
        return LEVELS[self.data_type][self.level_no]

    @property
    def points(self):
        '''
        Points of the polygon.

        Array of (lat, lon) pairs, shape (N, 2).

        :rtype: :class:`numpy.ndarray`
        '''
        if self._points is None:
            with open(self._file) as db:
                db.seek(self._offset)
                self._points = num.fromfile(
                    db, dtype='>i4', count=self.npoints*2)\
                    .astype(num.float32)\
                    .reshape(self.npoints, 2)

            self._points = num.fliplr(self._points)
            if self.data_type == 'coastlines' and self.level_no in (1, 3):
                self._points = self._points[::-1, :]

            self._points *= micro_deg

        return self._points

    @property
    def lats(self):
        return self.points[:, 0]

    @property
    def lons(self):
        return self.points[:, 1]

    def is_land(self):
        '''
        Check if the polygon is land.

        :rtype: bool
        '''
        return self.level_no == 0

    def is_lake(self):
        '''
        Check if the polygon is a lake.

        :rtype: bool
        '''
        return self.level_no == 1

    def is_island_in_lake(self):
        '''
        Check if the polygon is an island in a lake.

        :rtype: bool
        '''
        return self.level_no == 2

    def is_pond_in_island_in_lake(self):
        '''
        Check if the polygon is pond on an island in a lake.

        :rtype: bool
        '''
        return self.level_no == 3

    def is_antarctic_icefront(self):
        '''
        Check if the polygon is antarctic icefront.

        :rtype: bool
        '''
        return self.level_no == 4

    def is_antarctic_grounding_line(self):
        '''
        Check if the polygon is antarctic grounding line.

        :rtype: bool
        '''
        return self.level_no == 5

    def contains_point(self, point):
        '''
        Check if point lies in polygon.

        :param point: (lat, lon) [deg]
        :type point: tuple
        :rtype: bool

        See :py:func:`pyrocko.orthodrome.contains_points`.
        '''
        return bool(
            self.contains_points(num.asarray(point)[num.newaxis, :])[0])

    def contains_points(self, points):
        '''
        Check if points lie in polygon.

        :param points: Array of (lat lon) pairs, shape (N, 2) [deg].
        :type points: :class:`numpy.ndarray`

        See :py:func:`pyrocko.orthodrome.contains_points`.

        :returns: Bool array of shape (N,)
        '''
        mask = points_in_bounding_box(points, self.get_bounding_box())
        if num.any(mask):
            mask[mask] = orthodrome.contains_points(
                self.points, points[mask, :])

        return mask

    def get_bounding_box(self):
        return (self.west, self.east, self.south, self.north)

    def __lt__(self, polygon):
        return self.level_no < polygon.level_no

    def __str__(self):
        rstr = '''Polygon id: {p.pid}
-------------------
Points:     {p.npoints}
Level:      {p.level}
Area:       {p.area} km**2
Area Full:  {p.area_full} km**2
Extent:     {p.west} W, {p.east} E, {p.south} S, {p.north} N
Source:     {p.source}
Greenwhich crossed: {p.greenwhich_crossed}
Dateline crossed:   {p.dateline_crossed}
        '''.format(p=self)
        return rstr


class GSHHGBase(object):
    '''
    GSHHG database access.

    This class provides methods to select relevant polygons (land, lakes, etc.)
    for given locations or regions. It also provides robust high-level
    functions to test if the Earth is dry or wet at given coordinates.
    '''

    data_type = None

    gshhg_url = 'https://mirror.pyrocko.org/www.soest.hawaii.edu/pwessel/gshhg/gshhg-bin-2.3.7.zip'  # noqa
    _header_struct = struct.Struct('>IIIiiiiIIii')

    def __init__(self, gshhg_file):
        ''' Initialise the database from GSHHG binary.

        :param gshhg_file: Path to file
        :type gshhg_file: str
        :
        '''
        t0 = time.time()
        self._file = gshhg_file

        self.polygons = []
        self._read_database()
        logger.debug('Initialised GSHHG database from %s in [%.4f s]'
                     % (gshhg_file, time.time()-t0))

    def _read_database(self):
        with open(self._file, mode='rb') as db:
            while db:
                buf = db.read(self._header_struct.size)
                if not buf:
                    break
                header = self._header_struct.unpack_from(buf)

                p = Polygon(
                    self.data_type,
                    self._file,
                    db.tell(),
                    *header)

                self.polygons.append(p)

                offset = 8 * header[1]
                db.seek(offset, io.SEEK_CUR)

    def load_all(self):
        data = num.fromfile(self._file, dtype='>i4').astype(num.float32)
        data *= micro_deg
        i = 11
        for polygon in self.polygons:
            if self.data_type == 'coastlines' and polygon.level_no in (1, 3):
                polygon._points = data[i+polygon.npoints*2-1:i-1:-1].reshape(
                    (polygon.npoints, 2))
            else:
                polygon._points = num.fliplr(
                    data[i:i+polygon.npoints*2].reshape((polygon.npoints, 2)))

            i += polygon.npoints * 2 + 11

        assert i - 11 == data.size

    @classmethod
    def _get_database(cls, filename):
        file = path.join(config.gshhg_dir, filename)
        if not path.exists(file):
            from pyrocko import util
            import zipfile

            archive_path = path.join(config.gshhg_dir,
                                     path.basename(cls.gshhg_url))
            util.download_file(
                cls.gshhg_url, archive_path,
                status_callback=get_download_callback(
                    'Downloading GSHHG database...'))
            if not zipfile.is_zipfile(archive_path):
                raise util.DownloadError('GSHHG file is corrupted!')
            logger.info('Unzipping GSHHG database...')
            zipf = zipfile.ZipFile(archive_path)
            zipf.extractall(config.gshhg_dir)
        else:
            logger.debug('Using cached %s' % filename)
        return file

    def get_polygons_at(self, lat, lon):
        '''
        Get all polygons whose bounding boxes contain point.

        :param lat: Latitude in [deg]
        :type lat: float
        :param lon: Longitude in [deg]
        :type lon: float
        :returns: List of :class:`~pyrocko.dataset.gshhg.Polygon`
        :rtype: list
        '''
        rp = []
        for p in self.polygons:
            if point_in_bounding_box((lat, lon), p.get_bounding_box()):
                rp.append(p)
        return rp

    def get_polygons_within(self, west, east, south, north):
        '''
        Get all polygons whose bounding boxes intersect with a bounding box.

        :param west: Western boundary in decimal degree
        :type west: float
        :param east: Eastern boundary in decimal degree
        :type east: float
        :param north: Northern boundary in decimal degree
        :type north: float
        :param south: Southern boundary in decimal degree
        :type south: float
        :returns: List of :class:`~pyrocko.dataset.gshhg.Polygon`
        :rtype: list
        '''

        assert is_valid_bounding_box((west, east, south, north))

        rp = []
        for p in self.polygons:
            if bounding_boxes_overlap(
                    p.get_bounding_box(), (west, east, south, north)):

                rp.append(p)
        return rp


class Coastlines(GSHHGBase):

    data_type = 'coastlines'

    def is_point_on_land(self, lat, lon):
        '''
        Check whether a point is on land.

        Lakes are considered not land.

        :param lat: Latitude in [deg]
        :type lat: float
        :param lon: Longitude in [deg]
        :type lon: float

        :rtype: bool
        '''

        relevant_polygons = self.get_polygons_at(lat, lon)
        relevant_polygons.sort()

        land = False
        for p in relevant_polygons:
            if (p.is_land() or p.is_antarctic_grounding_line() or
               p.is_island_in_lake()):
                if p.contains_point((lat, lon)):
                    land = True
            elif (p.is_lake() or p.is_antarctic_icefront() or
                  p.is_pond_in_island_in_lake()):
                if p.contains_point((lat, lon)):
                    land = False
        return land

    def get_land_mask(self, points):
        '''
        Check whether given points are on land.

        Lakes are considered not land.

        :param points: Array of (lat, lon) pairs, shape (N, 2).
        :type points: :class:`numpy.ndarray`
        :return: Boolean land mask
        :rtype: :class:`numpy.ndarray` of shape (N,)
        '''

        west, east, south, north = bounding_box_covering_points(points)

        relevant_polygons = self.get_polygons_within(west, east, south, north)
        relevant_polygons.sort()

        mask = num.zeros(points.shape[0], dtype=bool)
        for p in relevant_polygons:
            if (p.is_land() or p.is_antarctic_grounding_line() or
               p.is_island_in_lake()):
                land = p.contains_points(points)
                mask[land] = True
            elif p.is_lake() or p.is_pond_in_island_in_lake():
                water = p.contains_points(points)
                mask[water] = False
        return mask

    @classmethod
    def full(cls):
        '''
        Return the full-resolution GSHHG database.
        '''
        return cls(cls._get_database('gshhs_f.b'))

    @classmethod
    def high(cls):
        '''
        Return the high-resolution GSHHG database.
        '''
        return cls(cls._get_database('gshhs_h.b'))

    @classmethod
    def intermediate(cls):
        '''
        Return the intermediate-resolution GSHHG database.
        '''
        return cls(cls._get_database('gshhs_i.b'))

    @classmethod
    def low(cls):
        '''
        Return the low-resolution GSHHG database.
        '''
        return cls(cls._get_database('gshhs_l.b'))

    @classmethod
    def crude(cls):
        '''
        Return the crude-resolution GSHHG database.
        '''
        return cls(cls._get_database('gshhs_c.b'))


GSHHG = Coastlines  # backwards compatibility


class Borders(GSHHGBase):

    data_type = 'borders'

    @classmethod
    def full(cls):
        '''
        Return the full-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_borders_f.b'))

    @classmethod
    def high(cls):
        '''
        Return the high-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_borders_h.b'))

    @classmethod
    def intermediate(cls):
        '''
        Return the intermediate-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_borders_i.b'))

    @classmethod
    def low(cls):
        '''
        Return the low-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_borders_l.b'))

    @classmethod
    def crude(cls):
        '''
        Return the crude-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_borders_c.b'))


class Rivers(GSHHGBase):

    data_type = 'rivers'

    @classmethod
    def full(cls):
        '''
        Return the full-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_rivers_f.b'))

    @classmethod
    def high(cls):
        '''
        Return the high-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_rivers_h.b'))

    @classmethod
    def intermediate(cls):
        '''
        Return the intermediate-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_rivers_i.b'))

    @classmethod
    def low(cls):
        '''
        Return the low-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_rivers_l.b'))

    @classmethod
    def crude(cls):
        '''
        Return the crude-resolution GSHHG database.
        '''
        return cls(cls._get_database('wdb_rivers_c.b'))
