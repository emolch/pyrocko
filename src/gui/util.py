# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import sys
import math
import time
import numpy as num
import logging
import enum
import calendar
import signal

from matplotlib.cm import get_cmap
from matplotlib.colors import Normalize

from .qt_compat import qc, qg, qw

from .snuffler.marker import Marker, PhaseMarker, EventMarker  # noqa
from .snuffler.marker import MarkerParseError, MarkerOneNSLCRequired  # noqa
from .snuffler.marker import load_markers, save_markers  # noqa
from pyrocko import plot, util


logger = logging.getLogger('pyrocko.gui.util')


class _Getch:
    '''
    Gets a single character from standard input.

    Does not echo to the screen.

    https://stackoverflow.com/questions/510357/how-to-read-a-single-character-from-the-user
    '''
    def __init__(self):
        try:
            self.impl = _GetchWindows()
        except ImportError:
            self.impl = _GetchUnix()

    def __call__(self): return self.impl()


class _GetchUnix:
    def __init__(self):
        import tty, sys  # noqa

    def __call__(self):
        import sys
        import tty
        import termios

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

        return ch


class _GetchWindows:
    def __init__(self):
        import msvcrt  # noqa

    def __call__(self):
        import msvcrt
        return msvcrt.getch()


getch = _Getch()


class PyrockoQApplication(qw.QApplication):

    def __init__(self):
        qw.QApplication.__init__(self, [])
        self._main_window = None

    def install_sigint_handler(self):
        self._old_signal_handler = signal.signal(
            signal.SIGINT,
            self.request_close_all_windows)

    def uninstall_sigint_handler(self):
        signal.signal(signal.SIGINT, self._old_signal_handler)

    def set_main_window(self, win):
        self._main_window = win
        name = win.windowTitle() if win is not None else ''
        self.setApplicationName(name)
        self.setApplicationDisplayName(name)
        self.setDesktopFileName(name)

    def unset_main_window(self):
        self.set_main_window(None)

    def get_main_window(self):
        return self._main_window

    def get_main_windows(self):
        return [self.get_main_window()]

    def status(self, message, duration=None):
        win = self.get_main_window()
        if not win:
            print(' - %s' % message, file=sys.stderr)
        else:
            win.statusBar().showMessage(
                message, int((duration or 0) * 1000))

    def event(self, e):
        if isinstance(e, qg.QFileOpenEvent):
            path = str(e.file())
            if path != sys.argv[0]:
                wins = self.get_main_windows()
                if wins:
                    wins[0].get_view().load_soon([path])

            return True
        else:
            return qw.QApplication.event(self, e)

    def request_close_all_windows(self, *args):

        def confirm():
            try:
                print(
                    '\nQuit %s? [y/n]' % self.applicationName(),
                    file=sys.stderr)

                confirmed = getch() == 'y'
                if not confirmed:
                    print(
                        'Continuing.',
                        file=sys.stderr)
                else:
                    print(
                        'Quitting %s.' % self.applicationName(),
                        file=sys.stderr)

                return confirmed

            except Exception:
                return False

        if confirm():
            for win in self.get_main_windows():
                win.instant_close = True

            self.closeAllWindows()


app = None


def get_app():
    from .qt_compat import qg
    try:
        global app
        if app is None:
            qg.QSurfaceFormat.setDefaultFormat(qg.QSurfaceFormat())
            app = PyrockoQApplication()
        return app
    except NameError:  # can happen during shutdown
        return None


def rint(x):
    return int(round(x))


def make_QPolygonF(xdata, ydata):
    assert len(xdata) == len(ydata)
    qpoints = qg.QPolygonF(len(ydata))
    vptr = qpoints.data()
    vptr.setsize(len(ydata)*8*2)
    aa = num.ndarray(
        shape=(len(ydata), 2),
        dtype=num.float64,
        buffer=memoryview(vptr))
    aa.setflags(write=True)
    aa[:, 0] = xdata
    aa[:, 1] = ydata
    return qpoints


def get_colormap_qimage(cmap_name, vmin=None, vmax=None):
    NCOLORS = 512
    norm = Normalize()
    norm.vmin = vmin
    norm.vmax = vmax

    return qg.QImage(
        get_cmap(cmap_name)(
            norm(num.linspace(0., 1., NCOLORS)),
            alpha=None, bytes=True),
        NCOLORS, 1, qg.QImage.Format_RGBX8888)


class Label(object):
    def __init__(
            self, p, x, y, label_str,
            label_bg=None,
            anchor='BL',
            outline=False,
            font=None,
            color=None):

        text = qg.QTextDocument()
        if font:
            text.setDefaultFont(font)
        text.setDefaultStyleSheet('span { color: %s; }' % color.name())
        text.setHtml('<span>%s</span>' % label_str)
        s = text.size()
        rect = qc.QRect(0, 0, int(s.width()), int(s.height()))
        tx, ty = x, y

        if 'B' in anchor:
            ty -= rect.height()
        if 'R' in anchor:
            tx -= rect.width()
        if 'M' in anchor:
            ty -= rect.height() // 2
        if 'C' in anchor:
            tx -= rect.width() // 2

        rect.translate(int(tx), int(ty))
        self.rect = rect
        self.text = text
        self.outline = outline
        self.label_bg = label_bg
        self.color = color
        self.p = p

    def draw(self):
        p = self.p
        rect = self.rect
        tx = rect.left()
        ty = rect.top()

        if self.outline:
            oldpen = p.pen()
            oldbrush = p.brush()
            p.setBrush(self.label_bg)
            rect.adjust(-2, 0, 2, 0)
            p.drawRect(rect)
            p.setPen(oldpen)
            p.setBrush(oldbrush)

        else:
            if self.label_bg:
                p.fillRect(rect, self.label_bg)

        p.translate(int(tx), int(ty))
        self.text.drawContents(p)
        p.translate(-int(tx), -int(ty))


def draw_label(p, x, y, label_str, label_bg, anchor='BL', outline=False):
    fm = p.fontMetrics()

    label = label_str
    rect = fm.boundingRect(label)

    tx, ty = x, y
    if 'T' in anchor:
        ty += rect.height()
    if 'R' in anchor:
        tx -= rect.width()
    if 'M' in anchor:
        ty += rect.height() // 2
    if 'C' in anchor:
        tx -= rect.width() // 2

    rect.translate(int(tx), int(ty))
    if outline:
        oldpen = p.pen()
        oldbrush = p.brush()
        p.setBrush(label_bg)
        rect.adjust(-2, 0, 2, 0)
        p.drawRect(rect)
        p.setPen(oldpen)
        p.setBrush(oldbrush)

    else:
        p.fillRect(rect, label_bg)

    p.drawText(int(tx), int(ty), label)


def get_err_palette():
    err_palette = qg.QPalette()
    err_palette.setColor(qg.QPalette.Base, qg.QColor(255, 200, 200))
    return err_palette


