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
import re

import numpy as num

from pyrocko import guts
from pyrocko import geonames
from pyrocko import moment_tensor as pmt

from pyrocko.gui.util import Progressbars
from pyrocko.gui.qt_compat import qw, qc, use_pyqt5

import vtk
import vtk.qt
vtk.qt.QVTKRWIBase = "QGLWidget"  # noqa

if use_pyqt5:  # noqa
    from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
else:
    from vtk.qt4.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor


from pyrocko import icosphere, geometry
from . import state as vstate, elements


logger = logging.getLogger('pyrocko.gui.sparrow.main')


d2r = num.pi/180.


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
        vals = map(float, s_vals.split())
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


def color_lights():
    l1 = vtk.vtkLight()
    l2 = vtk.vtkLight()
    l3 = vtk.vtkLight()
    l4 = vtk.vtkLight()
    # l1.SetColor(1., 0.5, 0.5)
    # l2.SetColor(0.5, 1.0, 1.0)
    # l3.SetColor(1., 0.5, 0.5)
    # l4.SetColor(0.5, 1.0, 1.0)
    l1.SetColor(1., 0.53, 0.0)
    l2.SetColor(0.53, 0.53, 0.37)
    l3.SetColor(1., 1., 0.69)
    l4.SetColor(0.56, 0.68, 0.84)
    vertices, _ = icosphere.tetrahedron()
    vertices *= -1.
    l1.SetPosition(*vertices[0, :])
    l2.SetPosition(*vertices[1, :])
    l3.SetPosition(*vertices[2, :])
    l4.SetPosition(*vertices[3, :])
    l1.SetFocalPoint(0., 0., 0.)
    l2.SetFocalPoint(0., 0., 0.)
    l3.SetFocalPoint(0., 0., 0.)
    l4.SetFocalPoint(0., 0., 0.)
    lights = [l1, l2, l3, l4]
    for light in lights:
        light.SetLightTypeToCameraLight()
    return lights


