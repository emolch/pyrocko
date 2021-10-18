import os
import unittest
import math
import random

import numpy as num
import logging

from pyrocko import orthodrome, util
from pyrocko import orthodrome_ext
from ..common import Benchmark
from pyrocko import config
from pyrocko import guts
from pyrocko.model.location import Location

logger = logging.getLogger('pyrocko.test.test_orthodrome')
benchmark = Benchmark()

earth_oblateness = 1./298.257223563
earthradius_equator = 6378.14 * 1000.
earthradius = config.config().earthradius

r2d = 180./math.pi
d2r = 1./r2d
km = 1000.

plot = int(os.environ.get('MPL_SHOW', 0))

assert_ae = num.testing.assert_almost_equal
assert_allclose = num.testing.assert_allclose


def random_lat(mi=-90., ma=90., rstate=None, size=None):
    if rstate is None:
        rstate = num.random
    mi_ = 0.5*(math.sin(mi * math.pi/180.)+1.)
    ma_ = 0.5*(math.sin(ma * math.pi/180.)+1.)
    return num.arcsin(rstate.uniform(mi_, ma_, size=size)*2.-1.)*180./math.pi


def random_lon(mi=-180., ma=180., rstate=None, size=None):
    if rstate is None:
        rstate = num.random

    return rstate.uniform(mi, ma, size=size)


def random_circle(npoints=100):
    radius = num.random.uniform(0*km, 20000*km)
    lat0, lon0 = random_lat(), random_lon()
    phis = num.linspace(0., 2.*math.pi, npoints, endpoint=False)
    ns, es = radius*num.sin(phis), radius*num.cos(phis)
    lats, lons = orthodrome.ne_to_latlon(lat0, lon0, ns, es)
    circle = num.vstack([lats, lons]).T
    return lat0, lon0, radius, circle


def light(color, factor=0.5):
    return tuple(1-(1-c)*factor for c in color)


def dark(color, factor=0.5):
    return tuple(c*factor for c in color)


def have_geographiclib():
    try:
        from geographiclib.geodesic import Geodesic  # noqa
        return True

    except ImportError:
        return False


