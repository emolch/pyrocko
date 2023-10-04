# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
'''
A Python interface to GMT.
'''

# This file has been part of GmtPy (http://emolch.github.io/gmtpy/)
# See there for copying and licensing information.

import subprocess
try:
    from StringIO import StringIO as BytesIO
except ImportError:
    from io import BytesIO
import re
import os
import sys
import shutil
from os.path import join as pjoin
import tempfile
import random
import logging
import math
import numpy as num
import copy
from select import select
try:
    from scipy.io import netcdf_file
except ImportError:
    from scipy.io.netcdf import netcdf_file

from pyrocko import ExternalProgramMissing
from . import AutoScaler


find_bb = re.compile(br'%%BoundingBox:((\s+[-0-9]+){4})')
find_hiresbb = re.compile(br'%%HiResBoundingBox:((\s+[-0-9.]+){4})')


encoding_gmt_to_python = {
    'isolatin1+': 'iso-8859-1',
    'standard+': 'ascii',
    'isolatin1': 'iso-8859-1',
    'standard': 'ascii'}

for i in range(1, 11):
    encoding_gmt_to_python['iso-8859-%i' % i] = 'iso-8859-%i' % i


def have_gmt():
    try:
        get_gmt_installation('newest')
        return True

    except GMTInstallationProblem:
        return False


def check_have_gmt():
    if not have_gmt():
        raise ExternalProgramMissing('GMT is not installed or cannot be found')


def have_pixmaptools():
    for prog in [['pdftocairo'], ['convert'], ['gs', '-h']]:
        try:
            p = subprocess.Popen(
                prog,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)

            (stdout, stderr) = p.communicate()

        except OSError:
            return False

    return True


class GmtPyError(Exception):
    pass


class GMTError(GmtPyError):
    pass


class GMTInstallationProblem(GmtPyError):
    pass


def convert_graph(in_filename, out_filename, resolution=75., oversample=2.,
                  width=None, height=None, size=None):

    _, tmp_filename_base = tempfile.mkstemp()

    try:
        if out_filename.endswith('.svg'):
            fmt_arg = '-svg'
            tmp_filename = tmp_filename_base
            oversample = 1.0
        else:
            fmt_arg = '-png'
            tmp_filename = tmp_filename_base + '-1.png'

        if size is not None:
            scale_args = ['-scale-to', '%i' % int(round(size*oversample))]
        elif width is not None:
            scale_args = ['-scale-to-x', '%i' % int(round(width*oversample))]
        elif height is not None:
            scale_args = ['-scale-to-y', '%i' % int(round(height*oversample))]
        else:
            scale_args = ['-r', '%i' % int(round(resolution * oversample))]

        try:
            subprocess.check_call(
                ['pdftocairo'] + scale_args +
                [fmt_arg, in_filename, tmp_filename_base])
        except OSError as e:
            raise GmtPyError(
                'Cannot start `pdftocairo`, is it installed? (%s)' % str(e))

        if oversample > 1.:
            try:
                subprocess.check_call([
                    'convert',
                    tmp_filename,
                    '-resize', '%i%%' % int(round(100.0/oversample)),
                    out_filename])
            except OSError as e:
                raise GmtPyError(
                    'Cannot start `convert`, is it installed? (%s)' % str(e))

        else:
            if out_filename.endswith('.png') or out_filename.endswith('.svg'):
                shutil.move(tmp_filename, out_filename)
            else:
                try:
                    subprocess.check_call(
                        ['convert', tmp_filename, out_filename])
                except Exception as e:
                    raise GmtPyError(
                        'Cannot start `convert`, is it installed? (%s)'
                        % str(e))

    except Exception:
        raise

    finally:
        if os.path.exists(tmp_filename_base):
            os.remove(tmp_filename_base)

        if os.path.exists(tmp_filename):
            os.remove(tmp_filename)


def get_bbox(s):
    for pat in [find_hiresbb, find_bb]:
        m = pat.search(s)
        if m:
            bb = [float(x) for x in m.group(1).split()]
            return bb

    raise GmtPyError('Cannot find bbox')


def replace_bbox(bbox, *args):

    def repl(m):
        if m.group(1):
            return ('%%HiResBoundingBox: ' + ' '.join(
                '%.3f' % float(x) for x in bbox)).encode('ascii')
        else:
            return ('%%%%BoundingBox: %i %i %i %i' % (
                    int(math.floor(bbox[0])),
                    int(math.floor(bbox[1])),
                    int(math.ceil(bbox[2])),
                    int(math.ceil(bbox[3])))).encode('ascii')

    pat = re.compile(br'%%(HiRes)?BoundingBox:((\s+[0-9.]+){4})')
    if len(args) == 1:
        s = args[0]
        return pat.sub(repl, s)

    else:
        fin, fout = args
        nn = 0
        for line in fin:
            line, n = pat.subn(repl, line)
            nn += n
            fout.write(line)
            if nn == 2:
                break

        if nn == 2:
            for line in fin:
                fout.write(line)


def escape_shell_arg(s):
    '''
    This function should be used for debugging output only - it could be
    insecure.
    '''

    if re.search(r'[^a-zA-Z0-9._/=-]', s):
        return "'" + s.replace("'", "'\\''") + "'"
    else:
        return s


def escape_shell_args(args):
    '''
    This function should be used for debugging output only - it could be
    insecure.
    '''

    return ' '.join([escape_shell_arg(x) for x in args])


golden_ratio = 1.61803

# units in points
_units = {
    'i': 72.,
    'c': 72./2.54,
    'm': 72.*100./2.54,
    'p': 1.}

inch = _units['i']
'''
Unit cm in points.
'''


cm = _units['c']
'''
Unit inch in points.
'''

# some awsome colors
tango_colors = {
    'butter1': (252, 233,  79),
    'butter2': (237, 212,   0),
    'butter3': (196, 160,   0),
    'chameleon1': (138, 226,  52),
    'chameleon2': (115, 210,  22),
    'chameleon3': (78, 154,   6),
    'orange1': (252, 175,  62),
    'orange2': (245, 121,   0),
    'orange3': (206,  92,   0),
    'skyblue1': (114, 159, 207),
    'skyblue2': (52, 101, 164),
    'skyblue3': (32,  74, 135),
    'plum1': (173, 127, 168),
    'plum2': (117,  80, 123),
    'plum3': (92,  53, 102),
    'chocolate1': (233, 185, 110),
    'chocolate2': (193, 125,  17),
    'chocolate3': (143,  89,   2),
    'scarletred1': (239,  41,  41),
    'scarletred2': (204,   0,   0),
    'scarletred3': (164,   0,   0),
    'aluminium1': (238, 238, 236),
    'aluminium2': (211, 215, 207),
    'aluminium3': (186, 189, 182),
    'aluminium4': (136, 138, 133),
    'aluminium5': (85,  87,  83),
    'aluminium6': (46,  52,  54)
}

graph_colors = [tango_colors[_x] for _x in (
    'scarletred2', 'skyblue3', 'chameleon3', 'orange2', 'plum2', 'chocolate2',
    'butter2')]


def color(x=None):
    '''
    Generate a string for GMT option arguments expecting a color.

    If ``x`` is None, a random color is returned. If it is an integer, the
    corresponding ``gmtpy.graph_colors[x]`` or black returned. If it is a
    string and the corresponding ``gmtpy.tango_colors[x]`` exists, this is
    returned, or the string is passed through. If ``x`` is a tuple, it is
    transformed into the string form which GMT expects.
    '''

    if x is None:
        return '%i/%i/%i' % tuple(random.randint(0, 255) for _ in 'rgb')

    if isinstance(x, int):
        if 0 <= x < len(graph_colors):
            return '%i/%i/%i' % graph_colors[x]
        else:
            return '0/0/0'

    elif isinstance(x, str):
        if x in tango_colors:
            return '%i/%i/%i' % tango_colors[x]
        else:
            return x

    return '%i/%i/%i' % x


def color_tup(x=None):
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

    return x


_gmt_installations = {}

# Set fixed installation(s) to use...
# (use this, if you want to use different GMT versions simultaneously.)

# _gmt_installations['4.2.1'] = {'home': '/sw/etch-ia32/gmt-4.2.1',
#                                'bin':  '/sw/etch-ia32/gmt-4.2.1/bin'}
# _gmt_installations['4.3.0'] = {'home': '/sw/etch-ia32/gmt-4.3.0',
#                                'bin':  '/sw/etch-ia32/gmt-4.3.0/bin'}
# _gmt_installations['6.0.0'] = {'home': '/usr/share/gmt',
#                                'bin':  '/usr/bin' }

# ... or let GmtPy autodetect GMT via $PATH and $GMTHOME


def key_version(a):
    a = a.split('_')[0]  # get rid of revision id
    return [int(x) for x in a.split('.')]


def newest_installed_gmt_version():
    return sorted(_gmt_installations.keys(), key=key_version)[-1]


def all_installed_gmt_versions():
    return sorted(_gmt_installations.keys(), key=key_version)


# To have consistent defaults, they are hardcoded here and should not be
# changed.

_gmt_defaults_by_version = {}
_gmt_defaults_by_version['4.2.1'] = r'''
#
#       GMT-SYSTEM 4.2.1 Defaults file
#
#-------- Plot Media Parameters -------------
PAGE_COLOR              = 255/255/255
PAGE_ORIENTATION        = portrait
PAPER_MEDIA             = a4+
#-------- Basemap Annotation Parameters ------
ANNOT_MIN_ANGLE         = 20
ANNOT_MIN_SPACING       = 0
ANNOT_FONT_PRIMARY      = Helvetica
ANNOT_FONT_SIZE         = 12p
ANNOT_OFFSET_PRIMARY    = 0.075i
ANNOT_FONT_SECONDARY    = Helvetica
ANNOT_FONT_SIZE_SECONDARY       = 16p
ANNOT_OFFSET_SECONDARY  = 0.075i
DEGREE_SYMBOL           = ring
HEADER_FONT             = Helvetica
HEADER_FONT_SIZE        = 36p
HEADER_OFFSET           = 0.1875i
LABEL_FONT              = Helvetica
LABEL_FONT_SIZE         = 14p
LABEL_OFFSET            = 0.1125i
OBLIQUE_ANNOTATION      = 1
PLOT_CLOCK_FORMAT       = hh:mm:ss
PLOT_DATE_FORMAT        = yyyy-mm-dd
PLOT_DEGREE_FORMAT      = +ddd:mm:ss
Y_AXIS_TYPE             = hor_text
#-------- Basemap Layout Parameters ---------
BASEMAP_AXES            = WESN
BASEMAP_FRAME_RGB       = 0/0/0
BASEMAP_TYPE            = plain
FRAME_PEN               = 1.25p
FRAME_WIDTH             = 0.075i
GRID_CROSS_SIZE_PRIMARY = 0i
GRID_CROSS_SIZE_SECONDARY       = 0i
GRID_PEN_PRIMARY        = 0.25p
GRID_PEN_SECONDARY      = 0.5p
MAP_SCALE_HEIGHT        = 0.075i
TICK_LENGTH             = 0.075i
POLAR_CAP               = 85/90
TICK_PEN                = 0.5p
X_AXIS_LENGTH           = 9i
Y_AXIS_LENGTH           = 6i
X_ORIGIN                = 1i
Y_ORIGIN                = 1i
UNIX_TIME               = FALSE
UNIX_TIME_POS           = -0.75i/-0.75i
#-------- Color System Parameters -----------
COLOR_BACKGROUND        = 0/0/0
COLOR_FOREGROUND        = 255/255/255
COLOR_NAN               = 128/128/128
COLOR_IMAGE             = adobe
COLOR_MODEL             = rgb
HSV_MIN_SATURATION      = 1
HSV_MAX_SATURATION      = 0.1
HSV_MIN_VALUE           = 0.3
HSV_MAX_VALUE           = 1
#-------- PostScript Parameters -------------
CHAR_ENCODING           = ISOLatin1+
DOTS_PR_INCH            = 300
N_COPIES                = 1
PS_COLOR                = rgb
PS_IMAGE_COMPRESS       = none
PS_IMAGE_FORMAT         = ascii
PS_LINE_CAP             = round
PS_LINE_JOIN            = miter
PS_MITER_LIMIT          = 35
PS_VERBOSE                      = FALSE
GLOBAL_X_SCALE          = 1
GLOBAL_Y_SCALE          = 1
#-------- I/O Format Parameters -------------
D_FORMAT                = %lg
FIELD_DELIMITER         = tab
GRIDFILE_SHORTHAND      = FALSE
GRID_FORMAT             = nf
INPUT_CLOCK_FORMAT      = hh:mm:ss
INPUT_DATE_FORMAT       = yyyy-mm-dd
IO_HEADER               = FALSE
N_HEADER_RECS           = 1
OUTPUT_CLOCK_FORMAT     = hh:mm:ss
OUTPUT_DATE_FORMAT      = yyyy-mm-dd
OUTPUT_DEGREE_FORMAT    = +D
XY_TOGGLE               = FALSE
#-------- Projection Parameters -------------
ELLIPSOID               = WGS-84
MAP_SCALE_FACTOR        = default
MEASURE_UNIT            = inch
#-------- Calendar/Time Parameters ----------
TIME_FORMAT_PRIMARY     = full
TIME_FORMAT_SECONDARY   = full
TIME_EPOCH              = 2000-01-01T00:00:00
TIME_IS_INTERVAL        = OFF
TIME_INTERVAL_FRACTION  = 0.5
TIME_LANGUAGE           = us
TIME_SYSTEM             = other
TIME_UNIT               = d
TIME_WEEK_START         = Sunday
Y2K_OFFSET_YEAR         = 1950
#-------- Miscellaneous Parameters ----------
HISTORY                 = TRUE
INTERPOLANT             = akima
LINE_STEP               = 0.01i
VECTOR_SHAPE            = 0
VERBOSE                 = FALSE'''

_gmt_defaults_by_version['4.3.0'] = r'''
#
#        GMT-SYSTEM 4.3.0 Defaults file
#
#-------- Plot Media Parameters -------------
PAGE_COLOR                = 255/255/255
PAGE_ORIENTATION        = portrait
PAPER_MEDIA                = a4+
#-------- Basemap Annotation Parameters ------
ANNOT_MIN_ANGLE                = 20
ANNOT_MIN_SPACING        = 0
ANNOT_FONT_PRIMARY        = Helvetica
ANNOT_FONT_SIZE_PRIMARY        = 12p
ANNOT_OFFSET_PRIMARY        = 0.075i
ANNOT_FONT_SECONDARY        = Helvetica
ANNOT_FONT_SIZE_SECONDARY        = 16p
ANNOT_OFFSET_SECONDARY        = 0.075i
DEGREE_SYMBOL                = ring
HEADER_FONT                = Helvetica
HEADER_FONT_SIZE        = 36p
HEADER_OFFSET                = 0.1875i
LABEL_FONT                = Helvetica
LABEL_FONT_SIZE                = 14p
LABEL_OFFSET                = 0.1125i
OBLIQUE_ANNOTATION        = 1
PLOT_CLOCK_FORMAT        = hh:mm:ss
PLOT_DATE_FORMAT        = yyyy-mm-dd
PLOT_DEGREE_FORMAT        = +ddd:mm:ss
Y_AXIS_TYPE                = hor_text
#-------- Basemap Layout Parameters ---------
BASEMAP_AXES                = WESN
BASEMAP_FRAME_RGB        = 0/0/0
BASEMAP_TYPE                = plain
FRAME_PEN                = 1.25p
FRAME_WIDTH                = 0.075i
GRID_CROSS_SIZE_PRIMARY        = 0i
GRID_PEN_PRIMARY        = 0.25p
GRID_CROSS_SIZE_SECONDARY        = 0i
GRID_PEN_SECONDARY        = 0.5p
MAP_SCALE_HEIGHT        = 0.075i
POLAR_CAP                = 85/90
TICK_LENGTH                = 0.075i
TICK_PEN                = 0.5p
X_AXIS_LENGTH                = 9i
Y_AXIS_LENGTH                = 6i
X_ORIGIN                = 1i
Y_ORIGIN                = 1i
UNIX_TIME                = FALSE
UNIX_TIME_POS                = BL/-0.75i/-0.75i
UNIX_TIME_FORMAT        = %Y %b %d %H:%M:%S
#-------- Color System Parameters -----------
COLOR_BACKGROUND        = 0/0/0
COLOR_FOREGROUND        = 255/255/255
COLOR_NAN                = 128/128/128
COLOR_IMAGE                = adobe
COLOR_MODEL                = rgb
HSV_MIN_SATURATION        = 1
HSV_MAX_SATURATION        = 0.1
HSV_MIN_VALUE                = 0.3
HSV_MAX_VALUE                = 1
#-------- PostScript Parameters -------------
CHAR_ENCODING                = ISOLatin1+
DOTS_PR_INCH                = 300
N_COPIES                = 1
PS_COLOR                = rgb
PS_IMAGE_COMPRESS        = none
PS_IMAGE_FORMAT                = ascii
PS_LINE_CAP                = round
PS_LINE_JOIN                = miter
PS_MITER_LIMIT                = 35
PS_VERBOSE                = FALSE
GLOBAL_X_SCALE                = 1
GLOBAL_Y_SCALE                = 1
#-------- I/O Format Parameters -------------
D_FORMAT                = %lg
FIELD_DELIMITER                = tab
GRIDFILE_SHORTHAND        = FALSE
GRID_FORMAT                = nf
INPUT_CLOCK_FORMAT        = hh:mm:ss
INPUT_DATE_FORMAT        = yyyy-mm-dd
IO_HEADER                = FALSE
N_HEADER_RECS                = 1
OUTPUT_CLOCK_FORMAT        = hh:mm:ss
OUTPUT_DATE_FORMAT        = yyyy-mm-dd
OUTPUT_DEGREE_FORMAT        = +D
XY_TOGGLE                = FALSE
#-------- Projection Parameters -------------
ELLIPSOID                = WGS-84
MAP_SCALE_FACTOR        = default
MEASURE_UNIT                = inch
#-------- Calendar/Time Parameters ----------
TIME_FORMAT_PRIMARY        = full
TIME_FORMAT_SECONDARY        = full
TIME_EPOCH                = 2000-01-01T00:00:00
TIME_IS_INTERVAL        = OFF
TIME_INTERVAL_FRACTION        = 0.5
TIME_LANGUAGE                = us
TIME_UNIT                = d
TIME_WEEK_START                = Sunday
Y2K_OFFSET_YEAR                = 1950
#-------- Miscellaneous Parameters ----------
HISTORY                        = TRUE
INTERPOLANT                = akima
LINE_STEP                = 0.01i
VECTOR_SHAPE                = 0
VERBOSE                        = FALSE'''


