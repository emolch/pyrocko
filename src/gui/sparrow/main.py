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
import time
import tempfile
import os
import shutil
from subprocess import check_call

import numpy as num

from pyrocko import cake
from pyrocko import guts
from pyrocko import geonames
from pyrocko import moment_tensor as pmt

from pyrocko.gui.util import Progressbars, RangeEdit
from pyrocko.gui.qt_compat import qw, qc, use_pyqt5, fnpatch
# from pyrocko.gui import vtk_util

from . import common, light, snapshots as snapshots_mod

import vtk
import vtk.qt
vtk.qt.QVTKRWIBase = 'QGLWidget'  # noqa

if use_pyqt5:  # noqa
    from vtk.qt.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor
else:  # noqa
    from vtk.qt4.QVTKRenderWindowInteractor import QVTKRenderWindowInteractor

from pyrocko import geometry  # noqa
from . import state as vstate, elements  # noqa

logger = logging.getLogger('pyrocko.gui.sparrow.main')


d2r = num.pi/180.
km = 1000.


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


class MyDockWidget(qw.QDockWidget):

    def __init__(self, *args, **kwargs):
        qw.QDockWidget.__init__(self, *args, **kwargs)
        self._visible = False
        self._blocked = False

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


class Viewer(qw.QMainWindow):
    def __init__(self, use_depth_peeling=True, events=None, snapshots=None):
        qw.QMainWindow.__init__(self)

        self.planet_radius = cake.earthradius
        self.feature_radius_min = cake.earthradius - 1000. * km

        self._panel_togglers = {}
        self._actors = set()
        self._actors_2d = set()
        self._render_window_size = (0, 0)
        self._use_depth_peeling = use_depth_peeling

        mbar = self.menuBar()
        menu = mbar.addMenu('File')

        mitem = qw.QAction('Quit', self)
        mitem.triggered.connect(self.request_quit)
        menu.addAction(mitem)

        mitem = qw.QAction('Export Image...', self)
        mitem.triggered.connect(self.export_image)
        menu.addAction(mitem)

        self.panels_menu = mbar.addMenu('Panels')

        menu = mbar.addMenu('Add')
        for name, estate in [
                ('Icosphere', elements.IcosphereState()),
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

        self.state = vstate.ViewerState()

        self.gui_state = vstate.ViewerGuiState()

        self.data_providers = []
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

        # self.vtk_widget = QVTKRenderWindowInteractor(frame2)
        self.vtk_widget = QVTKWidget(self, frame2)

        vl2.addWidget(self.vtk_widget)
        self.vl.addWidget(frame2)

        pb = Progressbars(self)
        self.progressbars = pb
        self.vl.addWidget(pb)

        self.frame.setLayout(self.vl)

        self.add_panel(
            'Navigation',
            self.controls(), visible=True,
            where=qc.Qt.LeftDockWidgetArea)

        snapshots_panel = self.snapshots_panel()
        self.add_panel(
            'Snapshots', snapshots_panel, visible=False,
            where=qc.Qt.LeftDockWidgetArea)

        self.setCentralWidget(self.frame)

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

        self.show()
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

        # #####
        # from pyrocko import table
        # import operator
        #
        # def oa_to_array(objects, attribute):
        #     return num.fromiter(
        #         map(operator.attrgetter(attribute), objects),
        #         num.float,
        #         len(objects))
        #
        # def eventtags_to_array(events, tag_ind):
        #
        #     if events[0].tags[tag_ind].find(':') > -1:
        #         header = '_'.join(
        #             ['tag', events[0].tags[tag_ind].split(':')[0]])
        #         value_ind = 1
        #     else:
        #         header = 'tag_%i' % (tag_ind + 1)
        #         value_ind = 0
        #
        #     try:
        #         float(events[0].tags[tag_ind].split(':')[value_ind])
        #         dtype = num.float
        #     except ValueError:
        #         dtype = num.string_
        #
        #     return header, num.array(
        #         [ev.tags[tag_ind].split(':')[value_ind] for ev in events],
        #         dtype=dtype)
        #
        # def events_to_table(events):
        #     c5 = num.zeros((len(events), 5))
        #     m6 = num.zeros((len(events), 6))
        #
        #     for i, ev in enumerate(events):
        #         c5[i, :] = (
        #             ev.lat, ev.lon, ev.north_shift, ev.east_shift, ev.depth)
        #
        #         if ev.moment_tensor:
        #             m6[i, :] = ev.moment_tensor.m6()
        #
        #     tab = table.Table()
        #
        #     loc_rec = table.LocationRecipe()
        #     tab.add_recipe(loc_rec)
        #     tab.add_col(loc_rec.c5_header, c5)
        #
        #     for k, unit in [
        #             ('time', 's'),
        #             ('magnitude', None)]:
        #
        #         tab.add_col(table.Header(k, unit), oa_to_array(events, k))
        #
        #     if events:
        #         for i in range(len(events[0].tags)):
        #             header, values = eventtags_to_array(events, i)
        #             tab.add_col(table.Header(header), values)
        #
        #     mt_rec = table.MomentTensorRecipe()
        #     tab.add_recipe(mt_rec)
        #     tab.add_col(mt_rec.m6_header, m6)
        #
        #     return tab
        #
        # from pyrocko import model
        # events = model.load_events('events.txt')
        # tab = events_to_table(events)
        #
        # positions = tab.get_col('xyz')
        #
        # m6s = tab.get_col('m6')
        # # m6s = num.zeros_like(m6s)
        # # m6s[:, 3] = 1.0
        # sizes = (tab.get_col('magnitude') / 8.0)**2
        #
        # # from pyrocko import orthodrome as od
        #
        # # n = 5
        # # latlons = num.zeros((n,2))
        # # latlons[:, 1] = num.zeros(n)
        # # latlons[:, 0] = num.linspace(-90., 90., n)
        # #
        # # m6s = num.zeros((n,6))
        # # # m6s[:, 0] = 1.0
        # # # m6s[:, 1] = -1.0
        # # # m6s[:, 3] = 1.0
        # # m6s[:, 3] = 1.0
        #
        # # sizes = num.ones(n)
        #
        # # positions = od.latlon_to_xyz(latlons)
        #
        # depths = tab.get_col('depth')
        #
        # bp = vtk_util.BeachballPipe(
        #     positions,
        #     m6s,
        #     sizes,
        #     depths,
        #     self.ren)
        #
        # self.bp = bp
        #
        # self.add_actor(bp.actor)
        # #####

    def export_image(self):

        caption = 'Export Image'
        fn_out, _ = fnpatch(qw.QFileDialog.getSaveFileName(
            self, caption, 'image.png',
            options=common.qfiledialog_options))

        if fn_out:
            self.save_image(fn_out)

    def save_image(self, path):
        self.showFullScreen()
        self.update_view()
        self.gui_state.panels_visible = False
        self.update_view()
        self.vtk_widget.setFixedSize(qc.QSize(1920, 1080))

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

        self.showNormal()
        self.gui_state.panels_visible = True

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
        self._animation_timer.setInterval(interpolator.dt * 1000.)
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

        print('<<<<<<<<<<')

        for tag, path, _ in self.state.diff(state):
            print('diff', tag, path)

        print('---')
        for el in self.state.elements:
            print('<  ', type(el).__name__, el.element_id, id(el))
        print('---')
        for el in state.elements:
            print('>  ', type(el).__name__, el.element_id, id(el))
        print('---')

        self.state.diff_update(state)

        print('---')
        for el in self.state.elements:
            print('  ', type(el).__name__, el.element_id, id(el))
        print('---')

        self.setUpdatesEnabled(True)
        print('>>>>>>>>>>>>')

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

        if use_pyqt5:
            angle = event.angleDelta().y()
        else:
            angle = event.delta()

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

    def key_up_event(self, obj, event):
        s = obj.GetKeySym()
        if s == 'Control_L':
            self.gui_state.next_focal_point()

    def _state_bind(self, *args, **kwargs):
        vstate.state_bind(self, self.state, *args, **kwargs)

    def _gui_state_bind(self, *args, **kwargs):
        vstate.state_bind(self, self.gui_state, *args, **kwargs)

    def controls(self):
        frame = qw.QFrame(self)
        layout = qw.QGridLayout()
        frame.setLayout(layout)

        layout.addWidget(qw.QLabel('Location'), 0, 0)
        le = qw.QLineEdit()
        layout.addWidget(le, 0, 1)

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

        layout.addWidget(qw.QLabel('Strike, Dip'), 1, 0)
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
            widget.setChecked(self.gui_state.focal_point != 'center')
            widget.blockSignals(False)

        def checkbox_to_focal_point(widget, state):
            self.gui_state.focal_point = \
                'target' if widget.isChecked() else 'center'

        self._gui_state_bind(
            ['focal_point'], checkbox_to_focal_point,
            cb, [cb.toggled], focal_point_to_checkbox)

        self.focal_point_checkbox = cb

        but = qw.QPushButton('Reset')
        but.clicked.connect(self.reset_strike_dip)
        layout.addWidget(but, 2, 1)

        update_camera = self.update_camera        # this assignment is
        update_render_settings = self.update_render_settings

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

        # lighting

        layout.addWidget(qw.QLabel('Lighting'), 4, 0)

        cb = common.string_choices_to_combobox(vstate.LightingChoice)
        layout.addWidget(cb, 4, 1)
        vstate.state_bind_combobox(self, self.state, 'lighting', cb)

        self.register_state_listener(update_render_settings)
        self.state.add_listener(update_render_settings, 'lighting')

        # background

        layout.addWidget(qw.QLabel('Background'), 5, 0)

        cb = common.strings_to_combobox(
            ['black', 'white', 'skyblue1 - white'])

        layout.addWidget(cb, 5, 1)
        vstate.state_bind_combobox_background(
            self, self.state, 'background', cb)

        self.register_state_listener(update_render_settings)
        self.state.add_listener(update_render_settings, 'background')

        # time

        layout.addWidget(qw.QLabel('T<sub>MIN</sub>'), 6, 0)
        le_tmin = qw.QLineEdit()
        layout.addWidget(le_tmin, 6, 1)

        layout.addWidget(qw.QLabel('T<sub>MAX</sub>'), 7, 0)
        le_tmax = qw.QLineEdit()
        layout.addWidget(le_tmax, 7, 1)

        def time_to_lineedit(state, attribute, widget):
            from pyrocko.util import time_to_str

            sel = widget.selectedText() == widget.text() \
                and widget.text() != ''

            if getattr(state, attribute) is None:
                widget.setText('')
            else:
                widget.setText('%s' % (time_to_str(
                    getattr(state, attribute), format='%Y-%m-%d %H:%M')))
            if sel:
                widget.selectAll()

        def lineedit_to_time(widget, state, attribute):
            from pyrocko.util import str_to_time

            s = str(widget.text())
            if not s.strip():
                setattr(state, attribute, None)
            else:
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

        range_edit = RangeEdit()
        range_edit.set_data_provider(self)
        range_edit.set_data_name('time')

        def range_to_range_edit(state, widget):
            widget.blockSignals(True)
            widget.set_range(state.tmin, state.tmax)
            widget.blockSignals(False)

        def range_edit_to_range(widget, state):
            self.state.tmin, self.state.tmax = widget.get_range()

        self._state_bind(
            ['tmin', 'tmax'], range_edit_to_range,
            range_edit, [range_edit.rangeChanged], range_to_range_edit)

        layout.addWidget(range_edit, 8, 0, 1, 2)

        layout.addWidget(ZeroFrame(), 9, 0, 1, 2)

        return frame

    def snapshots_panel(self):
        return snapshots_mod.SnapshotsPanel(self)

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

        nwrap = 3
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
            import qdarkgraystyle
            app.setStyleSheet(qdarkgraystyle.load_stylesheet())
            # import qdarkstyle
            #
            # if use_pyqt5:
            #     app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt5())
            # else:
            #     app.setStyleSheet(qdarkstyle.load_stylesheet_pyqt())

        except ImportError:
            logger.info(
                'Module qdarkgraystyle not available.\n'
                'If wanted, install qdarkstyle with "pip install qdarkgraystyle".')

    win = Viewer(*args, **kwargs)
    app.set_main_window(win)

    app.install_sigint_handler()
    app.exec_()
    app.uninstall_sigint_handler()

    app.set_main_window(None)

    del win

    gc.collect()
