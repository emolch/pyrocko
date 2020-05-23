# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import os
import re

import numpy as num

from pyrocko.guts import Object, Float, Tuple, List
from pyrocko import util


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

    @property
    def vmin(self):
        if self.levels:
            return self.levels[0].vmin
        else:
            return None

    @property
    def vmax(self):
        if self.levels:
            return self.levels[-1].vmax
        else:
            return None

    def scale(self, vmin, vmax):
        vmin_old, vmax_old = self.levels[0].vmin, self.levels[-1].vmax
        for level in self.levels:
            level.vmin = (level.vmin - vmin_old) / (vmax_old - vmin_old) * \
                (vmax - vmin) + vmin
            level.vmax = (level.vmax - vmin_old) / (vmax_old - vmin_old) * \
                (vmax - vmin) + vmin

    def get_lut(self):
        vs = []
        colors = []
        if self.color_below and self.levels:
            vs.append(self.levels[0].vmin)
            colors.append(self.color_below)

        for level in self.levels:
            vs.append(level.vmin)
            vs.append(level.vmax)
            colors.append(level.color_min)
            colors.append(level.color_max)

        if self.color_above and self.levels:
            vs.append(self.levels[-1].vmax)
            colors.append(self.color_above)

        vs_lut = num.array(vs)
        colors_lut = num.array(colors)
        return vs_lut, colors_lut

    def __call__(self, values):
        vs_lut, colors_lut = self.get_lut()

        colors = num.zeros((values.size, 3))
        colors[:, 0] = num.interp(values, vs_lut, colors_lut[:, 0])
        colors[:, 1] = num.interp(values, vs_lut, colors_lut[:, 1])
        colors[:, 2] = num.interp(values, vs_lut, colors_lut[:, 2])

        if self.color_nan:
            cnan = num.zeros((1, 3))
            cnan[0, :] = self.color_nan
            colors[num.isnan(values), :] = cnan

        return colors

    @classmethod
    def from_numpy(cls, colors):
        nbins = colors.shape[0]
        vs = num.linspace(0., 1., nbins)
        cpt_data = num.hstack((num.atleast_2d(vs).T, colors))
        return cls(
            levels=[
                CPTLevel(
                    vmin=a[0],
                    vmax=b[0],
                    color_min=[255*x for x in a[1:]],
                    color_max=[255*x for x in b[1:]])
                for (a, b) in zip(cpt_data[:-1], cpt_data[1:])])


def get_cpt_path(name):
    if os.path.exists(name):
        return name

    if not re.match(r'[A-Za-z0-9_]+', name):
        raise Exception('invalid cpt name')

    fn = util.data_file(os.path.join('colortables', '%s.cpt' % name))
    if not os.path.exists(fn):
        raise Exception('cpt file does not exist: %s' % fn)

    return fn


def get_cpt(name):
    return read_cpt(get_cpt_path(name))


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