_gmt_defaults_by_version['4.3.1'] = r'''
#
#        GMT-SYSTEM 4.3.1 Defaults file
#
#-------- Plot Media Parameters -------------
PAGE_COLOR                = 255/255/255
PAGE_ORIENTATION        = portrait
PAPER_MEDIA                = a4+
#-------- Basemap Annotation Parameters ------
ANNOT_MIN_ANGLE                = 20
ANNOT_MIN_SPACING        = 0
ANNOT_FONT_PRIMARY        = Helvetica
ANNOT_FONT_SIZE_PRIMARY        = 12p
ANNOT_OFFSET_PRIMARY        = 0.075i
ANNOT_FONT_SECONDARY        = Helvetica
ANNOT_FONT_SIZE_SECONDARY        = 16p
ANNOT_OFFSET_SECONDARY        = 0.075i
DEGREE_SYMBOL                = ring
HEADER_FONT                = Helvetica
HEADER_FONT_SIZE        = 36p
HEADER_OFFSET                = 0.1875i
LABEL_FONT                = Helvetica
LABEL_FONT_SIZE                = 14p
LABEL_OFFSET                = 0.1125i
OBLIQUE_ANNOTATION        = 1
PLOT_CLOCK_FORMAT        = hh:mm:ss
PLOT_DATE_FORMAT        = yyyy-mm-dd
PLOT_DEGREE_FORMAT        = +ddd:mm:ss
Y_AXIS_TYPE                = hor_text
#-------- Basemap Layout Parameters ---------
BASEMAP_AXES                = WESN
BASEMAP_FRAME_RGB        = 0/0/0
BASEMAP_TYPE                = plain
FRAME_PEN                = 1.25p
FRAME_WIDTH                = 0.075i
GRID_CROSS_SIZE_PRIMARY        = 0i
GRID_PEN_PRIMARY        = 0.25p
GRID_CROSS_SIZE_SECONDARY        = 0i
GRID_PEN_SECONDARY        = 0.5p
MAP_SCALE_HEIGHT        = 0.075i
POLAR_CAP                = 85/90
TICK_LENGTH                = 0.075i
TICK_PEN                = 0.5p
X_AXIS_LENGTH                = 9i
Y_AXIS_LENGTH                = 6i
X_ORIGIN                = 1i
Y_ORIGIN                = 1i
UNIX_TIME                = FALSE
UNIX_TIME_POS                = BL/-0.75i/-0.75i
UNIX_TIME_FORMAT        = %Y %b %d %H:%M:%S
#-------- Color System Parameters -----------
COLOR_BACKGROUND        = 0/0/0
COLOR_FOREGROUND        = 255/255/255
COLOR_NAN                = 128/128/128
COLOR_IMAGE                = adobe
COLOR_MODEL                = rgb
HSV_MIN_SATURATION        = 1
HSV_MAX_SATURATION        = 0.1
HSV_MIN_VALUE                = 0.3
HSV_MAX_VALUE                = 1
#-------- PostScript Parameters -------------
CHAR_ENCODING                = ISOLatin1+
DOTS_PR_INCH                = 300
N_COPIES                = 1
PS_COLOR                = rgb
PS_IMAGE_COMPRESS        = none
PS_IMAGE_FORMAT                = ascii
PS_LINE_CAP                = round
PS_LINE_JOIN                = miter
PS_MITER_LIMIT                = 35
PS_VERBOSE                = FALSE
GLOBAL_X_SCALE                = 1
GLOBAL_Y_SCALE                = 1
#-------- I/O Format Parameters -------------
D_FORMAT                = %lg
FIELD_DELIMITER                = tab
GRIDFILE_SHORTHAND        = FALSE
GRID_FORMAT                = nf
INPUT_CLOCK_FORMAT        = hh:mm:ss
INPUT_DATE_FORMAT        = yyyy-mm-dd
IO_HEADER                = FALSE
N_HEADER_RECS                = 1
OUTPUT_CLOCK_FORMAT        = hh:mm:ss
OUTPUT_DATE_FORMAT        = yyyy-mm-dd
OUTPUT_DEGREE_FORMAT        = +D
XY_TOGGLE                = FALSE
#-------- Projection Parameters -------------
ELLIPSOID                = WGS-84
MAP_SCALE_FACTOR        = default
MEASURE_UNIT                = inch
#-------- Calendar/Time Parameters ----------
TIME_FORMAT_PRIMARY        = full
TIME_FORMAT_SECONDARY        = full
TIME_EPOCH                = 2000-01-01T00:00:00
TIME_IS_INTERVAL        = OFF
TIME_INTERVAL_FRACTION        = 0.5
TIME_LANGUAGE                = us
TIME_UNIT                = d
TIME_WEEK_START                = Sunday
Y2K_OFFSET_YEAR                = 1950
#-------- Miscellaneous Parameters ----------
HISTORY                        = TRUE
INTERPOLANT                = akima
LINE_STEP                = 0.01i
VECTOR_SHAPE                = 0
VERBOSE                        = FALSE'''


_gmt_defaults_by_version['4.4.0'] = r'''
#
#       GMT-SYSTEM 4.4.0 [64-bit] Defaults file
#
#-------- Plot Media Parameters -------------
PAGE_COLOR              = 255/255/255
PAGE_ORIENTATION        = portrait
PAPER_MEDIA             = a4+
#-------- Basemap Annotation Parameters ------
ANNOT_MIN_ANGLE         = 20
ANNOT_MIN_SPACING       = 0
ANNOT_FONT_PRIMARY      = Helvetica
ANNOT_FONT_SIZE_PRIMARY = 14p
ANNOT_OFFSET_PRIMARY    = 0.075i
ANNOT_FONT_SECONDARY    = Helvetica
ANNOT_FONT_SIZE_SECONDARY       = 16p
ANNOT_OFFSET_SECONDARY  = 0.075i
DEGREE_SYMBOL           = ring
HEADER_FONT             = Helvetica
HEADER_FONT_SIZE        = 36p
HEADER_OFFSET           = 0.1875i
LABEL_FONT              = Helvetica
LABEL_FONT_SIZE         = 14p
LABEL_OFFSET            = 0.1125i
OBLIQUE_ANNOTATION      = 1
PLOT_CLOCK_FORMAT       = hh:mm:ss
PLOT_DATE_FORMAT        = yyyy-mm-dd
PLOT_DEGREE_FORMAT      = +ddd:mm:ss
Y_AXIS_TYPE             = hor_text
#-------- Basemap Layout Parameters ---------
BASEMAP_AXES            = WESN
BASEMAP_FRAME_RGB       = 0/0/0
BASEMAP_TYPE            = plain
FRAME_PEN               = 1.25p
FRAME_WIDTH             = 0.075i
GRID_CROSS_SIZE_PRIMARY = 0i
GRID_PEN_PRIMARY        = 0.25p
GRID_CROSS_SIZE_SECONDARY       = 0i
GRID_PEN_SECONDARY      = 0.5p
MAP_SCALE_HEIGHT        = 0.075i
POLAR_CAP               = 85/90
TICK_LENGTH             = 0.075i
TICK_PEN                = 0.5p
X_AXIS_LENGTH           = 9i
Y_AXIS_LENGTH           = 6i
X_ORIGIN                = 1i
Y_ORIGIN                = 1i
UNIX_TIME               = FALSE
UNIX_TIME_POS           = BL/-0.75i/-0.75i
UNIX_TIME_FORMAT        = %Y %b %d %H:%M:%S
#-------- Color System Parameters -----------
COLOR_BACKGROUND        = 0/0/0
COLOR_FOREGROUND        = 255/255/255
COLOR_NAN               = 128/128/128
COLOR_IMAGE             = adobe
COLOR_MODEL             = rgb
HSV_MIN_SATURATION      = 1
HSV_MAX_SATURATION      = 0.1
HSV_MIN_VALUE           = 0.3
HSV_MAX_VALUE           = 1
#-------- PostScript Parameters -------------
CHAR_ENCODING           = ISOLatin1+
DOTS_PR_INCH            = 300
N_COPIES                = 1
PS_COLOR                = rgb
PS_IMAGE_COMPRESS       = lzw
PS_IMAGE_FORMAT         = ascii
PS_LINE_CAP             = round
PS_LINE_JOIN            = miter
PS_MITER_LIMIT          = 35
PS_VERBOSE              = FALSE
GLOBAL_X_SCALE          = 1
GLOBAL_Y_SCALE          = 1
#-------- I/O Format Parameters -------------
D_FORMAT                = %lg
FIELD_DELIMITER         = tab
GRIDFILE_SHORTHAND      = FALSE
GRID_FORMAT             = nf
INPUT_CLOCK_FORMAT      = hh:mm:ss
INPUT_DATE_FORMAT       = yyyy-mm-dd
IO_HEADER               = FALSE
N_HEADER_RECS           = 1
OUTPUT_CLOCK_FORMAT     = hh:mm:ss
OUTPUT_DATE_FORMAT      = yyyy-mm-dd
OUTPUT_DEGREE_FORMAT    = +D
XY_TOGGLE               = FALSE
#-------- Projection Parameters -------------
ELLIPSOID               = WGS-84
MAP_SCALE_FACTOR        = default
MEASURE_UNIT            = inch
#-------- Calendar/Time Parameters ----------
TIME_FORMAT_PRIMARY     = full
TIME_FORMAT_SECONDARY   = full
TIME_EPOCH              = 2000-01-01T00:00:00
TIME_IS_INTERVAL        = OFF
TIME_INTERVAL_FRACTION  = 0.5
TIME_LANGUAGE           = us
TIME_UNIT               = d
TIME_WEEK_START         = Sunday
Y2K_OFFSET_YEAR         = 1950
#-------- Miscellaneous Parameters ----------
HISTORY                 = TRUE
INTERPOLANT             = akima
LINE_STEP               = 0.01i
VECTOR_SHAPE            = 0
VERBOSE                 = FALSE
'''

_gmt_defaults_by_version['4.5.2'] = r'''
#
#       GMT-SYSTEM 4.5.2 [64-bit] Defaults file
#
#-------- Plot Media Parameters -------------
PAGE_COLOR              = white
PAGE_ORIENTATION        = portrait
PAPER_MEDIA             = a4+
#-------- Basemap Annotation Parameters ------
ANNOT_MIN_ANGLE         = 20
ANNOT_MIN_SPACING       = 0
ANNOT_FONT_PRIMARY      = Helvetica
ANNOT_FONT_SIZE_PRIMARY = 14p
ANNOT_OFFSET_PRIMARY    = 0.075i
ANNOT_FONT_SECONDARY    = Helvetica
ANNOT_FONT_SIZE_SECONDARY       = 16p
ANNOT_OFFSET_SECONDARY  = 0.075i
DEGREE_SYMBOL           = ring
HEADER_FONT             = Helvetica
HEADER_FONT_SIZE        = 36p
HEADER_OFFSET           = 0.1875i
LABEL_FONT              = Helvetica
LABEL_FONT_SIZE         = 14p
LABEL_OFFSET            = 0.1125i
OBLIQUE_ANNOTATION      = 1
PLOT_CLOCK_FORMAT       = hh:mm:ss
PLOT_DATE_FORMAT        = yyyy-mm-dd
PLOT_DEGREE_FORMAT      = +ddd:mm:ss
Y_AXIS_TYPE             = hor_text
#-------- Basemap Layout Parameters ---------
BASEMAP_AXES            = WESN
BASEMAP_FRAME_RGB       = black
BASEMAP_TYPE            = plain
FRAME_PEN               = 1.25p
FRAME_WIDTH             = 0.075i
GRID_CROSS_SIZE_PRIMARY = 0i
GRID_PEN_PRIMARY        = 0.25p
GRID_CROSS_SIZE_SECONDARY       = 0i
GRID_PEN_SECONDARY      = 0.5p
MAP_SCALE_HEIGHT        = 0.075i
POLAR_CAP               = 85/90
TICK_LENGTH             = 0.075i
TICK_PEN                = 0.5p
X_AXIS_LENGTH           = 9i
Y_AXIS_LENGTH           = 6i
X_ORIGIN                = 1i
Y_ORIGIN                = 1i
UNIX_TIME               = FALSE
UNIX_TIME_POS           = BL/-0.75i/-0.75i
UNIX_TIME_FORMAT        = %Y %b %d %H:%M:%S
#-------- Color System Parameters -----------
COLOR_BACKGROUND        = black
COLOR_FOREGROUND        = white
COLOR_NAN               = 128
COLOR_IMAGE             = adobe
COLOR_MODEL             = rgb
HSV_MIN_SATURATION      = 1
HSV_MAX_SATURATION      = 0.1
HSV_MIN_VALUE           = 0.3
HSV_MAX_VALUE           = 1
#-------- PostScript Parameters -------------
CHAR_ENCODING           = ISOLatin1+
DOTS_PR_INCH            = 300
GLOBAL_X_SCALE          = 1
GLOBAL_Y_SCALE          = 1
N_COPIES                = 1
PS_COLOR                = rgb
PS_IMAGE_COMPRESS       = lzw
PS_IMAGE_FORMAT         = ascii
PS_LINE_CAP             = round
PS_LINE_JOIN            = miter
PS_MITER_LIMIT          = 35
PS_VERBOSE              = FALSE
TRANSPARENCY            = 0
#-------- I/O Format Parameters -------------
D_FORMAT                = %.12lg
FIELD_DELIMITER         = tab
GRIDFILE_FORMAT         = nf
GRIDFILE_SHORTHAND      = FALSE
INPUT_CLOCK_FORMAT      = hh:mm:ss
INPUT_DATE_FORMAT       = yyyy-mm-dd
IO_HEADER               = FALSE
N_HEADER_RECS           = 1
NAN_RECORDS             = pass
OUTPUT_CLOCK_FORMAT     = hh:mm:ss
OUTPUT_DATE_FORMAT      = yyyy-mm-dd
OUTPUT_DEGREE_FORMAT    = D
XY_TOGGLE               = FALSE
#-------- Projection Parameters -------------
ELLIPSOID               = WGS-84
MAP_SCALE_FACTOR        = default
MEASURE_UNIT            = inch
#-------- Calendar/Time Parameters ----------
TIME_FORMAT_PRIMARY     = full
TIME_FORMAT_SECONDARY   = full
TIME_EPOCH              = 2000-01-01T00:00:00
TIME_IS_INTERVAL        = OFF
TIME_INTERVAL_FRACTION  = 0.5
TIME_LANGUAGE           = us
TIME_UNIT               = d
TIME_WEEK_START         = Sunday
Y2K_OFFSET_YEAR         = 1950
#-------- Miscellaneous Parameters ----------
HISTORY                 = TRUE
INTERPOLANT             = akima
LINE_STEP               = 0.01i
VECTOR_SHAPE            = 0
VERBOSE                 = FALSE
'''

