
# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import os
import platform
import matplotlib
import logging

from pyrocko import config

logger = logging.getLogger('pyrocko.gui.qt_compat')

# Needed by MacOS Big Sur
# https://stackoverflow.com/questions/64833558/apps-not-popping-up-on-macos-big-sur-11-0-1#_=
if platform.uname()[0] == 'Darwin':
    os.environ['QT_MAC_WANTS_LAYER'] = '1'

gui_toolkit = config.effective_gui_toolkit()

if gui_toolkit == 'qt4':
    raise Exception(
        'Pyrocko has dropped support for Qt4. The last release with Qt4 '
        'support was v2021.09.14.')

qt5_backend_available = 'Qt5Agg' in matplotlib.rcsetup.all_backends

if not qt5_backend_available:
    logger.warn(
        'Matplotlib Qt5Agg backend is not available. Snufflings drawing '
        'matplotlib figures may not work properly.')

if matplotlib.get_backend().find('Qt4') != -1:
    matplotlib.use('Qt5Agg')

import PyQt5 as PyQt
from PyQt5 import Qt
from PyQt5 import QtCore as qc
from PyQt5 import QtGui as qg
from PyQt5 import QtWidgets as qw
from PyQt5 import QtNetwork as qn
from PyQt5 import QtSvg as qsvg
from PyQt5 import QtPrintSupport as qprint

def getSaveFileName(*args, **kwargs):
     return qw.QFileDialog.getSaveFileName(*args, **kwargs)[0]

class QPixmapCache(qg.QPixmapCache):
    def cached(self, key):
        return self.find(key)

try:
    vers = qc.QVersionNumber.fromString
except AttributeError:
    def vers(s):
        return tuple(s.split('.'))

# Application attribute has to be set for QWebView
if vers(Qt.QT_VERSION_STR) >= vers('5.4.0'):
    Qt.QCoreApplication.setAttribute(qc.Qt.AA_ShareOpenGLContexts, True)


def fnpatch(x):
    if use_pyqt5:
        return x
    else:
        return x, None


