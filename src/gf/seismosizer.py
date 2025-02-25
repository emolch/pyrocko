# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
High level synthetic seismogram synthesis.

.. _coordinate-system-names:

Coordinate systems
..................

Coordinate system names commonly used in source models.

=================  ============================================
Name               Description
=================  ============================================
``'xyz'``          northing, easting, depth in [m]
``'xy'``           northing, easting in [m]
``'latlon'``       latitude, longitude in [deg]
``'lonlat'``       longitude, latitude in [deg]
``'latlondepth'``  latitude, longitude in [deg], depth in [m]
=================  ============================================
'''

from collections import defaultdict
from functools import cmp_to_key
import time
import math
import os
import re
import logging
try:
    import resource
except ImportError:
    resource = None
from hashlib import sha1

import numpy as num
from scipy.interpolate import RegularGridInterpolator

from pyrocko.guts import (Object, Float, String, StringChoice, List,
                          Timestamp, Int, SObject, ArgumentError, Dict,
                          ValidationError, Bool)
from pyrocko.guts_array import Array

from pyrocko import moment_tensor as pmt
from pyrocko import trace, util, config, model, eikonal_ext
from pyrocko.orthodrome import ne_to_latlon
from pyrocko.model import Location
from pyrocko.modelling import OkadaSource, make_okada_coefficient_matrix, \
    okada_ext, invert_fault_dislocations_bem

from . import meta, store, ws
from .tractions import TractionField, DirectedTractions
from .targets import Target, StaticTarget, SatelliteTarget

pjoin = os.path.join

guts_prefix = 'pf'

d2r = math.pi / 180.
r2d = 180. / math.pi
km = 1e3

logger = logging.getLogger('pyrocko.gf.seismosizer')


def cmp_none_aware(a, b):
    if isinstance(a, tuple) and isinstance(b, tuple):
        for xa, xb in zip(a, b):
            rv = cmp_none_aware(xa, xb)
            if rv != 0:
                return rv

        return 0

    anone = a is None
    bnone = b is None

    if anone and bnone:
        return 0

    if anone:
        return -1

    if bnone:
        return 1

    return bool(a > b) - bool(a < b)


def xtime():
    return time.time()


class SeismosizerError(Exception):
    pass


class BadRequest(SeismosizerError):
    pass


class DuplicateStoreId(Exception):
    pass


class NoDefaultStoreSet(Exception):
    '''
    Raised, when a default store would be used but none is set.
    '''
    pass


class ConversionError(Exception):
    pass


class STFError(SeismosizerError):
    pass


class NoSuchStore(BadRequest):

    def __init__(self, store_id, store_dirs, store_superdirs, store_ids_avail):
        BadRequest.__init__(self)
        self.store_id = store_id
        self.store_dirs = store_dirs
        self.store_superdirs = store_superdirs
        self.store_ids_avail = store_ids_avail

    def __str__(self):
        lines = ['No GF store with id "%s" found.' % self.store_id]

        def add_entries(lines, name, entries):
            lines.append('  %s:' % name)
            if not entries:
                lines.append('    *empty*')
            else:
                for entry in entries:
                    lines.append('    - %s' % entry)

        add_entries(lines, 'store_superdirs searched', self.store_superdirs)
        add_entries(lines, 'store_dirs searched', self.store_dirs)
        add_entries(lines, 'store IDs available', self.store_ids_avail)
        return '\n'.join(lines)


def ufloat(s):
    units = {
        'k': 1e3,
        'M': 1e6,
    }

    factor = 1.0
    if s and s[-1] in units:
        factor = units[s[-1]]
        s = s[:-1]
        if not s:
            raise ValueError("unit without a number: '%s'" % s)

    return float(s) * factor


def ufloat_or_none(s):
    if s:
        return ufloat(s)
    else:
        return None


def int_or_none(s):
    if s:
        return int(s)
    else:
        return None


def nonzero(x, eps=1e-15):
    return abs(x) > eps


def permudef(ln, j=0):
    if j < len(ln):
        k, v = ln[j]
        for y in v:
            ln[j] = k, y
            for s in permudef(ln, j + 1):
                yield s

        ln[j] = k, v
        return
    else:
        yield ln


def arr(x):
    return num.atleast_1d(num.asarray(x))


def discretize_rect_source(deltas, deltat, time, north, east, depth,
                           strike, dip, length, width,
                           anchor, velocity=None, stf=None,
                           nucleation_x=None, nucleation_y=None,
                           decimation_factor=1, pointsonly=False,
                           plane_coords=False,
                           aggressive_oversampling=False):

    if stf is None:
        stf = STF()

    if not velocity and not pointsonly:
        raise AttributeError('velocity is required in time mode')

    mindeltagf = float(num.min(deltas))
    if velocity:
        mindeltagf = min(mindeltagf, deltat * velocity)

    ln = length
    wd = width

    if aggressive_oversampling:
        nl = int((2. / decimation_factor) * num.ceil(ln / mindeltagf)) + 1
        nw = int((2. / decimation_factor) * num.ceil(wd / mindeltagf)) + 1
    else:
        nl = int((1. / decimation_factor) * num.ceil(ln / mindeltagf)) + 1
        nw = int((1. / decimation_factor) * num.ceil(wd / mindeltagf)) + 1

    n = int(nl * nw)

    dl = ln / nl
    dw = wd / nw

    xl = num.linspace(-0.5 * (ln - dl), 0.5 * (ln - dl), nl)
    xw = num.linspace(-0.5 * (wd - dw), 0.5 * (wd - dw), nw)

    points = num.zeros((n, 3))
    points[:, 0] = num.tile(xl, nw)
    points[:, 1] = num.repeat(xw, nl)

    if nucleation_x is not None:
        dist_x = num.abs(nucleation_x - points[:, 0])
    else:
        dist_x = num.zeros(n)

    if nucleation_y is not None:
        dist_y = num.abs(nucleation_y - points[:, 1])
    else:
        dist_y = num.zeros(n)

    dist = num.sqrt(dist_x**2 + dist_y**2)
    times = dist / velocity

    anch_x, anch_y = map_anchor[anchor]

    points[:, 0] -= anch_x * 0.5 * length
    points[:, 1] -= anch_y * 0.5 * width

    if plane_coords:
        return points, dl, dw, nl, nw

    rotmat = pmt.euler_to_matrix(dip * d2r, strike * d2r, 0.0)
    points = num.dot(rotmat.T, points.T).T

    points[:, 0] += north
    points[:, 1] += east
    points[:, 2] += depth

    if pointsonly:
        return points, dl, dw, nl, nw

    xtau, amplitudes = stf.discretize_t(deltat, time)
    nt = xtau.size

    points2 = num.repeat(points, nt, axis=0)
    times2 = (times[:, num.newaxis] + xtau[num.newaxis, :]).ravel()
    amplitudes2 = num.tile(amplitudes, n)

    return points2, times2, amplitudes2, dl, dw, nl, nw


def check_rect_source_discretisation(points2, nl, nw, store):
    # We assume a non-rotated fault plane
    N_CRITICAL = 8
    points = points2.T.reshape((3, nl, nw))
    if points.size <= N_CRITICAL:
        logger.warning('RectangularSource is defined by only %d sub-sources!'
                       % points.size)
        return True

    distances = num.sqrt(
        (points[0, 0, :] - points[0, 1, :])**2 +
        (points[1, 0, :] - points[1, 1, :])**2 +
        (points[2, 0, :] - points[2, 1, :])**2)

    depths = points[2, 0, :]
    vs_profile = store.config.get_vs(
        lat=0., lon=0.,
        points=num.repeat(depths[:, num.newaxis], 3, axis=1),
        interpolation='multilinear')

    min_wavelength = vs_profile * (store.config.deltat * 2)
    if not num.all(min_wavelength > distances / 2):
        return False
    return True


def outline_rect_source(strike, dip, length, width, anchor):
    ln = length
    wd = width
    points = num.array(
        [[-0.5 * ln, -0.5 * wd, 0.],
         [0.5 * ln, -0.5 * wd, 0.],
         [0.5 * ln, 0.5 * wd, 0.],
         [-0.5 * ln, 0.5 * wd, 0.],
         [-0.5 * ln, -0.5 * wd, 0.]])

    anch_x, anch_y = map_anchor[anchor]
    points[:, 0] -= anch_x * 0.5 * length
    points[:, 1] -= anch_y * 0.5 * width

    rotmat = pmt.euler_to_matrix(dip * d2r, strike * d2r, 0.0)

    return num.dot(rotmat.T, points.T).T


def from_plane_coords(
        strike, dip, length, width, depth, x_plane_coords, y_plane_coords,
        lat=0., lon=0.,
        north_shift=0, east_shift=0,
        anchor='top', cs='xy'):

    ln = length
    wd = width
    x_abs = []
    y_abs = []
    if not isinstance(x_plane_coords, list):
        x_plane_coords = [x_plane_coords]
        y_plane_coords = [y_plane_coords]

    for x_plane, y_plane in zip(x_plane_coords, y_plane_coords):
        points = num.array(
            [[-0.5 * ln * x_plane, -0.5 * wd * y_plane, 0.],
             [0.5 * ln * x_plane, -0.5 * wd * y_plane, 0.],
             [0.5 * ln * x_plane, 0.5 * wd * y_plane, 0.],
             [-0.5 * ln * x_plane, 0.5 * wd * y_plane, 0.],
             [-0.5 * ln * x_plane, -0.5 * wd * y_plane, 0.]])

        anch_x, anch_y = map_anchor[anchor]
        points[:, 0] -= anch_x * 0.5 * length
        points[:, 1] -= anch_y * 0.5 * width

        rotmat = pmt.euler_to_matrix(dip * d2r, strike * d2r, 0.0)

        points = num.dot(rotmat.T, points.T).T
        points[:, 0] += north_shift
        points[:, 1] += east_shift
        points[:, 2] += depth
        if cs in ('latlon', 'lonlat'):
            latlon = ne_to_latlon(lat, lon,
                                  points[:, 0], points[:, 1])
            latlon = num.array(latlon).T
            x_abs.append(latlon[1:2, 1])
            y_abs.append(latlon[2:3, 0])
        if cs == 'xy':
            x_abs.append(points[1:2, 1])
            y_abs.append(points[2:3, 0])

    if cs == 'lonlat':
        return y_abs, x_abs
    else:
        return x_abs, y_abs


def points_on_rect_source(
        strike, dip, length, width, anchor,
        discretized_basesource=None, points_x=None, points_y=None):

    ln = length
    wd = width

    if isinstance(points_x, list) or isinstance(points_x, float):
        points_x = num.array([points_x])
    if isinstance(points_y, list) or isinstance(points_y, float):
        points_y = num.array([points_y])

    if discretized_basesource:
        ds = discretized_basesource

        nl_patches = ds.nl + 1
        nw_patches = ds.nw + 1

        npoints = nl_patches * nw_patches
        points = num.zeros((npoints, 3))
        ln_patches = num.array([il for il in range(nl_patches)])
        wd_patches = num.array([iw for iw in range(nw_patches)])

        points_ln =\
            2 * ((ln_patches - num.min(ln_patches)) / num.ptp(ln_patches)) - 1
        points_wd =\
            2 * ((wd_patches - num.min(wd_patches)) / num.ptp(wd_patches)) - 1

        for il in range(nl_patches):
            for iw in range(nw_patches):
                points[il * nw_patches + iw, :] = num.array([
                    points_ln[il] * ln * 0.5,
                    points_wd[iw] * wd * 0.5, 0.0])

    elif points_x.shape[0] > 0 and points_y.shape[0] > 0:
        points = num.zeros(shape=((len(points_x), 3)))
        for i, (x, y) in enumerate(zip(points_x, points_y)):
            points[i, :] = num.array(
                [x * 0.5 * ln, y * 0.5 * wd, 0.0])

    anch_x, anch_y = map_anchor[anchor]

    points[:, 0] -= anch_x * 0.5 * ln
    points[:, 1] -= anch_y * 0.5 * wd

    rotmat = pmt.euler_to_matrix(dip * d2r, strike * d2r, 0.0)

    return num.dot(rotmat.T, points.T).T


class InvalidGridDef(Exception):
    pass


class Range(SObject):
    '''
    Convenient range specification.

    Equivalent ways to sepecify the range [ 0., 1000., ... 10000. ]::

      Range('0 .. 10k : 1k')
      Range(start=0., stop=10e3, step=1e3)
      Range(0, 10e3, 1e3)
      Range('0 .. 10k @ 11')
      Range(start=0., stop=10*km, n=11)

      Range(0, 10e3, n=11)
      Range(values=[x*1e3 for x in range(11)])

    Depending on the use context, it can be possible to omit any part of the
    specification. E.g. in the context of extracting a subset of an already
    existing range, the existing range's specification values would be filled
    in where missing.

    The values are distributed with equal spacing, unless the ``spacing``
    argument is modified.  The values can be created offset or relative to an
    external base value with the ``relative`` argument if the use context
    supports this.

    The range specification can be expressed with a short string
    representation::

        'start .. stop @ num | spacing, relative'
        'start .. stop : step | spacing, relative'

    most parts of the expression can be omitted if not needed. Whitespace is
    allowed for readability but can also be omitted.
    '''

    start = Float.T(optional=True)
    stop = Float.T(optional=True)
    step = Float.T(optional=True)
    n = Int.T(optional=True)
    values = Array.T(optional=True, dtype=float, shape=(None,))

    spacing = StringChoice.T(
        choices=['lin', 'log', 'symlog'],
        default='lin',
        optional=True)

    relative = StringChoice.T(
        choices=['', 'add', 'mult'],
        default='',
        optional=True)

    pattern = re.compile(r'^((?P<start>.*)\.\.(?P<stop>[^@|:]*))?'
                         r'(@(?P<n>[^|]+)|:(?P<step>[^|]+))?'
                         r'(\|(?P<stuff>.+))?$')

    def __init__(self, *args, **kwargs):
        d = {}
        if len(args) == 1:
            d = self.parse(args[0])
        elif len(args) in (2, 3):
            d['start'], d['stop'] = [float(x) for x in args[:2]]
            if len(args) == 3:
                d['step'] = float(args[2])

        for k, v in kwargs.items():
            if k in d:
                raise ArgumentError('%s specified more than once' % k)

            d[k] = v

        SObject.__init__(self, **d)

    def __str__(self):
        def sfloat(x):
            if x is not None:
                return '%g' % x
            else:
                return ''

        if self.values:
            return ','.join('%g' % x for x in self.values)

        if self.start is None and self.stop is None:
            s0 = ''
        else:
            s0 = '%s .. %s' % (sfloat(self.start), sfloat(self.stop))

        s1 = ''
        if self.step is not None:
            s1 = [' : %g', ':%g'][s0 == ''] % self.step
        elif self.n is not None:
            s1 = [' @ %i', '@%i'][s0 == ''] % self.n

        if self.spacing == 'lin' and self.relative == '':
            s2 = ''
        else:
            x = []
            if self.spacing != 'lin':
                x.append(self.spacing)

            if self.relative != '':
                x.append(self.relative)

            s2 = ' | %s' % ','.join(x)

        return s0 + s1 + s2

    @classmethod
    def parse(cls, s):
        s = re.sub(r'\s+', '', s)
        m = cls.pattern.match(s)
        if not m:
            try:
                vals = [ufloat(x) for x in s.split(',')]
            except Exception:
                raise InvalidGridDef(
                    '"%s" is not a valid range specification' % s)

            return dict(values=num.array(vals, dtype=float))

        d = m.groupdict()
        try:
            start = ufloat_or_none(d['start'])
            stop = ufloat_or_none(d['stop'])
            step = ufloat_or_none(d['step'])
            n = int_or_none(d['n'])
        except Exception:
            raise InvalidGridDef(
                '"%s" is not a valid range specification' % s)

        spacing = 'lin'
        relative = ''

        if d['stuff'] is not None:
            t = d['stuff'].split(',')
            for x in t:
                if x in cls.spacing.choices:
                    spacing = x
                elif x and x in cls.relative.choices:
                    relative = x
                else:
                    raise InvalidGridDef(
                        '"%s" is not a valid range specification' % s)

        return dict(start=start, stop=stop, step=step, n=n, spacing=spacing,
                    relative=relative)

    def make(self, mi=None, ma=None, inc=None, base=None, eps=1e-5):
        if self.values:
            return self.values

        start = self.start
        stop = self.stop
        step = self.step
        n = self.n

        swap = step is not None and step < 0.
        if start is None:
            start = [mi, ma][swap]
        if stop is None:
            stop = [ma, mi][swap]
        if step is None and inc is not None:
            step = [inc, -inc][ma < mi]

        if start is None or stop is None:
            raise InvalidGridDef(
                'Cannot use range specification "%s" without start '
                'and stop in this context' % self)

        if step is None and n is None:
            step = stop - start

        if n is None:
            if (step < 0) != (stop - start < 0):
                raise InvalidGridDef(
                    'Range specification "%s" has inconsistent ordering '
                    '(step < 0 => stop > start)' % self)

            n = int(round((stop - start) / step)) + 1
            stop2 = start + (n - 1) * step
            if abs(stop - stop2) > eps:
                n = int(math.floor((stop - start) / step)) + 1
                stop = start + (n - 1) * step
            else:
                stop = stop2

        if start == stop:
            n = 1

        if self.spacing == 'lin':
            vals = num.linspace(start, stop, n)

        elif self.spacing in ('log', 'symlog'):
            if start > 0. and stop > 0.:
                vals = num.exp(num.linspace(num.log(start),
                                            num.log(stop), n))
            elif start < 0. and stop < 0.:
                vals = -num.exp(num.linspace(num.log(-start),
                                             num.log(-stop), n))
            else:
                raise InvalidGridDef(
                    'Log ranges should not include or cross zero '
                    '(in range specification "%s").' % self)

            if self.spacing == 'symlog':
                nvals = - vals
                vals = num.concatenate((nvals[::-1], vals))

        if self.relative in ('add', 'mult') and base is None:
            raise InvalidGridDef(
                'Cannot use relative range specification in this context.')

        vals = self.make_relative(base, vals)

        return list(map(float, vals))

    def make_relative(self, base, vals):
        if self.relative == 'add':
            vals += base

        if self.relative == 'mult':
            vals *= base

        return vals


class GridDefElement(Object):

    param = meta.StringID.T()
    rs = Range.T()

    def __init__(self, shorthand=None, **kwargs):
        if shorthand is not None:
            t = shorthand.split('=')
            if len(t) != 2:
                raise InvalidGridDef(
                    'Invalid grid specification element: %s' % shorthand)

            sp, sr = t[0].strip(), t[1].strip()

            kwargs['param'] = sp
            kwargs['rs'] = Range(sr)

        Object.__init__(self, **kwargs)

    def shorthand(self):
        return self.param + ' = ' + str(self.rs)


class GridDef(Object):

    elements = List.T(GridDefElement.T())

    def __init__(self, shorthand=None, **kwargs):
        if shorthand is not None:
            t = shorthand.splitlines()
            tt = []
            for x in t:
                x = x.strip()
                if x:
                    tt.extend(x.split(';'))

            elements = []
            for se in tt:
                elements.append(GridDef(se))

            kwargs['elements'] = elements

        Object.__init__(self, **kwargs)

    def shorthand(self):
        return '; '.join(str(x) for x in self.elements)


class Cloneable(object):
    '''
    Mix-in class for Guts objects, providing dict-like access and cloning.
    '''

    def __iter__(self):
        return iter(self.T.propnames)

    def __getitem__(self, k):
        if k not in self.keys():
            raise KeyError(k)

        return getattr(self, k)

    def __setitem__(self, k, v):
        if k not in self.keys():
            raise KeyError(k)

        return setattr(self, k, v)

    def clone(self, **kwargs):
        '''
        Make a copy of the object.

        A new object of the same class is created and initialized with the
        parameters of the object on which this method is called on. If
        ``kwargs`` are given, these are used to override any of the
        initialization parameters.
        '''

        d = dict(self)
        for k in d:
            v = d[k]
            if isinstance(v, Cloneable):
                d[k] = v.clone()

        d.update(kwargs)
        return self.__class__(**d)

    @classmethod
    def keys(cls):
        '''
        Get list of the source model's parameter names.
        '''

        return cls.T.propnames


class STF(Object, Cloneable):

    '''
    Base class for source time functions.
    '''

    def __init__(self, effective_duration=None, **kwargs):
        if effective_duration is not None:
            kwargs['duration'] = effective_duration / \
                self.factor_duration_to_effective()

        Object.__init__(self, **kwargs)

    @classmethod
    def factor_duration_to_effective(cls):
        return 1.0

    def centroid_time(self, tref):
        return tref

    @property
    def effective_duration(self):
        return self.duration * self.factor_duration_to_effective()

    def discretize_t(self, deltat, tref):
        tl = math.floor(tref / deltat) * deltat
        th = math.ceil(tref / deltat) * deltat
        if tl == th:
            return num.array([tl], dtype=float), num.ones(1)
        else:
            return (
                num.array([tl, th], dtype=float),
                num.array([th - tref, tref - tl], dtype=float) / deltat)

    def base_key(self):
        return (type(self).__name__,)


g_unit_pulse = STF()


def sshift(times, amplitudes, tshift, deltat):

    t0 = math.floor(tshift / deltat) * deltat
    t1 = math.ceil(tshift / deltat) * deltat
    if t0 == t1:
        return times, amplitudes

    amplitudes2 = num.zeros(amplitudes.size + 1, dtype=float)

    amplitudes2[:-1] += (t1 - tshift) / deltat * amplitudes
    amplitudes2[1:] += (tshift - t0) / deltat * amplitudes

    times2 = num.arange(times.size + 1, dtype=float) * \
        deltat + times[0] + t0

    return times2, amplitudes2


class BoxcarSTF(STF):

    '''
    Boxcar type source time function.

    .. figure :: /static/stf-BoxcarSTF.svg
        :width: 40%
        :align: center
        :alt: boxcar source time function
    '''

    duration = Float.T(
        default=0.0,
        help='duration of the boxcar')

    anchor = Float.T(
        default=0.0,
        help='anchor point with respect to source.time: ('
             '-1.0: left -> source duration [0, T] ~ hypocenter time, '
             ' 0.0: center -> source duration [-T/2, T/2] ~ centroid time, '
             '+1.0: right -> source duration [-T, 0] ~ rupture end time)')

    @classmethod
    def factor_duration_to_effective(cls):
        return 1.0

    def centroid_time(self, tref):
        return tref - 0.5 * self.duration * self.anchor

    def discretize_t(self, deltat, tref):
        tmin_stf = tref - self.duration * (self.anchor + 1.) * 0.5
        tmax_stf = tref + self.duration * (1. - self.anchor) * 0.5
        tmin = round(tmin_stf / deltat) * deltat
        tmax = round(tmax_stf / deltat) * deltat
        nt = int(round((tmax - tmin) / deltat)) + 1
        times = num.linspace(tmin, tmax, nt)
        amplitudes = num.ones_like(times)
        if times.size > 1:
            t_edges = num.linspace(
                tmin - 0.5 * deltat, tmax + 0.5 * deltat, nt + 1)
            t = tmin_stf + self.duration * num.array(
                [0.0, 0.0, 1.0, 1.0], dtype=float)
            f = num.array([0., 1., 1., 0.], dtype=float)
            amplitudes = util.plf_integrate_piecewise(t_edges, t, f)
            amplitudes /= num.sum(amplitudes)

        tshift = (num.sum(amplitudes * times) - self.centroid_time(tref))

        return sshift(times, amplitudes, -tshift, deltat)

    def base_key(self):
        return (type(self).__name__, self.duration, self.anchor)


class TriangularSTF(STF):

    '''
    Triangular type source time function.

    .. figure :: /static/stf-TriangularSTF.svg
        :width: 40%
        :align: center
        :alt: triangular source time function
    '''

    duration = Float.T(
        default=0.0,
        help='baseline of the triangle')

    peak_ratio = Float.T(
        default=0.5,
        help='fraction of time compared to duration, '
             'when the maximum amplitude is reached')

    anchor = Float.T(
        default=0.0,
        help='anchor point with respect to source.time: ('
             '-1.0: left -> source duration [0, T] ~ hypocenter time, '
             ' 0.0: center -> source duration [-T/2, T/2] ~ centroid time, '
             '+1.0: right -> source duration [-T, 0] ~ rupture end time)')

    @classmethod
    def factor_duration_to_effective(cls, peak_ratio=None):
        if peak_ratio is None:
            peak_ratio = cls.peak_ratio.default()

        return math.sqrt((peak_ratio**2 - peak_ratio + 1.0) * 2.0 / 3.0)

    def __init__(self, effective_duration=None, **kwargs):
        if effective_duration is not None:
            kwargs['duration'] = effective_duration / \
                self.factor_duration_to_effective(
                    kwargs.get('peak_ratio', None))

        STF.__init__(self, **kwargs)

    @property
    def centroid_ratio(self):
        ra = self.peak_ratio
        rb = 1.0 - ra
        return self.peak_ratio + (rb**2 / 3. - ra**2 / 3.) / (ra + rb)

    def centroid_time(self, tref):
        ca = self.centroid_ratio
        cb = 1.0 - ca
        if self.anchor <= 0.:
            return tref - ca * self.duration * self.anchor
        else:
            return tref - cb * self.duration * self.anchor

    @property
    def effective_duration(self):
        return self.duration * self.factor_duration_to_effective(
            self.peak_ratio)

    def tminmax_stf(self, tref):
        ca = self.centroid_ratio
        cb = 1.0 - ca
        if self.anchor <= 0.:
            tmin_stf = tref - ca * self.duration * (self.anchor + 1.)
            tmax_stf = tmin_stf + self.duration
        else:
            tmax_stf = tref + cb * self.duration * (1. - self.anchor)
            tmin_stf = tmax_stf - self.duration

        return tmin_stf, tmax_stf

    def discretize_t(self, deltat, tref):
        tmin_stf, tmax_stf = self.tminmax_stf(tref)

        tmin = round(tmin_stf / deltat) * deltat
        tmax = round(tmax_stf / deltat) * deltat
        nt = int(round((tmax - tmin) / deltat)) + 1
        if nt > 1:
            t_edges = num.linspace(
                tmin - 0.5 * deltat, tmax + 0.5 * deltat, nt + 1)
            t = tmin_stf + self.duration * num.array(
                [0.0, self.peak_ratio, 1.0], dtype=float)
            f = num.array([0., 1., 0.], dtype=float)
            amplitudes = util.plf_integrate_piecewise(t_edges, t, f)
            amplitudes /= num.sum(amplitudes)
        else:
            amplitudes = num.ones(1)

        times = num.linspace(tmin, tmax, nt)
        return times, amplitudes

    def base_key(self):
        return (
            type(self).__name__, self.duration, self.peak_ratio, self.anchor)


class HalfSinusoidSTF(STF):

    '''
    Half sinusoid type source time function.

    .. figure :: /static/stf-HalfSinusoidSTF.svg
        :width: 40%
        :align: center
        :alt: half-sinusouid source time function
    '''

    duration = Float.T(
        default=0.0,
        help='duration of the half-sinusoid (baseline)')

    anchor = Float.T(
        default=0.0,
        help='anchor point with respect to source.time: ('
             '-1.0: left -> source duration [0, T] ~ hypocenter time, '
             ' 0.0: center -> source duration [-T/2, T/2] ~ centroid time, '
             '+1.0: right -> source duration [-T, 0] ~ rupture end time)')

    exponent = Int.T(
        default=1,
        help='set to 2 to use square of the half-period sinusoidal function.')

    def __init__(self, effective_duration=None, **kwargs):
        if effective_duration is not None:
            kwargs['duration'] = effective_duration / \
                self.factor_duration_to_effective(
                    kwargs.get('exponent', 1))

        STF.__init__(self, **kwargs)

    @classmethod
    def factor_duration_to_effective(cls, exponent):
        if exponent == 1:
            return math.sqrt(3.0 * math.pi**2 - 24.0) / math.pi
        elif exponent == 2:
            return math.sqrt(math.pi**2 - 6) / math.pi
        else:
            raise ValueError('Exponent for HalfSinusoidSTF must be 1 or 2.')

    @property
    def effective_duration(self):
        return self.duration * self.factor_duration_to_effective(self.exponent)

    def centroid_time(self, tref):
        return tref - 0.5 * self.duration * self.anchor

    def discretize_t(self, deltat, tref):
        tmin_stf = tref - self.duration * (self.anchor + 1.) * 0.5
        tmax_stf = tref + self.duration * (1. - self.anchor) * 0.5
        tmin = round(tmin_stf / deltat) * deltat
        tmax = round(tmax_stf / deltat) * deltat
        nt = int(round((tmax - tmin) / deltat)) + 1
        if nt > 1:
            t_edges = num.maximum(tmin_stf, num.minimum(tmax_stf, num.linspace(
                tmin - 0.5 * deltat, tmax + 0.5 * deltat, nt + 1)))

            if self.exponent == 1:
                fint = -num.cos(
                    (t_edges - tmin_stf) * (math.pi / self.duration))

            elif self.exponent == 2:
                fint = (t_edges - tmin_stf) / self.duration \
                    - 1.0 / (2.0 * math.pi) * num.sin(
                        (t_edges - tmin_stf) * (2.0 * math.pi / self.duration))
            else:
                raise ValueError(
                    'Exponent for HalfSinusoidSTF must be 1 or 2.')

            amplitudes = fint[1:] - fint[:-1]
            amplitudes /= num.sum(amplitudes)
        else:
            amplitudes = num.ones(1)

        times = num.linspace(tmin, tmax, nt)
        return times, amplitudes

    def base_key(self):
        return (type(self).__name__, self.duration, self.anchor)


class SmoothRampSTF(STF):
    '''
    Smooth-ramp type source time function for near-field displacement.
    Based on moment function of double-couple point source proposed by [1]_.

    .. [1] W. Bruestle, G. Mueller (1983), Moment and duration of shallow
        earthquakes from Love-wave modelling for regional distances, PEPI 32,
        312-324.

    .. figure :: /static/stf-SmoothRampSTF.svg
        :width: 40%
        :alt: smooth ramp source time function
    '''
    duration = Float.T(
        default=0.0,
        help='duration of the ramp (baseline)')

    rise_ratio = Float.T(
        default=0.5,
        help='fraction of time compared to duration, '
             'when the maximum amplitude is reached')

    anchor = Float.T(
        default=0.0,
        help='anchor point with respect to source.time: ('
             '-1.0: left -> source duration ``[0, T]`` ~ hypocenter time, '
             '0.0: center -> source duration ``[-T/2, T/2]`` ~ centroid time, '
             '+1.0: right -> source duration ``[-T, 0]`` ~ rupture end time)')

    def discretize_t(self, deltat, tref):
        tmin_stf = tref - self.duration * (self.anchor + 1.) * 0.5
        tmax_stf = tref + self.duration * (1. - self.anchor) * 0.5
        tmin = round(tmin_stf / deltat) * deltat
        tmax = round(tmax_stf / deltat) * deltat
        D = round((tmax - tmin) / deltat) * deltat
        nt = int(round(D / deltat)) + 1
        times = num.linspace(tmin, tmax, nt)
        if nt > 1:
            rise_time = self.rise_ratio * self.duration
            amplitudes = num.ones_like(times)
            tp = tmin + rise_time
            ii = num.where(times <= tp)
            t_inc = times[ii]
            a = num.cos(num.pi * (t_inc - tmin_stf) / rise_time)
            b = num.cos(3 * num.pi * (t_inc - tmin_stf) / rise_time) - 1.0
            amplitudes[ii] = (9. / 16.) * (1 - a + (1. / 9.) * b)

            amplitudes /= num.sum(amplitudes)
        else:
            amplitudes = num.ones(1)

        return times, amplitudes

    def base_key(self):
        return (type(self).__name__,
                self.duration, self.rise_ratio, self.anchor)


class ResonatorSTF(STF):
    '''
    Simple resonator like source time function.

    .. math ::

        f(t) = 0 for t < 0
        f(t) = e^{-t/tau} * sin(2 * pi * f * t)


    .. figure :: /static/stf-SmoothRampSTF.svg
      :width: 40%
      :alt: smooth ramp source time function

    '''

    duration = Float.T(
        default=0.0,
        help='decay time')

    frequency = Float.T(
        default=1.0,
        help='resonance frequency')

    def discretize_t(self, deltat, tref):
        tmin_stf = tref
        tmax_stf = tref + self.duration * 3
        tmin = math.floor(tmin_stf / deltat) * deltat
        tmax = math.ceil(tmax_stf / deltat) * deltat
        times = util.arange2(tmin, tmax, deltat)
        amplitudes = num.exp(-(times - tref) / self.duration) \
            * num.sin(2.0 * num.pi * self.frequency * (times - tref))

        return times, amplitudes

    def base_key(self):
        return (type(self).__name__,
                self.duration, self.frequency)


class TremorSTF(STF):
    '''
    Oszillating source time function.

    .. math ::

        f(t) = 0 for t < -tau/2 or t > tau/2
        f(t) = cos(pi/tau*t) * sin(2 * pi * f * t)

    '''

    duration = Float.T(
        default=0.0,
        help='Tremor duration [s]')

    frequency = Float.T(
        default=1.0,
        help='Frequency [Hz]')

    def discretize_t(self, deltat, tref):
        tmin_stf = tref - 0.5 * self.duration
        tmax_stf = tref + 0.5 * self.duration
        tmin = math.floor(tmin_stf / deltat) * deltat
        tmax = math.ceil(tmax_stf / deltat) * deltat
        times = util.arange2(tmin, tmax, deltat)
        mask = num.logical_and(
            tref - 0.5 * self.duration < times,
            times < tref + 0.5 * self.duration)

        amplitudes = num.zeros_like(times)
        amplitudes[mask] = num.cos(num.pi/self.duration*(times[mask] - tref)) \
            * num.sin(2.0 * num.pi * self.frequency * (times[mask] - tref))
        amplitudes[mask] *= deltat

        return times, amplitudes

    def base_key(self):
        return (type(self).__name__,
                self.duration, self.frequency)


class SimpleLandslideSTF(STF):

    '''
    Doublepulse land-slide STF which respects conservation of momentum.
    '''

    duration_acceleration = Float.T(
        default=1.0,
        help='Duratian of the acceleration phase [s].')

    duration_deceleration = Float.T(
        default=1.0,
        help='Duration of the deceleration phase [s].')

    mute_acceleration = Bool.T(
        default=False,
        help='set acceleration to zero (for testing)')

    mute_deceleration = Bool.T(
        default=False,
        help='set acceleration to zero (for testing)')

    def discretize_t(self, deltat, tref):

        d_acc = self.duration_acceleration
        d_dec = self.duration_deceleration

        tmin_stf = tref
        tmax_stf = tref + d_acc + d_dec
        tmin = math.floor(tmin_stf / deltat) * deltat
        tmax = math.ceil(tmax_stf / deltat) * deltat
        times = util.arange2(tmin, tmax, deltat, epsilon=1e-3)

        mask_acc = num.logical_and(
            tref <= times,
            times < tref + d_acc)

        mask_dec = num.logical_and(
            tref + d_acc <= times,
            times < tref + d_acc + d_dec)

        n_acc = num.sum(mask_acc)
        if n_acc < 1:
            raise STFError(
                'SimpleLandslideSTF: `duration_acceleration` must be longer '
                'than sampling interval.')

        n_dec = num.sum(mask_dec)
        if n_dec < 1:
            raise STFError(
                'SimpleLandslideSTF: `duration_deceleration` must be longer '
                'than sampling interval.')

        amplitudes = num.zeros_like(times)

        amplitudes[mask_acc] = - num.sin(
            (times[mask_acc] - tref) / d_acc * num.pi)

        amplitudes[mask_dec] = num.sin(
            (times[mask_dec] - (tref + d_acc)) / d_dec * num.pi)

        sum_acc = num.abs(num.sum(amplitudes[mask_acc]))
        if sum_acc != 0.0:
            amplitudes[mask_acc] /= sum_acc
        else:
            amplitudes[mask_acc] = 1.0 / n_acc

        sum_dec = num.abs(num.sum(amplitudes[mask_dec]))
        if sum_dec != 0.0:
            amplitudes[mask_dec] /= sum_dec
        else:
            amplitudes[mask_dec] = 1.0 / n_dec

        if self.mute_acceleration:
            amplitudes[mask_acc] = 0.0

        if self.mute_deceleration:
            amplitudes[mask_dec] = 0.0

        return times, amplitudes


class MultiTriangleSTF(STF):
    '''
    Sequence of overlapping triangles to represent arbitrarily shaped STFs.

    Note: Integral of amplitudes is not automatically normalized. This must be
    considered when interpreting the moment of a source using this STF.
    '''

    deltat = Float.T(
        default=1.0,
        help='Time interval between too control nodes.')

    amplitudes = Array.T(
        default=num.array([1.]),
        dtype=num.float64,
        serialize_as='list',
        help='Amplitudes of the control nodes.')

    anchor = Float.T(
        default=0.0,
        help='anchor point with respect to source.time: ('
             '-1.0: left -> first control node is at source.time ~ '
             'hypocenter time, 0.0: center -> control nodes are layed out '
             'symmetric around source.time, +1.0: right -> last control node '
             'is at source.time')

    def centroid_time(self, tref):
        amplitudes = num.abs(self.amplitudes) \
            / num.sum(num.abs(self.amplitudes))
        times = num.arange(amplitudes.size) * self.deltat
        return tref + sum(amplitudes * times) / num.sum(amplitudes) \
            - (self.anchor + 1) * (self.amplitudes.size-1)/2 * self.deltat

    @property
    def effective_duration(self):
        # only halfway correct
        amplitudes = num.abs(self.amplitudes) \
            / num.sum(num.abs(self.amplitudes))
        times = num.arange(amplitudes.size) * self.deltat
        t0 = sum(amplitudes * times) / num.sum(amplitudes)
        return num.sqrt(num.sum((times - t0)**2 * amplitudes)) \
            * 2. * num.sqrt(3.)

    def discretize_t(self, deltat, tref):
        control_amplitudes = self.amplitudes
        control_deltat = self.deltat
        ncontrol = control_amplitudes.size

        duration = control_deltat * (ncontrol + 1)

        t0 = tref - 0.5 * (1.0 + self.anchor) * control_deltat * (ncontrol - 1)

        tmin_stf = t0 - control_deltat
        tmax_stf = tmin_stf + duration
        tmin = math.floor(tmin_stf / deltat) * deltat - 0.5*deltat
        tmax = math.ceil(tmax_stf / deltat) * deltat + 0.5*deltat
        times = util.arange2(tmin, tmax, deltat, epsilon=1e-3)
        control_times = t0 + control_deltat * num.arange(ncontrol)

        ct_ = control_times[:, num.newaxis]
        ca_ = control_amplitudes[:, num.newaxis]
        cd_ = control_deltat
        t_ = times[num.newaxis, :]

        amplitudes = num.sum(0.5 * ca_ * (
            cd_
            + 1. / cd_ * (num.clip(t_, ct_ - cd_, ct_) + cd_ - ct_)**2
            - 1. / cd_ * (num.clip(t_, ct_, ct_ + cd_) - cd_ - ct_)**2),
            axis=0)

        times = times[:-1] + 0.5 * deltat
        amplitudes = num.diff(amplitudes)

        return times, amplitudes

    def normalize(self):
        self.amplitudes /= (self.deltat * num.sum(num.abs(self.amplitudes)))


class STFMode(StringChoice):
    choices = ['pre', 'post']


class Source(Location, Cloneable):
    '''
    Base class for all source models.
    '''

    name = String.T(optional=True, default='')

    time = Timestamp.T(
        default=Timestamp.D('1970-01-01 00:00:00'),
        help='source origin time.')

    stf = STF.T(
        optional=True,
        help='source time function.')

    stf_mode = STFMode.T(
        default='post',
        help='whether to apply source time function in pre or '
             'post-processing.')

    def __init__(self, **kwargs):
        Location.__init__(self, **kwargs)

    def update(self, **kwargs):
        '''
        Change some of the source models parameters.

        Example::

          >>> from pyrocko import gf
          >>> s = gf.DCSource()
          >>> s.update(strike=66., dip=33.)
          >>> print(s)
          --- !pf.DCSource
          depth: 0.0
          time: 1970-01-01 00:00:00
          magnitude: 6.0
          strike: 66.0
          dip: 33.0
          rake: 0.0

        '''

        for (k, v) in kwargs.items():
            self[k] = v

    def grid(self, **variables):
        '''
        Create grid of source model variations.

        :returns: :py:class:`SourceGrid` instance.

        Example::

          >>> from pyrocko import gf
          >>> base = DCSource()
          >>> R = gf.Range
          >>> for s in base.grid(R('

        '''
        return SourceGrid(base=self, variables=variables)

    def base_key(self):
        '''
        Get key to decide about source discretization / GF stack sharing.

        When two source models differ only in amplitude and origin time, the
        discretization and the GF stacking can be done only once for a unit
        amplitude and a zero origin time and the amplitude and origin times of
        the seismograms can be applied during post-processing of the synthetic
        seismogram.

        For any derived parameterized source model, this method is called to
        decide if discretization and stacking of the source should be shared.
        When two source models return an equal vector of values discretization
        is shared.
        '''
        return (self.depth, self.lat, self.north_shift,
                self.lon, self.east_shift, self.time, type(self).__name__) + \
            self.effective_stf_pre().base_key()

    def get_factor(self):
        '''
        Get the scaling factor to be applied during post-processing.

        Discretization of the base seismogram is usually done for a unit
        amplitude, because a common factor can be efficiently multiplied to
        final seismograms. This eliminates to do repeat the stacking when
        creating seismograms for a series of source models only differing in
        amplitude.

        This method should return the scaling factor to apply in the
        post-processing (often this is simply the scalar moment of the source).
        '''

        return 1.0

    def effective_stf_pre(self):
        '''
        Return the STF applied before stacking of the Green's functions.

        This STF is used during discretization of the parameterized source
        models, i.e. to produce a temporal distribution of point sources.

        Handling of the STF before stacking of the GFs is less efficient but
        allows to use different source time functions for different parts of
        the source.
        '''

        if self.stf is not None and self.stf_mode == 'pre':
            return self.stf
        else:
            return g_unit_pulse

    def effective_stf_post(self):
        '''
        Return the STF applied after stacking of the Green's fuctions.

        This STF is used in the post-processing of the synthetic seismograms.

        Handling of the STF after stacking of the GFs is usually more efficient
        but is only possible when a common STF is used for all subsources.
        '''

        if self.stf is not None and self.stf_mode == 'post':
            return self.stf
        else:
            return g_unit_pulse

    def _dparams_base(self):
        return dict(times=arr(self.time),
                    lat=self.lat, lon=self.lon,
                    north_shifts=arr(self.north_shift),
                    east_shifts=arr(self.east_shift),
                    depths=arr(self.depth))

    def _hash(self):
        sha = sha1()
        for k in self.base_key():
            sha.update(str(k).encode())
        return sha.hexdigest()

    def _dparams_base_repeated(self, times):
        if times is None:
            return self._dparams_base()

        nt = times.size
        north_shifts = num.repeat(self.north_shift, nt)
        east_shifts = num.repeat(self.east_shift, nt)
        depths = num.repeat(self.depth, nt)
        return dict(times=times,
                    lat=self.lat, lon=self.lon,
                    north_shifts=north_shifts,
                    east_shifts=east_shifts,
                    depths=depths)

    def pyrocko_event(self, store=None, target=None, **kwargs):
        duration = None
        if self.stf:
            duration = self.stf.effective_duration

        return model.Event(
            lat=self.lat,
            lon=self.lon,
            north_shift=self.north_shift,
            east_shift=self.east_shift,
            time=self.time,
            name=self.name,
            depth=self.depth,
            duration=duration,
            **kwargs)

    def geometry(self, **kwargs):
        raise NotImplementedError

    def outline(self, cs='xyz'):
        points = num.atleast_2d(num.zeros([1, 3]))

        points[:, 0] += self.north_shift
        points[:, 1] += self.east_shift
        points[:, 2] += self.depth
        if cs == 'xyz':
            return points
        elif cs == 'xy':
            return points[:, :2]
        elif cs in ('latlon', 'lonlat'):
            latlon = ne_to_latlon(
                self.lat, self.lon, points[:, 0], points[:, 1])

            latlon = num.array(latlon).T
            if cs == 'latlon':
                return latlon
            else:
                return latlon[:, ::-1]

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        if ev.depth is None:
            raise ConversionError(
                'Cannot convert event object to source object: '
                'no depth information available')

        stf = None
        if ev.duration is not None:
            stf = HalfSinusoidSTF(effective_duration=ev.duration)

        d = dict(
            name=ev.name,
            time=ev.time,
            lat=ev.lat,
            lon=ev.lon,
            north_shift=ev.north_shift,
            east_shift=ev.east_shift,
            depth=ev.depth,
            stf=stf)
        d.update(kwargs)
        return cls(**d)

    def get_magnitude(self):
        raise NotImplementedError(
            '%s does not implement get_magnitude()'
            % self.__class__.__name__)


class SourceWithMagnitude(Source):
    '''
    Base class for sources containing a moment magnitude.
    '''

    magnitude = Float.T(
        default=6.0,
        help='Moment magnitude Mw as in [Hanks and Kanamori, 1979]')

    def __init__(self, **kwargs):
        if 'moment' in kwargs:
            mom = kwargs.pop('moment')
            if 'magnitude' not in kwargs:
                kwargs['magnitude'] = float(pmt.moment_to_magnitude(mom))

        Source.__init__(self, **kwargs)

    @property
    def moment(self):
        return float(pmt.magnitude_to_moment(self.magnitude))

    @moment.setter
    def moment(self, value):
        self.magnitude = float(pmt.moment_to_magnitude(value))

    def pyrocko_event(self, store=None, target=None, **kwargs):
        return Source.pyrocko_event(
            self, store, target,
            magnitude=self.magnitude,
            **kwargs)

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        d = {}
        if ev.magnitude:
            d.update(magnitude=ev.magnitude)

        d.update(kwargs)
        return super(SourceWithMagnitude, cls).from_pyrocko_event(ev, **d)

    def get_magnitude(self):
        return self.magnitude


class DerivedMagnitudeError(ValidationError):
    '''
    Raised when conversion between magnitude, moment, volume change or
    displacement failed.
    '''
    pass


class SourceWithDerivedMagnitude(Source):

    class __T(Source.T):

        def validate_extra(self, val):
            Source.T.validate_extra(self, val)
            val.check_conflicts()

    def check_conflicts(self):
        '''
        Check for parameter conflicts.

        To be overloaded in subclasses. Raises :py:exc:`DerivedMagnitudeError`
        on conflicts.
        '''
        pass

    def get_magnitude(self, store=None, target=None):
        raise DerivedMagnitudeError('No magnitude set.')

    def get_moment(self, store=None, target=None):
        return float(pmt.magnitude_to_moment(
            self.get_magnitude(store, target)))

    def pyrocko_moment_tensor(self, store=None, target=None):
        raise NotImplementedError(
            '%s does not implement pyrocko_moment_tensor()'
            % self.__class__.__name__)

    def pyrocko_event(self, store=None, target=None, **kwargs):
        try:
            mt = self.pyrocko_moment_tensor(store, target)
            magnitude = self.get_magnitude()
        except (DerivedMagnitudeError, NotImplementedError):
            mt = None
            magnitude = None

        return Source.pyrocko_event(
            self, store, target,
            moment_tensor=mt,
            magnitude=magnitude,
            **kwargs)


class ExplosionSource(SourceWithDerivedMagnitude):
    '''
    An isotropic explosion point source.
    '''

    magnitude = Float.T(
        optional=True,
        help='moment magnitude Mw as in [Hanks and Kanamori, 1979]')

    volume_change = Float.T(
        optional=True,
        help='volume change of the explosion/implosion or '
             'the contracting/extending magmatic source. [m^3]')

    discretized_source_class = meta.DiscretizedExplosionSource

    def __init__(self, **kwargs):
        if 'moment' in kwargs:
            mom = kwargs.pop('moment')
            if 'magnitude' not in kwargs:
                kwargs['magnitude'] = float(pmt.moment_to_magnitude(mom))

        SourceWithDerivedMagnitude.__init__(self, **kwargs)

    def base_key(self):
        return SourceWithDerivedMagnitude.base_key(self) + \
            (self.volume_change,)

    def check_conflicts(self):
        if self.magnitude is not None and self.volume_change is not None:
            raise DerivedMagnitudeError(
                'Magnitude and volume_change are both defined.')

    def get_magnitude(self, store=None, target=None):
        self.check_conflicts()

        if self.magnitude is not None:
            return self.magnitude

        elif self.volume_change is not None:
            moment = self.volume_change * \
                self.get_moment_to_volume_change_ratio(store, target)

            return float(pmt.moment_to_magnitude(abs(moment)))
        else:
            return float(pmt.moment_to_magnitude(1.0))

    def get_volume_change(self, store=None, target=None):
        self.check_conflicts()

        if self.volume_change is not None:
            return self.volume_change

        elif self.magnitude is not None:
            moment = float(pmt.magnitude_to_moment(self.magnitude))
            return moment / self.get_moment_to_volume_change_ratio(
                store, target)

        else:
            return 1.0 / self.get_moment_to_volume_change_ratio(store)

    def get_moment_to_volume_change_ratio(self, store, target=None):
        if store is None:
            raise DerivedMagnitudeError(
                'Need earth model to convert between volume change and '
                'magnitude.')

        points = num.array(
            [[self.north_shift, self.east_shift, self.depth]], dtype=float)

        interpolation = target.interpolation if target else 'multilinear'
        try:
            shear_moduli = store.config.get_shear_moduli(
                self.lat, self.lon,
                points=points,
                interpolation=interpolation)[0]

            bulk_moduli = store.config.get_bulk_moduli(
                self.lat, self.lon,
                points=points,
                interpolation=interpolation)[0]
        except meta.OutOfBounds:
            raise DerivedMagnitudeError(
                'Could not get shear modulus at source position.')

        return float(2. * shear_moduli + bulk_moduli)

    def get_factor(self):
        return 1.0

    def discretize_basesource(self, store, target=None):
        times, amplitudes = self.effective_stf_pre().discretize_t(
            store.config.deltat, self.time)

        amplitudes *= self.get_moment(store, target) * math.sqrt(2. / 3.)

        if self.volume_change is not None:
            if self.volume_change < 0.:
                amplitudes *= -1

        return meta.DiscretizedExplosionSource(
            m0s=amplitudes,
            **self._dparams_base_repeated(times))

    def pyrocko_moment_tensor(self, store=None, target=None):
        a = self.get_moment(store, target) * math.sqrt(2. / 3.)
        return pmt.MomentTensor(m=pmt.symmat6(a, a, a, 0., 0., 0.))


class RectangularExplosionSource(ExplosionSource):
    '''
    Rectangular or line explosion source.
    '''

    discretized_source_class = meta.DiscretizedExplosionSource

    strike = Float.T(
        default=0.0,
        help='strike direction in [deg], measured clockwise from north')

    dip = Float.T(
        default=90.0,
        help='dip angle in [deg], measured downward from horizontal')

    length = Float.T(
        default=0.,
        help='length of rectangular source area [m]')

    width = Float.T(
        default=0.,
        help='width of rectangular source area [m]')

    anchor = StringChoice.T(
        choices=['top', 'top_left', 'top_right', 'center', 'bottom',
                 'bottom_left', 'bottom_right'],
        default='center',
        optional=True,
        help='Anchor point for positioning the plane, can be: top, center or'
             'bottom and also top_left, top_right,bottom_left,'
             'bottom_right, center_left and center right')

    nucleation_x = Float.T(
        optional=True,
        help='horizontal position of rupture nucleation in normalized fault '
             'plane coordinates (-1 = left edge, +1 = right edge)')

    nucleation_y = Float.T(
        optional=True,
        help='down-dip position of rupture nucleation in normalized fault '
             'plane coordinates (-1 = upper edge, +1 = lower edge)')

    velocity = Float.T(
        default=3500.,
        help='speed of explosion front [m/s]')

    aggressive_oversampling = Bool.T(
        default=False,
        help='Aggressive oversampling for basesource discretization. '
             "When using 'multilinear' interpolation oversampling has"
             ' practically no effect.')

    def base_key(self):
        return Source.base_key(self) + (self.strike, self.dip, self.length,
                                        self.width, self.nucleation_x,
                                        self.nucleation_y, self.velocity,
                                        self.anchor)

    def discretize_basesource(self, store, target=None):

        if self.nucleation_x is not None:
            nucx = self.nucleation_x * 0.5 * self.length
        else:
            nucx = None

        if self.nucleation_y is not None:
            nucy = self.nucleation_y * 0.5 * self.width
        else:
            nucy = None

        stf = self.effective_stf_pre()

        points, times, amplitudes, dl, dw, nl, nw = discretize_rect_source(
            store.config.deltas, store.config.deltat,
            self.time, self.north_shift, self.east_shift, self.depth,
            self.strike, self.dip, self.length, self.width, self.anchor,
            self.velocity, stf=stf, nucleation_x=nucx, nucleation_y=nucy)

        amplitudes /= num.sum(amplitudes)
        amplitudes *= self.get_moment(store, target)

        return meta.DiscretizedExplosionSource(
            lat=self.lat,
            lon=self.lon,
            times=times,
            north_shifts=points[:, 0],
            east_shifts=points[:, 1],
            depths=points[:, 2],
            m0s=amplitudes)

    def outline(self, cs='xyz'):
        points = outline_rect_source(self.strike, self.dip, self.length,
                                     self.width, self.anchor)

        points[:, 0] += self.north_shift
        points[:, 1] += self.east_shift
        points[:, 2] += self.depth
        if cs == 'xyz':
            return points
        elif cs == 'xy':
            return points[:, :2]
        elif cs in ('latlon', 'lonlat'):
            latlon = ne_to_latlon(
                self.lat, self.lon, points[:, 0], points[:, 1])

            latlon = num.array(latlon).T
            if cs == 'latlon':
                return latlon
            else:
                return latlon[:, ::-1]

    def get_nucleation_abs_coord(self, cs='xy'):

        if self.nucleation_x is None:
            return None, None

        coords = from_plane_coords(self.strike, self.dip, self.length,
                                   self.width, self.depth, self.nucleation_x,
                                   self.nucleation_y, lat=self.lat,
                                   lon=self.lon, north_shift=self.north_shift,
                                   east_shift=self.east_shift, cs=cs)
        return coords


class DCSource(SourceWithMagnitude):
    '''
    A double-couple point source.
    '''

    strike = Float.T(
        default=0.0,
        help='strike direction in [deg], measured clockwise from north')

    dip = Float.T(
        default=90.0,
        help='dip angle in [deg], measured downward from horizontal')

    rake = Float.T(
        default=0.0,
        help='rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view')

    discretized_source_class = meta.DiscretizedMTSource

    def base_key(self):
        return Source.base_key(self) + (self.strike, self.dip, self.rake)

    def get_factor(self):
        return float(pmt.magnitude_to_moment(self.magnitude))

    def discretize_basesource(self, store, target=None):
        mot = pmt.MomentTensor(
            strike=self.strike, dip=self.dip, rake=self.rake)

        times, amplitudes = self.effective_stf_pre().discretize_t(
            store.config.deltat, self.time)
        return meta.DiscretizedMTSource(
            m6s=mot.m6()[num.newaxis, :] * amplitudes[:, num.newaxis],
            **self._dparams_base_repeated(times))

    def pyrocko_moment_tensor(self, store=None, target=None):
        return pmt.MomentTensor(
            strike=self.strike,
            dip=self.dip,
            rake=self.rake,
            scalar_moment=self.moment)

    def pyrocko_event(self, store=None, target=None, **kwargs):
        return SourceWithMagnitude.pyrocko_event(
            self, store, target,
            moment_tensor=self.pyrocko_moment_tensor(store, target),
            **kwargs)

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        d = {}
        mt = ev.moment_tensor
        if mt:
            (strike, dip, rake), _ = mt.both_strike_dip_rake()
            d.update(
                strike=float(strike),
                dip=float(dip),
                rake=float(rake),
                magnitude=float(mt.moment_magnitude()))

        d.update(kwargs)
        return super(DCSource, cls).from_pyrocko_event(ev, **d)


class CLVDSource(SourceWithMagnitude):
    '''
    A pure CLVD point source.
    '''

    discretized_source_class = meta.DiscretizedMTSource

    azimuth = Float.T(
        default=0.0,
        help='azimuth direction of largest dipole, clockwise from north [deg]')

    dip = Float.T(
        default=90.,
        help='dip direction of largest dipole, downward from horizontal [deg]')

    def base_key(self):
        return Source.base_key(self) + (self.azimuth, self.dip)

    def get_factor(self):
        return float(pmt.magnitude_to_moment(self.magnitude))

    @property
    def m6(self):
        a = math.sqrt(4. / 3.) * self.get_factor()
        m = pmt.symmat6(-0.5 * a, -0.5 * a, a, 0., 0., 0.)
        rotmat1 = pmt.euler_to_matrix(
            d2r * (self.dip - 90.),
            d2r * (self.azimuth - 90.),
            0.)
        m = num.dot(rotmat1.T, num.dot(m, rotmat1))
        return pmt.to6(m)

    @property
    def m6_astuple(self):
        return tuple(self.m6.tolist())

    def discretize_basesource(self, store, target=None):
        factor = self.get_factor()
        times, amplitudes = self.effective_stf_pre().discretize_t(
            store.config.deltat, self.time)
        return meta.DiscretizedMTSource(
            m6s=self.m6[num.newaxis, :] * amplitudes[:, num.newaxis] / factor,
            **self._dparams_base_repeated(times))

    def pyrocko_moment_tensor(self, store=None, target=None):
        return pmt.MomentTensor(m=pmt.symmat6(*self.m6_astuple))

    def pyrocko_event(self, store=None, target=None, **kwargs):
        mt = self.pyrocko_moment_tensor(store, target)
        return Source.pyrocko_event(
            self, store, target,
            moment_tensor=self.pyrocko_moment_tensor(store, target),
            magnitude=float(mt.moment_magnitude()),
            **kwargs)


class VLVDSource(SourceWithDerivedMagnitude):
    '''
    Volumetric linear vector dipole source.

    This source is a parameterization for a restricted moment tensor point
    source, useful to represent dyke or sill like inflation or deflation
    sources. The restriction is such that the moment tensor is rotational
    symmetric. It can be represented by a superposition of a linear vector
    dipole (here we use a CLVD for convenience) and an isotropic component. The
    restricted moment tensor has 4 degrees of freedom: 2 independent
    eigenvalues and 2 rotation angles orienting the the symmetry axis.

    In this parameterization, the isotropic component is controlled by
    ``volume_change``. To define the moment tensor, it must be converted to the
    scalar moment of the the MT's isotropic component. For the conversion, the
    shear modulus at the source's position must be known. This value is
    extracted from the earth model defined in the GF store in use.

    The CLVD part by controlled by its scalar moment :math:`M_0`:
    ``clvd_moment``. The sign of ``clvd_moment`` is used to switch between a
    positiv or negativ CLVD (the sign of the largest eigenvalue).
    '''

    discretized_source_class = meta.DiscretizedMTSource

    azimuth = Float.T(
        default=0.0,
        help='azimuth direction of symmetry axis, clockwise from north [deg].')

    dip = Float.T(
        default=90.,
        help='dip direction of symmetry axis, downward from horizontal [deg].')

    volume_change = Float.T(
        default=0.,
        help='volume change of the inflation/deflation [m^3].')

    clvd_moment = Float.T(
        default=0.,
        help='scalar moment :math:`M_0` of the CLVD component [Nm]. The sign '
             'controls the sign of the CLVD (the sign of its largest '
             'eigenvalue).')

    def get_moment_to_volume_change_ratio(self, store, target):
        if store is None or target is None:
            raise DerivedMagnitudeError(
                'Need earth model to convert between volume change and '
                'magnitude.')

        points = num.array(
            [[self.north_shift, self.east_shift, self.depth]], dtype=float)

        try:
            shear_moduli = store.config.get_shear_moduli(
                self.lat, self.lon,
                points=points,
                interpolation=target.interpolation)[0]

            bulk_moduli = store.config.get_bulk_moduli(
                    self.lat, self.lon,
                    points=points,
                    interpolation=target.interpolation)[0]
        except meta.OutOfBounds:
            raise DerivedMagnitudeError(
                'Could not get shear modulus at source position.')

        return float(2. * shear_moduli + bulk_moduli)

    def base_key(self):
        return Source.base_key(self) + \
            (self.azimuth, self.dip, self.volume_change, self.clvd_moment)

    def get_magnitude(self, store=None, target=None):
        mt = self.pyrocko_moment_tensor(store, target)
        return float(pmt.moment_to_magnitude(mt.moment))

    def get_m6(self, store, target):
        a = math.sqrt(4. / 3.) * self.clvd_moment
        m_clvd = pmt.symmat6(-0.5 * a, -0.5 * a, a, 0., 0., 0.)

        rotmat1 = pmt.euler_to_matrix(
            d2r * (self.dip - 90.),
            d2r * (self.azimuth - 90.),
            0.)
        m_clvd = num.dot(rotmat1.T, num.dot(m_clvd, rotmat1))

        m_iso = self.volume_change * \
            self.get_moment_to_volume_change_ratio(store, target)

        m_iso = pmt.symmat6(m_iso, m_iso, m_iso, 0.,
                            0., 0.,) * math.sqrt(2. / 3)

        m = pmt.to6(m_clvd) + pmt.to6(m_iso)
        return m

    def get_moment(self, store=None, target=None):
        return float(pmt.magnitude_to_moment(
            self.get_magnitude(store, target)))

    def get_m6_astuple(self, store, target):
        m6 = self.get_m6(store, target)
        return tuple(m6.tolist())

    def discretize_basesource(self, store, target=None):
        times, amplitudes = self.effective_stf_pre().discretize_t(
            store.config.deltat, self.time)

        m6 = self.get_m6(store, target)
        m6 *= amplitudes / self.get_factor()

        return meta.DiscretizedMTSource(
            m6s=m6[num.newaxis, :],
            **self._dparams_base_repeated(times))

    def pyrocko_moment_tensor(self, store=None, target=None):
        m6_astuple = self.get_m6_astuple(store, target)
        return pmt.MomentTensor(m=pmt.symmat6(*m6_astuple))


class MTSource(Source):
    '''
    A moment tensor point source.
    '''

    discretized_source_class = meta.DiscretizedMTSource

    mnn = Float.T(
        default=1.,
        help='north-north component of moment tensor in [Nm]')

    mee = Float.T(
        default=1.,
        help='east-east component of moment tensor in [Nm]')

    mdd = Float.T(
        default=1.,
        help='down-down component of moment tensor in [Nm]')

    mne = Float.T(
        default=0.,
        help='north-east component of moment tensor in [Nm]')

    mnd = Float.T(
        default=0.,
        help='north-down component of moment tensor in [Nm]')

    med = Float.T(
        default=0.,
        help='east-down component of moment tensor in [Nm]')

    def __init__(self, **kwargs):
        if 'm6' in kwargs:
            for (k, v) in zip('mnn mee mdd mne mnd med'.split(),
                              kwargs.pop('m6')):
                kwargs[k] = float(v)

        Source.__init__(self, **kwargs)

    @property
    def m6(self):
        return num.array(self.m6_astuple)

    @property
    def m6_astuple(self):
        return (self.mnn, self.mee, self.mdd, self.mne, self.mnd, self.med)

    @m6.setter
    def m6(self, value):
        self.mnn, self.mee, self.mdd, self.mne, self.mnd, self.med = value

    def base_key(self):
        return Source.base_key(self) + self.m6_astuple

    def discretize_basesource(self, store, target=None):
        times, amplitudes = self.effective_stf_pre().discretize_t(
            store.config.deltat, self.time)
        return meta.DiscretizedMTSource(
            m6s=self.m6[num.newaxis, :] * amplitudes[:, num.newaxis],
            **self._dparams_base_repeated(times))

    def get_magnitude(self, store=None, target=None):
        m6 = self.m6
        return pmt.moment_to_magnitude(
            math.sqrt(num.sum(m6[0:3]**2) + 2.0 * num.sum(m6[3:6]**2)) /
            math.sqrt(2.))

    def pyrocko_moment_tensor(self, store=None, target=None):
        return pmt.MomentTensor(m=pmt.symmat6(*self.m6_astuple))

    def pyrocko_event(self, store=None, target=None, **kwargs):
        mt = self.pyrocko_moment_tensor(store, target)
        return Source.pyrocko_event(
            self, store, target,
            moment_tensor=self.pyrocko_moment_tensor(store, target),
            magnitude=float(mt.moment_magnitude()),
            **kwargs)

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        d = {}
        mt = ev.moment_tensor
        if mt:
            d.update(m6=tuple(map(float, mt.m6())))
        else:
            if ev.magnitude is not None:
                mom = pmt.magnitude_to_moment(ev.magnitude)
                v = math.sqrt(2. / 3.) * mom
                d.update(m6=(v, v, v, 0., 0., 0.))

        d.update(kwargs)
        return super(MTSource, cls).from_pyrocko_event(ev, **d)


map_anchor = {
    'center': (0.0, 0.0),
    'center_left': (-1.0, 0.0),
    'center_right': (1.0, 0.0),
    'top': (0.0, -1.0),
    'top_left': (-1.0, -1.0),
    'top_right': (1.0, -1.0),
    'bottom': (0.0, 1.0),
    'bottom_left': (-1.0, 1.0),
    'bottom_right': (1.0, 1.0)}


class RectangularSource(SourceWithDerivedMagnitude):
    '''
    Classical Haskell source model modified for bilateral rupture.
    '''

    discretized_source_class = meta.DiscretizedMTSource

    magnitude = Float.T(
        optional=True,
        help='moment magnitude Mw as in [Hanks and Kanamori, 1979]')

    strike = Float.T(
        default=0.0,
        help='strike direction in [deg], measured clockwise from north')

    dip = Float.T(
        default=90.0,
        help='dip angle in [deg], measured downward from horizontal')

    rake = Float.T(
        default=0.0,
        help='rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view')

    length = Float.T(
        default=0.,
        help='length of rectangular source area [m]')

    width = Float.T(
        default=0.,
        help='width of rectangular source area [m]')

    anchor = StringChoice.T(
        choices=['top', 'top_left', 'top_right', 'center', 'bottom',
                 'bottom_left', 'bottom_right'],
        default='center',
        optional=True,
        help='Anchor point for positioning the plane, can be: ``top, center '
             'bottom, top_left, top_right,bottom_left,'
             'bottom_right, center_left, center right``.')

    nucleation_x = Float.T(
        optional=True,
        help='horizontal position of rupture nucleation in normalized fault '
             'plane coordinates (``-1.`` = left edge, ``+1.`` = right edge)')

    nucleation_y = Float.T(
        optional=True,
        help='down-dip position of rupture nucleation in normalized fault '
             'plane coordinates (``-1.`` = upper edge, ``+1.`` = lower edge)')

    velocity = Float.T(
        default=3500.,
        help='speed of rupture front [m/s]')

    slip = Float.T(
        optional=True,
        help='Slip on the rectangular source area [m]')

    opening_fraction = Float.T(
        default=0.,
        help='Determines fraction of slip related to opening. '
             '(``-1``: pure tensile closing, '
             '``0``: pure shear, '
             '``1``: pure tensile opening)')

    decimation_factor = Int.T(
        optional=True,
        default=1,
        help='Sub-source decimation factor, a larger decimation will'
             ' make the result inaccurate but shorten the necessary'
             ' computation time (use for testing puposes only).')

    aggressive_oversampling = Bool.T(
        default=False,
        help='Aggressive oversampling for basesource discretization. '
             "When using 'multilinear' interpolation oversampling has"
             ' practically no effect.')

    def __init__(self, **kwargs):
        if 'moment' in kwargs:
            mom = kwargs.pop('moment')
            if 'magnitude' not in kwargs:
                kwargs['magnitude'] = float(pmt.moment_to_magnitude(mom))

        SourceWithDerivedMagnitude.__init__(self, **kwargs)

    def base_key(self):
        return SourceWithDerivedMagnitude.base_key(self) + (
            self.magnitude,
            self.slip,
            self.strike,
            self.dip,
            self.rake,
            self.length,
            self.width,
            self.nucleation_x,
            self.nucleation_y,
            self.velocity,
            self.decimation_factor,
            self.anchor)

    def check_conflicts(self):
        if self.magnitude is not None and self.slip is not None:
            raise DerivedMagnitudeError(
                'Magnitude and slip are both defined.')

    def get_magnitude(self, store=None, target=None):
        self.check_conflicts()
        if self.magnitude is not None:
            return self.magnitude

        elif self.slip is not None:
            if None in (store, target):
                raise DerivedMagnitudeError(
                    'Magnitude for a rectangular source with slip defined '
                    'can only be derived when earth model and target '
                    'interpolation method are available.')

            amplitudes = self._discretize(store, target)[2]
            if amplitudes.ndim == 2:
                # CLVD component has no net moment, leave out
                return float(pmt.moment_to_magnitude(
                    num.sum(num.abs(amplitudes[0:2, :]).sum())))
            else:
                return float(pmt.moment_to_magnitude(num.sum(amplitudes)))

        else:
            return float(pmt.moment_to_magnitude(1.0))

    def get_factor(self):
        return 1.0

    def get_slip_tensile(self):
        return self.slip * self.opening_fraction

    def get_slip_shear(self):
        return self.slip - abs(self.get_slip_tensile)

    def _discretize(self, store, target):
        if self.nucleation_x is not None:
            nucx = self.nucleation_x * 0.5 * self.length
        else:
            nucx = None

        if self.nucleation_y is not None:
            nucy = self.nucleation_y * 0.5 * self.width
        else:
            nucy = None

        stf = self.effective_stf_pre()

        points, times, amplitudes, dl, dw, nl, nw = discretize_rect_source(
            store.config.deltas, store.config.deltat,
            self.time, self.north_shift, self.east_shift, self.depth,
            self.strike, self.dip, self.length, self.width, self.anchor,
            self.velocity, stf=stf, nucleation_x=nucx, nucleation_y=nucy,
            decimation_factor=self.decimation_factor,
            aggressive_oversampling=self.aggressive_oversampling)

        if self.slip is not None:
            if target is not None:
                interpolation = target.interpolation
            else:
                interpolation = 'nearest_neighbor'
                logger.warning(
                    'no target information available, will use '
                    '"nearest_neighbor" interpolation when extracting shear '
                    'modulus from earth model')

            shear_moduli = store.config.get_shear_moduli(
                self.lat, self.lon,
                points=points,
                interpolation=interpolation)

            tensile_slip = self.get_slip_tensile()
            shear_slip = self.slip - abs(tensile_slip)

            amplitudes_total = [shear_moduli * shear_slip]
            if tensile_slip != 0:
                bulk_moduli = store.config.get_bulk_moduli(
                    self.lat, self.lon,
                    points=points,
                    interpolation=interpolation)

                tensile_iso = bulk_moduli * tensile_slip
                tensile_clvd = (2. / 3.) * shear_moduli * tensile_slip

                amplitudes_total.extend([tensile_iso, tensile_clvd])

            amplitudes_total = num.vstack(amplitudes_total).squeeze() * \
                amplitudes * dl * dw

        else:
            # normalization to retain total moment
            amplitudes_norm = amplitudes / num.sum(amplitudes)
            moment = self.get_moment(store, target)

            amplitudes_total = [
                amplitudes_norm * moment * (1 - abs(self.opening_fraction))]
            if self.opening_fraction != 0.:
                amplitudes_total.append(
                    amplitudes_norm * self.opening_fraction * moment)

            amplitudes_total = num.vstack(amplitudes_total).squeeze()

        return points, times, num.atleast_1d(amplitudes_total), dl, dw, nl, nw

    def discretize_basesource(self, store, target=None):

        points, times, amplitudes, dl, dw, nl, nw = self._discretize(
            store, target)

        mot = pmt.MomentTensor(
            strike=self.strike, dip=self.dip, rake=self.rake)
        m6s = num.repeat(mot.m6()[num.newaxis, :], times.size, axis=0)

        if amplitudes.ndim == 1:
            m6s[:, :] *= amplitudes[:, num.newaxis]
        elif amplitudes.ndim == 2:
            # shear MT components
            rotmat1 = pmt.euler_to_matrix(
                d2r * self.dip, d2r * self.strike, d2r * -self.rake)
            m6s[:, :] *= amplitudes[0, :][:, num.newaxis]

            if amplitudes.shape[0] == 2:
                # tensile MT components - moment/magnitude input
                tensile = pmt.symmat6(1., 1., 3., 0., 0., 0.)
                rot_tensile = pmt.to6(
                    num.dot(rotmat1.T, num.dot(tensile, rotmat1)))

                m6s_tensile = rot_tensile[
                    num.newaxis, :] * amplitudes[1, :][:, num.newaxis]
                m6s += m6s_tensile

            elif amplitudes.shape[0] == 3:
                # tensile MT components - slip input
                iso = pmt.symmat6(1., 1., 1., 0., 0., 0.)
                clvd = pmt.symmat6(-1., -1., 2., 0., 0., 0.)

                rot_iso = pmt.to6(
                    num.dot(rotmat1.T, num.dot(iso, rotmat1)))
                rot_clvd = pmt.to6(
                    num.dot(rotmat1.T, num.dot(clvd, rotmat1)))

                m6s_iso = rot_iso[
                    num.newaxis, :] * amplitudes[1, :][:, num.newaxis]
                m6s_clvd = rot_clvd[
                    num.newaxis, :] * amplitudes[2, :][:, num.newaxis]
                m6s += m6s_iso + m6s_clvd
            else:
                raise ValueError('Unknwown amplitudes shape!')
        else:
            raise ValueError(
                'Unexpected dimension of {}'.format(amplitudes.ndim))

        ds = meta.DiscretizedMTSource(
            lat=self.lat,
            lon=self.lon,
            times=times,
            north_shifts=points[:, 0],
            east_shifts=points[:, 1],
            depths=points[:, 2],
            m6s=m6s,
            dl=dl,
            dw=dw,
            nl=nl,
            nw=nw)

        return ds

    def xy_to_coord(self, x, y, cs='xyz'):
        ln, wd = self.length, self.width
        strike, dip = self.strike, self.dip

        def array_check(variable):
            if not isinstance(variable, num.ndarray):
                return num.array(variable)
            else:
                return variable

        x, y = array_check(x), array_check(y)

        if x.shape[0] != y.shape[0]:
            raise ValueError('Shapes of x and y mismatch')

        x, y = x * 0.5 * ln, y * 0.5 * wd

        points = num.hstack((
            x.reshape(-1, 1), y.reshape(-1, 1), num.zeros((x.shape[0], 1))))

        anch_x, anch_y = map_anchor[self.anchor]
        points[:, 0] -= anch_x * 0.5 * ln
        points[:, 1] -= anch_y * 0.5 * wd

        rotmat = num.asarray(
            pmt.euler_to_matrix(dip * d2r, strike * d2r, 0.0))

        points_rot = num.dot(rotmat.T, points.T).T

        points_rot[:, 0] += self.north_shift
        points_rot[:, 1] += self.east_shift
        points_rot[:, 2] += self.depth

        if cs == 'xyz':
            return points_rot
        elif cs == 'xy':
            return points_rot[:, :2]
        elif cs in ('latlon', 'lonlat', 'latlondepth'):
            latlon = ne_to_latlon(
                self.lat, self.lon, points_rot[:, 0], points_rot[:, 1])
            latlon = num.array(latlon).T
            if cs == 'latlon':
                return latlon
            elif cs == 'lonlat':
                return latlon[:, ::-1]
            else:
                return num.concatenate(
                    (latlon, points_rot[:, 2].reshape((len(points_rot), 1))),
                    axis=1)

    def outline(self, cs='xyz'):
        x = num.array([-1., 1., 1., -1., -1.])
        y = num.array([-1., -1., 1., 1., -1.])

        return self.xy_to_coord(x, y, cs=cs)

    def points_on_source(self, cs='xyz', **kwargs):

        points = points_on_rect_source(
            self.strike, self.dip, self.length, self.width,
            self.anchor, **kwargs)

        points[:, 0] += self.north_shift
        points[:, 1] += self.east_shift
        points[:, 2] += self.depth
        if cs == 'xyz':
            return points
        elif cs == 'xy':
            return points[:, :2]
        elif cs in ('latlon', 'lonlat', 'latlondepth'):
            latlon = ne_to_latlon(
                self.lat, self.lon, points[:, 0], points[:, 1])

            latlon = num.array(latlon).T
            if cs == 'latlon':
                return latlon
            elif cs == 'lonlat':
                return latlon[:, ::-1]
            else:
                return num.concatenate(
                    (latlon, points[:, 2].reshape((len(points), 1))),
                    axis=1)

    def geometry(self, *args, **kwargs):
        from pyrocko.model import Geometry

        ds = self.discretize_basesource(*args, **kwargs)
        nx, ny = ds.nl, ds.nw

        def patch_outlines_xy(nx, ny):
            points = num.zeros((nx * ny, 2))
            points[:, 0] = num.tile(num.linspace(-1., 1., nx), ny)
            points[:, 1] = num.repeat(num.linspace(-1., 1., ny), nx)

            return points

        points_ds = patch_outlines_xy(nx + 1, ny + 1)
        npoints = (nx + 1) * (ny + 1)

        vertices = num.hstack((
            num.ones((npoints, 1)) * self.lat,
            num.ones((npoints, 1)) * self.lon,
            self.xy_to_coord(points_ds[:, 0], points_ds[:, 1], cs='xyz')))

        faces = num.array([[
                iy * (nx + 1) + ix,
                iy * (nx + 1) + ix + 1,
                (iy + 1) * (nx + 1) + ix + 1,
                (iy + 1) * (nx + 1) + ix,
                iy * (nx + 1) + ix]
            for iy in range(ny) for ix in range(nx)])

        xyz = self.outline('xyz')
        latlon = num.ones((5, 2)) * num.array([self.lat, self.lon])
        patchverts = num.hstack((latlon, xyz))

        geom = Geometry()
        geom.setup(vertices, faces)
        geom.set_outlines([patchverts])

        if self.stf:
            geom.times = num.unique(ds.times)

        if self.nucleation_x is not None and self.nucleation_y is not None:
            geom.add_property('t_arrival', ds.times)

        geom.add_property(
            'moment', ds.moments().reshape(ds.nl*ds.nw, -1))

        geom.add_property(
            'slip', num.ones_like(ds.times) * self.slip)

        return geom

    def get_nucleation_abs_coord(self, cs='xy'):

        if self.nucleation_x is None:
            return None, None

        coords = from_plane_coords(self.strike, self.dip, self.length,
                                   self.width, self.depth, self.nucleation_x,
                                   self.nucleation_y, lat=self.lat,
                                   lon=self.lon, north_shift=self.north_shift,
                                   east_shift=self.east_shift, cs=cs)
        return coords

    def pyrocko_moment_tensor(self, store=None, target=None):
        return pmt.MomentTensor(
            strike=self.strike,
            dip=self.dip,
            rake=self.rake,
            scalar_moment=self.get_moment(store, target))

    def pyrocko_event(self, store=None, target=None, **kwargs):
        return SourceWithDerivedMagnitude.pyrocko_event(
            self, store, target,
            **kwargs)

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        d = {}
        mt = ev.moment_tensor
        if mt:
            (strike, dip, rake), _ = mt.both_strike_dip_rake()
            d.update(
                strike=float(strike),
                dip=float(dip),
                rake=float(rake),
                magnitude=float(mt.moment_magnitude()))

        d.update(kwargs)
        return super(RectangularSource, cls).from_pyrocko_event(ev, **d)


class PseudoDynamicRupture(SourceWithDerivedMagnitude):
    '''
    Combined Eikonal and Okada quasi-dynamic rupture model.

    Details are described in :doc:`/topics/pseudo-dynamic-rupture`.
    Note: attribute `stf` is not used so far, but kept for future applications.
    '''

    discretized_source_class = meta.DiscretizedMTSource

    strike = Float.T(
        default=0.0,
        help='Strike direction in [deg], measured clockwise from north.')

    dip = Float.T(
        default=0.0,
        help='Dip angle in [deg], measured downward from horizontal.')

    length = Float.T(
        default=10. * km,
        help='Length of rectangular source area in [m].')

    width = Float.T(
        default=5. * km,
        help='Width of rectangular source area in [m].')

    anchor = StringChoice.T(
        choices=['top', 'top_left', 'top_right', 'center', 'bottom',
                 'bottom_left', 'bottom_right'],
        default='center',
        optional=True,
        help='Anchor point for positioning the plane, can be: ``top, center, '
             'bottom, top_left, top_right, bottom_left, '
             'bottom_right, center_left, center_right``.')

    nucleation_x__ = Array.T(
        default=num.array([0.]),
        dtype=num.float64,
        serialize_as='list',
        help='Horizontal position of rupture nucleation in normalized fault '
             'plane coordinates (``-1.`` = left edge, ``+1.`` = right edge).')

    nucleation_y__ = Array.T(
        default=num.array([0.]),
        dtype=num.float64,
        serialize_as='list',
        help='Down-dip position of rupture nucleation in normalized fault '
             'plane coordinates (``-1.`` = upper edge, ``+1.`` = lower edge).')

    nucleation_time__ = Array.T(
        optional=True,
        help='Time in [s] after origin, when nucleation points defined by '
             '``nucleation_x`` and ``nucleation_y`` rupture.',
        dtype=num.float64,
        serialize_as='list')

    gamma = Float.T(
        default=0.8,
        help='Scaling factor between rupture velocity and S-wave velocity: '
             r':math:`v_r = \gamma * v_s`.')

    nx = Int.T(
        default=2,
        help='Number of discrete source patches in x direction (along '
             'strike).')

    ny = Int.T(
        default=2,
        help='Number of discrete source patches in y direction (down dip).')

    slip = Float.T(
        optional=True,
        help='Maximum slip of the rectangular source [m]. '
             'Setting the slip the tractions/stress field '
             'will be normalized to accomodate the desired maximum slip.')

    rake = Float.T(
        optional=True,
        help='Rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view. Rake is translated into homogenous tractions '
             'in strike and up-dip direction. ``rake`` is mutually exclusive '
             'with tractions parameter.')

    patches = List.T(
        OkadaSource.T(),
        optional=True,
        help='List of all boundary elements/sub faults/fault patches.')

    patch_mask__ = Array.T(
        dtype=bool,
        serialize_as='list',
        shape=(None,),
        optional=True,
        help='Mask for all boundary elements/sub faults/fault patches. True '
             'leaves the patch in the calculation, False excludes the patch.')

    tractions = TractionField.T(
        optional=True,
        help='Traction field the rupture plane is exposed to. See the '
             ':py:mod:`pyrocko.gf.tractions` module for more details. '
             'If ``tractions=None`` and ``rake`` is given'
             ' :py:class:`~pyrocko.gf.tractions.DirectedTractions` will'
             ' be used.')

    coef_mat = Array.T(
        optional=True,
        help='Coefficient matrix linking traction and dislocation field.',
        dtype=num.float64,
        shape=(None, None))

    eikonal_decimation = Int.T(
        optional=True,
        default=1,
        help='Sub-source eikonal factor, a smaller eikonal factor will'
             ' increase the accuracy of rupture front calculation but'
             ' increases also the computation time.')

    decimation_factor = Int.T(
        optional=True,
        default=1,
        help='Sub-source decimation factor, a larger decimation will'
             ' make the result inaccurate but shorten the necessary'
             ' computation time (use for testing puposes only).')

    nthreads = Int.T(
        optional=True,
        default=1,
        help='Number of threads for Okada forward modelling, '
             'matrix inversion and calculation of point subsources. '
             'Note: for small/medium matrices 1 thread is most efficient.')

    pure_shear = Bool.T(
        optional=True,
        default=False,
        help='Calculate only shear tractions and omit tensile tractions.')

    smooth_rupture = Bool.T(
        default=True,
        help='Smooth the tractions by weighting partially ruptured'
             ' fault patches.')

    aggressive_oversampling = Bool.T(
        default=False,
        help='Aggressive oversampling for basesource discretization. '
             "When using 'multilinear' interpolation oversampling has"
             ' practically no effect.')

    def __init__(self, **kwargs):
        SourceWithDerivedMagnitude.__init__(self, **kwargs)
        self._interpolators = {}
        self.check_conflicts()

    @property
    def nucleation_x(self):
        return self.nucleation_x__

    @nucleation_x.setter
    def nucleation_x(self, nucleation_x):
        if isinstance(nucleation_x, list):
            nucleation_x = num.array(nucleation_x)

        elif not isinstance(
                nucleation_x, num.ndarray) and nucleation_x is not None:

            nucleation_x = num.array([nucleation_x])
        self.nucleation_x__ = nucleation_x

    @property
    def nucleation_y(self):
        return self.nucleation_y__

    @nucleation_y.setter
    def nucleation_y(self, nucleation_y):
        if isinstance(nucleation_y, list):
            nucleation_y = num.array(nucleation_y)

        elif not isinstance(nucleation_y, num.ndarray) \
                and nucleation_y is not None:
            nucleation_y = num.array([nucleation_y])

        self.nucleation_y__ = nucleation_y

    @property
    def nucleation(self):
        nucl_x, nucl_y = self.nucleation_x, self.nucleation_y

        if (nucl_x is None) or (nucl_y is None):
            return None

        assert nucl_x.shape[0] == nucl_y.shape[0]

        return num.concatenate(
            (nucl_x[:, num.newaxis], nucl_y[:, num.newaxis]), axis=1)

    @nucleation.setter
    def nucleation(self, nucleation):
        if isinstance(nucleation, list):
            nucleation = num.array(nucleation)

        assert nucleation.shape[1] == 2

        self.nucleation_x = nucleation[:, 0]
        self.nucleation_y = nucleation[:, 1]

    @property
    def nucleation_time(self):
        return self.nucleation_time__

    @nucleation_time.setter
    def nucleation_time(self, nucleation_time):
        if not isinstance(nucleation_time, num.ndarray) \
                and nucleation_time is not None:
            nucleation_time = num.array([nucleation_time])

        self.nucleation_time__ = nucleation_time

    @property
    def patch_mask(self):
        if (self.patch_mask__ is not None and
                self.patch_mask__.shape == (self.nx * self.ny,)):

            return self.patch_mask__
        else:
            return num.ones(self.nx * self.ny, dtype=bool)

    @patch_mask.setter
    def patch_mask(self, patch_mask):
        if isinstance(patch_mask, list):
            patch_mask = num.array(patch_mask)

        self.patch_mask__ = patch_mask

    def get_tractions(self):
        '''
        Get source traction vectors.

        If :py:attr:`rake` is given, unit length directed traction vectors
        (:py:class:`~pyrocko.gf.tractions.DirectedTractions`) are returned,
        else the given :py:attr:`tractions` are used.

        :returns:
            Traction vectors per patch.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(n_patches, 3)``.
        '''

        if self.rake is not None:
            if num.isnan(self.rake):
                raise ValueError('Rake must be a real number, not NaN.')

            logger.warning(
                'Tractions are derived based on the given source rake.')
            tractions = DirectedTractions(rake=self.rake)
        else:
            tractions = self.tractions
        return tractions.get_tractions(self.nx, self.ny, self.patches)

    def get_scaled_tractions(self, store):
        '''
        Get traction vectors rescaled to given slip.

        Opposing to :py:meth:`get_tractions` traction vectors
        (:py:class:`~pyrocko.gf.tractions.DirectedTractions`) are rescaled to
        the given :py:attr:`slip` before returning. If no :py:attr:`slip` and
        :py:attr:`rake` are provided, the given  :py:attr:`tractions` are
        returned without scaling.

        :param store:
            Green's function database (needs to cover whole region of the
            source).
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :returns:
            Traction vectors per patch.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(n_patches, 3)``.
        '''
        tractions = self.tractions
        factor = 1.

        if self.rake is not None and self.slip is not None:
            if num.isnan(self.rake):
                raise ValueError('Rake must be a real number, not NaN.')

            self.discretize_patches(store)
            slip_0t = max(num.linalg.norm(
                self.get_slip(scale_slip=False),
                axis=1))

            factor = self.slip / slip_0t
            tractions = DirectedTractions(rake=self.rake)

        return tractions.get_tractions(self.nx, self.ny, self.patches) * factor

    def base_key(self):
        return SourceWithDerivedMagnitude.base_key(self) + (
            self.slip,
            self.strike,
            self.dip,
            self.rake,
            self.length,
            self.width,
            float(self.nucleation_x.mean()),
            float(self.nucleation_y.mean()),
            self.decimation_factor,
            self.anchor,
            self.pure_shear,
            self.gamma,
            tuple(self.patch_mask))

    def check_conflicts(self):
        if self.tractions and self.rake:
            raise AttributeError(
                'Tractions and rake are mutually exclusive.')
        if self.tractions is None and self.rake is None:
            self.rake = 0.

    def get_magnitude(self, store=None, target=None):
        '''
        Get total seismic moment magnitude Mw.

        :param store:
            GF store to guide the discretization and providing the earthmodel
            which is needed to calculate moment from slip.
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param target:
            Target, used to get GF interpolation settings.
        :type target:
            :py:class:`pyrocko.gf.targets.Target`

        :returns:
            Moment magnitude
        :rtype:
            float
        '''
        self.check_conflicts()
        if self.slip is not None or self.tractions is not None:
            if store is None:
                raise DerivedMagnitudeError(
                    'Magnitude for a rectangular source with slip or '
                    'tractions defined can only be derived when earth model '
                    'is set.')

            moment_rate, calc_times = self.discretize_basesource(
                store, target=target).get_moment_rate(store.config.deltat)

            deltat = num.concatenate((
                (num.diff(calc_times)[0],),
                num.diff(calc_times)))

            return float(pmt.moment_to_magnitude(
                num.sum(moment_rate * deltat)))

        else:
            return float(pmt.moment_to_magnitude(1.0))

    def get_factor(self):
        return 1.0

    def outline(self, cs='xyz'):
        '''
        Get source outline corner coordinates.

        :param cs:
            :ref:`Output coordinate system <coordinate-system-names>`.
        :type cs:
            str

        :returns:
            Corner points in desired coordinate system.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(5, [2, 3])``.
        '''
        points = outline_rect_source(self.strike, self.dip, self.length,
                                     self.width, self.anchor)

        points[:, 0] += self.north_shift
        points[:, 1] += self.east_shift
        points[:, 2] += self.depth
        if cs == 'xyz':
            return points
        elif cs == 'xy':
            return points[:, :2]
        elif cs in ('latlon', 'lonlat', 'latlondepth'):
            latlon = ne_to_latlon(
                self.lat, self.lon, points[:, 0], points[:, 1])

            latlon = num.array(latlon).T
            if cs == 'latlon':
                return latlon
            elif cs == 'lonlat':
                return latlon[:, ::-1]
            else:
                return num.concatenate(
                    (latlon, points[:, 2].reshape((len(points), 1))),
                    axis=1)

    def points_on_source(self, cs='xyz', **kwargs):
        '''
        Convert relative plane coordinates to geographical coordinates.

        Given x and y coordinates (relative source coordinates between -1.
        and 1.) are converted to desired geographical coordinates. Coordinates
        need to be given as :py:class:`~numpy.ndarray` arguments ``points_x``
        and ``points_y``.

        :param cs:
            :ref:`Output coordinate system <coordinate-system-names>`.
        :type cs:
            str

        :returns:
            Point coordinates in desired coordinate system.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(n_points, [2, 3])``.
        '''
        points = points_on_rect_source(
            self.strike, self.dip, self.length, self.width,
            self.anchor, **kwargs)

        points[:, 0] += self.north_shift
        points[:, 1] += self.east_shift
        points[:, 2] += self.depth
        if cs == 'xyz':
            return points
        elif cs == 'xy':
            return points[:, :2]
        elif cs in ('latlon', 'lonlat', 'latlondepth'):
            latlon = ne_to_latlon(
                self.lat, self.lon, points[:, 0], points[:, 1])

            latlon = num.array(latlon).T
            if cs == 'latlon':
                return latlon
            elif cs == 'lonlat':
                return latlon[:, ::-1]
            else:
                return num.concatenate(
                    (latlon, points[:, 2].reshape((len(points), 1))),
                    axis=1)

    def pyrocko_moment_tensor(self, store=None, target=None):
        '''
        Get overall moment tensor of the rupture.

        :param store:
            GF store to guide the discretization and providing the earthmodel
            which is needed to calculate moment from slip.
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param target:
            Target, used to get GF interpolation settings.
        :type target:
            :py:class:`pyrocko.gf.targets.Target`

        :returns:
            Moment tensor.
        :rtype:
            :py:class:`~pyrocko.moment_tensor.MomentTensor`
        '''
        if store is not None:
            if not self.patches:
                self.discretize_patches(store)

            data = self.get_slip()
        else:
            data = self.get_tractions()

        weights = num.linalg.norm(data, axis=1)
        weights /= weights.sum()

        rakes = num.arctan2(data[:, 1], data[:, 0]) * r2d
        rake = num.average(rakes, weights=weights)

        return pmt.MomentTensor(
            strike=self.strike,
            dip=self.dip,
            rake=rake,
            scalar_moment=self.get_moment(store, target))

    def pyrocko_event(self, store=None, target=None, **kwargs):
        return SourceWithDerivedMagnitude.pyrocko_event(
            self, store, target,
            **kwargs)

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        d = {}
        mt = ev.moment_tensor
        if mt:
            (strike, dip, rake), _ = mt.both_strike_dip_rake()
            d.update(
                strike=float(strike),
                dip=float(dip),
                rake=float(rake))

        d.update(kwargs)
        return super(PseudoDynamicRupture, cls).from_pyrocko_event(ev, **d)

    def _discretize_points(self, store, *args, **kwargs):
        '''
        Discretize source plane with equal vertical and horizontal spacing.

        Additional ``*args`` and ``**kwargs`` are passed to
        :py:meth:`points_on_source`.

        :param store:
            Green's function database (needs to cover whole region of the
            source).
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :returns:
            Number of points in strike and dip direction, distance
            between adjacent points, coordinates (latlondepth) and coordinates
            (xy on fault) for discrete points.
        :rtype:
            (int, int, float, :py:class:`~numpy.ndarray`,
            :py:class:`~numpy.ndarray`).
        '''
        anch_x, anch_y = map_anchor[self.anchor]

        npoints = int(self.width // km) + 1
        points = num.zeros((npoints, 3))
        points[:, 1] = num.linspace(-1., 1., npoints)
        points[:, 1] = (points[:, 1] - anch_y) * self.width/2

        rotmat = pmt.euler_to_matrix(self.dip*d2r, self.strike*d2r, 0.0)
        points = num.dot(rotmat.T, points.T).T
        points[:, 2] += self.depth

        vs_min = store.config.get_vs(
            self.lat, self.lon, points,
            interpolation='nearest_neighbor')
        vr_min = max(vs_min.min(), .5*km) * self.gamma

        oversampling = 10.
        delta_l = self.length / (self.nx * oversampling)
        delta_w = self.width / (self.ny * oversampling)

        delta = self.eikonal_decimation * num.min([
            store.config.deltat * vr_min / oversampling,
            delta_l, delta_w] + [
            deltas for deltas in store.config.deltas])

        delta = delta_w / num.ceil(delta_w / delta)

        nx = int(num.ceil(self.length / delta)) + 1
        ny = int(num.ceil(self.width / delta)) + 1

        rem_l = (nx-1)*delta - self.length
        lim_x = rem_l / self.length

        points_xy = num.zeros((nx * ny, 2))
        points_xy[:, 0] = num.repeat(
            num.linspace(-1.-lim_x, 1.+lim_x, nx), ny)
        points_xy[:, 1] = num.tile(
            num.linspace(-1., 1., ny), nx)

        points = self.points_on_source(
            points_x=points_xy[:, 0],
            points_y=points_xy[:, 1],
            **kwargs)

        return nx, ny, delta, points, points_xy

    def _discretize_rupture_v(self, store, interpolation='nearest_neighbor',
                              points=None):
        '''
        Get rupture velocity for discrete points on source plane.

        :param store:
            Green's function database (needs to cover the whole region of the
            source)
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param interpolation:
            Interpolation method to use (choose between ``'nearest_neighbor'``
            and ``'multilinear'``).
        :type interpolation:
            str

        :param points:
            Coordinates on fault (-1.:1.) of discrete points.
        :type points:
            :py:class:`~numpy.ndarray`: ``(n_points, 2)``

        :returns:
            Rupture velocity assumed as :math:`v_s * \\gamma` for discrete
            points.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(n_points, )``.
        '''

        if points is None:
            _, _, _, points, _ = self._discretize_points(store, cs='xyz')

        return store.config.get_vs(
            self.lat, self.lon,
            points=points,
            interpolation=interpolation) * self.gamma

    def discretize_time(
            self, store,  interpolation='nearest_neighbor',
            vr=None, times=None, *args, **kwargs):
        '''
        Get rupture start time for discrete points on source plane.

        :param store:
            Green's function database (needs to cover whole region of the
            source)
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param interpolation:
            Interpolation method to use (choose between ``'nearest_neighbor'``
            and ``'multilinear'``).
        :type interpolation:
            str

        :param vr:
            Array, containing rupture user defined rupture velocity values.
        :type vr:
            :py:class:`~numpy.ndarray`

        :param times:
            Array, containing zeros, where rupture is starting, real positive
            numbers at later secondary nucleation points and -1, where time
            will be calculated. If not given, rupture starts at nucleation_x,
            nucleation_y. Times are given for discrete points with equal
            horizontal and vertical spacing.
        :type times:
            :py:class:`~numpy.ndarray`

        :returns:
            Coordinates (latlondepth), coordinates (xy), rupture velocity,
            rupture propagation time of discrete points.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(n_points, 3)``,
            :py:class:`~numpy.ndarray`: ``(n_points, 2)``,
            :py:class:`~numpy.ndarray`: ``(n_points_dip, n_points_strike)``,
            :py:class:`~numpy.ndarray`: ``(n_points_dip, n_points_strike)``.
        '''
        nx, ny, delta, points, points_xy = self._discretize_points(
            store, cs='xyz')

        if vr is None or vr.shape != tuple((nx, ny)):
            if vr:
                logger.warning(
                    'Given rupture velocities are not in right shape: '
                    '(%i, %i), but needed is (%i, %i).', *vr.shape + (nx, ny))
            vr = self._discretize_rupture_v(store, interpolation, points)\
                .reshape(nx, ny)

        if vr.shape != tuple((nx, ny)):
            logger.warning(
                'Given rupture velocities are not in right shape. Therefore'
                ' standard rupture velocity array is used.')

        def initialize_times():
            nucl_x, nucl_y = self.nucleation_x, self.nucleation_y

            if nucl_x.shape != nucl_y.shape:
                raise ValueError(
                    'Nucleation coordinates have different shape.')

            dist_points = num.array([
                num.linalg.norm(points_xy - num.array([x, y]).ravel(), axis=1)
                for x, y in zip(nucl_x, nucl_y)])
            nucl_indices = num.argmin(dist_points, axis=1)

            if self.nucleation_time is None:
                nucl_times = num.zeros_like(nucl_indices)
            else:
                if self.nucleation_time.shape == nucl_x.shape:
                    nucl_times = self.nucleation_time
                else:
                    raise ValueError(
                        'Nucleation coordinates and times have different '
                        'shapes')

            t = num.full(nx * ny, -1.)
            t[nucl_indices] = nucl_times
            return t.reshape(nx, ny)

        if times is None:
            times = initialize_times()
        elif times.shape != tuple((nx, ny)):
            times = initialize_times()
            logger.warning(
                'Given times are not in right shape. Therefore standard time'
                ' array is used.')

        eikonal_ext.eikonal_solver_fmm_cartesian(
            speeds=vr, times=times, delta=delta)

        return points, points_xy, vr, times

    def get_vr_time_interpolators(
            self, store, interpolation='nearest_neighbor', force=False,
            **kwargs):
        '''
        Get interpolators for rupture velocity and rupture time.

        Additional ``**kwargs`` are passed to :py:meth:`discretize_time`.

        :param store:
            Green's function database (needs to cover whole region of the
            source).
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param interpolation:
            Interpolation method to use (choose between ``'nearest_neighbor'``
            and ``'multilinear'``).
        :type interpolation:
            str

        :param force:
            Force recalculation of the interpolators (e.g. after change of
            nucleation point locations/times). Default is ``False``.
        :type force:
            bool
        '''
        interp_map = {'multilinear': 'linear', 'nearest_neighbor': 'nearest'}
        if interpolation not in interp_map:
            raise TypeError(
                'Interpolation method %s not available' % interpolation)

        if not self._interpolators.get(interpolation, False) or force:
            _, points_xy, vr, times = self.discretize_time(
                store, **kwargs)

            if self.length <= 0.:
                raise ValueError(
                    'length must be larger then 0. not %g' % self.length)

            if self.width <= 0.:
                raise ValueError(
                    'width must be larger then 0. not %g' % self.width)

            nx, ny = times.shape
            anch_x, anch_y = map_anchor[self.anchor]

            points_xy[:, 0] = (points_xy[:, 0] - anch_x) * self.length / 2.
            points_xy[:, 1] = (points_xy[:, 1] - anch_y) * self.width / 2.

            ascont = num.ascontiguousarray

            self._interpolators[interpolation] = (
                nx, ny, times, vr,
                RegularGridInterpolator(
                    (ascont(points_xy[::ny, 0]), ascont(points_xy[:ny, 1])),
                    times,
                    method=interp_map[interpolation]),
                RegularGridInterpolator(
                    (ascont(points_xy[::ny, 0]), ascont(points_xy[:ny, 1])),
                    vr,
                    method=interp_map[interpolation]))

        return self._interpolators[interpolation]

    def discretize_patches(
            self, store, interpolation='nearest_neighbor', force=False,
            grid_shape=(),
            **kwargs):
        '''
        Get rupture start time and OkadaSource elements for points on rupture.

        All source elements and their corresponding center points are
        calculated and stored in the :py:attr:`patches` attribute.

        Additional ``**kwargs`` are passed to :py:meth:`discretize_time`.

        :param store:
            Green's function database (needs to cover whole region of the
            source).
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param interpolation:
            Interpolation method to use (choose between ``'nearest_neighbor'``
            and ``'multilinear'``).
        :type interpolation:
            str

        :param force:
            Force recalculation of the vr and time interpolators ( e.g. after
            change of nucleation point locations/times). Default is ``False``.
        :type force:
            bool

        :param grid_shape:
            Desired sub fault patch grid size (nlength, nwidth). Either factor
            or grid_shape should be set.
        :type grid_shape:
            :py:class:`tuple` of :py:class:`int`
        '''
        nx, ny, times, vr, time_interpolator, vr_interpolator = \
            self.get_vr_time_interpolators(
                store,
                interpolation=interpolation, force=force, **kwargs)
        anch_x, anch_y = map_anchor[self.anchor]

        al = self.length / 2.
        aw = self.width / 2.
        al1 = -(al + anch_x * al)
        al2 = al - anch_x * al
        aw1 = -aw + anch_y * aw
        aw2 = aw + anch_y * aw
        assert num.abs([al1, al2]).sum() == self.length
        assert num.abs([aw1, aw2]).sum() == self.width

        def get_lame(*a, **kw):
            shear_mod = store.config.get_shear_moduli(*a, **kw)
            lamb = store.config.get_vp(*a, **kw)**2 \
                * store.config.get_rho(*a, **kw) - 2. * shear_mod
            return shear_mod, lamb / (2. * (lamb + shear_mod))

        shear_mod, poisson = get_lame(
            self.lat, self.lon,
            num.array([[self.north_shift, self.east_shift, self.depth]]),
            interpolation=interpolation)

        okada_src = OkadaSource(
            lat=self.lat, lon=self.lon,
            strike=self.strike, dip=self.dip,
            north_shift=self.north_shift, east_shift=self.east_shift,
            depth=self.depth,
            al1=al1, al2=al2, aw1=aw1, aw2=aw2,
            poisson=poisson.mean(),
            shearmod=shear_mod.mean(),
            opening=kwargs.get('opening', 0.))

        if not (self.nx and self.ny):
            if grid_shape:
                self.nx, self.ny = grid_shape
            else:
                self.nx = nx
                self.ny = ny

        source_disc, source_points = okada_src.discretize(self.nx, self.ny)

        shear_mod, poisson = get_lame(
            self.lat, self.lon,
            num.array([src.source_patch()[:3] for src in source_disc]),
            interpolation=interpolation)

        if (self.nx, self.ny) != (nx, ny):
            times_interp = time_interpolator(
                num.ascontiguousarray(source_points[:, :2]))
            vr_interp = vr_interpolator(
                num.ascontiguousarray(source_points[:, :2]))
        else:
            times_interp = times.T.ravel()
            vr_interp = vr.T.ravel()

        for isrc, src in enumerate(source_disc):
            src.vr = vr_interp[isrc]
            src.time = times_interp[isrc] + self.time

        self.patches = source_disc

    def discretize_basesource(self, store, target=None):
        '''
        Prepare source for synthetic waveform calculation.

        :param store:
            Green's function database (needs to cover whole region of the
            source).
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param target:
            Target information.
        :type target:
            :py:class:`~pyrocko.gf.targets.Target`

        :returns:
            Source discretized by a set of moment tensors and times.
        :rtype:
            :py:class:`~pyrocko.gf.meta.DiscretizedMTSource`
        '''
        if not target:
            interpolation = 'nearest_neighbor'
        else:
            interpolation = target.interpolation

        if not self.patches:
            self.discretize_patches(store, interpolation)

        if self.coef_mat is None:
            self.calc_coef_mat()

        delta_slip, slip_times = self.get_delta_slip(store)
        npatches = self.nx * self.ny
        ntimes = slip_times.size

        anch_x, anch_y = map_anchor[self.anchor]

        pln = self.length / self.nx
        pwd = self.width / self.ny

        patch_coords = num.array([
            (p.ix, p.iy)
            for p in self.patches]).reshape(self.nx, self.ny, 2)

        # boundary condition is zero-slip
        # is not valid to avoid unwished interpolation effects
        slip_grid = num.zeros((self.nx + 2, self.ny + 2, ntimes, 3))
        slip_grid[1:-1, 1:-1, :, :] = \
            delta_slip.reshape(self.nx, self.ny, ntimes, 3)

        slip_grid[0, 0, :, :] = slip_grid[1, 1, :, :]
        slip_grid[0, -1, :, :] = slip_grid[1, -2, :, :]
        slip_grid[-1, 0, :, :] = slip_grid[-2, 1, :, :]
        slip_grid[-1, -1, :, :] = slip_grid[-2, -2, :, :]

        slip_grid[1:-1, 0, :, :] = slip_grid[1:-1, 1, :, :]
        slip_grid[1:-1, -1, :, :] = slip_grid[1:-1, -2, :, :]
        slip_grid[0, 1:-1, :, :] = slip_grid[1, 1:-1, :, :]
        slip_grid[-1, 1:-1, :, :] = slip_grid[-2, 1:-1, :, :]

        def make_grid(patch_parameter):
            grid = num.zeros((self.nx + 2, self.ny + 2))
            grid[1:-1, 1:-1] = patch_parameter.reshape(self.nx, self.ny)

            grid[0, 0] = grid[1, 1]
            grid[0, -1] = grid[1, -2]
            grid[-1, 0] = grid[-2, 1]
            grid[-1, -1] = grid[-2, -2]

            grid[1:-1, 0] = grid[1:-1, 1]
            grid[1:-1, -1] = grid[1:-1, -2]
            grid[0, 1:-1] = grid[1, 1:-1]
            grid[-1, 1:-1] = grid[-2, 1:-1]

            return grid

        lamb = self.get_patch_attribute('lamb')
        mu = self.get_patch_attribute('shearmod')

        lamb_grid = make_grid(lamb)
        mu_grid = make_grid(mu)

        coords_x = num.zeros(self.nx + 2)
        coords_x[1:-1] = patch_coords[:, 0, 0]
        coords_x[0] = coords_x[1] - pln / 2
        coords_x[-1] = coords_x[-2] + pln / 2

        coords_y = num.zeros(self.ny + 2)
        coords_y[1:-1] = patch_coords[0, :, 1]
        coords_y[0] = coords_y[1] - pwd / 2
        coords_y[-1] = coords_y[-2] + pwd / 2

        slip_interp = RegularGridInterpolator(
            (coords_x, coords_y, slip_times),
            slip_grid, method='nearest')

        lamb_interp = RegularGridInterpolator(
            (coords_x, coords_y),
            lamb_grid, method='nearest')

        mu_interp = RegularGridInterpolator(
            (coords_x, coords_y),
            mu_grid, method='nearest')

        # discretize basesources
        mindeltagf = min(tuple(
            (self.length / self.nx, self.width / self.ny) +
            tuple(store.config.deltas)))

        nl = int((1. / self.decimation_factor) *
                 num.ceil(pln / mindeltagf)) + 1
        nw = int((1. / self.decimation_factor) *
                 num.ceil(pwd / mindeltagf)) + 1
        nsrc_patch = int(nl * nw)
        dl = pln / nl
        dw = pwd / nw

        patch_area = dl * dw

        xl = num.linspace(-0.5 * (pln - dl), 0.5 * (pln - dl), nl)
        xw = num.linspace(-0.5 * (pwd - dw), 0.5 * (pwd - dw), nw)

        base_coords = num.zeros((nsrc_patch, 3))
        base_coords[:, 0] = num.tile(xl, nw)
        base_coords[:, 1] = num.repeat(xw, nl)
        base_coords = num.tile(base_coords, (npatches, 1))

        center_coords = num.zeros((npatches, 3))
        center_coords[:, 0] = num.repeat(
            num.arange(self.nx) * pln + pln / 2, self.ny) - self.length / 2
        center_coords[:, 1] = num.tile(
            num.arange(self.ny) * pwd + pwd / 2, self.nx) - self.width / 2

        base_coords -= center_coords.repeat(nsrc_patch, axis=0)
        nbaselocs = base_coords.shape[0]

        base_interp = base_coords.repeat(ntimes, axis=0)

        base_times = num.tile(slip_times, nbaselocs)
        base_interp[:, 0] -= anch_x * self.length / 2
        base_interp[:, 1] -= anch_y * self.width / 2
        base_interp[:, 2] = base_times

        _, _, _, _, time_interpolator, _ = self.get_vr_time_interpolators(
            store, interpolation=interpolation)

        time_eikonal_max = time_interpolator.values.max()

        nbasesrcs = base_interp.shape[0]
        delta_slip = slip_interp(base_interp).reshape(nbaselocs, ntimes, 3)
        lamb = lamb_interp(base_interp[:, :2]).ravel()
        mu = mu_interp(base_interp[:, :2]).ravel()

        if False:
            try:
                import matplotlib.pyplot as plt
                coords = base_coords.copy()
                norm = num.sum(num.linalg.norm(delta_slip, axis=2), axis=1)
                plt.scatter(coords[:, 0], coords[:, 1], c=norm)
                plt.show()
            except AttributeError:
                pass

        base_interp[:, 2] = 0.
        rotmat = pmt.euler_to_matrix(self.dip * d2r, self.strike * d2r, 0.0)
        base_interp = num.dot(rotmat.T, base_interp.T).T
        base_interp[:, 0] += self.north_shift
        base_interp[:, 1] += self.east_shift
        base_interp[:, 2] += self.depth

        slip_strike = delta_slip[:, :, 0].ravel()
        slip_dip = delta_slip[:, :, 1].ravel()
        slip_norm = delta_slip[:, :, 2].ravel()

        slip_shear = num.linalg.norm([slip_strike, slip_dip], axis=0)
        slip_rake = r2d * num.arctan2(slip_dip, slip_strike)

        m6s = okada_ext.patch2m6(
            strikes=num.full(nbasesrcs, self.strike, dtype=float),
            dips=num.full(nbasesrcs, self.dip, dtype=float),
            rakes=slip_rake,
            disl_shear=slip_shear,
            disl_norm=slip_norm,
            lamb=lamb,
            mu=mu,
            nthreads=self.nthreads)

        m6s *= patch_area

        dl = -self.patches[0].al1 + self.patches[0].al2
        dw = -self.patches[0].aw1 + self.patches[0].aw2

        base_times[base_times > time_eikonal_max] = time_eikonal_max

        ds = meta.DiscretizedMTSource(
            lat=self.lat,
            lon=self.lon,
            times=base_times + self.time,
            north_shifts=base_interp[:, 0],
            east_shifts=base_interp[:, 1],
            depths=base_interp[:, 2],
            m6s=m6s,
            dl=dl,
            dw=dw,
            nl=self.nx,
            nw=self.ny)

        return ds

    def calc_coef_mat(self):
        '''
        Calculate coefficients connecting tractions and dislocations.
        '''
        if not self.patches:
            raise ValueError(
                'Patches are needed. Please calculate them first.')

        self.coef_mat = make_okada_coefficient_matrix(
            self.patches, nthreads=self.nthreads, pure_shear=self.pure_shear)

    def get_patch_attribute(self, attr):
        '''
        Get patch attributes.

        :param attr:
            Name of selected attribute (see
            :py:class`pyrocko.modelling.okada.OkadaSource`).
        :type attr:
            str

        :returns:
            Array with attribute value for each fault patch.
        :rtype:
            :py:class:`~numpy.ndarray`

        '''
        if not self.patches:
            raise ValueError(
                'Patches are needed. Please calculate them first.')
        return num.array([getattr(p, attr) for p in self.patches])

    def get_slip(
            self,
            time=None,
            scale_slip=True,
            interpolation='nearest_neighbor',
            **kwargs):
        '''
        Get slip per subfault patch for given time after rupture start.

        :param time:
            Time after origin [s], for which slip is computed. If not
            given, final static slip is returned.
        :type time:
            float

        :param scale_slip:
            If ``True`` and :py:attr:`slip` given, all slip values are scaled
            to fit the given maximum slip.
        :type scale_slip:
            bool

        :param interpolation:
            Interpolation method to use (choose between ``'nearest_neighbor'``
            and ``'multilinear'``).
        :type interpolation:
            str

        :returns:
            Inverted dislocations (:math:`u_{strike}, u_{dip}, u_{tensile}`)
            for each source patch.
        :rtype:
            :py:class:`~numpy.ndarray`: ``(n_sources, 3)``
        '''

        if self.patches is None:
            raise ValueError(
                'Please discretize the source first (discretize_patches())')
        npatches = len(self.patches)
        tractions = self.get_tractions()
        time_patch_max = self.get_patch_attribute('time').max() - self.time

        time_patch = time
        if time is None:
            time_patch = time_patch_max

        if self.coef_mat is None:
            self.calc_coef_mat()

        if tractions.shape != (npatches, 3):
            raise AttributeError(
                'The traction vector is of invalid shape.'
                ' Required shape is (npatches, 3)')

        patch_mask = num.ones(npatches, dtype=bool)
        if self.patch_mask is not None:
            patch_mask = self.patch_mask

        times = self.get_patch_attribute('time') - self.time
        times[~patch_mask] = time_patch + 1.  # exlcude unmasked patches
        relevant_sources = num.nonzero(times <= time_patch)[0]
        disloc_est = num.zeros_like(tractions)

        if self.smooth_rupture:
            patch_activation = num.zeros(npatches)

            nx, ny, times, vr, time_interpolator, vr_interpolator = \
                self.get_vr_time_interpolators(
                    store, interpolation=interpolation)

            # Getting the native Eikonal grid, bit hackish
            points_x = num.round(time_interpolator.grid[0], decimals=2)
            points_y = num.round(time_interpolator.grid[1], decimals=2)
            times_eikonal = time_interpolator.values

            time_max = time
            if time is None:
                time_max = times_eikonal.max()

            for ip, p in enumerate(self.patches):
                ul = num.round((p.ix + p.al1, p.iy + p.aw1), decimals=2)
                lr = num.round((p.ix + p.al2, p.iy + p.aw2), decimals=2)

                idx_length = num.logical_and(
                    points_x >= ul[0], points_x <= lr[0])
                idx_width = num.logical_and(
                    points_y >= ul[1], points_y <= lr[1])

                times_patch = times_eikonal[num.ix_(idx_length, idx_width)]
                if times_patch.size == 0:
                    raise AttributeError('could not use smooth_rupture')

                patch_activation[ip] = \
                    (times_patch <= time_max).sum() / times_patch.size

                if time_patch == 0 and time_patch != time_patch_max:
                    patch_activation[ip] = 0.

            patch_activation[~patch_mask] = 0.  # exlcude unmasked patches

            relevant_sources = num.nonzero(patch_activation > 0.)[0]

        if relevant_sources.size == 0:
            return disloc_est

        indices_disl = num.repeat(relevant_sources * 3, 3)
        indices_disl[1::3] += 1
        indices_disl[2::3] += 2

        disloc_est[relevant_sources] = invert_fault_dislocations_bem(
            stress_field=tractions[relevant_sources, :].ravel(),
            coef_mat=self.coef_mat[indices_disl, :][:, indices_disl],
            pure_shear=self.pure_shear, nthreads=self.nthreads,
            epsilon=None,
            **kwargs)

        if self.smooth_rupture:
            disloc_est *= patch_activation[:, num.newaxis]

        if scale_slip and self.slip is not None:
            disloc_tmax = num.zeros(npatches)

            indices_disl = num.repeat(num.nonzero(patch_mask)[0] * 3, 3)
            indices_disl[1::3] += 1
            indices_disl[2::3] += 2

            disloc_tmax[patch_mask] = num.linalg.norm(
                invert_fault_dislocations_bem(
                    stress_field=tractions[patch_mask, :].ravel(),
                    coef_mat=self.coef_mat[indices_disl, :][:, indices_disl],
                    pure_shear=self.pure_shear, nthreads=self.nthreads,
                    epsilon=None,
                    **kwargs), axis=1)

            disloc_tmax_max = disloc_tmax.max()
            if disloc_tmax_max == 0.:
                logger.warning(
                    'slip scaling not performed. Maximum slip is 0.')

            disloc_est *= self.slip / disloc_tmax_max

        return disloc_est

    def get_delta_slip(
            self,
            store=None,
            deltat=None,
            delta=True,
            interpolation='nearest_neighbor',
            **kwargs):
        '''
        Get slip change snapshots.

        The time interval, within which the slip changes are computed is
        determined by the sampling rate of the Green's function database or
        ``deltat``. Additional ``**kwargs`` are passed to :py:meth:`get_slip`.

        :param store:
            Green's function database (needs to cover whole region of of the
            source). Its sampling interval is used as time increment for slip
            difference calculation. Either ``deltat`` or ``store`` should be
            given.
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param deltat:
            Time interval for slip difference calculation [s]. Either
            ``deltat`` or ``store`` should be given.
        :type deltat:
            float

        :param delta:
            If ``True``, slip differences between two time steps are given. If
            ``False``, cumulative slip for all time steps.
        :type delta:
            bool

        :param interpolation:
            Interpolation method to use (choose between ``'nearest_neighbor'``
            and ``'multilinear'``).
        :type interpolation:
            str

        :returns:
            Displacement changes(:math:`\\Delta u_{strike},
            \\Delta u_{dip} , \\Delta u_{tensile}`) for each source patch and
            time; corner times, for which delta slip is computed. The order of
            displacement changes array is:

            .. math::

                &[[\\\\
                &[\\Delta u_{strike, patch1, t1},
                    \\Delta u_{dip, patch1, t1},
                    \\Delta u_{tensile, patch1, t1}],\\\\
                &[\\Delta u_{strike, patch1, t2},
                    \\Delta u_{dip, patch1, t2},
                    \\Delta u_{tensile, patch1, t2}]\\\\
                &], [\\\\
                &[\\Delta u_{strike, patch2, t1}, ...],\\\\
                &[\\Delta u_{strike, patch2, t2}, ...]]]\\\\

        :rtype: :py:class:`~numpy.ndarray`: ``(n_sources, n_times, 3)``,
                :py:class:`~numpy.ndarray`: ``(n_times, )``
        '''
        if store and deltat:
            raise AttributeError(
                'Argument collision. '
                'Please define only the store or the deltat argument.')

        if store:
            deltat = store.config.deltat

        if not deltat:
            raise AttributeError('Please give a GF store or set deltat.')

        npatches = len(self.patches)

        _, _, _, _, time_interpolator, _ = self.get_vr_time_interpolators(
            store, interpolation=interpolation)
        tmax = time_interpolator.values.max()

        calc_times = num.arange(0., tmax + deltat, deltat)
        calc_times[calc_times > tmax] = tmax

        disloc_est = num.zeros((npatches, calc_times.size, 3))

        for itime, t in enumerate(calc_times):
            disloc_est[:, itime, :] = self.get_slip(
                time=t, scale_slip=False, **kwargs)

        if self.slip:
            disloc_tmax = num.linalg.norm(
                self.get_slip(scale_slip=False, time=tmax),
                axis=1)

            disloc_tmax_max = disloc_tmax.max()
            if disloc_tmax_max == 0.:
                logger.warning(
                    'Slip scaling not performed. Maximum slip is 0.')
            else:
                disloc_est *= self.slip / disloc_tmax_max

        if not delta:
            return disloc_est, calc_times

        # if we have only one timestep there is no gradient
        if calc_times.size > 1:
            disloc_init = disloc_est[:, 0, :]
            disloc_est = num.diff(disloc_est, axis=1)
            disloc_est = num.concatenate((
               disloc_init[:, num.newaxis, :], disloc_est), axis=1)

            calc_times = calc_times

        return disloc_est, calc_times

    def get_slip_rate(self, *args, **kwargs):
        '''
        Get slip rate inverted from patches.

        The time interval, within which the slip rates are computed is
        determined by the sampling rate of the Green's function database or
        ``deltat``. Additional ``*args`` and ``**kwargs`` are passed to
        :py:meth:`get_delta_slip`.

        :returns:
            Slip rates (:math:`\\Delta u_{strike}/\\Delta t`,
            :math:`\\Delta u_{dip}/\\Delta t, \\Delta u_{tensile}/\\Delta t`)
            for each source patch and time; corner times, for which slip rate
            is computed. The order of sliprate array is:

            .. math::

                &[[\\\\
                &[\\Delta u_{strike, patch1, t1}/\\Delta t,
                    \\Delta u_{dip, patch1, t1}/\\Delta t,
                    \\Delta u_{tensile, patch1, t1}/\\Delta t],\\\\
                &[\\Delta u_{strike, patch1, t2}/\\Delta t,
                    \\Delta u_{dip, patch1, t2}/\\Delta t,
                    \\Delta u_{tensile, patch1, t2}/\\Delta t]], [\\\\
                &[\\Delta u_{strike, patch2, t1}/\\Delta t, ...],\\\\
                &[\\Delta u_{strike, patch2, t2}/\\Delta t, ...]]]\\\\

        :rtype: :py:class:`~numpy.ndarray`: ``(n_sources, n_times, 3)``,
                :py:class:`~numpy.ndarray`: ``(n_times, )``
        '''
        ddisloc_est, calc_times = self.get_delta_slip(
            *args, delta=True, **kwargs)

        dt = num.concatenate(
            [(num.diff(calc_times)[0], ), num.diff(calc_times)])
        slip_rate = num.linalg.norm(ddisloc_est, axis=2) / dt

        return slip_rate, calc_times

    def get_moment_rate_patches(self, *args, **kwargs):
        '''
        Get scalar seismic moment rate for each patch individually.

        Additional ``*args`` and ``**kwargs`` are passed to
        :py:meth:`get_slip_rate`.

        :returns:
            Seismic moment rate for each source patch and time; corner times,
            for which patch moment rate is computed based on slip rate. The
            order of the moment rate array is:

            .. math::

                &[\\\\
                &[(\\Delta M / \\Delta t)_{patch1, t1},
                    (\\Delta M / \\Delta t)_{patch1, t2}, ...],\\\\
                &[(\\Delta M / \\Delta t)_{patch2, t1},
                    (\\Delta M / \\Delta t)_{patch, t2}, ...],\\\\
                &[...]]\\\\

        :rtype: :py:class:`~numpy.ndarray`: ``(n_sources, n_times)``,
                :py:class:`~numpy.ndarray`: ``(n_times, )``
        '''
        slip_rate, calc_times = self.get_slip_rate(*args, **kwargs)

        shear_mod = self.get_patch_attribute('shearmod')
        p_length = self.get_patch_attribute('length')
        p_width = self.get_patch_attribute('width')

        dA = p_length * p_width

        mom_rate = shear_mod[:, num.newaxis] * slip_rate * dA[:, num.newaxis]

        return mom_rate, calc_times

    def get_moment_rate(self, store, target=None, deltat=None):
        '''
        Get seismic source moment rate for the total source (STF).

        :param store:
            Green's function database (needs to cover whole region of of the
            source). Its ``deltat`` [s] is used as time increment for slip
            difference calculation. Either ``deltat`` or ``store`` should be
            given.
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :param target:
            Target information, needed for interpolation method.
        :type target:
            :py:class:`~pyrocko.gf.targets.Target`

        :param deltat:
            Time increment for slip difference calculation [s]. If not given
            ``store.deltat`` is used.
        :type deltat:
            float

        :return:
            Seismic moment rate [Nm/s] for each time; corner times, for which
            moment rate is computed. The order of the moment rate array is:

            .. math::

                &[\\\\
                &(\\Delta M / \\Delta t)_{t1},\\\\
                &(\\Delta M / \\Delta t)_{t2},\\\\
                &...]\\\\

        :rtype:
            :py:class:`~numpy.ndarray`: ``(n_times, )``,
            :py:class:`~numpy.ndarray`: ``(n_times, )``
        '''
        if not deltat:
            deltat = store.config.deltat
        return self.discretize_basesource(
            store, target=target).get_moment_rate(deltat)

    def get_moment(self, *args, **kwargs):
        '''
        Get cumulative seismic moment.

        Additional ``*args`` and ``**kwargs`` are passed to
        :py:meth:`get_magnitude`.

        :returns:
            Cumulative seismic moment in [Nm].
        :rtype:
            float
        '''
        return float(pmt.magnitude_to_moment(self.get_magnitude(
            *args, **kwargs)))

    def rescale_slip(self, magnitude=None, moment=None, **kwargs):
        '''
        Rescale source slip based on given target magnitude or seismic moment.

        Rescale the maximum source slip to fit the source moment magnitude or
        seismic moment to the given target values. Either ``magnitude`` or
        ``moment`` need to be given. Additional ``**kwargs`` are passed to
        :py:meth:`get_moment`.

        :param magnitude:
            Target moment magnitude :math:`M_\\mathrm{w}` as in
            [Hanks and Kanamori, 1979]
        :type magnitude:
            float

        :param moment:
            Target seismic moment :math:`M_0` [Nm].
        :type moment:
            float
        '''
        if self.slip is None:
            self.slip = 1.
            logger.warning('No slip found for rescaling. '
                           'An initial slip of 1 m is assumed.')

        if magnitude is None and moment is None:
            raise ValueError(
                'Either target magnitude or moment need to be given.')

        moment_init = self.get_moment(**kwargs)

        if magnitude is not None:
            moment = pmt.magnitude_to_moment(magnitude)

        self.slip *= moment / moment_init

    def get_centroid(self, store, *args, **kwargs):
        '''
        Centroid of the pseudo dynamic rupture model.

        The centroid location and time are derived from the locations and times
        of the individual patches weighted with their moment contribution.
        Additional ``**kwargs`` are passed to :py:meth:`pyrocko_moment_tensor`.

        :param store:
            Green's function database (needs to cover whole region of of the
            source). Its ``deltat`` [s] is used as time increment for slip
            difference calculation. Either ``deltat`` or ``store`` should be
            given.
        :type store:
            :py:class:`~pyrocko.gf.store.Store`

        :returns:
            The centroid location and associated moment tensor.
        :rtype:
            :py:class:`pyrocko.model.event.Event`
        '''
        _, _, _, _, time, _ = self.get_vr_time_interpolators(store)
        t_max = time.values.max()

        moment_rate, times = self.get_moment_rate_patches(deltat=t_max)

        moment = num.sum(moment_rate * times, axis=1)
        weights = moment / moment.sum()

        norths = self.get_patch_attribute('north_shift')
        easts = self.get_patch_attribute('east_shift')
        depths = self.get_patch_attribute('depth')

        centroid_n = num.sum(weights * norths)
        centroid_e = num.sum(weights * easts)
        centroid_d = num.sum(weights * depths)

        centroid_lat, centroid_lon = ne_to_latlon(
            self.lat, self.lon, centroid_n, centroid_e)

        moment_rate_, times = self.get_moment_rate(store)
        delta_times = num.concatenate((
            [times[1] - times[0]],
            num.diff(times)))
        moment_src = delta_times * moment_rate

        centroid_t = num.sum(
            moment_src / num.sum(moment_src) * times) + self.time

        mt = self.pyrocko_moment_tensor(store, *args, **kwargs)

        return model.Event(
            lat=centroid_lat,
            lon=centroid_lon,
            depth=centroid_d,
            time=centroid_t,
            moment_tensor=mt,
            magnitude=mt.magnitude,
            duration=t_max)

    def get_coulomb_failure_stress(
            self,
            receiver_points,
            friction,
            pressure,
            strike,
            dip,
            rake,
            time=None,
            *args,
            **kwargs):
        '''
        Calculate Coulomb failure stress change CFS.

        The function obtains the Coulomb failure stress change :math:`\\Delta
        \\sigma_C` at arbitrary receiver points with a commonly oriented
        receiver plane assuming:

        .. math::

            \\Delta \\sigma_C = \\sigma_S - \\mu (\\sigma_N - \\Delta p)

        with the shear stress :math:`\\sigma_S`, the coefficient of friction
        :math:`\\mu`, the normal stress :math:`\\sigma_N`, and the pore fluid
        pressure change :math:`\\Delta p`. Each receiver point is characterized
        by its geographical coordinates, and depth. The required receiver plane
        orientation is defined by ``strike``, ``dip``, and ``rake``. The
        Coulomb failure stress change is calculated for a given time after
        rupture origin time.

        :param receiver_points:
            Location of the receiver points in Northing, Easting, and depth in
            [m].
        :type receiver_points:
            :py:class:`~numpy.ndarray`: ``(n_receiver, 3)``

        :param friction:
            Coefficient of friction.
        :type friction:
            float

        :param pressure:
            Pore pressure change in [Pa].
        :type pressure:
            float

        :param strike:
            Strike of the receiver plane in [deg].
        :type strike:
            float

        :param dip:
            Dip of the receiver plane in [deg].
        :type dip:
            float

        :param rake:
            Rake of the receiver plane in [deg].
        :type rake:
            float

        :param time:
            Time after origin [s], for which the resulting :math:`\\Delta
            \\Sigma_c` is computed. If not given, :math:`\\Delta \\Sigma_c` is
            derived based on the final static slip.
        :type time:
            float

        :returns:
            The Coulomb failure stress change :math:`\\Delta \\Sigma_c` at each
            receiver point in [Pa].
        :rtype:
            :py:class:`~numpy.ndarray`: ``(n_receiver,)``
        '''
        # dislocation at given time
        source_slip = self.get_slip(time=time, scale_slip=True)

        # source planes
        source_patches = num.array([
            src.source_patch() for src in self.patches])

        # earth model
        lambda_mean = num.mean([src.lamb for src in self.patches])
        mu_mean = num.mean([src.shearmod for src in self.patches])

        # Dislocation and spatial derivatives from okada in NED
        results = okada_ext.okada(
            source_patches,
            source_slip,
            receiver_points,
            lambda_mean,
            mu_mean,
            rotate_sdn=False,  # TODO Check
            stack_sources=0,  # TODO Check
            *args, **kwargs)

        # resolve stress tensor (sum!)
        diag_ind = [0, 4, 8]
        kron = num.zeros(9)
        kron[diag_ind] = 1.
        kron = kron[num.newaxis, num.newaxis, :]

        eps = 0.5 * (
            results[:, :, 3:] +
            results[:, :, (3, 6, 9, 4, 7, 10, 5, 8, 11)])

        dilatation \
            = eps[:, :, diag_ind].sum(axis=-1)[:, :, num.newaxis]

        stress = kron*lambda_mean*dilatation + 2.*mu_mean*eps

        # superposed stress of all sources at receiver locations
        stress_sum = num.sum(stress, axis=0)

        # get shear and normal stress from stress tensor
        strike_rad = d2r * strike
        dip_rad = d2r * dip
        rake_rad = d2r * rake

        n_rec = receiver_points.shape[0]
        stress_normal = num.zeros(n_rec)
        tau = num.zeros(n_rec)

        # Get vectors in receiver fault normal (ns), strike (rst) and
        # dip (rdi) direction
        ns = num.zeros(3)
        rst = num.zeros(3)
        rdi = num.zeros(3)

        ns[0] = num.sin(dip_rad) * num.cos(strike_rad + 0.5 * num.pi)
        ns[1] = num.sin(dip_rad) * num.sin(strike_rad + 0.5 * num.pi)
        ns[2] = -num.cos(dip_rad)

        rst[0] = num.cos(strike_rad)
        rst[1] = num.sin(strike_rad)
        rst[2] = 0.0

        rdi[0] = num.cos(dip_rad) * num.cos(strike_rad + 0.5 * num.pi)
        rdi[1] = num.cos(dip_rad) * num.sin(strike_rad + 0.5 * num.pi)
        rdi[2] = num.sin(dip_rad)

        ts = rst * num.cos(rake_rad) - rdi * num.sin(rake_rad)

        stress_normal = num.sum(
            num.tile(ns, 3) * stress_sum * num.repeat(ns, 3), axis=1)

        tau = num.sum(
            num.tile(ts, 3) * stress_sum * num.repeat(ns, 3), axis=1)

        # calculate cfs using formula above and return
        return tau + friction * (stress_normal + pressure)


class DoubleDCSource(SourceWithMagnitude):
    '''
    Two double-couple point sources separated in space and time.
    Moment share between the sub-sources is controlled by the
    parameter mix.
    The position of the subsources is dependent on the moment
    distribution between the two sources. Depth, east and north
    shift are given for the centroid between the two double-couples.
    The subsources will positioned according to their moment shares
    around this centroid position.
    This is done according to their delta parameters, which are
    therefore in relation to that centroid.
    Note that depth of the subsources therefore can be
    depth+/-delta_depth. For shallow earthquakes therefore
    the depth has to be chosen deeper to avoid sampling
    above surface.
    '''

    strike1 = Float.T(
        default=0.0,
        help='strike direction in [deg], measured clockwise from north')

    dip1 = Float.T(
        default=90.0,
        help='dip angle in [deg], measured downward from horizontal')

    azimuth = Float.T(
        default=0.0,
        help='azimuth to second double-couple [deg], '
             'measured at first, clockwise from north')

    rake1 = Float.T(
        default=0.0,
        help='rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view')

    strike2 = Float.T(
        default=0.0,
        help='strike direction in [deg], measured clockwise from north')

    dip2 = Float.T(
        default=90.0,
        help='dip angle in [deg], measured downward from horizontal')

    rake2 = Float.T(
        default=0.0,
        help='rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view')

    delta_time = Float.T(
        default=0.0,
        help='separation of double-couples in time (t2-t1) [s]')

    delta_depth = Float.T(
        default=0.0,
        help='difference in depth (z2-z1) [m]')

    distance = Float.T(
        default=0.0,
        help='distance between the two double-couples [m]')

    mix = Float.T(
        default=0.5,
        help='how to distribute the moment to the two doublecouples '
             'mix=0 -> m1=1 and m2=0; mix=1 -> m1=0, m2=1')

    stf1 = STF.T(
        optional=True,
        help='Source time function of subsource 1 '
             '(if given, overrides STF from attribute :py:gattr:`Source.stf`)')

    stf2 = STF.T(
        optional=True,
        help='Source time function of subsource 2 '
             '(if given, overrides STF from attribute :py:gattr:`Source.stf`)')

    discretized_source_class = meta.DiscretizedMTSource

    def base_key(self):
        return (
            self.time, self.depth, self.lat, self.north_shift,
            self.lon, self.east_shift, type(self).__name__) + \
            self.effective_stf1_pre().base_key() + \
            self.effective_stf2_pre().base_key() + (
            self.strike1, self.dip1, self.rake1,
            self.strike2, self.dip2, self.rake2,
            self.delta_time, self.delta_depth,
            self.azimuth, self.distance, self.mix)

    def get_factor(self):
        return self.moment

    def effective_stf1_pre(self):
        return self.stf1 or self.stf or g_unit_pulse

    def effective_stf2_pre(self):
        return self.stf2 or self.stf or g_unit_pulse

    def effective_stf_post(self):
        return g_unit_pulse

    def split(self):
        a1 = 1.0 - self.mix
        a2 = self.mix
        delta_north = math.cos(self.azimuth * d2r) * self.distance
        delta_east = math.sin(self.azimuth * d2r) * self.distance

        dc1 = DCSource(
            lat=self.lat,
            lon=self.lon,
            time=self.time - self.delta_time * a2,
            north_shift=self.north_shift - delta_north * a2,
            east_shift=self.east_shift - delta_east * a2,
            depth=self.depth - self.delta_depth * a2,
            moment=self.moment * a1,
            strike=self.strike1,
            dip=self.dip1,
            rake=self.rake1,
            stf=self.stf1 or self.stf)

        dc2 = DCSource(
            lat=self.lat,
            lon=self.lon,
            time=self.time + self.delta_time * a1,
            north_shift=self.north_shift + delta_north * a1,
            east_shift=self.east_shift + delta_east * a1,
            depth=self.depth + self.delta_depth * a1,
            moment=self.moment * a2,
            strike=self.strike2,
            dip=self.dip2,
            rake=self.rake2,
            stf=self.stf2 or self.stf)

        return [dc1, dc2]

    def discretize_basesource(self, store, target=None):
        a1 = 1.0 - self.mix
        a2 = self.mix
        mot1 = pmt.MomentTensor(strike=self.strike1, dip=self.dip1,
                                rake=self.rake1, scalar_moment=a1)
        mot2 = pmt.MomentTensor(strike=self.strike2, dip=self.dip2,
                                rake=self.rake2, scalar_moment=a2)

        delta_north = math.cos(self.azimuth * d2r) * self.distance
        delta_east = math.sin(self.azimuth * d2r) * self.distance

        times1, amplitudes1 = self.effective_stf1_pre().discretize_t(
            store.config.deltat, self.time - self.delta_time * a2)

        times2, amplitudes2 = self.effective_stf2_pre().discretize_t(
            store.config.deltat, self.time + self.delta_time * a1)

        nt1 = times1.size
        nt2 = times2.size

        ds = meta.DiscretizedMTSource(
            lat=self.lat,
            lon=self.lon,
            times=num.concatenate((times1, times2)),
            north_shifts=num.concatenate((
                num.repeat(self.north_shift - delta_north * a2, nt1),
                num.repeat(self.north_shift + delta_north * a1, nt2))),
            east_shifts=num.concatenate((
                num.repeat(self.east_shift - delta_east * a2, nt1),
                num.repeat(self.east_shift + delta_east * a1, nt2))),
            depths=num.concatenate((
                num.repeat(self.depth - self.delta_depth * a2, nt1),
                num.repeat(self.depth + self.delta_depth * a1, nt2))),
            m6s=num.vstack((
                mot1.m6()[num.newaxis, :] * amplitudes1[:, num.newaxis],
                mot2.m6()[num.newaxis, :] * amplitudes2[:, num.newaxis])))

        return ds

    def pyrocko_moment_tensor(self, store=None, target=None):
        a1 = 1.0 - self.mix
        a2 = self.mix
        mot1 = pmt.MomentTensor(strike=self.strike1, dip=self.dip1,
                                rake=self.rake1,
                                scalar_moment=a1 * self.moment)
        mot2 = pmt.MomentTensor(strike=self.strike2, dip=self.dip2,
                                rake=self.rake2,
                                scalar_moment=a2 * self.moment)
        return pmt.MomentTensor(m=mot1.m() + mot2.m())

    def pyrocko_event(self, store=None, target=None, **kwargs):
        return SourceWithMagnitude.pyrocko_event(
            self, store, target,
            moment_tensor=self.pyrocko_moment_tensor(store, target),
            **kwargs)

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        d = {}
        mt = ev.moment_tensor
        if mt:
            (strike, dip, rake), _ = mt.both_strike_dip_rake()
            d.update(
                strike1=float(strike),
                dip1=float(dip),
                rake1=float(rake),
                strike2=float(strike),
                dip2=float(dip),
                rake2=float(rake),
                mix=0.0,
                magnitude=float(mt.moment_magnitude()))

        d.update(kwargs)
        source = super(DoubleDCSource, cls).from_pyrocko_event(ev, **d)
        source.stf1 = source.stf
        source.stf2 = HalfSinusoidSTF(effective_duration=0.)
        source.stf = None
        return source


class RingfaultSource(SourceWithMagnitude):
    '''
    A ring fault with vertical doublecouples.
    '''

    diameter = Float.T(
        default=1.0,
        help='diameter of the ring in [m]')

    sign = Float.T(
        default=1.0,
        help='inside of the ring moves up (+1) or down (-1)')

    strike = Float.T(
        default=0.0,
        help='strike direction of the ring plane, clockwise from north,'
             ' in [deg]')

    dip = Float.T(
        default=0.0,
        help='dip angle of the ring plane from horizontal in [deg]')

    npointsources = Int.T(
        default=360,
        help='number of point sources to use')

    discretized_source_class = meta.DiscretizedMTSource

    def base_key(self):
        return Source.base_key(self) + (
            self.strike, self.dip, self.diameter, self.npointsources)

    def get_factor(self):
        return self.sign * self.moment

    def discretize_basesource(self, store=None, target=None):
        n = self.npointsources
        phi = num.linspace(0, 2.0 * num.pi, n, endpoint=False)

        points = num.zeros((n, 3))
        points[:, 0] = num.cos(phi) * 0.5 * self.diameter
        points[:, 1] = num.sin(phi) * 0.5 * self.diameter

        rotmat = pmt.euler_to_matrix(self.dip * d2r, self.strike * d2r, 0.0)
        points = num.dot(rotmat.T, points.T).T  # !!! ?

        points[:, 0] += self.north_shift
        points[:, 1] += self.east_shift
        points[:, 2] += self.depth

        m = num.array(pmt.MomentTensor(strike=90., dip=90., rake=-90.,
                                       scalar_moment=1.0 / n).m())

        rotmats = num.transpose(
            [[num.cos(phi), num.sin(phi), num.zeros(n)],
             [-num.sin(phi), num.cos(phi), num.zeros(n)],
             [num.zeros(n), num.zeros(n), num.ones(n)]], (2, 0, 1))

        ms = num.zeros((n, 3, 3))
        for i in range(n):
            mtemp = num.dot(rotmats[i].T, num.dot(m, rotmats[i]))
            ms[i, :, :] = num.dot(rotmat.T, num.dot(mtemp, rotmat))

        m6s = num.vstack((ms[:, 0, 0], ms[:, 1, 1], ms[:, 2, 2],
                          ms[:, 0, 1], ms[:, 0, 2], ms[:, 1, 2])).T

        times, amplitudes = self.effective_stf_pre().discretize_t(
            store.config.deltat, self.time)

        nt = times.size

        return meta.DiscretizedMTSource(
            times=num.tile(times, n),
            lat=self.lat,
            lon=self.lon,
            north_shifts=num.repeat(points[:, 0], nt),
            east_shifts=num.repeat(points[:, 1], nt),
            depths=num.repeat(points[:, 2], nt),
            m6s=num.repeat(m6s, nt, axis=0) * num.tile(
                amplitudes, n)[:, num.newaxis])


class CombiSource(Source):
    '''
    Composite source model.
    '''

    discretized_source_class = meta.DiscretizedMTSource

    subsources = List.T(Source.T())

    def __init__(self, subsources=[], **kwargs):
        if not subsources:
            raise BadRequest(
                'Need at least one sub-source to create a CombiSource object.')

        lats = num.array(
            [subsource.lat for subsource in subsources], dtype=float)
        lons = num.array(
            [subsource.lon for subsource in subsources], dtype=float)

        lat, lon = lats[0], lons[0]
        if not num.all(lats == lat) and num.all(lons == lon):
            subsources = [s.clone() for s in subsources]
            for subsource in subsources[1:]:
                subsource.set_origin(lat, lon)

        depth = float(num.mean([p.depth for p in subsources]))
        time = float(num.mean([p.time for p in subsources]))
        north_shift = float(num.mean([p.north_shift for p in subsources]))
        east_shift = float(num.mean([p.east_shift for p in subsources]))
        kwargs.update(
            time=time,
            lat=float(lat),
            lon=float(lon),
            north_shift=north_shift,
            east_shift=east_shift,
            depth=depth)

        Source.__init__(self, subsources=subsources, **kwargs)

    def get_factor(self):
        return 1.0

    def discretize_basesource(self, store, target=None):
        dsources = []
        for sf in self.subsources:
            ds = sf.discretize_basesource(store, target)
            ds.m6s *= sf.get_factor()
            dsources.append(ds)

        return meta.DiscretizedMTSource.combine(dsources)


class CombiSFSource(Source):
    '''
    Composite source model.
    '''

    discretized_source_class = meta.DiscretizedSFSource

    subsources = List.T(Source.T())

    def __init__(self, subsources=[], **kwargs):
        if not subsources:
            raise BadRequest(
                'Need at least one sub-source to create a CombiSFSource '
                'object.')

        lats = num.array(
            [subsource.lat for subsource in subsources], dtype=float)
        lons = num.array(
            [subsource.lon for subsource in subsources], dtype=float)

        lat, lon = lats[0], lons[0]
        if not num.all(lats == lat) and num.all(lons == lon):
            subsources = [s.clone() for s in subsources]
            for subsource in subsources[1:]:
                subsource.set_origin(lat, lon)

        depth = float(num.mean([p.depth for p in subsources]))
        time = float(num.mean([p.time for p in subsources]))
        north_shift = float(num.mean([p.north_shift for p in subsources]))
        east_shift = float(num.mean([p.east_shift for p in subsources]))
        kwargs.update(
            time=time,
            lat=float(lat),
            lon=float(lon),
            north_shift=north_shift,
            east_shift=east_shift,
            depth=depth)

        Source.__init__(self, subsources=subsources, **kwargs)

    def get_factor(self):
        return 1.0

    def discretize_basesource(self, store, target=None):
        dsources = []
        for sf in self.subsources:
            ds = sf.discretize_basesource(store, target)
            ds.forces *= sf.get_factor()
            dsources.append(ds)

        return meta.DiscretizedSFSource.combine(dsources)


class SFSource(Source):
    '''
    A single force point source.

    Supported GF schemes: `'elastic5'`.
    '''

    discretized_source_class = meta.DiscretizedSFSource

    fn = Float.T(
        default=0.,
        help='northward component of single force [N]')

    fe = Float.T(
        default=0.,
        help='eastward component of single force [N]')

    fd = Float.T(
        default=0.,
        help='downward component of single force [N]')

    def __init__(self, **kwargs):
        Source.__init__(self, **kwargs)

    def base_key(self):
        return Source.base_key(self) + (self.fn, self.fe, self.fd)

    def get_factor(self):
        return 1.0

    @property
    def force(self):
        return math.sqrt(self.fn**2 + self.fe**2 + self.fd**2)

    def discretize_basesource(self, store, target=None):
        times, amplitudes = self.effective_stf_pre().discretize_t(
            store.config.deltat, self.time)
        forces = amplitudes[:, num.newaxis] * num.array(
            [[self.fn, self.fe, self.fd]], dtype=float)

        return meta.DiscretizedSFSource(forces=forces,
                                        **self._dparams_base_repeated(times))

    def pyrocko_event(self, store=None, target=None, **kwargs):
        return Source.pyrocko_event(
            self, store, target,
            **kwargs)

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        d = {}
        d.update(kwargs)
        return super(SFSource, cls).from_pyrocko_event(ev, **d)


class SimpleLandslideSource(Source):
    '''
    A single force landslide source respecting conservation of momentum.

    The landslide is modelled point-like in space but with individual source
    time functions for each force component. The source time functions
    :py:class:`SimpleLandslideSTF` impose the constraint that everything is at
    rest before and after the event but are allowed to have different
    acceleration and deceleration durations. It should thus be suitable as a
    first order approximation of a rock fall or landslide.
    For realistic landslides, the horizontal accelerations and decelerations
    can be delayed with respect to the vertical ones but cannot precede them.

    Supported GF schemes: `'elastic5'`.
    '''

    discretized_source_class = meta.DiscretizedSFSource

    stf_mode = STFMode.T(
        default='pre',
        help='SimpleLandslideSource only works with `stf_mode == "pre"`.')

    impulse_n = Float.T(
        default=0.,
        help='northward component of impulse [Ns]')

    impulse_e = Float.T(
        default=0.,
        help='eastward component of impulse [Ns]')

    impulse_d = Float.T(
        default=0.,
        help='downward component of impulse [Ns]')

    azimuth = Float.T(
        default=0.,
        help='azimuth direction of the mass movement [deg]')

    stf_v = SimpleLandslideSTF.T(
        default=SimpleLandslideSTF.D(),
        help='source time function for vertical force component')

    stf_h = SimpleLandslideSTF.T(
        default=SimpleLandslideSTF.D(),
        help='source time function for horizontal force component')

    anchor_stf = StringChoice.T(
        choices=['onset', 'centroid'],
        default='onset',
        help='``"onset"``: STFs start at origin time ``"centroid"``: STFs all '
             'start at the same time but so that the centroid is at the given '
             'origin time.')

    def __init__(self, **kwargs):
        Source.__init__(self, **kwargs)

    def base_key(self):
        return Source.base_key(self) + (
            self.impulse_n, self.impulse_e, self.impulse_d) \
            + self.stf_v.base_key() + self.stf_h.base_key()

    def get_factor(self):
        return 1.0

    def get_tshift_centroid(self):
        if self.anchor_stf == 'centroid':
            duration_acc = num.array([
                self.stf_h.duration_acceleration,
                self.stf_h.duration_acceleration,
                self.stf_v.duration_acceleration], dtype=float)

            impulse = num.array([
                self.impulse_n,
                self.impulse_e,
                self.impulse_d], dtype=float)

            return - num.sum(duration_acc * impulse**2) \
                / num.sum(impulse**2)

        elif self.anchor_stf == 'onset':
            return 0.0
        else:
            raise ValueError('Invalid anchor_stf.')

    def discretize_basesource(self, store, target=None):
        if self.stf_mode != 'pre':
            raise Exception(
                'SimpleLandslideSource: '
                'Only works with `stf_mode == "pre"`.')

        if self.stf is not None:
            raise Exception(
                'SimpleLandslideSource: '
                'Setting `stf` is not supported: use `stf_v` and `stf_h`.')

        tshift_centroid = self.get_tshift_centroid()

        times, amplitudes = self.stf_v.discretize_t(
            store.config.deltat,
            self.time + tshift_centroid)

        forces_v = num.zeros((times.size, 3))
        forces_v[:, 2] = amplitudes * self.impulse_d

        dsource_v = meta.DiscretizedSFSource(
                forces=forces_v,
                **self._dparams_base_repeated(times))

        times, amplitudes = self.stf_h.discretize_t(
            store.config.deltat,
            self.time + tshift_centroid)

        forces_h = num.zeros((times.size, 3))
        forces_h[:, 0] = \
            amplitudes * self.impulse_n
        forces_h[:, 1] = \
            amplitudes * self.impulse_e

        dsource_h = meta.DiscretizedSFSource(
                forces=forces_h,
                **self._dparams_base_repeated(times))

        return meta.DiscretizedSFSource.combine([dsource_v, dsource_h])

    def pyrocko_event(self, store=None, target=None, **kwargs):
        return Source.pyrocko_event(
            self, store, target,
            **kwargs)

    @classmethod
    def from_pyrocko_event(cls, ev, **kwargs):
        d = {}
        d.update(kwargs)
        return super(SimpleLandslideSource, cls).from_pyrocko_event(ev, **d)


class PorePressurePointSource(Source):
    '''
    Excess pore pressure point source.

    For poro-elastic initial value problem where an excess pore pressure is
    brought into a small source volume.
    '''

    discretized_source_class = meta.DiscretizedPorePressureSource

    pp = Float.T(
        default=1.0,
        help='initial excess pore pressure in [Pa]')

    def base_key(self):
        return Source.base_key(self)

    def get_factor(self):
        return self.pp

    def discretize_basesource(self, store, target=None):
        return meta.DiscretizedPorePressureSource(pp=arr(1.0),
                                                  **self._dparams_base())


class PorePressureLineSource(Source):
    '''
    Excess pore pressure line source.

    The line source is centered at (north_shift, east_shift, depth).
    '''

    discretized_source_class = meta.DiscretizedPorePressureSource

    pp = Float.T(
        default=1.0,
        help='initial excess pore pressure in [Pa]')

    length = Float.T(
        default=0.0,
        help='length of the line source [m]')

    azimuth = Float.T(
        default=0.0,
        help='azimuth direction, clockwise from north [deg]')

    dip = Float.T(
        default=90.,
        help='dip direction, downward from horizontal [deg]')

    def base_key(self):
        return Source.base_key(self) + (self.azimuth, self.dip, self.length)

    def get_factor(self):
        return self.pp

    def discretize_basesource(self, store, target=None):

        n = 2 * int(math.ceil(self.length / num.min(store.config.deltas))) + 1

        a = num.linspace(-0.5 * self.length, 0.5 * self.length, n)

        sa = math.sin(self.azimuth * d2r)
        ca = math.cos(self.azimuth * d2r)
        sd = math.sin(self.dip * d2r)
        cd = math.cos(self.dip * d2r)

        points = num.zeros((n, 3))
        points[:, 0] = self.north_shift + a * ca * cd
        points[:, 1] = self.east_shift + a * sa * cd
        points[:, 2] = self.depth + a * sd

        return meta.DiscretizedPorePressureSource(
            times=num.full(n, self.time),
            lat=self.lat,
            lon=self.lon,
            north_shifts=points[:, 0],
            east_shifts=points[:, 1],
            depths=points[:, 2],
            pp=num.ones(n) / n)


class Request(Object):
    '''
    Synthetic seismogram computation request.

    ::

        Request(**kwargs)
        Request(sources, targets, **kwargs)
    '''

    sources = List.T(
        Source.T(),
        help='list of sources for which to produce synthetics.')

    targets = List.T(
        Target.T(),
        help='list of targets for which to produce synthetics.')

    @classmethod
    def args2kwargs(cls, args):
        if len(args) not in (0, 2, 3):
            raise BadRequest('Invalid arguments.')

        if len(args) == 2:
            return dict(sources=args[0], targets=args[1])
        else:
            return {}

    def __init__(self, *args, **kwargs):
        kwargs.update(self.args2kwargs(args))
        sources = kwargs.pop('sources', [])
        targets = kwargs.pop('targets', [])

        if isinstance(sources, Source):
            sources = [sources]

        if isinstance(targets, Target) or isinstance(targets, StaticTarget):
            targets = [targets]

        Object.__init__(self, sources=sources, targets=targets, **kwargs)

    @property
    def targets_dynamic(self):
        return [t for t in self.targets if isinstance(t, Target)]

    @property
    def targets_static(self):
        return [t for t in self.targets if isinstance(t, StaticTarget)]

    @property
    def has_dynamic(self):
        return True if len(self.targets_dynamic) > 0 else False

    @property
    def has_statics(self):
        return True if len(self.targets_static) > 0 else False

    def subsources_map(self):
        m = defaultdict(list)
        for source in self.sources:
            m[source.base_key()].append(source)

        return m

    def subtargets_map(self):
        m = defaultdict(list)
        for target in self.targets:
            m[target.base_key()].append(target)

        return m

    def subrequest_map(self):
        ms = self.subsources_map()
        mt = self.subtargets_map()
        m = {}
        for (ks, ls) in ms.items():
            for (kt, lt) in mt.items():
                m[ks, kt] = (ls, lt)

        return m


class ProcessingStats(Object):
    t_perc_get_store_and_receiver = Float.T(default=0.)
    t_perc_discretize_source = Float.T(default=0.)
    t_perc_make_base_seismogram = Float.T(default=0.)
    t_perc_make_same_span = Float.T(default=0.)
    t_perc_post_process = Float.T(default=0.)
    t_perc_optimize = Float.T(default=0.)
    t_perc_stack = Float.T(default=0.)
    t_perc_static_get_store = Float.T(default=0.)
    t_perc_static_discretize_basesource = Float.T(default=0.)
    t_perc_static_sum_statics = Float.T(default=0.)
    t_perc_static_post_process = Float.T(default=0.)
    t_wallclock = Float.T(default=0.)
    t_cpu = Float.T(default=0.)
    n_read_blocks = Int.T(default=0)
    n_results = Int.T(default=0)
    n_subrequests = Int.T(default=0)
    n_stores = Int.T(default=0)
    n_records_stacked = Int.T(default=0)


class Response(Object):
    '''
    Resonse object to a synthetic seismogram computation request.
    '''

    request = Request.T()
    results_list = List.T(List.T(meta.SeismosizerResult.T()))
    stats = ProcessingStats.T()

    def pyrocko_traces(self):
        '''
        Return a list of requested
        :class:`~pyrocko.trace.Trace` instances.
        '''

        traces = []
        for results in self.results_list:
            for result in results:
                if not isinstance(result, meta.Result):
                    continue
                traces.append(result.trace.pyrocko_trace())

        return traces

    def kite_scenes(self):
        '''
        Return a list of requested
        :class:`kite.Scene` instances.
        '''
        kite_scenes = []
        for results in self.results_list:
            for result in results:
                if isinstance(result, meta.KiteSceneResult):
                    sc = result.get_scene()
                    kite_scenes.append(sc)

        return kite_scenes

    def static_results(self):
        '''
        Return a list of requested
        :class:`~pyrocko.gf.meta.StaticResult` instances.
        '''
        statics = []
        for results in self.results_list:
            for result in results:
                if not isinstance(result, meta.StaticResult):
                    continue
                statics.append(result)

        return statics

    def iter_results(self, get='pyrocko_traces'):
        '''
        Generator function to iterate over results of request.

        Yields associated :py:class:`Source`,
        :class:`~pyrocko.gf.targets.Target`,
        :class:`~pyrocko.trace.Trace` instances in each iteration.
        '''

        for isource, source in enumerate(self.request.sources):
            for itarget, target in enumerate(self.request.targets):
                result = self.results_list[isource][itarget]
                if get == 'pyrocko_traces':
                    yield source, target, result.trace.pyrocko_trace()
                elif get == 'results':
                    yield source, target, result

    def snuffle(self, **kwargs):
        '''
        Open *snuffler* with requested traces.
        '''

        trace.snuffle(self.pyrocko_traces(), **kwargs)


class Engine(Object):
    '''
    Base class for synthetic seismogram calculators.
    '''

    def get_store_ids(self):
        '''
        Get list of available GF store IDs
        '''

        return []


class Rule(object):
    pass


class VectorRule(Rule):

    def __init__(self, quantity, differentiate=0, integrate=0):
        self.components = [quantity + '.' + c for c in 'ned']
        self.differentiate = differentiate
        self.integrate = integrate

    def required_components(self, target):
        n, e, d = self.components
        sa, ca, sd, cd = target.get_sin_cos_factors()

        comps = []
        if nonzero(ca * cd):
            comps.append(n)

        if nonzero(sa * cd):
            comps.append(e)

        if nonzero(sd):
            comps.append(d)

        return tuple(comps)

    def apply_(self, target, base_seismogram):
        n, e, d = self.components
        sa, ca, sd, cd = target.get_sin_cos_factors()

        if nonzero(ca * cd):
            data = base_seismogram[n].data * (ca * cd)
            deltat = base_seismogram[n].deltat
        else:
            data = 0.0

        if nonzero(sa * cd):
            data = data + base_seismogram[e].data * (sa * cd)
            deltat = base_seismogram[e].deltat

        if nonzero(sd):
            data = data + base_seismogram[d].data * sd
            deltat = base_seismogram[d].deltat

        if self.differentiate:
            data = util.diff_fd(self.differentiate, 4, deltat, data)

        if self.integrate:
            raise NotImplementedError('Integration is not implemented yet.')

        return data


class HorizontalVectorRule(Rule):

    def __init__(self, quantity, differentiate=0, integrate=0):
        self.components = [quantity + '.' + c for c in 'ne']
        self.differentiate = differentiate
        self.integrate = integrate

    def required_components(self, target):
        n, e = self.components
        sa, ca, _, _ = target.get_sin_cos_factors()

        comps = []
        if nonzero(ca):
            comps.append(n)

        if nonzero(sa):
            comps.append(e)

        return tuple(comps)

    def apply_(self, target, base_seismogram):
        n, e = self.components
        sa, ca, _, _ = target.get_sin_cos_factors()

        if nonzero(ca):
            data = base_seismogram[n].data * ca
        else:
            data = 0.0

        if nonzero(sa):
            data = data + base_seismogram[e].data * sa

        if self.differentiate:
            deltat = base_seismogram[e].deltat
            data = util.diff_fd(self.differentiate, 4, deltat, data)

        if self.integrate:
            raise NotImplementedError('Integration is not implemented yet.')

        return data


class ScalarRule(Rule):

    def __init__(self, quantity, differentiate=0):
        self.c = quantity

    def required_components(self, target):
        return (self.c, )

    def apply_(self, target, base_seismogram):
        data = base_seismogram[self.c].data.copy()
        deltat = base_seismogram[self.c].deltat
        if self.differentiate:
            data = util.diff_fd(self.differentiate, 4, deltat, data)

        return data


class StaticDisplacement(Rule):

    def required_components(self, target):
        return tuple(['displacement.%s' % c for c in list('ned')])

    def apply_(self, target, base_statics):
        if isinstance(target, SatelliteTarget):
            los_fac = target.get_los_factors()
            base_statics['displacement.los'] =\
                (los_fac[:, 0] * -base_statics['displacement.d'] +
                 los_fac[:, 1] * base_statics['displacement.e'] +
                 los_fac[:, 2] * base_statics['displacement.n'])
        return base_statics


channel_rules = {
    'displacement': [VectorRule('displacement')],
    'rotation_displacement': [VectorRule('rotation_displacement')],
    'velocity': [
        VectorRule('velocity'),
        VectorRule('displacement', differentiate=1)],
    'acceleration': [
        VectorRule('acceleration'),
        VectorRule('velocity', differentiate=1),
        VectorRule('displacement', differentiate=2)],
    'pore_pressure': [ScalarRule('pore_pressure')],
    'vertical_tilt': [HorizontalVectorRule('vertical_tilt')],
    'darcy_velocity': [VectorRule('darcy_velocity')],
}

static_rules = {
    'displacement': [StaticDisplacement()]
}


class OutOfBoundsContext(Object):
    source = Source.T()
    target = Target.T()
    distance = Float.T()
    components = List.T(String.T())


def process_dynamic_timeseries(work, psources, ptargets, engine, nthreads=0):
    dsource_cache = {}
    tcounters = list(range(6))

    store_ids = set()
    sources = set()
    targets = set()

    for itarget, target in enumerate(ptargets):
        target._id = itarget

    for w in work:
        _, _, isources, itargets = w

        sources.update([psources[isource] for isource in isources])
        targets.update([ptargets[itarget] for itarget in itargets])

    store_ids = set([t.store_id for t in targets])

    for isource, source in enumerate(psources):

        components = set()
        for itarget, target in enumerate(targets):
            rule = engine.get_rule(source, target)
            components.update(rule.required_components(target))

        for store_id in store_ids:
            store_targets = [t for t in targets if t.store_id == store_id]

            sample_rates = set([t.sample_rate for t in store_targets])
            interpolations = set([t.interpolation for t in store_targets])

            base_seismograms = []
            store_targets_out = []

            for samp_rate in sample_rates:
                for interp in interpolations:
                    engine_targets = [
                        t for t in store_targets if t.sample_rate == samp_rate
                        and t.interpolation == interp]

                    if not engine_targets:
                        continue

                    store_targets_out += engine_targets

                    base_seismograms += engine.base_seismograms(
                        source,
                        engine_targets,
                        components,
                        dsource_cache,
                        nthreads)

            for iseis, seismogram in enumerate(base_seismograms):
                for tr in seismogram.values():
                    if tr.err != store.SeismosizerErrorEnum.SUCCESS:
                        e = SeismosizerError(
                            'Seismosizer failed with return code %i\n%s' % (
                                tr.err, str(
                                    OutOfBoundsContext(
                                        source=source,
                                        target=store_targets[iseis],
                                        distance=source.distance_to(
                                            store_targets[iseis]),
                                        components=components))))
                        raise e

            for seismogram, target in zip(base_seismograms, store_targets_out):

                try:
                    result = engine._post_process_dynamic(
                        seismogram, source, target)
                except SeismosizerError as e:
                    result = e

                yield (isource, target._id, result), tcounters


def process_dynamic(work, psources, ptargets, engine, nthreads=0):
    dsource_cache = {}

    for w in work:
        _, _, isources, itargets = w

        sources = [psources[isource] for isource in isources]
        targets = [ptargets[itarget] for itarget in itargets]

        components = set()
        for target in targets:
            rule = engine.get_rule(sources[0], target)
            components.update(rule.required_components(target))

        for isource, source in zip(isources, sources):
            for itarget, target in zip(itargets, targets):

                try:
                    base_seismogram, tcounters = engine.base_seismogram(
                        source, target, components, dsource_cache, nthreads)
                except meta.OutOfBounds as e:
                    e.context = OutOfBoundsContext(
                        source=sources[0],
                        target=targets[0],
                        distance=sources[0].distance_to(targets[0]),
                        components=components)
                    raise

                n_records_stacked = 0
                t_optimize = 0.0
                t_stack = 0.0

                for _, tr in base_seismogram.items():
                    n_records_stacked += tr.n_records_stacked
                    t_optimize += tr.t_optimize
                    t_stack += tr.t_stack

                try:
                    result = engine._post_process_dynamic(
                        base_seismogram, source, target)
                    result.n_records_stacked = n_records_stacked
                    result.n_shared_stacking = len(sources) *\
                        len(targets)
                    result.t_optimize = t_optimize
                    result.t_stack = t_stack
                except SeismosizerError as e:
                    result = e

                tcounters.append(xtime())
                yield (isource, itarget, result), tcounters


def process_static(work, psources, ptargets, engine, nthreads=0):
    for w in work:
        _, _, isources, itargets = w

        sources = [psources[isource] for isource in isources]
        targets = [ptargets[itarget] for itarget in itargets]

        for isource, source in zip(isources, sources):
            for itarget, target in zip(itargets, targets):
                components = engine.get_rule(source, target)\
                    .required_components(target)

                try:
                    base_statics, tcounters = engine.base_statics(
                        source, target, components, nthreads)
                except meta.OutOfBounds as e:
                    e.context = OutOfBoundsContext(
                        source=sources[0],
                        target=targets[0],
                        distance=float('nan'),
                        components=components)
                    raise
                result = engine._post_process_statics(
                    base_statics, source, target)
                tcounters.append(xtime())

                yield (isource, itarget, result), tcounters


class LocalEngine(Engine):
    '''
    Offline synthetic seismogram calculator.

    :param use_env: if ``True``, fill :py:attr:`store_superdirs` and
        :py:attr:`store_dirs` with paths set in environment variables
        GF_STORE_SUPERDIRS and GF_STORE_DIRS.
    :param use_config: if ``True``, fill :py:attr:`store_superdirs` and
        :py:attr:`store_dirs` with paths set in the user's config file.

        The config file can be found at :file:`~/.pyrocko/config.pf`

        .. code-block :: python

            gf_store_dirs: ['/home/pyrocko/gf_stores/ak135/']
            gf_store_superdirs: ['/home/pyrocko/gf_stores/']
    '''

    store_superdirs = List.T(
        String.T(),
        help="directories which are searched for Green's function stores")

    store_dirs = List.T(
        String.T(),
        help="additional individual Green's function store directories")

    default_store_id = String.T(
        optional=True,
        help='default store ID to be used when a request does not provide '
             'one')

    nthreads = Int.T(
        default=1,
        help='default number of threads to utilize')

    def __init__(self, **kwargs):
        use_env = kwargs.pop('use_env', False)
        use_config = kwargs.pop('use_config', False)
        Engine.__init__(self, **kwargs)
        if use_env:
            env_store_superdirs = os.environ.get('GF_STORE_SUPERDIRS', '')
            env_store_dirs = os.environ.get('GF_STORE_DIRS', '')
            if env_store_superdirs:
                self.store_superdirs.extend(env_store_superdirs.split(':'))

            if env_store_dirs:
                self.store_dirs.extend(env_store_dirs.split(':'))

        if use_config:
            c = config.config()
            self.store_superdirs.extend(c.gf_store_superdirs)
            self.store_dirs.extend(c.gf_store_dirs)

        self._check_store_dirs_type()
        self._id_to_store_dir = {}
        self._open_stores = {}
        self._effective_default_store_id = None

    def _check_store_dirs_type(self):
        for sdir in ['store_dirs', 'store_superdirs']:
            if not isinstance(self.__getattribute__(sdir), list):
                raise TypeError('{} of {} is not of type list'.format(
                    sdir, self.__class__.__name__))

    def _get_store_id(self, store_dir):
        store_ = store.Store(store_dir)
        store_id = store_.config.id
        store_.close()
        return store_id

    def _looks_like_store_dir(self, store_dir):
        return os.path.isdir(store_dir) and \
            all(os.path.isfile(pjoin(store_dir, x)) for x in
                ('index', 'traces', 'config'))

    def iter_store_dirs(self):
        store_dirs = set()
        for d in self.store_superdirs:
            if not os.path.exists(d):
                logger.warning('store_superdir not available: %s' % d)
                continue

            for entry in os.listdir(d):
                store_dir = os.path.realpath(pjoin(d, entry))
                if self._looks_like_store_dir(store_dir):
                    store_dirs.add(store_dir)

        for store_dir in self.store_dirs:
            store_dirs.add(os.path.realpath(store_dir))

        return store_dirs

    def _scan_stores(self):
        for store_dir in self.iter_store_dirs():
            store_id = self._get_store_id(store_dir)
            if store_id not in self._id_to_store_dir:
                self._id_to_store_dir[store_id] = store_dir
            else:
                if store_dir != self._id_to_store_dir[store_id]:
                    raise DuplicateStoreId(
                        'GF store ID %s is used in (at least) two '
                        'different stores. Locations are: %s and %s' %
                        (store_id, self._id_to_store_dir[store_id], store_dir))

    def get_store_dir(self, store_id):
        '''
        Lookup directory given a GF store ID.
        '''

        if store_id not in self._id_to_store_dir:
            self._scan_stores()

        if store_id not in self._id_to_store_dir:
            raise NoSuchStore(
                store_id,
                self.store_dirs,
                self.store_superdirs,
                sorted(self._id_to_store_dir.keys()))

        return self._id_to_store_dir[store_id]

    def get_store_ids(self):
        '''
        Get list of available store IDs.
        '''

        self._scan_stores()
        return sorted(self._id_to_store_dir.keys())

    def effective_default_store_id(self):
        if self._effective_default_store_id is None:
            if self.default_store_id is None:
                store_ids = self.get_store_ids()
                if len(store_ids) == 1:
                    self._effective_default_store_id = self.get_store_ids()[0]
                else:
                    raise NoDefaultStoreSet()
            else:
                self._effective_default_store_id = self.default_store_id

        return self._effective_default_store_id

    def get_store(self, store_id=None):
        '''
        Get a store from the engine.

        :param store_id: identifier of the store (optional)
        :returns: :py:class:`~pyrocko.gf.store.Store` object

        If no ``store_id`` is provided the store
        associated with the :py:gattr:`default_store_id` is returned.
        Raises :py:exc:`NoDefaultStoreSet` if :py:gattr:`default_store_id` is
        undefined.
        '''

        if store_id is None:
            store_id = self.effective_default_store_id()

        if store_id not in self._open_stores:
            store_dir = self.get_store_dir(store_id)
            self._open_stores[store_id] = store.Store(store_dir)

        return self._open_stores[store_id]

    def get_store_config(self, store_id):
        store = self.get_store(store_id)
        return store.config

    def get_store_extra(self, store_id, key):
        store = self.get_store(store_id)
        return store.get_extra(key)

    def close_cashed_stores(self):
        '''
        Close and remove ids from cashed stores.
        '''
        store_ids = []
        for store_id, store_ in self._open_stores.items():
            store_.close()
            store_ids.append(store_id)

        for store_id in store_ids:
            self._open_stores.pop(store_id)

    def get_rule(self, source, target):
        cprovided = self.get_store(target.store_id).get_provided_components()

        if isinstance(target, StaticTarget):
            quantity = target.quantity
            available_rules = static_rules
        elif isinstance(target, Target):
            quantity = target.effective_quantity()
            available_rules = channel_rules

        try:
            for rule in available_rules[quantity]:
                cneeded = rule.required_components(target)
                if all(c in cprovided for c in cneeded):
                    return rule

        except KeyError:
            pass

        raise BadRequest(
            'No rule to calculate "%s" with GFs from store "%s" '
            'for source model "%s".' % (
                target.effective_quantity(),
                target.store_id,
                source.__class__.__name__))

    def _cached_discretize_basesource(self, source, store, cache, target):
        if (source, store) not in cache:
            cache[source, store] = source.discretize_basesource(store, target)

        return cache[source, store]

    def base_seismograms(self, source, targets, components, dsource_cache,
                         nthreads=None):

        target = targets[0]

        interp = set([t.interpolation for t in targets])
        if len(interp) > 1:
            raise BadRequest('Targets have different interpolation schemes.')

        rates = set([t.sample_rate for t in targets])
        if len(rates) > 1:
            raise BadRequest('Targets have different sample rates.')

        store_ = self.get_store(target.store_id)
        receivers = [t.receiver(store_) for t in targets]

        if target.sample_rate is not None:
            deltat = 1. / target.sample_rate
            rate = target.sample_rate
        else:
            deltat = None
            rate = store_.config.sample_rate

        tmin = num.fromiter(
            (t.tmin for t in targets), dtype=float, count=len(targets))
        tmax = num.fromiter(
            (t.tmax for t in targets), dtype=float, count=len(targets))

        mask = num.logical_and(num.isfinite(tmin), num.isfinite(tmax))

        itmin = num.zeros_like(tmin, dtype=num.int64)
        itmax = num.zeros_like(tmin, dtype=num.int64)
        nsamples = num.full_like(tmin, -1, dtype=num.int64)

        itmin[mask] = num.floor(tmin[mask] * rate).astype(num.int64)
        itmax[mask] = num.ceil(tmax[mask] * rate).astype(num.int64)
        nsamples = itmax - itmin + 1
        nsamples[num.logical_not(mask)] = -1

        base_source = self._cached_discretize_basesource(
            source, store_, dsource_cache, target)

        base_seismograms = store_.calc_seismograms(
            base_source, receivers, components,
            deltat=deltat,
            itmin=itmin, nsamples=nsamples,
            interpolation=target.interpolation,
            optimization=target.optimization,
            nthreads=nthreads if nthreads is not None else 1)

        for i, base_seismogram in enumerate(base_seismograms):
            base_seismograms[i] = store.make_same_span(base_seismogram)

        return base_seismograms

    def base_seismogram(self, source, target, components, dsource_cache,
                        nthreads):

        tcounters = [xtime()]

        store_ = self.get_store(target.store_id)
        receiver = target.receiver(store_)

        if target.tmin and target.tmax is not None:
            rate = store_.config.sample_rate
            itmin = int(num.floor(target.tmin * rate))
            itmax = int(num.ceil(target.tmax * rate))
            nsamples = itmax - itmin + 1
        else:
            itmin = None
            nsamples = None

        tcounters.append(xtime())
        base_source = self._cached_discretize_basesource(
            source, store_, dsource_cache, target)

        tcounters.append(xtime())

        if target.sample_rate is not None:
            deltat = 1. / target.sample_rate
        else:
            deltat = None

        base_seismogram = store_.seismogram(
            base_source, receiver, components,
            deltat=deltat,
            itmin=itmin, nsamples=nsamples,
            interpolation=target.interpolation,
            optimization=target.optimization,
            nthreads=nthreads)

        tcounters.append(xtime())

        base_seismogram = store.make_same_span(base_seismogram)

        tcounters.append(xtime())

        return base_seismogram, tcounters

    def base_statics(self, source, target, components, nthreads):
        tcounters = [xtime()]
        store_ = self.get_store(target.store_id)

        if target.tsnapshot is not None:
            rate = store_.config.sample_rate
            itsnapshot = int(num.floor(target.tsnapshot * rate))
        else:
            itsnapshot = None
        tcounters.append(xtime())

        base_source = source.discretize_basesource(store_, target=target)

        tcounters.append(xtime())

        base_statics = store_.statics(
            base_source,
            target,
            itsnapshot,
            components,
            target.interpolation,
            nthreads)

        tcounters.append(xtime())

        return base_statics, tcounters

    def _post_process_dynamic(self, base_seismogram, source, target):
        base_any = next(iter(base_seismogram.values()))
        deltat = base_any.deltat
        itmin = base_any.itmin

        rule = self.get_rule(source, target)
        data = rule.apply_(target, base_seismogram)

        factor = source.get_factor() * target.get_factor()
        if factor != 1.0:
            data = data * factor

        stf = source.effective_stf_post()

        times, amplitudes = stf.discretize_t(
            deltat, 0.0)

        # repeat end point to prevent boundary effects
        padded_data = num.empty(data.size + amplitudes.size, dtype=float)
        padded_data[:data.size] = data
        padded_data[data.size:] = data[-1]
        data = num.convolve(amplitudes, padded_data)

        tmin = itmin * deltat + times[0]

        tr = meta.SeismosizerTrace(
            codes=target.codes,
            data=data[:-amplitudes.size],
            deltat=deltat,
            tmin=tmin)

        return target.post_process(self, source, tr)

    def _post_process_statics(self, base_statics, source, starget):
        rule = self.get_rule(source, starget)
        data = rule.apply_(starget, base_statics)

        factor = source.get_factor()
        if factor != 1.0:
            for v in data.values():
                v *= factor

        return starget.post_process(self, source, base_statics)

    def process(self, *args, **kwargs):
        '''
        Process a request.

        ::

            process(**kwargs)
            process(request, **kwargs)
            process(sources, targets, **kwargs)

        The request can be given a a :py:class:`Request` object, or such an
        object is created using ``Request(**kwargs)`` for convenience.

        :returns: :py:class:`Response` object
        '''

        if len(args) not in (0, 1, 2):
            raise BadRequest('Invalid arguments.')

        if len(args) == 1:
            kwargs['request'] = args[0]

        elif len(args) == 2:
            kwargs.update(Request.args2kwargs(args))

        request = kwargs.pop('request', None)
        status_callback = kwargs.pop('status_callback', None)
        calc_timeseries = kwargs.pop('calc_timeseries', True)

        nprocs = kwargs.pop('nprocs', None)
        if nprocs is not None:
            raise BadRequest(
                'The `nprocs` keyword argument to process is no longer '
                'available. Please use `nthreads`.')

        nthreads = kwargs.pop('nthreads', self.nthreads)

        if request is None:
            request = Request(**kwargs)

        if resource:
            rs0 = resource.getrusage(resource.RUSAGE_SELF)
            rc0 = resource.getrusage(resource.RUSAGE_CHILDREN)
        tt0 = xtime()

        # make sure stores are open before fork()
        store_ids = set(target.store_id for target in request.targets)
        for store_id in store_ids:
            self.get_store(store_id)

        source_index = dict((x, i) for (i, x) in
                            enumerate(request.sources))
        target_index = dict((x, i) for (i, x) in
                            enumerate(request.targets))

        m = request.subrequest_map()

        skeys = sorted(m.keys(), key=cmp_to_key(cmp_none_aware))
        results_list = []

        for i in range(len(request.sources)):
            results_list.append([None] * len(request.targets))

        tcounters_dyn_list = []
        tcounters_static_list = []
        nsub = len(skeys)
        isub = 0

        # Processing dynamic targets through
        # parimap(process_subrequest_dynamic)

        if calc_timeseries:
            _process_dynamic = process_dynamic_timeseries
        else:
            _process_dynamic = process_dynamic

        if request.has_dynamic:
            work_dynamic = [
                (i, nsub,
                 [source_index[source] for source in m[k][0]],
                 [target_index[target] for target in m[k][1]
                  if not isinstance(target, StaticTarget)])
                for (i, k) in enumerate(skeys)]

            for ii_results, tcounters_dyn in _process_dynamic(
                    work_dynamic, request.sources, request.targets, self,
                    nthreads):

                tcounters_dyn_list.append(num.diff(tcounters_dyn))
                isource, itarget, result = ii_results
                results_list[isource][itarget] = result

                if status_callback:
                    status_callback(isub, nsub)

                isub += 1

        # Processing static targets through process_static
        if request.has_statics:
            work_static = [
                (i, nsub,
                 [source_index[source] for source in m[k][0]],
                 [target_index[target] for target in m[k][1]
                  if isinstance(target, StaticTarget)])
                for (i, k) in enumerate(skeys)]

            for ii_results, tcounters_static in process_static(
                    work_static, request.sources, request.targets, self,
                    nthreads=nthreads):

                tcounters_static_list.append(num.diff(tcounters_static))
                isource, itarget, result = ii_results
                results_list[isource][itarget] = result

                if status_callback:
                    status_callback(isub, nsub)

                isub += 1

        if status_callback:
            status_callback(nsub, nsub)

        tt1 = time.time()
        if resource:
            rs1 = resource.getrusage(resource.RUSAGE_SELF)
            rc1 = resource.getrusage(resource.RUSAGE_CHILDREN)

        s = ProcessingStats()

        if request.has_dynamic:
            tcumu_dyn = num.sum(num.vstack(tcounters_dyn_list), axis=0)
            t_dyn = float(num.sum(tcumu_dyn))
            perc_dyn = map(float, tcumu_dyn / t_dyn * 100.)
            (s.t_perc_get_store_and_receiver,
             s.t_perc_discretize_source,
             s.t_perc_make_base_seismogram,
             s.t_perc_make_same_span,
             s.t_perc_post_process) = perc_dyn
        else:
            t_dyn = 0.

        if request.has_statics:
            tcumu_static = num.sum(num.vstack(tcounters_static_list), axis=0)
            t_static = num.sum(tcumu_static)
            perc_static = map(float, tcumu_static / t_static * 100.)
            (s.t_perc_static_get_store,
             s.t_perc_static_discretize_basesource,
             s.t_perc_static_sum_statics,
             s.t_perc_static_post_process) = perc_static

        s.t_wallclock = tt1 - tt0
        if resource:
            s.t_cpu = (
                (rs1.ru_utime + rs1.ru_stime + rc1.ru_utime + rc1.ru_stime) -
                (rs0.ru_utime + rs0.ru_stime + rc0.ru_utime + rc0.ru_stime))
            s.n_read_blocks = (
                (rs1.ru_inblock + rc1.ru_inblock) -
                (rs0.ru_inblock + rc0.ru_inblock))

        n_records_stacked = 0.
        for results in results_list:
            for result in results:
                if not isinstance(result, meta.Result):
                    continue
                shr = float(result.n_shared_stacking)
                n_records_stacked += result.n_records_stacked / shr
                s.t_perc_optimize += result.t_optimize / shr
                s.t_perc_stack += result.t_stack / shr
        s.n_records_stacked = int(n_records_stacked)
        if t_dyn != 0.:
            s.t_perc_optimize /= t_dyn * 100
            s.t_perc_stack /= t_dyn * 100

        return Response(
            request=request,
            results_list=results_list,
            stats=s)


class RemoteEngine(Engine):
    '''
    Client for remote synthetic seismogram calculator.
    '''

    site = String.T(default=ws.g_default_site, optional=True)
    url = String.T(default=ws.g_url, optional=True)

    def process(self, request=None, status_callback=None, **kwargs):

        if request is None:
            request = Request(**kwargs)

        return ws.seismosizer(url=self.url, site=self.site, request=request)


g_engine = None


def get_engine(store_superdirs=[]):
    global g_engine
    if g_engine is None:
        g_engine = LocalEngine(use_env=True, use_config=True)

    for d in store_superdirs:
        if d not in g_engine.store_superdirs:
            g_engine.store_superdirs.append(d)

    return g_engine


class SourceGroup(Object):

    def __getattr__(self, k):
        return num.fromiter((getattr(s, k) for s in self),
                            dtype=float)

    def __iter__(self):
        raise NotImplementedError(
            'This method should be implemented in subclass.')

    def __len__(self):
        raise NotImplementedError(
            'This method should be implemented in subclass.')


class SourceList(SourceGroup):
    sources = List.T(Source.T())

    def append(self, s):
        self.sources.append(s)

    def __iter__(self):
        return iter(self.sources)

    def __len__(self):
        return len(self.sources)


class SourceGrid(SourceGroup):

    base = Source.T()
    variables = Dict.T(String.T(), Range.T())
    order = List.T(String.T())

    def __len__(self):
        n = 1
        for (k, v) in self.make_coords(self.base):
            n *= len(list(v))

        return n

    def __iter__(self):
        for items in permudef(self.make_coords(self.base)):
            s = self.base.clone(**{k: v for (k, v) in items})
            s.regularize()
            yield s

    def ordered_params(self):
        ks = list(self.variables.keys())
        for k in self.order + list(self.base.keys()):
            if k in ks:
                yield k
                ks.remove(k)
        if ks:
            raise Exception('Invalid parameter "%s" for source type "%s".' %
                            (ks[0], self.base.__class__.__name__))

    def make_coords(self, base):
        return [(param, self.variables[param].make(base=base[param]))
                for param in self.ordered_params()]


source_classes = [
    Source,
    SourceWithMagnitude,
    SourceWithDerivedMagnitude,
    ExplosionSource,
    RectangularExplosionSource,
    DCSource,
    CLVDSource,
    VLVDSource,
    MTSource,
    RectangularSource,
    PseudoDynamicRupture,
    DoubleDCSource,
    RingfaultSource,
    CombiSource,
    CombiSFSource,
    SFSource,
    SimpleLandslideSource,
    PorePressurePointSource,
    PorePressureLineSource,
]

stf_classes = [
    STF,
    BoxcarSTF,
    TriangularSTF,
    HalfSinusoidSTF,
    ResonatorSTF,
    TremorSTF,
    SimpleLandslideSTF,
    MultiTriangleSTF,
]

__all__ = '''
Cloneable
NoDefaultStoreSet
SeismosizerError
STFError
BadRequest
NoSuchStore
DerivedMagnitudeError
STFMode
'''.split() + [S.__name__ for S in source_classes + stf_classes] + '''
Request
ProcessingStats
Response
Engine
LocalEngine
RemoteEngine
source_classes
get_engine
Range
SourceGroup
SourceList
SourceGrid
map_anchor
'''.split()
