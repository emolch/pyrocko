# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Effective seismological trace viewer.
'''

import sys
import logging
import time
import re
import zlib
import struct
import pickle
try:
    from urlparse import parse_qsl
except ImportError:
    from urllib.parse import parse_qsl

from pyrocko.streaming import serial_hamster
from pyrocko.streaming import slink
from pyrocko.streaming import edl
from pyrocko.streaming import datacube

from pyrocko import pile            # noqa
from pyrocko import util            # noqa
from pyrocko import model           # noqa
from pyrocko import config          # noqa
from pyrocko import io              # noqa
from pyrocko.gui import util as gui_util

from . import pile_viewer     # noqa

from ..qt_compat import qc, qg, qw

logger = logging.getLogger('pyrocko.gui.snuffler.snuffler_app')


class AcquisitionThread(qc.QThread):
    def __init__(self, post_process_sleep=0.0):
        qc.QThread.__init__(self)
        self.mutex = qc.QMutex()
        self.queue = []
        self.post_process_sleep = post_process_sleep
        self._sun_is_shining = True

    def get_wanted_poll_interval(self):
        return 1000.

    def run(self):
        while True:
            try:
                self.acquisition_start()
                while self._sun_is_shining:
                    t0 = time.time()
                    self.process()
                    t1 = time.time()
                    if self.post_process_sleep != 0.0:
                        time.sleep(max(0, self.post_process_sleep-(t1-t0)))

                self.acquisition_stop()
                break

            except (
                    edl.ReadError,
                    serial_hamster.SerialHamsterError,
                    slink.SlowSlinkError) as e:

                logger.error(str(e))
                logger.error('Acquistion terminated, restart in 5 s')
                self.acquisition_stop()
                time.sleep(5)
                if not self._sun_is_shining:
                    break

            except Exception:
                self.acquisition_stop()
                raise

    def stop(self):
        self._sun_is_shining = False

        logger.debug('Waiting for thread to terminate...')
        self.wait()
        logger.debug('Thread has terminated.')

    def got_trace(self, tr):
        self.mutex.lock()
        self.queue.append(tr)
        self.mutex.unlock()

    def poll(self):
        self.mutex.lock()
        items = self.queue[:]
        self.queue[:] = []
        self.mutex.unlock()
        return items


class SlinkAcquisition(
        slink.SlowSlink, AcquisitionThread):

    def __init__(self, *args, **kwargs):
        slink.SlowSlink.__init__(self, *args, **kwargs)
        AcquisitionThread.__init__(self)

    def got_trace(self, tr):
        AcquisitionThread.got_trace(self, tr)


class CamAcquisition(
        serial_hamster.CamSerialHamster, AcquisitionThread):

    def __init__(self, *args, **kwargs):
        serial_hamster.CamSerialHamster.__init__(self, *args, **kwargs)
        AcquisitionThread.__init__(self, post_process_sleep=0.1)

    def got_trace(self, tr):
        AcquisitionThread.got_trace(self, tr)


class USBHB628Acquisition(
        serial_hamster.USBHB628Hamster, AcquisitionThread):

    def __init__(self, deltat=0.02, *args, **kwargs):
        serial_hamster.USBHB628Hamster.__init__(
            self, deltat=deltat, *args, **kwargs)
        AcquisitionThread.__init__(self)

    def got_trace(self, tr):
        AcquisitionThread.got_trace(self, tr)


class SchoolSeismometerAcquisition(
        serial_hamster.SerialHamster, AcquisitionThread):

    def __init__(self, *args, **kwargs):
        serial_hamster.SerialHamster.__init__(self, *args, **kwargs)
        AcquisitionThread.__init__(self, post_process_sleep=0.0)

    def got_trace(self, tr):
        AcquisitionThread.got_trace(self, tr)

    def get_wanted_poll_interval(self):
        return 100.


class EDLAcquisition(
        edl.EDLHamster, AcquisitionThread):

    def __init__(self, *args, **kwargs):
        edl.EDLHamster.__init__(self, *args, **kwargs)
        AcquisitionThread.__init__(self)

    def got_trace(self, tr):
        AcquisitionThread.got_trace(self, tr)


class CubeAcquisition(
        datacube.SerialCube, AcquisitionThread):

    def __init__(self, *args, **kwargs):
        datacube.SerialCube.__init__(self, *args, **kwargs)
        AcquisitionThread.__init__(self)

    def got_trace(self, tr):
        AcquisitionThread.got_trace(self, tr)


def setup_acquisition_sources(args):

    sources = []
    iarg = 0
    while iarg < len(args):
        arg = args[iarg]

        msl = re.match(r'seedlink://([a-zA-Z0-9.-]+)(:(\d+))?(/(.*))?', arg)
        mca = re.match(r'cam://([^:]+)', arg)
        mus = re.match(r'hb628://([^:?]+)(\?([^?]+))?', arg)
        msc = re.match(r'school://([^:?]+)(\?([^?]+))?', arg)
        med = re.match(r'edl://([^:]+)', arg)
        mcu = re.match(r'cube://([^:]+)', arg)

        if msl:
            host = msl.group(1)
            port = msl.group(3)
            if not port:
                port = '18000'

            sl = SlinkAcquisition(host=host, port=port)
            if msl.group(5):
                stream_patterns = msl.group(5).split(',')

                if '_' not in msl.group(5):
                    try:
                        streams = sl.query_streams()
                    except slink.SlowSlinkError as e:
                        logger.fatal(str(e))
                        sys.exit(1)

                    streams = list(set(
                        util.match_nslcs(stream_patterns, streams)))

                    for stream in streams:
                        sl.add_stream(*stream)
                else:
                    for stream in stream_patterns:
                        sl.add_raw_stream_selector(stream)

            sources.append(sl)

        elif mca:
            port = mca.group(1)
            cam = CamAcquisition(port=port, deltat=0.0314504)
            sources.append(cam)

        elif mus:
            port = mus.group(1)
            try:
                d = {}
                if mus.group(3):
                    d = dict(parse_qsl(mus.group(3)))

                deltat = 1.0/float(d.get('rate', '50'))
                channels = [(int(c), c) for c in d.get('channels', '01234567')]
                hb628 = USBHB628Acquisition(
                    port=port,
                    deltat=deltat,
                    channels=channels,
                    buffersize=16,
                    lookback=50)

                sources.append(hb628)
            except Exception:
                sys.exit('invalid acquisition source: %s' % arg)

        elif msc:
            port = msc.group(1)

            d = {}
            if msc.group(3):
                d = dict(parse_qsl(msc.group(3)))

            d_rate = {
                '20': ('a', 20.032),
                '40': ('b', 39.860),
                '80': ('c', 79.719)}

            s_rate = d.get('rate', '80')
            station = d.get('station', 'TEST')

            if s_rate not in d_rate:
                raise Exception(
                    'Unsupported rate: %s (expected "20", "40" or "80")'
                    % s_rate)

            s_gain = d.get('gain', '4')

            if s_gain not in ('1', '2', '4'):
                raise Exception(
                    'Unsupported gain: %s (expected "1", "2" or "4")'
                    % s_gain)

            start_string = s_gain + d_rate[s_rate][0]
            deltat = 1.0 / d_rate[s_rate][1]

            logger.info(
                'School seismometer: trying to use device %s with gain=%s and '
                'rate=%g.' % (port, s_gain, 1.0/deltat))

            sco = SchoolSeismometerAcquisition(
                port=port,
                deltat=deltat,
                start_string=start_string,
                min_detection_size=50,
                disallow_uneven_sampling_rates=False,
                station=station)

            sources.append(sco)

        elif med:
            port = med.group(1)
            edl = EDLAcquisition(port=port)
            sources.append(edl)
        elif mcu:
            device = mcu.group(1)
            cube = CubeAcquisition(device=device)
            sources.append(cube)

        if msl or mca or mus or msc or med or mcu:
            args.pop(iarg)
        else:
            iarg += 1

    return sources


class PollInjector(qc.QObject):

    def __init__(self, *args, **kwargs):
        interval = kwargs.pop('interval', 1000.)
        qc.QObject.__init__(self)
        self._injector = pile.Injector(*args, **kwargs)
        self._sources = []
        self.startTimer(int(interval))

    def add_source(self, source):
        self._sources.append(source)

    def remove_source(self, source):
        self._sources.remove(source)

    def timerEvent(self, ev):
        for source in self._sources:
            trs = source.poll()
            for tr in trs:
                self._injector.inject(tr)

    # following methods needed because mulitple inheritance does not seem
    # to work anymore with QObject in Python3 or PyQt5

    def set_fixation_length(self, length):
        return self._injector.set_fixation_length(length)

    def set_save_path(
            self,
            path='dump_%(network)s.%(station)s.%(location)s.%(channel)s_'
                 '%(tmin)s_%(tmax)s.mseed'):

        return self._injector.set_save_path(path)

    def fixate_all(self):
        return self._injector.fixate_all()

    def free(self):
        return self._injector.free()


class Connection(qc.QObject):

    received = qc.pyqtSignal(object, object)
    disconnected = qc.pyqtSignal(object)

    def __init__(self, parent, sock):
        qc.QObject.__init__(self, parent)
        self.socket = sock
        self.readyRead.connect(
            self.handle_read)
        self.disconnected.connect(
            self.handle_disconnected)
        self.nwanted = 8
        self.reading_size = True
        self.handler = None
        self.nbytes_received = 0
        self.nbytes_sent = 0
        self.compressor = zlib.compressobj()
        self.decompressor = zlib.decompressobj()

    def handle_read(self):
        while True:
            navail = self.socket.bytesAvailable()
            if navail < self.nwanted:
                return

            data = self.socket.read(self.nwanted)
            self.nbytes_received += len(data)
            if self.reading_size:
                self.nwanted = struct.unpack('>Q', data)[0]
                self.reading_size = False
            else:
                obj = pickle.loads(self.decompressor.decompress(data))
                if obj is None:
                    self.socket.disconnectFromHost()
                else:
                    self.handle_received(obj)
                self.nwanted = 8
                self.reading_size = True

    def handle_received(self, obj):
        self.received.emit(self, obj)

    def ship(self, obj):
        data = self.compressor.compress(pickle.dumps(obj))
        data_end = self.compressor.flush(zlib.Z_FULL_FLUSH)
        self.socket.write(struct.pack('>Q', len(data)+len(data_end)))
        self.socket.write(data)
        self.socket.write(data_end)
        self.nbytes_sent += len(data)+len(data_end) + 8

    def handle_disconnected(self):
        self.disconnected.emit(self)

    def close(self):
        self.socket.close()


class ConnectionHandler(qc.QObject):
    def __init__(self, parent):
        qc.QObject.__init__(self, parent)
        self.queue = []
        self.connection = None

    def connected(self):
        return self.connection is None

    def set_connection(self, connection):
        self.connection = connection
        connection.received.connect(
            self._handle_received)

        connection.connect(
            self.handle_disconnected)

        for obj in self.queue:
            self.connection.ship(obj)

        self.queue = []

    def _handle_received(self, conn, obj):
        self.handle_received(obj)

    def handle_received(self, obj):
        pass

    def handle_disconnected(self):
        self.connection = None

    def ship(self, obj):
        if self.connection:
            self.connection.ship(obj)
        else:
            self.queue.append(obj)


class SimpleConnectionHandler(ConnectionHandler):
    def __init__(self, parent, **mapping):
        ConnectionHandler.__init__(self, parent)
        self.mapping = mapping

    def handle_received(self, obj):
        command = obj[0]
        args = obj[1:]
        self.mapping[command](*args)


class MyMainWindow(qw.QMainWindow):

    def __init__(self, app, *args):
        qg.QMainWindow.__init__(self, *args)
        self.app = app

    def keyPressEvent(self, ev):
        self.app.pile_viewer.get_view().keyPressEvent(ev)


class SnufflerTabs(qw.QTabWidget):
    def __init__(self, parent):
        qw.QTabWidget.__init__(self, parent)
        if hasattr(self, 'setTabsClosable'):
            self.setTabsClosable(True)

        self.tabCloseRequested.connect(
            self.removeTab)

        if hasattr(self, 'setDocumentMode'):
            self.setDocumentMode(True)

    def hide_close_button_on_first_tab(self):
        tbar = self.tabBar()
        if hasattr(tbar, 'setTabButton'):
            tbar.setTabButton(0, qw.QTabBar.LeftSide, None)
            tbar.setTabButton(0, qw.QTabBar.RightSide, None)

    def append_tab(self, widget, name):
        widget.setParent(self)
        self.insertTab(self.count(), widget, name)
        self.setCurrentIndex(self.count()-1)

    def remove_tab(self, widget):
        self.removeTab(self.indexOf(widget))

    def tabInserted(self, index):
        if index == 0:
            self.hide_close_button_on_first_tab()

        self.tabbar_visibility()
        self.setFocus()

    def removeTab(self, index):
        w = self.widget(index)
        w.close()
        qw.QTabWidget.removeTab(self, index)

    def tabRemoved(self, index):
        self.tabbar_visibility()

    def tabbar_visibility(self):
        if self.count() <= 1:
            self.tabBar().hide()
        elif self.count() > 1:
            self.tabBar().show()

    def keyPressEvent(self, event):
        if event.text() == 'd':
            i = self.currentIndex()
            if i != 0:
                self.tabCloseRequested.emit(i)
        else:
            self.parent().keyPressEvent(event)


class SnufflerStartWizard(qw.QWizard):

    def __init__(self, parent):
        qw.QWizard.__init__(self, parent)

        self.setOption(self.NoBackButtonOnStartPage)
        self.setOption(self.NoBackButtonOnLastPage)
        self.setOption(self.NoCancelButton)
        self.addPageSurvey()
        self.addPageHelp()
        self.setWindowTitle('Welcome to Pyrocko')

    def getSystemInfo(self):
        import numpy
        import scipy
        import pyrocko
        import platform
        import uuid
        data = {
            'node-uuid': uuid.getnode(),
            'platform.architecture': platform.architecture(),
            'platform.system': platform.system(),
            'platform.release': platform.release(),
            'python': platform.python_version(),
            'pyrocko': pyrocko.__version__,
            'numpy': numpy.__version__,
            'scipy': scipy.__version__,
            'qt': qc.PYQT_VERSION_STR,
        }
        return data

    def addPageSurvey(self):
        import pprint
        webtk = 'DSFGK234ADF4ASDF'
        sys_info = self.getSystemInfo()

        p = qw.QWizardPage()
        p.setCommitPage(True)
        p.setTitle('Thank you for installing Pyrocko!')

        lyt = qw.QVBoxLayout()
        lyt.addWidget(qw.QLabel(
            '<p>Your feedback is important for'
            ' the development and improvement of Pyrocko.</p>'
            '<p>Do you want to send this system information anon'
            'ymously to <a href="https://pyrocko.org">'
            'https://pyrocko.org</a>?</p>'))

        text_data = qw.QLabel(
            '<code style="font-size: small;">%s</code>' %
            pprint.pformat(
                sys_info,
                indent=1).replace('\n', '<br>')
            )
        text_data.setStyleSheet('padding: 10px;')
        lyt.addWidget(text_data)

        lyt.addWidget(qw.QLabel(
            "This message won't be shown again.\n\n"
            'We appreciate your contribution!\n- The Pyrocko Developers'
            ))

        p.setLayout(lyt)
        p.setButtonText(self.CommitButton, 'No')

        yes_btn = qw.QPushButton(p)
        yes_btn.setText('Yes')

        @qc.pyqtSlot()
        def send_data():
            import requests
            import json
            try:
                requests.post('https://pyrocko.org/%s' % webtk,
                              data=json.dumps(sys_info))
            except Exception as e:
                print(e)
            self.button(self.NextButton).clicked.emit(True)

        self.customButtonClicked.connect(send_data)

        self.setButton(self.CustomButton1, yes_btn)
        self.setOption(self.HaveCustomButton1, True)

        self.addPage(p)
        return p

    def addPageHelp(self):
        p = qw.QWizardPage()
        p.setTitle('Welcome to Snuffler!')

        text = qw.QLabel('''<html>
