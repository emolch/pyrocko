# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import logging

import numpy as num

from pyrocko import util
from pyrocko.guts import StringChoice, Float, List, Bool, Timestamp, Tuple, \
    get_elements, set_elements, path_to_str, clone

from pyrocko.gui import talkie
from . import common, light

guts_prefix = 'sparrow'

logger = logging.getLogger('pyrocko.gui.sparrow.state')


class FocalPointChoice(StringChoice):
    choices = ['center', 'target']


class ShadingChoice(StringChoice):
    choices = ['flat', 'gouraud', 'phong', 'pbr']


class LightingChoice(StringChoice):
    choices = light.get_lighting_theme_names()


class ViewerGuiState(talkie.TalkieRoot):
    panels_visible = Bool.T(default=True)
    size = Tuple.T(2, Float.T(), default=(100., 100.))
    focal_point = FocalPointChoice.T(default='center')

    def next_focal_point(self):
        choices = FocalPointChoice.choices
        ii = choices.index(self.focal_point)
        self.focal_point = choices[(ii+1) % len(choices)]


class ViewerState(talkie.TalkieRoot):
    lat = Float.T(default=0.0)
    lon = Float.T(default=0.0)
    depth = Float.T(default=0.0)
    strike = Float.T(default=90.0)
    dip = Float.T(default=0.0)
    distance = Float.T(default=3.0)
    elements = List.T(talkie.Talkie.T())
    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)
    lighting = LightingChoice.T(default=LightingChoice.choices[0])


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


def state_bind_slider(owner, state, path, widget, factor=1., dtype=float):

    def make_funcs():
        def update_state(widget, state):
            state.set(path, dtype(widget.value() * factor))

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


def state_bind_lineedit(owner, state, path, widget):

    def make_funcs():

        def update_state(widget, state):
            state.set(path, str(widget.text()))

        def update_widget(state, widget):
            widget.blockSignals(True)
            widget.setText(state.get(path))
            widget.blockSignals(False)

        return update_state, update_widget

    update_state, update_widget = make_funcs()

    state_bind(
        owner,
        state, [path], update_state,
        widget, [widget.editingFinished, widget.returnPressed], update_widget)


def interpolateables(state_a, state_b):

    animate = []
    for tag, path, values in state_a.diff(state_b):
        if tag == 'set':
            ypath = path_to_str(path)
            v_old = get_elements(state_a, ypath)[0]
            v_new = values
            if isinstance(v_old, float) and isinstance(v_new, float):
                animate.append((ypath, v_old, v_new))

    return animate


def interpolate(times, states, times_inter):

    assert len(times) == len(states)

    states_inter = []
    for i in range(len(times) - 1):

        state_a = states[i]
        state_b = states[i+1]
        time_a = times[i]
        time_b = times[i+1]

        animate = interpolateables(state_a, state_b)

        if i == 0:
            times_inter_this = times_inter[num.logical_and(
                time_a <= times_inter, times_inter <= time_b)]
        else:
            times_inter_this = times_inter[num.logical_and(
                time_a < times_inter, times_inter <= time_b)]

        for time_inter in times_inter_this:
            state = clone(state_b)
            if time_b == time_a:
                blend = 0.
            else:
                blend = (time_inter - time_a) / (time_b - time_a)

            for ypath, v_old, v_new in animate:
                if isinstance(v_old, float) and isinstance(v_new, float):
                    if ypath == 'strike':
                        if v_new - v_old > 180.:
                            v_new -= 360.
                        elif v_new - v_old < -180.:
                            v_new += 360.

                    if ypath != 'distance':
                        v_inter = v_old + blend * (v_new - v_old)
                    else:
                        v_old = num.log(v_old)
                        v_new = num.log(v_new)
                        v_inter = v_old + blend * (v_new - v_old)
                        v_inter = num.exp(v_inter)

                    set_elements(state, ypath, v_inter)
                else:
                    set_elements(state, ypath, v_new)

            states_inter.append(state)

    return states_inter


class Interpolator(object):

    def __init__(self, times, states, fps=25.):

        assert len(times) == len(states)

        self.dt = 1.0 / fps
        self.tmin = times[0]
        self.tmax = times[-1]
        times_inter = util.arange2(self.tmin, self.tmax, self.dt)
        times_inter[-1] = times[-1]

        states_inter = []
        for i in range(len(times) - 1):

            state_a = states[i]
            state_b = states[i+1]
            time_a = times[i]
            time_b = times[i+1]

            animate = interpolateables(state_a, state_b)

            if i == 0:
                times_inter_this = times_inter[num.logical_and(
                    time_a <= times_inter, times_inter <= time_b)]
            else:
                times_inter_this = times_inter[num.logical_and(
                    time_a < times_inter, times_inter <= time_b)]

            for time_inter in times_inter_this:
                state = clone(state_b)

                if time_b == time_a:
                    blend = 0.
                else:
                    blend = (time_inter - time_a) / (time_b - time_a)

                for ypath, v_old, v_new in animate:
                    if isinstance(v_old, float) and isinstance(v_new, float):
                        if ypath == 'strike':
                            if v_new - v_old > 180.:
                                v_new -= 360.
                            elif v_new - v_old < -180.:
                                v_new += 360.

                        if ypath != 'distance':
                            v_inter = v_old + blend * (v_new - v_old)
                        else:
                            v_old = num.log(v_old)
                            v_new = num.log(v_new)
                            v_inter = v_old + blend * (v_new - v_old)
                            v_inter = num.exp(v_inter)

                        set_elements(state, ypath, v_inter)
                    else:
                        set_elements(state, ypath, v_new)

                states_inter.append(state)

        self._states_inter = states_inter

    def __call__(self, t):
        itime = int(round((t - self.tmin) / self.dt))
        itime = min(max(0, itime), len(self._states_inter)-1)
        return self._states_inter[itime]
