# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from matplotlib.patches import Wedge

from pyrocko.guts import Tuple, Float
from pyrocko.plot.smartplot import Plot
from pyrocko.gui import util as gui_util
from pyrocko.gui import talkie
from pyrocko import gato

from pyrocko.gato.grid.location import distances_3d

guts_prefix = 'gato'


km = 1000.


class ArrayResponseFunctionPlotState(talkie.TalkieRoot):
    target_slowness = Tuple.T(
        3, Float.T(), default=(0., 0., 0.),
        help='Target slowness in north-east-down [s/m],')


class ArrayResponseFunctionPlot(Plot, talkie.TalkieConnectionOwner):

    def __init__(self, state=None, **kwargs):
        self._info = None
        self._array = None
        self._items = []
        self._units_factor = 1.0
        self._units = 'm'
        if state is None:
            state = ArrayResponseFunctionPlotState()

        self.state = state

        Plot.__init__(
            self,
            ['slowness_east'],
            ['slowness_north'],
            **kwargs)
        talkie.TalkieConnectionOwner.__init__(self)

        self.set_aspect('slowness_north', 'slowness_east')
        self.set_units(1/km, 's/km')
        self.slowness_max = 0.001
        self.set_lim(
            'slowness_east',
            -self.slowness_max / self._units_factor,
            self.slowness_max / self._units_factor)
        self.set_lim(
            'slowness_north',
            -self.slowness_max / self._units_factor,
            self.slowness_max / self._units_factor)

        self._connect(
            self.fig.canvas, 'motion_notify_event', self.on_mouse_move)

        self._connect(
            self.fig.canvas, 'button_press_event', self.on_mouse_down)

        self.talkie_connect(self.state, 'target_slowness', self.update)

    def on_mouse_move(self, event):
        x, y = event.xdata, event.ydata
        if None not in (x, y):
            win = gui_util.get_app().get_main_window()
            slowness = num.array((
                y * self._units_factor,
                x * self._units_factor,
                0.0), dtype=float)

            win.status('Azimuth: %.0f°, Slowness: %.3g s/km' % (
                num.rad2deg(num.arctan2(slowness[1], slowness[0])),
                num.sqrt(num.sum(slowness**2))*km))

    def on_mouse_down(self, event):
        x, y = event.xdata, event.ydata
        if event.dblclick and None not in (x, y):
            self.state.target_slowness = (
                y * self._units_factor,
                x * self._units_factor,
                0.0)

    def set_units(self, factor, label):
        self._units_factor = factor
        self._units = label
        self.update_labels()

    def update_labels(self):
        self.set_label('slowness_east', 'Slowness East [%s]' % self._units)
        self.set_label('slowness_north', 'Slowness North [%s]' % self._units)

    def set_array(self, array, info):
        self._array = array
        self._info = info
        self.update()

    def update_layout_hook(self):
        self.draw()

    def update(self, *args):
        self.draw()
        self.fig.canvas.draw()

    def draw(self, resolution='low'):
        if not gui_util.get_app().slow_operations_enabled():
            resolution = 'low'

        while self._items:
            self._items.pop().remove()

        info = self._info
        array = self._array

        if info is None or len(info.sensors) < 2:
            return

        axes = self(0, 0)

        grid = gato.UnstructuredLocationGrid.from_locations(
            info.sensors, ignore_position_duplicates=True)
        points = grid.get_nodes('ned')

        distance_max = num.max(distances_3d(grid, grid))
        auto_frequency = 0.1 * 100*km / distance_max

        sy_min, sy_max = (s*self._units_factor for s in axes.get_xbound())
        sx_min, sx_max = (s*self._units_factor for s in axes.get_ybound())

        s_max = max(sx_max - sx_min, sy_max - sy_min)
        if resolution == 'low':
            s_delta = s_max / 200
        else:
            s_delta = s_max / 1000

        slowness_grid = gato.CartesianSlownessGrid(
            sx_min=sx_min,
            sx_max=sx_max,
            sx_delta=s_delta,
            sy_min=sy_min,
            sy_max=sy_max,
            sy_delta=s_delta)

        slowness = slowness_grid.get_nodes('xyz')

        arf = num.zeros(slowness_grid.size, dtype=complex)
        frequencies = num.array([auto_frequency])
        # frequencies = num.array(num.linspace(
        #    auto_frequency/2., auto_frequency*2., 10))

        axes.set_title('Array Response Function for %s at %.3g Hz' % (
            array.name, auto_frequency), pad=20)

        target_slowness = self.state.target_slowness

        for f in frequencies:
            for point in points:
                arf += num.exp(-2j*num.pi*f*(
                    (slowness[:, 0] - target_slowness[0])*point[0] +
                    (slowness[:, 1] - target_slowness[1])*point[1]))

        arf /= grid.size * frequencies.size
        abs_arf = num.abs(arf).reshape(slowness_grid.shape)[0, :, :].T

        sx, sy, _ = slowness_grid.get_coords('xyz')

        self._items.append(
            axes.imshow(
                abs_arf, extent=(
                    sy[0] / self._units_factor,
                    sy[-1] / self._units_factor,
                    sx[-1] / self._units_factor,
                    sx[0] / self._units_factor)))

        patch = Wedge(
            (0.0, 0.0),
            self.slowness_max*5. / self._units_factor,
            0.,
            360.,
            width=self.slowness_max*(5.-1.) / self._units_factor,
            ec='none',
            color=(1.0, 1.0, 1.0, 0.2))

        self._items.append(axes.add_patch(patch))
        if resolution == 'low':
            gui_util.call_later(self.redraw_high_res, 200)

    def redraw_high_res(self):
        self.draw(resolution='high')
        self.fig.canvas.draw()


__all__ = [
    'ArrayResponseFunctionPlotState',
    'ArrayResponseFunctionPlot',
]
