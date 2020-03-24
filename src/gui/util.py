# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, print_function

import sys
import math
import time
import numpy as num
import logging

from .qt_compat import qc, qg, qw, use_pyqt5

from .marker import Marker, PhaseMarker, EventMarker  # noqa
from .marker import MarkerParseError, MarkerOneNSLCRequired  # noqa
from .marker import load_markers, save_markers  # noqa
from pyrocko import plot


if sys.version_info > (3,):
    buffer = memoryview


logger = logging.getLogger('pyrocko.gui.util')


def make_QPolygonF(xdata, ydata):
    assert len(xdata) == len(ydata)
    qpoints = qg.QPolygonF(len(ydata))
    vptr = qpoints.data()
    vptr.setsize(len(ydata)*8*2)
    aa = num.ndarray(
        shape=(len(ydata), 2),
        dtype=num.float64,
        buffer=buffer(vptr))
    aa.setflags(write=True)
    aa[:, 0] = xdata
    aa[:, 1] = ydata
    return qpoints


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
        rect = qc.QRectF(0., 0., s.width(), s.height())
        tx, ty = x, y

        if 'B' in anchor:
            ty -= rect.height()
        if 'R' in anchor:
            tx -= rect.width()
        if 'M' in anchor:
            ty -= rect.height()/2.
        if 'C' in anchor:
            tx -= rect.width()/2.

        rect.translate(tx, ty)
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
            rect.adjust(-2., 0., 2., 0.)
            p.drawRect(rect)
            p.setPen(oldpen)
            p.setBrush(oldbrush)

        else:
            if self.label_bg:
                p.fillRect(rect, self.label_bg)

        p.translate(tx, ty)
        self.text.drawContents(p)
        p.translate(-tx, -ty)


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
        ty += rect.height()/2.
    if 'C' in anchor:
        tx -= rect.width()/2.

    rect.translate(tx, ty)
    if outline:
        oldpen = p.pen()
        oldbrush = p.brush()
        p.setBrush(label_bg)
        rect.adjust(-2., 0., 2., 0.)
        p.drawRect(rect)
        p.setPen(oldpen)
        p.setBrush(oldbrush)

    else:
        p.fillRect(rect, label_bg)
    p.drawText(tx, ty, label)


def get_err_palette():
    err_palette = qg.QPalette()
    err_palette.setColor(qg.QPalette.Base, qg.QColor(255, 200, 200))
    return err_palette


class MySlider(qw.QSlider):

    def wheelEvent(self, ev):
        ev.ignore()

    def keyPressEvent(self, ev):
        ev.ignore()


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
                raise Exception("out of range")

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
            self.setStyleSheet("font-style: italic;")
        else:
            self.setStyleSheet(None)

        self.setText(t)


class ValControl(qc.QObject):

    valchange = qc.pyqtSignal(object, int)
    max_change_rate = 30  # max changes per second

    def __init__(
            self,
            low_is_none=False,
            high_is_none=False,
            low_is_zero=False,
            *args):

        qc.QObject.__init__(self, *args)

        self.lname = qw.QLabel("name")
        self.lname.setSizePolicy(
            qw.QSizePolicy(qw.QSizePolicy.Minimum, qw.QSizePolicy.Minimum))
        self.lvalue = MyValueEdit(
            low_is_none=low_is_none,
            high_is_none=high_is_none,
            low_is_zero=low_is_zero)
        self.lvalue.setFixedWidth(80)
        self.lvalue.setAlignment(qc.Qt.AlignRight)
        self.slider = MySlider(qc.Qt.Horizontal)
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

        self.type = None
        self.mute = False

        self._lastchange = None

    def widgets(self):
        return self.lname, self.lvalue, self.slider

    def s2v(self, svalue):
        if self.ma == 0 or self.mi == 0:
            return 0

        a = math.log(self.ma/self.mi) / 10000.
        value = self.mi*math.exp(a*svalue)
        if self.type is not None:
            value = self.type(value)
        return value

    def v2s(self, value):
        if self.type is not None:
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

    def set_type(self, value_type):
        self.type = value_type

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
        if self._lastchange:
            t = time.time()
            dt = t - self._lastchange
            if dt < 1./self.max_change_rate:
                return
            self._lastchange = t

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
        if self.type is not None:
            value = self.type(value)
        return value

    def v2s(self, value):
        if self.type is not None:
            value = self.type(value)
        if self.ma == self.mi:
            return 0
        return int(round((value-self.mi)/(self.ma-self.mi) * 10000.))


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
        now = time.time()
        if name not in self.start_times:
            self.start_times[name] = now
            return False
        else:
            if now < self.start_times[name] + 1.0:
                return False

        self.start_times.get(name, 0.0)
        value = int(round(value))
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

    def __init__(self, parent=None):
        qw.QFrame.__init__(self, parent)

        # bgrgb = self.palette().color(qw.QPalette.Window).getRgb()[:3]
        fgcolor = plot.tango_colors['aluminium5']
        dpi = 0.5*(self.logicalDpiX() + self.logicalDpiY())

        font = qg.QFont()
        font.setBold(True)
        fontsize = font.pointSize()

        import matplotlib
        matplotlib.rcdefaults()
        if use_pyqt5:
            try:
                matplotlib.rcParams['backend'] = 'Qt5Agg'
            except ValueError:
                matplotlib.rcParams['backend'] = 'Qt4Agg'
        else:
            matplotlib.rcParams['backend'] = 'Qt4Agg'

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

        from matplotlib.figure import Figure

        if use_pyqt5:
            from matplotlib.backends.backend_qt5agg import \
                NavigationToolbar2QT as NavigationToolbar

            from matplotlib.backends.backend_qt5agg \
                import FigureCanvasQTAgg as FigureCanvas
        else:
            try:
                from matplotlib.backends.backend_qt4agg import \
                    NavigationToolbar2QTAgg as NavigationToolbar
            except ImportError:
                from matplotlib.backends.backend_qt4agg import \
                    NavigationToolbar2QT as NavigationToolbar

            from matplotlib.backends.backend_qt4agg \
                import FigureCanvasQTAgg as FigureCanvas

        layout = qw.QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.setLayout(layout)
        self.figure = Figure(dpi=dpi)
        self.canvas = FigureCanvas(self.figure)
        self.canvas.setParent(self)
        self.toolbar = NavigationToolbar(self.canvas, self)
        layout.addWidget(self.toolbar, 0, 0)
        layout.addWidget(self.canvas, 1, 0)
        self.closed = False

    def gca(self):
        axes = self.figure.gca()
        beautify_axes(axes)
        return axes

    def gcf(self):
        return self.figure

    def draw(self):
        '''Draw with AGG, then queue for Qt update.'''
        self.canvas.draw()

    def closeEvent(self, ev):
        self.closed = True


class WebKitFrame(qw.QFrame):

    def __init__(self, url=None, parent=None):
        if use_pyqt5:
            try:
                from PyQt5.QtWebEngineWidgets import QWebEngineView as WebView
            except (ImportError):
                from PyQt5.QtWebKitWidgets import QWebView as WebView

        else:
            from PyQt4.QtWebKit import QWebView as WebView

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
        from vtk.qt4.QVTKRenderWindowInteractor import \
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
