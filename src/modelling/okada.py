# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num
import logging

from pyrocko import moment_tensor as mt
from pyrocko.guts import Float, String, Timestamp, Int
from pyrocko.model import Location
from pyrocko.modelling import okada_ext
from pyrocko.util import get_threadpool_limits

guts_prefix = 'modelling'

logger = logging.getLogger(__name__)

d2r = num.pi/180.
r2d = 180./num.pi
km = 1e3


class AnalyticalSource(Location):
    '''
    Base class for analytical source models.
    '''

    name = String.T(
        optional=True,
        default='')

    time = Timestamp.T(
        default=0.,
        help='Source origin time',
        optional=True)

    vr = Float.T(
        default=0.,
        help='Rupture velocity [m/s]',
        optional=True)

    @property
    def northing(self):
        return self.north_shift

    @property
    def easting(self):
        return self.east_shift


class AnalyticalRectangularSource(AnalyticalSource):
    '''
    Rectangular analytical source model.

    Coordinates on the source plane are with respect to the origin point given
    by `(lat, lon, east_shift, north_shift, depth)`.
    '''

    strike = Float.T(
        default=0.0,
        help='Strike direction in [deg], measured clockwise from north.')

    dip = Float.T(
        default=90.0,
        help='Dip angle in [deg], measured downward from horizontal.')

    rake = Float.T(
        default=0.0,
        help='Rake angle in [deg], measured counter-clockwise from '
             'right-horizontal in on-plane view.')

    al1 = Float.T(
        default=0.,
        help='Left edge source plane coordinate [m].')

    al2 = Float.T(
        default=0.,
        help='Right edge source plane coordinate [m].')

    aw1 = Float.T(
        default=0.,
        help='Lower edge source plane coordinate [m].')

    aw2 = Float.T(
        default=0.,
        help='Upper edge source plane coordinate [m].')

    slip = Float.T(
        default=0.,
        help='Slip on the rectangular source area [m].',
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
    Rectangular Okada source model.
    '''

    opening = Float.T(
        default=0.,
        help='Opening of the plane in [m].',
        optional=True)

    poisson__ = Float.T(
        default=0.25,
        help='Poisson ratio :math:`\\nu`. '
             'The Poisson ratio :math:`\\nu`. If set to ``None``, calculated '
             'from the Lame\' parameters :math:`\\lambda` and :math:`\\mu` '
             'using :math:`\\nu = \\frac{\\lambda}{2(\\lambda + \\mu)}` (e.g. '
             'Mueller 2007).',
        optional=True)

    lamb__ = Float.T(
        help='First Lame parameter :math:`\\lambda` [Pa]. '
             'If set to ``None``, it is computed from Poisson ratio '
             ':math:`\\nu` and shear modulus :math:`\\mu`. **Important:** We '
             'assume a perfect elastic solid with :math:`K=\\frac{5}{3}\\mu`. '
             'Through :math:`\\nu = \\frac{\\lambda}{2(\\lambda + \\mu)}` '
             'this leads to :math:`\\lambda = \\frac{2 \\mu \\nu}{1-2\\nu}`.',
        optional=True)

    shearmod__ = Float.T(
        default=32.0e9,
        help='Shear modulus :math:`\\mu` [Pa]. '
             'If set to ``None``, it is computed from poisson ratio. '
             '**Important:** We assume a perfect elastic solid with '
             ':math:`K=\\frac{5}{3}\\mu`. Through '
             ':math:`\\mu = \\frac{3K(1-2\\nu)}{2(1+\\nu)}` this leads to '
             ':math:`\\mu = \\frac{8(1+\\nu)}{1-2\\nu}`.',
        optional=True)

    @property
    def poisson(self):
        if self.poisson__ is not None:
            return self.poisson__

        if self.shearmod__ is None or self.lamb__ is None:
            raise ValueError('Shearmod and lambda are needed')

        return (self.lamb__) / (2. * (self.lamb__ + self.shearmod__))

    @poisson.setter
    def poisson(self, poisson):
        self.poisson__ = poisson

    @property
    def lamb(self):

        if self.lamb__ is not None:
            return self.lamb__

        if self.shearmod__ is None or self.poisson__ is None:
            raise ValueError('Shearmod and poisson ratio are needed')

        return (
            2. * self.poisson__ * self.shearmod__) / (1. - 2. * self.poisson__)

    @lamb.setter
    def lamb(self, lamb):
        self.lamb__ = lamb

    @property
    def shearmod(self):

        if self.shearmod__ is not None:
            return self.shearmod__

        if self.poisson__ is None:
            raise ValueError('Poisson ratio is needed')

        return (8. * (1. + self.poisson__)) / (1. - 2. * self.poisson__)

    @shearmod.setter
    def shearmod(self, shearmod):
        self.shearmod__ = shearmod

    @property
    def seismic_moment(self):
        '''
        Scalar Seismic moment :math:`M_0`.

        Code copied from Kite. It disregards the opening (as for now).
        We assume :math:`M_0 = mu A D`.

        .. important ::

            We assume a perfect elastic solid with :math:`K=\\frac{5}{3}\\mu`.

            Through :math:`\\mu = \\frac{3K(1-2\\nu)}{2(1+\\nu)}` this leads to
            :math:`\\mu = \\frac{8(1+\\nu)}{1-2\\nu}`.

        :return:
            Seismic moment release.
        :rtype:
            float
        '''

        mu = self.shearmod

        disl = 0.
        if self.slip:
            disl = self.slip
        if self.opening:
            disl = (disl**2 + self.opening**2)**.5

        return mu * self.area * disl

    @property
    def moment_magnitude(self):
        '''
        Moment magnitude :math:`M_\\mathrm{w}` from seismic moment.

        We assume :math:`M_\\mathrm{w} = {\\frac{2}{3}}\\log_{10}(M_0) - 10.7`.

        :returns:
            Moment magnitude.
        :rtype:
            float
        '''
        return mt.moment_to_magnitude(self.seismic_moment)

    def source_patch(self):
        '''
        Get source location and geometry array for okada_ext.okada input.

        The values are defined according to Okada (1992).

        :return:
            Source data as input for okada_ext.okada. The order is
            northing [m], easting [m], depth [m], strike [deg], dip [deg],
            al1 [m], al2 [m], aw1 [m], aw2 [m].
        :rtype:
            :py:class:`~numpy.ndarray`: ``(9, )``
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
        Get source dislocation array for okada_ext.okada input.

        The given slip is splitted into a strike and an updip part based on the
        source rake.

        :return:
            Source dislocation data as input for okada_ext.okada. The order is
            dislocation in strike [m], dislocation updip [m], opening [m].
        :rtype:
            :py:class:`~numpy.ndarray`: ``(3, )``
        '''
        return num.array([
            num.cos(self.rake * d2r) * self.slip,
            num.sin(self.rake * d2r) * self.slip,
            self.opening])

    def discretize(self, nlength, nwidth, *args, **kwargs):
        '''
        Discretize fault into rectilinear grid of fault patches.

        Fault orientation, slip and elastic parameters are passed to the
        sub-faults unchanged.

        :param nlength:
            Number of patches in strike direction.
        :type nlength:
            int

        :param nwidth:
            Number of patches in down-dip direction.
        :type nwidth:
            int

        :return:
            Discrete fault patches.
        :rtype:
            list of :py:class:`~pyrocko.modelling.okada.OkadaPatch`
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

        rotmat = mt.euler_to_matrix(self.dip*d2r, self.strike*d2r, 0.)

        source_points_rot = num.dot(rotmat.T, source_points.T).T
        source_points_rot[:, 0] += self.northing
        source_points_rot[:, 1] += self.easting
        source_points_rot[:, 2] += self.depth

        kwargs = {
            prop: getattr(self, prop) for prop in self.T.propnames
            if prop not in [
                'north_shift', 'east_shift', 'depth',
                'al1', 'al2', 'aw1', 'aw2']}

        return (
            [OkadaPatch(
                parent=self,
                ix=src_point[0],
                iy=src_point[1],
                north_shift=coord[0],
                east_shift=coord[1],
                depth=coord[2],
                al1=al1, al2=al2, aw1=aw1, aw2=aw2, **kwargs)
             for src_point, coord in zip(source_points, source_points_rot)],
            source_points)


class OkadaPatch(OkadaSource):

    '''
    Okada source with additional 2D indexes for bookkeeping.
    '''

    ix = Int.T(help='Relative index of the patch in x')
    iy = Int.T(help='Relative index of the patch in y')

    def __init__(self, parent=None, *args, **kwargs):
        OkadaSource.__init__(self, *args, **kwargs)
        self.parent = parent


def make_okada_coefficient_matrix(
        source_patches_list,
        pure_shear=False,
        rotate_sdn=True,
        nthreads=1, variant='normal'):

    '''
    Build coefficient matrix for given fault patches.

    The boundary element method (BEM) for a discretized fault and the
    determination of the slip distribution :math:`\\Delta u` from stress drop
    :math:`\\Delta \\sigma` is based on
    :math:`\\Delta \\sigma = \\mathbf{C} \\cdot \\Delta u`. Here the
    coefficient matrix :math:`\\mathbf{C}` is built, based on the displacements
    from Okada's solution (Okada, 1992) and their partial derivatives.

    :param source_patches_list:
        Source patches, to be used in BEM.
    :type source_patches_list:
        list of :py:class:`~pyrocko.modelling.okada.OkadaSource`.

    :param pure_shear:
        If ``True``, only shear forces are taken into account.
    :type pure_shear:
        optional, bool

    :param rotate_sdn:
        If ``True``, rotate to strike, dip, normal.
    :type rotate_sdn:
        optional, bool

    :param nthreads:
        Number of threads.
    :type nthreads:
        optional, int

    :return:
        Coefficient matrix for all source combinations.
    :rtype:
        :py:class:`~numpy.ndarray`:
        ``(len(source_patches_list) * 3, len(source_patches_list) * 3)``
    '''

    if variant == 'slow':
        return _make_okada_coefficient_matrix_slow(
            source_patches_list, pure_shear, rotate_sdn, nthreads)

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

    if variant == 'normal':
        kron = kron[num.newaxis, num.newaxis, :]
    else:
        kron = kron[num.newaxis, :]

    for idisl, case_type in enumerate([
            'strikeslip', 'dipslip', 'tensileslip'][:n_eq]):
        case = disl_cases[case_type]
        source_disl = num.array([
            case['slip'] * num.cos(case['rake'] * d2r),
            case['slip'] * num.sin(case['rake'] * d2r),
            case['opening']])

        if variant == 'normal':
            results = okada_ext.okada(
                source_patches,
                num.tile(source_disl, npoints).reshape(-1, 3),
                receiver_coords,
                lambda_mean,
                mu_mean,
                nthreads=nthreads,
                rotate_sdn=int(rotate_sdn),
                stack_sources=int(variant != 'normal'))

            eps = 0.5 * (
                results[:, :, 3:] +
                results[:, :, (3, 6, 9, 4, 7, 10, 5, 8, 11)])

            dilatation \
                = eps[:, :, diag_ind].sum(axis=-1)[:, :, num.newaxis]

            stress_sdn = kron*lambda_mean*dilatation + 2.*mu_mean*eps
            coefmat[:, idisl::3] = stress_sdn[:, :, (2, 5, 8)]\
                .reshape(-1, npoints*3).T
        else:
            for isrc, source in enumerate(source_patches):
                results = okada_ext.okada(
                    source.reshape(1, -1),
                    source_disl.reshape(1, -1),
                    receiver_coords,
                    lambda_mean,
                    mu_mean,
                    nthreads=nthreads,
                    rotate_sdn=int(rotate_sdn))

                eps = 0.5 * (
                    results[:, 3:] +
                    results[:, (3, 6, 9, 4, 7, 10, 5, 8, 11)])

                dilatation \
                    = num.sum(eps[:, diag_ind], axis=1)[:, num.newaxis]
                stress_sdn \
                    = kron * lambda_mean * dilatation+2. * mu_mean * eps

                coefmat[:, isrc*3 + idisl] \
                    = stress_sdn[:, (2, 5, 8)].ravel()

    if pure_shear:
        coefmat[2::3, :] = 0.

    return -coefmat / unit_disl


def _make_okada_coefficient_matrix_slow(
        source_patches_list, pure_shear=False, rotate_sdn=True, nthreads=1):

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
            (dip + 180.) * d2r, strike * d2r, 0.)
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
                rotate_sdn=int(rotate_sdn))

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


