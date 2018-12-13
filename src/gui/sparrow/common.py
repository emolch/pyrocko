# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import math

from pyrocko.gui.qt_compat import qg, qw
from pyrocko import plot
from pyrocko.geometry import d2r


def get_err_palette():
    err_palette = qg.QPalette()
    err_palette.setColor(qg.QPalette.Text, qg.QColor(255, 200, 200))
    return err_palette


def get_palette():
    return qw.QApplication.palette()


def errorize(widget):
    widget.setStyleSheet('''
        QLineEdit {
            background: rgb(100, 20, 20);
        }''')


def de_errorize(widget):
    widget.setStyleSheet('')


def string_choices_to_combobox(cls):
    cb = qw.QComboBox()
    for i, s in enumerate(cls.choices):
        cb.insertItem(i, s)

    return cb


def cover_region(lat, lon, delta, step=None):
    if step is None:
        step = plot.nice_value(delta / 10.)

    assert step <= 10.

    def fl_major(x):
        return math.floor(x / step) * step

    def ce_major(x):
        return math.ceil(x / step) * step

    lat_min = max(-90. + step, fl_major(lat - delta))
    lat_max = min(90. - step, ce_major(lat + delta))

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
