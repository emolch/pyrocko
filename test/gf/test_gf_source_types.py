from __future__ import division, print_function, absolute_import

import unittest
import logging
import os

import numpy as num
from pyrocko import gf, util, trace
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

    @unittest.skipUnless(*have_store('crust2_ib'))
    def test_pseudo_dynamic_rupture(self):
        store_id = 'crust2_ib'

        engine = gf.get_engine()
        store = engine.get_store(store_id)

        pdr = gf.PseudoDynamicRupture(
            length=20000., width=10000., depth=2000.,
            anchor='top', gamma=0.8, dip=90., strike=0.,
            nucleation_x=0., nucleation_y=0.)

        points, _, vr, times = pdr.discretize_time(store)
        assert times.shape == vr.shape
        assert points.shape[0] == times.shape[0] * times.shape[1]

        pdr.discretize_patches(
            store=store,
            interpolation='nearest_neighbor',
            nucleation_x=0.,
            nucleation_y=0.)

        pdr.tractions = gf.tractions.HomogeneousTractions(
            strike=0.,
            dip=0.,
            normal=-.5e6)

        time = num.max(pdr.get_patch_attribute('time')) * 0.5

        disloc_est = pdr.get_okada_slip(t=time)

        coef_mat = DislocationInverter.get_coef_mat(pdr.patches)

        assert (coef_mat == pdr.coef_mat).all()

        if show_plot:
            level = num.arange(0., 15., 1.5)

            import matplotlib.pyplot as plt
            x_val = points[:times.shape[1], 0]
            y_val = points[::times.shape[1], 2]

            plt.gcf().add_subplot(1, 1, 1, aspect=1.0)
            plt.imshow(
                vr,
                extent=[
                    num.min(x_val), num.max(x_val),
                    num.max(y_val), num.min(y_val)])
            plt.contourf(x_val, y_val, times, level, cmap='gray', alpha=0.7)
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
            plt.colorbar(im, label='Opening [m] after %.2f s' % time)
            plt.show()

    @unittest.skipUnless(*have_store('crust2_ib'))
    def test_oversampling(self):
        store_id = 'crust2_ib'

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
                depth=5.*km,
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