<h3>- <i>The Seismogram browser and workbench.</i></h3>
<p>Looks like you are starting the Snuffler for the first time.<br>
It allows you to browse and process large archives of waveform data.</p>
<p>Basic processing is complemented by Snufflings (<i>Plugins</i>):</p>
<ul>
    <li><b>Download seismograms</b> from GEOFON IRIS and others</li>
    <li><b>Earthquake catalog</b> access to GEOFON, GlobalCMT, USGS...</li>
    <li><b>Cake</b>, Calculate synthetic arrival times</li>
    <li><b>Seismosizer</b>, generate synthetic seismograms on-the-fly</li>
    <li>
        <b>Map</b>, swiftly inspect stations and events on interactive maps
    </li>
</ul>
<p>And more, see <a href="https://pyrocko.org/">https://pyrocko.org/</a></p>
<p><b>NOTE:</b><br>If you installed snufflings from the
<a href="https://github.com/pyrocko/contrib-snufflings">user contributed
snufflings repository</a><br>you also have to pull an update from there.
</p>
<p style="width: 100%; background-color: #e9b96e; margin: 5px; padding: 50;"
          align="center">
    <b>You can always press <code>?</code> for help!</b>
</p>
</html>''')

        lyt = qw.QVBoxLayout()
        lyt.addWidget(text)

        def remove_custom_button():
            self.setOption(self.HaveCustomButton1, False)

        p.initializePage = remove_custom_button

        p.setLayout(lyt)
        self.addPage(p)
        return p


class SnufflerWindow(qw.QMainWindow):

    def __init__(
            self, pile, stations=None, events=None, markers=None, ntracks=12,
            marker_editor_sortable=True, follow=None, controls=True,
            opengl=None, instant_close=False):

        qw.QMainWindow.__init__(self)

        self.instant_close = instant_close

        self.dockwidget_to_toggler = {}
        self.dockwidgets = []

        self.setWindowTitle('Snuffler')

        self.pile_viewer = pile_viewer.PileViewer(
            pile, ntracks_shown_max=ntracks, use_opengl=opengl,
            marker_editor_sortable=marker_editor_sortable,
            panel_parent=self)

        self.marker_editor = self.pile_viewer.marker_editor()
        self.add_panel(
            'Markers', self.marker_editor, visible=False,
            where=qc.Qt.RightDockWidgetArea)
        if stations:
            self.get_view().add_stations(stations)

        if events:
            self.get_view().add_events(events)

            if len(events) == 1:
                self.get_view().set_active_event(events[0])

        if markers:
            self.get_view().add_markers(markers)
            self.get_view().associate_phases_to_events()

        self.tabs = SnufflerTabs(self)
        self.setCentralWidget(self.tabs)
        self.add_tab('Main', self.pile_viewer)

        self.pile_viewer.setup_snufflings()
        self.setMenuBar(self.pile_viewer.menu)

        self.main_controls = self.pile_viewer.controls()
        self.add_panel('Main Controls', self.main_controls, visible=controls)
        self.show()

        self.get_view().setFocus(qc.Qt.OtherFocusReason)

        self.status_messages = gui_util.StatusMessages()
        self.statusBar().addPermanentWidget(self.status_messages)

        self.status_messages.set(
                'welcome', 'Welcome to Snuffler! Press ? for help.')

        snuffler_config = self.pile_viewer.viewer.config

        if snuffler_config.first_start:
            wizard = SnufflerStartWizard(self)

            @qc.pyqtSlot()
            def wizard_finished(result):
                if result == wizard.Accepted:
                    snuffler_config.first_start = False
                    config.write_config(snuffler_config, 'snuffler')

            wizard.finished.connect(wizard_finished)

            wizard.show()

        if follow:
            self.get_view().follow(float(follow))

        self.closing = False

    def sizeHint(self):
        return qc.QSize(1024, 768)
        # return qc.QSize(800, 600) # used for screen shots in tutorial

    def keyPressEvent(self, ev):
        self.get_view().keyPressEvent(ev)

    def get_view(self):
        return self.pile_viewer.get_view()

    def get_panel_parent_widget(self):
        return self

    def add_tab(self, name, widget):
        self.tabs.append_tab(widget, name)

    def remove_tab(self, widget):
        self.tabs.remove_tab(widget)

    def add_panel(self, name, panel, visible=False, volatile=False,
                  where=qc.Qt.BottomDockWidgetArea):

        if not self.dockwidgets:
            self.dockwidgets = []

        dws = [x for x in self.dockwidgets if self.dockWidgetArea(x) == where]

        dockwidget = qw.QDockWidget(name, self)
        self.dockwidgets.append(dockwidget)
        dockwidget.setWidget(panel)
        panel.setParent(dockwidget)
        self.addDockWidget(where, dockwidget)

        if dws:
            self.tabifyDockWidget(dws[-1], dockwidget)

        self.toggle_panel(dockwidget, visible)

        mitem = qw.QAction(name, None)

        def toggle_panel(checked):
            self.toggle_panel(dockwidget, True)

        mitem.triggered.connect(toggle_panel)

        if volatile:
            def visibility(visible):
                if not visible:
                    self.remove_panel(panel)

            dockwidget.visibilityChanged.connect(
                visibility)

        self.get_view().add_panel_toggler(mitem)
        self.dockwidget_to_toggler[dockwidget] = mitem

        if pile_viewer.is_macos:
            tabbars = self.findChildren(qw.QTabBar)
            for tabbar in tabbars:
                tabbar.setShape(qw.QTabBar.TriangularNorth)
                tabbar.setDocumentMode(True)

    def toggle_panel(self, dockwidget, visible):
        if visible is None:
            visible = not dockwidget.isVisible()

        dockwidget.setVisible(visible)
        if visible:
            w = dockwidget.widget()
            minsize = w.minimumSize()
            w.setMinimumHeight(w.sizeHint().height() + 5)

            def reset_minimum_size():
                import sip
                if not sip.isdeleted(w):
                    w.setMinimumSize(minsize)

            qc.QTimer.singleShot(200, reset_minimum_size)

            dockwidget.setFocus()
            dockwidget.raise_()

    def toggle_marker_editor(self):
        self.toggle_panel(self.marker_editor.parent(), None)

    def toggle_main_controls(self):
        self.toggle_panel(self.main_controls.parent(), None)

    def remove_panel(self, panel):
        dockwidget = panel.parent()
        self.removeDockWidget(dockwidget)
        dockwidget.setParent(None)
        mitem = self.dockwidget_to_toggler[dockwidget]
        self.get_view().remove_panel_toggler(mitem)

    def return_tag(self):
        return self.get_view().return_tag

    def confirm_close(self):
        ret = qw.QMessageBox.question(
            self,
            'Snuffler',
            'Close Snuffler window?',
            qw.QMessageBox.Cancel | qw.QMessageBox.Ok,
            qw.QMessageBox.Ok)

        return ret == qw.QMessageBox.Ok

    def closeEvent(self, event):
        if self.instant_close or self.confirm_close():
            self.closing = True
            self.pile_viewer.cleanup()
            event.accept()
        else:
            event.ignore()

    def is_closing(self):
        return self.closing
