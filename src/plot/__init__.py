# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Utility functions and defintions for a common plot style throughout Pyrocko.

Functions with name prefix ``mpl_`` are Matplotlib specific. All others should
be toolkit-agnostic.

The following skeleton can be used to produce nice PDF figures, with absolute
sizes derived from paper and font sizes
(file :file:`/../../examples/plot_skeleton.py`
in the Pyrocko source directory)::

    from matplotlib import pyplot as plt

    from pyrocko.plot import mpl_init, mpl_margins, mpl_papersize
    # from pyrocko.plot import mpl_labelspace

    fontsize = 9.   # in points

    # set some Pyrocko style defaults
    mpl_init(fontsize=fontsize)

    fig = plt.figure(figsize=mpl_papersize('a4', 'landscape'))

    # let margins be proportional to selected font size, e.g. top and bottom
    # margin are set to be 5*fontsize = 45 [points]
    labelpos = mpl_margins(fig, w=7., h=5., units=fontsize)

    axes = fig.add_subplot(1, 1, 1)

    # positioning of axis labels
    # mpl_labelspace(axes)    # either: relative to axis tick labels
    labelpos(axes, 2., 1.5)   # or: relative to left/bottom paper edge

    axes.plot([0, 1], [0, 9])

    axes.set_xlabel('Time [s]')
    axes.set_ylabel('Amplitude [m]')

    fig.savefig('plot_skeleton.pdf')

    plt.show()