class Viewer(qw.QMainWindow):
    def __init__(self):
        qw.QMainWindow.__init__(self)

        self._panel_togglers = {}

        mbar = self.menuBar()
        menu = mbar.addMenu('File')

        mitem = qw.QAction('Quit', self)
        mitem.triggered.connect(self.request_quit)
        menu.addAction(mitem)

        menu = mbar.addMenu('Add')
        for name, estate in [
                ('Stations', elements.StationsState()),
                ('Topography', elements.TopoState()),
                ('Catalog', elements.CatalogState()),
                ('Coastlines', elements.CoastlinesState()),
                ('Source', elements.SourceState())]:

            def wrap_add_element(estate):
                def add_element(*args):
                    self.state.elements.append(guts.clone(estate))
                return add_element

            mitem = qw.QAction(name, self)

            mitem.triggered.connect(wrap_add_element(estate))

            menu.addAction(mitem)

        self.panels_menu = mbar.addMenu('Panels')

        self.state = vstate.ViewerState()
        self.listeners = []
        self.elements = {}

        self.frame = qw.QFrame()

        self.vl = qw.QVBoxLayout()
        self.vl.setContentsMargins(0, 0, 0, 0)

        frame2 = qw.QFrame()
        # frame2.setFrameStyle(qw.QFrame.StyledPanel)
        vl2 = qw.QVBoxLayout()
        vl2.setContentsMargins(0, 0, 0, 0)
        frame2.setLayout(vl2)

        self.vtk_widget = QVTKRenderWindowInteractor(frame2)

        vl2.addWidget(self.vtk_widget)
        self.vl.addWidget(frame2)

        pb = Progressbars(self)
        self.progressbars = pb
        self.vl.addWidget(pb)

        self.frame.setLayout(self.vl)

        self.add_panel('Navigation', self.controls(), visible=True)

        self.setCentralWidget(self.frame)

        self.mesh = None

        ren = vtk.vtkRenderer()
        for l in color_lights():
            ren.AddLight(l)

        ren.SetBackground(0.15, 0.15, 0.15)

        self.ren = ren
        self.update_camera()

        renwin = self.vtk_widget.GetRenderWindow()
        renwin.LineSmoothingOn()
        renwin.PointSmoothingOn()
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
        iren.AddObserver('KeyPressEvent', self.key_press_event)
        iren.AddObserver(
            'MouseWheelForwardEvent',
            self.mouse_wheel_event_forward)
        iren.AddObserver(
            'MouseWheelBackwardEvent',
            self.mouse_wheel_event_backward)

        self.show()
        iren.Initialize()

        self.renwin = renwin
        self.iren = iren

        self.rotating = False
        self.zooming = False
        self.reset_strike_dip()

        self._elements = {}

        update_elements = self.update_elements
        self.register_state_listener(update_elements)

        self.state.add_listener(update_elements, 'elements')
        self.state.elements.append(elements.IcosphereState(
            level=4, smooth=True))
        self.state.elements.append(elements.GridState())
        self.state.elements.append(elements.CoastlinesState())
        # self.state.elements.append(elements.StationsState())
        # self.state.elements.append(elements.SourceState())

        self.timer = qc.QTimer(self)
        self.timer.timeout.connect(self.periodical)
        self.timer.setInterval(1000)
        self.timer.start()

        self.closing = False

    def periodical(self):
        pass

    def request_quit(self):
        app = get_app()
        app.myQuit()

    def update_elements(self, path, value):
        for estate in self.state.elements:
            if estate not in self._elements:
                element = estate.create()
                element.set_parent(self)
                self._elements[estate] = element

    def add_actor(self, actor):
        self.ren.AddActor(actor)

    def add_actor_list(self, actorlist):
        for actor in actorlist:
            self.add_actor(actor)

    def remove_actor(self, actor):
        self.ren.RemoveActor(actor)

    def update_view(self):
        self.vtk_widget.update()

    def button_event(self, obj, event):
        if event == "LeftButtonPressEvent":
            self.rotating = True
        elif event == "LeftButtonReleaseEvent":
            self.rotating = False
        elif event == "RightButtonPressEvent":
            self.zooming = True
        elif event == "RightButtonReleaseEvent":
            self.zooming = False

    def mouse_move_event(self, obj, event):
        x0, y0 = self.iren.GetLastEventPosition()
        x, y = self.iren.GetEventPosition()

        size_x, size_y = self.renwin.GetSize()
        center_x = size_x / 2.0
        center_y = size_y / 2.0

        if self.rotating:
            self.do_rotate(x, y, x0, y0, center_x, center_y)
        elif self.zooming:
            self.do_dolly(x, y, x0, y0, center_x, center_y)

    def mouse_wheel_event_forward(self, obj, event):
        self.do_dolly(-1.0)

    def mouse_wheel_event_backward(self, obj, event):
        self.do_dolly(1.0)

    def do_rotate(self, x, y, x0, y0, center_x, center_y):

        if self.state.focal_point == 'center':
            lat = self.state.lat
            lon = self.state.lon
            factor = self.state.distance / 10.0
            factor_lat = (1.0 + 0.1)/(num.cos(lat*d2r) + 0.2)
        else:
            lat = 90. - self.state.dip
            lon = -self.state.strike - 90.
            factor = 0.5
            factor_lat = 1.0

        lat = max(min(lat + (y0 - y) * factor, 90.), -90.)
        lon += (x0 - x) * factor * factor_lat
        lon = (lon + 180.) % 360. - 180.

        if self. state.focal_point == 'center':
            self.state.lat = float(lat)
            self.state.lon = float(lon)
        else:
            self.state.dip = float(90. - lat)
            self.state.strike = float(-(lon + 90.))

    def do_dolly(self, v):
        self.state.distance *= float(1.0 + 0.1*v)

    def key_press_event(self, obj, event):
        k = obj.GetKeyCode()
        print(k)
        if k == 'f':
            self.state.next_focal_point()

        elif k == 'p':
            print(self.state)

        elif k == ' ':
            self.toggle_panel_visibility()

    def _state_bind(self, *args, **kwargs):
        vstate.state_bind(self, self.state, *args, **kwargs)

    def controls(self):
        frame = qw.QFrame(self)
        layout = qw.QGridLayout()
        frame.setLayout(layout)

        layout.addWidget(qw.QLabel('Location:'), 0, 0)
        le = qw.QLineEdit()
        layout.addWidget(le, 0, 1)

        def lat_lon_to_lineedit(state, widget):
            sel = str(widget.selectedText()) == str(widget.text())
            widget.setText('%g, %g, %g' % (state.lat, state.lon, state.depth))
            if sel:
                widget.selectAll()

        def lineedit_to_lat_lon(widget, state):
            s = str(widget.text())
            choices = location_to_choices(s)
            if len(choices) > 0:
                self.state.lat, self.state.lon, self.state.depth = \
                    choices[0].get_lat_lon_depth()
            else:
                raise NoLocationChoices(s)

        self._state_bind(
            ['lat', 'lon', 'depth'], lineedit_to_lat_lon,
            le, [le.editingFinished, le.returnPressed], lat_lon_to_lineedit)

        self.lat_lon_lineedit = le

        self.lat_lon_lineedit.returnPressed.connect(
            lambda *args: self.lat_lon_lineedit.selectAll())

        layout.addWidget(qw.QLabel('Strike, Dip:'), 1, 0)
        le = qw.QLineEdit()
        layout.addWidget(le, 1, 1)

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

        cb = qw.QCheckBox('Local Focus')
        layout.addWidget(cb, 2, 0)

        def focal_point_to_checkbox(state, widget):
            widget.blockSignals(True)
            widget.setChecked(self.state.focal_point != 'center')
            widget.blockSignals(False)

        def checkbox_to_focal_point(widget, state):
            self.state.focal_point = \
                'target' if widget.isChecked() else 'center'

        self._state_bind(
            ['focal_point'], checkbox_to_focal_point,
            cb, [cb.toggled], focal_point_to_checkbox)

        self.focal_point_checkbox = cb

        update_camera = self.update_camera        # this assignment is
        reset_strike_dip = self.reset_strike_dip  # necessary!

        self.register_state_listener(update_camera)
        self.register_state_listener(reset_strike_dip)

        self.state.add_listener(update_camera, 'lat')
        self.state.add_listener(update_camera, 'lon')
        self.state.add_listener(update_camera, 'strike')
        self.state.add_listener(update_camera, 'dip')
        self.state.add_listener(update_camera, 'distance')
        self.state.add_listener(update_camera, 'focal_point')
        self.state.add_listener(reset_strike_dip, 'focal_point')

        update_panel_visibility = self.update_panel_visibility
        self.register_state_listener(update_panel_visibility)
        self.state.add_listener(update_panel_visibility, 'panels_visible')

        layout.addWidget(qw.QLabel('T<sub>MIN</sub> UTC:'), 3, 0)
        le_tmin = qw.QLineEdit()
        layout.addWidget(le_tmin, 3, 1)

        layout.addWidget(qw.QLabel('T<sub>MAX</sub> UTC:'), 4, 0)
        le_tmax = qw.QLineEdit()
        layout.addWidget(le_tmax, 4, 1)

        def time_to_lineedit(state, attribute, widget):
            from pyrocko.util import time_to_str

            sel = getattr(state, attribute)
            widget.setText('%s' % (time_to_str(
                getattr(state, attribute), format='%Y-%m-%d %H:%M')))
            if sel:
                widget.selectAll()

        def lineedit_to_time(widget, state, attribute):
            from pyrocko.util import str_to_time

            s = str(widget.text())
            m = re.match(
                r'^\d\d\d\d-\d\d-\d\d( \d\d:\d\d+)?$', s)
            if m:
                if not m.group(1):
                    time_str = m.group(0) + ' 00:00'
                else:
                    time_str = m.group(0)
                setattr(
                    state,
                    attribute,
                    str_to_time(time_str, format='%Y-%m-%d %H:%M'))
            else:
                raise ValueError('Use time format: YYYY-mm-dd [HH:MM]')

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

        self.tmin_lineedit.returnPressed.connect(
            lambda *args: self.tmin_lineedit.selectAll())
        self.tmax_lineedit.returnPressed.connect(
            lambda *args: self.tmax_lineedit.selectAll())

        layout.addWidget(qw.QFrame(), 5, 0, 1, 2)

        return frame

    def reset_strike_dip(self, *args):
        self.state.strike = 90.
        self.state.dip = 0
        if self.state.focal_point == 'center':
            self.strike_dip_lineedit.setDisabled(True)
            self.strike_dip_lineedit.deselect()
        else:
            self.strike_dip_lineedit.setDisabled(False)
            self.strike_dip_lineedit.setFocus(qc.Qt.OtherFocusReason)
            self.strike_dip_lineedit.selectAll()

    def register_state_listener(self, listener):
        self.listeners.append(listener)  # keep listeners alive

    def get_camera_geometry(self):

        def rtp2xyz(rtp):
            return geometry.rtp2xyz(rtp[num.newaxis, :])[0]

        cam_rtp = num.array([
            1.0+self.state.distance,
            self.state.lat * d2r + 0.5*num.pi,
            self.state.lon * d2r])
        up_rtp = cam_rtp + num.array([0., 0.5*num.pi, 0.])
        cam, up, foc = \
            rtp2xyz(cam_rtp), rtp2xyz(up_rtp), num.array([0., 0., 0.])

        if self.state.focal_point == 'center':
            return cam, up, foc

        elif self.state.focal_point == 'target':
            foc_rtp = num.array([
                1.0,
                self.state.lat * d2r + 0.5*num.pi,
                self.state.lon * d2r])

            foc = rtp2xyz(foc_rtp)

            rot_world = pmt.euler_to_matrix(
                -(self.state.lat-90.)*d2r,
                (self.state.lon+90.)*d2r,
                0.0*d2r).A.T

            rot_cam = pmt.euler_to_matrix(
                self.state.dip*d2r, -(self.state.strike-90)*d2r, 0.0*d2r).A.T

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
        if self.state.focal_point == 'center':
            camera.SetClippingRange(0.0001, 1.0 + self.state.distance)
        else:
            horizon = math.sqrt(max(
                0.,
                self.state.distance**2
                - 2.0 * self.state.distance * math.cos(
                    (180. - self.state.dip)*d2r)))

            if horizon == 0.0:
                horizon = 2.0 + self.state.distance

            horizon = max(0.5, horizon)

            camera.SetClippingRange(0.0001, horizon)

        self.update_view()

    def add_panel(
            self, name, panel,
            visible=False,
            # volatile=False,
            tabify=False,
            where=qc.Qt.RightDockWidgetArea):

        dockwidget = qw.QDockWidget(name, self)

        dockwidget.setWidget(panel)
        panel.setParent(dockwidget)
        self.addDockWidget(where, dockwidget)

        mitem = dockwidget.toggleViewAction()
        self._panel_togglers[dockwidget] = mitem
        self.panels_menu.addAction(mitem)

    def toggle_panel_visibility(self):
        self.state.panels_visible = not self.state.panels_visible

    def update_panel_visibility(self, *args):
        mbar = self.menuBar()
        dockwidgets = self.findChildren(qw.QDockWidget)

        if self.state.panels_visible:
            mbar.show()
            for dockwidget in dockwidgets:
                dockwidget.setVisible(True)
        else:
            mbar.hide()
            for dockwidget in dockwidgets:
                dockwidget.setVisible(False)

    def remove_panel(self, panel):
        dockwidget = panel.parent()
        self.removeDockWidget(dockwidget)
        dockwidget.setParent(None)
        self.panels_menu.removeAction(self._panel_togglers[dockwidget])

    def closeEvent(self, event):
        event.accept()
        self.closing = True

    def is_closing(self):
        return self.closing


class App(qw.QApplication):
    def __init__(self):
        qw.QApplication.__init__(self, sys.argv)
        self.lastWindowClosed.connect(self.myQuit)
        self._main_window = None

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
        app = App()

        try:
            import qdarkstyle

            if use_pyqt5:
                app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
            else:
                app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt())

        except ImportError:
            logger.info(
                'Module qdarkstyle not available.\n'
                'If wanted, install qdarkstyle with "pip install qdarkstyle".')

    win = Viewer(*args, **kwargs)
    app.set_main_window(win)

    app.install_sigint_handler()
    app.exec_()
    app.uninstall_sigint_handler()

    app.set_main_window(None)

    del win

    gc.collect()