class QSliderNoWheel(qw.QSlider):

    def wheelEvent(self, ev):
        ev.ignore()

    def keyPressEvent(self, ev):
        ev.ignore()


class QSliderFloat(qw.QSlider):

    sliderMovedFloat = qc.pyqtSignal(float)
    valueChangedFloat = qc.pyqtSignal(float)
    rangeChangedFloat = qc.pyqtSignal(float, float)

    def __init__(self, *args, **kwargs):
        qw.QSlider.__init__(self, *args, **kwargs)
        self.setMinimum(0)
        self.setMaximum(1000)
        self.setSingleStep(10)
        self.setPageStep(100)
        self._fmin = 0.
        self._fmax = 1.
        self.valueChanged.connect(self._handleValueChanged)
        self.sliderMoved.connect(self._handleSliderMoved)

    def _f_to_i(self, fval):
        fval = float(fval)
        imin = self.minimum()
        imax = self.maximum()
        return max(
            imin,
            imin + min(
                int(round(
                    (fval-self._fmin) * (imax - imin)
                    / (self._fmax-self._fmin))),
                imax))

    def _i_to_f(self, ival):
        imin = self.minimum()
        imax = self.maximum()
        return self._fmin + (ival - imin) * (self._fmax - self._fmin) \
            / (imax - imin)

    def minimumFloat(self):
        return self._fmin

    def setMinimumFloat(self, fval):
        self._fmin = float(fval)
        self.rangeChangedFloat.emit(self._fmin, self._fmax)

    def maximumFloat(self):
        return self._fmax

    def setMaximumFloat(self, fval):
        self._fmax = float(fval)
        self.rangeChangedFloat.emit(self._fmin, self._fmax)

    def setRangeFloat(self, fmin, fmax):
        self._fmin = float(fmin)
        self._fmax = float(fmax)
        self.rangeChangedFloat.emit(self._fmin, self._fmax)

    def valueFloat(self):
        return self._i_to_f(self.value())

    def setValueFloat(self, fval):
        qw.QSlider.setValue(self, self._f_to_i(fval))

    def _handleValueChanged(self, ival):
        self.valueChangedFloat.emit(self._i_to_f(ival))

    def _handleSliderMoved(self, ival):
        self.sliderMovedFloat.emit(self._i_to_f(ival))


class MyValueEdit(qw.QLineEdit):

    edited = qc.pyqtSignal(float)

    def __init__(
            self,
            low_is_none=False,
            high_is_none=False,
            low_is_zero=False,
            *args, **kwargs):

        qw.QLineEdit.__init__(self, *args, **kwargs)
        self.value = 0.
        self.mi = 0.
        self.ma = 1.
        self.low_is_none = low_is_none
        self.high_is_none = high_is_none
        self.low_is_zero = low_is_zero
        self.editingFinished.connect(
            self.myEditingFinished)
        self.lock = False

    def setRange(self, mi, ma):
        self.mi = mi
        self.ma = ma

    def setValue(self, value):
        if not self.lock:
            self.value = value
            self.setPalette(qw.QApplication.palette())
            self.adjust_text()

    def myEditingFinished(self):
        try:
            t = str(self.text()).strip()
            if self.low_is_none and t in ('off', 'below'):
                value = self.mi
            elif self.high_is_none and t in ('off', 'above'):
                value = self.ma
            elif self.low_is_zero and float(t) == 0.0:
                value = self.mi
            else:
                value = float(t)

            if not (self.mi <= value <= self.ma):
                raise Exception('out of range')

            if value != self.value:
                self.value = value
                self.lock = True
                self.edited.emit(value)
                self.setPalette(qw.QApplication.palette())
        except Exception:
            self.setPalette(get_err_palette())

        self.lock = False

    def adjust_text(self):
        t = ('%8.5g' % self.value).strip()

        if self.low_is_zero and self.value == self.mi:
            t = '0'

        if self.low_is_none and self.value == self.mi:
            if self.high_is_none:
                t = 'below'
            else:
                t = 'off'

        if self.high_is_none and self.value == self.ma:
            if self.low_is_none:
                t = 'above'
            else:
                t = 'off'

        if t in ('off', 'below', 'above'):
            self.setStyleSheet('font-style: italic;')
        else:
            self.setStyleSheet(None)

        self.setText(t)


class ValControl(qw.QWidget):

    valchange = qc.pyqtSignal(object, int)

    def __init__(
            self,
            low_is_none=False,
            high_is_none=False,
            low_is_zero=False,
            type=float,
            *args):

        qc.QObject.__init__(self, *args)

        self.lname = qw.QLabel('name')
        self.lname.setSizePolicy(
            qw.QSizePolicy(qw.QSizePolicy.Minimum, qw.QSizePolicy.Minimum))
        self.lvalue = MyValueEdit(
            low_is_none=low_is_none,
            high_is_none=high_is_none,
            low_is_zero=low_is_zero)
        self.lvalue.setFixedWidth(100)
        self.slider = QSliderNoWheel(qc.Qt.Horizontal)
        self.slider.setSizePolicy(
            qw.QSizePolicy(qw.QSizePolicy.Expanding, qw.QSizePolicy.Minimum))
        self.slider.setMaximum(10000)
        self.slider.setSingleStep(100)
        self.slider.setPageStep(1000)
        self.slider.setTickPosition(qw.QSlider.NoTicks)
        self.slider.setFocusPolicy(qc.Qt.ClickFocus)

        self.low_is_none = low_is_none
        self.high_is_none = high_is_none
        self.low_is_zero = low_is_zero

        self.slider.valueChanged.connect(
                     self.slided)
        self.lvalue.edited.connect(
                     self.edited)

        self.type = type
        self.mute = False

    def widgets(self):
        return self.lname, self.lvalue, self.slider

    def s2v(self, svalue):
        if self.ma == 0 or self.mi == 0:
            return 0

        a = math.log(self.ma/self.mi) / 10000.
        value = self.mi*math.exp(a*svalue)
        value = self.type(value)
        return value

    def v2s(self, value):
        value = self.type(value)

        if value == 0 or self.mi == 0:
            return 0

        a = math.log(self.ma/self.mi) / 10000.
        return int(round(math.log(value/self.mi) / a))

    def setup(self, name, mi, ma, cur, ind):
        self.lname.setText(name)
        self.mi = mi
        self.ma = ma
        self.ind = ind
        self.lvalue.setRange(self.s2v(0), self.s2v(10000))
        self.set_value(cur)

    def set_range(self, mi, ma):
        if self.mi == mi and self.ma == ma:
            return

        vput = None
        if self.cursl == 0:
            vput = mi
        if self.cursl == 10000:
            vput = ma

        self.mi = mi
        self.ma = ma
        self.lvalue.setRange(self.s2v(0), self.s2v(10000))

        if vput is not None:
            self.set_value(vput)
        else:
            if self.cur < mi:
                self.set_value(mi)
            if self.cur > ma:
                self.set_value(ma)

    def set_value(self, cur):
        if cur is None:
            if self.low_is_none:
                cur = self.mi
            elif self.high_is_none:
                cur = self.ma

        if cur == 0.0:
            if self.low_is_zero:
                cur = self.mi

        self.mute = True
        self.cur = cur
        self.cursl = self.v2s(cur)
        self.slider.blockSignals(True)
        self.slider.setValue(self.cursl)
        self.slider.blockSignals(False)
        self.lvalue.blockSignals(True)
        if self.cursl in (0, 10000):
            self.lvalue.setValue(self.s2v(self.cursl))
        else:
            self.lvalue.setValue(self.cur)
        self.lvalue.blockSignals(False)
        self.mute = False

    def set_tracking(self, tracking):
        self.slider.setTracking(tracking)

    def get_value(self):
        return self.cur

    def slided(self, val):
        if self.cursl != val:
            self.cursl = val
            cur = self.s2v(self.cursl)

            if cur != self.cur:
                self.cur = cur
                self.lvalue.blockSignals(True)
                self.lvalue.setValue(self.cur)
                self.lvalue.blockSignals(False)
                self.fire_valchange()

    def edited(self, val):
        if self.cur != val:
            self.cur = val
            cursl = self.v2s(val)
            if (cursl != self.cursl):
                self.slider.blockSignals(True)
                self.slider.setValue(cursl)
                self.slider.blockSignals(False)
                self.cursl = cursl

            self.fire_valchange()

    def fire_valchange(self):

        if self.mute:
            return

        cur = self.cur

        if self.cursl == 0:
            if self.low_is_none:
                cur = None

            elif self.low_is_zero:
                cur = 0.0

        if self.cursl == 10000 and self.high_is_none:
            cur = None

        self.valchange.emit(cur, int(self.ind))


