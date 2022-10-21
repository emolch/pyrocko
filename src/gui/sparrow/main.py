# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import math
import sys
import signal
import gc
import logging
import time
import tempfile
import os
import shutil
import platform
from subprocess import check_call

import numpy as num

from pyrocko import cake
from pyrocko import guts
from pyrocko import geonames
from pyrocko import moment_tensor as pmt

from pyrocko.gui.util import Progressbars, RangeEdit
from pyrocko.gui.qt_compat import qw, qc, qg
# from pyrocko.gui import vtk_util

from . import common, light, snapshots as snapshots_mod

import vtk
import vtk.qt
vtk.qt.QVTKRWIBase = 'QGLWidget'  # noqa

from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor  # noqa

from pyrocko import geometry  # noqa
from . import state as vstate, elements  # noqa

logger = logging.getLogger('pyrocko.gui.sparrow.main')


d2r = num.pi/180.
km = 1000.

if platform.uname()[0] == 'Darwin':
    g_modifier_key = '\u2318'
else:
    g_modifier_key = 'Ctrl'


class ZeroFrame(qw.QFrame):

    def sizeHint(self):
        return qc.QSize(0, 0)


def get_app():
    global app
    return app


class LocationChoice(object):
    def __init__(self, name, lat, lon, depth=0):
        self._name = name
        self._lat = lat
        self._lon = lon
        self._depth = depth

    def get_lat_lon_depth(self):
        return self._lat, self._lon, self._depth


def location_to_choices(s):
    choices = []
    s_vals = s.replace(',', ' ')
    try:
        vals = [float(x) for x in s_vals.split()]
        if len(vals) == 3:
            vals[2] *= km

        choices.append(LocationChoice('', *vals))

    except ValueError:
        cities = geonames.get_cities_by_name(s.strip())
        for c in cities:
            choices.append(LocationChoice(c.asciiname, c.lat, c.lon))

    return choices


class NoLocationChoices(Exception):

    def __init__(self, s):
        self._string = s

    def __str__(self):
        return 'No location choices for string "%s"' % self._string


class QVTKWidget(QVTKRenderWindowInteractor):
    def __init__(self, parent, *args):
        QVTKRenderWindowInteractor.__init__(self, *args)
        self._parent = parent

    def wheelEvent(self, event):
        self._parent.myWheelEvent(event)


class MyDockWidgetTitleBar(qw.QLabel):

    def event(self, ev):
        ev.ignore()
        return qw.QLabel.event(self, ev)


class MyDockWidget(qw.QDockWidget):

    def __init__(self, name, parent, **kwargs):
        qw.QDockWidget.__init__(self, name, parent, **kwargs)

        self.setFeatures(
            qw.QDockWidget.DockWidgetClosable
            | qw.QDockWidget.DockWidgetMovable
            | qw.QDockWidget.DockWidgetFloatable
            | qw.QDockWidget.DockWidgetClosable)

        self._visible = False
        self._blocked = False

        lab = MyDockWidgetTitleBar('<strong>%s</strong>' % name)
        lab.setMargin(10)
        lab.setBackgroundRole(qg.QPalette.Mid)
        lab.setAutoFillBackground(True)

        self.setTitleBarWidget(lab)

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


class DetachedViewer(qw.QMainWindow):

    def __init__(self, main_window, vtk_frame):
        qw.QMainWindow.__init__(self)
        self.main_window = main_window
        self.setWindowTitle('Sparrow View')
        vtk_frame.setParent(self)
        self.setCentralWidget(vtk_frame)

    def closeEvent(self, ev):
        ev.ignore()
        self.main_window.attach()


