#!/usr/bin/python3
from subprocess import check_call, CalledProcessError

import os
import os.path as op
import re
import logging
import tempfile
import shutil
import inspect

import numpy as num
from scipy.interpolate import RegularGridInterpolator as scrgi

from matplotlib import cm, pyplot as plt, patheffects
from matplotlib.ticker import FuncFormatter

from pyrocko import gmtpy, orthodrome as pod
from pyrocko.guts import Object
from pyrocko.plot import mpl_init, mpl_papersize, mpl_color, AutoScaler
from pyrocko.plot.automap import Map, NoTopo
from pyrocko.gf import PseudoDynamicRupture
from pyrocko.gf.seismosizer import map_anchor
from pyrocko.dataset.topo.tile import Tile

logger = logging.getLogger('pyrocko.plot.dynamic_rupture')

gmtpy.check_have_gmt()
gmt = gmtpy.GMT()

km = 1e3

d2m = 111180.
m2d = 1. / d2m

cm2inch = gmtpy.cm/gmtpy.inch

d2r = num.pi / 180.
r2d = 1. / d2r


def km_formatter(v, p):
    return '%g' % (v / km)


def get_kwargs(cls):
    sig = inspect.signature(cls.__init__)
    kwargs = {}

    if cls.T.cls == RuptureMap:
        for p in Map.T.properties:
            kwargs[p.name] = p._default

    for par in sig.parameters.values():
        if par.default is inspect._empty:
            continue
        kwargs[par.name] = par.default

    return kwargs


def _save_grid(lats, lons, data, filename):
    '''
    Save lat-lon gridded data as gmt .grd file

    :param lats: Grid latitude coordinates [degree]
    :type lats: iterable
    :param lons: Grid longitude coordinates [degree]
    :type lons: iterable
    :param data: Grid data of any kind
    :type data: :py:class:`numpy.ndarray`, ``(n_lons, n_lats)``
    :param filename: Filename of the written grid file
    :type filename: str
    '''

    gmtpy.savegrd(lons, lats, data, filename=filename, naming='lonlat')


def _mplcmap_to_gmtcpt_code(mplcmap, steps=256):
    '''
    Get gmt readable R/G/A code from a given matplotlib colormap

    :param mplcmap: Name of the demanded matplotlib colormap
    :type mplcmap: str

    :returns: Series of comma seperate R/G/B values for gmtpy usage
    :rtype: str
    '''

    cmap = cm.get_cmap(mplcmap)

    rgbas = [cmap(i) for i in num.linspace(0, 255, steps).astype(num.int64)]

    return ','.join(['%g/%g/%g' % (
        c[0] * 255, c[1] * 255, c[2] * 255) for c in rgbas])


def make_colormap(
        vmin,
        vmax,
        C=None,
        cmap=None,
        space=False):
    '''
    Create gmt-readable colormap cpt file called my_<cmap>.cpt

    :type vmin: Minimum value covered by the colormap
    :param vmin: float
    :type vmax: Maximum value covered by the colormap
    :param vmax: float
    :type C: comma seperated R/G/B values for cmap definition.
    :param C: optional, str
    :type cmap: Name of the colormap. Colormap is stored as "my_<cmap>.cpt".
        If name is equivalent to a matplotlib colormap, R/G/B strings are
        extracted from this colormap.
    :param cmap: optional, str
    :type space: If True, the range of the colormap is broadened below vmin and
        above vmax.
    :param space: optional, bool
    '''

    scaler = AutoScaler(mode='min-max')
    scale = scaler.make_scale((vmin, vmax))

    incr = scale[2]
    margin = 0.

    if vmin == vmax:
        space = True

    if space:
        margin = incr

    msg = ('Please give either a valid color code or a'
           ' valid matplotlib colormap name.')

    if C is None and cmap is None:
        raise ValueError(msg)

    if C is None:
        try:
            C = _mplcmap_to_gmtcpt_code(cmap)
        except ValueError:
            raise ValueError(msg)

    if cmap is None:
        logger.warn('No colormap name given. Uses temporary filename instead')
        cmap = 'temp_cmap'

    return gmt.makecpt(
        C=C,
        D='o',
        T='%g/%g/%g' % (
            vmin - margin, vmax + margin, incr),
        Z=True,
        out_filename='my_%s.cpt' % cmap,
        suppress_defaults=True)


def clear_temp(gridfiles=[], cpts=[]):
    '''
    Clear all temporary needed grid and colormap cpt files

    :param gridfiles: List of all "...grd" files, which shall be deleted
    :type gridfiles: optional, list
    :param cpts: List of all cmaps, whose corresponding "my_<cmap>.cpt" file
        shall be deleted
    :type cpts: optional, list
    '''

    for fil in gridfiles:
        try:
            os.remove(fil)
        except OSError:
            continue
    for fil in cpts:
        try:
            os.remove('my_%s.cpt' % fil)
        except OSError:
            continue


def xy_to_latlon(source, x, y):
    '''
    Convert x and y relative coordinates on extended ruptures into latlon

    :param source: Extended source class, on which the given point is located
    :type source: :py:class:`pyrocko.gf.seismosizer.RectangularSource` or
        :py:class:`pyrocko.gf.seismosizer.PseudoDynamicRupture`
    :param x: Relative point coordinate along strike (range: -1:1)
    :type x: float or :py:class:`numpy.ndarray`
    :param y: Relative downdip point coordinate (range: -1:1)
    :type y: float or :py:class:`numpy.ndarray`

    :returns: Latitude and Longitude [degrees] of the given point
    :rtype: tuple of float
    '''

    s = source
    ax, ay = map_anchor[s.anchor]

    length, width = (x - ax) / 2. * s.length, (y - ay) / 2. * s.width
    strike, dip = s.strike * d2r, s.dip * d2r

    northing = num.cos(strike)*length - num.cos(dip) * num.sin(strike)*width
    easting = num.sin(strike)*length + num.cos(dip) * num.cos(strike)*width

    northing += source.north_shift
    easting += source.east_shift

    return pod.ne_to_latlon(s.lat, s.lon, northing, easting)


def xy_to_lw(source, x, y):
    '''
    Convert x and y relative coordinates on extended ruptures into length width

    :param source: Extended source class, on which the given points are located
    :type source: :py:class:`pyrocko.gf.seismosizer.RectangularSource` or
        :py:class:`pyrocko.gf.seismosizer.PseudoDynamicRupture`
    :param x: Relative point coordinates along strike (range: -1:1)
    :type x: float or :py:class:`numpy.ndarray`
    :param y: Relative downdip point coordinates (range: -1:1)
    :type y: float or :py:class:`numpy.ndarray`

    :returns: length and downdip width [m] of the given points from the anchor
    :rtype: tuple of float
    '''

    length, width = source.length, source.width

    ax, ay = map_anchor[source.anchor]

    lengths = (x - ax) / 2. * length
    widths = (y - ay) / 2. * width

    return lengths, widths


cbar_anchor = {
    'center': 'MC',
    'center_left': 'ML',
    'center_right': 'MR',
    'top': 'TC',
    'top_left': 'TL',
    'top_right': 'TR',
    'bottom': 'BC',
    'bottom_left': 'BL',
    'bottom_right': 'BR'}


cbar_helper = {
    'traction': {
        'unit': 'MPa',
        'factor': 1e-6},
    'tx': {
        'unit': 'MPa',
        'factor': 1e-6},
    'ty': {
        'unit': 'MPa',
        'factor': 1e-6},
    'tz': {
        'unit': 'MPa',
        'factor': 1e-6},
    'time': {
        'unit': 's',
        'factor': 1.},
    'strike': {
        'unit': '°',
        'factor': 1.},
    'dip': {
        'unit': '°',
        'factor': 1.},
    'vr': {
        'unit': 'km/s',
        'factor': 1e-3},
    'length': {
        'unit': 'km',
        'factor': 1e-3},
    'width': {
        'unit': 'km',
        'factor': 1e-3}
}


