# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
import numpy as num
import logging
from threadpoolctl import threadpool_limits

from pyrocko import moment_tensor as mt
import pyrocko.guts as guts
from pyrocko.guts import Float, String, Timestamp
from pyrocko.model import Location
from pyrocko.modelling import okada_ext

guts_prefix = 'modelling'

logger = logging.getLogger('pyrocko.modelling.okada')

d2r = num.pi/180.
r2d = 180./num.pi
km = 1e3


class AnalyticalSource(Location):
    name = String.T(
        optional=True,
        default='')

    time = Timestamp.T(
        default=0.,
        help='source origin time',
        optional=True)

    vr = Float.T(
        default=0.,
        help='Rupture velocity',
        optional=True)

    def __init__(self, **kwargs):
        Location.__init__(self, **kwargs)

    @property
    def northing(self):
        return self.north_shift

    @property
    def easting(self):
        return self.east_shift

    clone = guts.clone


class AnalyticalRectangularSource(AnalyticalSource):
    '''
    Rectangular analytical source model
    '''

    strike = Float.T(
        default=0.0,
        help='strike direction in [deg], measured clockwise from north')

    dip = Float.T(
        default=90.0,
        help='dip angle in [deg], measured downward from horizontal')

    rake = Float.T(
        default=0.0,
        help='rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view')

    al1 = Float.T(
        default=0.,
        help='Distance "left" side to source point [m]')

    al2 = Float.T(
        default=0.,
        help='Distance "right" side to source point [m]')

    aw1 = Float.T(
        default=0.,
        help='Distance "lower" side to source point [m]')

    aw2 = Float.T(
        default=0.,
        help='Distance "upper" side to source point [m]')

    slip = Float.T(
        default=0.,
        help='Slip on the rectangular source area [m]',
        optional=True)

    @property
    def length(self):
        return abs(-self.al1 + self.al2)

    @property
    def width(self):
        return abs(-self.aw1 + self.aw2)

    @property
    def area(self):
        return self.width * self.length