class CenteringScrollArea(qw.QScrollArea):
    def __init__(self):
        qw.QScrollArea.__init__(self)
        self.setAlignment(qc.Qt.AlignCenter)
        self.setVerticalScrollBarPolicy(qc.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(qc.Qt.ScrollBarAlwaysOff)
        self.setWidgetResizable(True)
        self.setFrameShape(qw.QFrame.NoFrame)

    def resizeEvent(self, *args):
        retval = qw.QScrollArea.resizeEvent(self, *args)
        self.recenter()
        return retval

    def recenter(self):
        for sb in (self.verticalScrollBar(), self.horizontalScrollBar()):
            sb.setValue(int(round(0.5 * (sb.minimum() + sb.maximum()))))

    def wheelEvent(self, *args, **kwargs):
        return self.widget().wheelEvent(*args, **kwargs)


class SparrowViewer(qw.QMainWindow):
    def __init__(self, use_depth_peeling=True, events=None, snapshots=None):
        qw.QMainWindow.__init__(self)
        self.listeners = []

        self.state = vstate.ViewerState()
        self.gui_state = vstate.ViewerGuiState()

        self.setWindowTitle('Sparrow')

        self.setTabPosition(
            qc.Qt.AllDockWidgetAreas, qw.QTabWidget.West)

        self.planet_radius = cake.earthradius
        self.feature_radius_min = cake.earthradius - 1000. * km

        self._panel_togglers = {}
        self._actors = set()
        self._actors_2d = set()
        self._render_window_size = (0, 0)
        self._use_depth_peeling = use_depth_peeling
        self._in_update_elements = False

        mbar = self.menuBar()
        menu = mbar.addMenu('File')

        mitem = qw.QAction('Quit', self)
        mitem.triggered.connect(self.request_quit)
        menu.addAction(mitem)

        mitem = qw.QAction('Export Image...', self)
        mitem.triggered.connect(self.export_image)
        menu.addAction(mitem)

        menu = mbar.addMenu('View')
        self._add_vtk_widget_size_menu_entries(menu)

        self.panels_menu = mbar.addMenu('Panels')

        menu = mbar.addMenu('Add')
        for name, estate in [
                ('Icosphere', elements.IcosphereState()),
                ('Grid', elements.GridState()),
                ('Stations', elements.StationsState()),
                ('Topography', elements.TopoState()),
                ('Custom Topography', elements.CustomTopoState()),
                ('Catalog', elements.CatalogState()),
                ('Coastlines', elements.CoastlinesState()),
                ('Source', elements.SourceState()),
                ('HUD (tmax)', elements.HudState(
                    variables=['tmax'],
                    template='tmax: {0|date}',
                    position='top-left')),
                ('HUD subtitle', elements.HudState(
                    template='Awesome')),
                ('Volcanoes', elements.VolcanoesState()),
                ('Faults', elements.ActiveFaultsState()),
                ('Plate bounds', elements.PlatesBoundsState()),
                ('InSAR Surface Displacements', elements.KiteState()),
                ('Geometry', elements.GeometryState()),
                ('Spheroid', elements.SpheroidState()),
                ('Rays', elements.RaysState())]:

            def wrap_add_element(estate):
                def add_element(*args):
                    new_element = guts.clone(estate)
                    new_element.element_id = elements.random_id()
                    self.state.elements.append(new_element)
                    self.state.sort_elements()

                return add_element

            mitem = qw.QAction(name, self)

            mitem.triggered.connect(wrap_add_element(estate))

            menu.addAction(mitem)

        self.data_providers = []
        self.elements = {}

        self.detached_window = None

        main_frame = qw.QFrame()
        main_frame.setFrameShape(qw.QFrame.NoFrame)

        self.vtk_widget = QVTKWidget(self, main_frame)

        self.vtk_frame = CenteringScrollArea()
        self.vtk_frame.setWidget(self.vtk_widget)

        main_layout = qw.QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.vtk_frame, qc.Qt.AlignCenter)

        pb = Progressbars(self)
        self.progressbars = pb
        main_layout.addWidget(pb)

        main_frame.setLayout(main_layout)

        self.main_frame = main_frame
        self.main_layout = main_layout
        self.vtk_frame_substitute = None

        self.add_panel(
            'Navigation',
            self.controls_navigation(), visible=True,
            where=qc.Qt.LeftDockWidgetArea)

        self.add_panel(
            'Time',
            self.controls_time(), visible=True,
            where=qc.Qt.LeftDockWidgetArea)

        self.add_panel(
            'Appearance',
            self.controls_appearance(), visible=True,
            where=qc.Qt.LeftDockWidgetArea)

        snapshots_panel = self.controls_snapshots()
        self.add_panel(
            'Snapshots',
            snapshots_panel, visible=False,
            where=qc.Qt.LeftDockWidgetArea)

        self.setCentralWidget(self.main_frame)

        self.mesh = None

        ren = vtk.vtkRenderer()

        # ren.SetBackground(0.15, 0.15, 0.15)
        # ren.SetBackground(0.0, 0.0, 0.0)
        # ren.TwoSidedLightingOn()
        # ren.SetUseShadows(1)

        self._lighting = None
        self._background = None

        self.ren = ren
        self.update_render_settings()
        self.update_camera()

        renwin = self.vtk_widget.GetRenderWindow()

        if self._use_depth_peeling:
            renwin.SetAlphaBitPlanes(1)
            renwin.SetMultiSamples(0)

            ren.SetUseDepthPeeling(1)
            ren.SetMaximumNumberOfPeels(100)
            ren.SetOcclusionRatio(0.1)

        ren.SetUseFXAA(1)
        # ren.SetUseHiddenLineRemoval(1)
        # ren.SetBackingStore(1)

        self.renwin = renwin

        # renwin.LineSmoothingOn()
        # renwin.PointSmoothingOn()
        # renwin.PolygonSmoothingOn()

        renwin.AddRenderer(ren)

        iren = renwin.GetInteractor()
        iren.LightFollowCameraOn()
        iren.SetInteractorStyle(None)

        iren.AddObserver('LeftButtonPressEvent', self.button_event)
        iren.AddObserver('LeftButtonReleaseEvent', self.button_event)
        iren.AddObserver('MiddleButtonPressEvent', self.button_event)
        iren.AddObserver('MiddleButtonReleaseEvent', self.button_event)
        iren.AddObserver('RightButtonPressEvent', self.button_event)
        iren.AddObserver('RightButtonReleaseEvent', self.button_event)
        iren.AddObserver('MouseMoveEvent', self.mouse_move_event)
        iren.AddObserver('KeyPressEvent', self.key_down_event)
        iren.AddObserver('KeyReleaseEvent', self.key_up_event)
        iren.AddObserver('ModifiedEvent', self.check_resize)

        renwin.Render()

        iren.Initialize()

        self.iren = iren

        self.rotating = False

        self._elements = {}
        self._elements_active = {}

        update_elements = self.update_elements
        self.register_state_listener(update_elements)

        self.state.add_listener(update_elements, 'elements')
        self.state.elements.append(elements.IcosphereState(
            element_id='icosphere', level=4, smooth=True))
        self.state.elements.append(elements.GridState(
            element_id='grid'))
        self.state.elements.append(elements.CoastlinesState(
            element_id='coastlines'))

        # self.state.elements.append(elements.StationsState())
        # self.state.elements.append(elements.SourceState())
        # self.state.elements.append(
        #      elements.CatalogState(
        #     selection=elements.FileCatalogSelection(paths=['japan.dat'])))
        #     selection=elements.FileCatalogSelection(paths=['excerpt.dat'])))

        if events:
            self.state.elements.append(
                elements.CatalogState(
                    selection=elements.MemoryCatalogSelection(events=events)))

        self.state.sort_elements()

        if snapshots:
            snapshots_ = []
            for obj in snapshots:
                if isinstance(obj, str):
                    snapshots_.extend(snapshots_mod.load_snapshots(obj))
                else:
                    snapshots.append(obj)

            snapshots_panel.add_snapshots(snapshots_)
            self.raise_panel(snapshots_panel)
            snapshots_panel.goto_snapshot(1)

        self.timer = qc.QTimer(self)
        self.timer.timeout.connect(self.periodical)
        self.timer.setInterval(1000)
        self.timer.start()

        self._animation_saver = None

        self.closing = False
        self.vtk_widget.setFocus()

        self.update_detached()

        self.status('Pyrocko Sparrow - A bird\'s eye view.', 2.0)
        self.status('Let\'s fly.', 2.0)

        self.show()
        self.windowHandle().showMaximized()

        update_vtk_widget_size = self.update_vtk_widget_size
        self.register_state_listener(update_vtk_widget_size)
        self.gui_state.add_listener(update_vtk_widget_size, 'fixed_size')

    def _add_vtk_widget_size_menu_entries(self, menu):

        group = qw.QActionGroup(menu)
        group.setExclusive(True)

        fixed_size_items = []
        for nx, ny in [
                (1920, 1080),
                (800, 600),
                (800, 800)]:
            name = '%i x %i' % (nx, ny)
            action = menu.addAction(name)
            action.setCheckable(True)
            action.setActionGroup(group)
            fixed_size_items.append((action, (nx, ny)))

            def make_set_fixed_size(nx, ny):
                def set_fixed_size():
                    self.gui_state.fixed_size = (float(nx), float(ny))

                return set_fixed_size

            action.triggered.connect(make_set_fixed_size(nx, ny))

        def set_variable_size():
            self.gui_state.fixed_size = False

        variable_size_action = menu.addAction('Variable Size')
        variable_size_action.setCheckable(True)
        variable_size_action.setActionGroup(group)
        variable_size_action.triggered.connect(set_variable_size)

        def update_widget(*args):
            for action, (nx, ny) in fixed_size_items:
                action.blockSignals(True)
                action.setChecked(
                    bool(self.gui_state.fixed_size and (nx, ny) == tuple(
                        int(z) for z in self.gui_state.fixed_size)))
                action.blockSignals(False)

            variable_size_action.blockSignals(True)
            variable_size_action.setChecked(not self.gui_state.fixed_size)
            variable_size_action.blockSignals(False)

        update_widget()
        self.register_state_listener(update_widget)
        self.gui_state.add_listener(update_widget, 'fixed_size')

    def status(self, message, duration=None):
        sb = self.statusBar()
        # if sb.current_message()
        sb.showMessage(message, int(duration * 1000))

    def update_vtk_widget_size(self, *args):
        if self.gui_state.fixed_size:
            nx, ny = map(int, self.gui_state.fixed_size)
            self.vtk_widget.setFixedSize(qc.QSize(nx, ny))
        else:
            self.vtk_widget.setFixedSize(
                qw.QWIDGETSIZE_MAX, qw.QWIDGETSIZE_MAX)

        self.vtk_frame.recenter()

    def update_focal_point(self, *args):
        if self.gui_state.focal_point == 'center':
            self.vtk_widget.setStatusTip(
                'Click and drag: change location. %s-click and drag: '
                'change view plane orientation.' % g_modifier_key)
        else:
            self.vtk_widget.setStatusTip(
                '%s-click and drag: change location. Click and drag: '
                'change view plane orientation. Uncheck "Navigation: Fix" to '
                'reverse sense.' % g_modifier_key)

    def update_detached(self, *args):

        if self.gui_state.detached and not self.detached_window:  # detach
            logger.debug('Detaching VTK view.')

            self.main_layout.removeWidget(self.vtk_frame)
            self.detached_window = DetachedViewer(self, self.vtk_frame)
            self.detached_window.show()
            self.vtk_widget.setFocus()

            screens = get_app().screens()
            if len(screens) > 1:
                for screen in screens:
                    if screen is not self.screen():
                        self.detached_window.windowHandle().setScreen(screen)
                        # .setScreen() does not work reliably,
                        # therefore trying also with .move()...
                        p = screen.geometry().topLeft()
                        self.detached_window.move(p.x() + 50, p.y() + 50)
                        # ... but also does not work in notion window manager.

            self.detached_window.windowHandle().showMaximized()

            frame = qw.QFrame()
            frame.setFrameShape(qw.QFrame.NoFrame)
            frame.setBackgroundRole(qg.QPalette.Mid)
            frame.setAutoFillBackground(True)
            frame.setSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Expanding)

            layout = qw.QGridLayout()
            frame.setLayout(layout)
            self.main_layout.insertWidget(0, frame)

            # attach_button = qw.QPushButton('Attach View')
            # attach_button.clicked.connect(self.attach)
            # layout.addWidget(
            #     attach_button, 0, 0, alignment=qc.Qt.AlignCenter)

            self.vtk_frame_substitute = frame

        if not self.gui_state.detached and self.detached_window:  # attach
            logger.debug('Attaching VTK view.')
            self.detached_window.hide()
            self.vtk_frame.setParent(self)
            if self.vtk_frame_substitute:
                self.main_layout.removeWidget(self.vtk_frame_substitute)

            self.main_layout.insertWidget(0, self.vtk_frame)
            self.detached_window = None
            self.vtk_widget.setFocus()

    def attach(self):
        self.gui_state.detached = False

    def export_image(self):

        caption = 'Export Image'
        fn_out, _ = qw.QFileDialog.getSaveFileName(
            self, caption, 'image.png',
            options=common.qfiledialog_options)

        if fn_out:
            self.save_image(fn_out)

    def save_image(self, path):

        original_fixed_size = self.gui_state.fixed_size
        if original_fixed_size is None:
            self.gui_state.fixed_size = (1920., 1080.)

        wif = vtk.vtkWindowToImageFilter()
        wif.SetInput(self.renwin)
        wif.SetInputBufferTypeToRGBA()
        wif.ReadFrontBufferOff()
        writer = vtk.vtkPNGWriter()
        writer.SetInputConnection(wif.GetOutputPort())

        self.renwin.Render()
        wif.Modified()
        writer.SetFileName(path)
        writer.Write()

        self.vtk_widget.setFixedSize(
            qw.QWIDGETSIZE_MAX, qw.QWIDGETSIZE_MAX)

        self.gui_state.fixed_size = original_fixed_size

    def update_render_settings(self, *args):
        if self._lighting is None or self._lighting != self.state.lighting:
            self.ren.RemoveAllLights()
            for li in light.get_lights(self.state.lighting):
                self.ren.AddLight(li)

            self._lighting = self.state.lighting

        if self._background is None \
                or self._background != self.state.background:

            self.state.background.vtk_apply(self.ren)
            self._background = self.state.background

        self.update_view()

    def start_animation(self, interpolator, output_path=None):
        self._animation = interpolator
        if output_path is None:
            self._animation_tstart = time.time()
            self._animation_iframe = None
        else:
            self._animation_iframe = 0
            self.showFullScreen()
            self.update_view()
            self.gui_state.panels_visible = False
            self.update_view()

        self._animation_timer = qc.QTimer(self)
        self._animation_timer.timeout.connect(self.next_animation_frame)
        self._animation_timer.setInterval(int(round(interpolator.dt * 1000.)))
        self._animation_timer.start()
        if output_path is not None:
            self.vtk_widget.setFixedSize(qc.QSize(1920, 1080))
            # self.vtk_widget.setFixedSize(qc.QSize(960, 540))

            wif = vtk.vtkWindowToImageFilter()
            wif.SetInput(self.renwin)
            wif.SetInputBufferTypeToRGBA()
            wif.SetScale(1, 1)
            wif.ReadFrontBufferOff()
            writer = vtk.vtkPNGWriter()
            temp_path = tempfile.mkdtemp()
            self._animation_saver = (wif, writer, temp_path, output_path)
            writer.SetInputConnection(wif.GetOutputPort())

    def next_animation_frame(self):

        ani = self._animation
        if not ani:
            return

        if self._animation_iframe is not None:
            state = ani(
                ani.tmin
                + self._animation_iframe * ani.dt)

            self._animation_iframe += 1
        else:
            tnow = time.time()
            state = ani(min(
                ani.tmax,
                ani.tmin + (tnow - self._animation_tstart)))

        self.set_state(state)
        self.renwin.Render()
        if self._animation_saver:
            wif, writer, temp_path, _ = self._animation_saver
            wif.Modified()
            fn = os.path.join(temp_path, 'f%09i.png')
            writer.SetFileName(fn % self._animation_iframe)
            writer.Write()

        if self._animation_iframe is not None:
            t = self._animation_iframe * ani.dt
        else:
            t = tnow - self._animation_tstart

        if t > ani.tmax - ani.tmin:
            self.stop_animation()

    def stop_animation(self):
        if self._animation_timer:
            self._animation_timer.stop()

        if self._animation_saver:
            self.vtk_widget.setFixedSize(
                qw.QWIDGETSIZE_MAX, qw.QWIDGETSIZE_MAX)

            wif, writer, temp_path, output_path = self._animation_saver
            fn_path = os.path.join(temp_path, 'f%09d.png')
            check_call([
                'ffmpeg', '-y',
                '-i', fn_path,
                '-c:v', 'libx264',
                '-preset', 'slow',
                '-crf', '17',
                '-vf', 'format=yuv420p,fps=%i' % (
                    int(round(1.0/self._animation.dt))),
                output_path])
            shutil.rmtree(temp_path)

            self._animation_saver = None
            self._animation_saver

            self.showNormal()
            self.gui_state.panels_visible = True

        self._animation_tstart = None
        self._animation_iframe = None
        self._animation = None

    def set_state(self, state):
        self.setUpdatesEnabled(False)
        self.state.diff_update(state)
        self.setUpdatesEnabled(True)

    def periodical(self):
        pass

    def request_quit(self):
        app = get_app()
        app.myQuit()

    def check_resize(self, *args):
        self._render_window_size
        render_window_size = self.renwin.GetSize()
        if self._render_window_size != render_window_size:
            self._render_window_size = render_window_size
            self.resize_event(*render_window_size)

    def update_elements(self, path, value):
        if self._in_update_elements:
            return

        self._in_update_elements = True
        for estate in self.state.elements:
            if estate.element_id not in self._elements:
                new_element = estate.create()
                logger.debug('Creating "%s".' % type(new_element).__name__)
                self._elements[estate.element_id] = new_element

            element = self._elements[estate.element_id]

            if estate.element_id not in self._elements_active:
                logger.debug('Adding "%s".' % type(element).__name__)
                element.bind_state(estate)
                element.set_parent(self)
                self._elements_active[estate.element_id] = element

        state_element_ids = [el.element_id for el in self.state.elements]
        deactivate = []
        for element_id, element in self._elements_active.items():
            if element_id not in state_element_ids:
                logger.debug('Removing "%s".' % type(element).__name__)
                element.unset_parent()
                deactivate.append(element_id)

        for element_id in deactivate:
            del self._elements_active[element_id]

        self._in_update_elements = False

    def add_actor_2d(self, actor):
        if actor not in self._actors_2d:
            self.ren.AddActor2D(actor)
            self._actors_2d.add(actor)

    def remove_actor_2d(self, actor):
        if actor in self._actors_2d:
            self.ren.RemoveActor2D(actor)
            self._actors_2d.remove(actor)

    def add_actor(self, actor):
        if actor not in self._actors:
            self.ren.AddActor(actor)
            self._actors.add(actor)

    def add_actor_list(self, actorlist):
        for actor in actorlist:
            self.add_actor(actor)

    def remove_actor(self, actor):
        if actor in self._actors:
            self.ren.RemoveActor(actor)
            self._actors.remove(actor)

    def update_view(self):
        self.vtk_widget.update()

    def resize_event(self, size_x, size_y):
        self.gui_state.size = (size_x, size_y)

    def button_event(self, obj, event):
        if event == "LeftButtonPressEvent":
            self.rotating = True
        elif event == "LeftButtonReleaseEvent":
            self.rotating = False

    def mouse_move_event(self, obj, event):
        x0, y0 = self.iren.GetLastEventPosition()
        x, y = self.iren.GetEventPosition()

        size_x, size_y = self.renwin.GetSize()
        center_x = size_x / 2.0
        center_y = size_y / 2.0

        if self.rotating:
            self.do_rotate(x, y, x0, y0, center_x, center_y)

    def myWheelEvent(self, event):

        angle = event.angleDelta().y()

        if angle > 200:
            angle = 200

        if angle < -200:
            angle = -200

        self.do_dolly(-angle/100.)

    def do_rotate(self, x, y, x0, y0, center_x, center_y):

        dx = x0 - x
        dy = y0 - y

        phi = d2r*(self.state.strike - 90.)
        focp = self.gui_state.focal_point

        if focp == 'center':
            dx, dy = math.cos(phi) * dx + math.sin(phi) * dy, \
                - math.sin(phi) * dx + math.cos(phi) * dy

            lat = self.state.lat
            lon = self.state.lon
            factor = self.state.distance / 10.0
            factor_lat = (1.0 + 0.1)/(num.cos(lat*d2r) + 0.2)
        else:
            lat = 90. - self.state.dip
            lon = -self.state.strike - 90.
            factor = 0.5
            factor_lat = 1.0

        dlat = dy * factor
        dlon = dx * factor * factor_lat

        lat = max(min(lat + dlat, 90.), -90.)
        lon += dlon
        lon = (lon + 180.) % 360. - 180.

        if focp == 'center':
            self.state.lat = float(lat)
            self.state.lon = float(lon)
        else:
            self.state.dip = float(90. - lat)
            self.state.strike = float(-(lon + 90.))

    def do_dolly(self, v):
        self.state.distance *= float(1.0 + 0.1*v)

    def key_down_event(self, obj, event):
        k = obj.GetKeyCode()
        s = obj.GetKeySym()
        if k == 'f' or s == 'Control_L':
            self.gui_state.next_focal_point()

        elif k == 'r':
            self.reset_strike_dip()

        elif k == 'p':
            print(self.state)

        elif k == 'i':
            for elem in self.state.elements:
                if isinstance(elem, elements.IcosphereState):
                    elem.visible = not elem.visible

        elif k == 'c':
            for elem in self.state.elements:
                if isinstance(elem, elements.CoastlinesState):
                    elem.visible = not elem.visible

        elif k == 't':
            if not any(
                    isinstance(elem, elements.TopoState)
                    for elem in self.state.elements):

                self.state.elements.append(elements.TopoState())
            else:
                for elem in self.state.elements:
                    if isinstance(elem, elements.TopoState):
                        elem.visible = not elem.visible

        elif k == ' ':
            self.toggle_panel_visibility()

        elif k == 'd':
            self.gui_state.detached = not self.gui_state.detached

    def key_up_event(self, obj, event):
        s = obj.GetKeySym()
        if s == 'Control_L':
            self.gui_state.next_focal_point()

    def _state_bind(self, *args, **kwargs):
        vstate.state_bind(self, self.state, *args, **kwargs)

    def _gui_state_bind(self, *args, **kwargs):
        vstate.state_bind(self, self.gui_state, *args, **kwargs)

    def controls_navigation(self):
        frame = qw.QFrame(self)
        frame.setSizePolicy(
            qw.QSizePolicy.Minimum, qw.QSizePolicy.Fixed)
        layout = qw.QGridLayout()
        frame.setLayout(layout)

        # lat, lon, depth

        layout.addWidget(
            qw.QLabel('Location'), 0, 0, 1, 2)

        le = qw.QLineEdit()
        le.setStatusTip(
            'Latitude, Longitude, Depth [km] or city name: '
            'Focal point location.')
        layout.addWidget(le, 1, 0, 1, 1)

        def lat_lon_depth_to_lineedit(state, widget):
            sel = str(widget.selectedText()) == str(widget.text())
            widget.setText('%g, %g, %g' % (
                state.lat, state.lon, state.depth / km))

            if sel:
                widget.selectAll()

        def lineedit_to_lat_lon_depth(widget, state):
            s = str(widget.text())
            choices = location_to_choices(s)
            if len(choices) > 0:
                self.state.lat, self.state.lon, self.state.depth = \
                    choices[0].get_lat_lon_depth()
            else:
                raise NoLocationChoices(s)

        self._state_bind(
            ['lat', 'lon', 'depth'],
            lineedit_to_lat_lon_depth,
            le, [le.editingFinished, le.returnPressed],
            lat_lon_depth_to_lineedit)

        self.lat_lon_lineedit = le

        self.lat_lon_lineedit.returnPressed.connect(
            lambda *args: self.lat_lon_lineedit.selectAll())

        # focal point

        cb = qw.QCheckBox('Fix')
        cb.setStatusTip(
            'Fix location. Orbit focal point without pressing %s.' 
            % g_modifier_key)
        layout.addWidget(cb, 1, 1, 1, 1)

        def focal_point_to_checkbox(state, widget):
            widget.blockSignals(True)
            widget.setChecked(self.gui_state.focal_point != 'center')
            widget.blockSignals(False)

        def checkbox_to_focal_point(widget, state):
            self.gui_state.focal_point = \
                'target' if widget.isChecked() else 'center'

        self._gui_state_bind(
            ['focal_point'], checkbox_to_focal_point,
            cb, [cb.toggled], focal_point_to_checkbox)

        self.focal_point_checkbox = cb

        update_focal_point = self.update_focal_point
        self.register_state_listener(update_focal_point)
        self.gui_state.add_listener(update_focal_point, 'focal_point')
        self.update_focal_point()

        # strike, dip

        layout.addWidget(
            qw.QLabel('View Plane'), 2, 0, 1, 2)

        le = qw.QLineEdit()
        le.setStatusTip(
            'Strike, Dip [deg]: View plane orientation, perpendicular to view '
            'direction.')
        layout.addWidget(le, 3, 0, 1, 1)

        def strike_dip_to_lineedit(state, widget):
            sel = widget.selectedText() == widget.text()
            widget.setText('%g, %g' % (state.strike, state.dip))
            if sel:
                widget.selectAll()

        def lineedit_to_strike_dip(widget, state):
            s = str(widget.text())
            string_to_strike_dip = {
                'east': (0., 90.),
                'west': (180., 90.),
                'south': (90., 90.),
                'north': (270., 90.),
                'top': (90., 0.),
                'bottom': (90., 180.)}

            if s in string_to_strike_dip:
                state.strike, state.dip = string_to_strike_dip[s]

            s = s.replace(',', ' ')
            try:
                state.strike, state.dip = map(float, s.split())
            except Exception:
                raise ValueError('need two numerical values: <strike>, <dip>')

        self._state_bind(
            ['strike', 'dip'], lineedit_to_strike_dip,
            le, [le.editingFinished, le.returnPressed], strike_dip_to_lineedit)

        self.strike_dip_lineedit = le
        self.strike_dip_lineedit.returnPressed.connect(
            lambda *args: self.strike_dip_lineedit.selectAll())

        but = qw.QPushButton('Reset')
        but.setStatusTip('Reset to north-up map view.')
        but.clicked.connect(self.reset_strike_dip)
        layout.addWidget(but, 3, 1, 1, 1)

        # camera bindings

        update_camera = self.update_camera        # this assignment is needed

        self.register_state_listener(update_camera)

        self.state.add_listener(update_camera, 'lat')
        self.state.add_listener(update_camera, 'lon')
        self.state.add_listener(update_camera, 'depth')
        self.state.add_listener(update_camera, 'strike')
        self.state.add_listener(update_camera, 'dip')
        self.state.add_listener(update_camera, 'distance')

        update_panel_visibility = self.update_panel_visibility
        self.register_state_listener(update_panel_visibility)
        self.gui_state.add_listener(update_panel_visibility, 'panels_visible')

        return frame

    def controls_time(self):
        frame = qw.QFrame(self)
        frame.setSizePolicy(
            qw.QSizePolicy.Minimum, qw.QSizePolicy.Fixed)

        layout = qw.QGridLayout()
        frame.setLayout(layout)

        layout.addWidget(qw.QLabel('Min'), 0, 0)
        le_tmin = qw.QLineEdit()
        layout.addWidget(le_tmin, 0, 1)

        layout.addWidget(qw.QLabel('Max'), 1, 0)
        le_tmax = qw.QLineEdit()
        layout.addWidget(le_tmax, 1, 1)

        def time_to_lineedit(state, attribute, widget):
            sel = widget.selectedText() == widget.text() \
                and widget.text() != ''

            widget.setText(
                common.time_or_none_to_str(getattr(state, attribute)))

            if sel:
                widget.selectAll()

        def lineedit_to_time(widget, state, attribute):
            from pyrocko.util import str_to_time_fillup

            s = str(widget.text())
            if not s.strip():
                setattr(state, attribute, None)
            else:
                try:
                    setattr(state, attribute, str_to_time_fillup(s))
                except Exception:
                    raise ValueError(
                        'Use time format: YYYY-MM-DD HH:MM:SS.FFF')

        self._state_bind(
            ['tmin'], lineedit_to_time, le_tmin,
            [le_tmin.editingFinished, le_tmin.returnPressed], time_to_lineedit,
            attribute='tmin')
        self._state_bind(
            ['tmax'], lineedit_to_time, le_tmax,
            [le_tmax.editingFinished, le_tmax.returnPressed], time_to_lineedit,
            attribute='tmax')

        self.tmin_lineedit = le_tmin
        self.tmax_lineedit = le_tmax

        range_edit = RangeEdit()
        range_edit.set_data_provider(self)
        range_edit.set_data_name('time')

        xblock = [False]

        def range_to_range_edit(state, widget):
            if not xblock[0]:
                widget.blockSignals(True)
                widget.set_focus(state.tduration, state.tposition)
                widget.set_range(state.tmin, state.tmax)
                widget.blockSignals(False)

        def range_edit_to_range(widget, state):
            xblock[0] = True
            self.state.tduration, self.state.tposition = widget.get_focus()
            self.state.tmin, self.state.tmax = widget.get_range()
            xblock[0] = False

        self._state_bind(
            ['tmin', 'tmax', 'tduration', 'tposition'],
            range_edit_to_range,
            range_edit,
            [range_edit.rangeChanged, range_edit.focusChanged],
            range_to_range_edit)

        layout.addWidget(range_edit, 2, 0, 1, 2)

        layout.addWidget(qw.QLabel('Focus'), 3, 0)
        le_focus = qw.QLineEdit()
        layout.addWidget(le_focus, 3, 1)

        def focus_to_lineedit(state, widget):
            sel = widget.selectedText() == widget.text() \
                and widget.text() != ''

            if state.tduration is None:
                widget.setText('')
            else:
                widget.setText('%s, %g' % (
                    guts.str_duration(state.tduration),
                    state.tposition))

            if sel:
                widget.selectAll()

        def lineedit_to_focus(widget, state):
            s = str(widget.text())
            w = [x.strip() for x in s.split(',')]
            try:
                if len(w) == 0 or not w[0]:
                    state.tduration = None
                    state.tposition = 0.0
                else:
                    state.tduration = guts.parse_duration(w[0])
                    if len(w) > 1:
                        state.tposition = float(w[1])
                    else:
                        state.tposition = 0.0

            except Exception:
                raise ValueError('need two values: <duration>, <position>')

        self._state_bind(
            ['tduration', 'tposition'], lineedit_to_focus, le_focus,
            [le_focus.editingFinished, le_focus.returnPressed],
            focus_to_lineedit)

        label_effective_tmin = qw.QLabel()
        label_effective_tmax = qw.QLabel()

        label_effective_tmin.setSizePolicy(
            qw.QSizePolicy.Minimum, qw.QSizePolicy.Fixed)
        label_effective_tmax.setSizePolicy(
            qw.QSizePolicy.Minimum, qw.QSizePolicy.Fixed)
        label_effective_tmin.setMinimumSize(
            qg.QFontMetrics(label_effective_tmin.font()).width(
                '0000-00-00 00:00:00.000  '), 0)

        layout.addWidget(label_effective_tmin, 4, 1)
        layout.addWidget(label_effective_tmax, 5, 1)

        update_effective_time_labels = self.update_effective_time_labels
        self.register_state_listener(update_effective_time_labels)
        for k in ['tmin', 'tmax', 'tduration', 'tposition']:
            self.state.add_listener(update_effective_time_labels, k)

        self._label_effective_tmin = label_effective_tmin
        self._label_effective_tmax = label_effective_tmax

        return frame

    def controls_appearance(self):
        frame = qw.QFrame(self)
        frame.setSizePolicy(
            qw.QSizePolicy.Minimum, qw.QSizePolicy.Fixed)
        layout = qw.QGridLayout()
        frame.setLayout(layout)

        layout.addWidget(qw.QLabel('Lighting'), 0, 0)

        cb = common.string_choices_to_combobox(vstate.LightingChoice)
        layout.addWidget(cb, 0, 1)
        vstate.state_bind_combobox(self, self.state, 'lighting', cb)

        update_render_settings = self.update_render_settings

        self.register_state_listener(update_render_settings)
        self.state.add_listener(update_render_settings, 'lighting')

        # background

        layout.addWidget(qw.QLabel('Background'), 1, 0)

        cb = common.strings_to_combobox(
            ['black', 'white', 'skyblue1 - white'])

        layout.addWidget(cb, 1, 1)
        vstate.state_bind_combobox_background(
            self, self.state, 'background', cb)

        self.register_state_listener(update_render_settings)
        self.state.add_listener(update_render_settings, 'background')

        # detached/attached

        update_detached = self.update_detached
        self.register_state_listener(update_detached)
        self.gui_state.add_listener(update_detached, 'detached')

        cb = qw.QCheckBox('Detach')
        layout.addWidget(cb, 2, 0, 2, 1)
        vstate.state_bind_checkbox(self, self.gui_state, 'detached', cb)

        return frame

    def controls_snapshots(self):
        return snapshots_mod.SnapshotsPanel(self)

    def update_effective_time_labels(self, *args):
        tmin = self.state.tmin_effective
        tmax = self.state.tmax_effective

        stmin = common.time_or_none_to_str(tmin)
        stmax = common.time_or_none_to_str(tmax)

        self._label_effective_tmin.setText(stmin)
        self._label_effective_tmax.setText(stmax)

    def reset_strike_dip(self, *args):
        self.state.strike = 90.
        self.state.dip = 0
        self.gui_state.focal_point = 'center'

    def register_state_listener(self, listener):
        self.listeners.append(listener)  # keep listeners alive

    def get_camera_geometry(self):

        def rtp2xyz(rtp):
            return geometry.rtp2xyz(rtp[num.newaxis, :])[0]

        radius = 1.0 - self.state.depth / self.planet_radius

        cam_rtp = num.array([
            radius+self.state.distance,
            self.state.lat * d2r + 0.5*num.pi,
            self.state.lon * d2r])
        up_rtp = cam_rtp + num.array([0., 0.5*num.pi, 0.])
        cam, up, foc = \
            rtp2xyz(cam_rtp), rtp2xyz(up_rtp), num.array([0., 0., 0.])

        foc_rtp = num.array([
            radius,
            self.state.lat * d2r + 0.5*num.pi,
            self.state.lon * d2r])

        foc = rtp2xyz(foc_rtp)

        rot_world = pmt.euler_to_matrix(
            -(self.state.lat-90.)*d2r,
            (self.state.lon+90.)*d2r,
            0.0*d2r).T

        rot_cam = pmt.euler_to_matrix(
            self.state.dip*d2r, -(self.state.strike-90)*d2r, 0.0*d2r).T

        rot = num.dot(rot_world, num.dot(rot_cam, rot_world.T))

        cam = foc + num.dot(rot, cam - foc)
        up = num.dot(rot, up)
        return cam, up, foc

    def update_camera(self, *args):
        cam, up, foc = self.get_camera_geometry()
        camera = self.ren.GetActiveCamera()
        camera.SetPosition(*cam)
        camera.SetFocalPoint(*foc)
        camera.SetViewUp(*up)

        planet_horizon = math.sqrt(max(0., num.sum(cam**2) - 1.0))

        feature_horizon = math.sqrt(max(0., num.sum(cam**2) - (
            self.feature_radius_min / self.planet_radius)**2))

        # if horizon == 0.0:
        #     horizon = 2.0 + self.state.distance

        # clip_dist = max(min(self.state.distance*5., max(
        #    1.0, num.sqrt(num.sum(cam**2)))), feature_horizon)
        # , math.sqrt(num.sum(cam**2)))
        clip_dist = max(1.0, feature_horizon)  # , math.sqrt(num.sum(cam**2)))
        # clip_dist = feature_horizon

        camera.SetClippingRange(max(clip_dist*0.001, clip_dist-3.0), clip_dist)

        self.camera_params = (
            cam, up, foc, planet_horizon, feature_horizon, clip_dist)

        self.update_view()

    def add_panel(
            self, name, panel,
            visible=False,
            # volatile=False,
            tabify=True,
            where=qc.Qt.RightDockWidgetArea):

        dockwidget = MyDockWidget(name, self)

        if not visible:
            dockwidget.hide()

        if not self.gui_state.panels_visible:
            dockwidget.block()

        dockwidget.setWidget(panel)
        panel.setParent(dockwidget)

        dockwidgets = self.findChildren(MyDockWidget)
        dws = [x for x in dockwidgets if self.dockWidgetArea(x) == where]

        self.addDockWidget(where, dockwidget)

        nwrap = 4
        if dws and len(dws) >= nwrap and tabify:
            self.tabifyDockWidget(
                dws[len(dws) - nwrap + len(dws) % nwrap], dockwidget)

        mitem = dockwidget.toggleViewAction()
        self._panel_togglers[dockwidget] = mitem
        self.panels_menu.addAction(mitem)
        if visible:
            dockwidget.setVisible(True)
            dockwidget.setFocus()
            dockwidget.raise_()

    def raise_panel(self, panel):
        dockwidget = panel.parent()
        dockwidget.setVisible(True)
        dockwidget.setFocus()
        dockwidget.raise_()

    def toggle_panel_visibility(self):
        self.gui_state.panels_visible = not self.gui_state.panels_visible

    def update_panel_visibility(self, *args):
        self.setUpdatesEnabled(False)
        mbar = self.menuBar()
        dockwidgets = self.findChildren(MyDockWidget)

        mbar.setVisible(self.gui_state.panels_visible)
        for dockwidget in dockwidgets:
            dockwidget.setBlocked(not self.gui_state.panels_visible)

        self.setUpdatesEnabled(True)

    def remove_panel(self, panel):
        dockwidget = panel.parent()
        self.removeDockWidget(dockwidget)
        dockwidget.setParent(None)
        self.panels_menu.removeAction(self._panel_togglers[dockwidget])

    def register_data_provider(self, provider):
        if provider not in self.data_providers:
            self.data_providers.append(provider)

    def unregister_data_provider(self, provider):
        if provider in self.data_providers:
            self.data_providers.remove(provider)

    def iter_data(self, name):
        for provider in self.data_providers:
            for data in provider.iter_data(name):
                yield data

    def closeEvent(self, event):
        self.attach()
        event.accept()
        self.closing = True

    def is_closing(self):
        return self.closing