fonttype = 'Helvetica'

c2disl = dict([('x', 0), ('y', 1), ('z', 2)])


def _make_gmt_conf(fontcolor, size):
    '''
    Update different gmt parameters depending on figure size and fontcolor

    :param fontcolor: GMT readable colorcode / colorstring for the font
    :type fontcolor: str
    :param size: Tuple of the figure size (width, height) [centimetre]
    :type size: tuple of float

    :returns: estimate best fitting fontsize,
        Dictionary of different gmt configuration parameter
    :rtype: float, dict
    '''

    color = fontcolor
    fontsize = num.max(size)

    font = '%gp,%s' % (fontsize, fonttype)

    pen_size = fontsize / 16.
    tick_size = num.min(size) / 200.

    return fontsize, dict(
        MAP_FRAME_PEN='%s' % color,
        MAP_TICK_PEN_PRIMARY='%gp,%s' % (pen_size, color),
        MAP_TICK_PEN_SECONDARY='%gp,%s' % (pen_size, color),
        MAP_TICK_LENGTH_PRIMARY='%gc' % tick_size,
        MAP_TICK_LENGTH_SECONDARY='%gc' % (tick_size * 3),
        FONT_ANNOT_PRIMARY='%s-Bold,%s' % (font, color),
        FONT_LABEL='%s-Bold,%s' % (font, color),
        FONT_TITLE='%s-Bold,%s' % (font, color),
        PS_CHAR_ENCODING='ISOLatin1+',
        MAP_FRAME_TYPE='fancy',
        FORMAT_GEO_MAP='D',
        PS_PAGE_ORIENTATION='portrait',
        MAP_GRID_PEN_PRIMARY='thinnest,%s' % color,
        MAP_ANNOT_OBLIQUE='6')


class SourceError(Exception):
    pass


