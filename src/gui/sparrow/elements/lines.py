# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko.guts import Bool, Float, List, String
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.gui import vtk_util
import vtk

from .base import Element, ElementState

from .. import common

guts_prefix = 'sparrow'

km = 1e3


class LinesState(ElementState):
    visible = Bool.T(default=True)
    line_width = Float.T(default=1.0)
    paths = List.T(String.T())

    def create(self):
        element = LinesElement()
        element.bind_state(self)
        return element


class LinesPipe(object):
    def __init__(self, lines):

        self._opacity = 1.0
        self._line_width = 1.0

        self._actors = {}

        mapper = vtk.vtkDataSetMapper()

        grid = vtk_util.make_multi_polyline(
            lines_latlondepth=lines)

        vtk_util.vtk_set_input(mapper, grid)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        self._actor = actor

    def set_color(self, color):
        actor = self._actor
        prop = actor.GetProperty()
        prop.SetDiffuseColor(1.0, 1.0, 1.0)

    def set_opacity(self, opacity):
        opacity = float(opacity)
        if self._opacity != opacity:
            self._actor.GetProperty().SetOpacity(opacity)

            self._opacity = opacity

    def set_line_width(self, width):
        width = float(width)
        if self._line_width != width:
            self._actor.GetProperty().SetLineWidth(width)

            self._line_width = width

    def get_actors(self):
        return [self._actor]


class LinesElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._pipe = None
        self._paths = None
        self._controls = None

    def bind_state(self, state):
        Element.bind_state(self, state)
        self.register_state_listener3(self.update, state, 'paths')
        self.register_state_listener3(self.update, state, 'visible')
        self.register_state_listener3(self.update, state, 'line_width')

    def get_name(self):
        return 'Lines'

    def set_parent(self, parent):
        Element.set_parent(self, parent)

        self._parent.add_panel(
            self.get_name(),
            self._get_controls(),
            visible=True,
            remove=self.remove)

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:
            if self._pipe:
                for actor in self._pipe.get_actors():
                    self._parent.remove_actor(actor)

                self._pipe = None

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def open_file_dialog(self):
        caption = 'Select one or more files to open'

        fns, _ = qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options)

        self._state.paths = [str(fn) for fn in fns]

    def load(self, paths):
        lines = [num.loadtxt(path) for path in paths]
        return lines

    def update(self, *args):

        state = self._state
        if state.paths is not self._paths:
            lines = self.load(state.paths)
            if self._pipe:
                for actor in self._pipe.get_actors():
                    self._parent.remove_actor(actor)

            self._pipe = LinesPipe(lines)
            self._paths = state.paths

        if self._pipe:
            self._pipe.set_line_width(state.line_width)

            if state.visible:
                for actor in self._pipe.get_actors():
                    self._parent.add_actor(actor)

            else:
                for actor in self._pipe.get_actors():
                    self._parent.remove_actor(actor)

        self._parent.update_view()

    def _get_controls(self):
        if self._controls is None:
            from ..state import state_bind_checkbox, state_bind_slider

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            layout.setAlignment(qc.Qt.AlignTop)
            frame.setLayout(layout)

            lab = qw.QLabel('Load from:')
            pb_file = qw.QPushButton('File')

            layout.addWidget(lab, 0, 0)
            layout.addWidget(pb_file, 0, 1)

            pb_file.clicked.connect(self.open_file_dialog)

            layout.addWidget(qw.QLabel('Line width'), 1, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(10)
            slider.setSingleStep(1)
            slider.setPageStep(1)
            layout.addWidget(slider, 1, 1)
            state_bind_slider(self, self._state, 'line_width', slider)

            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, 2, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            self._controls = frame

        return self._controls


__all__ = [
    'LinesElement',
    'LinesState'
]
