# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------


from pyrocko.guts import String
from .gshhg import GSHHGElement, GSHHGState

guts_prefix = 'sparrow'


class BordersState(GSHHGState):

    dataset = String.T(default='borders')

    def create(self):
        element = BordersElement()
        return element


class BordersElement(GSHHGElement):

    def __init__(self):
        GSHHGElement.__init__(self)

    def get_name(self):
        return 'Borders'

    def bind_state(self, state):
        GSHHGElement.bind_state(self, state)


__all__ = [
    'BordersElement',
    'BordersState']