class RuptureMap(Map):
    ''' Map plotting of attributes and results of the
        :py:class:`pyrocko.gf.seismosizer.PseudoDynamicRupture`
    '''

    def __init__(
            self,
            source=None,
            fontcolor='darkslategrey',
            width=20.,
            height=14.,
            margins=None,
            topo_cpt_wet='light_sea_uniform',
            topo_cpt_dry='light_land_uniform',
            show_cities=False,
            *args, **kwargs):

        size = (width, height)
        fontsize, gmt_config = _make_gmt_conf(fontcolor, size)

        if margins is None:
            margins = [
                fontsize * 0.15, num.min(size) / 200.,
                num.min(size) / 200., fontsize * 0.05]

        Map.__init__(self, margins=margins, width=width, height=height,
                     gmt_config=gmt_config,
                     topo_cpt_dry=topo_cpt_dry, topo_cpt_wet=topo_cpt_wet,
                     *args, **kwargs)

        if show_cities:
            self.draw_cities()

        self._source = source
        self._fontcolor = fontcolor
        self._fontsize = fontsize
        self.axes_layout = 'WeSn'

    @property
    def size(self):
        '''
        Figure size [cm]
        '''

        return (self.width, self.height)

    @property
    def font(self):
        '''
        Font style (size and type)
        '''

        return '%sp,%s' % (self._fontsize, fonttype)

    @property
    def source(self):
        '''
        PseudoDynamicRupture whose attributes are plotted.

        Note, that source.patches attribute needs to be calculated
        :type source: :py:class:`pyrocko.gf.seismosizer.PseudoDynamicRupture`
        '''

        if self._source is None:
            raise SourceError('No source given. Please define it!')

        if not isinstance(self._source, PseudoDynamicRupture):
            raise SourceError('This function is only capable for a source of'
                              ' type: %s' % type(PseudoDynamicRupture()))

        if not self._source.patches:
            raise TypeError('No source patches are defined. Please run'
                            '"source.discretize_patches()" on your source')

        return self._source

    @source.setter
    def source(self, source):
        self._source = source

    def _get_topotile(self):
        if self._dems is None:
            self._setup()

        try:
            t, _ = self._get_topo_tile('land')
        except NoTopo:
            wesn = self.wesn

            nx = int(num.ceil(
                self.width * cm2inch * self.topo_resolution_max))
            ny = int(num.ceil(
                self.height * cm2inch * self.topo_resolution_max))

            data = num.zeros((nx, ny))

            t = Tile(wesn[0], wesn[2],
                     (wesn[1] - wesn[0]) / nx, (wesn[3] - wesn[2]) / ny,
                     data)

        return t

    def _patches_to_lw(self):
        '''
        Generate regular rect. length-width grid based on the patch distance

        Prerequesite is a regular grid of patches (constant lengths and widths)
        Both coordinates are given relative to the source anchor point [in m]
        The grid is extended from the patch centres to the edges of the source

        :returns: lengths along strike, widths downdip
        :rtype: :py:class:`numpy.ndarray`, :py:class:`numpy.ndarray`
        '''

        source = self.source
        patches = source.patches

        patch_l, patch_w = patches[0].length, patches[0].width

        patch_lengths = num.concatenate((
            num.array([0.]),
            num.array([il*patch_l+patch_l/2. for il in range(source.nx)]),
            num.array([patch_l * source.nx])))

        patch_widths = num.concatenate((
            num.array([0.]),
            num.array([iw*patch_w+patch_w/2. for iw in range(source.ny)]),
            num.array([patch_w * source.ny])))

        ax, ay = map_anchor[source.anchor]

        patch_lengths -= source.length * (ax + 1.) / 2.
        patch_widths -= source.width * (ay + 1.) / 2.

        return patch_lengths, patch_widths

    def _xy_to_lw(self, x, y):
        '''
        Generate regular rect. length-width grid based on the xy coordinates

        Prerequesite is a regular grid with constant dx and dy. x and y are
        relative coordinates on the rupture plane (range -1:1) along strike and
        downdip.
        Length and width are obtained relative to the source anchor point
        [in m].

        :returns: lengths along strike [m], widths downdip [m]
        :rtype: :py:class:`numpy.ndarray`, :py:class:`numpy.ndarray`
        '''

        x, y = num.unique(x), num.unique(y)
        dx, dy = x[1] - x[0], y[1] - y[0]

        if any(num.abs(num.diff(x) - dx) >= 1e-6):
            raise ValueError('Regular grid with constant spacing needed.'
                             ' Please check the x coordinates.')

        if any(num.abs(num.diff(y) - dy) >= 1e-6):
            raise ValueError('Regular grid with constant spacing needed.'
                             ' Please check the y coordinates.')

        return xy_to_lw(self.source, x, y)

    def _tile_to_lw(self, ref_lat, ref_lon,
                    north_shift=0., east_shift=0., strike=0.):

        '''
        Coordinate transformation from the topo tile grid into length-width

        The topotile latlon grid is rotated into the length width grid. The
        width is defined here as its horizontal component. The resulting grid
        is used for interpolation of grid data.

        :param ref_lat: Reference latitude, from which length-width relative
            coordinatesgrid are calculated
        :type ref_lat: float
        :param ref_lon: Reference longitude, from which length-width relative
            coordinatesgrid are calculated
        :type ref_lon: float
        :param north_shift: North shift of the reference point [m]
        :type north_shift: optional, float
        :param east_shift: East shift of the reference point [m]
        :type east_shift: optional, float
        :param strike: striking of the length axis compared to the North axis
            [degree]
        :type strike: optional, float

        :returns: topotile grid nodes as array of length-width coordinates
        :rtype: :py:class:`numpy.ndarray`, ``(n_nodes, 2)``
        '''

        t = self._get_topotile()
        grid_lats = t.y()
        grid_lons = t.x()

        meshgrid_lons, meshgrid_lats = num.meshgrid(grid_lons, grid_lats)

        grid_northing, grid_easting = pod.latlon_to_ne_numpy(
            ref_lat, ref_lon, meshgrid_lats.flatten(), meshgrid_lons.flatten())

        grid_northing -= north_shift
        grid_easting -= east_shift

        strike *= d2r
        sin, cos = num.sin(strike), num.cos(strike)
        points_out = num.zeros((grid_northing.shape[0], 2))
        points_out[:, 0] = -sin * grid_northing + cos * grid_easting
        points_out[:, 1] = cos * grid_northing + sin * grid_easting

        return points_out

    def _prep_patch_grid_data(self, data):
        '''
        Extend patch data from patch centres to the outer source edges

        Patch data is always defined in the centre of the patches. For
        interpolation the data is extended here to the edges of the rupture
        plane.

        :param data: Patch wise data
        :type data: :py:class:`numpy.ndarray`

        :returns: Extended data array
        :rtype: :py:class:`numpy.ndarray`
        '''

        shape = (self.source.nx + 2, self.source.ny + 2)
        data = data.reshape(self.source.nx, self.source.ny).copy()

        data_new = num.zeros(shape)
        data_new[1:-1, 1:-1] = data
        data_new[1:-1, 0] = data[:, 0]
        data_new[1:-1, -1] = data[:, -1]
        data_new[0, 1:-1] = data[0, :]
        data_new[-1, 1:-1] = data[-1, :]

        for i, j in zip([-1, -1, 0, 0], [-1, 0, -1, 0]):
            data_new[i, j] = data[i, j]

        return data_new

    def _regular_data_to_grid(self, lengths, widths, data, filename):
        '''
        Interpolate regular data onto topotile grid

        Regular gridded data is interpolated onto the latlon grid of the
        topotile. It is then stored as a gmt-readable .grd-file.

        :param lengths: Grid coordinates along strike relative to anchor [m]
        :type lengths: :py:class:`numpy.ndarray`
        :param widths: Grid coordinates downdip relative to anchor [m]
        :type widths: :py:class:`numpy.ndarray`
        :param data: Data grid array
        :type data: :py:class:`numpy.ndarray`
        :param filename: Filename, where grid is stored
        :type filename: str
        '''

        source = self.source

        interpolator = scrgi(
            (widths * num.cos(d2r * source.dip), lengths),
            data.T,
            bounds_error=False,
            method='nearest')

        points_out = self._tile_to_lw(
            ref_lat=source.lat,
            ref_lon=source.lon,
            north_shift=source.north_shift,
            east_shift=source.east_shift,
            strike=source.strike)

        t = self._get_topotile()
        t.data = num.zeros_like(t.data, dtype=num.float)
        t.data[:] = num.nan

        t.data = interpolator(points_out).reshape(t.data.shape)

        _save_grid(t.y(), t.x(), t.data, filename=filename)

    def patch_data_to_grid(self, data, *args, **kwargs):
        '''
        Generate a grid file based on regular patch wise data.

        :param data: Patchwise data grid array
        :type data: :py:class:`numpy.ndarray`
        '''

        lengths, widths = self._patches_to_lw()

        data_new = self._prep_patch_grid_data(data)

        self._regular_data_to_grid(lengths, widths, data_new, *args, **kwargs)

    def xy_data_to_grid(self, x, y, data, *args, **kwargs):
        '''
        Generate a grid file based on regular gridded data using xy coordinates

        Convert a grid based on relative fault coordinates (range -1:1) along
        strike (x) and downdip (y) into a .grd file.

        :param x: Relative point coordinate along strike (range: -1:1)
        :type x: float or :py:class:`numpy.ndarray`
        :param y: Relative downdip point coordinate (range: -1:1)
        :type y: float or :py:class:`numpy.ndarray`
        :param data: Patchwise data grid array
        :type data: :py:class:`numpy.ndarray`
        '''

        lengths, widths = self._xy_to_lw(x, y)

        self._regular_data_to_grid(
            lengths, widths, data.reshape((lengths.shape[0], widths.shape[0])),
            *args, **kwargs)

    def draw_image(self, gridfile, cmap, cbar=True, **kwargs):
        '''
        Draw grid data as image and include, if whished, a colorbar

        :param gridfile: File of the grid which shall be plotted
        :type gridfile: str
        :param cmap: Name of the colormap, which shall be used. A .cpt-file
            "my_<cmap>.cpt" must exist
        :type cmap: str
        :param cbar: If True, a colorbar corresponding to the grid data is
            added. Keywordarguments are parsed to it.
        :type cbar: optional, bool
        '''

        self.gmt.grdimage(
            gridfile,
            C='my_%s.cpt' % cmap,
            E='200',
            Q=True,
            n='+t0.0',
            *self.jxyr)

        if cbar:
            self.draw_colorbar(cmap=cmap, **kwargs)

    def draw_contour(
            self,
            gridfile,
            contour_int,
            anot_int,
            angle=None,
            unit='',
            color='',
            style='',
            **kwargs):

        '''
        Draw grid data as contour lines

        :param gridfile: File of the grid which shall be plotted
        :type gridfile: str
        :param contour_int: Interval of contour lines in units of the gridfile
        :type contour_int: float
        :param anot_int: Interval of labelled contour lines in units of the
            gridfile. Must be a integer multiple of contour_int
        :type anot_int: float
        :param angle: Rotation angle of the labels [degree]
        :type angle: optional, float
        :param unit: Name of the unit in the grid file. It will be displayed
            behind the label on labelled contour lines
        :type unit: optional, str
        :param color: GMT readable color code/str of the contour lines
        :type color: optional, str
        :param style: Line style of the contour lines. If not given, solid
            lines are plotted
        :type style: optional, str
        '''

        pen_size = self._fontsize / 40.

        if not color:
            color = self._fontcolor

        a_string = '%g+f%s,%s+r%gc+u%s' % (
            anot_int, self.font, color, pen_size*4, unit)
        if angle:
            a_string += '+a%g' % angle
        c_string = '%g' % contour_int

        if kwargs:
            kwargs['A'], kwargs['C'] = a_string, c_string
        else:
            kwargs = dict(A=a_string, C=c_string)

        if style:
            style = ',' + style

        args = ['-Wc%gp,%s%s+s' % (pen_size, color, style)]

        self.gmt.grdcontour(
            gridfile,
            S='10',
            W='a%gp,%s%s+s' % (pen_size*4, color, style),
            *self.jxyr + args,
            **kwargs)

    def draw_colorbar(self, cmap, label='', anchor='top_right', **kwargs):
        '''
        Draw a colorbar based on a existing colormap

        :param cmap: Name of the colormap, which shall be used. A .cpt-file
            "my_<cmap>.cpt" must exist
        :type cmap: str
        :param label: Title of the colorbar
        :type label: optional, str
        :param anchor: Placement of the colorbar. Combine 'top', 'center' and
            'bottom' with 'left', None for middle and 'right'
        :type anchor: optional, str
        '''

        if not kwargs:
            kwargs = {}

        if label:
            kwargs['B'] = 'af+l%s' % label

        kwargs['C'] = 'my_%s.cpt' % cmap
        a_str = cbar_anchor[anchor]

        w = self.width / 3.
        h = w / 10.

        lgap = rgap = w / 10.
        bgap, tgap = h, h / 10.

        dx, dy = 2.5 * lgap, 2. * tgap

        if 'bottom' in anchor:
            dy += 4 * h

        self.gmt.psscale(
            D='j%s+w%gc/%gc+h+o%gc/%gc' % (a_str, w, h, dx, dy),
            F='+g238/236/230+c%g/%g/%g/%g' % (lgap, rgap, bgap, tgap),
            *self.jxyr,
            **kwargs)

    def draw_vector(self, x_gridfile, y_gridfile, vcolor='', **kwargs):
        ''' Draw vectors based on two grid files

        Two grid files for vector lengths in x and y need to be given. The
        function calls gmt.grdvector. All arguments defined for this function
        in gmt can be passed as keyword arguments. Different standard settings
        are applied if not defined differently.

        :param x_gridfile: File of the grid defining vector lengths in x
        :type x_gridfile: str
        :param y_gridfile: File of the grid defining vector lengths in y
        :type y_gridfile: str
        :param vcolor: Vector face color as defined in "G" option
        :type vcolor: str
        '''

        kwargs['S'] = kwargs.get('S', 'il1.')
        kwargs['I'] = kwargs.get('I', 'x20')
        kwargs['W'] = kwargs.get('W', '0.3p,%s' % 'black')
        kwargs['Q'] = kwargs.get('Q', '4c+e+n5c+h1')

        self.gmt.grdvector(
            x_gridfile, y_gridfile,
            G='%s' % 'lightgrey' if not vcolor else vcolor,
            *self.jxyr,
            **kwargs)

    def draw_dynamic_data(self, data, original_patch_indices=None, **kwargs):
        '''
        Draw an image of any data gridded on the patches e.g dislocation

        :param data: Patchwise data grid array
        :type data: :py:class:`numpy.ndarray`
        :param original_patch_indices: If the source has been recalculated and
            manually manipulated (``patches``, ``coef_mat`` etc.),
            then give here a boolean array indicating the position of the
            remaining patches on the original patch grid. False is interpreted
            as no data, ``True`` is replaced by the patch data.
        :type original_patch_indices: optional,
            :py:class:`numpy.ndarray` of bool ``(source.nx, source.ny)``
        '''

        plot_data = data
        if original_patch_indices is not None:
            plot_data = num.zeros(original_patch_indices.shape)
            plot_data[original_patch_indices] = data

        kwargs['cmap'] = kwargs.get('cmap', 'afmhot_r')

        clim = kwargs.pop('clim', (plot_data.min(), plot_data.max()))

        cpt = []
        if not op.exists('my_%s.cpt' % kwargs['cmap']):
            make_colormap(clim[0], clim[1],
                          cmap=kwargs['cmap'], space=False)
            cpt = [kwargs['cmap']]

        tmp_grd_file = 'tmpdata.grd'
        self.patch_data_to_grid(plot_data, tmp_grd_file)
        self.draw_image(tmp_grd_file, **kwargs)

        clear_temp(gridfiles=[tmp_grd_file], cpts=cpt)

    def draw_patch_parameter(self, attribute, **kwargs):
        '''Draw an image of a chosen patch attribute e.g traction

        :param attribute: Patch attribute, which is plotted. All patch
            attributes can be taken (see doc of
            :py:class:`pyrocko.modelling.okada.OkadaSource`) and also
            ``traction``, ``tx``, ``ty`` or ``tz`` to display the
            length or the single components of the traction vector.
        :type attribute: str
        '''

        a = attribute
        source = self.source

        if a == 'traction':
            data = num.linalg.norm(source.get_tractions(), axis=1)
        elif a == 'tx':
            data = source.get_tractions()[:, 0]
        elif a == 'ty':
            data = source.get_tractions()[:, 1]
        elif a == 'tz':
            data = source.get_tractions()[:, 2]
        else:
            data = source.get_patch_attribute(attribute)

        factor = 1. if 'label' in kwargs else cbar_helper[a]['factor']
        data *= factor

        kwargs['label'] = kwargs.get(
            'label',
            '%s [%s]' % (a, cbar_helper[a]['unit']))

        self.draw_dynamic_data(data, **kwargs)

    def draw_time_contour(self, store, clevel=[], **kwargs):
        '''Draw high contour lines of the rupture front propgation time

        :param store: Greens function store, which is used for time calculation
        :type store: :py:class:`pyrocko.gf.store.Store`
        :param clevel: List of times, for which contour lines are drawn,
            optional
        :type clevel: list of float
        '''

        _, _, _, _, points_xy = self.source._discretize_points(store, cs='xyz')
        _, _, times, _, _, _ = self.source.get_vr_time_interpolators(store)

        scaler = AutoScaler(mode='0-max', approx_ticks=8)
        scale = scaler.make_scale([num.min(times), num.max(times)])

        if clevel:
            if len(clevel) > 1:
                kwargs['anot_int'] = num.min(num.diff(clevel))
            else:
                kwargs['anot_int'] = clevel[0]

            kwargs['contour_int'] = kwargs['anot_int']
            kwargs['L'] = '0/%g' % num.max(clevel)

        kwargs['anot_int'] = kwargs.get('anot_int', scale[2] * 2.)
        kwargs['contour_int'] = kwargs.get('contour_int', scale[2])
        kwargs['unit'] = kwargs.get('unit', cbar_helper['time']['unit'])
        kwargs['L'] = kwargs.get('L', '0/%g' % (num.max(times) + 1.))
        kwargs['G'] = kwargs.get('G', 'n2/3c')

        tmp_grd_file = 'tmpdata.grd'
        self.xy_data_to_grid(points_xy[:, 0], points_xy[:, 1],
                             times, tmp_grd_file)
        self.draw_contour(tmp_grd_file, **kwargs)

        clear_temp(gridfiles=[tmp_grd_file], cpts=[])

    def draw_points(self, lats, lons, symbol='point', size=None, **kwargs):
        '''Draw points at given locations

        :param lats: Point latitude coordinates [degree]
        :type lats: iterable
        :param lons: Point longitude coordinates [degree]
        :type lons: iterable
        :param symbol: Define symbol of the points
            (``'star', 'circle', 'point', 'triangle'``) - default is ``point``
        :type symbol: optional, str
        :param size: Size of the points in points
        :type size: optional, float
        '''

        sym_to_gmt = dict(
            star='a',
            circle='c',
            point='p',
            triangle='t')

        lats = num.atleast_1d(lats)
        lons = num.atleast_1d(lons)

        if lats.shape[0] != lons.shape[0]:
            raise IndexError('lats and lons do not have the same shape!')

        if size is None:
            size = self._fontsize / 3.

        kwargs['S'] = kwargs.get('S', sym_to_gmt[symbol] + '%gp' % size)
        kwargs['G'] = kwargs.get('G', gmtpy.color('scarletred2'))
        kwargs['W'] = kwargs.get('W', '2p,%s' % self._fontcolor)

        self.gmt.psxy(
            in_columns=[lons, lats],
            *self.jxyr,
            **kwargs)

    def draw_nucleation_point(self, **kwargs):
        ''' Plot the nucleation point onto the map '''

        nlat, nlon = xy_to_latlon(
            self.source, self.source.nucleation_x, self.source.nucleation_y)

        self.draw_points(nlat, nlon, **kwargs)

    def draw_dislocation(self, time=None, component='', **kwargs):
        ''' Draw dislocation onto map at any time

        For a given time (if ``time`` is ``None``, ``tmax`` is used)
        and given component the patchwise dislocation is plotted onto the map.

        :param time: time after origin, for which dislocation is computed. If
            ``None``, ``tmax`` is taken.
        :type time: optional, float
        :param component: Dislocation component, which shall be plotted: ``x``
            along strike, ``y`` along updip, ``z`` normal. If ``None``, the
            length of the dislocation vector is plotted
        '''

        disl = self.source.get_okada_slip(time=time)

        if component:
            data = disl[:, c2disl[component]]
        else:
            data = num.linalg.norm(disl, axis=1)

        kwargs['label'] = kwargs.get(
            'label', 'u%s [m]' % (component))

        self.draw_dynamic_data(data, **kwargs)

    def draw_dislocation_contour(
            self, time=None, component=None, clevel=[], **kwargs):
        ''' Draw dislocation contour onto map at any time

        For a given time (if ``time`` is ``None``, ``tmax`` is used)
        and given component the patchwise dislocation is plotted as contour
        onto the map.

        :param time: time after origin, for which dislocation is computed. If
            ``None``, ``tmax`` is taken.
        :type time: optional, float
        :param component: Dislocation component, which shall be plotted: ``x``
            along strike, ``y`` along updip, ``z`` normal``. If ``None``,
            the length of the dislocation vector is plotted
        :param clevel: List of times, for which contour lines are drawn
        :type clevel: optional, list of float
        '''

        disl = self.source.get_okada_slip(time=time)

        if component:
            data = disl[:, c2disl[component]]
        else:
            data = num.linalg.norm(disl, axis=1)

        scaler = AutoScaler(mode='min-max', approx_ticks=7)
        scale = scaler.make_scale([num.min(data), num.max(data)])

        if clevel:
            if len(clevel) > 1:
                kwargs['anot_int'] = num.min(num.diff(clevel))
            else:
                kwargs['anot_int'] = clevel[0]

            kwargs['contour_int'] = kwargs['anot_int']
            kwargs['L'] = '%g/%g' % (
                num.min(clevel) - kwargs['contour_int'],
                num.max(clevel) + kwargs['contour_int'])
        else:
            kwargs['anot_int'] = kwargs.get('anot_int', scale[2] * 2.)
            kwargs['contour_int'] = kwargs.get('contour_int', scale[2])
            kwargs['L'] = kwargs.get('L', '%g/%g' % (
                num.min(data) - 1., num.max(data) + 1.))

        kwargs['unit'] = kwargs.get('unit', ' m')
        kwargs['G'] = kwargs.get('G', 'n2/3c')

        tmp_grd_file = 'tmpdata.grd'
        self.patch_data_to_grid(data, tmp_grd_file)
        self.draw_contour(tmp_grd_file, **kwargs)

        clear_temp(gridfiles=[tmp_grd_file], cpts=[])

    def draw_dislocation_vector(self, time=None, **kwargs):
        '''Draw vector arrows onto map indicating direction of dislocation

        For a given time (if ``time`` is ``None``, ``tmax`` is used)
        and given component the dislocation is plotted as vectors onto the map.

        :param time: time after origin [s], for which dislocation is computed.
            If ``None``, ``tmax`` is used.
        :type time: optional, float
        '''

        disl = self.source.get_okada_slip(time=time)

        p_strike = self.source.get_patch_attribute('strike') * d2r
        p_dip = self.source.get_patch_attribute('dip') * d2r

        disl_dh = num.cos(p_dip) * disl[:, 1]
        disl_n = num.cos(p_strike) * disl[:, 0] + num.sin(p_strike) * disl_dh
        disl_e = num.sin(p_strike) * disl[:, 0] - num.cos(p_strike) * disl_dh

        tmp_grd_files = ['tmpdata_%s.grd' % c for c in ('n', 'e')]

        self.patch_data_to_grid(disl_n, tmp_grd_files[0])
        self.patch_data_to_grid(disl_e, tmp_grd_files[1])

        self.draw_vector(
            tmp_grd_files[1], tmp_grd_files[0],
            **kwargs)

        clear_temp(gridfiles=tmp_grd_files, cpts=[])


