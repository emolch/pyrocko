# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
2-way state binding utilities for Qt/talkie.
'''

import logging

from pyrocko.gui import util as gui_util
from pyrocko.color import Color

logger = logging.getLogger('pyrocko.gui.state')


def state_bind(
        owner, state, paths, update_state,
        widget, signals, update_widget, attribute=None):

    def make_wrappers(widget):
        def wrap_update_widget(*args):
            if attribute:
                update_widget(state, attribute, widget)
            else:
                update_widget(state, widget)
            gui_util.de_errorize(widget)

        def wrap_update_state(*args):
            try:
                if attribute:
                    update_state(widget, state, attribute)
                else:
                    update_state(widget, state)
                gui_util.de_errorize(widget)
            except Exception as e:
                logger.warn('Caught exception: %s' % e)
                gui_util.errorize(widget)

        return wrap_update_widget, wrap_update_state

    wrap_update_widget, wrap_update_state = make_wrappers(widget)

    for sig in signals:
        sig.connect(wrap_update_state)

    for path in paths:
        owner.talkie_connect(state, path, wrap_update_widget)

    wrap_update_widget()


def state_bind_slider(
        owner, state, path, widget, factor=1.,
        dtype=float,
        min_is_none=False,
        max_is_none=False):

    viewer = gui_util.get_app().get_main_window()
    widget.sliderPressed.connect(viewer.disable_capture)
    widget.sliderReleased.connect(viewer.enable_capture)

    def make_funcs():
        def update_state(widget, state):
            val = widget.value()
            if (min_is_none and val == widget.minimum()) \
                    or (max_is_none and val == widget.maximum()):
                state.set(path, None)
            else:
                viewer.status('%g' % (val * factor))
                state.set(path, dtype(val * factor))

        def update_widget(state, widget):
            val = state.get(path)
            widget.blockSignals(True)
            if min_is_none and val is None:
                widget.setValue(widget.minimum())
            elif max_is_none and val is None:
                widget.setValue(widget.maximum())
            else:
                widget.setValue(int(state.get(path) * 1. / factor))
            widget.blockSignals(False)

        return update_state, update_widget

    update_state, update_widget = make_funcs()

    state_bind(
        owner, state, [path], update_state, widget, [widget.valueChanged],
        update_widget)


def state_bind_slider_float(
        owner, state, path, widget,
        min_is_none=False,
        max_is_none=False):

    assert isinstance(widget, gui_util.QSliderFloat)

    viewer = gui_util.get_app().get_main_window()
    widget.sliderPressed.connect(viewer.disable_capture)
    widget.sliderReleased.connect(viewer.enable_capture)

    def make_funcs():
        def update_state(widget, state):
            val = widget.valueFloat()
            if (min_is_none and val == widget.minimumFloat()) \
                    or (max_is_none and val == widget.maximumFloat()):
                state.set(path, None)
            else:
                viewer.status('%g' % (val))
                state.set(path, val)

        def update_widget(state, widget):
            val = state.get(path)
            widget.blockSignals(True)
            if min_is_none and val is None:
                widget.setValueFloat(widget.minimumFloat())
            elif max_is_none and val is None:
                widget.setValueFloat(widget.maximumFloat())
            else:
                widget.setValueFloat(state.get(path))
            widget.blockSignals(False)

        return update_state, update_widget

    update_state, update_widget = make_funcs()

    state_bind(
        owner, state, [path], update_state, widget, [widget.valueChanged],
        update_widget)


def state_bind_spinbox(owner, state, path, widget, factor=1., dtype=float):
    return state_bind_slider(owner, state, path, widget, factor, dtype)


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


def state_bind_combobox_color(owner, state, path, widget):

    def make_funcs():
        def update_state(widget, state):
            value = str(widget.currentText())
            state.set(path, Color(value))

        def update_widget(state, widget):
            widget.blockSignals(True)
            val = str(state.get(path))
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


def state_bind_lineedit(
        owner, state, path, widget, from_string=str, to_string=str):

    def make_funcs():

        def update_state(widget, state):
            state.set(path, from_string(widget.text()))

        def update_widget(state, widget):
            widget.blockSignals(True)
            widget.setText(to_string(state.get(path)))
            widget.blockSignals(False)

        return update_state, update_widget

    update_state, update_widget = make_funcs()

    state_bind(
        owner,
        state, [path], update_state,
        widget, [widget.editingFinished, widget.returnPressed], update_widget)
