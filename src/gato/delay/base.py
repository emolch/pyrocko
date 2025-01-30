# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from pyrocko.guts import Object, Timestamp
from pyrocko.guts_array import Array

from pyrocko.gato.grid.base import Grid

NA = num.newaxis


class DelayMethod(Object):
    '''Base class for time-delay calculators.'''

    def _check_type(self, name, obj, cls):

        if not isinstance(obj, cls):
            raise ValueError(
                'Need %s of type %s to calculate time delays with %s, not %s.'
                % (
                    name,
                    cls.__name__,
                    self.__class__.__name__,
                    obj.__class__.__name__))

    def calculate(
            self,
            source_grid,
            receiver_grid):

        '''
        Get time delays for combinations of source and receiver grid nodes.
        '''

        raise NotImplementedError()


class GenericDelayTable(Object):
    source_grid = Grid.T()
    receiver_grid = Grid.T()
    method = DelayMethod.T()
    reference_time = Timestamp.T(optional=True)
    source_delays = Array.T(optional=True, shape=(None,), dtype=num.float64)
    receiver_delays = Array.T(optional=True, shape=(None,), dtype=num.float64)

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self.clear_cached()

    def clear_cached(self):
        self._delays = None

    def get_delays(self):
        if self._delays is None:
            delays = self.method.calculate(
                self.source_grid, self.receiver_grid)

            if self.reference_time is not None:
                delays -= self.reference_time

            if self.receiver_delays is not None:
                delays += self.receiver_delays[num.newaxis, :]

            if self.source_delays is not None:
                delays += self.source_delays[:, num.newaxis]

            self._delays = delays

        return self._delays

    def get_delay_spectra(self, frequencies):
        delays = self.get_delays()
        return num.exp(2.0j*num.pi*frequencies[NA, NA, :]*delays[:, :, NA])


__all__ = [
    'DelayMethod',
    'GenericDelayTable',
]
