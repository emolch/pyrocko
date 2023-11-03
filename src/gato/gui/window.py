# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from pyrocko.gui.qt_compat import qw, qc, qg
from pyrocko.gui import util as gui_util, talkie
from pyrocko.gui.talkie import TalkieConnectionOwner

from .constrainer import Constrainer, ConstraintsState
from .browser import ArrayBrowser, ArrayBrowserState
from pyrocko import gato, progress

guts_prefix = 'gato'


class GatoState(talkie.TalkieRoot):
    constraints = ConstraintsState.T(default=ConstraintsState.D())
    browser = ArrayBrowserState.T(default=ArrayBrowserState.D())


class GatoWindow(qw.QMainWindow, TalkieConnectionOwner):

    squirrel_changed = qc.pyqtSignal()

    def __init__(
            self,
            make_squirrel,
            instant_close=False):

        qw.QMainWindow.__init__(self)
        TalkieConnectionOwner.__init__(self)
        self.instant_close = instant_close
        self.setWindowTitle('Gato')

        self.squirrel = None
        self.status_viewer = None
        self.have_named_arrays_dataset = False

        self.state = GatoState()

        self.constrainer = constrainer = Constrainer(self.state.constraints)

        self.browser = browser = ArrayBrowser(self.state.browser)
        self.squirrel_changed.connect(browser.update_array_infos_later)
        self.browser.current_array_changed.connect(
            constrainer.update_current_array)

        self.setup_menubar()

        self.talkie_connect(
            constrainer.state,
            ['channels', 'tmin_effective', 'tmax_effective'],
            self.constraints_changed)

        main_layout = qw.QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(constrainer)
        main_layout.addWidget(browser, qc.Qt.AlignCenter)
        self.main_layout = main_layout

        main_frame = qw.QFrame()
        main_frame.setFrameShape(qw.QFrame.NoFrame)
        main_frame.setLayout(main_layout)

        self.setCentralWidget(main_frame)

        self.timer = qc.QTimer()
        self.timer.timeout.connect(self.periodical)
        self.timer.setInterval(1000)
        self.timer.start()
        self.status('Pyrocko Gato - Generalized Array Toolkit.')

        self.show()

        self.setup_squirrel(make_squirrel)

    def constraints_changed(self, *args):
        self.browser.update_array_infos_later()

    def get_status_viewer(self, parent):
        if self.status_viewer is None:
            self.status_viewer = progress.get_GUIStatusViewer()(parent)
            self.main_layout.addWidget(self.status_viewer._frame)

        return self.status_viewer

    def status(self, message, duration=None):
        self.statusBar().showMessage(
            message, int((duration or 0) * 1000))

    def periodical(self):
        pass

    def setup_menubar(self):
        mbar = qw.QMenuBar()
        self.setMenuBar(mbar)
        menu = mbar.addMenu('File')

        self.browser.add_menu_entries(menu)

        menu.addAction(
            'Print State',
            self.dump_state)

        menu.addAction(
            'Quit',
            self.close,
            qg.QKeySequence(qc.Qt.CTRL | qc.Qt.Key_Q)).setShortcutContext(
                qc.Qt.ApplicationShortcut)

    def dump_state(self):
        print(self.state)

    def setup_squirrel(self, make_squirrel):
        self.squirrel = make_squirrel()
        self.squirrel.get_database().add_listener(
            self._squirrel_updated)

        gui_util.call_later(self.setup_squirrel_delayed, 200)

    def add_named_arrays_dataset(self):
        if not self.have_named_arrays_dataset:
            self.squirrel.add_dataset(gato.get_named_arrays_dataset())
            gui_util.call_later(self.setup_squirrel_delayed, 200)
            self.have_named_arrays_dataset = True

    def setup_squirrel_delayed(self):
        with progress.view():
            self.squirrel.update()

    def _squirrel_updated(self, *args):
        self.squirrel_changed.emit()

    def confirm_close(self):
        ret = qw.QMessageBox.question(
            self,
            'Gato',
            'Close Gato window?',
            qw.QMessageBox.Cancel | qw.QMessageBox.Ok,
            qw.QMessageBox.Ok)

        return ret == qw.QMessageBox.Ok

    def closeEvent(self, event):
        if self.instant_close or self.confirm_close():
            self.closing = True
            event.accept()
        else:
            event.ignore()

    def is_closing(self):
        return self.closing
