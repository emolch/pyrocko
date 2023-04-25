import unittest
from .. import common
import tempfile
import os
import platform
import gc

import numpy as num

from pyrocko import util, model
from pyrocko.pile import make_pile
from pyrocko import config, trace

if common.have_gui():  # noqa
    from pyrocko.gui.qt_compat import qc, qw
    from PyQt5.QtTest import QTest
    Qt = qc.Qt

    from pyrocko.gui.snuffler.snuffler_app import SnufflerWindow
    from pyrocko.gui.snuffler import pile_viewer as pyrocko_pile_viewer
    from pyrocko.gui import util as gui_util
    from pyrocko.gui.snuffler import snuffling

    class DummySnuffling(snuffling.Snuffling):

        def setup(self):
            self.set_name('DummySnuffling')

        def call(self):
            figframe = self.figure_frame()
            ax = figframe.gca()
            ax.plot([0, 1], [0, 1])
            figframe.draw()

            self.enable_pile_changed_notifications()

            self.pixmap_frame()
            # try:
            #     self.web_frame()
            # except ImportError as e:
            #     raise unittest.SkipTest(str(e))

            self.get_pile()

    no_gui = False
else:
    no_gui = True


@common.require_gui
class SnufflerTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        '''
        Create a reusable snuffler instance for all tests cases.
        '''
        super(SnufflerTest, cls).setUpClass()
        if no_gui:  # nosetests runs this even when class is has @skip
            return

        from pyrocko.gui import util as gui_util

        cls.app = gui_util.get_app()

        fpath = common.test_data_file('test2.mseed')
        p = make_pile(fpath, show_progress=False)
        cls.win = SnufflerWindow(pile=p, instant_close=True)
        cls.app.set_main_window(cls.win)
        cls.pile_viewer = cls.win.pile_viewer
        cls.viewer = cls.win.pile_viewer.viewer
        pv = cls.pile_viewer
        cls.main_control_defaults = dict(
            highpass_control=pv.highpass_control.get_value(),
            lowpass_control=pv.lowpass_control.get_value(),
            gain_control=pv.gain_control.get_value(),
            rot_control=pv.rot_control.get_value())

    @classmethod
    def tearDownClass(cls):
        '''
        Quit snuffler.
        '''
        if no_gui:  # nosetests runs this even when class is has @skip
            return

        cls.app.closeAllWindows()
        del cls.win
        del cls.pile_viewer
        del cls.viewer
        gc.collect()

    def setUp(self):
        '''
        reset GUI
        '''
        for k, v in self.main_control_defaults.items():
            getattr(self.pile_viewer, k).set_value(v)

        self.initial_trange = self.viewer.get_time_range()
        self.viewer.set_tracks_range(
            [0, self.viewer.ntracks_shown_max])
        self.tempfiles = []

    def tearDown(self):
        self.clear_all_markers()
        for tempfn in self.tempfiles:
            os.remove(tempfn)

        self.viewer.set_time_range(*self.initial_trange)

    def get_tempfile(self):
        fh, tempfn = tempfile.mkstemp()
        os.close(fh)
        self.tempfiles.append(tempfn)
        return tempfn

    def write_to_input_line(self, text):
        '''emulate writing to inputline and press return'''
        pv = self.pile_viewer
        il = pv.inputline
        QTest.keyPress(pv, ':')
        QTest.keyClicks(il, text)
        QTest.keyPress(il, Qt.Key_Return)

    def clear_all_markers(self):
        pv = self.pile_viewer
        QTest.keyPress(pv, 'A', Qt.ShiftModifier, 10)
        QTest.keyPress(pv, Qt.Key_Backspace)
        self.assertEqual(len(pv.viewer.get_markers()), 0)

    def trigger_menu_item(self, qmenu, action_text, dialog=False):
        ''' trigger a QMenu QAction with action_text. '''

        for iaction, action in enumerate(qmenu.actions()):
            if action.text() == action_text:

                if dialog:
                    def closeDialog():
                        dlg = self.snuffler.activeModalWidget()
                        QTest.keyClick(dlg, Qt.Key_Escape)

                    qc.QTimer.singleShot(150, closeDialog)

                action.trigger()
                break

    def get_slider_position(self, slider):
        style = slider.style()
        opt = qw.QStyleOptionSlider()
        return style.subControlRect(
            qw.QStyle.CC_Slider, opt, qw.QStyle.SC_SliderHandle, slider)

    def drag_slider(self, slider):
        ''' Click *slider*, drag from one side to the other, release mouse
        button repeat to restore inital state'''
        position = self.get_slider_position(slider)
        QTest.mouseMove(slider, pos=position.topLeft())
        QTest.mousePress(slider, Qt.LeftButton)
        QTest.mouseMove(slider, pos=position.bottomRight())
        QTest.mouseRelease(slider, Qt.LeftButton)
        QTest.mousePress(slider, Qt.LeftButton)
        QTest.mouseMove(slider, pos=position.topLeft())
        QTest.mouseRelease(slider, Qt.LeftButton)

    def add_one_pick(self):
        '''Add a single pick to pile_viewer'''
        pv = self.pile_viewer
        QTest.mouseDClick(pv.viewer, Qt.LeftButton)
        position_tl = pv.pos()
        geom = pv.frameGeometry()
        QTest.mouseMove(pv.viewer, pos=position_tl)
        QTest.mouseMove(pv.viewer, pos=(qc.QPoint(
            position_tl.x()+geom.x() // 2, position_tl.y()+geom.y() // 2)))

        # This should be done also by mouseDClick().
        QTest.mouseRelease(pv.viewer, Qt.LeftButton)
        QTest.mouseClick(pv.viewer, Qt.LeftButton)

    def test_main_control_sliders(self):
        self.drag_slider(self.pile_viewer.highpass_control.slider)
        self.drag_slider(self.pile_viewer.lowpass_control.slider)
        self.drag_slider(self.pile_viewer.gain_control.slider)
        self.drag_slider(self.pile_viewer.rot_control.slider)

    def test_inputline(self):
        initrange = self.viewer.shown_tracks_range

        self.write_to_input_line('hide W.X.Y.Z')
        self.write_to_input_line('unhide W.X.Y.Z')
        self.pile_viewer.update()

        self.write_to_input_line('hide *')
        self.pile_viewer.update()

        assert self.viewer.shown_tracks_range == (0, 1)
        self.write_to_input_line('unhide')

        assert self.viewer.shown_tracks_range == initrange

        self.write_to_input_line('markers')
        self.write_to_input_line('markers 4')
        self.write_to_input_line('markers all')

        # should error
        self.write_to_input_line('scaling 1000.')
        self.write_to_input_line('scaling -1000. 1000.')

        gotos = ['2015-01-01 00:00:00',
                 '2015-01-01 00:00',
                 '2015-01-01 00',
                 '2015-01-01',
                 '2015-01',
                 '2015']

        for gt in gotos:
            self.write_to_input_line('goto %s' % gt)

        # test some false input
        self.write_to_input_line('asdf')
        QTest.keyPress(self.pile_viewer.inputline, Qt.Key_Escape)

    def test_drawing_optimization(self):
        n = 505
        lats = num.random.uniform(-90., 90., n)
        lons = num.random.uniform(-180., 180., n)
        events = []
        for i, (lat, lon) in enumerate(zip(lats, lons)):
            events.append(
                model.Event(time=i, lat=lat, lon=lon, name='XXXX%s' % i))

        self.viewer.add_event(events[-1])
        assert len(self.viewer.markers) == 1
        self.viewer.add_events(events)
        assert len(self.viewer.markers) == n + 1

        self.viewer.set_time_range(-500., 5000)
        self.viewer.set_time_range(0., None)
        self.viewer.set_time_range(None, 0.)

    def test_follow(self):
        self.viewer.follow(10.)
        self.viewer.unfollow()

    def test_save_image(self):
        tempfn_svg = self.get_tempfile() + '.svg'
        self.viewer.savesvg(fn=tempfn_svg)

        tempfn_png = self.get_tempfile() + '.png'
        self.viewer.savesvg(fn=tempfn_png)

    def test_read_events(self):
        event = model.Event()
        tempfn = self.get_tempfile()
        model.event.dump_events([event], tempfn)
        self.viewer.read_events(tempfn)

    def test_add_remove_stations(self):
        n = 10
        lats = num.random.uniform(-90., 90., n)
        lons = num.random.uniform(-180., 180., n)
        stations = [
            model.station.Station(network=str(i), station=str(i),
                                  lat=lat, lon=lon) for i, (lat, lon) in
            enumerate(zip(lats, lons))
        ]
        tempfn = self.get_tempfile()
        model.station.dump_stations(stations, tempfn)
        self.viewer.open_stations(fns=[tempfn])
        last = stations[-1]
        self.assertTrue(self.viewer.has_station(last))
        self.viewer.get_station((last.network, last.station))

    def test_markers(self):
        self.add_one_pick()
        pv = self.pile_viewer
        self.assertEqual(pv.viewer.get_active_event(), None)

        conf = config.config('snuffler')

        # test kinds and phases
        kinds = range(5)
        fkey_map = pyrocko_pile_viewer.fkey_map

        for k in kinds:
            for fkey, fkey_int in fkey_map.items():
                fkey_int += 1
                QTest.keyPress(pv, fkey)
                QTest.keyPress(pv, str(k))

                if fkey_int != 10:
                    want = conf.phase_key_mapping.get(
                        'F%s' % fkey_int, 'Undefined')
                else:
                    want = None
                m = pv.viewer.get_markers()[0]
                self.assertEqual(m.kind, k)
                if want:
                    self.assertEqual(m.get_phasename(), want)

    def test_load_waveforms(self):
        self.viewer.load('data', regex=r'\w+.mseed')
        self.assertFalse(self.viewer.get_pile().is_empty())

    def test_add_traces(self):
        trs = []
        for i in range(3):
            trs.append(
                trace.Trace(network=str(i), tmin=num.random.uniform(1),
                            ydata=num.random.random(100),
                            deltat=num.random.random())
            )
        self.viewer.add_traces(trs)

    def test_event_marker(self):
        pv = self.pile_viewer
        self.add_one_pick()

        # select all markers
        QTest.keyPress(pv, 'a', Qt.ShiftModifier, 100)

        # convert to EventMarker
        QTest.keyPress(pv, 'e')

        QTest.keyPress(pv, 'd')

        for m in pv.viewer.get_markers():
            self.assertTrue(isinstance(m, gui_util.EventMarker))

    def test_load_save_markers(self):
        nmarkers = 505
        times = list(map(util.to_time_float, num.arange(nmarkers)))
        markers = [gui_util.Marker(tmin=t, tmax=t,
                                   nslc_ids=[('*', '*', '*', '*'), ])
                   for t in times]

        tempfn = self.get_tempfile()
        tempfn_selected = self.get_tempfile()

        self.viewer.add_markers(markers)
        self.viewer.write_selected_markers(
            fn=tempfn_selected)
        self.viewer.write_markers(fn=tempfn)

        self.viewer.read_markers(fn=tempfn_selected)
        self.viewer.read_markers(fn=tempfn)

        for k in 'pnPN':
            QTest.keyPress(self.pile_viewer, k)

        self.viewer.go_to_time(-20., 20)
        self.pile_viewer.update()
        self.viewer.update()
        assert len(self.viewer.markers) != 0
        assert len(self.viewer.markers) == nmarkers * 2
        len_before = len(self.viewer.markers)
        self.viewer.remove_marker(
            self.viewer.markers[0])
        assert len(self.viewer.markers) == len_before-1
        self.viewer.remove_markers(self.viewer.markers)
        assert len(self.viewer.markers) == 0

    def test_actions(self):
        # Click through many menu option combinations that do not require
        # further interaction. Activate options in pairs of two.

        pv = self.pile_viewer
        tinit = pv.viewer.tmin
        tinitlen = pv.viewer.tmax - pv.viewer.tmin

        non_dialog_actions = [
            'Indivdual Scale',
            'Common Scale',
            'Common Scale per Station',
            'Common Scale per Component',
            'Scaling based on Minimum and Maximum',
            'Scaling based on Mean +- 2 x Std. Deviation',
            'Scaling based on Mean +- 4 x Std. Deviation',
            'Sort by Names',
            'Sort by Distance',
            'Sort by Azimuth',
            'Sort by Distance in 12 Azimuthal Blocks',
            'Sort by Backazimuth',
            '3D distances',
            'Subsort by Network, Station, Location, Channel',
            'Subsort by Network, Station, Channel, Location',
            'Subsort by Station, Network, Channel, Location',
            'Subsort by Location, Network, Station, Channel',
            'Subsort by Channel, Network, Station, Location',
            'Subsort by Network, Station, Channel (Grouped by Location)',
            'Subsort by Station, Network, Channel (Grouped by Location)',
        ]

        dialog_actions = [
            'Open waveform files...',
            'Open waveform directory...',
            'Open station files...',
            'Save markers...',
            'Save selected markers...',
            'Open marker file...',
            'Open event file...',
            'Save as SVG|PNG',
            ]

        options = [
            'Antialiasing',
            'Liberal Fetch Optimization',
            'Clip Traces',
            'Show Boxes',
            'Color Traces',
            'Show Scale Ranges',
            'Show Scale Axes',
            'Show Zero Lines',
            'Fix Scale Ranges',
            'Allow Downsampling',
            'Allow Degapping',
            'FFT Filtering',
            'Bandpass is Lowpass + Highpass',
            'Watch Files',
        ]

        # create an event marker and activate it
        self.add_one_pick()

        keys = list('mAhefrRh+-fgc?')
        keys.extend([Qt.Key_PageUp, Qt.Key_PageDown])

        def fire_key(x):
            QTest.keyPress(self.pile_viewer, key)

        for key in keys:
            QTest.qWait(100)
            fire_key(key)

        event = model.Event()
        markers = pv.viewer.get_markers()
        self.assertEqual(len(markers), 1)
        markers[0]._event = event

        pv.viewer.set_active_event(event)
        pv.viewer.set_event_marker_as_origin()

        right_click_menu = self.viewer.menu

        for action_text in dialog_actions:
            self.trigger_menu_item(right_click_menu, action_text, dialog=True)

        for action_text in non_dialog_actions:
            for oa in options:
                for ob in options:
                    self.trigger_menu_item(right_click_menu, action_text)
                    self.trigger_menu_item(right_click_menu, oa)
                    self.trigger_menu_item(right_click_menu, ob)

                options.remove(oa)

        self.viewer.go_to_event_by_name(event.name)
        self.viewer.go_to_time(tinit, tinitlen)

    @unittest.skipIf(
        platform.system() != 'Windows' and os.getuid() == 0,
        'does not like to run as root')
    def test_frames(self):
        frame_snuffling = DummySnuffling()

        self.viewer.add_snuffling(frame_snuffling)
        frame_snuffling.call()

        # close three opened frames
        QTest.keyPress(self.pile_viewer, 'd')
        QTest.keyPress(self.pile_viewer, 'd')
        QTest.keyPress(self.pile_viewer, 'd')