class RuptureView(Object):
    ''' Plot of attributes and results of the
        :py:class:`pyrocko.gf.seismosizer.PseudoDynamicRupture`.
    '''

    _patches_to_lw = RuptureMap._patches_to_lw

    def __init__(self, source=None, figsize=None, fontsize=None):
        self._source = source
        self._axes = None

        self.figsize = figsize or mpl_papersize('halfletter', 'landscape')
        self.fontsize = fontsize or 10
        mpl_init(fontsize=self.fontsize)

        self._fig = None
        self._axes = None
        self._is_1d = False

    @property
    def source(self):
        ''' PseudoDynamicRupture whose attributes are plotted.

        Note, that source.patches attribute needs to be calculated for
        :type source: :py:class:`pyrocko.gf.seismosizer.PseudoDynamicRupture`
        '''

        if self._source is None:
            raise SourceError('No source given. Please define it!')

        if not isinstance(self._source, PseudoDynamicRupture):
            raise SourceError('This function is only capable for a source of'
                              ' type: %s' % type(PseudoDynamicRupture()))

        if not self._source.patches:
            raise TypeError('No source patches are defined. Please run'
                            '\"discretize_patches\" on your source')

        return self._source

    @source.setter
    def source(self, source):
        self._source = source

    def _setup(
            self,
            title='',
            xlabel='',
            ylabel='',
            aspect=1.,
            spatial_plot=True,
            **kwargs):

        if self._fig is not None and self._axes is not None:
            return

        self._fig = plt.figure(figsize=self.figsize)

        self._axes = self._fig.add_subplot(1, 1, 1, aspect=aspect)
        ax = self._axes

        if ax is not None:
            ax.set_title(title)
            ax.grid(alpha=.3)
            ax.set_xlabel(xlabel)
            ax.set_ylabel(ylabel)

        if spatial_plot:
            ax.xaxis.set_major_formatter(FuncFormatter(km_formatter))
            ax.yaxis.set_major_formatter(FuncFormatter(km_formatter))

    def _clear_all(self):
        plt.cla()
        plt.clf()
        plt.close()

        self._fig, self._axes = None, None

    def _draw_scatter(self, x, y, *args, **kwargs):
        default_kwargs = dict(
            linewidth=0,
            marker='o',
            markerfacecolor=mpl_color('skyblue2'),
            markersize=6.,
            markeredgecolor=mpl_color('skyblue3'))
        default_kwargs.update(kwargs)

        if self._axes is not None:
            self._axes.plot(x, y, *args, **default_kwargs)

    def _draw_image(self, length, width, data, *args, **kwargs):
        if self._axes is not None:
            if 'extent' not in kwargs:
                kwargs['extent'] = [
                    num.min(length), num.max(length),
                    num.max(width), num.min(width)]

            im = self._axes.imshow(
                data,
                interpolation='none',
                vmin=kwargs.get('clim', [None])[0],
                vmax=kwargs.get('clim', [None, None])[1],
                *args,
                **kwargs)

            del kwargs['extent']
            if 'aspect' in kwargs:
                del kwargs['aspect']
            if 'clim' in kwargs:
                del kwargs['clim']
            if 'cmap' in kwargs:
                del kwargs['cmap']

            plt.colorbar(
                im, shrink=0.9, pad=0.03, aspect=15., *args, **kwargs)

    def _draw_contour(self, x, y, data, clevel=None, unit='', *args, **kwargs):
        setup_kwargs = dict(
            xlabel=kwargs.pop('xlabel', 'along strike [km]'),
            ylabel=kwargs.pop('ylabel', 'down dip [km]'),
            title=kwargs.pop('title', ''),
            aspect=kwargs.pop('aspect', 1))

        self._setup(**setup_kwargs)

        if self._axes is not None:
            if clevel is None:
                scaler = AutoScaler(mode='min-max')
                scale = scaler.make_scale([data.min(), data.max()])

                clevel = num.arange(scale[0], scale[1] + scale[2], scale[2])

            if not isinstance(clevel, num.ndarray):
                clevel = num.array([clevel])

            clevel = clevel[clevel < data.max()]

            cont = self._axes.contour(
                x, y, data, clevel, *args,
                linewidths=1.5, **kwargs)

            plt.setp(cont.collections, path_effects=[
                patheffects.withStroke(linewidth=2.0, foreground="beige"),
                patheffects.Normal()])

            clabels = self._axes.clabel(
                cont, clevel[::2], *args,
                inline=1, fmt='%g' + '%s' % unit,
                inline_spacing=15, rightside_up=True, use_clabeltext=True,
                **kwargs)

            plt.setp(clabels, path_effects=[
                patheffects.withStroke(linewidth=1.25, foreground="beige"),
                patheffects.Normal()])

    def draw_points(self, length, width, *args, **kwargs):
        ''' Draw a point onto the figure.

        Args and kwargs can be defined according to
        :py:func:`matplotlib.pyplot.scatter`.

        :param length: Point(s) coordinate on the rupture plane along strike
            relative to the anchor point [m]
        :type length: float, :py:class:`numpy.ndarray`
        :param width: Point(s) coordinate on the rupture plane along downdip
            relative to the anchor point [m]
        :type width: float, :py:class:`numpy.ndarray`
        '''

        if self._axes is not None:
            kwargs['color'] = kwargs.get('color', mpl_color('scarletred2'))
            kwargs['s'] = kwargs.get('s', 100.)

            self._axes.scatter(length, width, *args, **kwargs)

    def draw_dynamic_data(self, data, original_patch_indices=None, **kwargs):
        ''' Draw an image of any data gridded on the patches e.g dislocation

        :param data: Patchwise data grid array
        :type data: :py:class:`numpy.ndarray`
        :param original_patch_indices: If the source has been recalculated and
            manually manipulated (``patches``, ``coef_mat`` etc.), then give
            here a boolean array indicating the position of the remaining
            patches on the original patch grid. False is interpreted
            as no data, ``True`` is replaced by the patch data.
        :type original_patch_indices: optional,
            :py:class:`numpy.ndarray` of bool ``(source.nx, source.ny)``
        '''

        plot_data = data
        if original_patch_indices is not None:
            plot_data = num.zeros(original_patch_indices.shape)
            plot_data[original_patch_indices] = data

        anchor_x, anchor_y = map_anchor[self.source.anchor]

        length, width = xy_to_lw(
            self.source, num.array([-1., 1.]), num.array([-1., 1.]))

        data = plot_data.reshape(self.source.nx, self.source.ny).T

        kwargs['cmap'] = kwargs.get('cmap', 'afmhot_r')

        setup_kwargs = dict(
            xlabel='along strike [km]',
            ylabel='down dip [km]',
            title='',
            aspect=1)
        setup_kwargs.update(kwargs)

        kwargs = {k: v for k, v in kwargs.items() if k not in
                  ('xlabel', 'ylabel', 'title')}
        self._setup(**setup_kwargs)
        self._draw_image(length=length, width=width, data=data, **kwargs)

    def draw_patch_parameter(self, attribute, **kwargs):
        ''' Draw an image of a chosen patch attribute e.g traction

        :param attribute: Patch attribute, which is plotted. All patch
            attributes can be taken (see doc of
            :py:class:`pyrocko.modelling.okada.OkadaSource`) and also
            ``'traction', 'tx', 'ty', 'tz'`` to display the length
            or the single components of the traction vector.
        :type attribute: str
        '''

        a = attribute
        source = self.source

        if a == 'traction':
            data = num.linalg.norm(source.get_tractions(), axis=1)
        elif a == 'tx':
            data = source.get_tractions()[:, 0]
        elif a == 'ty':
            data = source.get_tractions()[:, 1]
        elif a == 'tz':
            data = source.get_tractions()[:, 2]
        else:
            data = source.get_patch_attribute(attribute)

        factor = 1. if 'label' in kwargs else cbar_helper[a]['factor']
        data *= factor

        kwargs['label'] = kwargs.get(
            'label',
            '%s [%s]' % (a, cbar_helper[a]['unit']))

        return self.draw_dynamic_data(data=data, **kwargs)

    def draw_time_contour(self, store, clevel=[], **kwargs):
        ''' Draw high resolution contours of the rupture front propgation time

        :param store: Greens function store, which is used for time calculation
        :type store: :py:class:`pyrocko.gf.store.Store`
        :param clevel: levels of the contour lines. If no levels are given,
            they are automatically computed based on tmin and tmax
        :type clevel: optional, list
        '''
        source = self.source
        default_kwargs = dict(
            colors='#474747ff'
        )
        default_kwargs.update(kwargs)

        *_, points_xy = source._discretize_points(store, cs='xyz')
        *_, time_interpolator, _ = source.get_vr_time_interpolators(store)

        times = time_interpolator.values

        scaler = AutoScaler(mode='min-max', approx_ticks=8)
        scale = scaler.make_scale([times.min(), times.max()])

        if len(clevel) == 0:
            clevel = num.arange(scale[0] + scale[2], scale[1], scale[2])

        points_x = time_interpolator.grid[0]
        points_y = time_interpolator.grid[1]

        self._draw_contour(points_x, points_y, data=times.T,
                           clevel=clevel, unit='s', **default_kwargs)

    def draw_nucleation_point(self, **kwargs):
        ''' Draw the nucleation point onto the map '''

        nuc_x, nuc_y = self.source.nucleation_x, self.source.nucleation_y
        length, width = xy_to_lw(self.source, nuc_x, nuc_y)
        self.draw_points(length, width, marker='o', **kwargs)

    def draw_dislocation(self, time=None, component='', **kwargs):
        ''' Draw dislocation onto map at any time

        For a given time (if ``time`` is ``None``, ``tmax`` is used)
        and given component the patchwise dislocation is plotted onto the map.

        :param time: time after origin [s], for which dislocation is computed.
            If ``None``, ``tmax`` is taken.
        :type time: optional, float
        :param component: Dislocation component, which shall be plotted: ``x``
            along strike, ``y`` along updip, ``z`` normal. If ``None``, the
            length of the dislocation vector is plotted
        '''

        disl = self.source.get_okada_slip(time=time)

        if component:
            data = disl[:, c2disl[component]]
        else:
            data = num.linalg.norm(disl, axis=1)

        kwargs['label'] = kwargs.get(
            'label', 'u%s [m]' % (component))

        self.draw_dynamic_data(data, **kwargs)

    def draw_dislocation_contour(
            self, time=None, component=None, clevel=[], **kwargs):
        ''' Draw dislocation contour onto map at any time

        For a given time (if time is ``None``, ``tmax`` is used) and given
        component the patchwise dislocation is plotted as contour onto the map.

        :param time: time after origin, for which dislocation is computed. If
            None, tmax is taken.
        :type time: optional, float
        :param component: Dislocation component, which shall be plotted. ``x``
            along strike, ``y`` along updip, ``z`` - normal. If ``None``
            is given, the length of the dislocation vector is plotted
        :type component: str
        '''

        disl = self.source.get_okada_slip(time=time)

        if component:
            data = disl[:, c2disl[component]]
        else:
            data = num.linalg.norm(disl, axis=1)

        data = data.reshape(self.source.ny, self.source.nx, order='F')

        scaler = AutoScaler(mode='min-max', approx_ticks=7)
        scale = scaler.make_scale([data.min(), data.max()])

        if len(clevel) == 0:
            clevel = num.arange(scale[0] + scale[2], scale[1], scale[2])

        anchor_x, anchor_y = map_anchor[self.source.anchor]

        length, width = self._patches_to_lw()
        length, width = length[1:-1], width[1:-1]

        kwargs['colors'] = kwargs.get('colors', '#474747ff')

        self._setup(**kwargs)
        self._draw_contour(
            length, width, data=data, clevel=clevel, unit='m', **kwargs)

    def draw_source_dynamics(
            self, variable, store, deltat=None, *args, **kwargs):
        ''' Display dynamic source parameter

        Fast inspection possibility for the cumulative moment and the source
        time function approximation (assuming equal paths between different
        patches and observation point - valid for an observation point in the
        far field perpendicular to the source strike), so the cumulative moment
        rate function.

        :param variable: Dynamic parameter, which shall be plotted. Choose
            between 'moment_rate' ('stf') or 'cumulative_moment' ('moment')
        :type variable: str
        :param store: Greens function store, whose store.config.deltat defines
            the time increment between two parameter snapshots. If store is not
            given, the time increment is defined is taken from deltat.
        :type store: :py:class:`pyrocko.gf.store.Store`
        :param deltat: Time increment between two parameter snapshots. If not
            given, store.config.deltat is used to define deltat
        :type deltat: optional, float
        '''

        v = variable

        data, times = self.source.get_moment_rate(store=store, deltat=deltat)

        if v in ('moment_rate', 'stf'):
            name, unit = 'dM/dt', 'Nm/s'
        elif v in ('cumulative_moment', 'moment'):
            data = num.cumsum(data)
            name, unit = 'M', 'Nm'
        else:
            raise ValueError('No dynamic data for given variable %s found' % v)

        self._setup(xlabel='time [s]',
                    ylabel='%s / %.2g %s' % (name, data.max(), unit),
                    aspect='auto',
                    spatial_plot=False)
        self._draw_scatter(x=times, y=data/num.max(data), *args, **kwargs)
        self._is_1d = True

    def draw_patch_dynamics(
            self, variable, nx, ny, store=None, deltat=None, *args, **kwargs):
        ''' Display dynamic boundary element / patch parameter

        Fast inspection possibility for different dynamic parameter for a
        single patch / boundary element. The chosen parameter is plotted for
        the chosen patch.

        :param variable: Dynamic parameter, which shall be plotted. Choose
            between 'moment_rate' ('stf') or 'cumulative_moment' ('moment')
        :type variable: str
        :param nx: Patch index along strike (range: 0:self.source.nx - 1)
        :type nx: int
        :param nx: Patch index downdip (range: 0:self.source.ny - 1)
        :type nx: int
        :param store: Greens function store, whose store.config.deltat defines
            the time increment between two parameter snapshots. If store is not
            given, the time increment is defined is taken from deltat.
        :type store: optional, :py:class:`pyrocko.gf.store.Store`
        :param deltat: Time increment between two parameter snapshots. If not
            given, store.config.deltat is used to define deltat
        :type deltat: optional, float
        '''

        v = variable
        source = self.source
        idx = nx * source.ny + nx

        m = re.match(r'dislocation_([xyz])', v)

        if v in ('moment_rate', 'cumulative_moment', 'moment'):
            data, times = source.get_moment_rate_patches(
                store=store, deltat=deltat)
        elif 'dislocation' in v or 'slip_rate' == v:
            ddisloc, times = source.get_delta_slip(store=store, deltat=deltat)

        if v == 'moment_rate':
            data, times = source.get_moment_rate_patches(
                store=store, deltat=deltat)
            name, unit = 'dM/dt', 'Nm/s'
        elif v == 'cumulative_moment' or v == 'moment':
            data, times = source.get_moment_rate_patches(
                store=store, deltat=deltat)
            data = num.cumsum(data, axis=1)
            name, unit = 'M', 'Nm'
        elif v == 'slip_rate':
            data, times = source.get_delta_slip(store=store, deltat=deltat)
            data = num.linalg.norm(ddisloc, axis=2) / (times[1] - times[0])
            name, unit = 'du/dt', 'm/s'
        elif v == 'dislocation':
            data, times = source.get_delta_slip(store=store, deltat=deltat)
            data = num.linalg.norm(num.cumsum(data, axis=2), axis=1)
            name, unit = 'du', 'm'
        elif m:
            data, times = source.get_delta_slip(store=store, deltat=deltat)
            data = num.cumsum(data, axis=2)[:, c2disl[m.group(1)], :]
            name, unit = 'du%s' % m.group(1), 'm'
        else:
            raise ValueError('No dynamic data for given variable %s found' % v)

        self._setup(xlabel='time [s]',
                    ylabel='%s / %.2g %s' % (name, num.max(data), unit),
                    aspect='auto',
                    spatial_plot=False)
        self._draw_scatter(x=times, y=data[idx, :]/num.max(data),
                           *args, **kwargs)
        self._is_1d = True

    def finalize(self):
        if self._is_1d:
            return

        length, width = xy_to_lw(
            self.source, num.array([-1., 1.]), num.array([1., -1.]))

        self._axes.set_xlim(length)
        self._axes.set_ylim(width)

    def gcf(self):
        self.finalize()
        return self._fig

    def save(self, filename, dpi=None):
        ''' Save plot to file

        :param filename: filename and path, where the plot is stored at
        :type filename: str
        :param dpi: Resolution of the output plot [dpi]
        :type dpi: int
        '''
        self.finalize()
        self._fig.savefig(fname=filename, dpi=dpi, bbox_inches='tight')
        self._clear_all()

    def show_plot(self):
        ''' Show plot '''
        self.finalize()
        plt.show()
        self._clear_all()


