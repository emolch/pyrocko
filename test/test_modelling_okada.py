from __future__ import division, print_function, absolute_import
import os
import numpy as num
import unittest

from pyrocko import util
from pyrocko.modelling import DislocProcessor, DislocationInverter,\
    okada_ext, OkadaSource


d2r = num.pi / 180.
km = 1000.


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
        mu = 32.0e9
        lamb = (2 * poisson * mu) / (1 - 2 * poisson)

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
            source_patches, source_disl, receiver_coords, lamb, mu, nthreads)

        assert results.shape == tuple((n, 12))

        source_list2 = [OkadaSource(
            lat=0., lon=0.,
            north_shift=north[i], east_shift=east[i],
            depth=down[i], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=strike, dip=dip,
            rake=rake, slip=slip, opening=opening,
            poisson=poisson, shearmod=mu)
            for i in range(n)]
        source_patches2 = num.array([
            source.source_patch() for source in source_list2])
        assert (source_patches == source_patches2).all()

        source_disl2 = num.array([
            patch.source_disloc() for patch in source_list2])
        assert (source_disl == source_disl2).all()

        results2 = okada_ext.okada(
            source_patches2, source_disl2, receiver_coords, lamb, mu, nthreads)
        assert (results == results2).all()

        seismic_moment = \
            mu * num.sum(num.abs([al1, al2])) * \
            num.sum(num.abs([aw1, aw2])) * num.sqrt(num.sum(
                [slip**2, opening**2]))

        assert source_list2[0].seismic_moment == seismic_moment

    def test_okada_vs_disloc_single_source(self):
        north = 0.
        east = 0.
        depth = 10. * km
        length = 50. * km
        width = 10. * km

        strike = 45.
        dip = 89.
        rake = 90.
        slip = 0.0
        opening = 1.
        poisson = 0.25
        mu = 32.0e9
        lamb = (2 * poisson * mu) / (1 - 2 * poisson)

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
            rake=rake, slip=slip, opening=opening,
            poisson=poisson, shearmod=mu)]

        res_ok2d = DislocProcessor.process(
            segments, num.array(receiver_coords[:, ::-1][:, 1:]))

        source_patch = num.array([patch.source_patch() for patch in segments])
        source_disl = num.array([patch.source_disloc() for patch in segments])
        res_ok3d = okada_ext.okada(
            source_patch, source_disl, receiver_coords, lamb, mu, nthreads)

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
                    edgecolor='None')
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
        poisson = 0.25
        mu = 32.e9
        lamb = (2 * poisson * mu) / (1 - 2 * poisson)

        u = okada_ext.okada(
            num.array([source.source_patch() for source in source_list]),
            num.array([source.source_disloc() for source in source_list]),
            receiver_coords.copy(), lamb, mu, 0)

        u_check = num.array([-0.378981, -0.631789, -0.14960])
        # Example values from:
        # http://www.bosai.go.jp/study/application/dc3d/download/DC3Dmanual.pdf

        for i in range(3):
            vals = num.array([u[0][i], u_check[i]])
            assert num.abs(u[0][i]) - num.abs(u_check[i]) < 1e-5
            assert num.all(vals > 0.) or num.all(vals < 0.)

    def test_okada_discretize(self):
        nlength = 100
        nwidth = 10

        al1 = -80.
        al2 = -al1
        aw1 = -30.
        aw2 = -aw1

        strike = 0.
        dip = 70.

        ref_north = 100.
        ref_east = 200.
        ref_depth = 50.

        source = OkadaSource(
            lat=1., lon=-1., north_shift=ref_north, east_shift=ref_east,
            depth=ref_depth,
            al1=al1, al2=al2, aw1=aw1, aw2=aw2, strike=strike, dip=dip)

        source_disc, _ = source.discretize(nlength, nwidth)

        al1_patch = al1 / nlength
        al2_patch = al2 / nlength
        aw1_patch = aw1 / nwidth
        aw2_patch = aw2 / nwidth

        patch_length = num.sum(num.abs([al1_patch, al2_patch]))
        patch_width = num.sum(num.abs([aw1_patch, aw2_patch]))

        source_coords = num.zeros((nlength * nwidth, 3))
        for iw in range(nwidth):
            for il in range(nlength):
                idx = iw * nlength + il
                x = il * patch_length + num.abs(al1_patch) + al1
                y = iw * patch_width + num.abs(aw1_patch) - aw2

                source_coords[idx, 0] = \
                    num.cos(strike * d2r) * x - \
                    num.sin(strike * d2r) * num.cos(dip * d2r) * y
                source_coords[idx, 1] = \
                    num.sin(strike * d2r) * x + \
                    num.cos(strike * d2r) * num.cos(dip * d2r) * y
                source_coords[idx, 2] = \
                    num.sin(dip * d2r) * y

        source_coords[:, 0] += ref_north
        source_coords[:, 1] += ref_east
        source_coords[:, 2] += ref_depth

        assert (source_coords == num.array([
            [src.north_shift, src.east_shift, src.depth]
            for src in source_disc])).all()

        if show_plot:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D # noqa

            fig = plt.figure()
            ax = fig.add_subplot(1, 1, 1, projection='3d')
            ax.scatter(
                [src.east_shift for src in source_disc],
                [src.north_shift for src in source_disc],
                zs=[-src.depth for src in source_disc], s=20)
            ax.scatter(
                [ref_east], [ref_north], zs=[-ref_depth], s=200, c='red')
            plt.axis('equal')
            plt.show()

    def test_okada_gf_fill(self):
        ref_north = 0.
        ref_east = 0.
        ref_depth = 100000.

        nlength = 20
        nwidth = 16

        strike = 0.
        dip = 90.
        length = 0.5
        width = 0.5
        length_total = nlength * length
        width_total = nwidth * width

        al1 = -length_total / 2.
        al2 = length_total / 2.
        aw1 = -width_total / 2.
        aw2 = width_total / 2.
        poisson = 0.25
        mu = 32.0e9

        source = OkadaSource(
            lat=0., lon=0.,
            north_shift=ref_north, east_shift=ref_east,
            depth=ref_depth, al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=strike, dip=dip, rake=0.,
            shearmod=mu, poisson=poisson)

        source_list, _ = source.discretize(nlength, nwidth)

        receiver_coords = num.array([
            src.source_patch()[:3] for src in source_list])

        pure_shear = False
        if pure_shear:
            n_eq = 2
        else:
            n_eq = 3

        gf = DislocationInverter.get_coef_mat(
            source_list, pure_shear=pure_shear)
        gf2 = DislocationInverter.get_coef_mat_slow(
            source_list, pure_shear=pure_shear)

        assert num.linalg.slogdet(num.dot(gf.T, gf)) != (0., num.inf)
        assert num.linalg.slogdet(num.dot(gf2.T, gf2)) != (0., num.inf)
        assert (gf == gf2).all()

        # Function to test the computed GF
        dstress = -1.5e6
        stress_comp = 1

        stress = num.zeros((nlength * nwidth * n_eq, 1))
        for iw in range(nwidth):
            for il in range(nlength):
                idx = iw * nlength + il

                if (il > 8 and il < 16) and (iw > 2 and iw < 12):
                    stress[idx * n_eq + stress_comp] = dstress
                elif (il > 2 and il < 10) and (iw > 2 and iw < 12):
                    stress[idx * n_eq + stress_comp] = dstress / 4.

        disloc_est = DislocationInverter.get_disloc_lsq(
            stress, coef_mat=gf)

        if show_plot:
            import matplotlib.pyplot as plt
            from mpl_toolkits.mplot3d import Axes3D # noqa

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

    def test_okada_vs_griffith_inf2d(self):
        from pyrocko.modelling import GriffithCrack

        length_total = 100000.
        width_total = 10000.

        nlength = 3
        nwidth = 501
        length = length_total / nlength
        width = width_total / nwidth

        al1 = -length / 2.
        al2 = length / 2.
        aw1 = -width / 2.
        aw2 = width / 2.
        poisson = 0.25
        mu = 32.0e9

        dstress = -0.5e6
        stress_comp = 2
        min_x = -width_total / 2.
        max_x = width_total / 2.

        npoints = nlength * nwidth

        source_coords = num.zeros((npoints, 3))
        stress = num.zeros((npoints * 3, ))
        for iw in range(nwidth):
            for il in range(nlength):
                idx = iw * nlength + il
                source_coords[idx, 0] = \
                    il * length - (nlength - 1) / 2. * length
                source_coords[idx, 1] = \
                    iw * width - (nwidth - 1) / 2. * width
                stress[idx * 3 + stress_comp] = dstress

        source_coords[:, 2] = 100000.
        receiver_coords = source_coords.copy()

        source_list = [OkadaSource(
            lat=0., lon=0.,
            north_shift=coords[0], east_shift=coords[1],
            depth=coords[2], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=0., dip=0., rake=0.,
            shearmod=mu, poisson=poisson) for coords in source_coords]

        gf = DislocationInverter.get_coef_mat(source_list, pure_shear=False)
        disloc_est = DislocationInverter.get_disloc_lsq(stress, coef_mat=gf)

        stressdrop = num.zeros(3, )
        stressdrop[stress_comp] = dstress
        rec_grif = num.linspace(min_x - aw1, max_x - aw2, nwidth)

        griffith = GriffithCrack(
            width=num.sum(num.abs([min_x, max_x])),
            poisson=poisson,
            shearmod=mu,
            stressdrop=stressdrop)

        disloc_grif = griffith.disloc_infinite2d(x_obs=rec_grif)

        line = int(nlength / 2)
        idx = line
        idx2 = (nwidth - 1) * nlength + line + 1

        assert num.mean(num.abs(
            disloc_grif[:, 2] -
            disloc_est[idx * 3 + 2:idx2 * 3 + 2:3 * nlength])) < 0.001

        if show_plot:
            import matplotlib.pyplot as plt
            def add_subplot(fig, ntot, n, title, comp, typ='line'):
                ax = fig.add_subplot(ntot, 1, n)
                if typ == 'line':
                    ax.plot(
                        receiver_coords[idx:idx2:nlength, 1],
                        disloc_est[idx * 3 + comp:idx2 * 3 + comp:3 * nlength],
                        'b-', label='Okada solution')
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
            add_subplot(
                fig, 3, 1, r'$\Delta u_{strike}$ along profile %i' % line, 0)
            add_subplot(fig, 3, 2, r'$\Delta u_{dip}$', 1)
            add_subplot(fig, 3, 3, r'$\Delta u_{normal}$', 2)

            fig = plt.figure()
            add_subplot(fig, 3, 1, r'$\Delta u_{strike}$', 0, typ='scatter')
            add_subplot(fig, 3, 2, r'$\Delta u_{dip}$', 1, typ='scatter')
            add_subplot(fig, 3, 3, r'$\Delta u_{normal}$', 2, typ='scatter')
            plt.show()

    def test_okada_vs_griffith_circ(self):
        from pyrocko.modelling import GriffithCrack

        length_total = 10000.
        width_total = length_total

        nlength = 31
        nwidth = nlength
        length = length_total / nlength
        width = width_total / nwidth

        al1 = -length / 2.
        al2 = length / 2.
        aw1 = -width / 2.
        aw2 = width / 2.
        poisson = 0.25
        mu = 32.0e9

        dstress = -0.5e6
        radius = length_total / 2.

        source_coords = []
        stress = []
        for iw in range(nwidth):
            for il in range(nlength):
                coords = num.zeros(3)
                coords[0] = \
                    il * length - (nlength - 1) / 2. * length
                coords[1] = \
                    iw * width - (nwidth - 1) / 2. * width

                if num.sqrt(num.sum([
                        (coords[1])**2., (coords[0])**2.])) <= radius:

                    source_coords.append(coords)
                    stress.append(num.array([0., 0., dstress]))

        source_coords = num.array(source_coords)
        stress = num.array(stress).flatten()

        source_coords[:, 2] = 200000.
        receiver_coords = source_coords.copy()

        source_list = [OkadaSource(
            lat=0., lon=0.,
            north_shift=src_crds[0], east_shift=src_crds[1],
            depth=src_crds[2], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            strike=0., dip=0., rake=0.,
            shearmod=mu, poisson=poisson) for src_crds in source_coords]

        gf = DislocationInverter.get_coef_mat(source_list, pure_shear=False)
        disloc_est = DislocationInverter.get_disloc_lsq(
            stress, coef_mat=gf)

        stressdrop = num.zeros(3, )
        stressdrop[2] = dstress
        rec_grif = num.linspace(-radius - aw1, radius - aw2, nwidth)

        griffith = GriffithCrack(
            width=length_total,
            poisson=poisson, shearmod=mu, stressdrop=stressdrop)
        disloc_grif = griffith.disloc_circular(x_obs=rec_grif)

        indices = num.arange(source_coords.shape[0])[source_coords[:, 0] == 0.]
        line = int(nlength / 2.)

        assert num.abs(
            num.max(num.abs(disloc_grif[:, 2])) -
            num.max(num.abs(disloc_est[indices * 3 + 2]))) < 0.001

        if show_plot:
            import matplotlib.pyplot as plt
            def add_subplot(fig, ntot, n, title, comp, typ='line'):
                ax = fig.add_subplot(ntot, 1, n)
                if typ == 'line':
                    ax.plot(
                        receiver_coords[indices, 1],
                        disloc_est[indices * 3 + comp],
                        'b-', label='Okada solution')
                    ax.plot(
                        rec_grif,
                        disloc_grif[:, comp],
                        'r-', label='Griffith crack sol.')
                    plt.legend()
                elif typ == 'scatter':
                    scat = ax.scatter(
                        receiver_coords[:, 1], receiver_coords[:, 0],
                        c=num.array([i for i in disloc_est[comp::3]]))
                    artist = plt.Circle((0, 0), radius - al2, fill=False)
                    ax.add_artist(artist)
                    fig.colorbar(scat, shrink=0.8, aspect=5)
                    plt.axis('equal')
                ax.set_title(title)

            fig = plt.figure()
            add_subplot(
                fig, 3, 1, r'$\Delta u_{strike}$ along profile %i' % line, 0)
            add_subplot(fig, 3, 2, r'$\Delta u_{dip}$', 1)
            add_subplot(fig, 3, 3, r'$\Delta u_{normal}$', 2)

            fig = plt.figure()
            add_subplot(fig, 3, 1, r'$\Delta u_{strike}$', 0, typ='scatter')
            add_subplot(fig, 3, 2, r'$\Delta u_{dip}$', 1, typ='scatter')
            add_subplot(fig, 3, 3, r'$\Delta u_{normal}$', 2, typ='scatter')
            plt.show()


if __name__ == '__main__':
    util.setup_logging('test_okada', 'warning')
    unittest.main()