class OkadaSource(AnalyticalRectangularSource):
    '''
    Rectangular Okada source model
    '''

    opening = Float.T(
        default=0.,
        help='Opening of the plane in [m]',
        optional=True)

    poisson = Float.T(
        default=0.25,
        help='Poisson\'s ratio, typically 0.25',
        optional=True)

    shearmod = Float.T(
        default=32e9,
        help='Shear modulus along the plane [Pa]',
        optional=True)

    @property
    def lamb(self):
        '''
        Calculation of first Lame's parameter

        According to Mueller (2007), the first Lame parameter lambda can be
        determined from the formulation for the poisson ration nu:
        nu = lambda / (2 * (lambda + mu))
        with the shear modulus mu
        '''

        return (2. * self.poisson * self.shearmod) / (1. - 2*self.poisson)

    @property
    def seismic_moment(self):
        '''
        Scalar Seismic moment

        Code copied from Kite
        Disregarding the opening (as for now)
        We assume a shear modulus of :math:`mu = 36 mathrm{GPa}`
        and :math:`M_0 = mu A D`

        .. important ::

            We assume a perfect elastic solid with :math:`K=\\frac{5}{3}\\mu`

            Through :math:`\\mu = \\frac{3K(1-2\\nu)}{2(1+\\nu)}` this leads to
            :math:`\\mu = \\frac{8(1+\\nu)}{1-2\\nu}`

        :return: Seismic moment release
        :rtype: float
        '''

        if self.shearmod:
            mu = self.shearmod
        elif self.poisson:
            self.shearmod = (8. * (1. + self.poisson)) / (1. - 2*self.poisson)
            mu = self.shearmod
        else:
            raise ValueError(
                'Shear modulus or poisson ratio needed for moment calculation')

        disl = 0.
        if self.slip:
            disl = (disl**2 + self.slip**2)**.5
        if self.opening:
            disl = (disl**2 + self.opening**2)**.5

        return mu * self.area * disl

    @property
    def moment_magnitude(self):
        '''
        Moment magnitude from Seismic moment

        We assume :math:`M_\\mathrm{w} = {\\frac{2}{3}}\\log_{10}(M_0) - 10.7`

        :returns: Moment magnitude
        :rtype: float
        '''
        return mt.moment_to_magnitude(self.seismic_moment)

    def source_patch(self):
        '''
        Build source information array for okada_ext.okada input

        :return: array of the source data as input for okada_ext.okada
        :rtype: :py:class:`numpy.ndarray`, ``(1, 9)``
        '''
        return num.array([
            self.northing,
            self.easting,
            self.depth,
            self.strike,
            self.dip,
            self.al1,
            self.al2,
            self.aw1,
            self.aw2])

    def source_disloc(self):
        '''
        Build source dislocation for okada_ext.okada input

        :return: array of the source dislocation data as input for
        okada_ext.okada
        :rtype: :py:class:`numpy.ndarray`, ``(1, 3)``
        '''
        return num.array([
            num.cos(self.rake * d2r) * self.slip,
            num.sin(self.rake * d2r) * self.slip,
            self.opening])

    def discretize(self, nlength, nwidth, *args, **kwargs):
        '''
        Discretize the given fault by ``nlength * nwidth`` fault patches

        Discretizing the fault into several sub faults. ``nlength`` is
        number of points in strike direction, ``nwidth`` in down dip direction
        along the fault. Fault orientation, slip and elastic parameters are
        kept.

        :param nlength: Number of discrete points in faults strike direction
        :type nlength: int
        :param nwidth: Number of discrete points in faults down-dip direction
        :type nwidth: int

        :return: Discrete fault patches
        :rtype: list of :py:class:`pyrocko.modelling.OkadaSource` objects
        '''
        assert nlength > 0
        assert nwidth > 0

        il = num.repeat(num.arange(nlength), nwidth)
        iw = num.tile(num.arange(nwidth), nlength)

        patch_length = self.length / nlength
        patch_width = self.width / nwidth

        al1 = -patch_length / 2.
        al2 = patch_length / 2.
        aw1 = -patch_width / 2.
        aw2 = patch_width / 2.

        source_points = num.zeros((nlength * nwidth, 3))
        source_points[:, 0] = il * patch_length + patch_length / 2.
        source_points[:, 1] = iw * patch_width + patch_width / 2.

        source_points[:, 0] += self.al1
        source_points[:, 1] -= self.aw2

        rotmat = num.asarray(
            mt.euler_to_matrix(self.dip * d2r, self.strike * d2r, 0.))

        source_points_rot = num.dot(rotmat.T, source_points.T).T
        source_points_rot[:, 0] += self.northing
        source_points_rot[:, 1] += self.easting
        source_points_rot[:, 2] += self.depth

        kwargs = {
            prop: getattr(self, prop) for prop in self.T.propnames
            if prop not in [
                'north_shift', 'east_shift', 'depth',
                'al1', 'al2', 'aw1', 'aw2']}

        return [OkadaSource(
            north_shift=coord[0], east_shift=coord[1],
            depth=coord[2], al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            **kwargs)
            for coord in source_points_rot], source_points


