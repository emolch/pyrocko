#!/usr/bin/python3
import logging

import os

import numpy as num
from scipy.interpolate import RegularGridInterpolator as scrgi

from matplotlib import cm

from pyrocko import gmtpy, moment_tensor as pmt, orthodrome as pod, util
from pyrocko.plot.automap import Map
from pyrocko.gf import PseudoDynamicRupture
from pyrocko.gf.seismosizer import map_anchor

logger = logging.getLogger('pyrocko.plot.dynamic_rupture')


km = 1e3

d2m = 111180.
m2d = 1. / d2m

d2r = num.pi / 180.
r2d = 1. / d2r

gmtpy.check_have_gmt()
gmt = gmtpy.GMT()


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
    :type filename: string
    '''

    gmtpy.savegrd(lons, lats, data, filename=filename, naming='lonlat')


def _mplcmap_to_gmtcpt_code(mplcmap):
    '''
    Get gmt readable R/G/A code from a given matplotlib colormap

    :param mplcmap: Name of the demanded matplotlib colormap
    :type mplcmap: string

    :returns: Series of comma seperate R/G/B values for gmtpy usage
    :rtype: string
    '''

    cmap = cm.get_cmap(mplcmap)

    rgbas = [cmap(i) for i in num.linspace(0, 255, 256).astype(num.int64)]

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
    :param C: optional, string
    :type cmap: Name of the colormap. Colormap is stored as "my_<cmap>.cpt".
        If name is equivalent to a matplotlib colormap, R/G/B strings are
        extracted from this colormap.
    :param cmap: optional, string
    :type space: If True, the range of the colormap is broadened below vmin and
        above vmax.
    :param space: optional, bool
    '''

    from pyrocko.plot import AutoScaler

    scaler = AutoScaler(mode='min-max')
    scale = scaler.make_scale((vmin, vmax))

    incr = scale[2]
    margin = 0.

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

    l, w = (x - ax) / 2. * s.length, (y - ay) / 2. * s.width
    strike, dip = s.strike * d2r, s.dip * d2r

    northing = num.cos(strike) * l - num.cos(dip) * num.sin(strike) * w
    easting = num.sin(strike) * l + num.cos(dip) * num.cos(strike) * w

    return pod.ne_to_latlon(s.lat, s.lon, northing, easting)


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
        'factor': 1e-6},
    'dip': {
        'unit': '°',
        'factor': 1e-6},
    'vr': {
        'unit': 'km/s',
        'factor': 1e-3},
    'length': {
        'unit': 'm',
        'factor': 1e-3},
    'width': {
        'unit': 'm',
        'factor': 1e-3}
}


fonttype = 'Helvetica'