def render_movie(fn_path, output_path, framerate=20):
    ''' Generate a mp4 movie based on given png files using
        `ffmpeg <https://ffmpeg.org>`_.

    Render a movie based on a set of given .png files in fn_path. All files
    must have a filename specified by ``fn_path`` (e.g. giving ``fn_path`` with
    ``/temp/f%04.png`` a valid png filename would be ``/temp/f0001.png``). The
    files must have a numbering, indicating their order in the movie.

    :param fn_path: Path and fileformat specification of the input .png files.
    :type fn_path: str
    :param output_path: Path and filename of the output ``.mp4`` movie file
    :type output_path: str
    :param deltat: Time between individual frames (``1 / framerate``) [s]
    :type deltat: optional, float

    '''
    try:
        check_call(['ffmpeg', '-loglevel', 'panic'])
    except CalledProcessError:
        pass
    except (TypeError, IOError):
        logger.warn(
            'Package ffmpeg needed for movie rendering. Please install it '
            '(e.g. on linux distr. via sudo apt-get ffmpeg) and retry.')
        return False

    try:
        check_call([
            'ffmpeg', '-loglevel', 'info', '-y',
            '-framerate', '%g' % framerate,
            '-i', fn_path,
            '-vcodec', 'libx264',
            '-preset', 'medium',
            '-tune', 'animation',
            '-pix_fmt', 'yuv420p',
            '-movflags', '+faststart',
            '-filter:v', "crop='floor(in_w/2)*2:floor(in_h/2)*2'",
            '-crf', '15',
            output_path])

        return True
    except CalledProcessError as e:
        logger.warn(e)
        return False


