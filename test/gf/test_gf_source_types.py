from __future__ import division, print_function, absolute_import

import unittest
import logging
import os

import numpy as num
from pyrocko import gf, util, trace, moment_tensor as pmt, orthodrome as pod
from pyrocko.gf.seismosizer import map_anchor
from pyrocko.modelling import DislocationInverter

logger = logging.getLogger('pyrocko.test.test_gf_source_types')

km = 1e3
r2d = 180. / num.pi
d2r = num.pi / 180.

show_plot = int(os.environ.get('MPL_SHOW', 0))


def have_store(store_id):
    engine = gf.get_engine()
    try:
        engine.get_store(store_id)
        return True, ''
    except gf.NoSuchStore:
        return False, 'GF store "%s" not available' % store_id


class GFSourceTypesTestCase(unittest.TestCase):

    def test_rectangular_source(self):
        # WIP
        nsrc = 5
        rect_sources = []

        for n in range(nsrc):
            src = gf.RectangularSource(
                lat=0., lon=0.,
                anchor='bottom',
                north_shift=5000., east_shift=9000., depth=4.*km,
                width=2.*km, length=8.*km,
                dip=0., rake=0., strike=(180./nsrc + 1) * n,
                slip=1.)
            rect_sources.append(src)

    @staticmethod
    def plot_rectangular_source(src, store):
        from matplotlib import pyplot as plt
        from matplotlib.patches import Polygon
        ax = plt.gca()
        ne = src.outline(cs='xy')
        p = Polygon(num.fliplr(ne), fill=False, color='r', alpha=.7)
        ax.add_artist(p)

        mt = src.discretize_basesource(store)
        ax.scatter(mt.east_shifts, mt.north_shifts, alpha=1)
        ax.scatter(src.east_shift, src.north_shift, color='r')

        plt.axis('equal')
        plt.show()

    @unittest.skipUnless(*have_store('iceland_reg_v2'))
    def test_pseudo_dynamic_rupture(self):
        from matplotlib import pyplot as plt

        store_id = 'iceland_reg_v2'

        engine = gf.get_engine()
        store = engine.get_store(store_id)

        moment = 1e19
        nucleation_x, nucleation_y = 0., 0.

        pdr = gf.PseudoDynamicRupture(
            length=20000., width=10000., depth=2000.,
            anchor='top', gamma=0.8, dip=45., strike=60.,
            moment=moment, nx=5, ny=3, smooth_rupture=False,
            decimation_factor=1000)

        # Check magnitude calculations
        assert pdr.magnitude == pmt.moment_to_magnitude(moment)
        assert pdr.get_magnitude() == pmt.moment_to_magnitude(moment)

        # Check nucleation setting
        pdr.nucleation = num.array([[nucleation_x, nucleation_y]])
        assert pdr.nucleation_x == num.array(nucleation_x)
        assert pdr.nucleation_y == num.array(nucleation_y)
        num.testing.assert_equal(
            pdr.nucleation, num.array([[nucleation_x, nucleation_y]]))

        # Check new nucleation time
        pdr.nucleation_time = 1.
        points_old, _, vr_old, times_old = pdr.discretize_time(store)
        assert times_old.shape == vr_old.shape
        assert points_old.shape[0] == times_old.shape[0] * times_old.shape[1]

        pdr._interpolators = {}
        pdr.nucleation_time = 0.

        points_new, _, vr_new, times_new = pdr.discretize_time(store)
        assert times_new.shape == times_old.shape
        num.testing.assert_allclose(times_new, times_old - 1., rtol=1e-7)
        num.testing.assert_allclose(vr_new, vr_old, rtol=1e-7)
        num.testing.assert_allclose(points_new, points_old, rtol=1e-7)

        pdr.discretize_patches(
            store=store,
            interpolation='nearest_neighbor')

        # Check moment calculation discretize basesource vs moment_rate_patches
        mom_rate_old, times_old = pdr.get_moment_rate_patches(store=store)
        mom_rate_new, times_new = pdr.get_moment_rate(store=store)

        cum_mom_old = (mom_rate_old * num.concatenate([
            (num.diff(times_old)[0],), num.diff(times_old)])).sum()

        num.testing.assert_allclose(cum_mom_old, moment, rtol=2e-3)
        num.testing.assert_equal(times_new, times_old)

        # Check magnitude scaling of slip and slip rate
        disloc_tmax = pdr.get_slip()
        disloc_tmax_max = num.linalg.norm(disloc_tmax, axis=1).max()

        pdr.magnitude = None
        pdr.slip = disloc_tmax_max

        # Large rtol due to interpolation and rounding differences induced by
        # get_moment calculation
        num.testing.assert_allclose(
            pdr.get_moment(store=store),
            moment,
            rtol=5e-2)

        deltat = pdr.get_patch_attribute('time').max() * 0.5
        deltaslip, times = pdr.get_delta_slip(deltat=deltat, delta=False)

        num.testing.assert_allclose(disloc_tmax, pdr.get_slip())
        num.testing.assert_allclose(disloc_tmax, deltaslip[:, -1, :])

        pdr.slip = None

        pdr.tractions = gf.tractions.HomogeneousTractions(
            strike=0.,
            dip=0.,
            normal=-.5e6)

        disloc_est = pdr.get_slip(t=deltat)

        # Check get delta slip function
        deltaslip, times_old = pdr.get_delta_slip(deltat=deltat)
        cumslip, times_new = pdr.get_delta_slip(deltat=deltat, delta=False)

        num.testing.assert_equal(times_old, times_new)
        num.testing.assert_equal(cumslip, num.cumsum(deltaslip, axis=1))

        # Check coefficient matrix calculation
        coef_mat = DislocationInverter.get_coef_mat(pdr.patches)
        assert (coef_mat == pdr.coef_mat).all()

        if show_plot:
            level = num.arange(0., 15., 1.5)

            x_val = points_old[:times_old.shape[1], 0]
            y_val = points_old[::times_old.shape[1], 2]

            plt.gcf().add_subplot(1, 1, 1, aspect=1.0)
            plt.imshow(
                vr_old,
                extent=[
                    num.min(x_val), num.max(x_val),
                    num.max(y_val), num.min(y_val)])
            plt.contourf(
                x_val, y_val, times_old, level, cmap='gray', alpha=0.7)
            plt.colorbar(label='Rupture Propagation Time [s]')
            plt.show()

            x_val = num.array([
                src.northing for src in pdr.patches])[:pdr.nx]
            y_val = num.array([
                src.depth for src in pdr.patches])[::pdr.nx]

            plt.gcf().add_subplot(1, 1, 1, aspect=1.0)
            im = plt.imshow(
                disloc_est[2::3].reshape(y_val.shape[0], x_val.shape[0]),
                extent=[
                    num.min(x_val), num.max(x_val),
                    num.max(y_val), num.min(y_val)])
            plt.contourf(
                x_val, y_val,
                pdr.get_patch_attribute('time').reshape(pdr.ny, pdr.nx),
                level,
                cmap='gray', alpha=0.5)
            plt.colorbar(im, label='Opening [m] after %.2f s' % deltat)
            plt.show()

    def test_pseudo_dynamic_rupture_outline(self):
        length = 20000.
        width = 10000.
        depth = 3400.
        north_shift = 1500.
        east_shift = -2000.

        pdr = gf.PseudoDynamicRupture(
            length=length, width=width, depth=depth,
            north_shift=north_shift, east_shift=east_shift,
            anchor='top', gamma=0.8, dip=90., strike=0.)

        points = num.array(
            [[-0.5 * length + north_shift, east_shift, depth],
             [0.5 * length + north_shift, east_shift, depth],
             [0.5 * length + north_shift, east_shift, depth + width],
             [-0.5 * length + north_shift, east_shift, depth + width],
             [-0.5 * length + north_shift, east_shift, depth]])

        num.testing.assert_allclose(
            points, pdr.outline(cs='xyz'), atol=1.)

        num.testing.assert_allclose(
            points[:, :2], pdr.outline(cs='xy'), atol=1.)

        latlon = pod.ne_to_latlon(pdr.lat, pdr.lon, points[:, 0], points[:, 1])
        latlon = num.array(latlon).T

        num.testing.assert_allclose(
            latlon,
            pdr.outline(cs='latlon'), atol=1.)

        num.testing.assert_allclose(
            latlon[:, ::-1],
            pdr.outline(cs='lonlat'), atol=1.)

        num.testing.assert_allclose(
            num.concatenate((latlon, points[:, 2].reshape((-1, 1))), axis=1),
            pdr.outline(cs='latlondepth'), atol=1.)

    def test_pseudo_dynamic_rupture_points_on_source(self):
        length = 20000.
        width = 10000.
        depth = 3400.
        north_shift = 1500.
        east_shift = -2000.

        pdr = gf.PseudoDynamicRupture(
            length=length, width=width, depth=depth,
            north_shift=north_shift, east_shift=east_shift,
            anchor='top', gamma=0.8, dip=90., strike=0.)

        random_points = num.concatenate((
            num.random.uniform(-1, 1, size=(10, 1)),
            num.random.uniform(-1., 1., size=(10, 1))), axis=1)

        points_xy = num.array(list(map_anchor.values()))
        points_xy = num.concatenate((points_xy, random_points))

        points = num.zeros((points_xy.shape[0], 3))
        points[:, 0] = 0.5 * points_xy[:, 0] * length + north_shift
        points[:, 1] = east_shift
        points[:, 2] = 0.5 * (points_xy[:, 1] + 1.) * width + depth

        num.testing.assert_allclose(
            points, pdr.points_on_source(
                points_x=points_xy[:, 0], points_y=points_xy[:, 1],
                cs='xyz'), atol=1.)

        num.testing.assert_allclose(
            points[:, :2], pdr.points_on_source(
                points_x=points_xy[:, 0], points_y=points_xy[:, 1],
                cs='xy'), atol=1.)

        latlon = pod.ne_to_latlon(pdr.lat, pdr.lon, points[:, 0], points[:, 1])
        latlon = num.array(latlon).T

        num.testing.assert_allclose(
            latlon,
            pdr.points_on_source(
                points_x=points_xy[:, 0], points_y=points_xy[:, 1],
                cs='latlon'), atol=1.)

        num.testing.assert_allclose(
            latlon[:, ::-1],
            pdr.points_on_source(
                points_x=points_xy[:, 0], points_y=points_xy[:, 1],
                cs='lonlat'), atol=1.)

        num.testing.assert_allclose(
            num.concatenate((latlon, points[:, 2].reshape((-1, 1))), axis=1),
            pdr.points_on_source(
                points_x=points_xy[:, 0], points_y=points_xy[:, 1],
                cs='latlondepth'), atol=1.)

    @unittest.skipUnless(*have_store('iceland_reg_v2'))
    def test_oversampling(self):
        store_id = 'iceland_reg_v2'

        comp_map = {
            'E': 0,
            'N': 1,
            'Z': 2
        }

        nazimuths = 12
        azimuths = num.linspace(0, num.pi*2, nazimuths)
        dist = 15*km

        coords = num.zeros((2, nazimuths))
        coords[0, :] = num.cos(azimuths)
        coords[1, :] = num.sin(azimuths)
        coords *= dist

        targets = [
            gf.Target(
                north_shift=coords[0, iazi],
                east_shift=coords[1, iazi],
                interpolation='multilinear',

                store_id=store_id,
                codes=('', 'S%01d' % iazi, '', channel))
            for iazi in range(nazimuths)
            for channel in comp_map.keys()]

        for t, azi in zip(targets, azimuths):
            t.azimuth = azi * r2d

        nsizes = 20
        length = num.linspace(10, 20, nsizes)
        width = num.linspace(5, 10, nsizes)

        fault_sizes = length * width * km**2

        engine = gf.get_engine()

        misfit_setup = trace.MisfitSetup(
            norm=2,
            taper=trace.CosFader(xfade=.5))

        mf = num.zeros((nazimuths*3, nsizes, 2))

        all_traces = []
        for isize in range(nsizes):
            source = gf.RectangularSource(
                depth=1.5*km,
                strike=0.,
                dip=90.,
                anchor='top',

                length=length[isize]*km,
                width=width[isize]*km,
                slip=2.)

            source_os = source.clone(aggressive_oversampling=True)

            resp = engine.process(source, targets, nthreads=6)
            resp_os = engine.process(source_os, targets, nthreads=6)

            traces = resp.pyrocko_traces()
            traces_os = resp_os.pyrocko_traces()

            for itr, (tr, tr_os) in enumerate(zip(traces, traces_os)):
                assert tr.channel == tr_os.channel
                assert tr.station == tr_os.station
                tr.set_location(str(isize))
                tr_os.set_location(str(isize))
                misfit, norm = tr.misfit(tr_os, misfit_setup)

                assert misfit <= .1
                mf[itr, isize, :] = (misfit, norm)

            all_traces += traces
            all_traces += traces_os

        if show_plot:
            import matplotlib.pyplot as plt
            from matplotlib.ticker import FuncFormatter
            from pyrocko import io

            logger.info('saving oversampling data to /tmp/test_os.mseed')
            io.save(all_traces, '/tmp/test_os.mseed')

            ax = plt.gca()

            for itr in range(mf.shape[0]):
                ax.plot(fault_sizes, mf[itr, :, 0], label='%d' % itr)

            ax.set_title(
                'Misfit aggressive oversampling\n'
                '%d azimuths at %d km distance, ENZ components' %
                (nazimuths, dist/km))
            ax.set_ylim(0, 1)
            ax.grid(alpha=.3)
            ax.set_ylabel('Misfit [time_domain | Lp = 2]')
            ax.set_xlabel('Fault area [km**2]')
            ax.xaxis.set_major_formatter(FuncFormatter(lambda x, v: x / km**2))

            plt.show()


if __name__ == '__main__':
    util.setup_logging('test_gf_source_types', 'warning')
    unittest.main(defaultTest='GFSourceTypesTestCase')
