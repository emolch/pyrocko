import unittest
import gc
from .. import common
from pyrocko import guts

have_gui = common.have_gui()

if have_gui:
    from PyQt5.QtTest import QTest
    from pyrocko.gui.qt_compat import qc
    from pyrocko.gui import util as gui_util
    from pyrocko.gui.sparrow.main import SparrowViewer

    Qt = qc.Qt


@common.require_gui
class SparrowTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        '''
        Create a reusable snuffler instance for all tests cases.
        '''
        super(SparrowTest, cls).setUpClass()

        app = gui_util.get_app()
        app.set_main_window(None)
        cls.viewer = SparrowViewer(instant_close=True)
        app.set_main_window(cls.viewer)

        QTest.qWaitForWindowActive(cls.viewer)
        cls.initial_state = guts.clone(cls.viewer.state)

    @classmethod
    def tearDownClass(cls):
        '''
        Quit sparrow.
        '''
        super(SparrowTest, cls).tearDownClass()

        from pyrocko.gui.sparrow import common as sparrow_common

        gui_util.app.closeAllWindows()
        sparrow_common.release_viewer()

        del cls.viewer

        gc.collect()

    def setUp(self):
        '''
        reset GUI
        '''

        self.viewer.set_state(self.initial_state)

    def tearDown(self):
        pass

    @classmethod
    def get_action(cls, menu, name):
        for action in menu.actions():
            if action.text() == name:
                return action

        raise ValueError('Action not found: %s' % name)

    @classmethod
    def get_menu(cls, name):
        mbar = cls.viewer.menuBar()
        for maction in mbar.actions():
            menu = maction.menu()
            if menu:
                if maction.text() == name:
                    return menu

        raise ValueError('Menu not found: %s' % name)

    @classmethod
    def get_menu_action(cls, *names):
        names = list(names)
        menu = cls.get_menu(names.pop(0))
        while True:
            name = names.pop(0)
            action = cls.get_action(menu, name)
            if not names:
                return action

            menu = action.menu()

    @classmethod
    def trigger_all_actions(cls, menu):
        for action in menu.actions():
            action.trigger()
            QTest.qWait(10)

    @classmethod
    def press_key(cls, key):
        QTest.keyPress(cls.viewer, key)

    def test_view(self):
        self.get_menu_action('View', 'Detach').toggle()
        self.trigger_all_actions(self.get_menu_action('View', 'Size').menu())
        self.get_menu_action('View', 'Size', 'Fit Window Size')
        self.get_menu_action('View', 'Detach').toggle()
        self.trigger_all_actions(self.get_menu_action('View', 'Size').menu())
        self.get_menu_action('View', 'Size', 'Fit Window Size')

    def test_panels(self):
        self.trigger_all_actions(self.get_menu('Panels'))
        self.trigger_all_actions(self.get_menu('Panels'))

    def test_snapshots(self):
        from pyrocko.gui.sparrow import snapshots as snapshots_mod
        snapshots_ = snapshots_mod.load_snapshots(
            'https://data.pyrocko.org/testing/pyrocko/'
            'test-v0.snapshots.yaml')
        self.viewer.snapshots_panel.add_snapshots(snapshots_)
        for i in range(len(snapshots_)+1):
            self.viewer.snapshots_panel.transition_to_next_snapshot()
            self.viewer.update()
            self.viewer.renwin.Render()
            self.viewer.repaint()
            QTest.qWait(100)

    # def test_elements(self):
    #     self.trigger_all_actions(self.get_menu('Elements'))
    #
    # def test_tour(self):
    #     self.get_menu_action('Help', 'Interactive Tour').trigger()
    #     for i in range(40):
    #         self.press_key(Qt.Key_PageDown)
    #         QTest.qWait(10)