class OrthodromeTestCase(unittest.TestCase):

    @classmethod
    def tearDownClass(self):
        print(benchmark)

    def get_critical_random_locations(self, ntest):
        '''
        Create list of random (lat1, lon1, lat2, lon2) including critical
        locations.
        '''

        nasty_locations = [
            (0., 0., 0., 0.),
            (90., 0., -90., 0.),
            (0., -180., 0., 180.),
        ]

        assert ntest >= len(nasty_locations)

        lats1 = num.random.uniform(-90., 90., ntest)
        lats2 = num.random.uniform(-90., 90., ntest)
        lons1 = num.random.uniform(-180., 180., ntest)
        lons2 = num.random.uniform(-180., 180., ntest)

        for i, llll in enumerate(nasty_locations):
            lats1[i], lons1[i], lats2[i], lons2[i] = llll

        return lats1, lons1, lats2, lons2

    def testRaisesValueError(self):
        for lat1, lon1, lat2, lon2 in [
                (91., 0., 0., 0.),
                (0., 181., 0., 0.),
                (0., 0., 91., 0.),
                (0., 0., 0., 181.), ]:
            for f in [1, -1]:

                lat1 *= f
                lon1 *= f
                lat2 *= f
                lon2 *= f

                with self.assertRaises(ValueError):
                    orthodrome_ext.azibazi(lat1, lon1, lat2, lon2)

                with self.assertRaises(ValueError):
                    orthodrome_ext.distance_accurate50m(lat1, lon1, lat2, lon2)

    @benchmark
    def testAziBaziPython(self):
        ntest = 10000
        lats1, lons1, lats2, lons2 = self.get_critical_random_locations(ntest)
        for i in range(ntest):
            orthodrome.azibazi(
                float(lats1[i]), float(lons1[i]),
                float(lats2[i]), float(lons2[i]),
                implementation='python')

    @benchmark
    def testAziBaziC(self):
        ntest = 10000
        lats1, lons1, lats2, lons2 = self.get_critical_random_locations(ntest)
        for i in range(ntest):
            orthodrome.azibazi(
                lats1[i], lons1[i], lats2[i], lons2[i],
                implementation='c')

    def testAziBaziPythonC(self):
        ntest = 100
        lats1, lons1, lats2, lons2 = self.get_critical_random_locations(ntest)

        for i in range(ntest):
            azibazi_py = orthodrome.azibazi(
                float(lats1[i]), float(lons1[i]),
                float(lats2[i]), float(lons2[i]),
                implementation='python')
            azibazi_c = orthodrome.azibazi(
                lats1[i], lons1[i], lats2[i], lons2[i],
                implementation='c')

            assert_ae(azibazi_py, azibazi_c)

    @benchmark
    def testAziBaziArrayPython(self):
        ntest = 10000
        locs = self.get_critical_random_locations(ntest)
        orthodrome.azibazi_numpy(
            *locs,
            implementation='python')

    @benchmark
    def testAziBaziArrayC(self):
        ntest = 10000
        locs = self.get_critical_random_locations(ntest)
        orthodrome.azibazi_numpy(
            *locs,
            implementation='c')

    def testAziBaziArrayPythonC(self):
        ntest = 10000

        lats1, lons1, lats2, lons2 = self.get_critical_random_locations(ntest)

        azis_c, bazis_c = orthodrome.azibazi_numpy(
            lats1, lons1, lats2, lons2,
            implementation='c')

        azis_py, bazis_py = orthodrome.azibazi_numpy(
            lats1, lons1, lats2, lons2,
            implementation='python')

        for i in range(ntest):
            azi_py, bazi_py = orthodrome.azibazi(
                float(lats1[i]), float(lons1[i]),
                float(lats2[i]), float(lons2[i]),
                implementation='python')

            azi_c, bazi_c = orthodrome.azibazi(
                lats1[i], lons1[i], lats2[i], lons2[i],
                implementation='c')

            assert_ae(azi_py, azis_py[i])
            assert_ae(bazi_py, bazis_py[i])
            assert_ae(azi_c, azis_c[i])
            assert_ae(bazi_c, bazis_c[i])

        assert_ae(azis_py, azis_c)
        assert_ae(bazis_py, bazis_c)

    @benchmark
    def testDistancePython(self):
        ntest = 1000
        lats1, lons1, lats2, lons2 = self.get_critical_random_locations(ntest)
        loc1 = orthodrome.Loc(0., 0.)
        loc2 = orthodrome.Loc(0., 0.)
        for i in range(ntest):
            loc1.lat, loc1.lon = lats1[i], lons1[i]
            loc2.lat, loc2.lon = lats2[i], lons2[i]
            orthodrome.distance_accurate50m(
                loc1, loc2,
                implementation='python')

    @benchmark
    def testDistanceC(self):
        ntest = 1000
        lats1, lons1, lats2, lons2 = self.get_critical_random_locations(ntest)
        for i in range(ntest):
            orthodrome.distance_accurate50m(
                lats1[i], lons1[i], lats2[i], lons2[i],
                implementation='c')

    def testDistancePythonC(self):
        ntest = 100
        lats1, lons1, lats2, lons2 = self.get_critical_random_locations(ntest)
        for i in range(ntest):
            dist_py = orthodrome.distance_accurate50m(
                lats1[i], lons1[i], lats2[i], lons2[i],
                implementation='python')
            dist_c = orthodrome.distance_accurate50m(
                lats1[i], lons1[i], lats2[i], lons2[i],
                implementation='c')
            assert_ae(dist_py, dist_c)

    @benchmark
    def testDistanceArrayPython(self):
        ntest = 10000
        locs = self.get_critical_random_locations(ntest)
        orthodrome.distance_accurate50m_numpy(*locs, implementation='python')

    @benchmark
    def testDistanceArrayC(self):
        ntest = 10000
        locs = self.get_critical_random_locations(ntest)
        orthodrome.distance_accurate50m_numpy(*locs, implementation='c')

    def testDistanceArrayPythonC(self):
        ntest = 10000
        locs = self.get_critical_random_locations(ntest)
        a = orthodrome.distance_accurate50m_numpy(
            *locs,
            implementation='python')
        b = orthodrome.distance_accurate50m_numpy(
            *locs,
            implementation='c')
        num.testing.assert_array_almost_equal(a, b)

    def testGridDistances(self):
        for i in range(100):
            gsize = random.uniform(0., 1.)*2.*10.**random.uniform(4., 7.)
            north_grid, east_grid = num.meshgrid(
                num.linspace(-gsize/2., gsize/2., 11),
                num.linspace(-gsize/2., gsize/2., 11))

            north_grid = north_grid.flatten()
            east_grid = east_grid.flatten()

            lon = random.uniform(-180., 180.)
            lat = random.uniform(-90., 90.)

            lat_grid, lon_grid = orthodrome.ne_to_latlon(
                lat, lon, north_grid, east_grid)
            lat_grid_alt, lon_grid_alt = \
                orthodrome.ne_to_latlon_alternative_method(
                    lat, lon, north_grid, east_grid)

            for la, lo, no, ea in zip(
                    lat_grid, lon_grid, north_grid, east_grid):
                a = orthodrome.Loc(lat=la, lon=lo)
                b = orthodrome.Loc(lat=lat, lon=lon)

                cd = orthodrome.cosdelta(a, b)
                assert cd <= 1.0
                d = num.arccos(cd)*earthradius
                d2 = math.sqrt(no**2+ea**2)
                assert abs(d-d2) < 1.0e-3 or d2 < 10.

    def testLocationObjects(self):

        class Dummy(object):
            def __init__(self, lat, lon, depth):
                self.lat = lat
                self.lon = lon
                self.depth = depth

        a0 = Location(lat=10., lon=12., depth=1100.)
        a1 = guts.clone(a0)
        a1.set_origin(lat=9., lon=11)

        b0 = Location(lat=11., lon=13., depth=2100.)
        b1 = guts.clone(b0)
        b1.set_origin(lat=9., lon=11)
        b2 = Dummy(b0.lat, b0.lon, b0.depth)

        dist_ab = orthodrome.distance_accurate50m(
            a0.lat, a0.lon, b0.lat, b0.lon)

        azi_ab, bazi_ab = orthodrome.azibazi(
            a0.lat, a0.lon, b0.lat, b0.lon)

        def g_to_e(*args):
            return num.array(orthodrome.geodetic_to_ecef(*args))

        a_vec = g_to_e(a0.lat, a0.lon, -a0.depth)
        b_vec = g_to_e(b0.lat, b0.lon, -b0.depth)

        dist_3d_compare = math.sqrt(num.sum((a_vec - b_vec)**2))

        north_shift_compare, east_shift_compare = orthodrome.latlon_to_ne(
            a0.lat, a0.lon, b0.lat, b0.lon)

        for a in [a0, a1]:
            for b in [b0, b1, b2]:
                dist = a.distance_to(b)
                assert_allclose(dist, dist_ab)

                dist_3d = a.distance_3d_to(b)
                assert_allclose(dist_3d, dist_3d_compare, rtol=0.001)

                azi, bazi = a.azibazi_to(b)
                assert_allclose(azi % 360., azi_ab % 360., rtol=1e-2)
                assert_allclose(bazi % 360., bazi_ab % 360., rtol=1e-2)

                north_shift, east_shift = a.offset_to(b)
                assert_allclose(
                    (north_shift, east_shift),
                    (north_shift_compare, east_shift_compare), rtol=5e-3)

        for x, y in [(a0, a1), (b0, b1), (b0, b2), (b1, b2)]:
            dist = x.distance_to(y)
            assert_allclose(dist, 0.0)

    def test_wrap(self):
        assert orthodrome.wrap(11, -10, 10) == -9
        assert orthodrome.wrap(10, -10, 10) == -10
        assert orthodrome.wrap(10.001, -10, 10) == -9.999

    @unittest.skip('needs inspection')
    def test_local_distances(self):

        for reflat, reflon in [
                (0.0, 0.0),
                (10.0, 10.0),
                (90.0, 0.0),
                (-90.0, 0.0),
                (0.0, 180.0),
                (0.0, -180.0),
                (90.0, 180.0)]:

            north, east = serialgrid(num.linspace(-10*km, 10*km, 21),
                                     num.linspace(-10*km, 10*km, 21))

            lat, lon = orthodrome.ne_to_latlon2(reflat, reflon, north, east)
            north2, east2 = orthodrome.latlon_to_ne2(reflat, reflon, lat, lon)
            dist1 = num.sqrt(north**2 + east**2)
            dist2 = num.sqrt(north2**2 + east2**2)
            dist3 = orthodrome.distance_accurate15nm(reflat, reflon, lat, lon)
            assert num.all(num.abs(dist1-dist2) < 0.0001)
            assert num.all(num.abs(dist1-dist3) < 0.0001)

    def test_midpoint(self):
        center_lons = num.linspace(0., 180., 5)
        center_lats = [0., 89.]
        npoints = 10000
        half_side_length = 1000000.
        distance_error_max = 50000.
        for lat in center_lats:
            for lon in center_lons:
                n = num.random.uniform(
                    -half_side_length, half_side_length, npoints)
                e = num.random.uniform(
                    -half_side_length, half_side_length, npoints)
                dlats, dlons = orthodrome.ne_to_latlon(lat, lon, n, e)
                clat, clon = orthodrome.geographic_midpoint(dlats, dlons)
                d = orthodrome.distance_accurate50m_numpy(
                    clat, clon, lat, lon)[0]

                if plot:
                    import matplotlib.pyplot as plt
                    fig = plt.figure()
                    ax = fig.add_subplot(111)
                    ax.scatter(n, e)
                    c_n, c_e = orthodrome.latlon_to_ne_numpy(
                        lat, lon, clat, clon)
                    ax.plot(c_n, c_e, 'ro')
                    plt.show()

                self.assertTrue(d < distance_error_max, 'Distance %s > %s' %
                                (d, distance_error_max) +
                                '(maximum error)\n tested lat/lon: %s/%s' %
                                (lat, lon))

    @unittest.skipUnless(have_geographiclib(), 'geographiclib not available')
    def test_geodetic_to_ecef(self):
        orthodrome.geodetic_to_ecef(23., 0., 0.)

        a = orthodrome.earthradius_equator
        b = orthodrome.earthradius_equator * (1. - orthodrome.earth_oblateness)

        points = [
            ((90., 0., 0.), (0., 0., b)),
            ((-90., 0., 10.), (0., 0., -b-10.)),
            ((0., 0., 0.), (a, 0., 0.))]

        for p in points:
            assert_ae(orthodrome.geodetic_to_ecef(*p[0]), p[1])

    @unittest.skipUnless(have_geographiclib(), 'geographiclib not available')
    def test_ecef_to_geodetic(self):
        ncoords = 5
        lats = num.random.uniform(-90., 90, size=ncoords)
        lons = num.random.uniform(-180., 180, size=ncoords)
        alts = num.random.uniform(0, 10, size=ncoords)

        coords = num.array([lats, lons, alts]).T

        for ic in range(coords.shape[0]):
            xyz = orthodrome.geodetic_to_ecef(*coords[ic, :])
            latlonalt = orthodrome.ecef_to_geodetic(*xyz)

            assert_ae(coords[ic, :], latlonalt)

    def test_rotations(self):
        for lat in num.linspace(-90., 90., 20):
            for lon in num.linspace(-180., 180., 20):
                point = num.array([lat, lon], dtype=float)
                xyz = orthodrome.latlon_to_xyz(point)
                rot = orthodrome.rot_to_00(point[0], point[1])
                p2 = num.dot(rot, xyz)
                num.testing.assert_allclose(p2, [1., 0., 0.], atol=1.0e-7)

    def test_rotation2(self):
        eps = 1.0e-7
        lats = num.linspace(50., 60., 20)
        lons = num.linspace(170., 180., 20)
        lats2 = num.repeat(lats, lons.size)
        lons2 = num.tile(lons, lats.size)
        points = num.vstack((lats2, lons2)).T
        xyz = orthodrome.latlon_to_xyz(points)
        rot = orthodrome.rot_to_00(lats[0], lons[0])
        xyz2 = num.dot(rot, xyz.T).T
        points2 = orthodrome.xyz_to_latlon(xyz2)
        assert num.all(points2[:, 1] > -eps)

    def test_point_in_polygon(self):

        if plot:
            import matplotlib.pyplot as plt

        for i in range(100):
            if plot:
                plt.clf()
                axes = plt.gca()

            lat0, lon0, radius, circle = random_circle(100)
            if plot:
                print(lat0, lon0, radius)

            lats = num.linspace(-90., 90., 100)
            lons = num.linspace(-180., 180., 200)

            points = num.empty((lons.size*lats.size, 2))
            points[:, 0] = num.repeat(lats, lons.size)
            points[:, 1] = num.tile(lons, lats.size)

            mask = orthodrome.contains_points(circle, points)
            distances = orthodrome.distance_accurate50m_numpy(
                lat0, lon0, points[:, 0], points[:, 1])

            mask2 = distances < radius
            mask3 = num.logical_and(
                num.not_equal(mask2, mask),
                num.abs(distances - radius) > radius / 100.)

            if plot:
                axes.plot(
                    circle[:, 1], circle[:, 0], 'o',
                    ms=1, color='black')
                axes.plot(
                    points[mask, 1], points[mask, 0], 'o',
                    ms=1, alpha=0.2, color='black')
                axes.plot(
                    points[mask3, 1], points[mask3, 0], 'o',
                    ms=1, color='red')

            if plot:
                plt.show()

            assert not num.any(mask3)

    def test_point_in_region(self):
        testdata = [
            ((-20., 180.), (-180., 180., -90., 90.), True),
            ((-20., 180.), (170., -170., -90., 90.), True),
            ((-20., 160.), (170., -170., -90., 90.), False),
            ((-20., -160.), (170., -170., -90., 90.), False),
        ]

        for point, region, in_region in testdata:
            assert bool(orthodrome.point_in_region(point, region)) == in_region

    def test_track_distance(self):
        start = (0., 0.)
        end = (0., 1.)
        point = (0., 1.)

        distance = orthodrome.crosstrack_distance(
            start[0], start[1], end[0], end[1], point[0], point[1])
        assert distance == 0.

        point = (0., 0.)
        distance = orthodrome.crosstrack_distance(
            start[0], start[1], end[0], end[1], point[0], point[1])
        assert distance == 0.

        point = (0., .5)
        distance = orthodrome.crosstrack_distance(
            start[0], start[1], end[0], end[1], point[0], point[1])
        assert distance == 0.

        point = (1., 0.)
        distance = orthodrome.crosstrack_distance(
            start[0], start[1], end[0], end[1], point[0], point[1])
        num.testing.assert_almost_equal(abs(distance), 1.)

        point = (1., .5)
        distance = orthodrome.crosstrack_distance(
            start[0], start[1], end[0], end[1], point[0], point[1])
        num.testing.assert_almost_equal(abs(distance), 1.)

        point = (1., .5)
        distance = orthodrome.alongtrack_distance(
            start[0], start[1], end[0], end[1], point[0], point[1])
        num.testing.assert_almost_equal(abs(distance), .5)

        point = (1., .5)
        distance = orthodrome.alongtrack_distance_m(
            start[0], start[1], end[0], end[1], point[0], point[1])
        num.testing.assert_almost_equal(
            abs(distance),
            orthodrome.distance_accurate50m(
                orthodrome.Loc(*start), orthodrome.Loc(0., .5))
        )


