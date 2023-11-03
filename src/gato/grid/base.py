# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import math
import numpy as num

from pyrocko.guts import Object, StringChoice

from ..error import GatoError

guts_prefix = 'gato'


class GridSnapError(GatoError):
    pass


class GridSnap(StringChoice):
    '''
    Flag to indicate how grid inconsistencies are handled.

     ``'both'``: adjust minimum and maximum to be multiples of given spacing.
     ``'min'``: adjust minimum only. ``'max'``: adjust maximum only.
     ``'fail'``: raise an error.
    '''
    choices = ['both', 'max', 'min', 'fail']


def grid_snap(vmin, vmax, vdelta, snap, eps=1e-6):
    vanchor = {
        'fail': vmin,
        'both': 0.,
        'min': vmax,
        'max': vmin}[snap]

    veps = vdelta * eps

    vmin_new = vanchor + math.floor((vmin-vanchor+veps) / vdelta) * vdelta
    vmax_new = vanchor + math.ceil((vmax-vanchor-veps) / vdelta) * vdelta

    if snap == 'fail':
        if abs(vmin_new - vmin) > veps or abs(vmax_new - vmax) > veps:
            raise GridSnapError(
                'Invalid grid specification: min: %g, max: %g, step: %g, '
                'snap: %s' % (vmin, vmax, vdelta, snap))

    n = int(round((vmax_new-vmin_new) / vdelta)) + 1

    return vmin_new, vmax_new, n


def grid_coordinates(vmin, vmax, vdelta, snap, eps=1e-6):
    return num.linspace(*grid_snap(vmin, vmax, vdelta, snap, eps))


class Grid(Object):
    '''
    Base class for Gato grids.

    Grids can consist of location or slowness vectors.
    '''

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self.update()

    def update(self):
        raise NotImplementedError()

    @property
    def shape(self):
        '''
        Logical shape of the grid.
        '''
        raise NotImplementedError()

    @property
    def size(self):
        '''
        Number of grid nodes.
        '''
        raise NotImplementedError()

    @property
    def effective_dimension(self):
        '''
        Number of non-flat dimensions.
        '''
        raise NotImplementedError()

    def __len__(self):
        return self.size


__all__ = [
    'Grid',
    'GridSnapError',
]