class LinValControl(ValControl):

    def s2v(self, svalue):
        value = svalue/10000. * (self.ma-self.mi) + self.mi
        value = self.type(value)
        return value

    def v2s(self, value):
        value = self.type(value)
        if self.ma == self.mi:
            return 0
        return int(round((value-self.mi)/(self.ma-self.mi) * 10000.))


class ColorbarControl(qw.QWidget):

    AVAILABLE_CMAPS = (
        'viridis',
        'plasma',
        'magma',
        'binary',
        'Reds',
        'copper',
        'seismic',
        'RdBu',
        'YlGn',
    )

    DEFAULT_CMAP = 'viridis'

    cmap_changed = qc.pyqtSignal(str)
    show_absolute_toggled = qc.pyqtSignal(bool)
    show_integrate_toggled = qc.pyqtSignal(bool)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.lname = qw.QLabel('Colormap')
        self.lname.setSizePolicy(
            qw.QSizePolicy(qw.QSizePolicy.Minimum, qw.QSizePolicy.Minimum))

        self.cmap_options = qw.QComboBox()
        self.cmap_options.setIconSize(qc.QSize(64, 12))
        for ic, cmap in enumerate(self.AVAILABLE_CMAPS):
            pixmap = qg.QPixmap.fromImage(
                get_colormap_qimage(cmap))
            icon = qg.QIcon(pixmap.scaled(64, 12))

            self.cmap_options.addItem(icon, '', cmap)
            self.cmap_options.setItemData(ic, cmap, qc.Qt.ToolTipRole)

        # self.cmap_options.setCurrentIndex(self.cmap_name)
        self.cmap_options.currentIndexChanged.connect(self.set_cmap)
        self.cmap_options.setSizePolicy(
            qw.QSizePolicy(qw.QSizePolicy.Minimum, qw.QSizePolicy.Minimum))

        self.colorslider = ColorbarSlider(self)
        self.colorslider.setSizePolicy(
            qw.QSizePolicy.MinimumExpanding | qw.QSizePolicy.ExpandFlag,
            qw.QSizePolicy.MinimumExpanding | qw.QSizePolicy.ExpandFlag
        )
        self.clip_changed = self.colorslider.clip_changed

        btn_size = qw.QSizePolicy(
            qw.QSizePolicy.Maximum | qw.QSizePolicy.ShrinkFlag,
            qw.QSizePolicy.Maximum | qw.QSizePolicy.ShrinkFlag)

        self.symetry_toggle = qw.QPushButton()
        self.symetry_toggle.setIcon(
            qg.QIcon.fromTheme('object-flip-horizontal'))
        self.symetry_toggle.setToolTip('Symetric clip values')
        self.symetry_toggle.setSizePolicy(btn_size)
        self.symetry_toggle.setCheckable(True)
        self.symetry_toggle.toggled.connect(self.toggle_symetry)
        self.symetry_toggle.setChecked(True)

        self.reverse_toggle = qw.QPushButton()
        self.reverse_toggle.setIcon(
            qg.QIcon.fromTheme('object-rotate-right'))
        self.reverse_toggle.setToolTip('Reverse the colormap')
        self.reverse_toggle.setSizePolicy(btn_size)
        self.reverse_toggle.setCheckable(True)
        self.reverse_toggle.toggled.connect(self.toggle_reverse_cmap)

        self.abs_toggle = qw.QPushButton()
        self.abs_toggle.setIcon(
            qg.QIcon.fromTheme('go-bottom'))
        self.abs_toggle.setToolTip('Show absolute values')
        self.abs_toggle.setSizePolicy(btn_size)
        self.abs_toggle.setCheckable(True)
        self.abs_toggle.toggled.connect(self.toggle_absolute)

        self.int_toggle = qw.QPushButton()
        self.int_toggle.setText('∫')
        self.int_toggle.setToolTip(
            u'Integrate traces (e.g. strain rate → strain)')
        self.int_toggle.setSizePolicy(btn_size)
        self.int_toggle.setCheckable(True)
        self.int_toggle.setMaximumSize(
            24,
            self.int_toggle.maximumSize().height())
        self.int_toggle.toggled.connect(self.show_integrate_toggled.emit)

        v_splitter = qw.QFrame()
        v_splitter.setFrameShape(qw.QFrame.VLine)
        v_splitter.setFrameShadow(qw.QFrame.Sunken)

        self.controls = qw.QWidget()
        layout = qw.QHBoxLayout()
        layout.addWidget(self.colorslider)
        layout.addWidget(self.symetry_toggle)
        layout.addWidget(self.reverse_toggle)
        layout.addWidget(v_splitter)
        layout.addWidget(self.abs_toggle)
        layout.addWidget(self.int_toggle)
        self.controls.setLayout(layout)

        self.set_cmap_name(self.DEFAULT_CMAP)

    def set_cmap(self, idx):
        self.set_cmap_name(self.cmap_options.itemData(idx))

    def set_cmap_name(self, cmap_name):
        self.cmap_name = cmap_name
        self.colorslider.set_cmap_name(cmap_name)
        self.cmap_changed.emit(cmap_name)

    def get_cmap(self):
        return self.cmap_name

    def toggle_symetry(self, toggled):
        self.colorslider.set_symetry(toggled)

    def toggle_reverse_cmap(self):
        cmap = self.get_cmap()
        if cmap.endswith('_r'):
            r_cmap = cmap.rstrip('_r')
        else:
            r_cmap = cmap + '_r'
        self.set_cmap_name(r_cmap)

    def toggle_absolute(self, toggled):
        self.symetry_toggle.setChecked(not toggled)
        self.show_absolute_toggled.emit(toggled)

    def widgets(self):
        return (self.lname, self.cmap_options, self.controls)


