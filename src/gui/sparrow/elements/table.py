# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import copy

import numpy as num

from pyrocko.guts import Bool, Float, String, StringChoice
from pyrocko.gui.vtk_util import ScatterPipe
from pyrocko.gui.qt_compat import qw, qc
from pyrocko import automap

from .base import Element, ElementState
from .. import common

guts_prefix = 'sparrow'


def inormalize(x, imin, imax):

    xmin = num.min(x)
    xmax = num.max(x)
    if xmin == xmax:
        xmin -= 0.5
        xmax += 0.5

    rmin = imin - 0.5
    rmax = imax + 0.5

    return num.clip(
        num.round(
            rmin + (x - xmin) * ((rmax-rmin) / (xmax - xmin))).astype(num.int),
        imin, imax)


class SymbolChoice(StringChoice):
    choices = ['point', 'sphere']


class TableState(ElementState):
    visible = Bool.T(default=True)
    size = Float.T(default=5.0)
    color_parameter = String.T(optional=True)
    size_parameter = String.T(optional=True)
    depth_offset = Float.T(default=0.0)
    symbol = SymbolChoice.T(default='point')


class TableElement(Element):
    def __init__(self):
        Element.__init__(self)
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

        cpt_data = [
            (0.0, 0.8, 0.8, 0.2),
            (0.1, 0.9, 0.2, 0.2),
            (0.3, 0.3, 0.3, 0.9),
            (0.7, 0.5, 0.5, 0.9),
            (1.0, 0.2, 0.9, 0.2)]

        self.cpt = automap.CPT(
            levels=[
                automap.CPTLevel(
                    vmin=a[0],
                    vmax=b[0],
                    color_min=[255*x for x in a[1:]],
                    color_max=[255*x for x in b[1:]])
                for (a, b) in zip(cpt_data[:-1], cpt_data[1:])])

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'symbol')
        state.add_listener(upd, 'size')
        state.add_listener(upd, 'depth_offset')
        state.add_listener(upd, 'color_parameter')

        upd_s = self.update_sizes
        self._listeners.append(upd_s)
        state.add_listener(upd_s, 'size_parameter')

        self._state = state

    def unbind_state(self):
        self._listeners = []
        self._state = None

    def get_name(self):
        return 'Table'

    def set_parent(self, parent):
        self._parent = parent
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)

        update_alpha = self.update_alpha
        self._listeners.append(update_alpha)
        self._parent.state.add_listener(update_alpha, 'tmin')
        self._parent.state.add_listener(update_alpha, 'tmax')

        self.update()

    def set_table(self, table):
        self._table = table
        self._istate += 1
        self._update_controls()

    def update_sizes(self, *args):
        self._istate += 1
        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
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

                self._istate_view = self._istate

            if self._pipes is not None:
                for i, p in enumerate(self._pipes):
                    self._parent.add_actor(p.actor)
                    p.set_size(state.size * (self._isize_min + i)**1.3)

                if state.color_parameter:
                    cpt = copy.deepcopy(self.cpt)
                    values = self._table.get_col(state.color_parameter)
                    cpt.scale(num.min(values), num.max(values))
                    colors2 = cpt(values)
                    colors2 = colors2 / 255.

                    for m, p in zip(self._pipe_maps, self._pipes):
                        p.set_colors(colors2[m, :])

                for p in self._pipes:
                    p.set_symbol(state.symbol)

        self.update_alpha()  # TODO: only if needed?
        self._parent.update_view()

    def update_alpha(self, *args):
        if self._pipes is not None:

            time = self._table.get_col('time')
            mask = num.ones(time.size, dtype=num.bool)
            if self._parent.state.tmin is not None:
                mask &= self._parent.state.tmin <= time
            if self._parent.state.tmax is not None:
                mask &= time <= self._parent.state.tmax

            print(mask.shape)
            for m, p in zip(self._pipe_maps, self._pipes):
                p.set_alpha(mask[m])

            self._parent.update_view()

    def _get_table_widgets_start(self):
        return 0

    def _get_controls(self):
        if self._controls is None:
            from ..state import state_bind_checkbox, state_bind_slider, \
                state_bind_combobox

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

            layout.addWidget(qw.QLabel('Size'), iy, 0)

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

            iy += 1

            layout.addWidget(qw.QLabel('Symbol'), iy, 0)

            cb = common.string_choices_to_combobox(SymbolChoice)

            layout.addWidget(cb, iy, 1)
            state_bind_combobox(
                self, self._state, 'symbol', cb)

            iy += 1

            layout.addWidget(qw.QLabel('Depth Offset'), iy, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(100)
            layout.addWidget(slider, iy, 1)
            state_bind_slider(
                self, self._state, 'depth_offset', slider, factor=1000.)

            iy += 1

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, iy, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, iy, 1)
            pb.clicked.connect(self.remove)

            iy += 1

            layout.addWidget(qw.QFrame(), iy, 0, 1, 3)

            self._controls = frame

            self._update_controls()

        return self._controls

    def _update_controls(self):
        for cb in (self._color_combobox, self._size_combobox):
            if cb is not None:
                cb.clear()

                if self._table is not None:
                    for i, s in enumerate(self._table.get_col_names()):
                        h = self._table.get_header(s)
                        if h.get_ncols() == 1:
                            cb.insertItem(i, s)


__all__ = [
    'TableElement',
    'TableState',
]