def serialgrid(x, y):
    return num.repeat(x, y.size), num.tile(y, x.size)


def plot_erroneous_ne_to_latlon():
    import gmtpy
    import random
    import subprocess
    import time

    while True:
        w, h = 20, 15

        gsize = random.uniform(0., 1.)*4.*10.**random.uniform(4., 7.)
        north_grid, east_grid = num.meshgrid(
            num.linspace(-gsize/2., gsize/2., 11),
            num.linspace(-gsize/2., gsize/2., 11))

        north_grid = north_grid.flatten()
        east_grid = east_grid.flatten()

        lat_delta = gsize/earthradius*r2d*2.
        lon = random.uniform(-180., 180.)
        lat = random.uniform(-90., 90.)

        print(gsize/1000.)

        lat_grid, lon_grid = orthodrome.ne_to_latlon(
            lat, lon, north_grid, east_grid)
        lat_grid_alt, lon_grid_alt = \
            orthodrome.ne_to_latlon_alternative_method(
                lat, lon, north_grid, east_grid)

        maxerrlat = num.max(num.abs(lat_grid-lat_grid_alt))
        maxerrlon = num.max(num.abs(lon_grid-lon_grid_alt))
        eps = 1.0e-8
        if maxerrlon > eps or maxerrlat > eps:
            print(lat, lon, maxerrlat, maxerrlon)

            gmt = gmtpy.GMT(
                config={
                    'PLOT_DEGREE_FORMAT': 'ddd.xxxF',
                    'PAPER_MEDIA': 'Custom_%ix%i' % (w*gmtpy.cm, h*gmtpy.cm),
                    'GRID_PEN_PRIMARY': 'thinnest/0/50/0'})

            south = max(-85., lat - 0.5*lat_delta)
            north = min(85., lat + 0.5*lat_delta)

            lon_delta = lat_delta/math.cos(lat*d2r)

            delta = lat_delta/360.*earthradius*2.*math.pi
            scale_km = gmtpy.nice_value(delta/10.)/1000.

            west = lon - 0.5*lon_delta
            east = lon + 0.5*lon_delta

            x, y = (west, east), (south, north)
            xax = gmtpy.Ax(mode='min-max', approx_ticks=4.)
            yax = gmtpy.Ax(mode='min-max', approx_ticks=4.)
            scaler = gmtpy.ScaleGuru(data_tuples=[(x, y)], axes=(xax, yax))
            scaler['R'] = '-Rg'
            layout = gmt.default_layout()
            mw = 2.5*gmtpy.cm
            layout.set_fixed_margins(
                mw, mw, mw/gmtpy.golden_ratio, mw/gmtpy.golden_ratio)
            widget = layout.get_widget()
            # widget['J'] =  ('-JT%g/%g'  % (lon, lat)) + '/%(width)gp'
            widget['J'] = (
                '-JE%g/%g/%g' % (lon, lat, min(lat_delta/2., 180.)))\
                + '/%(width)gp'
            aspect = gmtpy.aspect_for_projection(*(widget.J() + scaler.R()))
            widget.set_aspect(aspect)

            gmt.psbasemap(
                B='5g5',
                L=('x%gp/%gp/%g/%g/%gk' % (
                    widget.width()/2., widget.height()/7.,
                    lon, lat, scale_km)),
                *(widget.JXY()+scaler.R()))

            gmt.psxy(
                in_columns=(lon_grid, lat_grid),
                S='x10p', W='1p/200/0/0', *(widget.JXY()+scaler.R()))
            gmt.psxy(
                in_columns=(lon_grid_alt, lat_grid_alt),
                S='c10p', W='1p/0/0/200', *(widget.JXY()+scaler.R()))

            gmt.save('orthodrome.pdf')
            subprocess.call(['xpdf', '-remote', 'ortho', '-reload'])
            time.sleep(2)
        else:
            print('ok', gsize, lat, lon)


if __name__ == '__main__':
    plot = False
    util.setup_logging('test_orthodrome', 'warning')
    unittest.main(exit=False)
    print(benchmark)