class ColorbarSlider(qw.QWidget):
    DEFAULT_CMAP = 'viridis'
    CORNER_THRESHOLD = 10
    MIN_WIDTH = .05

    clip_changed = qc.pyqtSignal(float, float)

    class COMPONENTS(enum.Enum):
        LeftLine = 1
        RightLine = 2
        Center = 3

    def __init__(self, *args, cmap_name=None):
        super().__init__()
        self.cmap_name = cmap_name or self.DEFAULT_CMAP
        self.clip_min = 0.
        self.clip_max = 1.

        self._sym_locked = True
        self._mouse_inside = False
        self._window = None
        self._old_pos = None
        self._component_grabbed = None

        self.setMouseTracking(True)

    def set_cmap_name(self, cmap_name):
        self.cmap_name = cmap_name
        self.repaint()

    def get_cmap_name(self):
        return self.cmap_name

    def set_symetry(self, symetry):
        self._sym_locked = symetry
        if self._sym_locked:
            clip_max = 1. - min(self.clip_min, 1.-self.clip_max)
            clip_min = 1. - clip_max
            self.set_clip(clip_min, clip_max)

    def _set_window(self, window):
        self._window = window

    def _get_left_line(self):
        rect = self._get_active_rect()
        if not rect:
            return
        return qc.QLineF(rect.left(), 0, rect.left(), rect.height())

    def _get_right_line(self):
        rect = self._get_active_rect()
        if not rect:
            return
        return qc.QLineF(rect.right(), 0, rect.right(), rect.height())

    def _get_active_rect(self):
        if not self._window:
            return
        rect = qc.QRect(self._window)
        width = rect.width()
        rect.setLeft(width * self.clip_min)
        rect.setRight(width * self.clip_max)
        return rect

    def set_clip(self, clip_min, clip_max):
        if clip_min < 0. or clip_max > 1.:
            return
        if clip_max - clip_min < self.MIN_WIDTH:
            return

        self.clip_min = clip_min
        self.clip_max = clip_max
        self.repaint()
        self.clip_changed.emit(self.clip_min, self.clip_max)

    def mousePressEvent(self, event):
        act_rect = self._get_active_rect()
        if event.buttons() != qc.Qt.MouseButton.LeftButton:
            self._component_grabbed = None
            return

        dist_left = abs(event.pos().x() - act_rect.left())
        dist_right = abs(event.pos().x() - act_rect.right())

        if 0 < dist_left < self.CORNER_THRESHOLD:
            self._component_grabbed = self.COMPONENTS.LeftLine
            self.setCursor(qg.QCursor(qc.Qt.CursorShape.SizeHorCursor))
        elif 0 < dist_right < self.CORNER_THRESHOLD:
            self._component_grabbed = self.COMPONENTS.RightLine
            self.setCursor(qg.QCursor(qc.Qt.CursorShape.SizeHorCursor))
        else:
            self.setCursor(qg.QCursor())

    def mouseReleaseEvent(self, event):
        self._component_grabbed = None
        self.repaint()

    def mouseDoubleClickEvent(self, event):
        self.set_clip(0., 1.)

    def wheelEvent(self, event):
        event.accept()
        if not self._sym_locked:
            return

        delta = event.angleDelta().y()
        delta = -delta / 5e3
        clip_min_new = max(self.clip_min + delta, 0.)
        clip_max_new = min(self.clip_max - delta, 1.)
        self._mouse_inside = True
        self.set_clip(clip_min_new, clip_max_new)

    def mouseMoveEvent(self, event):
        act_rect = self._get_active_rect()

        if not self._component_grabbed:
            dist_left = abs(event.pos().x() - act_rect.left())
            dist_right = abs(event.pos().x() - act_rect.right())

            if 0 <= dist_left < self.CORNER_THRESHOLD or \
                    0 <= dist_right < self.CORNER_THRESHOLD:
                self.setCursor(qg.QCursor(qc.Qt.CursorShape.SizeHorCursor))
            else:
                self.setCursor(qg.QCursor())

        if self._old_pos and self._component_grabbed:
            shift = (event.pos() - self._old_pos).x() / self._window.width()

            if self._component_grabbed is self.COMPONENTS.LeftLine:
                clip_min_new = max(self.clip_min + shift, 0.)
                clip_max_new = \
                    min(self.clip_max - shift, 1.) \
                    if self._sym_locked else self.clip_max

            elif self._component_grabbed is self.COMPONENTS.RightLine:
                clip_max_new = min(self.clip_max + shift, 1.)
                clip_min_new = \
                    max(self.clip_min - shift, 0.) \
                    if self._sym_locked else self.clip_min

            self.set_clip(clip_min_new, clip_max_new)

        self._old_pos = event.pos()

    def enterEvent(self, e):
        self._mouse_inside = True
        self.repaint()

    def leaveEvent(self, e):
        self._mouse_inside = False
        self.repaint()

    def paintEvent(self, e):
        p = qg.QPainter(self)
        self._set_window(p.window())

        p.drawImage(
            p.window(),
            get_colormap_qimage(self.cmap_name, self.clip_min, self.clip_max))

        left_line = self._get_left_line()
        right_line = self._get_right_line()

        pen = qg.QPen()
        pen.setWidth(2)
        pen.setStyle(qc.Qt.DotLine)
        pen.setBrush(qc.Qt.white)
        p.setPen(pen)
        p.setCompositionMode(
            qg.QPainter.CompositionMode.CompositionMode_Difference)

        p.drawLine(left_line)
        p.drawLine(right_line)

        label_rect = self._get_active_rect()
        label_rect.setLeft(label_rect.left() + 5)
        label_rect.setRight(label_rect.right() - 5)
        label_left_rect = qc.QRectF(label_rect)
        label_right_rect = qc.QRectF(label_rect)
        label_left_align = qc.Qt.AlignLeft
        label_right_align = qc.Qt.AlignRight

        if label_rect.left() > 50:
            label_left_rect.setRight(label_rect.left() - 10)
            label_left_rect.setLeft(0)
            label_left_align = qc.Qt.AlignRight

        if self._window.right() - label_rect.right() > 50:
            label_right_rect.setLeft(label_rect.right() + 10)
            label_right_rect.setRight(self._window.right())
            label_right_align = qc.Qt.AlignLeft

        if self._mouse_inside or self._component_grabbed:
            p.drawText(
                label_left_rect,
                label_left_align | qc.Qt.AlignVCenter,
                '%d%%' % round(self.clip_min * 100))
            p.drawText(
                label_right_rect,
                label_right_align | qc.Qt.AlignVCenter,
                '%d%%' % round(self.clip_max * 100))


