# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

from pyrocko.gui.talkie import TalkieRoot


class ElementState(TalkieRoot):
    pass


class Element(object):
    def __init__(self):
        self._listeners = []

    def register_state_listener(self, listener):
        self._listeners.append(listener)  # keep listeners alive
