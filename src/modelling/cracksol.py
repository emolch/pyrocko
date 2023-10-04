# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Analytical crack solutions for surface displacements and fault dislocations.
'''

import numpy as num
import logging

from pyrocko.guts import Float, Object
from pyrocko.guts_array import Array

guts_prefix = 'modelling'

logger = logging.getLogger(__name__)


class GriffithCrack(Object):
    '''
    Analytical Griffith crack model.
    '''

    width = Float.T(
        help='Width equals to :math:`2 \\cdot a`.',
        default=1.)

    poisson = Float.T(
        help='Poisson ratio :math:`\\nu`.',
        default=.25)

    shearmod = Float.T(
        help='Shear modulus :math:`\\mu` [Pa].',
        default=1.e9)

    stressdrop = Array.T(
        help='Stress drop array:'
             '[:math:`\\sigma_{3,r} - \\sigma_{3,c}`, '
             ':math:`\\sigma_{2,r} - \\sigma_{2,c}`, '
             ':math:`\\sigma_{1,r} - \\sigma_{1,c}`] :math:`=` '
             '[:math:`\\Delta \\sigma_{strike}, '
             '\\Delta \\sigma_{dip}, \\Delta \\sigma_{tensile}`].',
        default=num.array([0., 0., 0.]))

    @property
    def a(self):
        '''
        Half width of the crack in [m].
        '''

        return self.width / 2.

    def disloc_infinite2d(self, x_obs):
        '''
        Calculation of dislocation at crack surface along x2 axis.

        Follows equations by Pollard and Segall (1987) to calculate
        dislocations for an infinite 2D crack extended in x3 direction,
        opening in x1 direction and the crack extending in x2 direction.

        :param x_obs:
            Observation point coordinates along x2-axis.
            If :math:`x_{obs} < -a` or :math:`x_{obs} > a`, output dislocations
            are zero.
        :type x_obs:
            :py:class:`~numpy.ndarray`: ``(N,)``

        :return:
            Dislocations at each observation point in strike, dip and
            tensile direction.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(N, 3)``
        '''

        if type(x_obs) is not num.ndarray:
            x_obs = num.array(x_obs)

        factor = num.array([2. / self.shearmod])
        factor = num.append(
            factor, num.tile(
                2. * (1. - self.poisson) / self.shearmod, (1, 2)))
        factor[1] *= -1.

        crack_el = (x_obs > -self.a) | (x_obs < self.a)

        disl = num.zeros((x_obs.shape[0], 3))
        disl[crack_el, :] = \
            self.stressdrop * num.sqrt(
            self.a**2 - num.tile(x_obs[crack_el, num.newaxis], (1, 3))**2) * \
            factor

        return disl

    def disloc_circular(self, x_obs):
        '''
        Calculation of dislocation at crack surface along x2 axis.

        Follows equations by Pollard and Segall (1987) to calculate
        displacements for a circulat crack extended in x2 and x3 direction and
        opening in x1 direction.

        :param x_obs:
            Observation point coordinates along axis through crack
            centre. If :math:`x_{obs} < -a` or :math:`x_{obs} > a`, output
            dislocations are zero.
        :type x_obs:
            :py:class:`~numpy.ndarray`: ``(N,)``

        :return:
            Dislocations at each observation point in strike, dip and
            tensile direction.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(N, 3)``
        '''

        if type(x_obs) is not num.ndarray:
            x_obs = num.array(x_obs)

        factor = num.array([4. / (self.shearmod * num.pi)])
        factor = num.append(
            factor, num.tile(
                4. * (1. - self.poisson) / (self.shearmod * num.pi), (1, 2)))
        factor[1] *= -1.

        crack_el = (x_obs > -self.a) | (x_obs < self.a)

        disl = num.zeros((x_obs.shape[0], 3))
        disl[crack_el] = \
            self.stressdrop * num.sqrt(
            self.a**2 - num.tile(x_obs[crack_el, num.newaxis], (1, 3))**2) * \
            factor

        return disl

    def _displ_infinite2d_along_x1(self, x1_obs):
        '''
        Calculation of displacement at crack surface along x1-axis.

        Follows equations by Pollard and Segall (1987) to calculate
        displacements for an infinite 2D crack extended in x3 direction,
        opening in x1 direction and the crack tip in x2 direction.

        :param x1_obs:
            Observation point coordinates along x1-axis.
        :type x1_obs:
            :py:class:`~numpy.ndarray`: ``(N,)``

        :return:
            Displacements at each observation point in strike, dip and
            tensile direction.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(M, 3)``
        '''
        displ = num.zeros((x1_obs.shape[0], 3))

        if self.stressdrop[0] != 0.:
            sign = num.sign(x1_obs)
            x1_ratio = x1_obs / self.a

            displ[:, 0] = (
                num.sqrt((x1_ratio)**2 + 1.) - num.abs(
                    x1_ratio)
            ) * self.stressdrop[0] * self.a / self.shearmod * sign

        return displ

    def _displ_infinite2d_along_x2(self, x2_obs):
        '''
        Calculation of displacement at crack surface along x2-axis.

        Follows equations by Pollard and Segall (1987) to calculate
        displacements for an infinite 2D crack extended in x3 direction,
        opening in x1 direction and the crack tip in x2 direction.

        :param x2_obs:
            Observation point coordinates along x2-axis.
        :type x2_obs:
            :py:class:`~numpy.ndarray`: ``(N,)``

        :return:
            Displacements at each observation point in strike, dip and
            tensile direction.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(N, 3)``
        '''

        crack_el = (x2_obs >= -self.a) & (x2_obs <= self.a)

        displ = num.zeros((x2_obs.shape[0], 3))

        if self.stressdrop[1] != 0.:
            factor = (1. - 2. * self.poisson) / (2. * self.shearmod)

            displ[crack_el, 2] = \
                self.stressdrop[1] * factor * x2_obs[crack_el]

            sign = num.sign(x2_obs)

            displ[~crack_el, 2] = \
                self.stressdrop[1] * factor * self.a * sign[~crack_el] * (
                    num.abs(x2_obs[~crack_el] / self.a) -
                    num.sqrt(x2_obs[~crack_el]**2 / self.a**2 - 1.))

        return displ

    def displ_infinite2d(self, x1_obs, x2_obs):
        '''
        Calculation of displacement at crack surface along different axis.

        Follows equations by Pollard and Segall (1987) to calculate
        displacements for an infinite 2D crack extended in x3 direction,
        opening in x1 direction and the crack tip in x2 direction.

        :param x1_obs:
            Observation point coordinates along x1-axis.
            If :math:`x1_obs = 0.`, displacment is calculated along x2-axis.
        :type x1_obs:
            :py:class:`~numpy.ndarray`: ``(M,)``

        :param x2_obs:
            Observation point coordinates along x2-axis.
            If :math:`x2_obs = 0.`, displacment is calculated along x1-axis.
        :type x2_obs:
            :py:class:`~numpy.ndarray`: ``(N,)``

        :return:
            Displacements at each observation point in strike, dip and
            tensile direction.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(M, 3)`` or ``(N, 3)``
        '''

        if type(x1_obs) is not num.ndarray:
            x1_obs = num.array(x1_obs)
        if type(x2_obs) is not num.ndarray:
            x2_obs = num.array(x2_obs)

        if (x1_obs == 0.).all():
            return self._displ_infinite2d_along_x2(x2_obs)
        elif (x2_obs == 0.).all():
            return self._displ_infinite2d_along_x1(x1_obs)


__all__ = [
    'GriffithCrack']