class Progressbar(object):
    def __init__(self, parent, name, can_abort=True):
        self.parent = parent
        self.name = name
        self.label = qw.QLabel(name, parent)
        self.pbar = qw.QProgressBar(parent)
        self.aborted = False
        self.time_last_update = 0.
        if can_abort:
            self.abort_button = qw.QPushButton('Abort', parent)
            self.abort_button.clicked.connect(
                self.abort)
        else:
            self.abort_button = None

    def widgets(self):
        widgets = [self.label, self.bar()]
        if self.abort_button:
            widgets.append(self.abort_button)
        return widgets

    def bar(self):
        return self.pbar

    def abort(self):
        self.aborted = True


class Progressbars(qw.QFrame):
    def __init__(self, parent):
        qw.QFrame.__init__(self, parent)
        self.layout = qw.QGridLayout()
        self.setLayout(self.layout)
        self.bars = {}
        self.start_times = {}
        self.hide()

    def set_status(self, name, value, can_abort=True):
        value = int(round(value))
        now = time.time()
        if name not in self.start_times:
            self.start_times[name] = now
            return False
        else:
            if now < self.start_times[name] + 1.0:
                if value == 100:
                    del self.start_times[name]
                return False

        self.start_times.get(name, 0.0)
        if name not in self.bars:
            if value == 100:
                return False
            self.bars[name] = Progressbar(self, name, can_abort=can_abort)
            self.make_layout()

        bar = self.bars[name]
        if bar.time_last_update < now - 0.1 or value == 100:
            bar.bar().setValue(value)
            bar.time_last_update = now

        if value == 100:
            del self.bars[name]
            del self.start_times[name]
            self.make_layout()
            for w in bar.widgets():
                w.setParent(None)

        return bar.aborted

    def make_layout(self):
        while True:
            c = self.layout.takeAt(0)
            if c is None:
                break

        for ibar, bar in enumerate(self.bars.values()):
            for iw, w in enumerate(bar.widgets()):
                self.layout.addWidget(w, ibar, iw)

        if not self.bars:
            self.hide()
        else:
            self.show()


def tohex(c):
    return '%02x%02x%02x' % c


def to01(c):
    return c[0]/255., c[1]/255., c[2]/255.


def beautify_axes(axes):
    try:
        from cycler import cycler
        axes.set_prop_cycle(
            cycler('color', [to01(x) for x in plot.graph_colors]))

    except (ImportError, KeyError):
        axes.set_color_cycle(list(map(to01, plot.graph_colors)))

    xa = axes.get_xaxis()
    ya = axes.get_yaxis()
    for attr in ('labelpad', 'LABELPAD'):
        if hasattr(xa, attr):
            setattr(xa, attr, xa.get_label().get_fontsize())
            setattr(ya, attr, ya.get_label().get_fontsize())
            break


class FigureFrame(qw.QFrame):

    def __init__(self, parent=None, figure_cls=None):
        qw.QFrame.__init__(self, parent)
        fgcolor = plot.tango_colors['aluminium5']
        dpi = 0.5*(self.logicalDpiX() + self.logicalDpiY())

        font = qg.QFont()
        font.setBold(True)
        fontsize = font.pointSize()

        import matplotlib
        matplotlib.rcdefaults()
        matplotlib.rcParams['backend'] = 'Qt5Agg'

        matplotlib.rc('xtick', direction='out', labelsize=fontsize)
        matplotlib.rc('ytick', direction='out', labelsize=fontsize)
        matplotlib.rc('xtick.major', size=8, width=1)
        matplotlib.rc('xtick.minor', size=4, width=1)
        matplotlib.rc('ytick.major', size=8, width=1)
        matplotlib.rc('ytick.minor', size=4, width=1)
        matplotlib.rc('figure', facecolor='white', edgecolor=tohex(fgcolor))

        matplotlib.rc(
            'font',
            family='sans-serif',
            weight='bold',
            size=fontsize,
            **{'sans-serif': [
                font.family(),
                'DejaVu Sans', 'Bitstream Vera Sans', 'Lucida Grande',
                'Verdana', 'Geneva', 'Lucid', 'Arial', 'Helvetica']})

        matplotlib.rc('legend', fontsize=fontsize)

        matplotlib.rc('text', color=tohex(fgcolor))
        matplotlib.rc('xtick', color=tohex(fgcolor))
        matplotlib.rc('ytick', color=tohex(fgcolor))
        matplotlib.rc('figure.subplot', bottom=0.15)

        matplotlib.rc('axes', linewidth=1.0, unicode_minus=False)
        matplotlib.rc(
            'axes',
            facecolor='white',
            edgecolor=tohex(fgcolor),
            labelcolor=tohex(fgcolor))

        try:
            from cycler import cycler
            matplotlib.rc(
                'axes', prop_cycle=cycler(
                    'color', [to01(x) for x in plot.graph_colors]))

        except (ImportError, KeyError):
            try:
                matplotlib.rc('axes', color_cycle=[
                    to01(x) for x in plot.graph_colors])

            except KeyError:
                pass

        try:
            matplotlib.rc('axes', labelsize=fontsize)
        except KeyError:
            pass

        try:
            matplotlib.rc('axes', labelweight='bold')
        except KeyError:
            pass

        if figure_cls is None:
            from matplotlib.figure import Figure
            figure_cls = Figure

        from matplotlib.backends.backend_qt5agg import \
            NavigationToolbar2QT as NavigationToolbar

        from matplotlib.backends.backend_qt5agg \
            import FigureCanvasQTAgg as FigureCanvas

        layout = qw.QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setLayout(layout)
        self.figure = figure_cls(dpi=dpi)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setParent(self)
        self.canvas.setSizePolicy(
            qw.QSizePolicy(
                qw.QSizePolicy.Expanding,
                qw.QSizePolicy.Expanding))
        toolbar_frame = qw.QFrame()
        toolbar_frame.setFrameShape(qw.QFrame.StyledPanel)
        toolbar_frame_layout = qw.QHBoxLayout()
        toolbar_frame_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_frame.setLayout(toolbar_frame_layout)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.canvas, 0, 0)
        toolbar_frame_layout.addWidget(self.toolbar)
        layout.addWidget(toolbar_frame, 1, 0)
        self.closed = False

    def gca(self):
        axes = self.figure.gca()
        beautify_axes(axes)
        return axes

    def gcf(self):
        return self.figure

    def draw(self):
        '''
        Draw with AGG, then queue for Qt update.
        '''
        self.canvas.draw()

    def closeEvent(self, ev):
        self.closed = True


