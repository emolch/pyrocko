# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import copy

import math
import numpy as num
from scipy.interpolate import interp1d

from pyrocko import automap, plot, util
from pyrocko.geometry import d2r
from pyrocko.gui.qt_compat import qg, qw, qc


def get_err_palette():
    err_palette = qg.QPalette()
    err_palette.setColor(qg.QPalette.Text, qg.QColor(255, 200, 200))
    return err_palette


def get_palette():
    return qw.QApplication.palette()


def errorize(widget):
    widget.setStyleSheet('''
        QLineEdit {
            background: rgb(200, 150, 150);
        }''')


def de_errorize(widget):
    widget.setStyleSheet('')


def strings_to_combobox(list_of_str):
    cb = qw.QComboBox()
    for i, s in enumerate(list_of_str):
        cb.insertItem(i, s)

    return cb


def string_choices_to_combobox(cls):
    return strings_to_combobox(cls.choices)


def time_or_none_to_str(t):
    if t is None:
        return ''
    else:
        return util.time_to_str(t)


def tmin_effective(tmin, tmax, tduration, tposition):
    if None in (tmin, tmax, tduration, tposition):
        return tmin
    else:
        return tmin + (tmax - tmin) * tposition


def tmax_effective(tmin, tmax, tduration, tposition):
    if None in (tmin, tmax, tduration, tposition):
        return tmax
    else:
        return tmin + (tmax - tmin) * tposition + tduration


def cover_region(lat, lon, delta, step=None, avoid_poles=False):
    if step is None:
        step = plot.nice_value(delta / 10.)

    assert step <= 20.

    def fl_major(x):
        return math.floor(x / step) * step

    def ce_major(x):
        return math.ceil(x / step) * step

    if avoid_poles:
        lat_min_lim = -90. + step
        lat_max_lim = 90. - step
    else:
        lat_min_lim = -90.
        lat_max_lim = 90.

    lat_min = max(lat_min_lim, fl_major(lat - delta))
    lat_max = min(lat_max_lim, ce_major(lat + delta))

    lon_closed = False
    if abs(lat)+delta < 89.:
        factor = 1.0 / math.cos((abs(lat)+delta) * d2r)
        lon_min = fl_major(lon - delta * factor)
        lon_max = ce_major(lon + delta * factor)
        if lon_max >= lon_min + 360. - step*1e-5:
            lon_min, lon_max = -180., 180. - step
            lon_closed = True
    else:
        lon_min, lon_max = -180., 180. - step
        lon_closed = True

    return lat_min, lat_max, lon_min, lon_max, lon_closed


qfiledialog_options = qw.QFileDialog.DontUseNativeDialog | \
    qw.QFileDialog.DontUseSheet


def _paint_cpt_rect(painter, cpt, rect):
    rect.adjust(+5, +2, -5, -2)

    rect_cpt = copy.deepcopy(rect)
    rect_cpt.setWidth(int(rect.width() * 0.9) - 2)

    rect_c_nan = copy.deepcopy(rect)
    rect_c_nan.setLeft(rect.left() + rect_cpt.width() + 4)
    rect_c_nan.setWidth(int(rect.width() * 0.1) - 2)

    levels = num.zeros(len(cpt.levels) * 2 + 4)
    colors = num.ones((levels.shape[0], 4)) * 255

    for il, level in enumerate(cpt.levels):
        levels[il*2+2] = level.vmin + (
            level.vmax - level.vmin) / rect_cpt.width()  # ow interp errors
        levels[il*2+3] = level.vmax

        colors[il*2+2, :3] = level.color_min
        colors[il*2+3, :3] = level.color_max

    level_range = levels[-3] - levels[2]
    levels[0], levels[1] = levels[2] - level_range * 0.05, levels[2]
    levels[-2], levels[-1] = levels[-3], levels[-3] + level_range * 0.05

    if cpt.color_below:
        colors[:2, :3] = cpt.color_below
    else:
        colors[:2] = (0, 0, 0, 0)

    if cpt.color_above:
        colors[-2:, :3] = cpt.color_above
    else:
        colors[-2:] = (0, 0, 0, 0)

    levels_interp = num.linspace(levels[0], levels[-1], rect_cpt.width())
    interpolator = interp1d(levels, colors.T)

    colors_interp = interpolator(
        levels_interp).T.astype(num.uint8).tobytes()

    colors_interp = num.tile(
        colors_interp, rect_cpt.height())

    img = qg.QImage(
        colors_interp, rect_cpt.width(), rect_cpt.height(),
        qg.QImage.Format_RGBA8888)

    painter.drawImage(rect_cpt, img)

    c = cpt.color_nan
    qcolor_nan = qg.QColor(*c if c is not None else (0, 0, 0))
    qcolor_nan.setAlpha(255 if c is not None else 0)

    painter.fillRect(rect_c_nan, qcolor_nan)


class CPTStyleDelegate(qw.QItemDelegate):

    def __init__(self, parent=None):
        qw.QItemDelegate.__init__(self, parent)

    def paint(self, painter, option, index):
        data = index.model().data(index, qc.Qt.UserRole)

        if isinstance(data, automap.CPT):
            painter.save()
            rect = option.rect
            _paint_cpt_rect(painter, data, rect)
            painter.restore()

        else:
            qw.QItemDelegate.paint(self, painter, option, index)


class CPTComboBox(qw.QComboBox):
    def __init__(self):
        super().__init__()

        self.setItemDelegate(CPTStyleDelegate(parent=self))
        self.setInsertPolicy(qw.QComboBox.InsertAtBottom)

    def paintEvent(self, e):
        data = self.itemData(self.currentIndex(), qc.Qt.UserRole)

        if isinstance(data, automap.CPT):
            spainter = qw.QStylePainter(self)
            spainter.setPen(self.palette().color(qg.QPalette.Text))

            opt = qw.QStyleOptionComboBox()
            self.initStyleOption(opt)
            spainter.drawComplexControl(qw.QStyle.CC_ComboBox, opt)

            painter = qg.QPainter(self)
            painter.save()

            rect = spainter.style().subElementRect(
                qw.QStyle.SE_ComboBoxFocusRect, opt, self)

            _paint_cpt_rect(painter, data, rect)

            painter.restore()

        else:
            qw.QComboBox.paintEvent(self, e)
