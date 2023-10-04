# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Recursive STA/LTA.
'''

from . import autopick_ext
import numpy as num


class AutopickError(Exception):
    pass


def recursive_stalta(
        tshort, tlong, kshort, klong, kderivative, energytrace,
        temp=None, inplace=True):

    if not energytrace.ydata.dtype == num.float32:
        raise AutopickError(
            'energytrace given to recursive_stalta() must have data in '
            'float32 format.')

    ns = int(round(tshort/energytrace.deltat))
    nl = int(round(tlong/energytrace.deltat))

    if temp is None:
        temp = num.zeros((ns+2,), dtype=num.float32)

    if not inplace:
        energytrace = energytrace.copy()

    autopick_ext.recursive_stalta(
        ns, nl, kshort/ns, klong/nl, kderivative, energytrace.ydata,
        temp, temp is None)

    if inplace:
        return temp
    else:
        return energytrace, temp
