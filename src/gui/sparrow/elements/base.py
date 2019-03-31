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
        self._parent = None
        self._state = None

    def register_state_listener(self, listener):
        self._listeners.append(listener)  # keep listeners alive

    def remove(self):
        if self._parent and self._state:
            self._parent.state.elements.remove(self._state)

    def set_parent(self, parent):
        self._parent = parent

    def unset_parent(self):
        self._parent = None

    def bind_state(self, state):
        self._state = state

    def unbind_state(self):
        self._listeners = []
        self._state = None
