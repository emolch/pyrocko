# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num
from .base import DelayMethod
from ..grid.slowness import SlownessGrid
from ..grid.location import LocationGrid


class PlaneWaveDM(DelayMethod):
    def calculate(self, source_grid, receiver_grid):

        self._check_type('source_grid', source_grid, SlownessGrid)
        self._check_type('receiver_grid', receiver_grid, LocationGrid)

        slownesses = source_grid.get_nodes('ned')
        ned = receiver_grid.get_nodes('ned')
        return num.sum(
            slownesses[:, num.newaxis, :] * ned[num.newaxis, :, :], axis=2)


__all__ = [
    'PlaneWaveDM',
]
