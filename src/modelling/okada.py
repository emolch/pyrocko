# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
import numpy as num
import logging

from pyrocko import moment_tensor as mt
import pyrocko.guts as guts
from pyrocko.guts import Float, String, Timestamp
from pyrocko.model import Location
from pyrocko.modelling import okada_ext

guts_prefix = 'modelling'

logger = logging.getLogger('pyrocko.modelling.okada')

d2r = num.pi / 180.
r2d = 180. / num.pi
km = 1.0e3


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
        return num.sum(num.abs([self.al1, self.al2]))

    @property
    def width(self):
        return num.sum(num.abs([self.aw1, self.aw2]))

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

        return (2 * self.poisson * self.shearmod) / (1 - 2 * self.poisson)

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
            self.shearmod = (8. * (1 + self.poisson)) / (1 - 2. * self.poisson)
            mu = self.shearmod
        else:
            raise ValueError(
                'Shear modulus or poisson ratio needed for moment calculation')

        disl = 0.
        if self.slip:
            disl = num.sqrt(num.sum([disl**2, self.slip**2]))
        if self.opening:
            disl = num.sqrt(num.sum([disl**2, self.opening**2]))

        return mu * self.area * disl

    @property
    def moment_magnitude(self):
        '''
        Moment magnitude from Seismic moment

        Copied from Kite. Returns the moment magnitude
        We assume :math:`M_\\mathrm{w} = {\\frac{2}{3}}\\log_{10}(M_0) - 10.7`

        :returns: Moment magnitude
        :rtype: float
        '''

        return 2. / 3 * num.log10(self.seismic_moment * 1e7) - 10.7

    def source_patch(self):
        '''
        Build source information array for okada_ext.okada input

        :return: array of the source data as input for okada_ext.okada
        :rtype: :py:class:`numpy.ndarray`, ``(1, 9)``
        '''

        source_patch = num.empty(9)

        source_patch[0] = self.northing
        source_patch[1] = self.easting
        source_patch[2] = self.depth
        source_patch[3] = self.strike
        source_patch[4] = self.dip
        source_patch[5] = self.al1
        source_patch[6] = self.al2
        source_patch[7] = self.aw1
        source_patch[8] = self.aw2

        return source_patch

    def source_disloc(self):
        '''
        Build source dislocation for okada_ext.okada input

        :return: array of the source dislocation data as input for
        okada_ext.okada
        :rtype: :py:class:`numpy.ndarray`, ``(1, 3)``
        '''

        source_disl = num.empty(3)

        source_disl[0] = num.cos(self.rake * d2r) * self.slip
        source_disl[1] = num.sin(self.rake * d2r) * self.slip
        source_disl[2] = self.opening

        return source_disl

    def get_parameters_array(self):
        return num.array([self.__getattribute__(p) for p in self.parameters])

    def set_parameters_array(self, parameter_arr):
        if parameter_arr.size != len(self.parameters):
            raise AttributeError('Invalid number of parameters, %s has %d'
                                 ' parameters'
                                 % self.__name__, len(self.parameters))
        for ip, param in enumerate(self.parameters):
            self.__setattr__(param, parameter_arr[ip])

    def discretize(self, nlength, nwidth, *args, **kwargs):
        '''
        Discretize the given fault by nlength * nwidth fault patches

        Discretizing the fault into several sub faults. Nlength is number of
        points in strike direction, nwidth in down dip direction along the
        fault. Fault orientation, slip and elastic parameters are kept.

        :param nlength: Number of discrete points in faults strike direction
        :type nlength: int
        :param nwidth: Number of discrete points in faults down-dip direction
        :type nwidth: int

        :return: Discrete fault patches
        :rtype: list of :py:class:`pyrocko.modelling.OkadaSource` objects
        '''

        il = num.tile(num.arange(0, nlength, 1), nwidth)
        iw = num.repeat(num.arange(0, nwidth, 1), nlength)

        patch_length = self.length / nlength
        patch_width = self.width / nwidth

        al1 = -patch_length / 2.
        al2 = patch_length / 2.
        aw1 = -patch_width / 2.
        aw2 = patch_width / 2.

        source_points = num.zeros((nlength * nwidth, 3))
        source_points[:, 0] = il * patch_length + num.abs(al1)
        source_points[:, 1] = iw * patch_width + num.abs(aw1)

        source_points[:, 0] += self.al1
        source_points[:, 1] -= self.aw2

        rotmat = num.asarray(
            mt.euler_to_matrix(self.dip * d2r, self.strike * d2r, 0.0))

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
    def get_coef_mat(source_patches_list, pure_shear=False):
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
            ``(source_patches_list.shape[0] * 3,
            source_patches.shape[] * 3(2))``
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
                    0)

                eps = \
                    0.5 * (
                        results[:, 3:] +
                        results[:, [3, 6, 9, 4, 7, 10, 5, 8, 11]])

                diag_ind = [0, 4, 8]
                dilatation = num.sum(eps[:, diag_ind], axis=1)[:, num.newaxis]
                lamb = lambda_mean
                mu = shearmod_mean
                kron = num.zeros_like(eps)
                kron[:, diag_ind] = 1.

                stress_ned = kron * lamb * dilatation + 2. * mu * eps

                rotmat = ned2sdn_rotmat(
                    source_patches_list[isource].strike,
                    source_patches_list[isource].dip)

                stress_sdn = num.array([
                    num.dot(num.dot(
                        rotmat, stress.reshape(3, 3)), rotmat.T).flatten()
                    for stress in stress_ned])

                coefmat[0::3, isource * 3 + idisl] = -stress_sdn[
                    :, 2].flatten() / unit_disl
                coefmat[1::3, isource * 3 + idisl] = -stress_sdn[
                    :, 5].flatten() / unit_disl
                if n_eq == 3:
                    coefmat[2::3, isource * 3 + idisl] = -stress_sdn[
                        :, 8].flatten() / unit_disl

        return coefmat

    @staticmethod
    def get_coef_mat_slow(source_patches_list, pure_shear=False):
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
                    0)

                for irec in range(receiver_coords.shape[0]):
                    eps = num.zeros((3, 3))
                    for m in range(3):
                        for n in range(3):
                            eps[m, n] = 0.5 * (
                                results[irec][m * 3 + n + 3] +
                                results[irec][n * 3 + m + 3])

                    stress_tens = num.zeros((3, 3))
                    dilatation = num.sum([eps[i, i] for i in range(3)])

                    for m, n in zip([0, 0, 0, 1, 1, 2], [0, 1, 2, 1, 2, 2]):
                        if m == n:
                            stress_tens[m, n] = \
                                lambda_mean * \
                                dilatation + \
                                2. * shearmod_mean * \
                                eps[m, n]

                        else:
                            stress_tens[m, n] = \
                                2. * shearmod_mean * \
                                eps[m, n]
                            stress_tens[n, m] = stress_tens[m, n]

                    rotmat = ned2sdn_rotmat(
                        source_patches_list[isource].strike,
                        source_patches_list[isource].dip)

                    stress_sdn = num.dot(num.dot(
                        rotmat, stress_tens), rotmat.T)

                    normal = num.array([0., 0., -1.])
                    for isig in range(3):
                        tension = num.sum(stress_sdn[isig, :] * normal)
                        coefmat[irec * n_eq + isig, isource * n_eq + idisl] = \
                            tension / unit_disl

        return coefmat

    @staticmethod
    def get_disloc_lsq(
            stress_field,
            coef_mat=None,
            source_list=None,
            pure_shear=False,
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
            patch1 u_Strike, patch1 u_Dip, patch1 u_Tensile,
            patch2 u_Strike, ...]
        :rtype: :py:class:`numpy.ndarray`, ``(n_sources * 3, 1)``
        '''

        if source_list is not None and coef_mat is None:
            coef_mat = DislocationInverter.get_coef_mat(
                source_list, pure_shear=pure_shear, **kwargs)

        idx = num.arange(0, coef_mat.shape[0], 1)
        if pure_shear:
            idx = idx[
                (idx + 1) / 3. != num.floor((idx + 1) / 3.)]

        coef_mat_in = coef_mat[idx, :][:, idx]
        disloc_est = num.zeros(coef_mat.shape[0])

        if stress_field.ndim == 2:
            stress_field = stress_field.reshape(-1,)

        if not (coef_mat_in is None):
            if stress_field[idx].shape[0] == coef_mat_in.shape[0]:
                disloc_est[idx] = num.linalg.multi_dot([num.linalg.inv(
                    num.dot(coef_mat_in.T, coef_mat_in)),
                    coef_mat_in.T,
                    stress_field[idx]])
                return disloc_est.reshape(-1,)


__all__ = [
    'AnalyticalSource',
    'AnalyticalRectangularSource',
    'OkadaSource',
    'DislocationInverter']