class DislocationInverter(object):
    '''
    Toolbox for Boundary Element Method (BEM) and dislocation inversion based
    on okada_ext.okada
    '''

    @staticmethod
    def get_coef_mat(source_patches_list, pure_shear=False,
                     rotate_sdn=True, nthreads=1):
        '''
        Build coefficient matrix for given source_patches

        The BEM for a fault and the determination of the slip distribution from
        the stress drop is based on the relation stress = coef_mat * displ.
        Here the coefficient matrix is build and filled based on the
        okada_ext.okada displacements and partial displacement
        differentiations.

        :param source_patches_list: list of all OkadaSources, which shall be
            used for BEM
        :type source_patches_list: list of
            :py:class:`pyrocko.modelling.OkadaSource`
        :param pure_shear: Flag, if also opening mode shall be taken into
            account (False) or the fault is described as pure shear (True).
        :type pure_shear: optional, Bool

        :return: coefficient matrix for all sources
        :rtype: :py:class:`numpy.ndarray`,
            ``(len(source_patches_list) * 3, len(source_patches_list) * 3)``
        '''

        source_patches = num.array([
            src.source_patch() for src in source_patches_list])
        receiver_coords = source_patches[:, :3].copy()

        npoints = len(source_patches_list)

        if pure_shear:
            n_eq = 2
        else:
            n_eq = 3

        coefmat = num.zeros((npoints * 3, npoints * 3))

        lambda_mean = num.mean([src.lamb for src in source_patches_list])
        mu_mean = num.mean([src.shearmod for src in source_patches_list])

        unit_disl = 1.
        disl_cases = {
            'strikeslip': {
                'slip': unit_disl,
                'opening': 0.,
                'rake': 0.},
            'dipslip': {
                'slip': unit_disl,
                'opening': 0.,
                'rake': 90.},
            'tensileslip': {
                'slip': 0.,
                'opening': unit_disl,
                'rake': 0.}
        }

        diag_ind = [0, 4, 8]
        kron = num.zeros(9)
        kron[diag_ind] = 1.
        kron = kron[num.newaxis, num.newaxis, :]

        for idisl, case_type in enumerate([
                'strikeslip', 'dipslip', 'tensileslip'][:n_eq]):
            case = disl_cases[case_type]
            source_disl = num.array([
                case['slip'] * num.cos(case['rake'] * d2r),
                case['slip'] * num.sin(case['rake'] * d2r),
                case['opening']])

            results = okada_ext.okada(
                source_patches,
                num.tile(source_disl, npoints).reshape(-1, 3),
                receiver_coords,
                lambda_mean,
                mu_mean,
                nthreads=nthreads,
                rotate_sdn=rotate_sdn,
                stack_sources=False)

            eps = 0.5 * (results[:, :, 3:] +
                         results[:, :, (3, 6, 9, 4, 7, 10, 5, 8, 11)])

            dilatation = eps[:, :, diag_ind].sum(axis=-1)[:, :, num.newaxis]

            stress_sdn = kron*lambda_mean*dilatation + 2.*mu_mean*eps
            coefmat[:, idisl::3] = stress_sdn[:, :, (2, 5, 8)]\
                .reshape(-1, npoints*3).T

        if pure_shear:
            coefmat[2::3, :] = 0.

        return -coefmat / unit_disl

    @staticmethod
    def get_coef_mat_single(source_patches_list, pure_shear=False,
                            rotate_sdn=True, nthreads=1):
        '''
        Build coefficient matrix for given source_patches

        The BEM for a fault and the determination of the slip distribution from
        the stress drop is based on the relation stress = coef_mat * displ.
        Here the coefficient matrix is build and filled based on the
        okada_ext.okada displacements and partial displacement
        differentiations.

        :param source_patches_list: list of all OkadaSources, which shall be
            used for BEM
        :type source_patches_list: list of
            :py:class:`pyrocko.modelling.OkadaSource`
        :param pure_shear: Flag, if also opening mode shall be taken into
            account (False) or the fault is described as pure shear (True).
        :type pure_shear: optional, Bool

        :return: coefficient matrix for all sources
        :rtype: :py:class:`numpy.ndarray`,
            ``(len(source_patches_list) * 3, len(source_patches_list) * 3)``
        '''

        source_patches = num.array([
            src.source_patch() for src in source_patches_list])
        receiver_coords = source_patches[:, :3].copy()

        npoints = len(source_patches_list)

        if pure_shear:
            n_eq = 2
        else:
            n_eq = 3

        coefmat = num.zeros((npoints * 3, npoints * 3))

        lambda_mean = num.mean([src.lamb for src in source_patches_list])
        mu_mean = num.mean([src.shearmod for src in source_patches_list])

        unit_disl = 1.
        disl_cases = {
            'strikeslip': {
                'slip': unit_disl,
                'opening': 0.,
                'rake': 0.},
            'dipslip': {
                'slip': unit_disl,
                'opening': 0.,
                'rake': 90.},
            'tensileslip': {
                'slip': 0.,
                'opening': unit_disl,
                'rake': 0.}
        }

        diag_ind = [0, 4, 8]
        kron = num.zeros(9)
        kron[diag_ind] = 1.
        kron = kron[num.newaxis, :]

        for idisl, case_type in enumerate([
                'strikeslip', 'dipslip', 'tensileslip'][:n_eq]):
            case = disl_cases[case_type]
            source_disl = num.array([
                case['slip'] * num.cos(case['rake'] * d2r),
                case['slip'] * num.sin(case['rake'] * d2r),
                case['opening']])

            for isrc, source in enumerate(source_patches):
                results = okada_ext.okada(
                    source[num.newaxis, :],
                    source_disl[num.newaxis, :],
                    receiver_coords,
                    lambda_mean,
                    mu_mean,
                    nthreads=nthreads,
                    rotate_sdn=rotate_sdn)

                eps = \
                    0.5 * (
                        results[:, 3:] +
                        results[:, (3, 6, 9, 4, 7, 10, 5, 8, 11)])

                dilatation = num.sum(eps[:, diag_ind], axis=1)[:, num.newaxis]
                stress_sdn = kron * lambda_mean * dilatation+2. * mu_mean * eps

                coefmat[:, isrc*3 + idisl] = stress_sdn[:, (2, 5, 8)].ravel()

                if pure_shear:
                    coefmat[2::3, isrc * 3 + idisl] = 0.

        return -coefmat / unit_disl

    @staticmethod
    def get_coef_mat_slow(source_patches_list, pure_shear=False,
                          rotate_sdn=True, nthreads=1):
        '''
        Build coefficient matrix for given source_patches (Slow version)

        The BEM for a fault and the determination of the slip distribution from
        the stress drop is based on the relation stress = coef_mat * displ.
        Here the coefficient matrix is build and filled based on the
        okada_ext.okada displacements and partial displacement
        differentiations.

        :param source_patches_list: list of all OkadaSources, which shall be
            used for BEM
        :type source_patches_list: list of
            :py:class:`pyrocko.modelling.OkadaSource`
        :param pure_shear: Flag, if also opening mode shall be taken into
            account (False) or the fault is described as pure shear (True).
        :type pure_shear: optional, Bool

        :return: coefficient matrix for all sources
        :rtype: :py:class:`numpy.ndarray`,
            ``(source_patches_list.shape[0] * 3,
            source_patches_list.shape[0] * 3(2))``
        '''

        source_patches = num.array([
            src.source_patch() for src in source_patches_list])
        receiver_coords = source_patches[:, :3].copy()

        npoints = len(source_patches_list)

        if pure_shear:
            n_eq = 2
        else:
            n_eq = 3

        coefmat = num.zeros((npoints * 3, npoints * 3))

        def ned2sdn_rotmat(strike, dip):
            rotmat = mt.euler_to_matrix(
                (dip + 180.) * d2r, strike * d2r, 0.).A
            return rotmat

        lambda_mean = num.mean([src.lamb for src in source_patches_list])
        shearmod_mean = num.mean([src.shearmod for src in source_patches_list])

        unit_disl = 1.
        disl_cases = {
            'strikeslip': {
                'slip': unit_disl,
                'opening': 0.,
                'rake': 0.},
            'dipslip': {
                'slip': unit_disl,
                'opening': 0.,
                'rake': 90.},
            'tensileslip': {
                'slip': 0.,
                'opening': unit_disl,
                'rake': 0.}
        }
        for idisl, case_type in enumerate([
                'strikeslip', 'dipslip', 'tensileslip'][:n_eq]):
            case = disl_cases[case_type]
            source_disl = num.array([
                case['slip'] * num.cos(case['rake'] * d2r),
                case['slip'] * num.sin(case['rake'] * d2r),
                case['opening']])

            for isource, source in enumerate(source_patches):
                results = okada_ext.okada(
                    source[num.newaxis, :].copy(),
                    source_disl[num.newaxis, :].copy(),
                    receiver_coords,
                    lambda_mean,
                    shearmod_mean,
                    nthreads=nthreads,
                    rotate_sdn=rotate_sdn)

                for irec in range(receiver_coords.shape[0]):
                    eps = num.zeros((3, 3))
                    for m in range(3):
                        for n in range(3):
                            eps[m, n] = 0.5 * (
                                results[irec][m * 3 + n + 3] +
                                results[irec][n * 3 + m + 3])

                    stress = num.zeros((3, 3))
                    dilatation = num.sum([eps[i, i] for i in range(3)])

                    for m, n in zip([0, 0, 0, 1, 1, 2], [0, 1, 2, 1, 2, 2]):
                        if m == n:
                            stress[m, n] = \
                                lambda_mean * \
                                dilatation + \
                                2. * shearmod_mean * \
                                eps[m, n]

                        else:
                            stress[m, n] = \
                                2. * shearmod_mean * \
                                eps[m, n]
                            stress[n, m] = stress[m, n]

                    normal = num.array([0., 0., -1.])
                    for isig in range(3):
                        tension = num.sum(stress[isig, :] * normal)
                        coefmat[irec * n_eq + isig, isource * n_eq + idisl] = \
                            tension / unit_disl

        return coefmat

    @staticmethod
    def get_disloc_lsq(
            stress_field,
            coef_mat=None,
            source_list=None,
            pure_shear=False,
            nthreads=1,
            **kwargs):
        '''
        Least square inversion to get displacement from stress

        Follows approach for Least-Square Inversion published in Menke (1989)
        to calculate displacements on a fault with several segments from a
        given stress field. If not done, the coefficient matrix is determined
        within the code.

        :param stress_field: Array containing the stress change [Pa] for each
            source patch (order: [
            src1 dstress_Strike, src1 dstress_Dip, src1 dstress_Tensile,
            src2 dstress_Strike, ...])
        :type stress_field: :py:class:`numpy.ndarray`, ``(n_sources * 3, )``
        :param coef_mat: Coefficient matrix to connect source patches
            displacement and the resulting stress field
        :type coef_mat: optional, :py:class:`numpy.ndarray`,
            ``(source_patches_list.shape[0] * 3,
            source_patches.shape[] * 3(2)``
        :param source_list: list of all OkadaSources, which shall be
            used for BEM
        :type source_list: optional, list of
            :py:class:`pyrocko.modelling.OkadaSource`

        :return: inverted displacements (u_strike, u_dip , u_tensile) for each
            source patch. order: [
            [patch1 u_Strike, patch1 u_Dip, patch1 u_Tensile],
            [patch2 u_Strike, patch2 u_Dip, patch2 u_Tensile],
            ...]
        :rtype: :py:class:`numpy.ndarray`, ``(n_sources, 3)``
        '''

        if source_list is not None and coef_mat is None:
            coef_mat = DislocationInverter.get_coef_mat(
                source_list, pure_shear=pure_shear, nthreads=nthreads,
                **kwargs)

        idx = num.arange(0, coef_mat.shape[0])
        if pure_shear:
            idx = idx[idx % 3 != 2]

        coef_mat_in = coef_mat[idx, :][:, idx]
        disloc_est = num.zeros(coef_mat.shape[0])

        if stress_field.ndim == 2:
            stress_field = stress_field.ravel()

        with threadpool_limits(limits=nthreads, user_api='blas'):
            disloc_est[idx] = num.linalg.multi_dot([num.linalg.inv(
                num.dot(coef_mat_in.T, coef_mat_in)),
                coef_mat_in.T,
                stress_field[idx]])
            return disloc_est.reshape(-1, 3)


__all__ = [
    'AnalyticalSource',
    'AnalyticalRectangularSource',
    'OkadaSource',
    'DislocationInverter']
