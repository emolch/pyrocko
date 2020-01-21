# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import re

from pyrocko.guts import Object, Dict, SObject, Float, String, TBase, \
    ValidationError, load_string


guts_prefix = 'pf'


class ColorError(ValueError):
    pass


class InvalidColorString(ColorError):
    def __init__(self, s):
        ColorError.__init__(self, 'Invalid color string: %s' % s)


g_pattern_hex = re.compile(
    r'^#([0-9a-fA-F]{1,2}){3,4}$')


g_pattern_rgb = re.compile(
    r'^(RGBA?|rgba?)\(([^,]+),([^,]+),([^,]+)(,([^)]+))?\)$')


g_tango_colors = {
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


g_standard_colors = {
    'white':       (255, 255, 255),
    'black':       (0,     0,   0),
    'red':         (255,   0,   0),
    'green':       (0,   255,   0),
    'blue':        (0,     0, 255)}


g_named_colors = {}

g_named_colors.update(g_tango_colors)
g_named_colors.update(g_standard_colors)


def parse_color(s):
    orig_s = s

    rgba = None

    if s in g_named_colors:
        rgba = tuple(to_float_1(x) for x in g_named_colors[s]) + (1.0,)

    else:
        m = g_pattern_hex.match(s)
        if m:
            s = s[1:]
            if len(s) == 3:
                s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2]

            if len(s) == 4:
                s = s[0] + s[0] + s[1] + s[1] + s[2] + s[2] + s[3] + s[3]

            if len(s) == 6:
                s = s + 'FF'

            if len(s) == 8:
                try:
                    rgba = tuple(
                        int(s[i*2:i*2+2], base=16) / 255.
                        for i in range(4))
                except ValueError:
                    raise InvalidColorString(orig_s)

            else:
                raise InvalidColorString(orig_s)

        m = g_pattern_rgb.match(s)
        if m:
            rgb_mode = m.group(1)
            if rgb_mode.startswith('rgb'):
                typ = float
            else:
                def typ(x):
                    return int(x) / 255.

            try:
                rgba = (
                    typ(m.group(2)),
                    typ(m.group(3)),
                    typ(m.group(4)),
                    typ(m.group(6)) if m.group(6) else 1.0)

            except ValueError:
                raise InvalidColorString(orig_s)

    if rgba is None:
        raise InvalidColorString(orig_s)

    if any(x < 0.0 or x > 1.0 for x in rgba):
        raise InvalidColorString(orig_s)

    return rgba


def to_int_255(f):
    if not (0.0 <= f <= 1.0):
        raise ColorError(
            'Floating point color component must be in the range [0.0, 1.0]')

    return int(round(f * 255.))


def to_float_1(i):
    if not (0 <= i <= 255):
        raise ColorError(
            'Integer color component must be in the range [0, 255]')

    return i / 255.


def simplify_hex(s):
    if s[1] == s[2] and s[3] == s[4] and s[5] == s[6] \
            and (len(s) == 9 and s[7] == s[8]):

        s = s[0] + s[1] + s[3] + s[5] + (s[7] if len(s) == 9 else '')

    if len(s) == 9 and s[-2:].lower() == 'ff':
        s = s[:7]

    elif len(s) == 5 and s[-1:].lower() == 'f':
        s = s[:4]

    return s


class Component(Float):
    class __T(TBase):
        def validate_extra(self, x):
            if not (0.0 <= x <= 1.0):
                raise ValidationError(
                    'Color component must be in the range [0.0, 1.0]')


class Color(SObject):

    name__ = String.T(optional=True)
    r__ = Component.T(default=0.0)
    g__ = Component.T(default=0.0)
    b__ = Component.T(default=0.0)
    a__ = Component.T(default=1.0)

    def __init__(self, *args, **kwargs):
        if len(args) == 1:
            SObject.__init__(self, init_props=False)
            self.name = args[0]

        elif len(args) in (3, 4):
            SObject.__init__(self, init_props=False)

            if all(isinstance(x, int) for x in args):
                if len(args) == 3:
                    args = args + (255,)

                self.RGBA = args

            elif all(isinstance(x, float) for x in args):
                if len(args) == 3:
                    args = args + (1.0,)

                self.rgba = args

        else:
            SObject.__init__(self, **kwargs)

    @property
    def name(self):
        return self.name__ or ''

    @name.setter
    def name(self, name):
        self.r__, self.g__, self.b__, self.a__ = parse_color(name)
        self.name__ = name

    @property
    def r(self):
        return self.r__

    @r.setter
    def r(self, r):
        self.name__ = None
        self.r__ = r

    @property
    def g(self):
        return self.g__

    @g.setter
    def g(self, g):
        self.name__ = None
        self.g__ = g

    @property
    def b(self):
        return self.b__

    @b.setter
    def b(self, b):
        self.name__ = None
        self.b__ = b

    @property
    def a(self):
        return self.a__

    @a.setter
    def a(self, a):
        self.name__ = None
        self.a__ = a

    @property
    def rgb(self):
        return self.r__, self.g__, self.b__

    @rgb.setter
    def rgb(self, rgb):
        self.r__, self.g__, self.b__ = rgb
        self.name__ = None

    @property
    def rgba(self):
        return self.r__, self.g__, self.b__, self.a__

    @rgba.setter
    def rgba(self, rgba):
        self.r__, self.g__, self.b__, self.a__ = rgba
        self.name__ = None

    @property
    def RGB(self):
        return tuple(to_int_255(x) for x in self.rgb)

    @RGB.setter
    def RGB(self, RGB):
        self.r__, self.g__, self.b__ = (to_float_1(x) for x in RGB)
        self.name__ = None

    @property
    def RGBA(self):
        return tuple(to_int_255(x) for x in self.rgba)

    @RGBA.setter
    def RGBA(self, RGBA):
        self.r__, self.g__, self.b__, self.a__ = (to_float_1(x) for x in RGBA)
        self.name__ = None

    @property
    def str_hex(self):
        return simplify_hex('#%02x%02x%02x%02x' % self.RGBA)

    def use_hex_name(self):
        self.name__ = simplify_hex('#%02x%02x%02x%02x' % self.RGBA)

    @property
    def str_rgb(self):
        return 'rgb(%5.3f, %5.3f, %5.3f)' % self.rgb

    @property
    def str_RGB(self):
        return 'RGB(%i, %i, %i)' % self.RGB

    @property
    def str_rgba(self):
        return 'rgba(%5.3f, %5.3f, %5.3f, %5.3f)' % self.rgba

    @property
    def str_RGBA(self):
        return 'RGBA(%i, %i, %i, %i)' % self.RGBA

    def describe(self):
        return '''
            name: %s
            hex: %s
            RGBA: %s
            rgba: %s
            str: %s
''' % (
                self.name,
                self.str_hex,
                self.str_RGBA,
                self.str_rgba,
                str(self))

    def __str__(self):
        return self.name__ if self.name__ is not None else self.str_rgba


class ColorGroup(Object):
    name = String.T(optional=True)
    mapping = Dict.T(String.T(), Color.T())


g_groups = []

for name, color_dict in [
        ('tango', g_tango_colors),
        ('standard', g_standard_colors)]:

    g_groups.append(ColorGroup(
        name=name,
        mapping=dict((k, Color(*v)) for (k, v) in color_dict.items())))

    for color in g_groups[-1].mapping.values():
        color.use_hex_name()

if __name__ == '__main__':

    import sys

    for g in g_groups:
        print(load_string(str(g)))

    for s in sys.argv[1:]:

        try:
            color = Color(s)
        except ColorError as e:
            sys.exit(str(e))

        print(color.describe())