class SmartplotFrame(FigureFrame):
    def __init__(
            self, parent=None, plot_args=[], plot_kwargs={}, plot_cls=None):

        from pyrocko.plot import smartplot

        FigureFrame.__init__(
            self,
            parent=parent,
            figure_cls=smartplot.SmartplotFigure)

        if plot_cls is None:
            plot_cls = smartplot.Plot

        self.plot = plot_cls(
            *plot_args,
            fig=self.figure,
            call_mpl_init=False,
            **plot_kwargs)


class WebKitFrame(qw.QFrame):

    def __init__(self, url=None, parent=None):
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView as WebView
        except ImportError:
            from PyQt5.QtWebKitWidgets import QWebView as WebView
        qw.QFrame.__init__(self, parent)
        layout = qw.QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)
        self.web_widget = WebView()
        layout.addWidget(self.web_widget, 0, 0)
        if url:
            self.web_widget.load(qc.QUrl(url))


class VTKFrame(qw.QFrame):

    def __init__(self, actors=None, parent=None):
        import vtk
        from vtk.qt.QVTKRenderWindowInteractor import \
            QVTKRenderWindowInteractor

        qw.QFrame.__init__(self, parent)
        layout = qw.QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setLayout(layout)

        self.vtk_widget = QVTKRenderWindowInteractor(self)
        layout.addWidget(self.vtk_widget, 0, 0)

        self.renderer = vtk.vtkRenderer()
        self.vtk_widget.GetRenderWindow().AddRenderer(self.renderer)
        self.iren = self.vtk_widget.GetRenderWindow().GetInteractor()

        if actors:
            for a in actors:
                self.renderer.AddActor(a)

    def init(self):
        self.iren.Initialize()

    def add_actor(self, actor):
        self.renderer.AddActor(actor)


class PixmapFrame(qw.QLabel):

    def __init__(self, filename=None, parent=None):

        qw.QLabel.__init__(self, parent)
        self.setAlignment(qc.Qt.AlignCenter)
        self.setContentsMargins(0, 0, 0, 0)
        self.menu = qw.QMenu(self)
        action = qw.QAction('Save as', self.menu)
        action.triggered.connect(self.save_pixmap)
        self.menu.addAction(action)

        if filename:
            self.load_pixmap(filename)

    def contextMenuEvent(self, event):
        self.menu.popup(qg.QCursor.pos())

    def load_pixmap(self, filename):
        self.pixmap = qg.QPixmap(filename)
        self.setPixmap(self.pixmap)

    def save_pixmap(self, filename=None):
        if not filename:
            filename, _ = qw.QFileDialog.getSaveFileName(
                self.parent(), caption='save as')
        self.pixmap.save(filename)


class Projection(object):
    def __init__(self):
        self.xr = 0., 1.
        self.ur = 0., 1.

    def set_in_range(self, xmin, xmax):
        if xmax == xmin:
            xmax = xmin + 1.

        self.xr = xmin, xmax

    def get_in_range(self):
        return self.xr

    def set_out_range(self, umin, umax):
        if umax == umin:
            umax = umin + 1.

        self.ur = umin, umax

    def get_out_range(self):
        return self.ur

    def __call__(self, x):
        umin, umax = self.ur
        xmin, xmax = self.xr
        return umin + (x-xmin)*((umax-umin)/(xmax-xmin))

    def clipped(self, x):
        umin, umax = self.ur
        xmin, xmax = self.xr
        return min(umax, max(umin, umin + (x-xmin)*((umax-umin)/(xmax-xmin))))

    def rev(self, u):
        umin, umax = self.ur
        xmin, xmax = self.xr
        return xmin + (u-umin)*((xmax-xmin)/(umax-umin))


class NoData(Exception):
    pass


g_working_system_time_range = util.get_working_system_time_range()

g_initial_time_range = []

try:
    g_initial_time_range.append(
        calendar.timegm((1950, 1, 1, 0, 0, 0)))
except Exception:
    g_initial_time_range.append(g_working_system_time_range[0])

try:
    g_initial_time_range.append(
        calendar.timegm((time.gmtime().tm_year + 1, 1, 1, 0, 0, 0)))
except Exception:
    g_initial_time_range.append(g_working_system_time_range[1])


def four_way_arrow(position, size):
    r = 5.
    w = 1.

    points = [
        (position[0]+size*float(a), position[1]+size*float(b))
        for (a, b) in [
            (0, r),
            (1.5*w, r-2*w),
            (0.5*w, r-2*w),
            (0.5*w, 0.5*w),
            (r-2*w, 0.5*w),
            (r-2*w, 1.5*w),
            (r, 0),
            (r-2*w, -1.5*w),
            (r-2*w, -0.5*w),
            (0.5*w, -0.5*w),
            (0.5*w, -(r-2*w)),
            (1.5*w, -(r-2*w)),
            (0, -r),
            (-1.5*w, -(r-2*w)),
            (-0.5*w, -(r-2*w)),
            (-0.5*w, -0.5*w),
            (-(r-2*w), -0.5*w),
            (-(r-2*w), -1.5*w),
            (-r, 0),
            (-(r-2*w), 1.5*w),
            (-(r-2*w), 0.5*w),
            (-0.5*w, 0.5*w),
            (-0.5*w, r-2*w),
            (-1.5*w, r-2*w)]]

    poly = qg.QPolygon(len(points))
    for ipoint, point in enumerate(points):
        poly.setPoint(ipoint, *(int(round(v)) for v in point))

    return poly


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