_gmt_defaults_by_version['4.5.3'] = r'''
#
#       GMT-SYSTEM 4.5.3 (CVS Jun 18 2010 10:56:07) [64-bit] Defaults file
#
#-------- Plot Media Parameters -------------
PAGE_COLOR              = white
PAGE_ORIENTATION        = portrait
PAPER_MEDIA             = a4+
#-------- Basemap Annotation Parameters ------
ANNOT_MIN_ANGLE         = 20
ANNOT_MIN_SPACING       = 0
ANNOT_FONT_PRIMARY      = Helvetica
ANNOT_FONT_SIZE_PRIMARY = 14p
ANNOT_OFFSET_PRIMARY    = 0.075i
ANNOT_FONT_SECONDARY    = Helvetica
ANNOT_FONT_SIZE_SECONDARY       = 16p
ANNOT_OFFSET_SECONDARY  = 0.075i
DEGREE_SYMBOL           = ring
HEADER_FONT             = Helvetica
HEADER_FONT_SIZE        = 36p
HEADER_OFFSET           = 0.1875i
LABEL_FONT              = Helvetica
LABEL_FONT_SIZE         = 14p
LABEL_OFFSET            = 0.1125i
OBLIQUE_ANNOTATION      = 1
PLOT_CLOCK_FORMAT       = hh:mm:ss
PLOT_DATE_FORMAT        = yyyy-mm-dd
PLOT_DEGREE_FORMAT      = +ddd:mm:ss
Y_AXIS_TYPE             = hor_text
#-------- Basemap Layout Parameters ---------
BASEMAP_AXES            = WESN
BASEMAP_FRAME_RGB       = black
BASEMAP_TYPE            = plain
FRAME_PEN               = 1.25p
FRAME_WIDTH             = 0.075i
GRID_CROSS_SIZE_PRIMARY = 0i
GRID_PEN_PRIMARY        = 0.25p
GRID_CROSS_SIZE_SECONDARY       = 0i
GRID_PEN_SECONDARY      = 0.5p
MAP_SCALE_HEIGHT        = 0.075i
POLAR_CAP               = 85/90
TICK_LENGTH             = 0.075i
TICK_PEN                = 0.5p
X_AXIS_LENGTH           = 9i
Y_AXIS_LENGTH           = 6i
X_ORIGIN                = 1i
Y_ORIGIN                = 1i
UNIX_TIME               = FALSE
UNIX_TIME_POS           = BL/-0.75i/-0.75i
UNIX_TIME_FORMAT        = %Y %b %d %H:%M:%S
#-------- Color System Parameters -----------
COLOR_BACKGROUND        = black
COLOR_FOREGROUND        = white
COLOR_NAN               = 128
COLOR_IMAGE             = adobe
COLOR_MODEL             = rgb
HSV_MIN_SATURATION      = 1
HSV_MAX_SATURATION      = 0.1
HSV_MIN_VALUE           = 0.3
HSV_MAX_VALUE           = 1
#-------- PostScript Parameters -------------
CHAR_ENCODING           = ISOLatin1+
DOTS_PR_INCH            = 300
GLOBAL_X_SCALE          = 1
GLOBAL_Y_SCALE          = 1
N_COPIES                = 1
PS_COLOR                = rgb
PS_IMAGE_COMPRESS       = lzw
PS_IMAGE_FORMAT         = ascii
PS_LINE_CAP             = round
PS_LINE_JOIN            = miter
PS_MITER_LIMIT          = 35
PS_VERBOSE              = FALSE
TRANSPARENCY            = 0
#-------- I/O Format Parameters -------------
D_FORMAT                = %.12lg
FIELD_DELIMITER         = tab
GRIDFILE_FORMAT         = nf
GRIDFILE_SHORTHAND      = FALSE
INPUT_CLOCK_FORMAT      = hh:mm:ss
INPUT_DATE_FORMAT       = yyyy-mm-dd
IO_HEADER               = FALSE
N_HEADER_RECS           = 1
NAN_RECORDS             = pass
OUTPUT_CLOCK_FORMAT     = hh:mm:ss
OUTPUT_DATE_FORMAT      = yyyy-mm-dd
OUTPUT_DEGREE_FORMAT    = D
XY_TOGGLE               = FALSE
#-------- Projection Parameters -------------
ELLIPSOID               = WGS-84
MAP_SCALE_FACTOR        = default
MEASURE_UNIT            = inch
#-------- Calendar/Time Parameters ----------
TIME_FORMAT_PRIMARY     = full
TIME_FORMAT_SECONDARY   = full
TIME_EPOCH              = 2000-01-01T00:00:00
TIME_IS_INTERVAL        = OFF
TIME_INTERVAL_FRACTION  = 0.5
TIME_LANGUAGE           = us
TIME_UNIT               = d
TIME_WEEK_START         = Sunday
Y2K_OFFSET_YEAR         = 1950
#-------- Miscellaneous Parameters ----------
HISTORY                 = TRUE
INTERPOLANT             = akima
LINE_STEP               = 0.01i
VECTOR_SHAPE            = 0
VERBOSE                 = FALSE
'''

_gmt_defaults_by_version['5.1.2'] = r'''
#
# GMT 5.1.2 Defaults file
# vim:sw=8:ts=8:sts=8
# $Revision: 13836 $
# $LastChangedDate: 2014-12-20 03:45:42 -1000 (Sat, 20 Dec 2014) $
#
# COLOR Parameters
#
COLOR_BACKGROUND = black
COLOR_FOREGROUND = white
COLOR_NAN = 127.5
COLOR_MODEL = none
COLOR_HSV_MIN_S = 1
COLOR_HSV_MAX_S = 0.1
COLOR_HSV_MIN_V = 0.3
COLOR_HSV_MAX_V = 1
#
# DIR Parameters
#
DIR_DATA =
DIR_DCW =
DIR_GSHHG =
#
# FONT Parameters
#
FONT_ANNOT_PRIMARY = 14p,Helvetica,black
FONT_ANNOT_SECONDARY = 16p,Helvetica,black
FONT_LABEL = 14p,Helvetica,black
FONT_LOGO = 8p,Helvetica,black
FONT_TITLE = 24p,Helvetica,black
#
# FORMAT Parameters
#
FORMAT_CLOCK_IN = hh:mm:ss
FORMAT_CLOCK_OUT = hh:mm:ss
FORMAT_CLOCK_MAP = hh:mm:ss
FORMAT_DATE_IN = yyyy-mm-dd
FORMAT_DATE_OUT = yyyy-mm-dd
FORMAT_DATE_MAP = yyyy-mm-dd
FORMAT_GEO_OUT = D
FORMAT_GEO_MAP = ddd:mm:ss
FORMAT_FLOAT_OUT = %.12g
FORMAT_FLOAT_MAP = %.12g
FORMAT_TIME_PRIMARY_MAP = full
FORMAT_TIME_SECONDARY_MAP = full
FORMAT_TIME_STAMP = %Y %b %d %H:%M:%S
#
# GMT Miscellaneous Parameters
#
GMT_COMPATIBILITY = 4
GMT_CUSTOM_LIBS =
GMT_EXTRAPOLATE_VAL = NaN
GMT_FFT = auto
GMT_HISTORY = true
GMT_INTERPOLANT = akima
GMT_TRIANGULATE = Shewchuk
GMT_VERBOSE = compat
GMT_LANGUAGE = us
#
# I/O Parameters
#
IO_COL_SEPARATOR = tab
IO_GRIDFILE_FORMAT = nf
IO_GRIDFILE_SHORTHAND = false
IO_HEADER = false
IO_N_HEADER_RECS = 0
IO_NAN_RECORDS = pass
IO_NC4_CHUNK_SIZE = auto
IO_NC4_DEFLATION_LEVEL = 3
IO_LONLAT_TOGGLE = false
IO_SEGMENT_MARKER = >
#
# MAP Parameters
#
MAP_ANNOT_MIN_ANGLE = 20
MAP_ANNOT_MIN_SPACING = 0p
MAP_ANNOT_OBLIQUE = 1
MAP_ANNOT_OFFSET_PRIMARY = 0.075i
MAP_ANNOT_OFFSET_SECONDARY = 0.075i
MAP_ANNOT_ORTHO = we
MAP_DEFAULT_PEN = default,black
MAP_DEGREE_SYMBOL = ring
MAP_FRAME_AXES = WESNZ
MAP_FRAME_PEN = thicker,black
MAP_FRAME_TYPE = fancy
MAP_FRAME_WIDTH = 5p
MAP_GRID_CROSS_SIZE_PRIMARY = 0p
MAP_GRID_CROSS_SIZE_SECONDARY = 0p
MAP_GRID_PEN_PRIMARY = default,black
MAP_GRID_PEN_SECONDARY = thinner,black
MAP_LABEL_OFFSET = 0.1944i
MAP_LINE_STEP = 0.75p
MAP_LOGO = false
MAP_LOGO_POS = BL/-54p/-54p
MAP_ORIGIN_X = 1i
MAP_ORIGIN_Y = 1i
MAP_POLAR_CAP = 85/90
MAP_SCALE_HEIGHT = 5p
MAP_TICK_LENGTH_PRIMARY = 5p/2.5p
MAP_TICK_LENGTH_SECONDARY = 15p/3.75p
MAP_TICK_PEN_PRIMARY = thinner,black
MAP_TICK_PEN_SECONDARY = thinner,black
MAP_TITLE_OFFSET = 14p
MAP_VECTOR_SHAPE = 0
#
# Projection Parameters
#
PROJ_AUX_LATITUDE = authalic
PROJ_ELLIPSOID = WGS-84
PROJ_LENGTH_UNIT = cm
PROJ_MEAN_RADIUS = authalic
PROJ_SCALE_FACTOR = default
#
# PostScript Parameters
#
PS_CHAR_ENCODING = ISOLatin1+
PS_COLOR_MODEL = rgb
PS_COMMENTS = false
PS_IMAGE_COMPRESS = deflate,5
PS_LINE_CAP = butt
PS_LINE_JOIN = miter
PS_MITER_LIMIT = 35
PS_MEDIA = a4
PS_PAGE_COLOR = white
PS_PAGE_ORIENTATION = portrait
PS_SCALE_X = 1
PS_SCALE_Y = 1
PS_TRANSPARENCY = Normal
#
# Calendar/Time Parameters
#
TIME_EPOCH = 1970-01-01T00:00:00
TIME_IS_INTERVAL = off
TIME_INTERVAL_FRACTION = 0.5
TIME_UNIT = s
TIME_WEEK_START = Monday
TIME_Y2K_OFFSET_YEAR = 1950
'''


def get_gmt_version(gmtdefaultsbinary, gmthomedir=None):
    args = [gmtdefaultsbinary]

    environ = os.environ.copy()
    environ['GMTHOME'] = gmthomedir or ''

    p = subprocess.Popen(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environ)

    (stdout, stderr) = p.communicate()
    m = re.search(br'(\d+(\.\d+)*)', stderr) \
        or re.search(br'# GMT (\d+(\.\d+)*)', stdout)

    if not m:
        raise GMTInstallationProblem(
            "Can't extract version number from output of %s."
            % gmtdefaultsbinary)

    return str(m.group(1).decode('ascii'))