'''

import math
import random
import time
import calendar
import numpy as num

from pyrocko.util import parse_md, time_to_str, arange2, to_time_float
from pyrocko.guts import StringChoice, Float, Int, Bool, Tuple, Object


__doc__ += parse_md(__file__)


guts_prefix = 'pf'

point = 1.
inch = 72.
cm = 28.3465

units_dict = {
    'point': point,
    'inch': inch,
    'cm': cm,
}

_doc_units = "``'point'``, ``'inch'``, or ``'cm'``"


def apply_units(x, units):
    if isinstance(units, str):
        units = units_dict[units]

    if isinstance(x, (int, float)):
        return x / units
    else:
        if isinstance(x, tuple):
            return tuple(v / units for v in x)
        else:
            return list(v / units for v in x)


tango_colors = {
    'butter1':     (252, 233,  79),
    'butter2':     (237, 212,   0),
    'butter3':     (196, 160,   0),
    'chameleon1':  (138, 226,  52),
    'chameleon2':  (115, 210,  22),
    'chameleon3':  (78,  154,   6),
    'orange1':     (252, 175,  62),
    'orange2':     (245, 121,   0),
    'orange3':     (206,  92,   0),
    'skyblue1':    (114, 159, 207),
    'skyblue2':    (52,  101, 164),
    'skyblue3':    (32,   74, 135),
    'plum1':       (173, 127, 168),
    'plum2':       (117,  80, 123),
    'plum3':       (92,  53, 102),
    'chocolate1':  (233, 185, 110),
    'chocolate2':  (193, 125,  17),
    'chocolate3':  (143,  89,   2),
    'scarletred1': (239,  41,  41),
    'scarletred2': (204,   0,   0),
    'scarletred3': (164,   0,   0),
    'aluminium1':  (238, 238, 236),
    'aluminium2':  (211, 215, 207),
    'aluminium3':  (186, 189, 182),
    'aluminium4':  (136, 138, 133),
    'aluminium5':  (85,   87,  83),
    'aluminium6':  (46,   52,  54)}


graph_colors = [
    tango_colors[_x] for _x in (
        'scarletred2',
        'skyblue3',
        'chameleon3',
        'orange2',
        'plum2',
        'chocolate2',
        'butter2')]


def color(x=None):
    if x is None:
        return tuple([random.randint(0, 255) for _x in 'rgb'])

    if isinstance(x, int):
        if 0 <= x < len(graph_colors):
            return graph_colors[x]
        else:
            return (0, 0, 0)

    elif isinstance(x, str):
        if x in tango_colors:
            return tango_colors[x]

    elif isinstance(x, tuple):
        return x

    assert False, "Don't know what to do with this color definition: %s" % x


def to01(c):
    return tuple(x/255. for x in c)


def nice_value(x):
    '''
    Round x to nice value.
    '''

    if x == 0.0:
        return 0.0

    exp = 1.0
    sign = 1
    if x < 0.0:
        x = -x
        sign = -1
    while x >= 1.0:
        x /= 10.0
        exp *= 10.0
    while x < 0.1:
        x *= 10.0
        exp /= 10.0

    if x >= 0.75:
        return sign * 1.0 * exp
    if x >= 0.35:
        return sign * 0.5 * exp
    if x >= 0.15:
        return sign * 0.2 * exp

    return sign * 0.1 * exp


_papersizes_list = [
    ('a0', (2380., 3368.)),
    ('a1', (1684., 2380.)),
    ('a2', (1190., 1684.)),
    ('a3', (842., 1190.)),
    ('a4', (595., 842.)),
    ('a5', (421., 595.)),
    ('a6', (297., 421.)),
    ('a7', (210., 297.)),
    ('a8', (148., 210.)),
    ('a9', (105., 148.)),
    ('a10', (74., 105.)),
    ('b0', (2836., 4008.)),
    ('b1', (2004., 2836.)),
    ('b2', (1418., 2004.)),
    ('b3', (1002., 1418.)),
    ('b4', (709., 1002.)),
    ('b5', (501., 709.)),
    ('archa', (648., 864.)),
    ('archb', (864., 1296.)),
    ('archc', (1296., 1728.)),
    ('archd', (1728., 2592.)),
    ('arche', (2592., 3456.)),
    ('flsa', (612., 936.)),
    ('halfletter', (396., 612.)),
    ('note', (540., 720.)),
    ('letter', (612., 792.)),
    ('legal', (612., 1008.)),
    ('11x17', (792., 1224.)),
    ('ledger', (1224., 792.))]

papersizes = dict(_papersizes_list)

_doc_papersizes = ', '.join("``'%s'``" % k for (k, _) in _papersizes_list)


def papersize(paper, orientation='landscape', units='point'):

    '''
    Get paper size from string.

    :param paper: string selecting paper size. Choices: %s
    :param orientation: ``'landscape'``, or ``'portrait'``
    :param units: Units to be returned. Choices: %s

    :returns: ``(width, height)``
    '''

    assert orientation in ('landscape', 'portrait')

    w, h = papersizes[paper.lower()]
    if orientation == 'landscape':
        w, h = h, w

    return apply_units((w, h), units)


papersize.__doc__ %= (_doc_papersizes, _doc_units)


class AutoScaleMode(StringChoice):
    '''
    Mode of operation for auto-scaling.

    ================ ==================================================
    mode             description
    ================ ==================================================
    ``'auto'``:      Look at data range and choose one of the choices
                     below.
    ``'min-max'``:   Output range is selected to include data range.
    ``'0-max'``:     Output range shall start at zero and end at data
                     max.
    ``'min-0'``:     Output range shall start at data min and end at
                     zero.
    ``'symmetric'``: Output range shall by symmetric by zero.
    ``'off'``:       Similar to ``'min-max'``, but snap and space are
                     disabled, such that the output range always
                     exactly matches the data range.
    ================ ==================================================
    '''
    choices = ['auto', 'min-max', '0-max', 'min-0', 'symmetric', 'off']


class AutoScaler(Object):

    '''
    Tunable 1D autoscaling based on data range.

    Instances of this class may be used to determine nice minima, maxima and
    increments for ax annotations, as well as suitable common exponents for
    notation.

    The autoscaling process is guided by the following public attributes:
    '''

    approx_ticks = Float.T(
        default=7.0,
        help='Approximate number of increment steps (tickmarks) to generate.')

    mode = AutoScaleMode.T(
        default='auto',
        help='''Mode of operation for auto-scaling.''')

    exp = Int.T(
        optional=True,
        help='If defined, override automatically determined exponent for '
             'notation by the given value.')

    snap = Bool.T(
        default=False,
        help='If set to True, snap output range to multiples of increment. '
             "This parameter has no effect, if mode is set to ``'off'``.")

    inc = Float.T(
        optional=True,
        help='If defined, override automatically determined tick increment by '
             'the given value.')

    space = Float.T(
        default=0.0,
        help='Add some padding to the range. The value given, is the fraction '
             'by which the output range is increased on each side. If mode is '
             "``'0-max'`` or ``'min-0'``, the end at zero is kept fixed "
             'at zero. This parameter has no effect if mode is set to '
             "``'off'``.")

    exp_factor = Int.T(
        default=3,
        help='Exponent of notation is chosen to be a multiple of this value.')

    no_exp_interval = Tuple.T(
        2, Int.T(),
        default=(-3, 5),
        help='Range of exponent, for which no exponential notation is a'
             'allowed.')

    def __init__(
            self,
            approx_ticks=7.0,
            mode='auto',
            exp=None,
            snap=False,
            inc=None,
            space=0.0,
            exp_factor=3,
            no_exp_interval=(-3, 5)):

        '''
        Create new AutoScaler instance.

        The parameters are described in the AutoScaler documentation.
        '''

        Object.__init__(
            self,
            approx_ticks=approx_ticks,
            mode=mode,
            exp=exp,
            snap=snap,
            inc=inc,
            space=space,
            exp_factor=exp_factor,
            no_exp_interval=no_exp_interval)

    def make_scale(self, data_range, override_mode=None):

        '''
        Get nice minimum, maximum and increment for given data range.

        Returns ``(minimum, maximum, increment)`` or ``(maximum, minimum,
        -increment)``, depending on whether data_range is ``(data_min,
        data_max)`` or ``(data_max, data_min)``. If ``override_mode`` is
        defined, the mode attribute is temporarily overridden by the given
        value.
        '''

        data_min = min(data_range)
        data_max = max(data_range)

        is_reverse = (data_range[0] > data_range[1])

        a = self.mode
        if self.mode == 'auto':
            a = self.guess_autoscale_mode(data_min, data_max)

        if override_mode is not None:
            a = override_mode

        mi, ma = 0, 0
        if a == 'off':
            mi, ma = data_min, data_max
        elif a == '0-max':
            mi = 0.0
            if data_max > 0.0:
                ma = data_max
            else:
                ma = 1.0
        elif a == 'min-0':
            ma = 0.0
            if data_min < 0.0:
                mi = data_min
            else:
                mi = -1.0
        elif a == 'min-max':
            mi, ma = data_min, data_max
        elif a == 'symmetric':
            m = max(abs(data_min), abs(data_max))
            mi = -m
            ma = m

        nmi = mi
        if (mi != 0. or a == 'min-max') and a != 'off':
            nmi = mi - self.space*(ma-mi)

        nma = ma
        if (ma != 0. or a == 'min-max') and a != 'off':
            nma = ma + self.space*(ma-mi)

        mi, ma = nmi, nma

        if mi == ma and a != 'off':
            mi -= 1.0
            ma += 1.0

        # make nice tick increment
        if self.inc is not None:
            inc = self.inc
        else:
            if self.approx_ticks > 0.:
                inc = nice_value((ma-mi) / self.approx_ticks)
            else:
                inc = nice_value((ma-mi)*10.)

        if inc == 0.0:
            inc = 1.0

        # snap min and max to ticks if this is wanted
        if self.snap and a != 'off':
            ma = inc * math.ceil(ma/inc)
            mi = inc * math.floor(mi/inc)

        if is_reverse:
            return ma, mi, -inc
        else:
            return mi, ma, inc

    def make_exp(self, x):
        '''
        Get nice exponent for notation of ``x``.

        For ax annotations, give tick increment as ``x``.
        '''

        if self.exp is not None:
            return self.exp

        x = abs(x)
        if x == 0.0:
            return 0

        if 10**self.no_exp_interval[0] <= x <= 10**self.no_exp_interval[1]:
            return 0

        return math.floor(math.log10(x)/self.exp_factor)*self.exp_factor

    def guess_autoscale_mode(self, data_min, data_max):
        '''
        Guess mode of operation, based on data range.

        Used to map ``'auto'`` mode to ``'0-max'``, ``'min-0'``, ``'min-max'``
        or ``'symmetric'``.
        '''

        a = 'min-max'
        if data_min >= 0.0:
            if data_min < data_max/2.:
                a = '0-max'
            else:
                a = 'min-max'
        if data_max <= 0.0:
            if data_max > data_min/2.:
                a = 'min-0'
            else:
                a = 'min-max'
        if data_min < 0.0 and data_max > 0.0:
            if abs((abs(data_max)-abs(data_min)) /
                   (abs(data_max)+abs(data_min))) < 0.5:
                a = 'symmetric'
            else:
                a = 'min-max'
        return a


# below, some convenience functions for matplotlib plotting

def mpl_init(fontsize=10):
    '''
    Initialize Matplotlib rc parameters Pyrocko style.

    Returns the matplotlib.pyplot module for convenience.
    '''

    import matplotlib

    matplotlib.rcdefaults()
    matplotlib.rc('font', size=fontsize)
    matplotlib.rc('axes', linewidth=1.5)
    matplotlib.rc('xtick', direction='out')
    matplotlib.rc('ytick', direction='out')
    ts = fontsize * 0.7071
    matplotlib.rc('xtick.major', size=ts, width=0.5, pad=ts)
    matplotlib.rc('ytick.major', size=ts, width=0.5, pad=ts)
    matplotlib.rc('figure', facecolor='white')

    try:
        from cycler import cycler
        matplotlib.rc(
            'axes', prop_cycle=cycler(
                'color', [to01(x) for x in graph_colors]))
    except (ImportError, KeyError):
        try:
            matplotlib.rc('axes', color_cycle=[to01(x) for x in graph_colors])
        except KeyError:
            pass

    from matplotlib import pyplot as plt
    return plt


def mpl_get_cmap_names():
    '''
    Compatibility function to get named MPL colormap names.
    '''

    try:
        from matplotlib import colormaps
        names = list(colormaps.keys())
    except ImportError:
        from matplotlib.cm import _cmap_registry
        names = list(_cmap_registry.keys())

    names.sort()
    return names


def mpl_get_cmap(name):
    '''
    Compatibility function to get named MPL colormap.

    The function matplotlib.cm.get_cmap has been removed in MPL 3.8 but the
    suggested replacement is not available in slightly older versions of MPL,
    e.g. 3.3 (default on Debian 11).
    '''

    try:
        from matplotlib import colormaps
        return colormaps[name]
    except ImportError:
        from matplotlib import cm
        return cm.get_cmap(name)


def mpl_margins(
        fig,
        left=1.0, top=1.0, right=1.0, bottom=1.0,
        wspace=None, hspace=None,
        w=None, h=None,
        nw=None, nh=None,
        all=None,
        units='inch'):

    '''
    Adjust Matplotlib subplot params with absolute values in user units.

    Calls :py:meth:`matplotlib.figure.Figure.subplots_adjust` on ``fig`` with
    absolute margin widths/heights rather than relative values. If ``wspace``
    or ``hspace`` are given, the number of subplots must be given in ``nw``
    and ``nh`` because ``subplots_adjust()`` treats the spacing parameters
    relative to the subplot width and height.

    :param units: Unit multiplier or unit as string: %s
    :param left,right,top,bottom: margin space
    :param w: set ``left`` and ``right`` at once
    :param h: set ``top`` and ``bottom`` at once
    :param all: set ``left``, ``top``, ``right``, and ``bottom`` at once
    :param nw: number of subplots horizontally
    :param nh: number of subplots vertically
    :param wspace: horizontal spacing between subplots
    :param hspace: vertical spacing between subplots
    '''

    left, top, right, bottom = map(
        float, (left, top, right, bottom))

    if w is not None:
        left = right = float(w)

    if h is not None:
        top = bottom = float(h)

    if all is not None:
        left = right = top = bottom = float(all)

    ufac = units_dict.get(units, units) / inch

    left *= ufac
    right *= ufac
    top *= ufac
    bottom *= ufac

    width, height = fig.get_size_inches()

    rel_wspace = None
    rel_hspace = None

    if wspace is not None:
        wspace *= ufac
        if nw is None:
            raise ValueError('wspace must be given in combination with nw')

        wsub = (width - left - right - (nw-1) * wspace) / nw
        rel_wspace = wspace / wsub
    else:
        wsub = width - left - right

    if hspace is not None:
        hspace *= ufac
        if nh is None:
            raise ValueError('hspace must be given in combination with nh')

        hsub = (height - top - bottom - (nh-1) * hspace) / nh
        rel_hspace = hspace / hsub
    else:
        hsub = height - top - bottom

    fig.subplots_adjust(
        left=left/width,
        right=1.0 - right/width,
        bottom=bottom/height,
        top=1.0 - top/height,
        wspace=rel_wspace,
        hspace=rel_hspace)

    def labelpos(axes, xpos=0., ypos=0.):
        xpos *= ufac
        ypos *= ufac
        axes.get_yaxis().set_label_coords(-((left-xpos) / wsub), 0.5)
        axes.get_xaxis().set_label_coords(0.5, -((bottom-ypos) / hsub))

    return labelpos


mpl_margins.__doc__ %= _doc_units


def mpl_labelspace(axes):
    '''
    Add some extra padding between label and ax annotations.
    '''

    xa = axes.get_xaxis()
    ya = axes.get_yaxis()
    for attr in ('labelpad', 'LABELPAD'):
        if hasattr(xa, attr):
            setattr(xa, attr, xa.get_label().get_fontsize())
            setattr(ya, attr, ya.get_label().get_fontsize())
            break


def mpl_papersize(paper, orientation='landscape'):
    '''
    Get paper size in inch from string.

    Returns argument suitable to be passed to the ``figsize`` argument of
    :py:func:`matplotlib.pyplot.figure`.

    :param paper: string selecting paper size. Choices: %s
    :param orientation: ``'landscape'``, or ``'portrait'``

    :returns: ``(width, height)``
    '''

    return papersize(paper, orientation=orientation, units='inch')


mpl_papersize.__doc__ %= _doc_papersizes


class InvalidColorDef(ValueError):
    '''
    Raised for invalid color definitions.
    '''
    pass


def mpl_graph_color(i):
    return to01(graph_colors[i % len(graph_colors)])


def mpl_color(x):
    '''
    Convert string into color float tuple ranged 0-1 for use with Matplotlib.

    Accepts tango color names, matplotlib color names, and slash-separated
    strings. In the latter case, if values are larger than 1., the color
    is interpreted as 0-255 ranged. Single-valued (grayscale), three-valued
    (color) and four-valued (color with alpha) are accepted. An
    :py:exc:`InvalidColorDef` exception is raised when the convertion fails.
    '''

    import matplotlib.colors

    if x in tango_colors:
        return to01(tango_colors[x])

    s = x.split('/')
    if len(s) in (1, 3, 4):
        try:
            vals = list(map(float, s))
            if all(0. <= v <= 1. for v in vals):
                return vals

            elif all(0. <= v <= 255. for v in vals):
                return to01(vals)

        except ValueError:
            try:
                return matplotlib.colors.colorConverter.to_rgba(x)
            except Exception:
                pass

    raise InvalidColorDef('invalid color definition: %s' % x)


hours = 3600.
days = hours*24
approx_months = days*30.5
approx_years = days*365


nice_time_tinc_inc_approx_units = {
    'seconds': 1,
    'months': approx_months,
    'years': approx_years}


def nice_time_tick_inc(tinc_approx):

    if tinc_approx >= approx_years:
        return max(1.0, nice_value(tinc_approx / approx_years)), 'years'

    elif tinc_approx >= approx_months:
        nice = [1, 2, 3, 6]
        for tinc in nice:
            if tinc*approx_months >= tinc_approx or tinc == nice[-1]:
                return tinc, 'months'

    elif tinc_approx > days:
        return nice_value(tinc_approx / days) * days, 'seconds'

    elif tinc_approx >= 1.0:
        nice = [
            1., 2., 5., 10., 20., 30., 60., 120., 300., 600., 1200., 1800.,
            1*hours, 2*hours, 3*hours, 6*hours, 12*hours, days, 2*days]

        for tinc in nice:
            if tinc >= tinc_approx or tinc == nice[-1]:
                return tinc, 'seconds'

    else:
        return nice_value(tinc_approx), 'seconds'


def nice_time_tick_inc_approx_secs(tinc_approx):
    v, unit = nice_time_tick_inc(tinc_approx)
    return v * nice_time_tinc_inc_approx_units[unit]


def time_tick_labels(tmin, tmax, tinc, tinc_unit):

    if tinc_unit == 'years':
        tt = time.gmtime(int(tmin))
        tmin_year = tt[0]
        if tt[1:6] != (1, 1, 0, 0, 0):
            tmin_year += 1

        tmax_year = time.gmtime(int(tmax))[0]

        tick_times_year = arange2(
            math.ceil(tmin_year/tinc)*tinc,
            math.floor(tmax_year/tinc)*tinc,
            tinc).astype(int)

        times = [
            to_time_float(calendar.timegm((year, 1, 1, 0, 0, 0)))
            for year in tick_times_year]

        labels = ['%04i' % year for year in tick_times_year]

    elif tinc_unit == 'months':
        tt = time.gmtime(int(tmin))
        tmin_ym = tt[0] * 12 + (tt[1] - 1)
        if tt[2:6] != (1, 0, 0, 0):
            tmin_ym += 1

        tt = time.gmtime(int(tmax))
        tmax_ym = tt[0] * 12 + (tt[1] - 1)

        tick_times_ym = arange2(
            math.ceil(tmin_ym/tinc)*tinc,
            math.floor(tmax_ym/tinc)*tinc, tinc).astype(int)

        times = [
            to_time_float(calendar.timegm((ym // 12, ym % 12 + 1, 1, 0, 0, 0)))
            for ym in tick_times_ym]

        labels = [
            '%04i-%02i' % (ym // 12, ym % 12 + 1) for ym in tick_times_ym]

    elif tinc_unit == 'seconds':
        imin = int(num.ceil(tmin/tinc))
        imax = int(num.floor(tmax/tinc))
        nticks = imax - imin + 1
        tmin_ticks = imin * tinc
        times = tmin_ticks + num.arange(nticks) * tinc
        times = times.tolist()

        if tinc < 1e-6:
            fmt = '%Y-%m-%d.%H:%M:%S.9FRAC'
        elif tinc < 1e-3:
            fmt = '%Y-%m-%d.%H:%M:%S.6FRAC'
        elif tinc < 1.0:
            fmt = '%Y-%m-%d.%H:%M:%S.3FRAC'
        elif tinc < 60:
            fmt = '%Y-%m-%d.%H:%M:%S'
        elif tinc < 3600.*24:
            fmt = '%Y-%m-%d.%H:%M'
        else:
            fmt = '%Y-%m-%d'

        nwords = len(fmt.split('.'))

        labels = [time_to_str(t, format=fmt) for t in times]
        labels_weeded = []
        have_ymd = have_hms = False
        ymd = hms = ''
        for ilab, lab in reversed(list(enumerate(labels))):
            words = lab.split('.')
            if nwords > 2:
                words[2] = '.' + words[2]
                if float(words[2]) == 0.0:  # or (ilab == 0 and not have_hms):
                    have_hms = True
                else:
                    hms = words[1]
                    words[1] = ''
            else:
                have_hms = True

            if nwords > 1:
                if words[1] in ('00:00', '00:00:00'):  # or (ilab == 0 and not have_ymd):  # noqa
                    have_ymd = True
                else:
                    ymd = words[0]
                    words[0] = ''
            else:
                have_ymd = True

            labels_weeded.append('\n'.join(reversed(words)))

        labels = list(reversed(labels_weeded))
        if (not have_ymd or not have_hms) and (hms or ymd):
            words = ([''] if nwords > 2 else []) + [
                hms if not have_hms else '',
                ymd if not have_ymd else '']

            labels[0:0] = ['\n'.join(words)]
            times[0:0] = [tmin]

    return times, labels


def mpl_time_axis(axes, approx_ticks=5.):

    '''
    Configure x axis of a matplotlib axes object for interactive time display.

    :param axes: Axes to be configured.
    :type axes: :py:class:`matplotlib.axes.Axes`

    :param approx_ticks: Approximate number of ticks to create.
    :type approx_ticks: float

    This function tries to use nice tick increments and tick labels for time
    ranges from microseconds to years, similar to how this is handled in
    Snuffler.
    '''

    from matplotlib.ticker import Locator, Formatter

    class labeled_float(float):
        pass

    class TimeLocator(Locator):

        def __init__(self, approx_ticks=5.):
            self._approx_ticks = approx_ticks
            Locator.__init__(self)

        def __call__(self):
            vmin, vmax = self.axis.get_view_interval()
            return self.tick_values(vmin, vmax)

        def tick_values(self, vmin, vmax):
            if vmax < vmin:
                vmin, vmax = vmax, vmin

            if vmin == vmax:
                return []

            tinc_approx = (vmax - vmin) / self._approx_ticks
            tinc, tinc_unit = nice_time_tick_inc(tinc_approx)
            times, labels = time_tick_labels(vmin, vmax, tinc, tinc_unit)
            ftimes = []
            for t, label in zip(times, labels):
                ftime = labeled_float(t)
                ftime._mpl_label = label
                ftimes.append(ftime)

            return self.raise_if_exceeds(ftimes)

    class TimeFormatter(Formatter):

        def __call__(self, x, pos=None):
            if isinstance(x, labeled_float):
                return x._mpl_label
            else:
                return time_to_str(x, format='%Y-%m-%d %H:%M:%S.6FRAC')

    axes.xaxis.set_major_locator(TimeLocator(approx_ticks=approx_ticks))
    axes.xaxis.set_major_formatter(TimeFormatter())