class SparrowApp(qw.QApplication):
    def __init__(self):
        qw.QApplication.__init__(self, ['Sparrow'])
        self.lastWindowClosed.connect(self.myQuit)
        self._main_window = None
        self.setApplicationDisplayName('Sparrow')
        self.setDesktopFileName('Sparrow')

    def install_sigint_handler(self):
        self._old_signal_handler = signal.signal(
            signal.SIGINT, self.myCloseAllWindows)

    def uninstall_sigint_handler(self):
        signal.signal(signal.SIGINT, self._old_signal_handler)

    def myQuit(self, *args):
        self.quit()

    def myCloseAllWindows(self, *args):
        self.closeAllWindows()

    def set_main_window(self, win):
        self._main_window = win

    def get_main_window(self):
        return self._main_window

    def get_progressbars(self):
        if self._main_window:
            return self._main_window.progressbars
        else:
            return None


app = None


def main(*args, **kwargs):

    from pyrocko import util
    util.setup_logging('sparrow', 'info')

    global app
    global win

    if app is None:
        app = SparrowApp()

        # try:
        #     from qt_material import apply_stylesheet
        #
        #     apply_stylesheet(app, theme='dark_teal.xml')
        #
        #
        #     import qdarkgraystyle
        #     app.setStyleSheet(qdarkgraystyle.load_stylesheet())
        #     import qdarkstyle
        #
        #     app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
        #
        #
        # except ImportError:
        #     logger.info(
        #         'Module qdarkgraystyle not available.\n'
        #         'If wanted, install qdarkstyle with "pip install '
        #         'qdarkgraystyle".')
        #
    win = SparrowViewer(*args, **kwargs)
    app.set_main_window(win)

    app.install_sigint_handler()
    app.exec_()
    app.uninstall_sigint_handler()

    app.set_main_window(None)

    del win

    gc.collect()
