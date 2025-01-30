# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import logging
import unittest

import numpy as num

from numpy.testing import assert_almost_equal, assert_allclose

from pyrocko.model import Location
from pyrocko import gato, orthodrome as od

logger = logging.getLogger('test_gato.py')

km = 1000.
s_km = 0.001
d2r = num.pi/180.
r2d = 180./num.pi


class GatoTestCase(unittest.TestCase):

    def test_cartesian_location_grid(self):

        grid0 = gato.CartesianLocationGrid(
            origin=Location(lat=60., lon=10.))

        assert 0 == grid0.effective_dimension

        grid3 = gato.CartesianLocationGrid(
            origin=Location(lat=60., lon=10.),
            x_min=-2*km,
            x_max=2*km,
            x_delta=1*km,
            y_min=-3*km,
            y_max=3*km,
            y_delta=1*km,
            z_min=0*km,
            z_max=4*km,
            z_delta=1*km)

        assert 3 == grid3.effective_dimension

    def test_cartesian_location_grid_snap(self):
        for snap, mi, ma in [
                ('both', -10.*km, 10.*km),
                ('min', -10.1*km, 9.9*km),
                ('max', -9.9*km, 10.1*km)]:

            grid1 = gato.CartesianLocationGrid(
                origin=Location(lat=60., lon=10.),
                x_min=-9.9*km,
                x_max=9.9*km,
                x_delta=1*km,
                snap=snap)

            assert 1 == grid1.effective_dimension
            assert_almost_equal(grid1._x[0], mi)
            assert_almost_equal(grid1._x[-1], ma)

        with self.assertRaises(gato.GridSnapError):
            gato.CartesianLocationGrid(
                origin=Location(lat=60., lon=10.),
                x_min=-9.9*km,
                x_max=9.9*km,
                x_delta=1*km,
                snap='fail')

    def test_cartesian_location_grid_rot(self):

        grid = gato.CartesianLocationGrid(
            origin=Location(lat=60., lon=10.),
            x_min=1*km,
            x_max=1*km,
            x_delta=1*km,
            y_min=2*km,
            y_max=2*km,
            y_delta=1*km,
            azimuth=90.,
            dip=90.)

        assert grid.shape == (1, 1, 1)

        assert_almost_equal(
            grid._get_ned()[0, :], [0*km, 1*km, 2*km])

    def test_cartesian_slowness_grid(self):

        grid0 = gato.CartesianSlownessGrid()
        assert 0 == grid0.effective_dimension

        grid = gato.CartesianSlownessGrid(
            sx_min=-2*s_km,
            sx_max=2*s_km,
            sx_delta=1*s_km,
            sy_min=-3*s_km,
            sy_max=3*s_km,
            sy_delta=1*s_km,
            sz_min=0*s_km,
            sz_max=4*s_km,
            sz_delta=1*s_km)

        assert 3 == grid.effective_dimension
        assert grid.shape == (5, 7, 5)
        assert grid.size == 5*7*5

    def test_cartesian_slowness_grid_rot(self):

        grid = gato.CartesianSlownessGrid(
            sx_min=1*s_km,
            sx_max=1*s_km,
            sx_delta=1*s_km,
            sy_min=2*s_km,
            sy_max=2*s_km,
            sy_delta=1*s_km,
            azimuth=90.,
            dip=90.)

        assert grid.shape == (1, 1, 1)
        assert grid.size == 1

        assert_almost_equal(
            grid._get_ned()[0, :], [0*s_km, 1*s_km, 2*s_km])

    def test_spherical_slowness_grid(self):

        grid0 = gato.SphericalSlownessGrid()
        assert 1 == grid0.effective_dimension

        grid = gato.SphericalSlownessGrid(
            sr_min=1*s_km,
            sr_max=3*s_km,
            sr_delta=1*s_km,
            stheta_min=45,
            stheta_max=135,
            stheta_delta=45,
            sphi_min=-90,
            sphi_max=45,
            sphi_delta=45)

        assert 3 == grid.effective_dimension
        assert grid.shape == (3, 3, 4)
        assert grid.size == 3*3*4

        rtp = grid._get_rtp()[0, :]
        print(rtp[2], rtp[1]*r2d, rtp[0]*r2d)
        print(grid._get_ned()[0, :])

        # ojo - i got here x, y, z as right handed coordinate system
        # as standard - but not
        # as intended with north --> x, east --> y and z --> down ....
        # - need to re-write _get_ned!
        assert_almost_equal(
            grid._get_ned()[0, :],
            [0*s_km, -0.5*num.sqrt(2)*s_km, 0.5*num.sqrt(2)*s_km])

    def test_unstructured_location_grid(self):
        grid = gato.UnstructuredLocationGrid(
            coordinates=num.array([
                [0., 0., 0., 0., 0.5*km, 0.0],
                [0., 0.01, 0., 0., 0.5*km, 0.0],
                [0.01, 0.01, 0., 0., 0.5*km, 0.0],
                [0.01, 0., 0., 0., 0.5*km, 0.0]]))

        dlat = od.distance_proj(0., 0., 0.01, 0.)
        dlon = od.distance_proj(0., 0., 0., 0.01)
        dd = 0.5*km
        d2lat = 0.5*dlat
        d2lon = 0.5*dlon

        center = grid.get_center()
        assert_allclose(
            (center.lat, center.lon, center.depth), (0.005, 0.005, 0.5*km),
            rtol=0.0001)

        lld = grid.get_nodes('latlondepth')
        assert lld.shape == (4, 3)

        ned1 = grid.get_nodes('ned')
        assert_allclose(
            ned1, [
                [-d2lat, -d2lon, 0.],
                [-d2lat, d2lon, 0.],
                [d2lat, d2lon, 0.],
                [d2lat, -d2lon, 0.]],
            atol=0.1)

        grid.origin = Location(lat=0., lon=0., depth=0.0)
        grid.update()
        ned2 = grid.get_nodes('ned')
        assert_allclose(
            ned2, [
                [0., 0., dd],
                [0., dlon, dd],
                [dlat, dlon, dd],
                [dlat, 0., dd]],
            atol=0.1)

        grid.set_origin_to_center()
        grid.update()
        ned3 = grid.get_nodes('ned')
        assert_allclose(
            ned3, [
                [-d2lat, -d2lon, 0.],
                [-d2lat, d2lon, 0.],
                [d2lat, d2lon, 0.],
                [d2lat, -d2lon, 0.]],
            atol=0.1)

    def test_generic_delay_table_cloc_uloc(self):
        gdt = gato.GenericDelayTable(
            source_grid=gato.CartesianLocationGrid(
                origin=Location(lat=60., lon=10.),
                x_min=-2*km,
                x_max=2*km,
                x_delta=4*km,
                y_min=-3*km,
                y_max=3*km,
                y_delta=6*km,
                z_min=0*km,
                z_max=4*km,
                z_delta=4*km,
                snap='max'),
            receiver_grid=gato.UnstructuredLocationGrid(
                coordinates=num.array([
                    [60., 10., -2*km, -3*km, 0., 0.],
                    [60., 10., 2*km, -3*km, 0., 0.],
                    [60., 10., -2*km, 3*km, 0., 0.],
                    [60., 10., 2*km, 3*km, 0., 0.]])),
            method=gato.SphericalWaveDM(
                velocity=2500.))

        delays = gdt.get_delays()
        ii = num.arange(4)
        assert delays.shape == (gdt.source_grid.size, gdt.receiver_grid.size)
        assert num.all(delays[ii, ii] == 0.)
        assert_allclose(delays[4+ii, ii], 4000./2500., atol=1e-6)

    def test_generic_delay_table_sgrid_uloc(self):
        gdt = gato.GenericDelayTable(
            source_grid=gato.CartesianSlownessGrid(
                sx_min=-1*s_km,
                sx_max=1*s_km,
                sx_delta=1*s_km,
                sy_min=-0.5*s_km,
                sy_max=0.5*s_km,
                sy_delta=1*s_km,
                snap='max'),
            receiver_grid=gato.UnstructuredLocationGrid(
                coordinates=num.array([
                    [0., 0., -1*km, -1*km, 0., 0.],
                    [0., 0., 1*km, -1*km, 0., 0.],
                    [0., 0., -1*km, 1*km, 0., 0.],
                    [0., 0., 1*km, 1*km, 0., 0.]])),
            method=gato.PlaneWaveDM())

        delays = gdt.get_delays()

        for isource, (sn, se, sd) in enumerate(
                gdt.source_grid.get_nodes('ned')):
            for ireceiver, (rn, re, rd) in enumerate(
                    gdt.receiver_grid.get_nodes('ned')):
                assert delays[isource, ireceiver] == sn*rn + se*re + sd*rd
