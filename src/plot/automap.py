# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, print_function

import math
import random
import logging

try:
    from StringIO import StringIO as BytesIO
except ImportError:
    from io import BytesIO

import numpy as num

from pyrocko.guts import (Object, Float, Bool, Int, Tuple, String, List,
                          Unicode, Dict)
from pyrocko.guts_array import Array
from pyrocko.dataset import topo
from pyrocko import orthodrome as od
from . import gmtpy

try:
    newstr = unicode
except NameError:
    newstr = str

points_in_region = od.points_in_region

logger = logging.getLogger('pyrocko.plot.automap')

earthradius = 6371000.0
r2d = 180./math.pi
d2r = 1./r2d
km = 1000.
d2m = d2r*earthradius
m2d = 1./d2m
cm = gmtpy.cm


def darken(c, f=0.7):
    return (c[0]*f, c[1]*f, c[2]*f)


def corners(lon, lat, w, h):
    ll_lat, ll_lon = od.ne_to_latlon(lat, lon, -0.5*h, -0.5*w)
    ur_lat, ur_lon = od.ne_to_latlon(lat, lon, 0.5*h, 0.5*w)
    return ll_lon, ll_lat, ur_lon, ur_lat


def extent(lon, lat, w, h, n):
    x = num.linspace(-0.5*w, 0.5*w, n)
    y = num.linspace(-0.5*h, 0.5*h, n)
    slats, slons = od.ne_to_latlon(lat, lon, y[0], x)
    nlats, nlons = od.ne_to_latlon(lat, lon, y[-1], x)
    south = slats.min()
    north = nlats.max()

    wlats, wlons = od.ne_to_latlon(lat, lon, y, x[0])
    elats, elons = od.ne_to_latlon(lat, lon, y, x[-1])
    elons = num.where(elons < wlons, elons + 360., elons)

    if elons.max() - elons.min() > 180 or wlons.max() - wlons.min() > 180.:
        west = -180.
        east = 180.
    else:
        west = wlons.min()
        east = elons.max()

    return topo.positive_region((west, east, south, north))


class NoTopo(Exception):
    pass


class OutOfBounds(Exception):
    pass


class FloatTile(Object):
    xmin = Float.T()
    ymin = Float.T()
    dx = Float.T()
    dy = Float.T()
    data = Array.T(shape=(None, None), dtype=float, serialize_as='table')

    def __init__(self, xmin, ymin, dx, dy, data):
        Object.__init__(self, init_props=False)
        self.xmin = float(xmin)
        self.ymin = float(ymin)
        self.dx = float(dx)
        self.dy = float(dy)
        self.data = data
        self._set_maxes()

    def _set_maxes(self):
        self.ny, self.nx = self.data.shape
        self.xmax = self.xmin + (self.nx-1) * self.dx
        self.ymax = self.ymin + (self.ny-1) * self.dy

    def x(self):
        return self.xmin + num.arange(self.nx) * self.dx

    def y(self):
        return self.ymin + num.arange(self.ny) * self.dy

    def get(self, x, y):
        ix = int(round((x - self.xmin) / self.dx))
        iy = int(round((y - self.ymin) / self.dy))
        if 0 <= ix < self.nx and 0 <= iy < self.ny:
            return self.data[iy, ix]
        else:
            raise OutOfBounds()


class City(Object):
    def __init__(self, name, lat, lon, population=None, asciiname=None):
        name = newstr(name)
        lat = float(lat)
        lon = float(lon)
        if asciiname is None:
            asciiname = name.encode('ascii', errors='replace')

        if population is None:
            population = 0
        else:
            population = int(population)

        Object.__init__(self, name=name, lat=lat, lon=lon,
                        population=population, asciiname=asciiname)

    name = Unicode.T()
    lat = Float.T()
    lon = Float.T()
    population = Int.T()
    asciiname = String.T()


