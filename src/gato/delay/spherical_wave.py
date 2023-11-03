# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from pyrocko.guts import Float

from .base import DelayMethod
from ..grid.location import LocationGrid, distances_3d


class SphericalWaveDM(DelayMethod):
    velocity = Float.T()

    def calculate(self, source_grid, receiver_grid):
        self._check_type('source_grid', source_grid, LocationGrid)
        self._check_type('receiver_grid', receiver_grid, LocationGrid)

        return distances_3d(source_grid, receiver_grid) / self.velocity


__all__ = [
    'SphericalWaveDM',
]
