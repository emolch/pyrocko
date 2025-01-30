# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from pyrocko.guts import StringChoice, clone
from pyrocko.model.location import Location
from pyrocko.plot.smartplot import Plot
from pyrocko import plot, util
from pyrocko.gui import util as gui_util, talkie
from pyrocko import gato

guts_prefix = 'gato'


km = 1000.


def time_or_none_to_date_str(t):
    if t is None:
        return '...'
    else:
        return util.time_to_str(t, format='%Y-%m-%d')


def get_normal_ecef(origin, ned):
    point = clone(origin)
    point.north_shift += ned[0]
    point.east_shift += ned[1]
    point.depth += ned[2]
    normal = point.ecef() - origin.ecef()
    normal /= num.sqrt(num.sum(normal**2))
    return normal


class ProjectionChoice(StringChoice):
    choices = [
        'top',
        'south',
        'east']


class GeometryPlotState(talkie.TalkieRoot):
    projection = ProjectionChoice.T(
        default='top',
        help="View from direction.")


class GeometryPlot(Plot, talkie.TalkieConnectionOwner):

    def __init__(self, state=None, *args, **kwargs):
        self._info = None
        self._array = None
        self._items = []
        self._items_highlight = []
        self._units_factor = 1.0
        self._units = 'm'
        if state is None:
            state = GeometryPlotState()

        self.state = state

        Plot.__init__(
            self,
            ['x'],
            ['y'],
            *args,
            **kwargs)

        talkie.TalkieConnectionOwner.__init__(self)

        self.set_aspect('y', 'x')
        self.set_units(km, 'km')
        self._connect(
            self.fig.canvas, 'motion_notify_event', self.on_mouse_move)

        self.talkie_connect(self.state, 'projection', self.update_projection)

    def have_sensors(self):
        return self._info and self._info.sensors

    def plot_coords_to_ned(self, x, y):
        x *= self._units_factor
        y *= self._units_factor
        return {
            'top': (y, x, 0),
            'south': (0, x, y),
            'east': (x, 0, y)}[self.state.projection]

    def on_mouse_move(self, event):
        x, y = event.xdata, event.ydata
        if self.have_sensors() and None not in (x, y):
            north, east, depth = self.plot_coords_to_ned(x, y)
            origin = self._grid_no_dups.get_effective_origin()
            location = Location(
                lat=origin.effective_lat,
                lon=origin.effective_lon,
                elevation=origin.elevation,
                north_shift=north,
                east_shift=east,
                depth=origin.depth + depth)

            self.highlight_closest_sensor(location)
        else:
            self.highlight_closest_sensor(None)

        self.fig.canvas.draw()

    def set_units(self, factor, label):
        self._units_factor = factor
        self._units = label
        self.update_labels()

    def update_projection(self, *args):
        self.update_labels()
        self.update()

    def update_labels(self):
        label_x, label_y = {
            'top': ('Easting', 'Northing'),
            'south': ('Easting', 'Depth'),
            'east': ('Northing', 'Depth')}[self.state.projection]

        self.set_label('x', '%s [%s]' % (label_x, self._units))
        self.set_label('y', '%s [%s]' % (label_y, self._units))

    def set_array(self, array, info):
        self._array = array
        self._info = info
        self._grid_no_dups = None
        self._grid = None
        self._grid_origin = None

        if self.have_sensors():
            self._grid_no_dups = gato.UnstructuredLocationGrid.from_locations(
                info.sensors, ignore_position_duplicates=True)
            self._grid_no_dups.set_origin_to_center()

            self._grid = gato.UnstructuredLocationGrid.from_locations(
                info.sensors)

            self._grid.origin = self._grid_no_dups.get_effective_origin()

        self.update()

    def update(self, *args):
        self.draw()
        self.fig.canvas.draw()

    def get_closest_sensors(self, location):
        if not self.have_sensors():
            return [], num.zeros((0, 3))

        lgrid = gato.UnstructuredLocationGrid.from_locations([location])

        normal_ned = {
            'top': (0, 0, 1),
            'south': (1, 0, 0),
            'east': (0, 1, 0)}[self.state.projection]

        normal_ecef = get_normal_ecef(lgrid.get_effective_origin(), normal_ned)
        distances = gato.distances_projected(
            normal_ecef, self._grid, lgrid)[:, 0]

        coords_ned = self._grid.get_nodes('ned')
        order = num.argsort(distances)
        sensors = []
        i = 0
        while i < order.size \
                and num.all(
                    coords_ned[order[0], :] == coords_ned[order[i], :]):
            sensors.append(self._info.sensors[order[i]])
            i += 1

        return sensors, coords_ned[order[:len(sensors)], :]

    def highlight_closest_sensor(self, location):

        axes = self(0, 0)
        while self._items_highlight:
            self._items_highlight.pop().remove()

        win = gui_util.get_app().get_main_window()

        if location is None:
            win.status('')
            return

        if not self.have_sensors:
            return

        sensors, coords_ned = self.get_closest_sensors(location)

        ix, iy = {
            'top': (1, 0),
            'south': (1, 2),
            'east': (0, 2)}[self.state.projection]

        pos = (
            coords_ned[0, ix] / self._units_factor,
            coords_ned[0, iy] / self._units_factor)

        self._items_highlight.extend(
            axes.plot(
                *pos,
                'o',
                color=plot.mpl_color('scarletred1'),
                mec=plot.mpl_color('scarletred3'),
                ms=10))

        codes_list = sorted(set(sensor.codes for sensor in sensors))
        nsl_list = sorted(set(sensor.codes.nsl for sensor in sensors))
        c_list = sorted(set(
            channel.codes.channel
            for sensor in sensors for channel in sensor.channels))
        lat_lon_list = sorted(set(
            sensor.effective_latlon for sensor in sensors))
        elevation_list = sorted(set(
            sensor.elevation for sensor in sensors))
        depth_list = sorted(set(
            sensor.depth for sensor in sensors))

        spans_list = sorted(set('%s - %s' % (
            time_or_none_to_date_str(sensor.tmin),
            time_or_none_to_date_str(sensor.tmax))
            for sensor in sensors))

        label = ', '.join('.'.join(nsl) for nsl in nsl_list)
        self._items_highlight.append(
            axes.annotate(
                label,
                xy=pos,
                xytext=(10, 10),
                textcoords='offset points'))

        message = 'Sensors: %s, Location: %s, Elevation: %s, Depth: %s, ' \
            'Channels: %s, Epochs: %s' % (
                ', '.join(str(codes) for codes in codes_list),
                ', '.join('%g°/%g°' % lat_lon for lat_lon in lat_lon_list),
                ', '.join('%g m' % elevation for elevation in elevation_list),
                ', '.join('%g m' % depth for depth in depth_list),
                ', '.join(c_list),
                ', '.join(spans_list))

        win.status(message)

    def draw(self):
        while self._items:
            self._items.pop().remove()

        array = self._array

        if not self.have_sensors():
            return

        axes = self(0, 0)
        title = array.name + (' (%s)' % array.comment if array.comment else '')
        axes.set_title(title, pad=20)

        coords_ned = self._grid_no_dups.get_nodes('ned')

        ix, iy, invertx, inverty = {
            'top': (1, 0, False, False),
            'south': (1, 2, False, True),
            'east': (0, 2, False, True)}[self.state.projection]

        vmin = num.min(coords_ned, axis=0)
        vmax = num.max(coords_ned, axis=0)
        mask_eq = vmin == vmax
        vmin[mask_eq] -= 1.0
        vmax[mask_eq] += 1.0

        scale_factor = 1.2
        self.set_lim(
            'x',
            scale_factor * vmin[ix] / self._units_factor,
            scale_factor * vmax[ix] / self._units_factor)
        self.set_lim(
            'y',
            scale_factor * vmin[iy] / self._units_factor,
            scale_factor * vmax[iy] / self._units_factor)

        self.set_x_invert(0, invertx)
        self.set_y_invert(0, inverty)

        self.need_update_layout()

        self._items.extend(
            axes.plot(
                coords_ned[:, ix] / self._units_factor,
                coords_ned[:, iy] / self._units_factor,
                'o',
                color='black'))


__all__ = [
    'ProjectionChoice',
    'GeometryPlotState',
    'GeometryPlot',
]
