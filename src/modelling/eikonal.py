# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
FMM solver for the  eikonal equation in 2D and 3D.
'''

from .. import eikonal_ext


def eikonal_solver_fmm_cartesian(speeds, times, delta):
    '''
    Solve eikonal equation in 2D or 3D using the fast marching method.

    This function implements the fast marching method (FMM) by [sethian1996]_.

    :param speeds:
        Velocities at the grid nodes.
    :type speeds:
        2D or 3D :py:class:`numpy.ndarray`

    :param times:
        Arrival times (input and output). The solution is obtained at nodes
        where times is set to a negative value. Values of zero, or positive
        values are used as seeding points.
    :type times:
        2D or 3D :py:class:`numpy.ndarray`, same shape as `speeds`

    :param delta:
        Grid spacing.
    :type delta:
        float

    .. [sethian1996] Sethian, James A. "A fast marching level set method for
        monotonically advancing fronts." Proceedings of the National Academy of
        Sciences 93.4 (1996): 1591-1595. https://doi.org/10.1073/pnas.93.4.1591
    '''

    return eikonal_ext.eikonal_solver_fmm_cartesian(speeds, times, delta)
