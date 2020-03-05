from __future__ import division, print_function, absolute_import

import unittest
import logging
import os

import numpy as num
from pyrocko import gf, util
from pyrocko.modelling import DislocationInverter

logger = logging.getLogger('pyrocko.test.test_gf_source_types')

km = 1e3

show_plot = int(os.environ.get('MPL_SHOW', 0))


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

    def test_pseudo_dynamic_rupture(self):
        store_id = 'crust2_dd'

        if not os.path.exists(os.path.join('/home/mmetz/src/gf_stores', store_id)):
            gf.ws.download_gf_store(site='kinherd', store_id=store_id)

        engine = gf.LocalEngine(store_superdirs=['.', '/home/mmetz/src/gf_stores'])
        store = engine.get_store(store_id)

        pdr = gf.PseudoDynamicRupture(
            length=20000., width=10000., depth=2000.,
            anchor='top', gamma=0.8, dip=90., strike=0.,
            nucleation_x=0., nucleation_y=0.,
            decimation_factor=10, eikonal_factor=0.5)

        points, _, vr, times = pdr.discretize_time(store)
        assert times.shape == vr.shape
        assert points.shape[0] == times.shape[0] * times.shape[1]

        pdr.discretize_patches(
            store=store,
            interpolation='nearest_neighbor',
            nucleation_x=0.,
            nucleation_y=0.)

        stress_field = num.zeros((len(pdr.patches) * 3, 1))
        stress_field[2::3] = -0.5e6
        pdr.tractions = stress_field

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

if __name__ == '__main__':
    util.setup_logging('test_gf_source_types', 'warning')
    unittest.main(defaultTest='GFSourceTypesTestCase')