def _make_gmt_conf(fontcolor, size):
    '''
    Update different gmt parameters depending on figure size and fontcolor

    :param fontcolor: GMT readable colorcode / colorstring for the font
    :type fontcolor: string
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
        PS_CHAR_ENCODING='ISOLatin1+',
        MAP_FRAME_TYPE='fancy',
        FORMAT_GEO_MAP='D',
        PS_PAGE_ORIENTATION='portrait',
        MAP_GRID_PEN_PRIMARY='thinnest,%s' % color,
        MAP_ANNOT_OBLIQUE='6')   # ToDo


class SourceError(Exception):
    pass


class RuptureMap(Map):
    '''
    Map plotting of attributes and results of the PseudoDynamicRupture
    '''

    def __init__(
            self,
            source=None,
            fontcolor='darkslategrey',
            width=20.,
            height=14.,
            *args, **kwargs):

        size = (width, height)
        fontsize, gmt_config = _make_gmt_conf(fontcolor, size)
        margins = [
            fontsize * 0.15, num.min(size) / 200.,
            num.min(size) / 200., fontsize * 0.05]

        Map.__init__(self, margins=margins, width=width, height=height,
                     gmt_config=gmt_config,
                     *args, **kwargs)

        self.source = source
        self._fontcolor = fontcolor
        self._fontsize = fontsize

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

        if self.source__ is None:
            raise SourceError('No source given. Please define it!')

        if not isinstance(self.source__, PseudoDynamicRupture):
            raise SourceError('This function is only capable for a source of'
                              ' type: %s' % type(PseudoDynamicRupture()))

        if not self.source__.patches:
            raise TypeError('No source patches are defined. Please run'
                            '\"discretize_patches\" on your source')

        return self.source__

    @source.setter
    def source(self, source):
        self.source__ = source

    def _get_topotile(self):
        if self._dems is None:
            self._setup()

        t, _ = self._get_topo_tile('land')
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
            num.array([patch_l* source.nx])))

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

        source = self.source

        l, w = source.length, source.width

        x, y = num.unique(x), num.unique(y)
        dx, dy = x[1] - x[0], y[1] - y[0]

        if any(num.abs(num.diff(x) - dx) >= 1e-6):
            raise ValueError('Regular grid with constant spacing needed.'
                             ' Please check the x coordinates.')

        if any(num.abs(num.diff(y) - dy) >= 1e-6):
            raise ValueError('Regular grid with constant spacing needed.'
                             ' Please check the y coordinates.')

        ax, ay = map_anchor[source.anchor]

        lengths = (x - ax) / 2. * l
        widths = (y - ay) / 2. * w

        return lengths, widths

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
        :type filename: string
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
        Generate a grid file based on patch wise data.

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
        :type gridfile: string
        :param cmap: Name of the colormap, which shall be used. A .cpt-file
            "my_<cmap>.cpt" must exist
        :type cmap: string
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
        :type gridfile: string
        :param contour_int: Interval of contour lines in units of the gridfile
        :type contour_int: float
        :param anot_int: Interval of labelled contour lines in units of the
            gridfile. Must be a integer multiple of contour_int
        :type anot_int: float
        :param angle: Rotation angle of the labels [degree]
        :type angle: optional, float
        :param unit: Name of the unit in the grid file. It will be displayed
            behind the label on labelled contour lines
        :type unit: optional, string
        :param color: GMT readable color code/string of the contour lines
        :type color: optional, string
        :param style: Line style of the contour lines. If not given, solid
            lines are plotted
        :type style: optional, string
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

    def draw_colorbar(self, cmap, title='', anchor='top_right', **kwargs):
        '''
        Draw a colorbar based on a existing colormap

        :param cmap: Name of the colormap, which shall be used. A .cpt-file
            "my_<cmap>.cpt" must exist
        :type cmap: string
        :param title: Title of the colorbar
        :type title: optional, string
        :param anchor: Placement of the colorbar. Combine 'top', 'centre' and
            'bottom' with 'left', None for middle and 'right'
        :type anchor: optional, string
        '''

        b_string, c_string = 'af+l%s' % title, 'my_%s.cpt' % cmap
        a_str = cbar_anchor[anchor]

        if kwargs:
            kwargs['B'], kwargs['C'] = b_string, c_string
        else:
            kwargs = dict(B=b_string, C=c_string)

        w = self.width / 4.
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

    def draw_dynamic_data(self, data, **kwargs):
        '''
        Draw an image of any data gridded on the patches e.g dislocation

        :param data: Patchwise data grid array
        :type data: :py:class:`numpy.ndarray`
        '''

        kwargs['cmap'] = kwargs.get('cmap', 'afmhot_r')

        make_colormap(num.min(data), num.max(data),
                      cmap=kwargs['cmap'], space=True)

        tmp_grd_file = 'tmpdata.grd'
        self.patch_data_to_grid(data, tmp_grd_file)
        self.draw_image(tmp_grd_file, **kwargs)

        clear_temp(gridfiles=[tmp_grd_file], cpts=[kwargs['cmap']])

    def draw_patch_parameter(self, attribute, **kwargs):
        '''
        Draw an image of a chosen patch attribute e.g traction

        :param attribute: Patch attribute, which is plotted. All patch
            attributes can be taken (see doc of
            :py:class:`pyrocko.modelling.okada.OkadaSource) and also
            'traction', 'tx', 'ty' or 'tz' to display the length or the single
            components of the traction vector
        :type attribute: string
        '''

        a = attribute
        source = self.source

        if a == 'traction':
            data = num.linalg.norm(source.tractions, axis=1)
        elif a == 'tx':
            data = source.tractions[:, 0]
        elif a == 'ty':
            data = source.tractions[:, 1]
        elif a == 'tz':
            data = source.tractions[:, 2]
        else:
            data = source.get_patch_attribute(attribute)

        factor = 1. if 'title' in kwargs else cbar_helper[a]['factor']
        data *= factor

        kwargs['title'] = kwargs.get(
            'title',
            '%s [%s]' % (a, cbar_helper[a]['unit']))

        self.draw_dynamic_data(data, **kwargs)

    def draw_time_contour(self, store, **kwargs):
        '''
        Draw high resolved contour lines of the rupture front propgation time

        :param store: Greens function store, which is used for time calculation
        :type store: :py:class:`pyrocko.gf.store.Store`
        '''

        from pyrocko.plot import AutoScaler

        scaler = AutoScaler(mode='0-max', approx_ticks=8)

        _, points_xy, _, times = self.source.discretize_time(store)

        scale = scaler.make_scale([num.min(times), num.max(times)])

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

    def draw_point(self, lats, lons, symbol='point', size=None, **kwargs):
        '''
        Draw points at given locations

        :param lats: Point latitude coordinates [degree]
        :type lats: iterable
        :param lons: Point longitude coordinates [degree]
        :type lons: iterable
        :param symbol: Define symbol of the points
            ('star', 'circle', 'point' or 'triangle') - default is 'point'
        :type symbol: optional, string
        :param size: Size of the points in points
        :type size: optional, float
        '''

        sym_to_gmt = dict(
            star='a',
            circle='c',
            point='p',
            triangle='t')

        try:
            iterator = iter(lats)
        except TypeError:
            lats = num.array([lats])

        try:
            iterator = iter(lons)
        except TypeError:
            lons = num.array([lons])

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
        '''
        Plot the nucleation point onto the map
        '''

        nlat, nlon = xy_to_latlon(
            self.source, self.source.nucleation_x, self.source.nucleation_y)

        self.draw_point(nlat, nlon, **kwargs)