def render_gif(fn, output_path, loops=-1):
    ''' Generate a gif based on a given mp4 using ffmpeg

    Render a gif based on a given .mp4 movie file in ``fn`` path.

    :param fn: Path and file name of the input .mp4 file.
    :type fn: str
    :param output_path: Path and filename of the output animated gif file
    :type output_path: str
    :param loops: Number of gif repeats (loops). ``-1`` is not repetition,
        ``0`` infinite
    :type loops: optional, integer
    '''

    try:
        check_call(['ffmpeg', '-loglevel', 'panic'])
    except CalledProcessError:
        pass
    except (TypeError, IOError):
        logger.warn(
            'Package ffmpeg needed for movie rendering. Please install it '
            '(e.g. on linux distr. via sudo apt-get ffmpeg.) and retry.')
        return False

    try:
        check_call([
            'ffmpeg', '-hide_banner', '-loglevel', 'panic', '-i',
            fn,
            '-filter_complex', 'palettegen[v1];[0:v][v1]paletteuse',
            '-loop', '%d' % loops,
            output_path])

        return True
    except CalledProcessError as e:
        logger.warn(e)
        return False


def rupture_movie(
        source,
        store,
        variable='dislocation',
        draw_time_contours=False,
        fn_path='.',
        prefix='',
        plot_type='map',
        deltat=None,
        framerate=None,
        store_images=False,
        render_as_gif=False,
        gif_loops=-1,
        **kwargs):
    ''' Generate a movie based on a given source for dynamic parameter

    Create a MPEG-4 movie or gif of one of the following dynamic parameters
    (``dislocation``, ``dislocation_x`` (along strike), ``dislocation_y``
    (along updip), ``dislocation_z`` (normal), ``slip_rate``, ``moment_rate``).
    If desired, the single snap shots can be stored as images as well.
    ``kwargs`` have to be given according to the chosen ``plot_type``.

    :param source: Pseudo dynamic rupture, for which the movie is produced
    :type source: :py:class:`pyrocko.gf.seismosizer.PseudoDynamicRupture`
    :param store: Greens function store, which is used for time calculation. If
        deltat is not given, it is taken from the store.config.deltat
    :type store: :py:class:`pyrocko.gf.store.Store`
    :param variable: Dynamic parameter, which shall be plotted. Choose between
        ``dislocation``, ``dislocation_x`` (along strike), ``dislocation_y``
        (along updip), ``dislocation_z`` (normal), ``slip_rate`` and
        ``moment_rate``, default ``dislocation``
    :type variable: optional, str
    :param draw_time_contours: If True, corresponding isochrones are drawn on
        the each plots
    :type draw_time_contours: optional, bool
    :param fn_path: Absolut or relative path, where movie (and optional images)
        are stored
    :type fn_path: optional, str
    :param prefix: File prefix used for the movie (and optional image) files
    :type prefix: optional, str
    :param plot_type: Choice of plot type: ``map``, ``view`` (map plot using
        :py:class:`~pyrocko.plot.dynamic_rupture.RuptureMap`
        or plane view using
        :py:class:`~pyrocko.plot.dynamic_rupture.RuptureView`)
    :type plot_type: optional, str
    :param deltat: Time between parameter snapshots. If not given,
        store.config.deltat is used to define deltat
    :type deltat: optional, float
    :param store_images: Choice to store the single .png parameter snapshots in
        fn_path or not.
    :type store_images: optional, bool
    :param render_as_gif: If True, the movie is converted into a gif. If
        ``False``, the movie is returned as mp4
    :type render_as_gif: optional, bool
    :param gif_loops: If ``render_as_gif`` is ``True``, a gif with gif_loops
        number of loops (repetitions) is returned.
        ``-1`` is no repetition, ``0`` infinite.
    :type gif_loops: optional, integer
    '''

    v = variable
    assert plot_type in ('map', 'view')

    if not source.patches:
        source.discretize_patches(store, interpolation='multilinear')

    if source.coef_mat is None:
        source.calc_coef_mat()

    prefix = prefix or v
    deltat = deltat or store.config.deltat
    framerate = max(framerate or int(1./deltat), 1)

    if v == 'moment_rate':
        data, times = source.get_moment_rate_patches(deltat=deltat)
        name, unit = 'dM/dt', 'Nm/s'
    elif 'dislocation' in v or 'slip_rate' == v:
        ddisloc, times = source.get_delta_slip(deltat=deltat)
    else:
        raise ValueError('No dynamic data for given variable %s found' % v)

    deltat = times[1] - times[0]

    m = re.match(r'dislocation_([xyz])', v)
    if m:
        data = num.cumsum(ddisloc, axis=1)[:, :, c2disl[m.group(1)]]
        name, unit = 'du%s' % m.group(1), 'm'
    elif v == 'dislocation':
        data = num.linalg.norm(num.cumsum(ddisloc, axis=1), axis=2)
        name, unit = 'du', 'm'
    elif v == 'slip_rate':
        data = num.linalg.norm(ddisloc, axis=2) / deltat
        name, unit = 'du/dt', 'm/s'

    if plot_type == 'map':
        plt_base = RuptureMap
    elif plot_type == 'view':
        plt_base = RuptureView
    else:
        raise AttributeError('invalid type: %s' % plot_type)

    attrs_base = get_kwargs(plt_base)
    kwargs_base = dict([k for k in kwargs.items() if k[0] in attrs_base])
    kwargs_plt = dict([k for k in kwargs.items() if k[0] not in kwargs_base])

    if 'clim' in kwargs_plt:
        data = num.clip(data, kwargs_plt['clim'][0], kwargs_plt['clim'][1])
    else:
        kwargs_plt['clim'] = [num.min(data), num.max(data)]

    if 'label' not in kwargs_plt:
        vmax = num.max(num.abs(kwargs_plt['clim']))
        data /= vmax

        kwargs_plt['label'] = '%s / %.2g %s' % (name, vmax, unit)
        kwargs_plt['clim'] = [i / vmax for i in kwargs_plt['clim']]

    with tempfile.TemporaryDirectory(suffix='pyrocko') as temp_path:
        fns_temp = [op.join(temp_path, 'f%09d.png' % (it + 1))
                    for it, _ in enumerate(times)]
        fn_temp_path = op.join(temp_path, 'f%09d.png')

        for it, (t, ft) in enumerate(zip(times, fns_temp)):
            plot_data = data[:, it]

            plt = plt_base(source=source, **kwargs_base)
            plt.draw_dynamic_data(plot_data, **kwargs_plt)
            plt.draw_nucleation_point()

            if draw_time_contours:
                plt.draw_time_contour(store, clevel=[t])

            plt.save(ft)

        fn_mp4 = op.join(temp_path, 'movie.mp4')
        return_code = render_movie(
            fn_temp_path,
            output_path=fn_mp4,
            framerate=framerate)

        if render_as_gif and return_code:
            render_gif(fn=fn_mp4, output_path=op.join(
                fn_path, '%s_%s_gif.gif' % (prefix, plot_type)),
                loops=gif_loops)

        elif return_code:
            shutil.move(fn_mp4, op.join(
                fn_path, '%s_%s_movie.mp4' % (prefix, plot_type)))

        else:
            logger.error('ffmpeg failed. Exit')

        if store_images:
            fns = [op.join(fn_path, '%s_%s_%g.png' % (prefix, plot_type, t))
                   for t in times]

            for ft, f in zip(fns_temp, fns):
                shutil.move(ft, f)


__all__ = [
    'make_colormap',
    'clear_temp',
    'xy_to_latlon',
    'xy_to_lw',
    'SourceError',
    'RuptureMap',
    'RuptureView',
    'rupture_movie',
    'render_movie']
