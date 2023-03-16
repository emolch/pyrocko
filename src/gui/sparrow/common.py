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
from pyrocko.gui.util import tmin_effective, tmax_effective, get_app  # noqa


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
    if isinstance(widget, qw.QWidget):
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


class MyDockWidgetTitleBarButton(qw.QPushButton):

    def __init__(self, *args, **kwargs):
        qw.QPushButton.__init__(self, *args, **kwargs)
        self.setFlat(True)
        self.setSizePolicy(
            qw.QSizePolicy.Fixed, qw.QSizePolicy.Fixed)

    def sizeHint(self):
        s = qw.QPushButton.sizeHint(self)
        return qc.QSize(s.height(), s.height())


class MyDockWidgetTitleBarButtonToggle(MyDockWidgetTitleBarButton):

    toggled = qc.pyqtSignal(bool)

    def __init__(self, text_checked, text_unchecked, *args, **kwargs):
        MyDockWidgetTitleBarButton.__init__(
            self, text_checked, *args, **kwargs)

        self._checked = True
        self._text_checked = text_checked
        self._text_unchecked = text_unchecked
        self.update_text()
        self.clicked.connect(self.toggle)

    def set_checked(self, checked):
        self._checked = checked
        self.update_text()

    def toggle(self):
        self._checked = not self._checked
        self.update_text()
        self.toggled.emit(self._checked)

    def update_text(self):
        if self._checked:
            self.setText(self._text_checked)
        else:
            self.setText(self._text_unchecked)


class MyDockWidgetTitleBarLabel(qw.QLabel):

    def event(self, ev):
        ev.ignore()
        return qw.QLabel.event(self, ev)


class MyDockWidgetTitleBar(qw.QFrame):

    def __init__(self, title, title_controls=[]):
        qw.QFrame.__init__(self)

        lab = MyDockWidgetTitleBarLabel('<strong>%s</strong>' % title)
        lab.setSizePolicy(
            qw.QSizePolicy.Expanding, qw.QSizePolicy.Minimum)

        button_hide = MyDockWidgetTitleBarButton('-')
        button_hide.setStatusTip('Hide Panel')

        layout = qw.QGridLayout()
        layout.setSpacing(0)
        layout.addWidget(lab, 0, 0)
        layout.addWidget(button_hide, 0, 1)
        for i, button in enumerate(title_controls):
            layout.addWidget(button, 0, 2 + i)

        self.setLayout(layout)
        self.setBackgroundRole(qg.QPalette.Mid)
        self.setAutoFillBackground(True)
        self.button_hide = button_hide

    def event(self, ev):
        ev.ignore()
        return qw.QFrame.event(self, ev)


class MyDockWidget(qw.QDockWidget):

    def __init__(self, name, parent, title_controls=[], **kwargs):
        qw.QDockWidget.__init__(self, name, parent, **kwargs)

        self.setFeatures(
            qw.QDockWidget.DockWidgetClosable
            | qw.QDockWidget.DockWidgetMovable
            | qw.QDockWidget.DockWidgetFloatable
            | qw.QDockWidget.DockWidgetClosable)

        self._visible = False
        self._blocked = False

        tb = MyDockWidgetTitleBar(name, title_controls)
        tb.button_hide.clicked.connect(self.hide)
        self.setTitleBarWidget(tb)
        self.titlebar = tb

    def setVisible(self, visible):
        self._visible = visible
        if not self._blocked:
            qw.QDockWidget.setVisible(self, self._visible)

    def show(self):
        self.setVisible(True)

    def hide(self):
        self.setVisible(False)

    def setBlocked(self, blocked):
        self._blocked = blocked
        if blocked:
            qw.QDockWidget.setVisible(self, False)
        else:
            qw.QDockWidget.setVisible(self, self._visible)

    def block(self):
        self.setBlocked(True)

    def unblock(self):
        self.setBlocked(False)