class RangeEdit(qw.QFrame):

    rangeChanged = qc.pyqtSignal()
    focusChanged = qc.pyqtSignal()
    tcursorChanged = qc.pyqtSignal()
    rangeEditPressed = qc.pyqtSignal()
    rangeEditReleased = qc.pyqtSignal()

    def __init__(self, parent=None):
        qw.QFrame.__init__(self, parent)
        self.setFrameStyle(qw.QFrame.StyledPanel | qw.QFrame.Plain)
        # self.setBackgroundRole(qg.QPalette.Button)
        # self.setAutoFillBackground(True)
        self.setMouseTracking(True)
        poli = qw.QSizePolicy(
            qw.QSizePolicy.Expanding,
            qw.QSizePolicy.Fixed)

        self.setSizePolicy(poli)
        self.setMinimumSize(100, 3*24)

        self._size_hint = qw.QPushButton().sizeHint()

        self._track_start = None
        self._track_range = None
        self._track_focus = None
        self._track_what = None

        self._tcursor = None
        self._hover_point = None

        self._provider = None
        self.tmin, self.tmax = None, None
        self.tduration, self.tposition = None, 0.

    def set_data_provider(self, provider):
        self._provider = provider

    def set_data_name(self, name):
        self._data_name = name

    def sizeHint(self):
        return self._size_hint

    def get_data_range(self):
        if self._provider:
            vals = []
            for data in self._provider.iter_data(self._data_name):
                vals.append(data.min())
                vals.append(data.max())

            if vals:
                return min(vals), max(vals)

        return None, None

    def get_histogram(self, projection, h):
        h = int(h)
        umin_w, umax_w = projection.get_out_range()
        tmin_w, tmax_w = projection.get_in_range()
        nbins = int(umax_w - umin_w)
        counts = num.zeros(nbins, dtype=int)
        if self._provider:
            for data in self._provider.iter_data(self._data_name):
                ibins = ((data - tmin_w) * (nbins / (tmax_w - tmin_w))) \
                    .astype(int)
                num.clip(ibins, 0, nbins-1, ibins)
                counts += num.bincount(ibins, minlength=nbins)

        histogram = counts * h // (num.max(counts[1:-1]) or 1)
        bitmap = num.zeros((h, nbins), dtype=bool)
        for i in range(h):
            bitmap[h-1-i, :] = histogram > i

        bitmap = num.packbits(bitmap, axis=1, bitorder='little')

        return qg.QBitmap.fromData(
            qc.QSize(nbins, h),
            bitmap.tobytes(),
            qg.QImage.Format_MonoLSB)

    def draw_time_ticks(self, painter, projection, rect):

        palette = self.palette()
        alpha_brush = palette.highlight()
        color = alpha_brush.color()
        # color.setAlpha(60)
        painter.setPen(qg.QPen(color))

        tmin, tmax = projection.get_in_range()
        tinc, tinc_unit = plot.nice_time_tick_inc((tmax - tmin) / 7.)
        tick_times, _ = plot.time_tick_labels(tmin, tmax, tinc, tinc_unit)

        for tick_time in tick_times:
            x = int(round(projection(tick_time)))
            painter.drawLine(
                x, rect.top(), x, rect.top() + rect.height() // 5)

    def drawit(self, painter):

        palette = self.palette()

        upper_projection = self.upper_projection()
        lower_projection = self.lower_projection()

        upper_rect = self.upper_rect()
        lower_rect = self.lower_rect()
        focus_rect = self.focus_rect(upper_projection)

        fill_brush = palette.brush(qg.QPalette.Button)
        painter.fillRect(upper_rect, fill_brush)

        if focus_rect:
            painter.setBrush(palette.light())
            poly = qg.QPolygon(8)
            poly.setPoint(
                0, lower_rect.x(), lower_rect.y())
            poly.setPoint(
                1, lower_rect.x(), lower_rect.y()+lower_rect.height())
            poly.setPoint(
                2, lower_rect.x() + lower_rect.width(),
                lower_rect.y() + lower_rect.height())
            poly.setPoint(
                3, lower_rect.x() + lower_rect.width(), lower_rect.y())
            poly.setPoint(
                4, focus_rect.x() + focus_rect.width(),
                upper_rect.y() + upper_rect.height())
            poly.setPoint(
                5, focus_rect.x() + focus_rect.width(), upper_rect.y())
            poly.setPoint(
                6, focus_rect.x(), upper_rect.y())
            poly.setPoint(
                7, focus_rect.x(), upper_rect.y() + upper_rect.height())
            painter.drawPolygon(poly)
        else:
            fill_brush = palette.light()
            painter.fillRect(upper_rect, fill_brush)

        # painter.setBrush(palette.text())
        # poly = four_way_arrow((self.width() / 2.0, self.height() / 2.0), 2.)
        # painter.drawPolygon(poly)

        self.draw_time_ticks(painter, upper_projection, upper_rect)
        if focus_rect and self.tduration:
            self.draw_time_ticks(painter, lower_projection, lower_rect)

        xpen = qg.QPen(palette.color(qg.QPalette.ButtonText))
        painter.setPen(xpen)
        painter.drawPixmap(
            0, upper_rect.x(),
            self.get_histogram(upper_projection, upper_rect.height()))

        if focus_rect and self.tduration:
            painter.drawPixmap(
                0, lower_rect.y(),
                self.get_histogram(lower_projection, lower_rect.height()))

        # frame_pen = qg.QPen(palette.color(qg.QPalette.ButtonText))
        # painter.setPen(frame_pen)
        # painter.drawRect(upper_rect)
        # if self.tduration:
        #     painter.drawRect(lower_rect)

        if self._tcursor is not None:
            x = int(round(upper_projection(self._tcursor)))
            painter.drawLine(x, upper_rect.top(), x, upper_rect.bottom())
            if focus_rect and self.tduration and lower_projection:
                x = int(round(lower_projection(self._tcursor)))
                painter.drawLine(x, lower_rect.top(), x, lower_rect.bottom())

        if self._hover_point and lower_rect.contains(self._hover_point) \
                and not self.tduration and not self._track_start:

            alpha_brush = palette.highlight()
            color = alpha_brush.color()
            color.setAlpha(30)
            alpha_brush.setColor(color)
            painter.fillRect(lower_rect, alpha_brush)

    def upper_projection(self):
        p = Projection()
        if None in (self.tmin, self.tmax):
            p.set_in_range(*g_initial_time_range)
        else:
            p.set_in_range(self.tmin, self.tmax)

        p.set_out_range(0., self.width())
        return p

    def lower_projection(self):
        tmin_eff = self.tmin_effective()
        tmax_eff = self.tmax_effective()
        if None in (tmin_eff, tmax_eff):
            return None

        p = Projection()
        p.set_in_range(tmin_eff, tmax_eff)
        p.set_out_range(0., self.width())
        return p

    def tmin_effective(self):
        return tmin_effective(
            self.tmin, self.tmax, self.tduration, self.tposition)

    def tmax_effective(self):
        return tmax_effective(
            self.tmin, self.tmax, self.tduration, self.tposition)

    def upper_rect(self):
        vmin = 0
        vmax = self.height() // 3
        umin, umax = 0, self.width()
        return qc.QRect(umin, vmin, umax-umin, vmax-vmin)

    def lower_rect(self):
        vmin = 2 * self.height() // 3
        vmax = self.height()
        umin, umax = 0, self.width()
        return qc.QRect(umin, vmin, umax-umin, vmax-vmin)

    def focus_rect(self, projection):
        vmin = 0
        vmax = self.height() // 3

        tmin_eff = self.tmin_effective()
        tmax_eff = self.tmax_effective()
        if None in (tmin_eff, tmax_eff):
            return None

        umin = rint(projection(tmin_eff))
        umax = rint(projection(tmax_eff))

        return qc.QRect(umin, vmin, umax-umin+1, vmax-vmin)

    def set_range(self, tmin, tmax):
        if None in (tmin, tmax):
            tmin = None
            tmax = None
        elif tmin == tmax:
            tmin -= 0.5
            tmax += 0.5

        self.tmin = tmin
        self.tmax = tmax

        self.rangeChanged.emit()
        self.update()

    def get_range(self):
        return self.tmin, self.tmax

    def set_focus(self, tduration, tposition):
        self.tduration = tduration
        self.tposition = tposition
        self.focusChanged.emit()
        self.update()

    def get_focus(self):
        return (self.tduration, self.tposition)

    def get_tcursor(self):
        return self._tcursor

    def update_data_range(self):
        self.set_range(*self.get_data_range())

    def paintEvent(self, paint_ev):
        painter = qg.QPainter(self)
        painter.setRenderHint(qg.QPainter.Antialiasing)
        self.drawit(painter)
        qw.QFrame.paintEvent(self, paint_ev)

    def mousePressEvent(self, mouse_ev):

        if mouse_ev.button() == qc.Qt.LeftButton:
            self.rangeEditPressed.emit()

            if None in (self.tmin, self.tmax):
                self.set_range(*g_initial_time_range)

            self._track_start = mouse_ev.x(), mouse_ev.y()
            self._track_range = self.get_range()
            self._track_focus = self.get_focus()
            # upper_projection = self.upper_projection()
            # focus_rect = self.focus_rect(upper_projection)
            upper_rect = self.upper_rect()
            lower_rect = self.lower_rect()
            if upper_rect.contains(mouse_ev.pos()):
                self._track_what = 'global'
            elif lower_rect.contains(mouse_ev.pos()):
                self._track_what = 'focus'
                if self.tduration is None:
                    frac = 0.02
                    tduration = (self.tmax - self.tmin) * (1.0 - frac)
                    tposition = 0.5*frac
                    self.set_focus(tduration, tposition)

            else:
                if self.tduration is not None:
                    self._track_what = 'focus_slide'
                else:
                    self._track_what = 'global_slide'

        self.update()

    def enterEvent(self, ev):
        self._tcursor = None  # is set later by mouseMoveEvent
        self._hover_point = None
        self.tcursorChanged.emit()

    def leaveEvent(self, ev):
        self._tcursor = None
        self._hover_point = None
        self.tcursorChanged.emit()
        self.update()

    def mouseReleaseEvent(self, mouse_ev):
        if self._track_start:
            self.rangeEditReleased.emit()
            self.update()

        self._track_start = None
        self._track_range = None
        self._track_focus = None
        self._track_what = None
        if self.tduration is not None:
            if self.tduration >= self.tmax - self.tmin:
                self.set_focus(None, 0.0)
            elif self.tposition < 0.:
                self.set_focus(self.tduration, 0.0)
            elif self.tposition > 1.0 - self.tduration \
                    / (self.tmax - self.tmin):
                self.set_focus(
                    self.tduration, 1.0 - self.tduration
                    / (self.tmax - self.tmin))

    def mouseDoubleClickEvent(self, mouse_ev):
        if mouse_ev.button() == qc.Qt.LeftButton:
            lower_rect = self.lower_rect()
            if lower_rect.contains(mouse_ev.pos()) \
                    and self.tduration is not None:

                etmin = self.tmin_effective()
                etmax = self.tmax_effective()
                self.set_range(etmin, etmax)
                self.set_focus(None, 0.0)

            upper_rect = self.upper_rect()
            if upper_rect.contains(mouse_ev.pos()) \
                    and self.tduration is not None:

                self.set_focus(None, 0.0)

    def mouseMoveEvent(self, mouse_ev):
        point = self.mapFromGlobal(mouse_ev.globalPos())
        self._hover_point = point

        if self._track_start is not None:
            x0, y0 = self._track_start
            dx = (point.x() - x0)/float(self.width())
            dy = (point.y() - y0)/float(self.height())
            xfrac = x0/float(self.width())
            tmin0, tmax0 = self._track_range
            tduration0, tposition0 = self._track_focus

            if self._track_what in ('global', 'global_slide'):
                if self._track_what == 'global':
                    scale = math.exp(-dy)
                else:
                    scale = 1.0

                dtr = (tmax0-tmin0) * (scale - 1.0)
                dt = dx*(tmax0-tmin0)*scale

                tmin = tmin0 - dt - dtr*xfrac
                tmax = tmax0 - dt + dtr*(1.-xfrac)

                self.set_range(tmin, tmax)

                tduration, tposition = self._track_focus
                if tduration is not None:
                    etmin0 = tmin_effective(
                        tmin0, tmax0, tduration0, tposition0)

                    tposition = (etmin0 - tmin) / (tmax - tmin)
                    self.set_focus(tduration0, tposition)

            elif self._track_what == 'focus':
                if tduration0 is not None:
                    scale = math.exp(-dy)

                    dtr = tduration0 * (scale - 1.0)
                    dt = dx * tduration0 * scale

                    etmin0 = tmin_effective(
                        tmin0, tmax0, tduration0, tposition0)
                    etmax0 = tmax_effective(
                        tmin0, tmax0, tduration0, tposition0)

                    tmin = etmin0 - dt - dtr*xfrac
                    tmax = etmax0 - dt + dtr*(1.-xfrac)

                    tduration = tmax - tmin

                    tposition = (tmin - tmin0) / (tmax0 - tmin0)
                    tposition = min(
                        max(0., tposition),
                        1.0 - tduration / (tmax0 - tmin0))

                    if tduration < (tmax0 - tmin0):
                        self.set_focus(tduration, tposition)
                    else:
                        self.set_focus(None, tposition)

                else:
                    tduration, tposition = tmax0 - tmin0, 0.0
                    self.set_focus(tduration, tposition)
                    self._track_focus = (tduration, tposition)

            elif self._track_what == 'focus_slide':
                if tduration0 is not None:
                    self.set_focus(
                        tduration0,
                        min(
                            max(0., tposition0 + dx),
                            1.0 - tduration0 / (tmax0 - tmin0)))

        else:

            upper_rect = self.upper_rect()
            lower_rect = self.lower_rect()
            upper_projection = self.upper_projection()
            lower_projection = self.lower_projection()

            app = get_app()
            have_focus = lower_projection and self.tduration is not None

            if upper_rect.contains(point):
                self.setCursor(qg.QCursor(qc.Qt.CursorShape.CrossCursor))
                self._tcursor = upper_projection.rev(point.x())
                app.status(
                    'Click and drag to change global time interval. '
                    'Move up/down to zoom.' + (
                        ' Double-click to clear focus time interval.'
                        if have_focus else ''))

            elif lower_rect.contains(point):
                self.setCursor(qg.QCursor(qc.Qt.CursorShape.CrossCursor))
                if have_focus:
                    self._tcursor = lower_projection.rev(point.x())
                    app.status(
                        'Click and drag to change local time interval. '
                        'Double-click to set global time interval from focus.')
                else:
                    app.status(
                        'Click to activate focus time window.')
            else:
                self.setCursor(qg.QCursor(qc.Qt.CursorShape.SizeHorCursor))
                self._tcursor = None
                if have_focus:
                    app.status('Move focus time interval with fixed length.')
                else:
                    app.status('Move global time interval with fixed length.')

            self.update()
            self.tcursorChanged.emit()
