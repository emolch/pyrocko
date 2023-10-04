# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Matplotlib plotting with some fancy extras.
'''

from collections import defaultdict
import math
import logging

import numpy as num
import matplotlib
from matplotlib.axes import Axes
# from matplotlib.ticker import MultipleLocator
from matplotlib import cm, colors, colorbar, figure

from pyrocko.guts import Tuple, Float, Object
from pyrocko import plot

import scipy.optimize

logger = logging.getLogger('pyrocko.plot.smartplot')

guts_prefix = 'pf'

inch = 2.54


def get_callbacks(obj):
    try:
        return obj.callbacks
    except AttributeError:
        return obj._callbacks


class SmartplotAxes(Axes):

    if matplotlib.__version__.split('.') < '3.6'.split('.'):
        # Subclassing cla is deprecated on newer mpl but need this fallback for
        # older versions. Code is duplicated because mpl behaviour depends
        # on the existence of cla in the subclass...
        def cla(self):
            if hasattr(self, 'callbacks'):
                callbacks = self.callbacks
                Axes.cla(self)
                self.callbacks = callbacks
            else:
                Axes.cla(self)

    else:
        def clear(self):
            if hasattr(self, 'callbacks'):
                callbacks = self.callbacks
                Axes.clear(self)
                self.callbacks = callbacks
            elif hasattr(self, '_callbacks'):
                callbacks = self._callbacks
                Axes.clear(self)
                self._callbacks = callbacks
            else:
                Axes.clear(self)


class SmartplotFigure(figure.Figure):

    def set_smartplot(self, plot):
        self._smartplot = plot

    def draw(self, *args, **kwargs):
        if hasattr(self, '_smartplot'):
            try:
                self._smartplot._update_layout()
            except NotEnoughSpace:
                logger.error('Figure is too small to show the plot.')
                return

        return figure.Figure.draw(self, *args, **kwargs)


def limits(points):
    lims = num.zeros((3, 2))
    if points.size != 0:
        lims[:, 0] = num.min(points, axis=0)
        lims[:, 1] = num.max(points, axis=0)

    return lims


def wcenter(rect):
    return rect[0] + rect[2]*0.5


def hcenter(rect):
    return rect[1] + rect[3]*0.5


def window_min(n, w, ml, mu, s, x):
    return ml + x/float(n) * (w - (ml + mu + (n-1)*s)) + math.floor(x) * s


def window_max(n, w, ml, mu, s, x):
    return ml + x/float(n) * (w - (ml + mu + (n-1)*s)) + (math.floor(x)-1) * s


def make_smap(cmap, norm=None):
    if isinstance(norm, tuple):
        norm = colors.Normalize(*norm, clip=False)
    smap = cm.ScalarMappable(cmap=cmap, norm=norm)
    smap._A = []  # not needed in newer versions of mpl?
    return smap


def solve_layout_fixed_panels(size, shape, limits, aspects, fracs=None):

    weight_aspect = 1000.

    sx, sy = size
    nx, ny = shape
    nvar = nx+ny
    vxs, vys = limits
    uxs = vxs[:, 1] - vxs[:, 0]
    uys = vys[:, 1] - vys[:, 0]
    aspects_xx, aspects_yy, aspects_xy = aspects

    if fracs is None:
        wxs = num.full(nx, sx / nx)
        wys = num.full(ny, sy / ny)
    else:
        frac_x, frac_y = fracs
        wxs = sx * frac_x / num.sum(frac_x)
        wys = sy * frac_y / num.sum(frac_y)

    data = []
    weights = []
    rows = []
    bounds = []
    for ix in range(nx):
        u = uxs[ix]
        assert u > 0.0
        row = num.zeros(nvar)
        row[ix] = u
        rows.append(row)
        data.append(wxs[ix])
        weights.append(1.0 / u)
        bounds.append((0, wxs[ix] / u))

    for iy in range(ny):
        u = uys[iy]
        assert u > 0.0
        row = num.zeros(nvar)
        row[nx+iy] = u
        rows.append(row)
        data.append(wys[iy])
        weights.append(1.0)
        bounds.append((0, wys[iy] / u))

    for ix1, ix2, aspect in aspects_xx:
        row = num.zeros(nvar)
        row[ix1] = aspect
        row[ix2] = -1.0
        weights.append(weight_aspect/aspect)
        rows.append(row)
        data.append(0.0)

    for iy1, iy2, aspect in aspects_yy:
        row = num.zeros(nvar)
        row[nx+iy1] = aspect
        row[nx+iy2] = -1.0
        weights.append(weight_aspect/aspect)
        rows.append(row)
        data.append(0.0)

    for ix, iy, aspect in aspects_xy:
        row = num.zeros(nvar)
        row[ix] = aspect
        row[nx+iy] = -1.0
        weights.append(weight_aspect/aspect)
        rows.append(row)
        data.append(0.0)

    weights = num.array(weights)
    data = num.array(data)
    mat = num.vstack(rows) * weights[:, num.newaxis]
    data *= weights

    bounds = num.array(bounds).T

    model = scipy.optimize.lsq_linear(mat, data, bounds).x

    cxs = model[:nx]
    cys = model[nx:nx+ny]

    vlimits_x = num.zeros((nx, 2))
    for ix in range(nx):
        u = wxs[ix] / cxs[ix]
        vmin, vmax = vxs[ix]
        udata = vmax - vmin
        eps = 1e-7 * u
        assert udata <= u + eps
        vlimits_x[ix, 0] = (vmin + vmax) / 2.0 - u / 2.0
        vlimits_x[ix, 1] = (vmin + vmax) / 2.0 + u / 2.0

    vlimits_y = num.zeros((ny, 2))
    for iy in range(ny):
        u = wys[iy] / cys[iy]
        vmin, vmax = vys[iy]
        udata = vmax - vmin
        eps = 1e-7 * u
        assert udata <= u + eps
        vlimits_y[iy, 0] = (vmin + vmax) / 2.0 - u / 2.0
        vlimits_y[iy, 1] = (vmin + vmax) / 2.0 + u / 2.0

    def check_aspect(a, awant, eps=1e-2):
        if abs(1.0 - (a/awant)) > eps:
            logger.error(
                'Unable to comply with requested aspect ratio '
                '(wanted: %g, achieved: %g)' % (awant, a))

    for ix1, ix2, aspect in aspects_xx:
        check_aspect(cxs[ix2] / cxs[ix1], aspect)

    for iy1, iy2, aspect in aspects_yy:
        check_aspect(cys[iy2] / cys[iy1], aspect)

    for ix, iy, aspect in aspects_xy:
        check_aspect(cys[iy] / cxs[ix], aspect)

    return (vlimits_x, vlimits_y), (wxs, wys)


def solve_layout_iterative(size, shape, limits, aspects, niterations=3):

    sx, sy = size
    nx, ny = shape
    vxs, vys = limits
    uxs = vxs[:, 1] - vxs[:, 0]
    uys = vys[:, 1] - vys[:, 0]
    aspects_xx, aspects_yy, aspects_xy = aspects

    fracs_x, fracs_y = num.ones(nx), num.ones(ny)
    for i in range(niterations):
        (vlimits_x, vlimits_y), (wxs, wys) = solve_layout_fixed_panels(
            size, shape, limits, aspects, (fracs_x, fracs_y))

        uxs_view = vlimits_x[:, 1] - vlimits_x[:, 0]
        uys_view = vlimits_y[:, 1] - vlimits_y[:, 0]
        wxs_used = wxs * uxs / uxs_view
        wys_used = wys * uys / uys_view
        # wxs_wasted = wxs * (1.0 - uxs / uxs_view)
        # wys_wasted = wys * (1.0 - uys / uys_view)

        fracs_x = wxs_used
        fracs_y = wys_used

    return (vlimits_x, vlimits_y), (wxs, wys)


class PlotError(Exception):
    pass


class NotEnoughSpace(PlotError):
    pass


class PlotConfig(Object):
    '''
    Configuration for :py:class:`Plot`.
    '''

    font_size = Float.T(default=9.0)

    size_cm = Tuple.T(
        2, Float.T(), default=(20., 20.))

    margins_em = Tuple.T(
        4, Float.T(), default=(8., 6., 8., 6.))

    separator_em = Float.T(default=1.5)

    colorbar_width_em = Float.T(default=2.0)

    label_offset_em = Tuple.T(
        2, Float.T(), default=(2., 2.))

    tick_label_offset_em = Tuple.T(
        2, Float.T(), default=(0.5, 0.5))

    @property
    def size_inch(self):
        return self.size_cm[0]/inch, self.size_cm[1]/inch


class Plot(object):
    '''
    Matplotlib plotting with some fancy extras.

    - Absolute sized figure margins, also for interactive plots.
    - Improved label placement for grids of axes.
    - Improved shared axis'es across multiple axes, e.g. for cross section
      plots.
    - Fixed aspect plotting across multiple axis'es on separate axes.
    - Automatic subplot sizing based on aspect and data limit constraints.
    - Serializable plot configuration.
    '''

    def __init__(
            self, x_dims=['x'], y_dims=['y'], z_dims=[], config=None,
            fig=None, call_mpl_init=True):

        if config is None:
            config = PlotConfig()

        self._shape = len(x_dims), len(y_dims)

        dims = []
        for dim in x_dims + y_dims + z_dims:
            dim = dim.lstrip('-')
            if dim not in dims:
                dims.append(dim)

        self.config = config
        self._disconnect_data = []
        self._width = self._height = self._pixels = None
        if call_mpl_init:
            self._plt = plot.mpl_init(self.config.font_size)

        if fig is None:
            fig = self._plt.figure(
                figsize=self.config.size_inch, FigureClass=SmartplotFigure)
        else:
            assert isinstance(fig, SmartplotFigure)

        fig.set_smartplot(self)

        self._fig = fig
        self._colorbar_width = 0.0
        self._colorbar_height = 0.0
        self._colorbar_axes = []

        self._dims = dims
        self._dim_index = self._dims.index
        self._ndims = len(dims)
        self._labels = {}
        self._aspects = {}

        self.setup_axes()

        self._view_limits = num.zeros((self._ndims, 2))

        self._view_limits[:, :] = num.nan
        self._last_mpl_view_limits = None

        self._x_dims = [dim.lstrip('-') for dim in x_dims]
        self._x_dims_invert = [dim.startswith('-') for dim in x_dims]

        self._y_dims = [dim.lstrip('-') for dim in y_dims]
        self._y_dims_invert = [dim.startswith('-') for dim in y_dims]

        self._z_dims = [dim.lstrip('-') for dim in z_dims]
        self._z_dims_invert = [dim.startswith('-') for dim in z_dims]

        self._mappables = {}
        self._updating_layout = False

        self._need_update_layout = True
        self._update_geometry()

        for axes in self.axes_list:
            fig.add_axes(axes)
            self._connect(axes, 'xlim_changed', self.lim_changed_handler)
            self._connect(axes, 'ylim_changed', self.lim_changed_handler)

        self._cid_resize = fig.canvas.mpl_connect(
            'resize_event', self.resize_handler)

        try:
            self._connect(fig, 'dpi_changed', self.dpi_changed_handler)
        except ValueError:
            # 'dpi_changed' event has been removed in MPL 3.8.
            # canvas 'resize_event'  may be sufficient but needs to be checked.
            # https://matplotlib.org/stable/api/prev_api_changes/api_changes_3.8.0.html#text-get-rotation
            pass

        self._lim_changed_depth = 0

    def reset_size(self):
        self._fig.set_size_inches(self.config.size_inch)

    def axes(self, ix, iy):
        if not (isinstance(ix, int) and isinstance(iy, int)):
            ix = self._x_dims.index(ix)
            iy = self._y_dims.index(iy)

        return self._axes[iy][ix]

    def set_color_dim(self, mappable, dim):
        assert dim in self._dims
        self._mappables[mappable] = dim

    def set_aspect(self, ydim, xdim, aspect=1.0):
        self._aspects[ydim, xdim] = aspect

    @property
    def dims(self):
        return self._dims

    @property
    def fig(self):
        return self._fig

    @property
    def axes_list(self):
        axes = []
        for row in self._axes:
            axes.extend(row)
        return axes

    @property
    def axes_bottom_list(self):
        return self._axes[0]

    @property
    def axes_left_list(self):
        return [row[0] for row in self._axes]

    def setup_axes(self):
        rect = [0., 0., 1., 1.]
        nx, ny = self._shape
        axes = []
        for iy in range(ny):
            axes.append([])
            for ix in range(nx):
                axes[-1].append(SmartplotAxes(self.fig, rect))

        self._axes = axes

        for _, _, axes_ in self.iaxes():
            axes_.set_autoscale_on(False)

    def _connect(self, obj, sig, handler):
        cid = get_callbacks(obj).connect(sig, handler)
        self._disconnect_data.append((obj, cid))

    def _disconnect_all(self):
        for obj, cid in self._disconnect_data:
            get_callbacks(obj).disconnect(cid)

        self._fig.canvas.mpl_disconnect(self._cid_resize)

    def dpi_changed_handler(self, fig):
        if self._updating_layout:
            return

        self._update_geometry()

    def resize_handler(self, event):
        if self._updating_layout:
            return

        self._update_geometry()

    def lim_changed_handler(self, axes):
        if self._updating_layout:
            return

        current = self._get_mpl_view_limits()
        last = self._last_mpl_view_limits
        if last is None:
            return

        for iy, ix, axes in self.iaxes():
            acurrent = current[iy][ix]
            alast = last[iy][ix]
            if acurrent[0] != alast[0]:
                xdim = self._x_dims[ix]
                logger.debug(
                    'X limits have been changed interactively in subplot '
                    '(%i, %i)' % (ix, iy))
                self.set_lim(xdim, *sorted(acurrent[0]))

            if acurrent[1] != alast[1]:
                ydim = self._y_dims[iy]
                logger.debug(
                    'Y limits have been changed interactively in subplot '
                    '(%i, %i)' % (ix, iy))
                self.set_lim(ydim, *sorted(acurrent[1]))

        self.need_update_layout()

    def _update_geometry(self):
        w, h = self._fig.canvas.get_width_height()
        dp = self.get_device_pixel_ratio()
        p = self.get_pixels_factor() * dp

        if (self._width, self._height, self._pixels) != (w, h, p, dp):
            logger.debug(
                'New figure size: %g x %g, '
                'logical-pixel/point: %g, physical-pixel/logical-pixel: %g' % (
                    w, h, p, dp))

            self._width = w                # logical pixel
            self._height = h               # logical pixel
            self._pixels = p               # logical pixel / point
            self._device_pixel_ratio = dp  # physical / logical
            self.need_update_layout()

    @property
    def margins(self):
        return tuple(
            x * self.config.font_size / self._pixels
            for x in self.config.margins_em)

    @property
    def separator(self):
        return self.config.separator_em * self.config.font_size / self._pixels

    def rect_to_figure_coords(self, rect):
        left, bottom, width, height = rect
        return (
            left / self._width,
            bottom / self._height,
            width / self._width,
            height / self._height)

    def point_to_axes_coords(self, axes, point):
        x, y = point
        aleft, abottom, awidth, aheight = axes.get_position().bounds

        x_fig = x / self._width
        y_fig = y / self._height

        x_axes = (x_fig - aleft) / awidth
        y_axes = (y_fig - abottom) / aheight

        return (x_axes, y_axes)

    def get_pixels_factor(self):
        try:
            r = self._fig.canvas.get_renderer()
            return 1.0 / r.points_to_pixels(1.0)
        except AttributeError:
            return 1.0

    def get_device_pixel_ratio(self):
        try:
            return self._fig.canvas.device_pixel_ratio
        except AttributeError:
            return 1.0

    def make_limits(self, lims):
        a = plot.AutoScaler(space=0.05)
        return a.make_scale(lims)[:2]

    def iaxes(self):
        for iy, row in enumerate(self._axes):
            for ix, axes in enumerate(row):
                yield iy, ix, axes

    def get_data_limits(self):
        dim_to_values = defaultdict(list)
        for iy, ix, axes in self.iaxes():
            dim_to_values[self._y_dims[iy]].extend(
                axes.get_yaxis().get_data_interval())
            dim_to_values[self._x_dims[ix]].extend(
                axes.get_xaxis().get_data_interval())

        for mappable, dim in self._mappables.items():
            dim_to_values[dim].extend(mappable.get_clim())

        lims = num.zeros((self._ndims, 2))
        for idim in range(self._ndims):
            dim = self._dims[idim]
            if dim in dim_to_values:
                vs = num.array(
                    dim_to_values[self._dims[idim]], dtype=float)
                vs = vs[num.isfinite(vs)]
                if vs.size > 0:
                    lims[idim, :] = num.min(vs), num.max(vs)
                else:
                    lims[idim, :] = num.nan, num.nan
            else:
                lims[idim, :] = num.nan, num.nan

        lims[num.logical_not(num.isfinite(lims))] = 0.0
        return lims

    def set_lim(self, dim, vmin, vmax):
        assert vmin <= vmax
        self._view_limits[self._dim_index(dim), :] = vmin, vmax

    def _get_mpl_view_limits(self):
        vl = []
        for row in self._axes:
            vl_row = []
            for axes in row:
                vl_row.append((
                    axes.get_xaxis().get_view_interval().tolist(),
                    axes.get_yaxis().get_view_interval().tolist()))

            vl.append(vl_row)

        return vl

    def _remember_mpl_view_limits(self):
        self._last_mpl_view_limits = self._get_mpl_view_limits()

    def window_xmin(self, x):
        return window_min(
            self._shape[0], self._width,
            self.margins[0], self.margins[2] + self._colorbar_width,
            self.separator, x)

    def window_xmax(self, x):
        return window_max(
            self._shape[0], self._width,
            self.margins[0], self.margins[2] + self._colorbar_width,
            self.separator, x)

    def window_ymin(self, y):
        return window_min(
            self._shape[1], self._height,
            self.margins[3] + self._colorbar_height, self.margins[1],
            self.separator, y)

    def window_ymax(self, y):
        return window_max(
            self._shape[1], self._height,
            self.margins[3] + self._colorbar_height, self.margins[1],
            self.separator, y)

    def need_update_layout(self):
        self._need_update_layout = True

    def _update_layout(self):
        assert not self._updating_layout

        if not self._need_update_layout:
            return

        self._updating_layout = True
        try:
            data_limits = self.get_data_limits()

            limits = num.zeros((self._ndims, 2))
            for idim in range(self._ndims):
                limits[idim, :] = self.make_limits(data_limits[idim, :])

            mask = num.isfinite(self._view_limits)
            limits[mask] = self._view_limits[mask]

            # deltas = limits[:, 1] - limits[:, 0]

            # data_w = deltas[0]
            # data_h = deltas[1]

            ml, mt, mr, mb = self.margins
            mr += self._colorbar_width
            mb += self._colorbar_height
            sw = sh = self.separator

            nx, ny = self._shape

            # data_r = data_h / data_w
            em = self.config.font_size
            em_pixels = em / self._pixels
            w = self._width
            h = self._height
            fig_w_avail = w - mr - ml - (nx-1) * sw
            fig_h_avail = h - mt - mb - (ny-1) * sh

            if fig_w_avail <= 0.0 or fig_h_avail <= 0.0:
                raise NotEnoughSpace()

            x_limits = num.zeros((nx, 2))
            for ix, xdim in enumerate(self._x_dims):
                x_limits[ix, :] = limits[self._dim_index(xdim)]

            y_limits = num.zeros((ny, 2))
            for iy, ydim in enumerate(self._y_dims):
                y_limits[iy, :] = limits[self._dim_index(ydim)]

            def get_aspect(dim1, dim2):
                if (dim2, dim1) in self._aspects:
                    return 1.0/self._aspects[dim2, dim1]

                return self._aspects.get((dim1, dim2), None)

            aspects_xx = []
            for ix1, xdim1 in enumerate(self._x_dims):
                for ix2, xdim2 in enumerate(self._x_dims):
                    aspect = get_aspect(xdim2, xdim1)
                    if aspect:
                        aspects_xx.append((ix1, ix2, aspect))

            aspects_yy = []
            for iy1, ydim1 in enumerate(self._y_dims):
                for iy2, ydim2 in enumerate(self._y_dims):
                    aspect = get_aspect(ydim2, ydim1)
                    if aspect:
                        aspects_yy.append((iy1, iy2, aspect))

            aspects_xy = []
            for iy, ix, axes in self.iaxes():
                xdim = self._x_dims[ix]
                ydim = self._y_dims[iy]
                aspect = get_aspect(ydim, xdim)
                if aspect:
                    aspects_xy.append((ix, iy, aspect))

            (x_limits, y_limits), (aws, ahs) = solve_layout_iterative(
                size=(fig_w_avail, fig_h_avail),
                shape=(nx, ny),
                limits=(x_limits, y_limits),
                aspects=(
                    aspects_xx,
                    aspects_yy,
                    aspects_xy))

            for iy, ix, axes in self.iaxes():
                rect = [
                    ml + num.sum(aws[:ix])+(ix*sw),
                    mb + num.sum(ahs[:iy])+(iy*sh),
                    aws[ix], ahs[iy]]

                axes.set_position(
                    self.rect_to_figure_coords(rect), which='both')

                self.set_label_coords(
                    axes, 'x', [
                        wcenter(rect),
                        self.config.label_offset_em[0]*em_pixels
                        + self._colorbar_height])

                self.set_label_coords(
                    axes, 'y', [
                        self.config.label_offset_em[1]*em_pixels,
                        hcenter(rect)])

                axes.get_xaxis().set_tick_params(
                    bottom=(iy == 0), top=(iy == ny-1),
                    labelbottom=(iy == 0), labeltop=False)

                axes.get_yaxis().set_tick_params(
                    left=(ix == 0), right=(ix == nx-1),
                    labelleft=(ix == 0), labelright=False)

                istride = -1 if self._x_dims_invert[ix] else 1
                axes.set_xlim(*x_limits[ix, ::istride])
                istride = -1 if self._y_dims_invert[iy] else 1
                axes.set_ylim(*y_limits[iy, ::istride])

                axes.tick_params(
                    axis='x',
                    pad=self.config.tick_label_offset_em[0]*em)

                axes.tick_params(
                    axis='y',
                    pad=self.config.tick_label_offset_em[0]*em)

            self._remember_mpl_view_limits()

            for mappable, dim in self._mappables.items():
                mappable.set_clim(*limits[self._dim_index(dim)])

            # scaler = plot.AutoScaler()

            # aspect tick incs same
            #
            # inc = scaler.make_scale(
            #     [0, min(data_expanded_w, data_expanded_h)],
            #     override_mode='off')[2]
            #
            # for axes in self.axes_list:
            #     axes.set_xlim(*limits[0, :])
            #     axes.set_ylim(*limits[1, :])
            #
            #     tl = MultipleLocator(inc)
            #     axes.get_xaxis().set_major_locator(tl)
            #     tl = MultipleLocator(inc)
            #     axes.get_yaxis().set_major_locator(tl)

            for axes, orientation, position in self._colorbar_axes:
                if orientation == 'horizontal':
                    xmin = self.window_xmin(position[0])
                    xmax = self.window_xmax(position[1])
                    ymin = mb - self._colorbar_height
                    ymax = mb - self._colorbar_height \
                        + self.config.colorbar_width_em * em_pixels
                else:
                    ymin = self.window_ymin(position[0])
                    ymax = self.window_ymax(position[1])
                    xmin = w - mr + 2 * sw
                    xmax = w - mr + 2 * sw \
                        + self.config.colorbar_width_em * em_pixels

                rect = [xmin, ymin, xmax-xmin, ymax-ymin]
                axes.set_position(
                    self.rect_to_figure_coords(rect), which='both')

            for ix, axes in enumerate(self.axes_bottom_list):
                dim = self._x_dims[ix]
                s = self._labels.get(dim, dim)
                axes.set_xlabel(s)

            for iy, axes in enumerate(self.axes_left_list):
                dim = self._y_dims[iy]
                s = self._labels.get(dim, dim)
                axes.set_ylabel(s)

        finally:
            self._updating_layout = False

    def set_label_coords(self, axes, which, point):
        axis = axes.get_xaxis() if which == 'x' else axes.get_yaxis()
        axis.set_label_coords(*self.point_to_axes_coords(axes, point))

    def plot(self, points, *args, **kwargs):
        for iy, row in enumerate(self._axes):
            y = points[:, self._dim_index(self._y_dims[iy])]
            for ix, axes in enumerate(row):
                x = points[:, self._dim_index(self._x_dims[ix])]
                axes.plot(x, y, *args, **kwargs)

    def close(self):
        self._disconnect_all()
        self._plt.close(self._fig)

    def show(self):
        self._plt.show()
        self.reset_size()

    def set_label(self, dim, s):
        # just set attribute, handle in update_layout
        self._labels[dim] = s

    def colorbar(
            self, dim,
            orientation='vertical',
            position=None):

        if dim not in self._dims:
            raise PlotError(
                'dimension "%s" is not defined')

        if orientation not in ('vertical', 'horizontal'):
            raise PlotError(
                'orientation must be "vertical" or "horizontal"')

        mappable = None
        for mappable_, dim_ in self._mappables.items():
            if dim_ == dim:
                if mappable is None:
                    mappable = mappable_
                else:
                    mappable_.set_cmap(mappable.get_cmap())

        if mappable is None:
            raise PlotError(
                'no mappable registered for dimension "%s"' % dim)

        if position is None:
            if orientation == 'vertical':
                position = (0, self._shape[1])
            else:
                position = (0, self._shape[0])

        em_pixels = self.config.font_size / self._pixels

        if orientation == 'vertical':
            self._colorbar_width = self.config.colorbar_width_em*em_pixels + \
                self.separator * 2.0
        else:
            self._colorbar_height = self.config.colorbar_width_em*em_pixels + \
                self.separator + self.margins[3]

        axes = SmartplotAxes(self.fig, [0., 0., 1., 1.])
        self.fig.add_axes(axes)

        self._colorbar_axes.append(
            (axes, orientation, position))

        self.need_update_layout()
        # axes.plot([1], [1])
        label = self._labels.get(dim, dim)
        return colorbar.Colorbar(
            axes, mappable, orientation=orientation, label=label)

    def __call__(self, *args):
        return self.axes(*args)


if __name__ == '__main__':
    import sys
    from pyrocko import util

    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    util.setup_logging('smartplot', 'debug')

    iplots = [int(x) for x in sys.argv[1:]]

    if 0 in iplots:
        p = Plot(['x'], ['y'])
        n = 100
        x = num.arange(n) * 2.0
        y = num.random.normal(size=n)
        p(0, 0).plot(x, y, 'o')
        p.show()

    if 1 in iplots:
        p = Plot(['x', 'x'], ['y'])
        n = 100
        x = num.arange(n) * 2.0
        y = num.random.normal(size=n)
        p(0, 0).plot(x, y, 'o')
        x = num.arange(n) * 2.0
        y = num.random.normal(size=n)
        p(1, 0).plot(x, y, 'o')
        p.show()

    if 11 in iplots:
        p = Plot(['x'], ['y'])
        p.set_aspect('y', 'x', 2.0)
        n = 100
        xy = num.random.normal(size=(n, 2))
        p(0, 0).plot(xy[:, 0], xy[:, 1], 'o')
        p.show()

    if 12 in iplots:
        p = Plot(['x', 'x2'], ['y'])
        p.set_aspect('x2', 'x', 2.0)
        p.set_aspect('y', 'x', 2.0)
        n = 100
        xy = num.random.normal(size=(n, 2))
        p(0, 0).plot(xy[:, 0], xy[:, 1], 'o')
        p(1, 0).plot(xy[:, 0], xy[:, 1], 'o')
        p.show()

    if 13 in iplots:
        p = Plot(['x'], ['y', 'y2'])
        p.set_aspect('y2', 'y', 2.0)
        p.set_aspect('y', 'x', 2.0)
        n = 100
        xy = num.random.normal(size=(n, 2))
        p(0, 0).plot(xy[:, 0], xy[:, 1], 'o')
        p(0, 1).plot(xy[:, 0], xy[:, 1], 'o')
        p.show()

    if 2 in iplots:
        p = Plot(['easting', 'depth'], ['northing', 'depth'])

        n = 100

        ned = num.random.normal(size=(n, 3))
        p(0, 0).plot(ned[:, 1], ned[:, 0], 'o')
        p(1, 0).plot(ned[:, 2], ned[:, 0], 'o')
        p(0, 1).plot(ned[:, 1], ned[:, 2], 'o')
        p.show()

    if 3 in iplots:
        p = Plot(['easting', 'depth'], ['-depth', 'northing'])
        p.set_aspect('easting', 'northing', 1.0)
        p.set_aspect('easting', 'depth', 0.5)
        p.set_aspect('northing', 'depth', 0.5)

        n = 100

        ned = num.random.normal(size=(n, 3))
        ned[:, 2] *= 0.25
        p(0, 1).plot(ned[:, 1], ned[:, 0], 'o', color='black')
        p(0, 0).plot(ned[:, 1], ned[:, 2], 'o')
        p(1, 1).plot(ned[:, 2], ned[:, 0], 'o')
        p(1, 0).set_visible(False)
        p.set_lim('depth', 0., 0.2)
        p.show()

    if 5 in iplots:
        p = Plot(['time'], ['northing', 'easting', '-depth'], ['depth'])

        n = 100

        t = num.arange(n)
        xyz = num.random.normal(size=(n, 4))
        xyz[:, 0] *= 0.5

        smap = make_smap('summer')

        p(0, 0).scatter(
            t, xyz[:, 0], c=xyz[:, 2], cmap=smap.cmap, norm=smap.norm)
        p(0, 1).scatter(
            t, xyz[:, 1], c=xyz[:, 2], cmap=smap.cmap, norm=smap.norm)
        p(0, 2).scatter(
            t, xyz[:, 2], c=xyz[:, 2], cmap=smap.cmap, norm=smap.norm)

        p.set_lim('depth', -1., 1.)

        p.set_color_dim(smap, 'depth')

        p.set_aspect('northing', 'easting', 1.0)
        p.set_aspect('northing', 'depth', 1.0)

        p.set_label('time', 'Time [s]')
        p.set_label('depth', 'Depth [km]')
        p.set_label('easting', 'Easting [km]')
        p.set_label('northing', 'Northing [km]')

        p.colorbar('depth')

        p.show()

    if 6 in iplots:
        km = 1000.
        p = Plot(
            ['easting'], ['northing']*3, ['displacement'])

        nn, ne = 50, 40
        n = num.linspace(-5*km, 5*km, nn)
        e = num.linspace(-10*km, 10*km, ne)

        displacement = num.zeros((nn, ne, 3))
        g = num.exp(
            -(n[:, num.newaxis]**2 + e[num.newaxis, :]**2) / (5*km)**2)

        displacement[:, :, 0] = g
        displacement[:, :, 1] = g * 0.5
        displacement[:, :, 2] = -g * 0.2

        for icomp in (0, 1, 2):
            c = p(0, icomp).pcolormesh(
                e/km, n/km, displacement[:, :, icomp], shading='gouraud')
            p.set_color_dim(c, 'displacement')

        p.colorbar('displacement')
        p.set_lim('displacement', -1.0, 1.0)
        p.set_label('easting', 'Easting [km]')
        p.set_label('northing', 'Northing [km]')
        p.set_aspect('northing', 'easting')

        p.set_lim('northing', -5.0, 5.0)
        p.set_lim('easting', -3.0, 3.0)
        p.show()