def invert_fault_dislocations_bem(
        stress_field,
        coef_mat=None,
        source_list=None,
        pure_shear=False,
        epsilon=None,
        nthreads=1,
        **kwargs):
    '''
    BEM least squares inversion to get fault dislocations given stress field.

    Follows least squares inversion approach by Menke (1989) to calculate
    dislocations on a fault with several segments from a given stress field.
    The coefficient matrix connecting stresses and displacements of the fault
    patches can either be specified by the user (``coef_mat``) or it is
    calculated using the solution of Okada (1992) for a rectangular fault in a
    homogeneous half space (``source_list``).

    :param stress_field:
        Stress change [Pa] for each source patch (as
        ``stress_field[isource, icomponent]`` where isource indexes the source
        patch and ``icomponent`` indexes component, ordered (strike, dip,
        tensile).
    :type stress_field:
        :py:class:`~numpy.ndarray`: ``(nsources, 3)``

    :param coef_mat:
        Coefficient matrix connecting source patch dislocations and the stress
        field.
    :type coef_mat:
        optional, :py:class:`~numpy.ndarray`:
        ``(len(source_list) * 3, len(source_list) * 3)``

    :param source_list:
        Source patches to be used for BEM.
    :type source_list:
        optional, list of
        :py:class:`~pyrocko.modelling.okada.OkadaSource`

    :param epsilon:
        If given, values in ``coef_mat`` smaller than ``epsilon`` are set to
        zero.
    :type epsilon:
        optional, float

    :param nthreads:
        Number of threads allowed.
    :type nthreads:
        int

    :return:
        Inverted displacements as ``displacements[isource, icomponent]``
        where isource indexes the source patch and ``icomponent`` indexes
        component, ordered (strike, dip, tensile).
    :rtype:
        :py:class:`~numpy.ndarray`: ``(nsources, 3)``
    '''

    if source_list is not None and coef_mat is None:
        coef_mat = make_okada_coefficient_matrix(
            source_list, pure_shear=pure_shear, nthreads=nthreads,
            **kwargs)

    if epsilon is not None:
        coef_mat[coef_mat < epsilon] = 0.

    idx = num.arange(0, coef_mat.shape[0])
    if pure_shear:
        idx = idx[idx % 3 != 2]

    coef_mat_in = coef_mat[idx, :][:, idx]
    disloc_est = num.zeros(coef_mat.shape[0])

    if stress_field.ndim == 2:
        stress_field = stress_field.ravel()

    threadpool_limits = get_threadpool_limits()

    with threadpool_limits(limits=nthreads, user_api='blas'):
        try:
            disloc_est[idx] = num.linalg.multi_dot([
                num.linalg.inv(num.dot(coef_mat_in.T, coef_mat_in)),
                coef_mat_in.T,
                stress_field[idx]])
        except num.linalg.LinAlgError as e:
            logger.warning('Linear inversion failed!')
            logger.warning(
                'coef_mat: %s\nstress_field: %s',
                coef_mat_in, stress_field[idx])
            raise e
        return disloc_est.reshape(-1, 3)


__all__ = [
    'AnalyticalSource',
    'AnalyticalRectangularSource',
    'OkadaSource',
    'OkadaPatch',
    'make_okada_coefficient_matrix',
    'invert_fault_dislocations_bem']
