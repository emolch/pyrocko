from __future__ import division, print_function, absolute_import
import os
import numpy as num
import unittest

from pyrocko import util
from pyrocko.modelling import DislocProcessor, DislocationInverter,\
    okada_ext, OkadaSource


d2r = num.pi / 180.
m2km = 1000.


show_plot = int(os.environ.get('MPL_SHOW', 0))


class OkadaTestCase(unittest.TestCase):
    def test_okada(self):
        n = 1

        north = num.linspace(0., 5., n)
        east = num.linspace(-5., 0., n)
        down = num.linspace(15., 5., n)

        strike = 0.
        dip = 0.
        rake = 90.
        slip = 1.0
        opening = 0.

        al1 = 0.
        al2 = 0.5
        aw1 = 0.
        aw2 = 0.25
        poisson = 0.25

        nthreads = 0

        source_patches = num.zeros((n, 9))
        source_patches[:, 0] = north
        source_patches[:, 1] = east
        source_patches[:, 2] = down
        source_patches[:, 3] = strike
        source_patches[:, 4] = dip
        source_patches[:, 5] = al1
        source_patches[:, 6] = al2
        source_patches[:, 7] = aw1
        source_patches[:, 8] = aw2

        source_disl = num.zeros((n, 3))
        source_disl[:, 0] = num.cos(rake * d2r) * slip
        source_disl[:, 1] = num.sin(rake * d2r) * slip
        source_disl[:, 2] = opening

        receiver_coords = source_patches[:, :3].copy()

        results = okada_ext.okada(
            source_patches, source_disl, receiver_coords, poisson, nthreads)

        assert results.shape == tuple((n, 12))

        source_list2 = [OkadaSource(
            lat=0., lon=0.,
            north_shift=north[i], east_shift=east[i],
            depth=down[i], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=strike, dip=dip,
            rake=rake, slip=slip, opening=opening, nu=poisson)
            for i in range(n)]
        source_patches2 = num.array([
            source.source_patch() for source in source_list2])
        assert (source_patches == source_patches2).all()

        source_disl2 = num.array([
            patch.source_disloc() for patch in source_list2])
        assert (source_disl == source_disl2).all()

        results2 = okada_ext.okada(
            source_patches2, source_disl2, receiver_coords, poisson, nthreads)
        assert (results == results2).all()

    def test_okada_vs_disloc_single_Source(self):
        north = 0.
        east = 0.
        depth = 10. * m2km
        length = 50. * m2km
        width = 10. * m2km

        strike = 45.
        dip = 89.
        rake = 90.
        slip = 1.0
        opening = 0.
        poisson = 0.25

        nthreads = 0

        al1 = -length / 2.
        al2 = length / 2.
        aw1 = -width
        aw2 = 0.

        nrec_north = 100
        nrec_east = 200
        rec_north = num.linspace(
            -2. * length + north, 2. * length + north, nrec_north)
        rec_east = num.linspace(
            -2. * length + east, 2. * length + east, nrec_east)
        nrec = nrec_north * nrec_east
        receiver_coords = num.zeros((nrec, 3))
        receiver_coords[:, 0] = num.tile(rec_north, nrec_east)
        receiver_coords[:, 1] = num.repeat(rec_east, nrec_north)

        segments = [OkadaSource(
            lat=0., lon=0.,
            north_shift=north, east_shift=east,
            depth=depth, al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=strike, dip=dip,
            rake=rake, slip=slip, opening=opening, nu=poisson)]

        res_ok2d = DislocProcessor.process(
            segments, num.array(receiver_coords[:, ::-1][:, 1:]))

        source_patch = num.array([patch.source_patch() for patch in segments])
        source_disl = num.array([patch.source_disloc() for patch in segments])
        res_ok3d = okada_ext.okada(
            source_patch, source_disl, receiver_coords, poisson, nthreads)

        def compare_plot(param1, param2):
            import matplotlib.pyplot as plt

            valmin = num.min([param1, param2])
            valmax = num.max([param1, param2])

            def add_subplot(
                fig, param, ntot, n, sharedaxis=None, title='',
                    vmin=None, vmax=None):

                ax = fig.add_subplot(
                    ntot, 1, n, sharex=sharedaxis, sharey=sharedaxis)
                scat = ax.scatter(
                    receiver_coords[:, 1], receiver_coords[:, 0], s=20,
                    c=param, vmin=vmin, vmax=vmax, cmap='seismic',
                    edgecolor='none')
                fig.colorbar(scat, shrink=0.8, aspect=5)
                rect = plt.Rectangle((
                    -num.sin(strike * d2r) * length / 2.,
                    -num.cos(strike * d2r) * length / 2.),
                    num.cos(dip * d2r) * width, length,
                    angle=-strike, edgecolor='green', facecolor='None')
                ax.add_patch(rect)
                ax.set_title(title)
                plt.axis('equal')
                return ax

            fig = plt.figure()
            ax = add_subplot(
                fig, 100. * (param1 - param2) / num.max(num.abs([
                    valmin, valmax])), 3, 1,
                title='Okada Surface minus Okada Halfspace [%]')
            add_subplot(
                fig, param1, 3, 2, sharedaxis=ax,
                title='Okada Surface', vmin=valmin, vmax=valmax)
            add_subplot(
                fig, param2, 3, 3, sharedaxis=ax,
                title='Okada Halfspace', vmin=valmin, vmax=valmax)

            plt.show()

        if show_plot:
            compare_plot(res_ok2d['displacement.e'], res_ok3d[:, 1])

    def test_okada_online_example(self):
        source_list = [OkadaSource(
            lat=0., lon=0., north_shift=0., east_shift=0., depth=50.,
            al1=-80., al2=120., aw1=-30., aw2=25., strike=0., dip=70.,
            opening=1., slip=2.5, rake=323.130103)]

        receiver_coords = num.array([10., -20., 30.])[num.newaxis, :]
        poisson = 1. / 6.

        u = okada_ext.okada(
            num.array([source.source_patch() for source in source_list]),
            num.array([source.source_disloc() for source in source_list]),
            receiver_coords, poisson, 0)

        u_check = num.array([-0.378981, -0.631789, -0.14960])
        # Example values from:
        # http://www.bosai.go.jp/study/application/dc3d/download/DC3Dmanual.pdf

        for i in range(3):
            vals = num.array([u[0][i], u_check[i]])
            assert num.abs(u[0][i]) - num.abs(u_check[i]) < 1e-5
            assert num.all(vals > 0.) or num.all(vals < 0.)

    def test_okada_GF_fill(self):
        ref_north = 0.
        ref_east = 0.
        ref_depth = 100000.

        nlength = 20
        nwidth = 16

        strike = 0.
        dip = 90.
        length = 0.5
        width = 0.5

        al1 = -length / 2.
        al2 = length / 2.
        aw1 = -width / 2.
        aw2 = width / 2.
        poisson = 0.25
        mu = 32. * 1e9

        npoints = nlength * nwidth
        source_coords = num.zeros((npoints, 3))

        for il in range(nlength):
            for iw in range(nwidth):
                idx = il * nwidth + iw
                source_coords[idx, 0] = \
                    num.cos(strike * d2r) * (
                        il * (num.abs(al1) + num.abs(al2)) + num.abs(al1)) - \
                    num.sin(strike * d2r) * num.cos(dip * d2r) * (
                        iw * (num.abs(aw1) + num.abs(aw2)) + num.abs(aw1)) + \
                    ref_north
                source_coords[idx, 1] = \
                    num.sin(strike * d2r) * (
                        il * (num.abs(al1) + num.abs(al2)) + num.abs(al1)) - \
                    num.cos(strike * d2r) * num.cos(dip * d2r) * (
                        iw * (num.abs(aw1) + num.abs(aw2)) + num.abs(aw1)) + \
                    ref_east
                source_coords[idx, 2] = \
                    ref_depth + num.sin(dip * d2r) * iw * (
                        num.abs(aw1) + num.abs(aw2)) + num.abs(aw1)

        receiver_coords = source_coords.copy()

        source_list = [OkadaSource(
            lat=0., lon=0.,
            north_shift=coords[0], east_shift=coords[1],
            depth=coords[2], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=strike, dip=dip, rake=0.,
            mu=mu, nu=poisson) for coords in source_coords]

        pure_shear = False
        if pure_shear:
            n_eq = 2
        else:
            n_eq = 3

        gf = DislocationInverter.get_coef_mat(
            source_list, pure_shear=pure_shear)
        assert num.linalg.det(gf.T * gf) != 0.

        # Function to test the computed GF
        dstress = -1.5e9
        stress_comp = 1

        stress = num.zeros((npoints * n_eq, 1))
        for il in range(nlength):
            for iw in range(nwidth):
                idx = il * nwidth + iw

                if (il > 8 and il < 16) and (iw > 2 and iw < 12):
                    stress[idx * n_eq + stress_comp] = dstress
                elif (il > 2 and il < 10) and (iw > 2 and iw < 12):
                    stress[idx * n_eq + stress_comp] = dstress / 4.

        disloc_est = num.linalg.inv(gf.T * gf) * gf.T * stress

        if show_plot:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D

            def add_subplot(fig, ntot, n, param, title, **kwargs):
                ax = fig.add_subplot(ntot, 1, n, projection='3d')
                scat = ax.scatter(
                    receiver_coords[:, 1], receiver_coords[:, 0],
                    zs=-receiver_coords[:, 2], zdir='z', s=20,
                    c=num.array(param), cmap='jet',
                    edgecolor='None', **kwargs)
                fig.colorbar(scat, shrink=0.5, aspect=5)
                ax.set_title(title)

            param = disloc_est
            vmin = num.min(param)
            vmax = num.max(param)

            fig = plt.figure()
            add_subplot(
                fig, n_eq + 1, 1, [i for i in stress[stress_comp::n_eq]],
                'stress')
            add_subplot(
                fig, n_eq + 1, 2, [i for i in param[::n_eq]],
                '$u_{strike}$', vmin=vmin, vmax=vmax)
            add_subplot(
                fig, n_eq + 1, 3, [i for i in param[1::n_eq]],
                '$u_{dip}$', vmin=vmin, vmax=vmax)
            if n_eq == 3:
                add_subplot(
                    fig, n_eq + 1, 4, [i for i in param[2::n_eq]],
                    '$u_{opening}$', vmin=vmin, vmax=vmax)
            plt.show()

    def test_okada_vs_griffith(self):
        from pyrocko.modelling import GriffithCrack

        nlength = 20
        nwidth = 24
        length = 30.
        width = 20.

        al1 = -length / 2.
        al2 = length / 2.
        aw1 = -width / 2.
        aw2 = width / 2.
        poisson = 0.25
        mu = 32e9

        dstress = -0.5e9
        min_x = -30.
        max_x = 30.

        npoints = nlength * nwidth

        source_coords = num.zeros((npoints, 3))
        stress = num.zeros((npoints * 3, 1))
        for il in range(nlength):
            for iw in range(nwidth):
                idx = il * nwidth + iw
                source_coords[idx, 0] = \
                    il * length - (nlength - 1) / 2. * length
                source_coords[idx, 1] = \
                    iw * width - (nwidth - 1) / 2. * width

                if (source_coords[idx, 1] > min_x and
                        source_coords[idx, 1] < max_x):
                    if (il > 0) and (il < nlength - 1):
                        stress[idx * 3 + 2, 0] = dstress

        source_coords[:, 2] = 10000.
        receiver_coords = source_coords.copy()

        source_list = [OkadaSource(
            lat=0., lon=0.,
            north_shift=coords[0], east_shift=coords[1],
            depth=coords[2], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=0., dip=0., rake=0.,
            slip=0., opening=1.,
            mu=mu, nu=poisson) for coords in source_coords]

        gf = DislocationInverter.get_coef_mat(source_list, pure_shear=False)
        disloc_est = DislocationInverter.get_disloc_lsq(stress, coef_mat=gf)

        stressdrop = num.zeros((3, 1))
        stressdrop[2] = dstress
        width = num.sum(num.abs([min_x, max_x]))
        rec_grif = num.linspace(min_x, max_x, 100)

        griffith = GriffithCrack(
            width=width, poisson=poisson, shear_mod=mu, stressdrop=stressdrop)
        disloc_grif = griffith.disloc_modeI(rec_grif)

        if show_plot:
            import matplotlib.pyplot as plt

            line = int(nlength / 2)
            def add_subplot(fig, ntot, n, title, comp, typ='line'): 
                idx = line * nwidth
                idx2 = (line + 1) * nwidth
                ax = fig.add_subplot(ntot, 1, n)
                if typ == 'line':
                    ax.plot(
                        receiver_coords[idx:idx2, 1],
                        disloc_est[idx * 3 + comp:idx2 * 3 + comp:3],
                        'b-', label='Okada Solution')
                    ax.plot(
                        rec_grif,
                        disloc_grif[:, comp],
                        'r-', label='Griffith crack sol.')
                    plt.legend()
                elif typ == 'scatter':
                    scat = ax.scatter(
                        receiver_coords[:, 1], receiver_coords[:, 0],
                        c=num.array([i for i in disloc_est[comp::3]]))
                    fig.colorbar(scat, shrink=0.8, aspect=5)
                    plt.axis('equal')
                ax.set_title(title)

            fig = plt.figure()
            add_subplot(fig, 3, 1, '$u_{strike}$ along profile %i' % line, 0)
            add_subplot(fig, 3, 2, '$u_{dip}$', 1)
            add_subplot(fig, 3, 3, '$u_{normal}$', 2)

            fig = plt.figure()
            add_subplot(fig, 3, 1, '$u_{strike}$', 0, typ='scatter')
            add_subplot(fig, 3, 2, '$u_{dip}$', 1, typ='scatter')
            add_subplot(fig, 3, 3, '$u_{normal}$', 2, typ='scatter')
            plt.show()


if __name__ == '__main__':
    util.setup_logging('test_okada', 'warning')
    unittest.main()
