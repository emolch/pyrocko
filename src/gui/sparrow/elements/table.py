# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import copy

import numpy as num

from pyrocko.guts import Bool, Float, String, StringChoice
from pyrocko.gui.vtk_util import ScatterPipe, BeachballPipe
from pyrocko.gui.qt_compat import qw, qc

from . import base
from .. import common

guts_prefix = 'sparrow'
km = 1e3


def inormalize(x, imin, imax, discrete=True):

    xmin = num.nanmin(x)
    xmax = num.nanmax(x)
    if xmin == xmax:
        xmin -= 0.5
        xmax += 0.5

    rmin = imin - 0.5
    rmax = imax + 0.5

    if discrete:
        return num.clip(
            num.round(
                rmin + (x - xmin) * (
                    (rmax-rmin) / (xmax - xmin))).astype(num.int),
            imin, imax)
    else:
        return num.clip(
            rmin + (x - xmin) * ((rmax-rmin) / (xmax - xmin)),
            imin, imax)


def string_to_sorted_idx(values):
    val_sort = num.sort(values, axis=-1, kind='mergesort')
    val_sort_unique = num.unique(val_sort)

    val_to_idx = dict([
        (val_sort_unique[i], i)
        for i in range(val_sort_unique.shape[0])])

    return num.array([val_to_idx[val] for val in values])


class SymbolChoice(StringChoice):
    choices = ['point', 'sphere', 'beachball']


class MaskingShapeChoice(StringChoice):
    choices = ['rect', 'linear', 'quadratic']


class MaskingModeChoice(StringChoice):
    choices = ['past + future', 'past', 'future']

    @classmethod
    def get_factors(cls, mode, value_low):
        return {
            'past + future': (value_low, 1.0, value_low),
            'past': (value_low, 1.0, 0.0),
            'future': (0.0, 1.0, value_low)}[mode]


class TableState(base.ElementState):
    visible = Bool.T(default=True)
    size = Float.T(default=3.0)
    color_parameter = String.T(optional=True)
    cpt = base.CPTState.T(default=base.CPTState.D())
    size_parameter = String.T(optional=True)
    depth_min = Float.T(default=-60*km)
    depth_max = Float.T(default=700*km)
    depth_offset = Float.T(default=0.0)
    symbol = SymbolChoice.T(default='sphere')
    time_masking_opacity = Float.T(default=0.0)
    time_masking_shape = MaskingShapeChoice.T(default='rect')
    time_masking_mode = MaskingModeChoice.T(default='past + future')


