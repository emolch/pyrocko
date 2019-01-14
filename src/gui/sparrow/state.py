# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import logging
import time

from pyrocko.guts import StringChoice, Float, List, Bool

from pyrocko.gui import talkie
from . import common

guts_prefix = 'sparrow'

logger = logging.getLogger('pyrocko.gui.sparrow.state')


class FocalPointChoice(StringChoice):
    choices = ['center', 'target']


class ViewerState(talkie.TalkieRoot):
    lat = Float.T(default=0.0)
    lon = Float.T(default=0.0)
    depth = Float.T(default=0.0)
    strike = Float.T(default=90.0)
    dip = Float.T(default=0.0)
    focal_point = FocalPointChoice.T(default='center')
    distance = Float.T(default=3.0)
    elements = List.T(talkie.Talkie.T())
    panels_visible = Bool.T(default=True)
    tmin = Float.T(default=time.time() - 3600.)
    tmax = Float.T(default=time.time())

    def next_focal_point(self):
        choices = FocalPointChoice.choices
        ii = choices.index(self.focal_point)
        self.focal_point = choices[(ii+1) % len(choices)]


def state_bind(
        owner, state, paths, update_state,
        widget, signals, update_widget, attribute=None):

    def make_wrappers(widget):
        def wrap_update_widget(*args):
            if attribute:
                update_widget(state, attribute, widget)
            else:
                update_widget(state, widget)
            common.de_errorize(widget)

        def wrap_update_state(*args):
            try:
                if attribute:
                    update_state(widget, state, attribute)
                else:
                    update_state(widget, state)
                common.de_errorize(widget)
            except Exception as e:
                logger.warn('caught exception: %s' % e)
                common.errorize(widget)

        return wrap_update_widget, wrap_update_state

    wrap_update_widget, wrap_update_state = make_wrappers(widget)

    for sig in signals:
        sig.connect(wrap_update_state)

    for path in paths:
        owner.register_state_listener(wrap_update_widget)
        state.add_listener(wrap_update_widget, path)

    wrap_update_widget()


def state_bind_slider(owner, state, path, widget, factor=1.):

    def make_funcs():
        def update_state(widget, state):
            state.set(path, widget.value() * factor)

        def update_widget(state, widget):
            widget.blockSignals(True)
            widget.setValue(state.get(path) * 1. / factor)
            widget.blockSignals(False)

        return update_state, update_widget

    update_state, update_widget = make_funcs()

    state_bind(
        owner, state, [path], update_state, widget, [widget.valueChanged],
        update_widget)


def state_bind_combobox(owner, state, path, widget):

    def make_funcs():
        def update_state(widget, state):
            state.set(path, str(widget.currentText()))

        def update_widget(state, widget):
            widget.blockSignals(True)
            val = state.get(path)
            for i in range(widget.count()):
                if str(widget.itemText(i)) == val:
                    widget.setCurrentIndex(i)
            widget.blockSignals(False)

        return update_state, update_widget

    update_state, update_widget = make_funcs()

    state_bind(
        owner, state, [path], update_state, widget, [widget.activated],
        update_widget)


def state_bind_checkbox(owner, state, path, widget):

    def make_funcs():
        def update_state(widget, state):
            state.set(path, bool(widget.isChecked()))

        def update_widget(state, widget):
            widget.blockSignals(True)
            widget.setChecked(state.get(path))
            widget.blockSignals(False)

        return update_state, update_widget

    update_state, update_widget = make_funcs()

    state_bind(
        owner, state, [path], update_state, widget, [widget.toggled],
        update_widget)