class Map(Object):
    lat = Float.T(optional=True)
    lon = Float.T(optional=True)
    radius = Float.T(optional=True)
    width = Float.T(default=20.)
    height = Float.T(default=14.)
    margins = List.T(Float.T())
    illuminate = Bool.T(default=True)
    skip_feature_factor = Float.T(default=0.02)
    show_grid = Bool.T(default=False)
    show_topo = Bool.T(default=True)
    show_scale = Bool.T(default=False)
    show_topo_scale = Bool.T(default=False)
    show_center_mark = Bool.T(default=False)
    show_rivers = Bool.T(default=True)
    show_plates = Bool.T(default=False)
    show_plate_velocities = Bool.T(default=False)
    show_plate_names = Bool.T(default=False)
    show_boundaries = Bool.T(default=False)
    illuminate_factor_land = Float.T(default=0.5)
    illuminate_factor_ocean = Float.T(default=0.25)
    color_wet = Tuple.T(3, Int.T(), default=(216, 242, 254))
    color_dry = Tuple.T(3, Int.T(), default=(172, 208, 165))
    color_boundaries = Tuple.T(3, Int.T(), default=(1, 1, 1))
    topo_resolution_min = Float.T(
        default=40.,
        help='minimum resolution of topography [dpi]')
    topo_resolution_max = Float.T(
        default=200.,
        help='maximum resolution of topography [dpi]')
    replace_topo_color_only = FloatTile.T(
        optional=True,
        help='replace topo color while keeping topographic shading')
    topo_cpt_wet = String.T(default='light_sea')
    topo_cpt_dry = String.T(default='light_land')
    axes_layout = String.T(optional=True)
    custom_cities = List.T(City.T())
    gmt_config = Dict.T(String.T(), String.T())
    comment = String.T(optional=True)
    approx_ticks = Int.T(default=4)

    def __init__(self, gmtversion='newest', **kwargs):
        Object.__init__(self, **kwargs)
        self._gmt = None
        self._scaler = None
        self._widget = None
        self._corners = None
        self._wesn = None
        self._minarea = None
        self._coastline_resolution = None
        self._rivers = None
        self._dems = None
        self._have_topo_land = None
        self._have_topo_ocean = None
        self._jxyr = None
        self._prep_topo_have = None
        self._labels = []
        self._area_labels = []
        self._gmtversion = gmtversion

    def save(self, outpath, resolution=75., oversample=2., size=None,
             width=None, height=None, psconvert=False, crop_eps_mode=False):

        '''
        Save the image.

        Save the image to ``outpath``. The format is determined by the filename
        extension. Formats are handled as follows: ``'.eps'`` and ``'.ps'``
        produce EPS and PS, respectively, directly with GMT. If the file name
        ends with ``'.pdf'``, GMT output is fed through ``gmtpy-epstopdf`` to
        create a PDF file. For any other filename extension, output is first
        converted to PDF with ``gmtpy-epstopdf``, then with ``pdftocairo`` to
        PNG with a resolution oversampled by the factor ``oversample`` and
        finally the PNG is downsampled and converted to the target format with
        ``convert``. The resolution of rasterized target image can be
        controlled either by ``resolution`` in DPI or by specifying ``width``
        or ``height`` or ``size``, where the latter fits the image into a
        square with given side length. To save transparency use
        ``psconvert=True``. To crop the output image with a rectangle to the
        nearest non-white element set ``crop_eps_mode=True``.
        '''

        gmt = self.gmt
        self.draw_labels()
        self.draw_axes()
        if self.show_topo and self.show_topo_scale:
            self._draw_topo_scale()

        gmt.save(outpath, resolution=resolution, oversample=oversample,
                 crop_eps_mode=crop_eps_mode,
                 size=size, width=width, height=height, psconvert=psconvert)

    @property
    def scaler(self):
        if self._scaler is None:
            self._setup_geometry()

        return self._scaler

    @property
    def wesn(self):
        if self._wesn is None:
            self._setup_geometry()

        return self._wesn

    @property
    def widget(self):
        if self._widget is None:
            self._setup()

        return self._widget

    @property
    def layout(self):
        if self._layout is None:
            self._setup()

        return self._layout

    @property
    def jxyr(self):
        if self._jxyr is None:
            self._setup()

        return self._jxyr

    @property
    def pxyr(self):
        if self._pxyr is None:
            self._setup()

        return self._pxyr

    @property
    def gmt(self):
        if self._gmt is None:
            self._setup()

        if self._have_topo_ocean is None:
            self._draw_background()

        return self._gmt

    def _setup(self):
        if not self._widget:
            self._setup_geometry()

        self._setup_lod()
        self._setup_gmt()

    def _setup_geometry(self):
        wpage, hpage = self.width, self.height
        ml, mr, mt, mb = self._expand_margins()
        wpage -= ml + mr
        hpage -= mt + mb

        wreg = self.radius * 2.0
        hreg = self.radius * 2.0
        if wpage >= hpage:
            wreg *= wpage/hpage
        else:
            hreg *= hpage/wpage

        self._wreg = wreg
        self._hreg = hreg

        self._corners = corners(self.lon, self.lat, wreg, hreg)
        west, east, south, north = extent(self.lon, self.lat, wreg, hreg, 10)

        x, y, z = ((west, east), (south, north), (-6000., 4500.))

        xax = gmtpy.Ax(mode='min-max', approx_ticks=self.approx_ticks)
        yax = gmtpy.Ax(mode='min-max', approx_ticks=self.approx_ticks)
        zax = gmtpy.Ax(mode='min-max', inc=1000., label='Height',
                       scaled_unit='km', scaled_unit_factor=0.001)

        scaler = gmtpy.ScaleGuru(data_tuples=[(x, y, z)], axes=(xax, yax, zax))

        par = scaler.get_params()

        west = par['xmin']
        east = par['xmax']
        south = par['ymin']
        north = par['ymax']

        self._wesn = west, east, south, north
        self._scaler = scaler

    def _setup_lod(self):
        w, e, s, n = self._wesn
        if self.radius > 1500.*km:
            coastline_resolution = 'i'
            rivers = False
        else:
            coastline_resolution = 'f'
            rivers = True

        self._minarea = (self.skip_feature_factor * self.radius/km)**2

        self._coastline_resolution = coastline_resolution
        self._rivers = rivers

        self._prep_topo_have = {}
        self._dems = {}

        cm2inch = gmtpy.cm/gmtpy.inch

        dmin = 2.0 * self.radius * m2d / (self.topo_resolution_max *
                                          (self.height * cm2inch))
        dmax = 2.0 * self.radius * m2d / (self.topo_resolution_min *
                                          (self.height * cm2inch))

        for k in ['ocean', 'land']:
            self._dems[k] = topo.select_dem_names(k, dmin, dmax, self._wesn)
            if self._dems[k]:
                logger.debug('using topography dataset %s for %s'
                             % (','.join(self._dems[k]), k))

    def _expand_margins(self):
        if len(self.margins) == 0 or len(self.margins) > 4:
            ml = mr = mt = mb = 2.0
        elif len(self.margins) == 1:
            ml = mr = mt = mb = self.margins[0]
        elif len(self.margins) == 2:
            ml = mr = self.margins[0]
            mt = mb = self.margins[1]
        elif len(self.margins) == 4:
            ml, mr, mt, mb = self.margins

        return ml, mr, mt, mb

    def _setup_gmt(self):
        w, h = self.width, self.height
        scaler = self._scaler

        if gmtpy.is_gmt5(self._gmtversion):
            gmtconf = dict(
                MAP_TICK_PEN_PRIMARY='1.25p',
                MAP_TICK_PEN_SECONDARY='1.25p',
                MAP_TICK_LENGTH_PRIMARY='0.2c',
                MAP_TICK_LENGTH_SECONDARY='0.6c',
                FONT_ANNOT_PRIMARY='12p,1,black',
                FONT_LABEL='12p,1,black',
                PS_CHAR_ENCODING='ISOLatin1+',
                MAP_FRAME_TYPE='fancy',
                FORMAT_GEO_MAP='D',
                PS_MEDIA='Custom_%ix%i' % (
                    w*gmtpy.cm,
                    h*gmtpy.cm),
                PS_PAGE_ORIENTATION='portrait',
                MAP_GRID_PEN_PRIMARY='thinnest,0/50/0',
                MAP_ANNOT_OBLIQUE='6')
        else:
            gmtconf = dict(
                TICK_PEN='1.25p',
                TICK_LENGTH='0.2c',
                ANNOT_FONT_PRIMARY='1',
                ANNOT_FONT_SIZE_PRIMARY='12p',
                LABEL_FONT='1',
                LABEL_FONT_SIZE='12p',
                CHAR_ENCODING='ISOLatin1+',
                BASEMAP_TYPE='fancy',
                PLOT_DEGREE_FORMAT='D',
                PAPER_MEDIA='Custom_%ix%i' % (
                    w*gmtpy.cm,
                    h*gmtpy.cm),
                GRID_PEN_PRIMARY='thinnest/0/50/0',
                DOTS_PR_INCH='1200',
                OBLIQUE_ANNOTATION='6')

        gmtconf.update(
            (k.upper(), v) for (k, v) in self.gmt_config.items())

        gmt = gmtpy.GMT(config=gmtconf, version=self._gmtversion)

        layout = gmt.default_layout()

        layout.set_fixed_margins(*[x*cm for x in self._expand_margins()])

        widget = layout.get_widget()
        widget['P'] = widget['J']
        widget['J'] = ('-JA%g/%g' % (self.lon, self.lat)) + '/%(width)gp'
        scaler['R'] = '-R%g/%g/%g/%gr' % self._corners

        # aspect = gmtpy.aspect_for_projection(
        #     gmt.installation['version'], *(widget.J() + scaler.R()))

        aspect = self._map_aspect(jr=widget.J() + scaler.R())
        widget.set_aspect(aspect)

        self._gmt = gmt
        self._layout = layout
        self._widget = widget
        self._jxyr = self._widget.JXY() + self._scaler.R()
        self._pxyr = self._widget.PXY() + [
            '-R%g/%g/%g/%g' % (0, widget.width(), 0, widget.height())]
        self._have_drawn_axes = False
        self._have_drawn_labels = False

    def _draw_background(self):
        self._have_topo_land = False
        self._have_topo_ocean = False
        if self.show_topo:
            self._have_topo = self._draw_topo()

        self._draw_basefeatures()

    def _get_topo_tile(self, k):
        t = None
        demname = None
        for dem in self._dems[k]:
            t = topo.get(dem, self._wesn)
            demname = dem
            if t is not None:
                break

        if not t:
            raise NoTopo()

        return t, demname

    def _prep_topo(self, k):
        gmt = self._gmt
        t, demname = self._get_topo_tile(k)

        if demname not in self._prep_topo_have:

            grdfile = gmt.tempfilename()

            is_flat = num.all(t.data[0] == t.data)

            gmtpy.savegrd(
                t.x(), t.y(), t.data, filename=grdfile, naming='lonlat')

            if self.illuminate and not is_flat:
                if k == 'ocean':
                    factor = self.illuminate_factor_ocean
                else:
                    factor = self.illuminate_factor_land

                ilumfn = gmt.tempfilename()
                gmt.grdgradient(
                    grdfile,
                    N='e%g' % factor,
                    A=-45,
                    G=ilumfn,
                    out_discard=True)

                ilumargs = ['-I%s' % ilumfn]
            else:
                ilumargs = []

            if self.replace_topo_color_only:
                t2 = self.replace_topo_color_only
                grdfile2 = gmt.tempfilename()

                gmtpy.savegrd(
                    t2.x(), t2.y(), t2.data, filename=grdfile2,
                    naming='lonlat')

                if gmt.is_gmt5():
                    gmt.grdsample(
                        grdfile2,
                        G=grdfile,
                        n='l',
                        I='%g/%g' % (t.dx, t.dy),  # noqa
                        R=grdfile,
                        out_discard=True)
                else:
                    gmt.grdsample(
                        grdfile2,
                        G=grdfile,
                        Q='l',
                        I='%g/%g' % (t.dx, t.dy),  # noqa
                        R=grdfile,
                        out_discard=True)

                gmt.grdmath(
                    grdfile, '0.0', 'AND', '=', grdfile2,
                    out_discard=True)

                grdfile = grdfile2

            self._prep_topo_have[demname] = grdfile, ilumargs

        return self._prep_topo_have[demname]

    def _draw_topo(self):
        widget = self._widget
        scaler = self._scaler
        gmt = self._gmt
        cres = self._coastline_resolution
        minarea = self._minarea

        JXY = widget.JXY()
        R = scaler.R()

        try:
            grdfile, ilumargs = self._prep_topo('ocean')
            gmt.pscoast(D=cres, S='c', A=minarea, *(JXY+R))
            gmt.grdimage(grdfile, C=topo.cpt(self.topo_cpt_wet),
                         *(ilumargs+JXY+R))
            gmt.pscoast(Q=True, *(JXY+R))
            self._have_topo_ocean = True
        except NoTopo:
            self._have_topo_ocean = False

        try:
            grdfile, ilumargs = self._prep_topo('land')
            gmt.pscoast(D=cres, G='c', A=minarea, *(JXY+R))
            gmt.grdimage(grdfile, C=topo.cpt(self.topo_cpt_dry),
                         *(ilumargs+JXY+R))
            gmt.pscoast(Q=True, *(JXY+R))
            self._have_topo_land = True
        except NoTopo:
            self._have_topo_land = False

    def _draw_topo_scale(self, label='Elevation [km]'):
        dry = read_cpt(topo.cpt(self.topo_cpt_dry))
        wet = read_cpt(topo.cpt(self.topo_cpt_wet))
        combi = cpt_merge_wet_dry(wet, dry)
        for level in combi.levels:
            level.vmin /= km
            level.vmax /= km

        topo_cpt = self.gmt.tempfilename() + '.cpt'
        write_cpt(combi, topo_cpt)

        (w, h), (xo, yo) = self.widget.get_size()
        self.gmt.psscale(
            D='%gp/%gp/%gp/%gph' % (xo + 0.5*w, yo - 2.0*gmtpy.cm, w,
                                    0.5*gmtpy.cm),
            C=topo_cpt,
            B='1:%s:' % label)

    def _draw_basefeatures(self):
        gmt = self._gmt
        cres = self._coastline_resolution
        rivers = self._rivers
        minarea = self._minarea

        color_wet = self.color_wet
        color_dry = self.color_dry

        if self.show_rivers and rivers:
            rivers = ['-Ir/0.25p,%s' % gmtpy.color(self.color_wet)]
        else:
            rivers = []

        fill = {}
        if not self._have_topo_land:
            fill['G'] = color_dry

        if not self._have_topo_ocean:
            fill['S'] = color_wet

        if self.show_boundaries:
            fill['N'] = '1/1p,%s,%s' % (
                gmtpy.color(self.color_boundaries), 'solid')

        gmt.pscoast(
            D=cres,
            W='thinnest,%s' % gmtpy.color(darken(gmtpy.color_tup(color_dry))),
            A=minarea,
            *(rivers+self._jxyr), **fill)

        if self.show_plates:
            self.draw_plates()

    def _draw_axes(self):
        gmt = self._gmt
        scaler = self._scaler
        widget = self._widget

        if self.axes_layout is None:
            if self.lat > 0.0:
                axes_layout = 'WSen'
            else:
                axes_layout = 'WseN'
        else:
            axes_layout = self.axes_layout

        scale_km = gmtpy.nice_value(self.radius/5.) / 1000.

        if self.show_center_mark:
            gmt.psxy(
                in_rows=[[self.lon, self.lat]],
                S='c20p', W='2p,black',
                *self._jxyr)

        if self.show_grid:
            btmpl = ('%(xinc)gg%(xinc)g:%(xlabel)s:/'
                     '%(yinc)gg%(yinc)g:%(ylabel)s:')
        else:
            btmpl = '%(xinc)g:%(xlabel)s:/%(yinc)g:%(ylabel)s:'

        if self.show_scale:
            scale = 'x%gp/%gp/%g/%g/%gk' % (
                    6./7*widget.width(),
                    widget.height()/7.,
                    self.lon,
                    self.lat,
                    scale_km)
        else:
            scale = False

        gmt.psbasemap(
            B=(btmpl % scaler.get_params())+axes_layout,
            L=scale,
            *self._jxyr)

        if self.comment:
            font_size = self.gmt.label_font_size()

            _, east, south, _ = self._wesn
            if gmt.is_gmt5():
                row = [
                    1, 0,
                    '%gp,%s,%s' % (font_size, 0, 'black'), 'BR',
                    self.comment]

                farg = ['-F+f+j']
            else:
                row = [1, 0, font_size, 0, 0, 'BR', self.comment]
                farg = []

            gmt.pstext(
                in_rows=[row],
                N=True,
                R=(0, 1, 0, 1),
                D='%gp/%gp' % (-font_size*0.2, font_size*0.3),
                *(widget.PXY() + farg))

    def draw_axes(self):
        if not self._have_drawn_axes:
            self._draw_axes()
            self._have_drawn_axes = True

    def _have_coastlines(self):
        gmt = self._gmt
        cres = self._coastline_resolution
        minarea = self._minarea

        checkfile = gmt.tempfilename()

        gmt.pscoast(
            M=True,
            D=cres,
            W='thinnest,black',
            A=minarea,
            out_filename=checkfile,
            *self._jxyr)

        points = []
        with open(checkfile, 'r') as f:
            for line in f:
                ls = line.strip()
                if ls.startswith('#') or ls.startswith('>') or ls == '':
                    continue
                plon, plat = [float(x) for x in ls.split()]
                points.append((plat, plon))

        points = num.array(points, dtype=float)
        return num.any(points_in_region(points, self._wesn))

    def have_coastlines(self):
        self.gmt
        return self._have_coastlines()

    def project(self, lats, lons, jr=None):
        onepoint = False
        if isinstance(lats, float) and isinstance(lons, float):
            lats = [lats]
            lons = [lons]
            onepoint = True

        if jr is not None:
            j, r = jr
            gmt = gmtpy.GMT(version=self._gmtversion)
        else:
            j, _, _, r = self.jxyr
            gmt = self.gmt

        f = BytesIO()
        gmt.mapproject(j, r, in_columns=(lons, lats), out_stream=f, D='p')
        f.seek(0)
        data = num.loadtxt(f, ndmin=2)
        xs, ys = data.T
        if onepoint:
            xs = xs[0]
            ys = ys[0]
        return xs, ys

    def _map_box(self, jr=None):
        ll_lon, ll_lat, ur_lon, ur_lat = self._corners

        xs_corner, ys_corner = self.project(
            (ll_lat, ur_lat), (ll_lon, ur_lon), jr=jr)

        w = xs_corner[1] - xs_corner[0]
        h = ys_corner[1] - ys_corner[0]

        return w, h

    def _map_aspect(self, jr=None):
        w, h = self._map_box(jr=jr)
        return h/w

    def _draw_labels(self):
        points_taken = []
        regions_taken = []

        def no_points_in_rect(xs, ys, xmin, ymin, xmax, ymax):
            xx = not num.any(la(la(xmin < xs, xs < xmax),
                                la(ymin < ys, ys < ymax)))
            return xx

        def roverlaps(a, b):
            return (a[0] < b[2] and b[0] < a[2] and
                    a[1] < b[3] and b[1] < a[3])

        w, h = self._map_box()

        label_font_size = self.gmt.label_font_size()

        if self._labels:

            n = len(self._labels)

            lons, lats, texts, sx, sy, colors, fonts, font_sizes, \
                angles, styles = list(zip(*self._labels))

            font_sizes = [
                (font_size or label_font_size) for font_size in font_sizes]

            sx = num.array(sx, dtype=float)
            sy = num.array(sy, dtype=float)

            xs, ys = self.project(lats, lons)

            points_taken.append((xs, ys))

            dxs = num.zeros(n)
            dys = num.zeros(n)

            for i in range(n):
                dx, dy = gmtpy.text_box(
                    texts[i],
                    font=fonts[i],
                    font_size=font_sizes[i],
                    **styles[i])

                dxs[i] = dx
                dys[i] = dy

            la = num.logical_and
            anchors_ok = (
                la(xs + sx + dxs < w, ys + sy + dys < h),
                la(xs - sx - dxs > 0., ys - sy - dys > 0.),
                la(xs + sx + dxs < w, ys - sy - dys > 0.),
                la(xs - sx - dxs > 0., ys + sy + dys < h),
            )

            arects = [
                (xs, ys, xs + sx + dxs, ys + sy + dys),
                (xs - sx - dxs, ys - sy - dys, xs, ys),
                (xs, ys - sy - dys, xs + sx + dxs, ys),
                (xs - sx - dxs, ys, xs, ys + sy + dys)]

            for i in range(n):
                for ianch in range(4):
                    anchors_ok[ianch][i] &= no_points_in_rect(
                        xs, ys, *[xxx[i] for xxx in arects[ianch]])

            anchor_choices = []
            anchor_take = []
            for i in range(n):
                choices = [ianch for ianch in range(4)
                           if anchors_ok[ianch][i]]
                anchor_choices.append(choices)
                if choices:
                    anchor_take.append(choices[0])
                else:
                    anchor_take.append(None)

            def cost(anchor_take):
                noverlaps = 0
                for i in range(n):
                    for j in range(n):
                        if i != j:
                            i_take = anchor_take[i]
                            j_take = anchor_take[j]
                            if i_take is None or j_take is None:
                                continue
                            r_i = [xxx[i] for xxx in arects[i_take]]
                            r_j = [xxx[j] for xxx in arects[j_take]]
                            if roverlaps(r_i, r_j):
                                noverlaps += 1

                return noverlaps

            cur_cost = cost(anchor_take)
            imax = 30
            while cur_cost != 0 and imax > 0:
                for i in range(n):
                    for t in anchor_choices[i]:
                        anchor_take_new = list(anchor_take)
                        anchor_take_new[i] = t
                        new_cost = cost(anchor_take_new)
                        if new_cost < cur_cost:
                            anchor_take = anchor_take_new
                            cur_cost = new_cost

                imax -= 1

            while cur_cost != 0:
                for i in range(n):
                    anchor_take_new = list(anchor_take)
                    anchor_take_new[i] = None
                    new_cost = cost(anchor_take_new)
                    if new_cost < cur_cost:
                        anchor_take = anchor_take_new
                        cur_cost = new_cost
                        break

            anchor_strs = ['BL', 'TR', 'TL', 'BR']

            for i in range(n):
                ianchor = anchor_take[i]
                color = colors[i]
                if color is None:
                    color = 'black'

                if ianchor is not None:
                    regions_taken.append([xxx[i] for xxx in arects[ianchor]])

                    anchor = anchor_strs[ianchor]

                    yoff = [-sy[i], sy[i]][anchor[0] == 'B']
                    xoff = [-sx[i], sx[i]][anchor[1] == 'L']
                    if self.gmt.is_gmt5():
                        row = (
                            lons[i], lats[i],
                            '%i,%s,%s' % (font_sizes[i], fonts[i], color),
                            anchor,
                            texts[i])

                        farg = ['-F+f+j+a%g' % angles[i]]
                    else:
                        row = (
                            lons[i], lats[i],
                            font_sizes[i], angles[i], fonts[i], anchor,
                            texts[i])
                        farg = ['-G%s' % color]

                    self.gmt.pstext(
                        in_rows=[row],
                        D='%gp/%gp' % (xoff, yoff),
                        *(self.jxyr + farg),
                        **styles[i])

        if self._area_labels:

            for lons, lats, text, color, font, font_size, style in \
                    self._area_labels:

                if font_size is None:
                    font_size = label_font_size

                if color is None:
                    color = 'black'

                if self.gmt.is_gmt5():
                    farg = ['-F+f+j']
                else:
                    farg = ['-G%s' % color]

                xs, ys = self.project(lats, lons)
                dx, dy = gmtpy.text_box(
                    text, font=font, font_size=font_size, **style)

                rects = [xs-0.5*dx, ys-0.5*dy, xs+0.5*dx, ys+0.5*dy]

                locs_ok = num.ones(xs.size, dtype=num.bool)

                for iloc in range(xs.size):
                    rcandi = [xxx[iloc] for xxx in rects]

                    locs_ok[iloc] = True
                    locs_ok[iloc] &= (
                        0 < rcandi[0] and rcandi[2] < w
                        and 0 < rcandi[1] and rcandi[3] < h)

                    overlap = False
                    for r in regions_taken:
                        if roverlaps(r, rcandi):
                            overlap = True
                            break

                    locs_ok[iloc] &= not overlap

                    for xs_taken, ys_taken in points_taken:
                        locs_ok[iloc] &= no_points_in_rect(
                            xs_taken, ys_taken, *rcandi)

                        if not locs_ok[iloc]:
                            break

                rows = []
                for iloc, (lon, lat) in enumerate(zip(lons, lats)):
                    if not locs_ok[iloc]:
                        continue

                    if self.gmt.is_gmt5():
                        row = (
                            lon, lat,
                            '%i,%s,%s' % (font_size, font, color),
                            'MC',
                            text)

                    else:
                        row = (
                            lon, lat,
                            font_size, 0, font, 'MC',
                            text)

                    rows.append(row)

                    regions_taken.append([xxx[iloc] for xxx in rects])
                    break

                self.gmt.pstext(
                    in_rows=rows,
                    *(self.jxyr + farg),
                    **style)

    def draw_labels(self):
        self.gmt
        if not self._have_drawn_labels:
            self._draw_labels()
            self._have_drawn_labels = True

    def add_label(
            self, lat, lon, text,
            offset_x=5., offset_y=5.,
            color=None,
            font='1',
            font_size=None,
            angle=0,
            style={}):

        if 'G' in style:
            style = style.copy()
            color = style.pop('G')

        self._labels.append(
            (lon, lat, text, offset_x, offset_y, color, font, font_size,
             angle, style))

    def add_area_label(
            self, lat, lon, text,
            color=None,
            font='3',
            font_size=None,
            style={}):

        self._area_labels.append(
            (lon, lat, text, color, font, font_size, style))

    def cities_in_region(self):
        from pyrocko.dataset import geonames
        cities = geonames.get_cities_region(region=self.wesn, minpop=0)
        cities.extend(self.custom_cities)
        cities.sort(key=lambda x: x.population)
        return cities

    def draw_cities(self,
                    exact=None,
                    include=[],
                    exclude=[],
                    nmax_soft=10,
                    psxy_style=dict(S='s5p', G='black')):

        cities = self.cities_in_region()

        if exact is not None:
            cities = [c for c in cities if c.name in exact]
            minpop = None
        else:
            cities = [c for c in cities if c.name not in exclude]
            minpop = 10**3
            for minpop_new in [1e3, 3e3, 1e4, 3e4, 1e5, 3e5, 1e6, 3e6, 1e7]:
                cities_new = [
                    c for c in cities
                    if c.population > minpop_new or c.name in include]

                if len(cities_new) == 0 or (
                        len(cities_new) < 3 and len(cities) < nmax_soft*2):
                    break

                cities = cities_new
                minpop = minpop_new
                if len(cities) <= nmax_soft:
                    break

        if cities:
            lats = [c.lat for c in cities]
            lons = [c.lon for c in cities]

            self.gmt.psxy(
                in_columns=(lons, lats),
                *self.jxyr, **psxy_style)

            for c in cities:
                try:
                    text = c.name.encode('iso-8859-1').decode('iso-8859-1')
                except UnicodeEncodeError:
                    text = c.asciiname

                self.add_label(c.lat, c.lon, text)

        self._cities_minpop = minpop

    def add_stations(self, stations, psxy_style=dict()):

        default_psxy_style = {
            'S': 't8p',
            'G': 'black'
        }
        default_psxy_style.update(psxy_style)

        lats, lons = zip(*[s.effective_latlon for s in stations])

        self.gmt.psxy(
            in_columns=(lons, lats),
            *self.jxyr, **default_psxy_style)

        for station in stations:
            self.add_label(
                station.effective_lat,
                station.effective_lon,
                '.'.join(x for x in (station.network, station.station) if x))

    def add_kite_scene(self, scene):
        tile = FloatTile(
            scene.frame.llLon,
            scene.frame.llLat,
            scene.frame.dLon,
            scene.frame.dLat,
            scene.displacement)

        return tile

    def add_gnss_campaign(self, campaign, psxy_style=None, offset_scale=None,
                          labels=True, vertical=False, fontsize=10):

        stations = campaign.stations

        if offset_scale is None:
            offset_scale = num.zeros(campaign.nstations)
            for ista, sta in enumerate(stations):
                for comp in sta.components.values():
                    offset_scale[ista] += comp.shift
            offset_scale = num.sqrt(offset_scale**2).max()

        size = math.sqrt(self.height**2 + self.width**2)
        scale = (size/10.) / offset_scale
        logger.debug('GNSS: Using offset scale %f, map scale %f',
                     offset_scale, scale)

        lats, lons = zip(*[s.effective_latlon for s in stations])

        if vertical:
            rows = [[lons[ista], lats[ista],
                    0., -s.up.shift,
                    (s.east.sigma + s.north.sigma) if s.east.sigma else 0.,
                    s.up.sigma, 0.,
                    s.code if labels else None]
                    for ista, s in enumerate(stations)
                    if s.up is not None]

        else:
            rows = [[lons[ista], lats[ista],
                     -s.east.shift, -s.north.shift,
                     s.east.sigma, s.north.sigma, s.correlation_ne,
                     s.code if labels else None]
                    for ista, s in enumerate(stations)
                    if s.east is not None or s.north is not None]

        default_psxy_style = {
            'h': 0,
            'W': '2p,black',
            'A': '+p2p,black+b+a40',
            'G': 'black',
            'L': True,
            'S': 'e%dc/0.95/%d' % (scale, fontsize),
        }

        if not labels:
            for row in rows:
                row.pop(-1)

        if psxy_style is not None:
            default_psxy_style.update(psxy_style)

        self.gmt.psvelo(
            in_rows=rows,
            *self.jxyr,
            **default_psxy_style)

    def draw_plates(self):
        from pyrocko.dataset import tectonics

        neast = 20
        nnorth = max(1, int(round(num.round(self._hreg/self._wreg * neast))))
        norths = num.linspace(-self._hreg*0.5, self._hreg*0.5, nnorth)
        easts = num.linspace(-self._wreg*0.5, self._wreg*0.5, neast)
        norths2 = num.repeat(norths, neast)
        easts2 = num.tile(easts, nnorth)
        lats, lons = od.ne_to_latlon(
            self.lat, self.lon, norths2, easts2)

        bird = tectonics.PeterBird2003()
        plates = bird.get_plates()

        color_plates = gmtpy.color('aluminium5')
        color_velocities = gmtpy.color('skyblue1')
        color_velocities_lab = gmtpy.color(darken(gmtpy.color_tup('skyblue1')))

        points = num.vstack((lats, lons)).T
        used = []
        for plate in plates:
            mask = plate.contains_points(points)
            if num.any(mask):
                used.append((plate, mask))

        if len(used) > 1:

            candi_fixed = {}

            label_data = []
            for plate, mask in used:

                mean_north = num.mean(norths2[mask])
                mean_east = num.mean(easts2[mask])
                iorder = num.argsort(num.sqrt(
                        (norths2[mask] - mean_north)**2 +
                        (easts2[mask] - mean_east)**2))

                lat_candis = lats[mask][iorder]
                lon_candis = lons[mask][iorder]

                candi_fixed[plate.name] = lat_candis.size

                label_data.append((
                    lat_candis, lon_candis, plate, color_plates))

            boundaries = bird.get_boundaries()

            size = 1.

            psxy_kwargs = []

            for boundary in boundaries:
                if num.any(points_in_region(boundary.points, self._wesn)):
                    for typ, part in boundary.split_types(
                            [['SUB'],
                             # ['OSR', 'OTF', 'OCB', 'CTF', 'CCB', 'CRB']]):
                             ['OSR', 'CRB'],
                             ['OTF', 'CTF'],
                             ['OCB', 'CCB']]):

                        lats, lons = part.T

                        kwargs = {}

                        kwargs['in_columns'] = (lons, lats)
                        kwargs['W'] = '%gp,%s' % (size, color_plates)

                        if typ[0] == 'SUB':
                            if boundary.kind == '\\':
                                kwargs['S'] = 'f%g/%gp+t+r' % (
                                    0.45*size, 3.*size)
                            elif boundary.kind == '/':
                                kwargs['S'] = 'f%g/%gp+t+l' % (
                                    0.45*size, 3.*size)

                            kwargs['G'] = color_plates

                        elif typ[0] in ['OSR', 'CRB']:
                            kwargs_bg = {}
                            kwargs_bg['in_columns'] = (lons, lats)
                            kwargs_bg['W'] = '%gp,%s' % (
                                size * 3, color_plates)
                            psxy_kwargs.append(kwargs_bg)

                            kwargs['W'] = '%gp,%s' % (size * 2, 'white')

                        psxy_kwargs.append(kwargs)

                        if boundary.kind == '\\':
                            if boundary.plate_name2 in candi_fixed:
                                candi_fixed[boundary.plate_name2] += \
                                    neast*nnorth

                        elif boundary.kind == '/':
                            if boundary.plate_name1 in candi_fixed:
                                candi_fixed[boundary.plate_name1] += \
                                    neast*nnorth

            candi_fixed = [name for name in sorted(
                list(candi_fixed.keys()), key=lambda name: -candi_fixed[name])]

            candi_fixed.append(None)

            gsrm = tectonics.GSRM1()

            for name in candi_fixed:
                if name not in gsrm.plate_names() \
                        and name not in gsrm.plate_alt_names():

                    continue

                lats, lons, vnorth, veast, vnorth_err, veast_err, corr = \
                    gsrm.get_velocities(name, region=self._wesn)

                fixed_plate_name = name

                if self.show_plate_velocities:
                    self.gmt.psvelo(
                        in_columns=(
                            lons, lats, veast, vnorth, veast_err, vnorth_err,
                            corr),
                        W='0.25p,%s' % color_velocities,
                        A='9p+e+g%s' % color_velocities,
                        S='e0.2p/0.95/10',
                        *self.jxyr)

                    for _ in range(len(lons) // 50 + 1):
                        ii = random.randint(0, len(lons)-1)
                        v = math.sqrt(vnorth[ii]**2 + veast[ii]**2)
                        self.add_label(
                            lats[ii], lons[ii], '%.0f' % v,
                            font_size=0.7*self.gmt.label_font_size(),
                            style=dict(
                                G=color_velocities_lab))

                    break

            if self.show_plate_names:
                for (lat_candis, lon_candis, plate, color) in label_data:
                    full_name = bird.full_name(plate.name)
                    if plate.name == fixed_plate_name:
                        full_name = '@_' + full_name + '@_'

                    self.add_area_label(
                        lat_candis, lon_candis,
                        full_name,
                        color=color,
                        font='3')

            for kwargs in psxy_kwargs:
                self.gmt.psxy(*self.jxyr, **kwargs)


def rand(mi, ma):
    mi = float(mi)
    ma = float(ma)
    return random.random() * (ma-mi) + mi


def split_region(region):
    west, east, south, north = topo.positive_region(region)
    if east > 180:
        return [(west, 180., south, north),
                (-180., east-360., south, north)]
    else:
        return [region]


class CPTLevel(Object):
    vmin = Float.T()
    vmax = Float.T()
    color_min = Tuple.T(3, Float.T())
    color_max = Tuple.T(3, Float.T())


class CPT(Object):
    color_below = Tuple.T(3, Float.T(), optional=True)
    color_above = Tuple.T(3, Float.T(), optional=True)
    color_nan = Tuple.T(3, Float.T(), optional=True)
    levels = List.T(CPTLevel.T())

    def scale(self, vmin, vmax):
        vmin_old, vmax_old = self.levels[0].vmin, self.levels[-1].vmax
        for level in self.levels:
            level.vmin = (level.vmin - vmin_old) / (vmax_old - vmin_old) * \
                (vmax - vmin) + vmin
            level.vmax = (level.vmax - vmin_old) / (vmax_old - vmin_old) * \
                (vmax - vmin) + vmin

    def discretize(self, nlevels):
        colors = []
        vals = []
        for level in self.levels:
            vals.append(level.vmin)
            vals.append(level.vmax)
            colors.append(level.color_min)
            colors.append(level.color_max)

        r, g, b = num.array(colors, dtype=float).T
        vals = num.array(vals, dtype=float)

        vmin, vmax = self.levels[0].vmin, self.levels[-1].vmax
        x = num.linspace(vmin, vmax, nlevels+1)
        rd = num.interp(x, vals, r)
        gd = num.interp(x, vals, g)
        bd = num.interp(x, vals, b)

        levels = []
        for ilevel in range(nlevels):
            color = (
                float(0.5*(rd[ilevel]+rd[ilevel+1])),
                float(0.5*(gd[ilevel]+gd[ilevel+1])),
                float(0.5*(bd[ilevel]+bd[ilevel+1])))

            levels.append(CPTLevel(
                vmin=x[ilevel],
                vmax=x[ilevel+1],
                color_min=color,
                color_max=color))

        cpt = CPT(
            color_below=self.color_below,
            color_above=self.color_above,
            color_nan=self.color_nan,
            levels=levels)

        return cpt


class CPTParseError(Exception):
    pass


def read_cpt(filename):
    with open(filename) as f:
        color_below = None
        color_above = None
        color_nan = None
        levels = []
        try:
            for line in f:
                line = line.strip()
                toks = line.split()

                if line.startswith('#'):
                    continue

                elif line.startswith('B'):
                    color_below = tuple(map(float, toks[1:4]))

                elif line.startswith('F'):
                    color_above = tuple(map(float, toks[1:4]))

                elif line.startswith('N'):
                    color_nan = tuple(map(float, toks[1:4]))

                else:
                    values = list(map(float, line.split()))
                    vmin = values[0]
                    color_min = tuple(values[1:4])
                    vmax = values[4]
                    color_max = tuple(values[5:8])
                    levels.append(CPTLevel(
                        vmin=vmin,
                        vmax=vmax,
                        color_min=color_min,
                        color_max=color_max))

        except Exception:
            raise CPTParseError()

    return CPT(
        color_below=color_below,
        color_above=color_above,
        color_nan=color_nan,
        levels=levels)


def color_to_int(color):
    return tuple(max(0, min(255, int(round(x)))) for x in color)


def write_cpt(cpt, filename):
    with open(filename, 'w') as f:
        for level in cpt.levels:
            f.write(
                '%e %i %i %i %e %i %i %i\n' %
                ((level.vmin, ) + color_to_int(level.color_min) +
                 (level.vmax, ) + color_to_int(level.color_max)))

        if cpt.color_below:
            f.write('B %i %i %i\n' % color_to_int(cpt.color_below))

        if cpt.color_above:
            f.write('F %i %i %i\n' % color_to_int(cpt.color_above))

        if cpt.color_nan:
            f.write('N %i %i %i\n' % color_to_int(cpt.color_nan))


def cpt_merge_wet_dry(wet, dry):
    levels = []
    for level in wet.levels:
        if level.vmin < 0.:
            if level.vmax > 0.:
                level.vmax = 0.

            levels.append(level)

    for level in dry.levels:
        if level.vmax > 0.:
            if level.vmin < 0.:
                level.vmin = 0.

            levels.append(level)

    combi = CPT(
        color_below=wet.color_below,
        color_above=dry.color_above,
        color_nan=dry.color_nan,
        levels=levels)

    return combi


if __name__ == '__main__':
    from pyrocko import util
    util.setup_logging('pyrocko.automap', 'info')

    import sys
    if len(sys.argv) == 2:

        n = int(sys.argv[1])

    for i in range(n):
        m = Map(
            lat=rand(-60., 60.),
            lon=rand(-180., 180.),
            radius=math.exp(rand(math.log(500*km), math.log(3000*km))),
            width=30., height=30.,
            show_grid=True,
            show_topo=True,
            color_dry=(238, 236, 230),
            topo_cpt_wet='light_sea_uniform',
            topo_cpt_dry='light_land_uniform',
            illuminate=True,
            illuminate_factor_ocean=0.15,
            show_rivers=False,
            show_plates=True)

        m.draw_cities()
        print(m)
        m.save('map_%02i.pdf' % i)