def detect_gmt_installations():

    installations = {}
    errmesses = []

    # GMT 4.x:
    try:
        p = subprocess.Popen(
            ['GMT'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE)

        (stdout, stderr) = p.communicate()

        m = re.search(br'Version\s+(\d+(\.\d+)*)', stderr, re.M)
        if not m:
            raise GMTInstallationProblem(
                "Can't get version number from output of GMT.")

        version = str(m.group(1).decode('ascii'))
        if version[0] != '5':

            m = re.search(br'^\s+executables\s+(.+)$', stderr, re.M)
            if not m:
                raise GMTInstallationProblem(
                    "Can't extract executables dir from output of GMT.")

            gmtbin = str(m.group(1).decode('ascii'))

            m = re.search(br'^\s+shared data\s+(.+)$', stderr, re.M)
            if not m:
                raise GMTInstallationProblem(
                    "Can't extract shared dir from output of GMT.")

            gmtshare = str(m.group(1).decode('ascii'))
            if not gmtshare.endswith('/share'):
                raise GMTInstallationProblem(
                    "Can't determine GMTHOME from output of GMT.")

            gmthome = gmtshare[:-6]

            installations[version] = {
                'home': gmthome,
                'bin': gmtbin}

    except OSError as e:
        errmesses.append(('GMT', str(e)))

    try:
        version = str(subprocess.check_output(
            ['gmt', '--version']).strip().decode('ascii')).split('_')[0]
        gmtbin = str(subprocess.check_output(
            ['gmt', '--show-bindir']).strip().decode('ascii'))
        installations[version] = {
            'bin': gmtbin}

    except (OSError, subprocess.CalledProcessError) as e:
        errmesses.append(('gmt', str(e)))

    if not installations:
        s = []
        for (progname, errmess) in errmesses:
            s.append('Cannot start "%s" executable: %s' % (progname, errmess))

        raise GMTInstallationProblem(', '.join(s))

    return installations


def appropriate_defaults_version(version):
    avails = sorted(_gmt_defaults_by_version.keys(), key=key_version)
    for iavail, avail in enumerate(avails):
        if key_version(version) == key_version(avail):
            return version

        elif key_version(version) < key_version(avail):
            return avails[max(0, iavail-1)]

    return avails[-1]


def gmt_default_config(version):
    '''
    Get default GMT configuration dict for given version.
    '''

    xversion = appropriate_defaults_version(version)

    # if not version in _gmt_defaults_by_version:
    #     raise GMTError('No GMT defaults for version %s found' % version)

    gmt_defaults = _gmt_defaults_by_version[xversion]

    d = {}
    for line in gmt_defaults.splitlines():
        sline = line.strip()
        if not sline or sline.startswith('#'):
            continue

        k, v = sline.split('=', 1)
        d[k.strip()] = v.strip()

    return d


def diff_defaults(v1, v2):
    d1 = gmt_default_config(v1)
    d2 = gmt_default_config(v2)
    for k in d1:
        if k not in d2:
            print('%s not in %s' % (k, v2))
        else:
            if d1[k] != d2[k]:
                print('%s %s = %s' % (v1, k, d1[k]))
                print('%s %s = %s' % (v2, k, d2[k]))

    for k in d2:
        if k not in d1:
            print('%s not in %s' % (k, v1))

# diff_defaults('4.5.2', '4.5.3')


def check_gmt_installation(installation):

    home_dir = installation.get('home', None)
    bin_dir = installation['bin']
    version = installation['version']

    for d in home_dir, bin_dir:
        if d is not None:
            if not os.path.exists(d):
                logging.error(('Directory does not exist: %s\n'
                              'Check your GMT installation.') % d)

    major_version = version.split('.')[0]

    if major_version not in ['5', '6']:
        gmtdefaults = pjoin(bin_dir, 'gmtdefaults')

        versionfound = get_gmt_version(gmtdefaults, home_dir)

        if versionfound != version:
            raise GMTInstallationProblem((
                'Expected GMT version %s but found version %s.\n'
                '(Looking at output of %s)') % (
                    version, versionfound, gmtdefaults))


def get_gmt_installation(version):
    setup_gmt_installations()
    if version != 'newest' and version not in _gmt_installations:
        logging.warn('GMT version %s not installed, taking version %s instead'
                     % (version, newest_installed_gmt_version()))

        version = 'newest'

    if version == 'newest':
        version = newest_installed_gmt_version()

    installation = dict(_gmt_installations[version])

    return installation


def setup_gmt_installations():
    if not setup_gmt_installations.have_done:
        if not _gmt_installations:

            _gmt_installations.update(detect_gmt_installations())

        # store defaults as dicts into the gmt installations dicts
        for version, installation in _gmt_installations.items():
            installation['defaults'] = gmt_default_config(version)
            installation['version'] = version

        for installation in _gmt_installations.values():
            check_gmt_installation(installation)

        setup_gmt_installations.have_done = True


setup_gmt_installations.have_done = False

_paper_sizes_a = '''A0 2380 3368
                      A1 1684 2380
                      A2 1190 1684
                      A3 842 1190
                      A4 595 842
                      A5 421 595
                      A6 297 421
                      A7 210 297
                      A8 148 210
                      A9 105 148
                      A10 74 105
                      B0 2836 4008
                      B1 2004 2836
                      B2 1418 2004
                      B3 1002 1418
                      B4 709 1002
                      B5 501 709
                      archA 648 864
                      archB 864 1296
                      archC 1296 1728
                      archD 1728 2592
                      archE 2592 3456
                      flsa 612 936
                      halfletter 396 612
                      note 540 720
                      letter 612 792
                      legal 612 1008
                      11x17 792 1224
                      ledger 1224 792'''


_paper_sizes = {}


def setup_paper_sizes():
    if not _paper_sizes:
        for line in _paper_sizes_a.splitlines():
            k, w, h = line.split()
            _paper_sizes[k.lower()] = float(w), float(h)


def get_paper_size(k):
    setup_paper_sizes()
    return _paper_sizes[k.lower().rstrip('+')]


def all_paper_sizes():
    setup_paper_sizes()
    return _paper_sizes


def measure_unit(gmt_config):
    for k in ['MEASURE_UNIT', 'PROJ_LENGTH_UNIT']:
        if k in gmt_config:
            return gmt_config[k]

    raise GmtPyError('cannot get measure unit / proj length unit from config')


def paper_media(gmt_config):
    for k in ['PAPER_MEDIA', 'PS_MEDIA']:
        if k in gmt_config:
            return gmt_config[k]

    raise GmtPyError('cannot get paper media from config')


def page_orientation(gmt_config):
    for k in ['PAGE_ORIENTATION', 'PS_PAGE_ORIENTATION']:
        if k in gmt_config:
            return gmt_config[k]

    raise GmtPyError('cannot get paper orientation from config')


def make_bbox(width, height, gmt_config, margins=(0.8, 0.8, 0.8, 0.8)):

    leftmargin, topmargin, rightmargin, bottommargin = margins
    portrait = page_orientation(gmt_config).lower() == 'portrait'

    paper_size = get_paper_size(paper_media(gmt_config))
    if not portrait:
        paper_size = paper_size[1], paper_size[0]

    xoffset = (paper_size[0] - (width + leftmargin + rightmargin)) / \
        2.0 + leftmargin
    yoffset = (paper_size[1] - (height + topmargin + bottommargin)) / \
        2.0 + bottommargin

    if portrait:
        bb1 = int((xoffset - leftmargin))
        bb2 = int((yoffset - bottommargin))
        bb3 = bb1 + int((width+leftmargin+rightmargin))
        bb4 = bb2 + int((height+topmargin+bottommargin))
    else:
        bb1 = int((yoffset - topmargin))
        bb2 = int((xoffset - leftmargin))
        bb3 = bb1 + int((height+topmargin+bottommargin))
        bb4 = bb2 + int((width+leftmargin+rightmargin))

    return xoffset, yoffset, (bb1, bb2, bb3, bb4)


def gmtdefaults_as_text(version='newest'):

    '''
    Get the built-in gmtdefaults.
    '''

    if version not in _gmt_installations:
        logging.warn('GMT version %s not installed, taking version %s instead'
                     % (version, newest_installed_gmt_version()))
        version = 'newest'

    if version == 'newest':
        version = newest_installed_gmt_version()

    return _gmt_defaults_by_version[version]


def savegrd(x, y, z, filename, title=None, naming='xy'):
    '''
    Write COARDS compliant netcdf (grd) file.
    '''

    assert y.size, x.size == z.shape
    ny, nx = z.shape
    nc = netcdf_file(filename, 'w')
    assert naming in ('xy', 'lonlat')

    if naming == 'xy':
        kx, ky = 'x', 'y'
    else:
        kx, ky = 'lon', 'lat'

    nc.node_offset = 0
    if title is not None:
        nc.title = title

    nc.Conventions = 'COARDS/CF-1.0'
    nc.createDimension(kx, nx)
    nc.createDimension(ky, ny)

    xvar = nc.createVariable(kx, 'd', (kx,))
    yvar = nc.createVariable(ky, 'd', (ky,))
    if naming == 'xy':
        xvar.long_name = kx
        yvar.long_name = ky
    else:
        xvar.long_name = 'longitude'
        xvar.units = 'degrees_east'
        yvar.long_name = 'latitude'
        yvar.units = 'degrees_north'

    zvar = nc.createVariable('z', 'd', (ky, kx))

    xvar[:] = x.astype(num.float64)
    yvar[:] = y.astype(num.float64)
    zvar[:] = z.astype(num.float64)

    nc.close()


def to_array(var):
    arr = var[:].copy()
    if hasattr(var, 'scale_factor'):
        arr *= var.scale_factor

    if hasattr(var, 'add_offset'):
        arr += var.add_offset

    return arr


def loadgrd(filename):
    '''
    Read COARDS compliant netcdf (grd) file.
    '''

    nc = netcdf_file(filename, 'r')
    vkeys = list(nc.variables.keys())
    kx = 'x'
    ky = 'y'
    if 'lon' in vkeys:
        kx = 'lon'
    if 'lat' in vkeys:
        ky = 'lat'

    kz = 'z'
    if 'altitude' in vkeys:
        kz = 'altitude'

    x = to_array(nc.variables[kx])
    y = to_array(nc.variables[ky])
    z = to_array(nc.variables[kz])

    nc.close()
    return x, y, z


def centers_to_edges(asorted):
    return (asorted[1:] + asorted[:-1])/2.


def nvals(asorted):
    eps = (asorted[-1]-asorted[0])/asorted.size
    return num.sum(asorted[1:] - asorted[:-1] >= eps) + 1


def guess_vals(asorted):
    eps = (asorted[-1]-asorted[0])/asorted.size
    indis = num.nonzero(asorted[1:] - asorted[:-1] >= eps)[0]
    indis = num.concatenate((num.array([0]), indis+1,
                             num.array([asorted.size])))
    asum = num.zeros(asorted.size+1)
    asum[1:] = num.cumsum(asorted)
    return (asum[indis[1:]] - asum[indis[:-1]]) / (indis[1:]-indis[:-1])


def blockmean(asorted, b):
    indis = num.nonzero(asorted[1:] - asorted[:-1])[0]
    indis = num.concatenate((num.array([0]), indis+1,
                             num.array([asorted.size])))
    bsum = num.zeros(b.size+1)
    bsum[1:] = num.cumsum(b)
    return (
        asorted[indis[:-1]],
        (bsum[indis[1:]] - bsum[indis[:-1]]) / (indis[1:]-indis[:-1]))


def griddata_regular(x, y, z, xvals, yvals):
    nx, ny = xvals.size, yvals.size
    xindi = num.digitize(x, centers_to_edges(xvals))
    yindi = num.digitize(y, centers_to_edges(yvals))

    zindi = yindi*nx+xindi
    order = num.argsort(zindi)
    z = z[order]
    zindi = zindi[order]

    zindi, z = blockmean(zindi, z)
    znew = num.empty(nx*ny, dtype=float)
    znew[:] = num.nan
    znew[zindi] = z
    return znew.reshape(ny, nx)


def guess_field_size(x_sorted, y_sorted, z=None, mode=None):
    critical_fraction = 1./num.e - 0.014*3
    xs = x_sorted
    ys = y_sorted
    nxs, nys = nvals(xs), nvals(ys)
    if mode == 'nonrandom':
        return nxs, nys, 0
    elif xs.size == nxs*nys:
        # exact match
        return nxs, nys, 0
    elif nxs >= xs.size*critical_fraction and nys >= xs.size*critical_fraction:
        # possibly randomly sampled
        nxs = int(math.sqrt(xs.size))
        nys = nxs
        return nxs, nys, 2
    else:
        return nxs, nys, 1


def griddata_auto(x, y, z, mode=None):
    '''
    Grid tabular XYZ data by binning.

    This function does some extra work to guess the size of the grid. This
    should work fine if the input values are already defined on an rectilinear
    grid, even if data points are missing or duplicated. This routine also
    tries to detect a random distribution of input data and in that case
    creates a grid of size sqrt(N) x sqrt(N).

    The points do not have to be given in any particular order. Grid nodes
    without data are assigned the NaN value. If multiple data points map to the
    same grid node, their average is assigned to the grid node.
    '''

    x, y, z = [num.asarray(X) for X in (x, y, z)]
    assert x.size == y.size == z.size
    xs, ys = num.sort(x), num.sort(y)
    nx, ny, badness = guess_field_size(xs, ys, z, mode=mode)
    if badness <= 1:
        xf = guess_vals(xs)
        yf = guess_vals(ys)
        zf = griddata_regular(x, y, z, xf, yf)
    else:
        xf = num.linspace(xs[0], xs[-1], nx)
        yf = num.linspace(ys[0], ys[-1], ny)
        zf = griddata_regular(x, y, z, xf, yf)

    return xf, yf, zf


def tabledata(xf, yf, zf):
    assert yf.size, xf.size == zf.shape
    x = num.tile(xf, yf.size)
    y = num.repeat(yf, xf.size)
    z = zf.flatten()
    return x, y, z


def double1d(a):
    a2 = num.empty(a.size*2-1)
    a2[::2] = a
    a2[1::2] = (a[:-1] + a[1:])/2.
    return a2


def double2d(f):
    f2 = num.empty((f.shape[0]*2-1, f.shape[1]*2-1))
    f2[:, :] = num.nan
    f2[::2, ::2] = f
    f2[1::2, ::2] = (f[:-1, :] + f[1:, :])/2.
    f2[::2, 1::2] = (f[:, :-1] + f[:, 1:])/2.
    f2[1::2, 1::2] = (f[:-1, :-1] + f[1:, :-1] + f[:-1, 1:] + f[1:, 1:])/4.
    diag = f2[1::2, 1::2]
    diagA = (f[:-1, :-1] + f[1:, 1:]) / 2.
    diagB = (f[1:, :-1] + f[:-1, 1:]) / 2.
    f2[1::2, 1::2] = num.where(num.isnan(diag), diagA, diag)
    f2[1::2, 1::2] = num.where(num.isnan(diag), diagB, diag)
    return f2


def doublegrid(x, y, z):
    x2 = double1d(x)
    y2 = double1d(y)
    z2 = double2d(z)
    return x2, y2, z2


class Guru(object):
    '''
    Abstract base class providing template interpolation, accessible as
    attributes.

    Classes deriving from this one, have to implement a :py:meth:`get_params`
    method, which is called to get a dict to do ordinary
    ``"%(key)x"``-substitutions. The deriving class must also provide a dict
    with the templates.
    '''

    def __init__(self):
        self.templates = {}

    def get_params(self, ax_projection=False):
        '''
        To be implemented in subclasses.
        '''
        raise NotImplementedError

    def fill(self, templates, **kwargs):
        params = self.get_params(**kwargs)
        strings = [t % params for t in templates]
        return strings

    # hand through templates dict
    def __getitem__(self, template_name):
        return self.templates[template_name]

    def __setitem__(self, template_name, template):
        self.templates[template_name] = template

    def __contains__(self, template_name):
        return template_name in self.templates

    def __iter__(self):
        return iter(self.templates)

    def __len__(self):
        return len(self.templates)

    def __delitem__(self, template_name):
        del self.templates[template_name]

    def _simple_fill(self, template_names, **kwargs):
        templates = [self.templates[n] for n in template_names]
        return self.fill(templates, **kwargs)

    def __getattr__(self, template_names):
        if [n for n in template_names if n not in self.templates]:
            raise AttributeError(template_names)

        def f(**kwargs):
            return self._simple_fill(template_names, **kwargs)

        return f


class Ax(AutoScaler):
    '''
    Ax description with autoscaling capabilities.

    The ax is described by the :py:class:`~pyrocko.plot.AutoScaler`
    public attributes, plus the following additional attributes
    (with default values given in paranthesis):

      .. py:attribute:: label

          Ax label (without unit).

      .. py:attribute:: unit

          Physical unit of the data attached to this ax.

      .. py:attribute:: scaled_unit

           (see below)

      .. py:attribute:: scaled_unit_factor

          Scaled physical unit and factor between unit and scaled_unit so that

            unit = scaled_unit_factor x scaled_unit.

          (E.g. if unit is 'm' and data is in the range of nanometers, you may
          want to set the scaled_unit to 'nm' and the scaled_unit_factor to
          1e9.)

      .. py:attribute:: limits

          If defined, fix range of ax to limits=(min,max).

      .. py:attribute:: masking

          If true and if there is a limit on the ax, while calculating ranges,
          the data points are masked such that data points outside of this axes
          limits are not used to determine the range of another dependant ax.

    '''

    def __init__(self, label='', unit='', scaled_unit_factor=1.,
                 scaled_unit='', limits=None, masking=True, **kwargs):

        AutoScaler.__init__(self, **kwargs)
        self.label = label
        self.unit = unit
        self.scaled_unit_factor = scaled_unit_factor
        self.scaled_unit = scaled_unit
        self.limits = limits
        self.masking = masking

    def label_str(self, exp, unit):
        '''
        Get label string including the unit and multiplier.
        '''

        slabel, sunit, sexp = '', '', ''
        if self.label:
            slabel = self.label

        if unit or exp != 0:
            if exp != 0:
                sexp = '\\327 10@+%i@+' % exp
                sunit = '[ %s %s ]' % (sexp, unit)
            else:
                sunit = '[ %s ]' % unit

        p = []
        if slabel:
            p.append(slabel)

        if sunit:
            p.append(sunit)

        return ' '.join(p)

    def make_params(self, data_range, ax_projection=False, override_mode=None,
                    override_scaled_unit_factor=None):

        '''
        Get minimum, maximum, increment and label string for ax display.'

        Returns minimum, maximum, increment and label string including unit and
        multiplier for given data range.

        If ``ax_projection`` is True, values suitable to be displayed on the ax
        are returned, e.g. min, max and inc are returned in scaled units.
        Otherwise the values are returned in the original units, without any
        scaling applied.
        '''

        sf = self.scaled_unit_factor

        if override_scaled_unit_factor is not None:
            sf = override_scaled_unit_factor

        dr_scaled = [sf*x for x in data_range]

        mi, ma, inc = self.make_scale(dr_scaled, override_mode=override_mode)
        if self.inc is not None:
            inc = self.inc*sf

        if ax_projection:
            exp = self.make_exp(inc)
            if sf == 1. and override_scaled_unit_factor is None:
                unit = self.unit
            else:
                unit = self.scaled_unit
            label = self.label_str(exp, unit)
            return mi/10**exp, ma/10**exp, inc/10**exp, label
        else:
            label = self.label_str(0, self.unit)
            return mi/sf, ma/sf, inc/sf, label


class ScaleGuru(Guru):

    '''
    2D/3D autoscaling and ax annotation facility.

    Instances of this class provide automatic determination of plot ranges,
    tick increments and scaled annotations, as well as label/unit handling. It
    can in particular be used to automatically generate the -R and -B option
    arguments, which are required for most GMT commands.

    It extends the functionality of the :py:class:`Ax` and
    :py:class:`~pyrocko.plot.AutoScaler` classes at the level, where it can not
    be handled anymore by looking at a single dimension of the dataset's data,
    e.g.:

    * The ability to impose a fixed aspect ratio between two axes.

    * Recalculation of data range on non-limited axes, when there are
      limits imposed on other axes.

    '''

    def __init__(self, data_tuples=None, axes=None, aspect=None,
                 percent_interval=None, copy_from=None):

        Guru.__init__(self)

        if copy_from:
            self.templates = copy.deepcopy(copy_from.templates)
            self.axes = copy.deepcopy(copy_from.axes)
            self.data_ranges = copy.deepcopy(copy_from.data_ranges)
            self.aspect = copy_from.aspect

        if percent_interval is not None:
            from scipy.stats import scoreatpercentile as scap

        self.templates = dict(
            R='-R%(xmin)g/%(xmax)g/%(ymin)g/%(ymax)g',
            B='-B%(xinc)g:%(xlabel)s:/%(yinc)g:%(ylabel)s:WSen',
            T='-T%(zmin)g/%(zmax)g/%(zinc)g')

        maxdim = 2
        if data_tuples:
            maxdim = max(maxdim, max([len(dt) for dt in data_tuples]))
        else:
            if axes:
                maxdim = len(axes)
            data_tuples = [([],) * maxdim]
        if axes is not None:
            self.axes = axes
        else:
            self.axes = [Ax() for i in range(maxdim)]

        # sophisticated data-range calculation
        data_ranges = [None] * maxdim
        for dt_ in data_tuples:
            dt = num.asarray(dt_)
            in_range = True
            for ax, x in zip(self.axes, dt):
                if ax.limits and ax.masking:
                    ax_limits = list(ax.limits)
                    if ax_limits[0] is None:
                        ax_limits[0] = -num.inf
                    if ax_limits[1] is None:
                        ax_limits[1] = num.inf
                    in_range = num.logical_and(
                        in_range,
                        num.logical_and(ax_limits[0] <= x, x <= ax_limits[1]))

            for i, ax, x in zip(range(maxdim), self.axes, dt):

                if not ax.limits or None in ax.limits:
                    if len(x) >= 1:
                        if in_range is not True:
                            xmasked = num.where(in_range, x, num.NaN)
                            if percent_interval is None:
                                range_this = (
                                    num.nanmin(xmasked),
                                    num.nanmax(xmasked))
                            else:
                                xmasked_finite = num.compress(
                                    num.isfinite(xmasked), xmasked)
                                range_this = (
                                    scap(xmasked_finite,
                                         (100.-percent_interval)/2.),
                                    scap(xmasked_finite,
                                         100.-(100.-percent_interval)/2.))
                        else:
                            if percent_interval is None:
                                range_this = num.nanmin(x), num.nanmax(x)
                            else:
                                xmasked_finite = num.compress(
                                    num.isfinite(xmasked), xmasked)
                                range_this = (
                                    scap(xmasked_finite,
                                         (100.-percent_interval)/2.),
                                    scap(xmasked_finite,
                                         100.-(100.-percent_interval)/2.))
                    else:
                        range_this = (0., 1.)

                    if ax.limits:
                        if ax.limits[0] is not None:
                            range_this = ax.limits[0], max(ax.limits[0],
                                                           range_this[1])

                        if ax.limits[1] is not None:
                            range_this = min(ax.limits[1],
                                             range_this[0]), ax.limits[1]

                else:
                    range_this = ax.limits

                if data_ranges[i] is None and range_this[0] <= range_this[1]:
                    data_ranges[i] = range_this
                else:
                    mi, ma = range_this
                    if data_ranges[i] is not None:
                        mi = min(data_ranges[i][0], mi)
                        ma = max(data_ranges[i][1], ma)

                    data_ranges[i] = (mi, ma)

        for i in range(len(data_ranges)):
            if data_ranges[i] is None or not (
                    num.isfinite(data_ranges[i][0])
                    and num.isfinite(data_ranges[i][1])):

                data_ranges[i] = (0., 1.)

        self.data_ranges = data_ranges
        self.aspect = aspect

    def copy(self):
        return ScaleGuru(copy_from=self)

    def get_params(self, ax_projection=False):

        '''
        Get dict with output parameters.

        For each data dimension, ax minimum, maximum, increment and a label
        string (including unit and exponential factor) are determined. E.g. in
        for the first dimension the output dict will contain the keys
        ``'xmin'``, ``'xmax'``, ``'xinc'``, and ``'xlabel'``.

        Normally, values corresponding to the scaling of the raw data are
        produced, but if ``ax_projection`` is ``True``, values which are
        suitable to be printed on the axes are returned. This means that in the
        latter case, the :py:attr:`Ax.scaled_unit` and
        :py:attr:`Ax.scaled_unit_factor` attributes as set on the axes are
        respected and that a common 10^x factor is factored out and put to the
        label string.
        '''

        xmi, xma, xinc, xlabel = self.axes[0].make_params(
            self.data_ranges[0], ax_projection)
        ymi, yma, yinc, ylabel = self.axes[1].make_params(
            self.data_ranges[1], ax_projection)
        if len(self.axes) > 2:
            zmi, zma, zinc, zlabel = self.axes[2].make_params(
                self.data_ranges[2], ax_projection)

        # enforce certain aspect, if needed
        if self.aspect is not None:
            xwid = xma-xmi
            ywid = yma-ymi
            if ywid < xwid*self.aspect:
                ymi -= (xwid*self.aspect - ywid)*0.5
                yma += (xwid*self.aspect - ywid)*0.5
                ymi, yma, yinc, ylabel = self.axes[1].make_params(
                    (ymi, yma), ax_projection, override_mode='off',
                    override_scaled_unit_factor=1.)

            elif xwid < ywid/self.aspect:
                xmi -= (ywid/self.aspect - xwid)*0.5
                xma += (ywid/self.aspect - xwid)*0.5
                xmi, xma, xinc, xlabel = self.axes[0].make_params(
                    (xmi, xma), ax_projection, override_mode='off',
                    override_scaled_unit_factor=1.)

        params = dict(xmin=xmi, xmax=xma, xinc=xinc, xlabel=xlabel,
                      ymin=ymi, ymax=yma, yinc=yinc, ylabel=ylabel)
        if len(self.axes) > 2:
            params.update(dict(zmin=zmi, zmax=zma, zinc=zinc, zlabel=zlabel))

        return params


class GumSpring(object):

    '''
    Sizing policy implementing a minimal size, plus a desire to grow.
    '''

    def __init__(self, minimal=None, grow=None):
        self.minimal = minimal
        if grow is None:
            if minimal is None:
                self.grow = 1.0
            else:
                self.grow = 0.0
        else:
            self.grow = grow
        self.value = 1.0

    def get_minimal(self):
        if self.minimal is not None:
            return self.minimal
        else:
            return 0.0

    def get_grow(self):
        return self.grow

    def set_value(self, value):
        self.value = value

    def get_value(self):
        return self.value


def distribute(sizes, grows, space):
    sizes = list(sizes)
    gsum = sum(grows)
    if gsum > 0.0:
        for i in range(len(sizes)):
            sizes[i] += space*grows[i]/gsum
    return sizes


class Widget(Guru):

    '''
    Base class of the gmtpy layout system.

    The Widget class provides the basic functionality for the nesting and
    placing of elements on the output page, and maintains the sizing policies
    of each element. Each of the layouts defined in gmtpy is itself a Widget.

    Sizing of the widget is controlled by :py:meth:`get_min_size` and
    :py:meth:`get_grow` which should be overloaded in derived classes. The
    basic behaviour of a Widget instance is to have a vertical and a horizontal
    minimum size which default to zero, as well as a vertical and a horizontal
    desire to grow, represented by floats, which default to 1.0. Additionally
    an aspect ratio constraint may be imposed on the Widget.

    After layouting, the widget provides its width, height, x-offset and
    y-offset in various ways. Via the Guru interface (see :py:class:`Guru`
    class), templates for the -X, -Y and -J option arguments used by GMT
    arguments are provided.  The defaults are suitable for plotting of linear
    (-JX) plots. Other projections can be selected by giving an appropriate 'J'
    template, or by manual construction of the -J option, e.g. by utilizing the
    :py:meth:`width` and :py:meth:`height` methods. The :py:meth:`bbox` method
    can be used to create a PostScript bounding box from the widgets border,
    e.g. for use in :py:meth:`GMT.save`.

    The convention is, that all sizes are given in PostScript points.
    Conversion factors are provided as constants :py:const:`inch` and
    :py:const:`cm` in the gmtpy module.
    '''

    def __init__(self, horizontal=None, vertical=None, parent=None):

        '''
        Create new widget.
        '''

        Guru.__init__(self)

        self.templates = dict(
            X='-Xa%(xoffset)gp',
            Y='-Ya%(yoffset)gp',
            J='-JX%(width)gp/%(height)gp')

        if horizontal is None:
            self.horizontal = GumSpring()
        else:
            self.horizontal = horizontal

        if vertical is None:
            self.vertical = GumSpring()
        else:
            self.vertical = vertical

        self.aspect = None
        self.parent = parent
        self.dirty = True

    def set_widget(self):
        '''
        To be implemented in subclasses.
        '''
        raise NotImplementedError

    def set_parent(self, parent):

        '''
        Set the parent widget.

        This method should not be called directly. The :py:meth:`set_widget`
        methods are responsible for calling this.
        '''

        self.parent = parent
        self.dirtyfy()

    def get_parent(self):

        '''
        Get the widgets parent widget.
        '''

        return self.parent

    def get_root(self):

        '''
        Get the root widget in the layout hierarchy.
        '''

        if self.parent is not None:
            return self.get_parent()
        else:
            return self

    def set_horizontal(self, minimal=None, grow=None):

        '''
        Set the horizontal sizing policy of the Widget.


        :param minimal: new minimal width of the widget
        :param grow:    new horizontal grow disire of the widget
        '''

        self.horizontal = GumSpring(minimal, grow)
        self.dirtyfy()

    def get_horizontal(self):
        return self.horizontal.get_minimal(), self.horizontal.get_grow()

    def set_vertical(self, minimal=None, grow=None):

        '''
        Set the horizontal sizing policy of the Widget.

        :param minimal: new minimal height of the widget
        :param grow:    new vertical grow disire of the widget
        '''

        self.vertical = GumSpring(minimal, grow)
        self.dirtyfy()

    def get_vertical(self):
        return self.vertical.get_minimal(), self.vertical.get_grow()

    def set_aspect(self, aspect=None):

        '''
        Set aspect constraint on the widget.

        The aspect is given as height divided by width.
        '''

        self.aspect = aspect
        self.dirtyfy()

    def set_policy(self, minimal=(None, None), grow=(None, None), aspect=None):

        '''
        Shortcut to set sizing and aspect constraints in a single method
        call.
        '''

        self.set_horizontal(minimal[0], grow[0])
        self.set_vertical(minimal[1], grow[1])
        self.set_aspect(aspect)

    def get_policy(self):
        mh, gh = self.get_horizontal()
        mv, gv = self.get_vertical()
        return (mh, mv), (gh, gv), self.aspect

    def legalize(self, size, offset):

        '''
        Get legal size for widget.

        Returns: (new_size, new_offset)

        Given a box as ``size`` and ``offset``, return ``new_size`` and
        ``new_offset``, such that the widget's sizing and aspect constraints
        are fullfilled. The returned box is centered on the given input box.
        '''

        sh, sv = size
        oh, ov = offset
        shs, svs = Widget.get_min_size(self)
        ghs, gvs = Widget.get_grow(self)

        if ghs == 0.0:
            oh += (sh-shs)/2.
            sh = shs

        if gvs == 0.0:
            ov += (sv-svs)/2.
            sv = svs

        if self.aspect is not None:
            if sh > sv/self.aspect:
                oh += (sh-sv/self.aspect)/2.
                sh = sv/self.aspect
            if sv > sh*self.aspect:
                ov += (sv-sh*self.aspect)/2.
                sv = sh*self.aspect

        return (sh, sv), (oh, ov)

    def get_min_size(self):

        '''
        Get minimum size of widget.

        Used by the layout managers. Should be overloaded in derived classes.
        '''

        mh, mv = self.horizontal.get_minimal(), self.vertical.get_minimal()
        if self.aspect is not None:
            if mv == 0.0:
                return mh, mh*self.aspect
            elif mh == 0.0:
                return mv/self.aspect, mv
        return mh, mv

    def get_grow(self):

        '''
        Get widget's desire to grow.

        Used by the layout managers. Should be overloaded in derived classes.
        '''

        return self.horizontal.get_grow(), self.vertical.get_grow()

    def set_size(self, size, offset):

        '''
        Set the widget's current size.

        Should not be called directly. It is the layout manager's
        responsibility to call this.
        '''

        (sh, sv), inner_offset = self.legalize(size, offset)
        self.offset = inner_offset
        self.horizontal.set_value(sh)
        self.vertical.set_value(sv)
        self.dirty = False

    def __str__(self):

        def indent(ind, str):
            return ('\n'+ind).join(str.splitlines())
        size, offset = self.get_size()
        s = '%s (%g x %g) (%g, %g)\n' % ((self.__class__,) + size + offset)
        children = self.get_children()
        if children:
            s += '\n'.join(['  ' + indent('  ', str(c)) for c in children])
        return s

    def policies_debug_str(self):

        def indent(ind, str):
            return ('\n'+ind).join(str.splitlines())
        mins, grows, aspect = self.get_policy()
        s = '%s: minimum=(%s, %s), grow=(%s, %s), aspect=%s\n' % (
            (self.__class__,) + mins+grows+(aspect,))

        children = self.get_children()
        if children:
            s += '\n'.join(['  ' + indent(
                '  ', c.policies_debug_str()) for c in children])
        return s

    def get_corners(self, descend=False):

        '''
        Get coordinates of the corners of the widget.

        Returns list with coordinate tuples.

        If ``descend`` is True, the returned list will contain corner
        coordinates of all sub-widgets.
        '''

        self.do_layout()
        (sh, sv), (oh, ov) = self.get_size()
        corners = [(oh, ov), (oh+sh, ov), (oh+sh, ov+sv), (oh, ov+sv)]
        if descend:
            for child in self.get_children():
                corners.extend(child.get_corners(descend=True))
        return corners

    def get_sizes(self):

        '''
        Get sizes of this widget and all it's children.

        Returns a list with size tuples.
        '''
        self.do_layout()
        sizes = [self.get_size()]
        for child in self.get_children():
            sizes.extend(child.get_sizes())
        return sizes

    def do_layout(self):

        '''
        Triggers layouting of the widget hierarchy, if needed.
        '''

        if self.parent is not None:
            return self.parent.do_layout()

        if not self.dirty:
            return

        sh, sv = self.get_min_size()
        gh, gv = self.get_grow()
        if sh == 0.0 and gh != 0.0:
            sh = 15.*cm
        if sv == 0.0 and gv != 0.0:
            sv = 15.*cm*gv/gh * 1./golden_ratio
        self.set_size((sh, sv), (0., 0.))

    def get_children(self):

        '''
        Get sub-widgets contained in this widget.

        Returns a list of widgets.
        '''

        return []

    def get_size(self):

        '''
        Get current size and position of the widget.

        Triggers layouting and returns
        ``((width, height), (xoffset, yoffset))``
        '''

        self.do_layout()
        return (self.horizontal.get_value(),
                self.vertical.get_value()), self.offset

    def get_params(self):

        '''
        Get current size and position of the widget.

        Triggers layouting and returns dict with keys ``'xoffset'``,
        ``'yoffset'``, ``'width'`` and ``'height'``.
        '''

        self.do_layout()
        (w, h), (xo, yo) = self.get_size()
        return dict(xoffset=xo, yoffset=yo, width=w, height=h,
                    width_m=w/_units['m'])

    def width(self):

        '''
        Get current width of the widget.

        Triggers layouting and returns width.
        '''

        self.do_layout()
        return self.horizontal.get_value()

    def height(self):

        '''
        Get current height of the widget.

        Triggers layouting and return height.
        '''

        self.do_layout()
        return self.vertical.get_value()

    def bbox(self):

        '''
        Get PostScript bounding box for this widget.

        Triggers layouting and returns values suitable to create PS bounding
        box, representing the widgets current size and position.
        '''

        self.do_layout()
        return (self.offset[0], self.offset[1], self.offset[0]+self.width(),
                self.offset[1]+self.height())

    def dirtyfy(self):

        '''
        Set dirty flag on top level widget in the hierarchy.

        Called by various methods, to indicate, that the widget hierarchy needs
        new layouting.
        '''

        if self.parent is not None:
            self.parent.dirtyfy()

        self.dirty = True


class CenterLayout(Widget):

    '''
    A layout manager which centers its single child widget.

    The child widget may be oversized.
    '''

    def __init__(self, horizontal=None, vertical=None):
        Widget.__init__(self, horizontal, vertical)
        self.content = Widget(horizontal=GumSpring(grow=1.),
                              vertical=GumSpring(grow=1.), parent=self)

    def get_min_size(self):
        shs, svs = Widget.get_min_size(self)
        sh, sv = self.content.get_min_size()
        return max(shs, sh), max(svs, sv)

    def get_grow(self):
        ghs, gvs = Widget.get_grow(self)
        gh, gv = self.content.get_grow()
        return gh*ghs, gv*gvs

    def set_size(self, size, offset):
        (sh, sv), (oh, ov) = self.legalize(size, offset)

        shc, svc = self.content.get_min_size()
        ghc, gvc = self.content.get_grow()
        if ghc != 0.:
            shc = sh
        if gvc != 0.:
            svc = sv
        ohc = oh+(sh-shc)/2.
        ovc = ov+(sv-svc)/2.

        self.content.set_size((shc, svc), (ohc, ovc))
        Widget.set_size(self, (sh, sv), (oh, ov))

    def set_widget(self, widget=None):

        '''
        Set the child widget, which shall be centered.
        '''

        if widget is None:
            widget = Widget()

        self.content = widget

        widget.set_parent(self)

    def get_widget(self):
        return self.content

    def get_children(self):
        return [self.content]


class FrameLayout(Widget):

    '''
    A layout manager containing a center widget sorrounded by four margin
    widgets.

    ::

            +---------------------------+
            |             top           |
            +---------------------------+
            |      |            |       |
            | left |   center   | right |
            |      |            |       |
            +---------------------------+
            |           bottom          |
            +---------------------------+

    This layout manager does a little bit of extra effort to maintain the
    aspect constraint of the center widget, if this is set. It does so, by
    allowing for a bit more flexibility in the sizing of the margins. Two
    shortcut methods are provided to set the margin sizes in one shot:
    :py:meth:`set_fixed_margins` and :py:meth:`set_min_margins`. The first sets
    the margins to fixed sizes, while the second gives them a minimal size and
    a (neglectably) small desire to grow. Using the latter may be useful when
    setting an aspect constraint on the center widget, because this way the
    maximum size of the center widget may be controlled without creating empty
    spaces between the widgets.
    '''

    def __init__(self, horizontal=None, vertical=None):
        Widget.__init__(self, horizontal, vertical)
        mw = 3.*cm
        self.left = Widget(
            horizontal=GumSpring(grow=0.15, minimal=mw), parent=self)
        self.right = Widget(
            horizontal=GumSpring(grow=0.15, minimal=mw), parent=self)
        self.top = Widget(
            vertical=GumSpring(grow=0.15, minimal=mw/golden_ratio),
            parent=self)
        self.bottom = Widget(
            vertical=GumSpring(grow=0.15, minimal=mw/golden_ratio),
            parent=self)
        self.center = Widget(
            horizontal=GumSpring(grow=0.7), vertical=GumSpring(grow=0.7),
            parent=self)

    def set_fixed_margins(self, left, right, top, bottom):
        '''
        Give margins fixed size constraints.
        '''

        self.left.set_horizontal(left, 0)
        self.right.set_horizontal(right, 0)
        self.top.set_vertical(top, 0)
        self.bottom.set_vertical(bottom, 0)

    def set_min_margins(self, left, right, top, bottom, grow=0.0001):
        '''
        Give margins a minimal size and the possibility to grow.

        The desire to grow is set to a very small number.
        '''
        self.left.set_horizontal(left, grow)
        self.right.set_horizontal(right, grow)
        self.top.set_vertical(top, grow)
        self.bottom.set_vertical(bottom, grow)

    def get_min_size(self):
        shs, svs = Widget.get_min_size(self)

        sl, sr, st, sb, sc = [x.get_min_size() for x in (
            self.left, self.right, self.top, self.bottom, self.center)]
        gl, gr, gt, gb, gc = [x.get_grow() for x in (
            self.left, self.right, self.top, self.bottom, self.center)]

        shsum = sl[0]+sr[0]+sc[0]
        svsum = st[1]+sb[1]+sc[1]

        # prevent widgets from collapsing
        for s, g in ((sl, gl), (sr, gr), (sc, gc)):
            if s[0] == 0.0 and g[0] != 0.0:
                shsum += 0.1*cm

        for s, g in ((st, gt), (sb, gb), (sc, gc)):
            if s[1] == 0.0 and g[1] != 0.0:
                svsum += 0.1*cm

        sh = max(shs, shsum)
        sv = max(svs, svsum)

        return sh, sv

    def get_grow(self):
        ghs, gvs = Widget.get_grow(self)
        gh = (self.left.get_grow()[0] +
              self.right.get_grow()[0] +
              self.center.get_grow()[0]) * ghs
        gv = (self.top.get_grow()[1] +
              self.bottom.get_grow()[1] +
              self.center.get_grow()[1]) * gvs
        return gh, gv

    def set_size(self, size, offset):
        (sh, sv), (oh, ov) = self.legalize(size, offset)

        sl, sr, st, sb, sc = [x.get_min_size() for x in (
            self.left, self.right, self.top, self.bottom, self.center)]
        gl, gr, gt, gb, gc = [x.get_grow() for x in (
            self.left, self.right, self.top, self.bottom, self.center)]

        ah = sh - (sl[0]+sr[0]+sc[0])
        av = sv - (st[1]+sb[1]+sc[1])

        if ah < 0.0:
            raise GmtPyError('Container not wide enough for contents '
                             '(FrameLayout, available: %g cm, needed: %g cm)'
                             % (sh/cm, (sl[0]+sr[0]+sc[0])/cm))
        if av < 0.0:
            raise GmtPyError('Container not high enough for contents '
                             '(FrameLayout, available: %g cm, needed: %g cm)'
                             % (sv/cm, (st[1]+sb[1]+sc[1])/cm))

        slh, srh, sch = distribute((sl[0], sr[0], sc[0]),
                                   (gl[0], gr[0], gc[0]), ah)
        stv, sbv, scv = distribute((st[1], sb[1], sc[1]),
                                   (gt[1], gb[1], gc[1]), av)

        if self.center.aspect is not None:
            ahm = sh - (sl[0]+sr[0] + scv/self.center.aspect)
            avm = sv - (st[1]+sb[1] + sch*self.center.aspect)
            if 0.0 < ahm < ah:
                slh, srh, sch = distribute(
                    (sl[0], sr[0], scv/self.center.aspect),
                    (gl[0], gr[0], 0.0), ahm)

            elif 0.0 < avm < av:
                stv, sbv, scv = distribute((st[1], sb[1],
                                            sch*self.center.aspect),
                                           (gt[1], gb[1], 0.0), avm)

        ah = sh - (slh+srh+sch)
        av = sv - (stv+sbv+scv)

        oh += ah/2.
        ov += av/2.
        sh -= ah
        sv -= av

        self.left.set_size((slh, scv), (oh, ov+sbv))
        self.right.set_size((srh, scv), (oh+slh+sch, ov+sbv))
        self.top.set_size((sh, stv), (oh, ov+sbv+scv))
        self.bottom.set_size((sh, sbv), (oh, ov))
        self.center.set_size((sch, scv), (oh+slh, ov+sbv))
        Widget.set_size(self, (sh, sv), (oh, ov))

    def set_widget(self, which='center', widget=None):

        '''
        Set one of the sub-widgets.

        ``which`` should be one of ``'left'``, ``'right'``, ``'top'``,
        ``'bottom'`` or ``'center'``.
        '''

        if widget is None:
            widget = Widget()

        if which in ('left', 'right', 'top', 'bottom', 'center'):
            self.__dict__[which] = widget
        else:
            raise GmtPyError('No such sub-widget: %s' % which)

        widget.set_parent(self)

    def get_widget(self, which='center'):

        '''
        Get one of the sub-widgets.

        ``which`` should be one of ``'left'``, ``'right'``, ``'top'``,
        ``'bottom'`` or ``'center'``.
        '''

        if which in ('left', 'right', 'top', 'bottom', 'center'):
            return self.__dict__[which]
        else:
            raise GmtPyError('No such sub-widget: %s' % which)

    def get_children(self):
        return [self.left, self.right, self.top, self.bottom, self.center]


class GridLayout(Widget):

    '''
    A layout manager which arranges its sub-widgets in a grid.

    The grid spacing is flexible and based on the sizing policies of the
    contained sub-widgets. If an equidistant grid is needed, the sizing
    policies of the sub-widgets have to be set equally.

    The height of each row and the width of each column is derived from the
    sizing policy of the largest sub-widget in the row or column in question.
    The algorithm is not very sophisticated, so conflicting sizing policies
    might not be resolved optimally.
    '''

    def __init__(self, nx=2, ny=2, horizontal=None, vertical=None):

        '''
        Create new grid layout with ``nx`` columns and ``ny`` rows.
        '''

        Widget.__init__(self, horizontal, vertical)
        self.grid = []
        for iy in range(ny):
            row = []
            for ix in range(nx):
                w = Widget(parent=self)
                row.append(w)

            self.grid.append(row)

    def sub_min_sizes_as_array(self):
        esh = num.array(
            [[w.get_min_size()[0] for w in row] for row in self.grid],
            dtype=float)
        esv = num.array(
            [[w.get_min_size()[1] for w in row] for row in self.grid],
            dtype=float)
        return esh, esv

    def sub_grows_as_array(self):
        egh = num.array(
            [[w.get_grow()[0] for w in row] for row in self.grid],
            dtype=float)
        egv = num.array(
            [[w.get_grow()[1] for w in row] for row in self.grid],
            dtype=float)
        return egh, egv

    def get_min_size(self):
        sh, sv = Widget.get_min_size(self)
        esh, esv = self.sub_min_sizes_as_array()
        if esh.size != 0:
            sh = max(sh, num.sum(esh.max(0)))
        if esv.size != 0:
            sv = max(sv, num.sum(esv.max(1)))
        return sh, sv

    def get_grow(self):
        ghs, gvs = Widget.get_grow(self)
        egh, egv = self.sub_grows_as_array()
        if egh.size != 0:
            gh = num.sum(egh.max(0))*ghs
        else:
            gh = 1.0
        if egv.size != 0:
            gv = num.sum(egv.max(1))*gvs
        else:
            gv = 1.0
        return gh, gv

    def set_size(self, size, offset):
        (sh, sv), (oh, ov) = self.legalize(size, offset)
        esh, esv = self.sub_min_sizes_as_array()
        egh, egv = self.sub_grows_as_array()

        # available additional space
        empty = esh.size == 0

        if not empty:
            ah = sh - num.sum(esh.max(0))
            av = sv - num.sum(esv.max(1))
        else:
            av = sv
            ah = sh

        if ah < 0.0:
            raise GmtPyError('Container not wide enough for contents '
                             '(GridLayout, available: %g cm, needed: %g cm)'
                             % (sh/cm, (num.sum(esh.max(0)))/cm))
        if av < 0.0:
            raise GmtPyError('Container not high enough for contents '
                             '(GridLayout, available: %g cm, needed: %g cm)'
                             % (sv/cm, (num.sum(esv.max(1)))/cm))

        nx, ny = esh.shape

        if not empty:
            # distribute additional space on rows and columns
            # according to grow weights and minimal sizes
            gsh = egh.sum(1)[:, num.newaxis].repeat(ny, axis=1)
            nesh = esh.copy()
            nesh += num.where(gsh > 0.0, ah*egh/gsh, 0.0)

            nsh = num.maximum(nesh.max(0), esh.max(0))

            gsv = egv.sum(0)[num.newaxis, :].repeat(nx, axis=0)
            nesv = esv.copy()
            nesv += num.where(gsv > 0.0, av*egv/gsv, 0.0)
            nsv = num.maximum(nesv.max(1), esv.max(1))

            ah = sh - sum(nsh)
            av = sv - sum(nsv)

            oh += ah/2.
            ov += av/2.
            sh -= ah
            sv -= av

            # resize child widgets
            neov = ov + sum(nsv)
            for row, nesv in zip(self.grid, nsv):
                neov -= nesv
                neoh = oh
                for w, nesh in zip(row, nsh):
                    w.set_size((nesh, nesv), (neoh, neov))
                    neoh += nesh

        Widget.set_size(self, (sh, sv), (oh, ov))

    def set_widget(self, ix, iy, widget=None):

        '''
        Set one of the sub-widgets.

        Sets the sub-widget in column ``ix`` and row ``iy``. The indices are
        counted from zero.
        '''

        if widget is None:
            widget = Widget()

        self.grid[iy][ix] = widget
        widget.set_parent(self)

    def get_widget(self, ix, iy):

        '''
        Get one of the sub-widgets.

        Gets the sub-widget from column ``ix`` and row ``iy``. The indices are
        counted from zero.
        '''

        return self.grid[iy][ix]

    def get_children(self):
        children = []
        for row in self.grid:
            children.extend(row)

        return children


def is_gmt5(version='newest'):
    return get_gmt_installation(version)['version'][0] in ['5', '6']


def is_gmt6(version='newest'):
    return get_gmt_installation(version)['version'][0] in ['6']


def aspect_for_projection(gmtversion, *args, **kwargs):

    gmt = GMT(version=gmtversion, eps_mode=True)

    if gmt.is_gmt5():
        gmt.psbasemap('-B+gblack', finish=True, *args, **kwargs)
        fn = gmt.tempfilename('test.eps')
        gmt.save(fn, crop_eps_mode=True)
        with open(fn, 'rb') as f:
            s = f.read()

        l, b, r, t = get_bbox(s)  # noqa
    else:
        gmt.psbasemap('-G0', finish=True, *args, **kwargs)
        l, b, r, t = gmt.bbox()  # noqa

    return (t-b)/(r-l)  # noqa


def text_box(
        text, font=0, font_size=12., angle=0, gmtversion='newest', **kwargs):

    gmt = GMT(version=gmtversion)
    if gmt.is_gmt5():
        row = [0, 0, text]
        farg = ['-F+f%gp,%s,%s+j%s' % (font_size, font, 'black', 'BL')]
    else:
        row = [0, 0, font_size, 0, font, 'BL', text]
        farg = []

    gmt.pstext(
        in_rows=[row],
        finish=True,
        R=(0, 1, 0, 1),
        J='x10p',
        N=True,
        *farg,
        **kwargs)

    fn = gmt.tempfilename() + '.ps'
    gmt.save(fn)

    (_, stderr) = subprocess.Popen(
        ['gs', '-q', '-dNOPAUSE', '-dBATCH', '-r720', '-sDEVICE=bbox', fn],
        stderr=subprocess.PIPE).communicate()

    dx, dy = None, None
    for line in stderr.splitlines():
        if line.startswith(b'%%HiResBoundingBox:'):
            l, b, r, t = [float(x) for x in line.split()[-4:]]  # noqa
            dx, dy = r-l, t-b  # noqa
            break

    return dx, dy


class TableLiner(object):
    '''
    Utility class to turn tables into lines.
    '''

    def __init__(self, in_columns=None, in_rows=None, encoding='utf-8'):
        self.in_columns = in_columns
        self.in_rows = in_rows
        self.encoding = encoding

    def __iter__(self):
        if self.in_columns is not None:
            for row in zip(*self.in_columns):
                yield (' '.join([str(x) for x in row])+'\n').encode(
                    self.encoding)

        if self.in_rows is not None:
            for row in self.in_rows:
                yield (' '.join([str(x) for x in row])+'\n').encode(
                    self.encoding)


class LineStreamChopper(object):
    '''
    File-like object to buffer data.
    '''

    def __init__(self, liner):
        self.chopsize = None
        self.liner = liner
        self.chop_iterator = None
        self.closed = False

    def _chopiter(self):
        buf = BytesIO()
        for line in self.liner:
            buf.write(line)
            buflen = buf.tell()
            if self.chopsize is not None and buflen >= self.chopsize:
                buf.seek(0)
                while buf.tell() <= buflen-self.chopsize:
                    yield buf.read(self.chopsize)

                newbuf = BytesIO()
                newbuf.write(buf.read())
                buf.close()
                buf = newbuf

        yield buf.getvalue()
        buf.close()

    def read(self, size=None):
        if self.closed:
            raise ValueError('Cannot read from closed LineStreamChopper.')
        if self.chop_iterator is None:
            self.chopsize = size
            self.chop_iterator = self._chopiter()

        self.chopsize = size
        try:
            return next(self.chop_iterator)
        except StopIteration:
            return ''

    def close(self):
        self.chopsize = None
        self.chop_iterator = None
        self.closed = True

    def flush(self):
        pass


font_tab = {
    0: 'Helvetica',
    1: 'Helvetica-Bold',
}

font_tab_rev = dict((v, k) for (k, v) in font_tab.items())


class GMT(object):
    '''
    A thin wrapper to GMT command execution.

    A dict ``config`` may be given to override some of the default GMT
    parameters. The ``version`` argument may be used to select a specific GMT
    version, which should be used with this GMT instance. The selected
    version of GMT has to be installed on the system, must be supported by
    gmtpy and gmtpy must know where to find it.

    Each instance of this class is used for the task of producing one PS or PDF
    output file.

    Output of a series of GMT commands is accumulated in memory and can then be
    saved as PS or PDF file using the :py:meth:`save` method.

    GMT commands are accessed as method calls to instances of this class. See
    the :py:meth:`__getattr__` method for details on how the method's
    arguments are translated into options and arguments for the GMT command.

    Associated with each instance of this class, a temporary directory is
    created, where temporary files may be created, and which is automatically
    deleted, when the object is destroyed. The :py:meth:`tempfilename` method
    may be used to get a random filename in the instance's temporary directory.

    Any .gmtdefaults files are ignored. The GMT class uses a fixed
    set of defaults, which may be altered via an argument to the constructor.
    If possible, GMT is run in 'isolation mode', which was introduced with GMT
    version 4.2.2, by setting `GMT_TMPDIR` to the instance's  temporary
    directory.  With earlier versions of GMT, problems may arise with parallel
    execution of more than one GMT instance.

    Each instance of the GMT class may pick a specific version of GMT which
    shall be used, so that, if multiple versions of GMT are installed on the
    system, different versions of GMT can be used simultaneously such that
    backward compatibility of the scripts can be maintained.

    '''

    def __init__(
            self,
            config=None,
            kontinue=None,
            version='newest',
            config_papersize=None,
            eps_mode=False):

        self.installation = get_gmt_installation(version)
        self.gmt_config = dict(self.installation['defaults'])
        self.eps_mode = eps_mode
        self._shutil = shutil

        if config:
            self.gmt_config.update(config)

        if config_papersize:
            if not isinstance(config_papersize, str):
                config_papersize = 'Custom_%ix%i' % (
                    int(config_papersize[0]), int(config_papersize[1]))

            if self.is_gmt5():
                self.gmt_config['PS_MEDIA'] = config_papersize
            else:
                self.gmt_config['PAPER_MEDIA'] = config_papersize

        self.tempdir = tempfile.mkdtemp('', 'gmtpy-')
        self.gmt_config_filename = pjoin(self.tempdir, 'gmt.conf')
        self.gen_gmt_config_file(self.gmt_config_filename, self.gmt_config)

        if kontinue is not None:
            self.load_unfinished(kontinue)
            self.needstart = False
        else:
            self.output = BytesIO()
            self.needstart = True

        self.finished = False

        self.environ = os.environ.copy()
        self.environ['GMTHOME'] = self.installation.get('home', '')
        # GMT isolation mode: works only properly with GMT version >= 4.2.2
        self.environ['GMT_TMPDIR'] = self.tempdir

        self.layout = None
        self.command_log = []
        self.keep_temp_dir = False

    def is_gmt5(self):
        return self.get_version()[0] in ['5', '6']

    def is_gmt6(self):
        return self.get_version()[0] in ['6']

    def get_version(self):
        return self.installation['version']

    def get_config(self, key):
        return self.gmt_config[key]

    def to_points(self, string):
        if not string:
            return 0

        unit = string[-1]
        if unit in _units:
            return float(string[:-1])/_units[unit]
        else:
            default_unit = measure_unit(self.gmt_config).lower()[0]
            return float(string)/_units[default_unit]

    def label_font_size(self):
        if self.is_gmt5():
            return self.to_points(self.gmt_config['FONT_LABEL'].split(',')[0])
        else:
            return self.to_points(self.gmt_config['LABEL_FONT_SIZE'])

    def label_font(self):
        if self.is_gmt5():
            return font_tab_rev(self.gmt_config['FONT_LABEL'].split(',')[1])
        else:
            return self.gmt_config['LABEL_FONT']

    def gen_gmt_config_file(self, config_filename, config):
        f = open(config_filename, 'wb')
        f.write(
            ('#\n# GMT %s Defaults file\n'
             % self.installation['version']).encode('ascii'))

        for k, v in config.items():
            f.write(('%s = %s\n' % (k, v)).encode('ascii'))
        f.close()

    def __del__(self):
        if not self.keep_temp_dir:
            self._shutil.rmtree(self.tempdir)

    def _gmtcommand(self, command, *addargs, **kwargs):

        '''
        Execute arbitrary GMT command.

        See docstring in __getattr__ for details.
        '''

        in_stream = kwargs.pop('in_stream', None)
        in_filename = kwargs.pop('in_filename', None)
        in_string = kwargs.pop('in_string', None)
        in_columns = kwargs.pop('in_columns', None)
        in_rows = kwargs.pop('in_rows', None)
        out_stream = kwargs.pop('out_stream', None)
        out_filename = kwargs.pop('out_filename', None)
        out_discard = kwargs.pop('out_discard', None)
        finish = kwargs.pop('finish', False)
        suppressdefaults = kwargs.pop('suppress_defaults', False)
        config_override = kwargs.pop('config', None)

        assert not self.finished

        # check for mutual exclusiveness on input and output possibilities
        assert (1 >= len(
            [x for x in [
                in_stream, in_filename, in_string, in_columns, in_rows]
             if x is not None]))
        assert (1 >= len([x for x in [out_stream, out_filename, out_discard]
                         if x is not None]))

        options = []

        gmt_config = self.gmt_config
        if not self.is_gmt5():
            gmt_config_filename = self.gmt_config_filename
            if config_override:
                gmt_config = self.gmt_config.copy()
                gmt_config.update(config_override)
                gmt_config_override_filename = pjoin(
                    self.tempdir, 'gmtdefaults_override')
                self.gen_gmt_config_file(
                    gmt_config_override_filename, gmt_config)
                gmt_config_filename = gmt_config_override_filename

        else:  # gmt5 needs override variables as --VAR=value
            if config_override:
                for k, v in config_override.items():
                    options.append('--%s=%s' % (k, v))

        if out_discard:
            out_filename = '/dev/null'

        out_mustclose = False
        if out_filename is not None:
            out_mustclose = True
            out_stream = open(out_filename, 'wb')

        if in_filename is not None:
            in_stream = open(in_filename, 'rb')

        if in_string is not None:
            in_stream = BytesIO(in_string)

        encoding_gmt = gmt_config.get(
            'PS_CHAR_ENCODING',
            gmt_config.get('CHAR_ENCODING', 'ISOLatin1+'))

        encoding = encoding_gmt_to_python[encoding_gmt.lower()]

        if in_columns is not None or in_rows is not None:
            in_stream = LineStreamChopper(TableLiner(in_columns=in_columns,
                                                     in_rows=in_rows,
                                                     encoding=encoding))

        # convert option arguments to strings
        for k, v in kwargs.items():
            if len(k) > 1:
                raise GmtPyError('Found illegal keyword argument "%s" '
                                 'while preparing options for command "%s"'
                                 % (k, command))

            if type(v) is bool:
                if v:
                    options.append('-%s' % k)
            elif type(v) is tuple or type(v) is list:
                options.append('-%s' % k + '/'.join([str(x) for x in v]))
            else:
                options.append('-%s%s' % (k, str(v)))

        # if not redirecting to an external sink, handle -K -O
        if out_stream is None:
            if not finish:
                options.append('-K')
            else:
                self.finished = True

            if not self.needstart:
                options.append('-O')
            else:
                self.needstart = False

            out_stream = self.output

        # run the command
        if self.is_gmt5():
            args = [pjoin(self.installation['bin'], 'gmt'), command]
        else:
            args = [pjoin(self.installation['bin'], command)]

        if not os.path.isfile(args[0]):
            raise OSError('No such file: %s' % args[0])
        args.extend(options)
        args.extend(addargs)
        if not self.is_gmt5() and not suppressdefaults:
            # does not seem to work with GMT 5 (and should not be necessary
            args.append('+'+gmt_config_filename)

        bs = 2048
        p = subprocess.Popen(args, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, bufsize=bs,
                             env=self.environ)
        while True:
            cr, cw, cx = select([p.stdout], [p.stdin], [])
            if cr:
                out_stream.write(p.stdout.read(bs))
            if cw:
                if in_stream is not None:
                    data = in_stream.read(bs)
                    if len(data) == 0:
                        break
                    p.stdin.write(data)
                else:
                    break
            if not cr and not cw:
                break

        p.stdin.close()

        while True:
            data = p.stdout.read(bs)
            if len(data) == 0:
                break
            out_stream.write(data)

        p.stdout.close()

        retcode = p.wait()

        if in_stream is not None:
            in_stream.close()

        if out_mustclose:
            out_stream.close()

        if retcode != 0:
            self.keep_temp_dir = True
            raise GMTError('Command %s returned an error. '
                           'While executing command:\n%s'
                           % (command, escape_shell_args(args)))

        self.command_log.append(args)

    def __getattr__(self, command):

        '''
        Maps to call self._gmtcommand(command, \\*addargs, \\*\\*kwargs).

        Execute arbitrary GMT command.

        Run a GMT command and by default append its postscript output to the
        output file maintained by the GMT instance on which this method is
        called.

        Except for a few keyword arguments listed below, any ``kwargs`` and
        ``addargs`` are converted into command line options and arguments and
        passed to the GMT command. Numbers in keyword arguments are converted
        into strings. E.g. ``S=10`` is translated into ``'-S10'``. Tuples of
        numbers or strings are converted into strings where the elements of the
        tuples are separated by slashes '/'. E.g. ``R=(10, 10, 20, 20)`` is
        translated into ``'-R10/10/20/20'``. Options with a boolean argument
        are only appended to the GMT command, if their values are True.

        If no output redirection is in effect, the -K and -O options are
        handled by gmtpy and thus should not be specified. Use
        ``out_discard=True`` if you don't want -K or -O beeing added, but are
        not interested in the output.

        The standard input of the GMT process is fed by data selected with one
        of the following ``in_*`` keyword arguments:

        =============== =======================================================
        ``in_stream``   Data is read from an open file like object.
        ``in_filename`` Data is read from the given file.
        ``in_string``   String content is dumped to the process.
        ``in_columns``  A 2D nested iterable whose elements can be accessed as
                        ``in_columns[icolumn][irow]`` is converted into an
                        ascii
                        table, which is fed to the process.
        ``in_rows``     A 2D nested iterable whos elements can be accessed as
                        ``in_rows[irow][icolumn]`` is converted into an ascii
                        table, which is fed to the process.
        =============== =======================================================

        The standard output of the GMT process may be redirected by one of the
        following options:

        ================= =====================================================
        ``out_stream``    Output is fed to an open file like object.
        ``out_filename``  Output is dumped to the given file.
        ``out_discard``   If True, output is dumped to :file:`/dev/null`.
        ================= =====================================================

        Additional keyword arguments:

        ===================== =================================================
        ``config``            Dict with GMT defaults which override the
                              currently active set of defaults exclusively
                              during this call.
        ``finish``            If True, the postscript file, which is maintained
                              by the GMT instance is finished, and no further
                              plotting is allowed.
        ``suppress_defaults`` Suppress appending of the ``'+gmtdefaults'``
                              option to the command.
        ===================== =================================================

        '''

        def f(*args, **kwargs):
            return self._gmtcommand(command, *args, **kwargs)
        return f

    def tempfilename(self, name=None):
        '''
        Get filename for temporary file in the private temp directory.

           If no ``name`` argument is given, a random name is picked. If
           ``name`` is given, returns a path ending in that ``name``.
        '''

        if not name:
            name = ''.join(
                [random.choice('abcdefghijklmnopqrstuvwxyz')
                 for i in range(10)])

        fn = pjoin(self.tempdir, name)
        return fn

    def tempfile(self, name=None):
        '''
        Create and open a file in the private temp directory.
        '''

        fn = self.tempfilename(name)
        f = open(fn, 'wb')
        return f, fn

    def save_unfinished(self, filename):
        out = open(filename, 'wb')
        out.write(self.output.getvalue())
        out.close()

    def load_unfinished(self, filename):
        self.output = BytesIO()
        self.finished = False
        inp = open(filename, 'rb')
        self.output.write(inp.read())
        inp.close()

    def dump(self, ident):
        filename = self.tempfilename('breakpoint-%s' % ident)
        self.save_unfinished(filename)

    def load(self, ident):
        filename = self.tempfilename('breakpoint-%s' % ident)
        self.load_unfinished(filename)

    def save(self, filename=None, bbox=None, resolution=150, oversample=2.,
             width=None, height=None, size=None, crop_eps_mode=False,
             psconvert=False):

        '''
        Finish and save figure as PDF, PS or PPM file.

        If filename ends with ``'.pdf'`` a PDF file is created by piping the
        GMT output through :program:`gmtpy-epstopdf`.

        If filename ends with ``'.png'`` a PNG file is created by running
        :program:`gmtpy-epstopdf`, :program:`pdftocairo` and
        :program:`convert`. ``resolution`` specifies the resolution in DPI for
        raster file formats. Rasterization is done at a higher resolution if
        ``oversample`` is set to a value higher than one. The output image size
        can also be controlled by setting ``width``, ``height`` or ``size``
        instead of ``resolution``. When ``size`` is given, the image is scaled
        so that ``max(width, height) == size``.

        The bounding box is set according to the values given in ``bbox``.
        '''

        if not self.finished:
            self.psxy(R=True, J=True, finish=True)

        if filename:
            tempfn = pjoin(self.tempdir, 'incomplete')
            out = open(tempfn, 'wb')
        else:
            out = sys.stdout

        if bbox and not self.is_gmt5():
            out.write(replace_bbox(bbox, self.output.getvalue()))
        else:
            out.write(self.output.getvalue())

        if filename:
            out.close()

        if filename.endswith('.ps') or (
                not self.is_gmt5() and filename.endswith('.eps')):

            shutil.move(tempfn, filename)
            return

        if self.is_gmt5():
            if crop_eps_mode:
                addarg = ['-A']
            else:
                addarg = []

            subprocess.call(
                [pjoin(self.installation['bin'], 'gmt'), 'psconvert',
                 '-Te', '-F%s' % tempfn, tempfn, ] + addarg)

            if bbox:
                with open(tempfn + '.eps', 'rb') as fin:
                    with open(tempfn + '-fixbb.eps', 'wb') as fout:
                        replace_bbox(bbox, fin, fout)

                shutil.move(tempfn + '-fixbb.eps', tempfn + '.eps')

        else:
            shutil.move(tempfn, tempfn + '.eps')

        if filename.endswith('.eps'):
            shutil.move(tempfn + '.eps', filename)
            return

        elif filename.endswith('.pdf'):
            if psconvert:
                gmt_bin = pjoin(self.installation['bin'], 'gmt')
                subprocess.call([gmt_bin, 'psconvert', tempfn + '.eps', '-Tf',
                                 '-F' + filename])
            else:
                subprocess.call(['gmtpy-epstopdf', '--res=%i' % resolution,
                                 '--outfile=' + filename, tempfn + '.eps'])
        else:
            subprocess.call([
                'gmtpy-epstopdf',
                '--res=%i' % (resolution * oversample),
                '--outfile=' + tempfn + '.pdf', tempfn + '.eps'])

            convert_graph(
                tempfn + '.pdf', filename,
                resolution=resolution, oversample=oversample,
                size=size, width=width, height=height)

    def bbox(self):
        return get_bbox(self.output.getvalue())

    def get_command_log(self):
        '''
        Get the command log.
        '''

        return self.command_log

    def __str__(self):
        s = ''
        for com in self.command_log:
            s += com[0] + '\n  ' + '\n  '.join(com[1:]) + '\n\n'
        return s

    def page_size_points(self):
        '''
        Try to get paper size of output postscript file in points.
        '''

        pm = paper_media(self.gmt_config).lower()
        if pm.endswith('+') or pm.endswith('-'):
            pm = pm[:-1]

        orient = page_orientation(self.gmt_config).lower()

        if pm in all_paper_sizes():

            if orient == 'portrait':
                return get_paper_size(pm)
            else:
                return get_paper_size(pm)[1], get_paper_size(pm)[0]

        m = re.match(r'custom_([0-9.]+)([cimp]?)x([0-9.]+)([cimp]?)', pm)
        if m:
            w, uw, h, uh = m.groups()
            w, h = float(w), float(h)
            if uw:
                w *= _units[uw]
            if uh:
                h *= _units[uh]
            if orient == 'portrait':
                return w, h
            else:
                return h, w

        return None, None

    def default_layout(self, with_palette=False):
        '''
        Get a default layout for the output page.

        One of three different layouts is choosen, depending on the
        `PAPER_MEDIA` setting in the GMT configuration dict.

        If `PAPER_MEDIA` ends with a ``'+'`` (EPS output is selected), a
        :py:class:`FrameLayout` is centered on the page, whose size is
        controlled by its center widget's size plus the margins of the
        :py:class:`FrameLayout`.

        If `PAPER_MEDIA` indicates, that a custom page size is wanted by
        starting with ``'Custom_'``, a :py:class:`FrameLayout` is used to fill
        the complete page. The center widget's size is then controlled by the
        page's size minus the margins of the :py:class:`FrameLayout`.

        In any other case, two FrameLayouts are nested, such that the outer
        layout attaches a 1 cm (printer) margin around the complete page, and
        the inner FrameLayout's center widget takes up as much space as
        possible under the constraint, that an aspect ratio of 1/golden_ratio
        is preserved.

        In any case, a reference to the innermost :py:class:`FrameLayout`
        instance is returned. The top-level layout can be accessed by calling
        :py:meth:`Widget.get_parent` on the returned layout.
        '''

        if self.layout is None:
            w, h = self.page_size_points()

            if w is None or h is None:
                raise GmtPyError("Can't determine page size for layout")

            pm = paper_media(self.gmt_config).lower()

            if with_palette:
                palette_layout = GridLayout(3, 1)
                spacer = palette_layout.get_widget(1, 0)
                palette_widget = palette_layout.get_widget(2, 0)
                spacer.set_horizontal(0.5*cm)
                palette_widget.set_horizontal(0.5*cm)

            if pm.endswith('+') or self.eps_mode:
                outer = CenterLayout()
                outer.set_policy((w, h), (0., 0.))
                inner = FrameLayout()
                outer.set_widget(inner)
                if with_palette:
                    inner.set_widget('center', palette_layout)
                    widget = palette_layout
                else:
                    widget = inner.get_widget('center')
                widget.set_policy((w/golden_ratio, 0.), (0., 0.),
                                  aspect=1./golden_ratio)
                mw = 3.0*cm
                inner.set_fixed_margins(
                    mw, mw, mw/golden_ratio, mw/golden_ratio)
                self.layout = inner

            elif pm.startswith('custom_'):
                layout = FrameLayout()
                layout.set_policy((w, h), (0., 0.))
                mw = 3.0*cm
                layout.set_min_margins(
                    mw, mw, mw/golden_ratio, mw/golden_ratio)
                if with_palette:
                    layout.set_widget('center', palette_layout)
                self.layout = layout
            else:
                outer = FrameLayout()
                outer.set_policy((w, h), (0., 0.))
                outer.set_fixed_margins(1.*cm, 1.*cm, 1.*cm, 1.*cm)

                inner = FrameLayout()
                outer.set_widget('center', inner)
                mw = 3.0*cm
                inner.set_min_margins(mw, mw, mw/golden_ratio, mw/golden_ratio)
                if with_palette:
                    inner.set_widget('center', palette_layout)
                    widget = palette_layout
                else:
                    widget = inner.get_widget('center')

                widget.set_aspect(1./golden_ratio)

                self.layout = inner

        return self.layout

    def draw_layout(self, layout):
        '''
        Use psxy to draw layout; for debugging
        '''

        # corners = layout.get_corners(descend=True)
        rects = num.array(layout.get_sizes(), dtype=float)
        rects_wid = rects[:, 0, 0]
        rects_hei = rects[:, 0, 1]
        rects_center_x = rects[:, 1, 0] + rects_wid*0.5
        rects_center_y = rects[:, 1, 1] + rects_hei*0.5
        nrects = len(rects)
        prects = (rects_center_x, rects_center_y, num.arange(nrects),
                  num.zeros(nrects), rects_hei, rects_wid)

        # points = num.array(corners, dtype=float)

        cptfile = self.tempfilename() + '.cpt'
        self.makecpt(
            C='ocean',
            T='%g/%g/%g' % (-nrects, nrects, 1),
            Z=True,
            out_filename=cptfile, suppress_defaults=True)

        bb = layout.bbox()
        self.psxy(
            in_columns=prects,
            C=cptfile,
            W='1p',
            S='J',
            R=(bb[0], bb[2], bb[1], bb[3]),
            *layout.XYJ())


def simpleconf_to_ax(conf, axname):
    c = {}
    x = axname
    for x in ('', axname):
        for k in ('label', 'unit', 'scaled_unit', 'scaled_unit_factor',
                  'space', 'mode', 'approx_ticks', 'limits', 'masking', 'inc',
                  'snap'):

            if x+k in conf:
                c[k] = conf[x+k]

    return Ax(**c)


class DensityPlotDef(object):
    def __init__(self, data, cpt='ocean', tension=0.7, size=(640, 480),
                 contour=False, method='surface', zscaler=None, **extra):
        self.data = data
        self.cpt = cpt
        self.tension = tension
        self.size = size
        self.contour = contour
        self.method = method
        self.zscaler = zscaler
        self.extra = extra


class TextDef(object):
    def __init__(
            self,
            data,
            size=9,
            justify='MC',
            fontno=0,
            offset=(0, 0),
            color='black'):

        self.data = data
        self.size = size
        self.justify = justify
        self.fontno = fontno
        self.offset = offset
        self.color = color


class Simple(object):
    def __init__(self, gmtconfig=None, gmtversion='newest', **simple_config):
        self.data = []
        self.symbols = []
        self.config = copy.deepcopy(simple_config)
        self.gmtconfig = gmtconfig
        self.density_plot_defs = []
        self.text_defs = []

        self.gmtversion = gmtversion

        self.data_x = []
        self.symbols_x = []

        self.data_y = []
        self.symbols_y = []

        self.default_config = {}
        self.set_defaults(width=15.*cm,
                          height=15.*cm / golden_ratio,
                          margins=(2.*cm, 2.*cm, 2.*cm, 2.*cm),
                          with_palette=False,
                          palette_offset=0.5*cm,
                          palette_width=None,
                          palette_height=None,
                          zlabeloffset=2*cm,
                          draw_layout=False)

        self.setup_defaults()
        self.fixate_widget_aspect = False

    def setup_defaults(self):
        pass

    def set_defaults(self, **kwargs):
        self.default_config.update(kwargs)

    def plot(self, data, symbol=''):
        self.data.append(data)
        self.symbols.append(symbol)

    def density_plot(self, data, **kwargs):
        dpd = DensityPlotDef(data, **kwargs)
        self.density_plot_defs.append(dpd)

    def text(self, data, **kwargs):
        dpd = TextDef(data, **kwargs)
        self.text_defs.append(dpd)

    def plot_x(self, data, symbol=''):
        self.data_x.append(data)
        self.symbols_x.append(symbol)

    def plot_y(self, data, symbol=''):
        self.data_y.append(data)
        self.symbols_y.append(symbol)

    def set(self, **kwargs):
        self.config.update(kwargs)

    def setup_base(self, conf):
        w = conf.pop('width')
        h = conf.pop('height')
        margins = conf.pop('margins')

        gmtconfig = {}
        if self.gmtconfig is not None:
            gmtconfig.update(self.gmtconfig)

        gmt = GMT(
            version=self.gmtversion,
            config=gmtconfig,
            config_papersize='Custom_%ix%i' % (w, h))

        layout = gmt.default_layout(with_palette=conf['with_palette'])
        layout.set_min_margins(*margins)
        if conf['with_palette']:
            widget = layout.get_widget().get_widget(0, 0)
            spacer = layout.get_widget().get_widget(1, 0)
            spacer.set_horizontal(conf['palette_offset'])
            palette_widget = layout.get_widget().get_widget(2, 0)
            if conf['palette_width'] is not None:
                palette_widget.set_horizontal(conf['palette_width'])
            if conf['palette_height'] is not None:
                palette_widget.set_vertical(conf['palette_height'])
                widget.set_vertical(h-margins[2]-margins[3]-0.03*cm)
            return gmt, layout, widget, palette_widget
        else:
            widget = layout.get_widget()
            return gmt, layout, widget, None

    def setup_projection(self, widget, scaler, conf):
        pass

    def setup_scaling(self, conf):
        ndims = 2
        if self.density_plot_defs:
            ndims = 3

        axes = [simpleconf_to_ax(conf, x) for x in 'xyz'[:ndims]]

        data_all = []
        data_all.extend(self.data)
        for dsd in self.density_plot_defs:
            if dsd.zscaler is None:
                data_all.append(dsd.data)
            else:
                data_all.append(dsd.data[:2])
        data_chopped = [ds[:ndims] for ds in data_all]

        scaler = ScaleGuru(data_chopped, axes=axes[:ndims])

        self.setup_scaling_plus(scaler, axes[:ndims])

        return scaler

    def setup_scaling_plus(self, scaler, axes):
        pass

    def setup_scaling_extra(self, scaler, conf):

        scaler_x = scaler.copy()
        scaler_x.data_ranges[1] = (0., 1.)
        scaler_x.axes[1].mode = 'off'

        scaler_y = scaler.copy()
        scaler_y.data_ranges[0] = (0., 1.)
        scaler_y.axes[0].mode = 'off'

        return scaler_x, scaler_y

    def draw_density(self, gmt, widget, scaler):

        R = scaler.R()
        # par = scaler.get_params()
        rxyj = R + widget.XYJ()
        innerticks = False
        for dpd in self.density_plot_defs:

            fn_cpt = gmt.tempfilename() + '.cpt'

            if dpd.zscaler is not None:
                s = dpd.zscaler
            else:
                s = scaler

            gmt.makecpt(C=dpd.cpt, out_filename=fn_cpt, *s.T())

            fn_grid = gmt.tempfilename()

            fn_mean = gmt.tempfilename()

            if dpd.method in ('surface', 'triangulate'):
                gmt.blockmean(in_columns=dpd.data,
                              I='%i+/%i+' % dpd.size,  # noqa
                              out_filename=fn_mean, *R)

                if dpd.method == 'surface':
                    gmt.surface(
                        in_filename=fn_mean,
                        T=dpd.tension,
                        G=fn_grid,
                        I='%i+/%i+' % dpd.size,  # noqa
                        out_discard=True,
                        *R)

                if dpd.method == 'triangulate':
                    gmt.triangulate(
                        in_filename=fn_mean,
                        G=fn_grid,
                        I='%i+/%i+' % dpd.size,  # noqa
                        out_discard=True,
                        V=True,
                        *R)

                if gmt.is_gmt5():
                    gmt.grdimage(fn_grid, C=fn_cpt, E='i', n='l', *rxyj)

                else:
                    gmt.grdimage(fn_grid, C=fn_cpt, E='i', S='l', *rxyj)

                if dpd.contour:
                    gmt.grdcontour(fn_grid,  C=fn_cpt, W='0.5p,black', *rxyj)
                    innerticks = '0.5p,black'

                os.remove(fn_grid)
                os.remove(fn_mean)

            if dpd.method == 'fillcontour':
                extra = dict(C=fn_cpt)
                extra.update(dpd.extra)
                gmt.pscontour(in_columns=dpd.data,
                              I=True, *rxyj, **extra)  # noqa

            if dpd.method == 'contour':
                extra = dict(W='0.5p,black', C=fn_cpt)
                extra.update(dpd.extra)
                gmt.pscontour(in_columns=dpd.data, *rxyj, **extra)

        return fn_cpt, innerticks

    def draw_basemap(self, gmt, widget, scaler):
        gmt.psbasemap(*(widget.JXY() + scaler.RB(ax_projection=True)))

    def draw(self, gmt, widget, scaler):
        rxyj = scaler.R() + widget.JXY()
        for dat, sym in zip(self.data, self.symbols):
            gmt.psxy(in_columns=dat, *(sym.split()+rxyj))

    def post_draw(self, gmt, widget, scaler):
        pass

    def pre_draw(self, gmt, widget, scaler):
        pass

    def draw_extra(self, gmt, widget, scaler_x, scaler_y):

        for dat, sym in zip(self.data_x, self.symbols_x):
            gmt.psxy(in_columns=dat,
                     *(sym.split() + scaler_x.R() + widget.JXY()))

        for dat, sym in zip(self.data_y, self.symbols_y):
            gmt.psxy(in_columns=dat,
                     *(sym.split() + scaler_y.R() + widget.JXY()))

    def draw_text(self, gmt, widget, scaler):

        rxyj = scaler.R() + widget.JXY()
        for td in self.text_defs:
            x, y = td.data[0:2]
            text = td.data[-1]
            size = td.size
            angle = 0
            fontno = td.fontno
            justify = td.justify
            color = td.color
            if gmt.is_gmt5():
                gmt.pstext(
                    in_rows=[(x, y, text)],
                    F='+f%gp,%s,%s+a%g+j%s' % (
                        size, fontno, color, angle, justify),
                    D='%gp/%gp' % td.offset,  *rxyj)
            else:
                gmt.pstext(
                    in_rows=[(x, y, size, angle, fontno, justify, text)],
                    D='%gp/%gp' % td.offset,  *rxyj)

    def save(self, filename, resolution=150):

        conf = dict(self.default_config)
        conf.update(self.config)

        gmt, layout, widget, palette_widget = self.setup_base(conf)
        scaler = self.setup_scaling(conf)
        scaler_x, scaler_y = self.setup_scaling_extra(scaler, conf)

        self.setup_projection(widget, scaler, conf)
        if self.fixate_widget_aspect:
            aspect = aspect_for_projection(
                gmt.installation['version'], *(widget.J() + scaler.R()))

            widget.set_aspect(aspect)

        if conf['draw_layout']:
            gmt.draw_layout(layout)
        cptfile = None
        if self.density_plot_defs:
            cptfile, innerticks = self.draw_density(gmt, widget, scaler)
        self.pre_draw(gmt, widget, scaler)
        self.draw(gmt, widget, scaler)
        self.post_draw(gmt, widget, scaler)
        self.draw_extra(gmt, widget, scaler_x, scaler_y)
        self.draw_text(gmt, widget, scaler)
        self.draw_basemap(gmt, widget, scaler)

        if palette_widget and cptfile:
            nice_palette(gmt, palette_widget, scaler, cptfile,
                         innerticks=innerticks,
                         zlabeloffset=conf['zlabeloffset'])

        gmt.save(filename, resolution=resolution)


class LinLinPlot(Simple):
    pass


class LogLinPlot(Simple):

    def setup_defaults(self):
        self.set_defaults(xmode='min-max')

    def setup_projection(self, widget, scaler, conf):
        widget['J'] = '-JX%(width)gpl/%(height)gp'
        scaler['B'] = '-B2:%(xlabel)s:/%(yinc)g:%(ylabel)s:WSen'


class LinLogPlot(Simple):

    def setup_defaults(self):
        self.set_defaults(ymode='min-max')

    def setup_projection(self, widget, scaler, conf):
        widget['J'] = '-JX%(width)gp/%(height)gpl'
        scaler['B'] = '-B%(xinc)g:%(xlabel)s:/2:%(ylabel)s:WSen'


class LogLogPlot(Simple):

    def setup_defaults(self):
        self.set_defaults(mode='min-max')

    def setup_projection(self, widget, scaler, conf):
        widget['J'] = '-JX%(width)gpl/%(height)gpl'
        scaler['B'] = '-B2:%(xlabel)s:/2:%(ylabel)s:WSen'


class AziDistPlot(Simple):

    def __init__(self, *args, **kwargs):
        Simple.__init__(self, *args, **kwargs)
        self.fixate_widget_aspect = True

    def setup_defaults(self):
        self.set_defaults(
            height=15.*cm,
            width=15.*cm,
            xmode='off',
            xlimits=(0., 360.),
            xinc=45.)

    def setup_projection(self, widget, scaler, conf):
        widget['J'] = '-JPa%(width)gp'

    def setup_scaling_plus(self, scaler, axes):
        scaler['B'] = '-B%(xinc)g:%(xlabel)s:/%(yinc)g:%(ylabel)s:N'


class MPlot(Simple):

    def __init__(self, *args, **kwargs):
        Simple.__init__(self, *args, **kwargs)
        self.fixate_widget_aspect = True

    def setup_defaults(self):
        self.set_defaults(xmode='min-max', ymode='min-max')

    def setup_projection(self, widget, scaler, conf):
        par = scaler.get_params()
        lon0 = (par['xmin'] + par['xmax'])/2.
        lat0 = (par['ymin'] + par['ymax'])/2.
        sll = '%g/%g' % (lon0, lat0)
        widget['J'] = '-JM' + sll + '/%(width)gp'
        scaler['B'] = \
            '-B%(xinc)gg%(xinc)g:%(xlabel)s:/%(yinc)gg%(yinc)g:%(ylabel)s:WSen'


def nice_palette(gmt, widget, scaleguru, cptfile, zlabeloffset=0.8*inch,
                 innerticks=True):

    par = scaleguru.get_params()
    par_ax = scaleguru.get_params(ax_projection=True)
    nz_palette = int(widget.height()/inch * 300)
    px = num.zeros(nz_palette*2)
    px[1::2] += 1
    pz = num.linspace(par['zmin'], par['zmax'], nz_palette).repeat(2)
    pdz = pz[2]-pz[0]
    palgrdfile = gmt.tempfilename()
    pal_r = (0, 1, par['zmin'], par['zmax'])
    pal_ax_r = (0, 1, par_ax['zmin'], par_ax['zmax'])
    gmt.xyz2grd(
        G=palgrdfile, R=pal_r,
        I=(1, pdz), in_columns=(px, pz, pz),  # noqa
        out_discard=True)

    gmt.grdimage(palgrdfile, R=pal_r, C=cptfile, *widget.JXY())
    if isinstance(innerticks, str):
        tickpen = innerticks
        gmt.grdcontour(palgrdfile, W=tickpen, R=pal_r, C=cptfile,
                       *widget.JXY())

    negpalwid = '%gp' % -widget.width()
    if not isinstance(innerticks, str) and innerticks:
        ticklen = negpalwid
    else:
        ticklen = '0p'

    TICK_LENGTH_PARAM = 'MAP_TICK_LENGTH' if gmt.is_gmt5() else 'TICK_LENGTH'
    gmt.psbasemap(
        R=pal_ax_r, B='4::/%(zinc)g::nsw' % par_ax,
        config={TICK_LENGTH_PARAM: ticklen},
        *widget.JXY())

    if innerticks:
        gmt.psbasemap(
            R=pal_ax_r, B='4::/%(zinc)g::E' % par_ax,
            config={TICK_LENGTH_PARAM: '0p'},
            *widget.JXY())
    else:
        gmt.psbasemap(R=pal_ax_r, B='4::/%(zinc)g::E' % par_ax, *widget.JXY())

    if par_ax['zlabel']:
        label_font = gmt.label_font()
        label_font_size = gmt.label_font_size()
        label_offset = zlabeloffset
        gmt.pstext(
            R=(0, 1, 0, 2), D='%gp/0p' % label_offset,
            N=True,
            in_rows=[(1, 1, label_font_size, -90, label_font, 'CB',
                     par_ax['zlabel'])],
            *widget.JXY())
