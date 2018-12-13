# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import vtk

from pyrocko.guts import Bool, StringChoice
from pyrocko.gui.qt_compat import qw


from pyrocko.gui import vtk_util
from .. import common
from .base import Element, ElementState

guts_prefix = 'sparrow'


class CoastlineResolutionChoice(StringChoice):
    choices = [
        'crude',
        'low',
        'intermediate',
        'high',
        'full']


class CoastlinesPipe(object):
    def __init__(self, resolution='low'):

        self.mapper = vtk.vtkDataSetMapper()
        self._polyline_grid = {}
        self.set_resolution(resolution)

        actor = vtk.vtkActor()
        actor.SetMapper(self.mapper)

        prop = actor.GetProperty()
        prop.SetDiffuseColor(1, 1, 1)
        prop.SetOpacity(0.3)

        self.actor = actor

    def set_resolution(self, resolution):
        assert resolution in CoastlineResolutionChoice.choices

        if resolution not in self._polyline_grid:
            from ..main import app
            pb = app.get_progressbars()
            if pb:
                mess = 'Loading %s resolution coastlines' % resolution
                pb.set_status(mess, 0, can_abort=False)

            from pyrocko.dataset.gshhg import GSHHG
            g = getattr(GSHHG, resolution)()

            lines = []
            npoly = len(g.polygons)
            for ipoly, poly in enumerate(g.polygons):
                if pb:
                    pb.set_status(
                        mess, float(ipoly) / npoly * 100., can_abort=False)

                lines.append(poly.points)

            self._polyline_grid[resolution] = vtk_util.make_multi_polyline(
                lines_latlon=lines)

            if pb:
                pb.set_status(mess, 100, can_abort=False)

        vtk_util.vtk_set_input(self.mapper, self._polyline_grid[resolution])


class CoastlinesState(ElementState):
    visible = Bool.T(default=True)
    resolution = CoastlineResolutionChoice.T(default='low')

    def create(self):
        element = CoastlinesElement()
        element.bind_state(self)
        return element


class CoastlinesElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._controls = None
        self._coastlines = None

    def get_name(self):
        return 'Coastlines'

    def bind_state(self, state):
        upd = self.update
        self._listeners = [upd]
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'resolution')
        self._state = state

    def unbind_state(self):
        self._listeners = []

    def set_parent(self, parent):
        self._parent = parent
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._coastlines:
                self._parent.remove_actor(self._coastlines.actor)
                self._coastlines = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def update(self, *args):
        state = self._state
        if not state.visible and self._coastlines:
            self._parent.remove_actor(self._coastlines.actor)

        if state.visible:
            if not self._coastlines:
                self._coastlines = CoastlinesPipe(resolution=state.resolution)

            self._parent.add_actor(self._coastlines.actor)
            self._coastlines.set_resolution(state.resolution)

        self._parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_combobox, \
                state_bind_checkbox

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            layout.addWidget(qw.QLabel('Resolution'), 0, 0)

            cb = common.string_choices_to_combobox(CoastlineResolutionChoice)
            layout.addWidget(cb, 0, 1)
            state_bind_combobox(self, self._state, 'resolution', cb)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 1, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, 1, 1)
            pb.clicked.connect(self.unset_parent)

            layout.addWidget(qw.QFrame(), 2, 0, 1, 2)

        self._controls = frame

        return self._controls


__all__ = [
    'CoastlinesElement',
    'CoastlinesState']