class TableElement(base.Element):
    def __init__(self):
        base.Element.__init__(self)
        self._parent = None

        self._table = None
        self._istate = 0
        self._istate_view = 0

        self._controls = None
        self._color_combobox = None
        self._size_combobox = None

        self._pipes = None
        self._isize_min = 1
        self._isize_max = 6

        self.cpt_handler = base.CPTHandler()

    def bind_state(self, state):
        base.Element.bind_state(self, state)
        for var in ['visible', 'size']:
            self.register_state_listener3(self.update, state, var)

        for var in [
                'depth_min', 'depth_max', 'time_masking_shape',
                'time_masking_mode', 'time_masking_opacity']:

            self.register_state_listener3(self.update_alpha, state, var)

        self.cpt_handler.bind_state(state.cpt, self.update)

        for var in ['symbol', 'size_parameter', 'color_parameter']:
            self.register_state_listener3(self.update_sizes, state, var)

    def unbind_state(self):
        self.cpt_handler.unbind_state()
        self._listeners = []
        self._state = None

    def get_name(self):
        return 'Table'

    def set_parent(self, parent):
        self._parent = parent
        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=True,
            remove=self.remove)

        for var in ['tmin', 'tmax', 'tduration', 'tposition']:
            self.register_state_listener3(
                self.update_alpha, self._parent.state, var)

        self._parent.register_data_provider(self)

        self.update()

    def iter_data(self, name):
        if self._table and self._table.has_col(name):
            yield self._table.get_col(name)

    def set_table(self, table):
        self._table = table

        self._istate += 1
        self._update_controls()

    def get_size_parameter_extra_entries(self):
        return []

    def get_color_parameter_extra_entries(self):
        return []

    def update_sizes(self, *args):
        self._istate += 1
        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            self._parent.unregister_data_provider(self)

            self._clear_pipes()

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def _clear_pipes(self):
        if self._pipes is not None:
            for p in self._pipes:
                self._parent.remove_actor(p.actor)

            self._pipes = None

    def _init_pipes_scatter(self):
        state = self._state
        points = self._table.get_col('xyz')
        self._pipes = []
        self._pipe_maps = []
        if state.size_parameter:
            sizes = self._table.get_col(state.size_parameter)
            isizes = inormalize(
                sizes, self._isize_min, self._isize_max)

            for i in range(self._isize_min, self._isize_max+1):
                b = isizes == i
                p = ScatterPipe(points[b].copy())
                self._pipes.append(p)
                self._pipe_maps.append(b)
        else:
            self._pipes.append(
                ScatterPipe(points))
            self._pipe_maps.append(
                num.ones(points.shape[0], dtype=num.bool))

    def _init_pipes_beachball(self):
        state = self._state
        self._pipes = []

        tab = self._table

        positions = tab.get_col('xyz')

        if tab.has_col('m6'):
            m6s = tab.get_col('m6')
        else:
            m6s = num.zeros((tab.get_nrows(), 6))
            m6s[:, 3] = 1.0

        if state.size_parameter:
            sizes = tab.get_col(state.size_parameter)
        else:
            sizes = num.ones(tab.get_nrows())

        if state.color_parameter:
            values = self._table.get_col(state.color_parameter)
        else:
            values = num.zeros(tab.get_nrows())

        rsizes = inormalize(
            sizes, self._isize_min, self._isize_max, discrete=False) * 0.005

        pipe = BeachballPipe(positions, m6s, rsizes, values, self._parent.ren)
        self._pipes = [pipe]

    def _update_pipes_scatter(self):
        state = self._state
        for i, p in enumerate(self._pipes):
            self._parent.add_actor(p.actor)
            p.set_size(state.size * (self._isize_min + i)**1.3)

        if state.color_parameter:
            values = self._table.get_col(state.color_parameter)

            if num.issubdtype(values.dtype, num.string_):
                values = string_to_sorted_idx(values)

            self.cpt_handler._values = values
            self.cpt_handler.update_cpt()

            cpt = copy.deepcopy(
                self.cpt_handler._cpts[self._state.cpt.cpt_name])
            colors2 = cpt(values)
            colors2 = colors2 / 255.

            for m, p in zip(self._pipe_maps, self._pipes):
                p.set_colors(colors2[m, :])

        for p in self._pipes:
            p.set_symbol(state.symbol)

    def _update_pipes_beachball(self):
        state = self._state

        p = self._pipes[0]

        self._parent.add_actor(p.actor)
        p.set_size_factor(state.size * 0.005)

    def update(self, *args):
        state = self._state
        if self._pipes is not None and self._istate != self._istate_view:
            self._clear_pipes()

        if not state.visible:
            if self._pipes is not None:
                for p in self._pipes:
                    self._parent.remove_actor(p.actor)

        else:
            if self._istate != self._istate_view and self._table:
                if state.symbol == 'beachball':
                    self._init_pipes_beachball()
                else:
                    self._init_pipes_scatter()

                self._istate_view = self._istate

            if self._pipes is not None:
                if state.symbol == 'beachball':
                    self._update_pipes_beachball()
                else:
                    self._update_pipes_scatter()

        self.update_alpha()  # TODO: only if needed?
        self._parent.update_view()

    def update_alpha(self, *args, mask=None):
        if self._state.symbol == 'beachball':
            return

        if self._pipes is None:
            return

        time = self._table.get_col('time')
        depth = self._table.get_col('depth')

        depth_mask = num.ones(time.size, dtype=bool)

        if self._state.depth_min is not None:
            depth_mask &= depth >= self._state.depth_min
        if self._state.depth_max is not None:
            depth_mask &= depth <= self._state.depth_max

        tmin = self._parent.state.tmin_effective
        tmax = self._parent.state.tmax_effective

        if tmin is not None:
            m1 = time < tmin
        else:
            m1 = num.zeros(time.size, dtype=bool)

        if tmax is not None:
            m3 = tmax < time
        else:
            m3 = num.zeros(time.size, dtype=bool)

        m2 = num.logical_not(num.logical_or(m1, m3))

        value_low = self._state.time_masking_opacity

        f1, f2, f3 = MaskingModeChoice.get_factors(
            self._state.time_masking_mode, value_low)

        amp = num.ones(time.size, dtype=num.float)
        amp[m1] = f1
        amp[m3] = f3
        if None in (tmin, tmax):
            amp[m2] = 1.0
        else:
            if self._state.time_masking_shape == 'rect':
                amp[m2] == 1.0
            elif self._state.time_masking_shape == 'linear':
                amp[m2] = time[m2]
                amp[m2] -= tmin
                amp[m2] /= (tmax - tmin)
            elif self._state.time_masking_shape == 'quadratic':
                amp[m2] = time[m2]
                amp[m2] -= tmin
                amp[m2] /= (tmax - tmin)
                amp[m2] **= 2

            if f1 != 0.0:
                amp[m2] *= (1.0 - value_low)
                amp[m2] += value_low

        amp *= depth_mask

        for m, p in zip(self._pipe_maps, self._pipes):
            p.set_alpha(amp[m])

        self._parent.update_view()

    def _get_table_widgets_start(self):
        return 0

    def _get_controls(self):
        if self._controls is None:
            from ..state import state_bind_checkbox, state_bind_slider, \
                state_bind_combobox, state_bind_spinbox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            iy = self._get_table_widgets_start()

            layout.addWidget(qw.QLabel('Size'), iy, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(100)
            layout.addWidget(slider, iy, 1)
            state_bind_slider(self, self._state, 'size', slider, factor=0.1)

            iy += 1

            layout.addWidget(qw.QLabel('Size Scaling'), iy, 0)

            cb = qw.QComboBox()

            layout.addWidget(cb, iy, 1)
            state_bind_combobox(
                self, self._state, 'size_parameter', cb)

            self._size_combobox = cb

            iy += 1

            layout.addWidget(qw.QLabel('Color'), iy, 0)

            cb = qw.QComboBox()

            layout.addWidget(cb, iy, 1)
            state_bind_combobox(
                self, self._state, 'color_parameter', cb)

            self._color_combobox = cb

            self.cpt_handler.cpt_controls(
                self._parent, self._state.cpt, layout)

            iy = layout.rowCount() + 1

            layout.addWidget(qw.QLabel('Symbol'), iy, 0)

            cb = common.string_choices_to_combobox(SymbolChoice)

            layout.addWidget(cb, iy, 1)
            state_bind_combobox(
                self, self._state, 'symbol', cb)

            iy += 1

            layout.addWidget(qw.QLabel('Depth Min'), iy, 0)
            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            layout.addWidget(slider, iy, 1)
            state_bind_slider(
                self, self._state, 'depth_min', slider)
            self._depth_min_slider = slider

            spinbox = qw.QDoubleSpinBox()
            spinbox.setDecimals(1)
            spinbox.setSuffix(' km')
            spinbox.setSingleStep(1)
            layout.addWidget(spinbox, iy, 2)
            state_bind_spinbox(
                self, self._state, 'depth_min', spinbox, factor=km)
            self._depth_min_spinbox = spinbox

            iy += 1

            layout.addWidget(qw.QLabel('Depth Max'), iy, 0)
            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            layout.addWidget(slider, iy, 1)
            state_bind_slider(
                self, self._state, 'depth_max', slider)
            self._depth_max_slider = slider

            spinbox = qw.QDoubleSpinBox()
            spinbox.setDecimals(1)
            spinbox.setSuffix(' km')
            spinbox.setSingleStep(1)
            layout.addWidget(spinbox, iy, 2)
            state_bind_spinbox(
                self, self._state, 'depth_max', spinbox, factor=km)
            self._depth_max_spinbox = spinbox

            def sync_depth_min(value):
                state = self._state
                if state.depth_min > value:
                    state.depth_min = value

            def sync_depth_max(value):
                state = self._state
                if state.depth_max < value:
                    state.depth_max = value

            self._depth_max_slider.valueChanged.connect(sync_depth_min)
            self._depth_max_spinbox.valueChanged.connect(sync_depth_min)

            self._depth_min_slider.valueChanged.connect(sync_depth_max)
            self._depth_min_spinbox.valueChanged.connect(sync_depth_max)

            iy += 1

            layout.addWidget(qw.QLabel('Time Masking Opacity'), iy, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(100)
            layout.addWidget(slider, iy, 1)
            state_bind_slider(
                self, self._state, 'time_masking_opacity', slider, factor=0.01)

            iy += 1

            layout.addWidget(qw.QLabel('Time Masking Shape'), iy, 0)
            cb = common.string_choices_to_combobox(MaskingShapeChoice)
            layout.addWidget(cb, iy, 1)
            state_bind_combobox(self, self._state, 'time_masking_shape', cb)

            iy += 1

            layout.addWidget(qw.QLabel('Time Masking Mode'), iy, 0)
            cb = common.string_choices_to_combobox(MaskingModeChoice)
            layout.addWidget(cb, iy, 1)
            state_bind_combobox(self, self._state, 'time_masking_mode', cb)

            iy += 1

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, iy, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            iy += 1

            layout.addWidget(qw.QFrame(), iy, 0, 1, 3)

            self._controls = frame

            self._update_controls()

        return self._controls

    def _update_controls(self):
        for (cb, get_extra_entries) in [
                (self._color_combobox, self.get_color_parameter_extra_entries),
                (self._size_combobox, self.get_size_parameter_extra_entries)]:

            if cb is not None:
                cb.clear()

                have = set()
                for s in get_extra_entries():
                    if s not in have:
                        cb.insertItem(len(have), s)
                        have.add(s)

                if self._table is not None:
                    for s in self._table.get_col_names():
                        h = self._table.get_header(s)
                        if h.get_ncols() == 1 and s not in have:
                            cb.insertItem(len(have), s)
                            have.add(s)

        self.cpt_handler._update_cpt_combobox()
        self.cpt_handler._update_cptscale_lineedit()

        if self._table is not None and self._table.has_col('depth'):
            depth = self._table.get_col('depth')

            depth_min = depth.min()
            depth_max = depth.max()

            for wdg in (self._depth_min_slider, self._depth_max_slider,
                        self._depth_min_spinbox, self._depth_max_spinbox):
                wdg.setMinimum(int(depth_min))
                wdg.setMaximum(int(depth_max))

            for wdg in (self._depth_min_slider, self._depth_min_spinbox):
                wdg.setValue(int(depth_min / km))

            for wdg in (self._depth_max_slider, self._depth_max_spinbox):
                wdg.setValue(int(depth_max / km))


__all__ = [
    'TableElement',
    'TableState',
]
