# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import logging

import numpy as num

from pyrocko import util
from pyrocko.guts import StringChoice, Float, List, Bool, Timestamp, Tuple, \
    Duration, Object, get_elements, set_elements, path_to_str, clone

from pyrocko.color import Color, interpolate as interpolate_color

from pyrocko.gui import talkie
from pyrocko.gui import util as gui_util
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
    fixed_size = Tuple.T(2, Float.T(), optional=True)
    focal_point = FocalPointChoice.T(default='center')
    detached = Bool.T(default=False)
    tcursor = Timestamp.T(optional=True)

    def next_focal_point(self):
        choices = FocalPointChoice.choices
        ii = choices.index(self.focal_point)
        self.focal_point = choices[(ii+1) % len(choices)]


class Background(Object):
    color = Color.T(default=Color.D('black'))

    def vtk_apply(self, ren):
        ren.GradientBackgroundOff()
        ren.SetBackground(*self.color.rgb)

    def __str__(self):
        return str(self.color)

    @property
    def color_top(self):
        return self.color

    @property
    def color_bottom(self):
        return self.color

    # def __eq__(self, other):
    #     print('in==', self.color.rgb, other.color.rgb)
    #     return type(self) is type(other) and self.color == other.color


class BackgroundGradient(Background):
    color_top = Color.T(default=Color.D('skyblue1'))
    color_bottom = Color.T(default=Color.D('white'))

    def vtk_apply(self, ren):
        ren.GradientBackgroundOn()
        ren.SetBackground(*self.color_bottom.rgb)
        ren.SetBackground2(*self.color_top.rgb)

    def __str__(self):
        return '%s - %s' % (self.color_top, self.color_bottom)

    # def __eq__(self, other):
    #     return type(self) is type(other) and \
    #         self.color_top == other.color_top and \
    #         self.color_bottom == other.color_bottom


def interpolate_background(a, b, blend):
    if type(a) is Background and type(b) is Background:
        return Background(color=interpolate_color(a.color, b.color, blend))
    else:
        return BackgroundGradient(
            color_top=interpolate_color(
                a.color_top, b.color_top, blend),
            color_bottom=interpolate_color(
                a.color_bottom, b.color_bottom, blend))


@talkie.has_computed
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
    tduration = Duration.T(optional=True)
    tposition = Float.T(default=0.0)
    lighting = LightingChoice.T(default=LightingChoice.choices[0])
    background = Background.T(default=Background.D(color=Color('black')))

    @talkie.computed(['tmin', 'tmax', 'tduration', 'tposition'])
    def tmin_effective(self):
        return common.tmin_effective(
            self.tmin, self.tmax, self.tduration, self.tposition)

    @talkie.computed(['tmin', 'tmax', 'tduration', 'tposition'])
    def tmax_effective(self):
        return common.tmax_effective(
            self.tmin, self.tmax, self.tduration, self.tposition)

    def sort_elements(self):
        self.elements.sort(key=lambda el: el.element_id)


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
                logger.warn('Caught exception: %s' % e)
                common.errorize(widget)

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

    viewer = common.get_viewer()
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

    viewer = common.get_viewer()
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


def state_bind_combobox_background(owner, state, path, widget):

    def make_funcs():
        def update_state(widget, state):
            values = str(widget.currentText()).split(' - ')
            if len(values) == 1:
                state.set(
                    path,
                    Background(color=Color(values[0])))

            elif len(values) == 2:
                state.set(
                    path,
                    BackgroundGradient(
                        color_top=Color(values[0]),
                        color_bottom=Color(values[1])))

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


def interpolateables(state_a, state_b):

    animate = []
    for tag, path, values in state_b.diff(state_a):
        if tag == 'set':
            ypath = path_to_str(path)
            v_new = get_elements(state_b, ypath)[0]
            v_old = values
            for type in [float, Color, Background]:
                if isinstance(v_old, type) and isinstance(v_new, type):
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
        times_inter = util.arange2(
            self.tmin, self.tmax, self.dt, error='floor')
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
                        if ypath in ('lon', 'strike'):
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

                    elif isinstance(v_old, Color) and isinstance(v_new, Color):
                        v_inter = interpolate_color(v_old, v_new, blend)
                        set_elements(state, ypath, v_inter)

                    elif isinstance(v_old, Background) \
                            and isinstance(v_new, Background):
                        v_inter = interpolate_background(v_old, v_new, blend)
                        set_elements(state, ypath, v_inter)

                    else:
                        set_elements(state, ypath, v_new)

                states_inter.append(state)

        self._states_inter = states_inter

    def __call__(self, t):
        itime = int(round((t - self.tmin) / self.dt))
        itime = min(max(0, itime), len(self._states_inter)-1)
        return self._states_inter[itime]
