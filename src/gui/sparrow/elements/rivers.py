# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------


from pyrocko.guts import String
from .gshhg import GSHHGElement, GSHHGState

guts_prefix = 'sparrow'


class RiversState(GSHHGState):

    dataset = String.T(default='rivers')

    def create(self):
        element = RiversElement()
        return element


class RiversElement(GSHHGElement):

    def __init__(self):
        GSHHGElement.__init__(self)

    def get_name(self):
        return 'Rivers'

    def bind_state(self, state):
        GSHHGElement.bind_state(self, state)


__all__ = [
    'RiversElement',
    'RiversState']
