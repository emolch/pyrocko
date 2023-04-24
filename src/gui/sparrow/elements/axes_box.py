# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
import vtk
import numpy as num

from pyrocko import geometry, cake, orthodrome as od
from pyrocko.guts import Bool, Float
from pyrocko.gui.qt_compat import qw, qc

from pyrocko.gui.vtk_util import Color

from .base import Element, ElementState

import string

from .. import common, state as vstate


guts_prefix = 'sparrow'

km = 1e3


class AxisPipe(object):

    def __init__(self, start_point, end_point, axis_range, axis_type):

        available_types = ['X', 'Y', 'Z']
        if axis_type not in available_types:
            raise TypeError('Axis type %s not available!' % axis_type)

        self._axis_type = axis_type

        self.start_point = start_point
        self.end_point = end_point
        self.axis_range = axis_range

        min_bounds = num.minimum(start_point, end_point)
        max_bounds = num.maximum(start_point, end_point)
        bounds = num.vstack((min_bounds, max_bounds)).ravel('f')

        ax = vtk.vtkAxisActor()
        ax.SetPoint1(*start_point)
        ax.SetPoint2(*end_point)
        ax.SetRange(*axis_range)
        ax.SetBounds(*bounds)

        self.actor = ax

    def vector(self):
        return self.start_point - self.end_point

    def length(self):
        return num.linalg.norm(self.vector())

    def unit_vector(self):
        xyz = self.vector()
        return xyz / num.linalg.norm(xyz)

    def set_label_size(self, label_size):
        self.actor.SetTitleScale(label_size)
        self.actor.SetLabelScale(label_size)

    def set_tick_size(self, tick_size):
        self.actor.SetMajorTickSize(tick_size)

    def set_ticks(self, delta):

        self.actor.SetDeltaRangeMajor(delta)
        self.actor.SetMajorRangeStart(self.axis_range[0])
        self.actor.SetMajorStart(0, self.axis_range[0])
        self.actor.SetTickLocationToInside()  # Outside/Both/Inside
        nticks = int(
            round((self.axis_range[1] - self.axis_range[0]) / delta)) + 1

        labels = vtk.vtkStringArray()
        labels.SetNumberOfTuples(nticks)
        for i in range(nticks):
            if self._axis_type == 'Z':
                tick_value = (self.axis_range[1] - i * delta) / 1e3
            else:
                tick_value = (self.axis_range[0] + i * delta) / 1e3

            labels.SetValue(i, '%0.1f' % tick_value)

        self.actor.SetLabels(labels)
        self.actor.SetCalculateLabelOffset(0)

    def set_colors(self, color):
        tprop = self.actor.GetTitleTextProperty()
        tprop.SetColor(color.rgb)
        tprop.SetBackgroundColor(color.rgb)
        tprop.SetFontFamilyToArial()

        lprop = self.actor.GetLabelTextProperty()
        lprop.SetColor(color.rgb)
        lprop.SetFontFamilyToArial()

        self.actor.GetAxisLinesProperty().SetColor(color.rgb)
        self.actor.GetAxisMajorTicksProperty().SetColor(color.rgb)

    def set_linewidth(self, linewidth):
        self.actor.GetAxisLinesProperty().SetLineWidth(linewidth)
        self.actor.GetAxisMajorTicksProperty().SetLineWidth(linewidth)

    def set_axes_base(self, basex, basey, basez):
        self.actor.SetAxisBaseForX(*basex)
        self.actor.SetAxisBaseForY(*basey)
        self.actor.SetAxisBaseForZ(*basez)

        getattr(self.actor, "SetAxisTypeTo%s" % self._axis_type)()


class BoxPipe(object):

    def __init__(self, width, length, height, lat, lon, depth, camera):

        self._line_width = None
        self._color = Color('white')

        origin_xyz = geometry.latlondepth2xyz(
                num.atleast_2d(num.array((lat, lon, depth))),
                planetradius=cake.earthradius)
        z_top = geometry.latlondepth2xyz(
                num.atleast_2d(num.array((lat, lon, depth - height))),
                planetradius=cake.earthradius)

        lat2, lon2 = od.ne_to_latlon(lat, lon, 0, length)
        x_east = geometry.latlondepth2xyz(
                num.atleast_2d(num.array((lat2, lon2, depth))),
                planetradius=cake.earthradius)

        lat3, lon3 = od.ne_to_latlon(lat, lon, width, 0)
        y_north = geometry.latlondepth2xyz(
                num.atleast_2d(num.array((lat3, lon3, depth))),
                planetradius=cake.earthradius)

        xax_range = (0, length)
        yax_range = (0, width)
        zax_range = (depth - height, depth)

        end_points = [x_east, y_north, z_top]
        axis_ranges = [xax_range, yax_range, zax_range]
        labels = ['E-Distance [km]', 'N-Distance [km]', 'Depth [km]']
        axis_types = ['X', 'Y', 'Z']

        vector_base = []
        self.axes = []
        for end_point, axis_range, label, axis_type in zip(
                end_points, axis_ranges, labels, axis_types):

            ax = AxisPipe(
                start_point=origin_xyz,
                end_point=end_point,
                axis_range=axis_range,
                axis_type=axis_type)

            ax.actor.SetTitle(label)
            ax.set_colors(self._color)
            ax.actor.SetCamera(camera)

            # correct tick rotation around the globe
            vector_base.append(ax.unit_vector())
            self.axes.append(ax)

        for ax in self.axes:
            ax.set_axes_base(*vector_base)

    @property
    def actor(self):
        return [ax.actor for ax in self.axes]

    def set_color(self, color):
        if color != self._color:
            for ax in self.axes:
                ax.set_colors(color)

            self._color = color

    def set_label_size(self, label_size):
        for ax in self.axes:
            ax.set_label_size(label_size)

        self._label_size = label_size

    def set_line_width(self, linewidth):
        linewidth = float(linewidth)
        if self._line_width != linewidth:
            for ax in self.axes:
                ax.set_linewidth(linewidth)

            self._line_width = linewidth

    def set_ticks(self, tick_size, delta):
        '''
        Set tick size of all axes to smallest tick-size.
        '''
        for ax in self.axes:
            ax.set_ticks(delta=delta)
            ax.set_tick_size(tick_size)


box_ranges = {
    'lat': {'min': -90., 'max': 90., 'step': 1, 'ini': 0.},
    'lon': {'min': -180., 'max': 180., 'step': 1, 'ini': 0.},
    'depth': {'min': 0., 'max': 600 * km, 'step': 1 * km, 'ini': 10. * km},
    'width': {'min': 0.1, 'max': 1000. * km, 'step': 1 * km, 'ini': 10. * km},
    'length': {'min': 0.1, 'max': 1000. * km, 'step': 1 * km, 'ini': 50. * km},
    'height': {'min': 0.1, 'max': 500. * km, 'step': 1 * km, 'ini': 10. * km},
    'delta': {'min': 0.01, 'max': 250. * km, 'step': 1 * km, 'ini': 5. * km}}


class AxesBoxState(ElementState):
    visible = Bool.T(default=True)
    width = Float.T(default=20.0 * km)
    length = Float.T(default=20.0 * km)
    height = Float.T(default=10.0 * km)
    lat = Float.T(default=0.0)
    lon = Float.T(default=0.0)
    depth = Float.T(default=5. * km)
    color = Color.T(default=Color.D('white'))
    line_width = Float.T(default=1.0)
    label_size = Float.T(default=0.0001)
    tick_size = Float.T(default=0.0001)
    delta = Float.T(default=5 * km)

    def create(self):
        element = AxesBoxElement()
        return element


class AxesBoxElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._pipe = []
        self._controls = None

    def bind_state(self, state):
        Element.bind_state(self, state)

        self.talkie_connect(
            state,
            ['visible', 'width', 'length', 'height', 'lat', 'lon', 'depth',
             'color', 'line_width', 'label_size', 'tick_size', 'delta'],
            self.update)

    def _state_bind_box(self, *args, **kwargs):
        vstate.state_bind(self, self._state, *args, **kwargs)

    def get_name(self):
        return 'AxesBox'

    def set_parent(self, parent):
        self._parent = parent

        self._parent.add_panel(
            self.get_title_label(),
            self._get_controls(),
            visible=True,
            title_controls=[
                self.get_title_control_remove(),
                self.get_title_control_visible()])

        self.update()

    def unset_parent(self):
        self.unbind_state()
        if self._parent:

            if self._pipe:
                for pipe in self._pipe:
                    if isinstance(pipe.actor, list):
                        for act in pipe.actor:
                            self._parent.remove_actor(act)
                    else:
                        self._parent.remove_actor(pipe.actor)
                self._pipe = []

            if self._controls is not None:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def update_box(self):

        state = self._state

        camera = self._parent.ren.GetActiveCamera()
        box_pipe = BoxPipe(
            state.width, state.length, state.height,
            state.lat, state.lon, state.depth, camera)
        box_pipe.set_color(state.color)
        box_pipe.set_line_width(state.line_width)
        box_pipe.set_ticks(state.tick_size, state.delta)
        box_pipe.set_label_size(state.label_size)

        self._pipe.append(box_pipe)

        for actor in box_pipe.actor:
            self._parent.add_actor(actor)

    def update(self, *args):
        state = self._state

        if self._pipe:
            for pipe in self._pipe:
                if isinstance(pipe.actor, list):
                    for actor in pipe.actor:
                        self._parent.remove_actor(actor)
                else:
                    self._parent.remove_actor(pipe.actor)

            self._pipe = []

        if state.visible:
            self.update_box()

        self._parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import state_bind_slider, state_bind_combobox_color

            frame = qw.QFrame()
            layout = qw.QGridLayout()
            frame.setLayout(layout)

            def state_to_lineedit(state, attribute, widget):
                sel = getattr(state, attribute)

                widget.setText('%g' % sel)
                # if sel:
                #     widget.selectAll()

            def lineedit_to_state(widget, state, attribute):
                s = float(widget.text())
                try:
                    setattr(state, attribute, s)
                except Exception:
                    raise ValueError(
                        'Value of %s needs to be a float or integer'
                        % string.capwords(attribute))

            for il, label in enumerate(box_ranges.keys()):
                layout.addWidget(qw.QLabel(
                    string.capwords(label) + ':'), il, 0)

                slider = qw.QSlider(qc.Qt.Horizontal)
                slider.setSizePolicy(
                    qw.QSizePolicy(
                        qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
                slider.setMinimum(
                    int(round(box_ranges[label]['min'])))
                slider.setMaximum(
                    int(round(box_ranges[label]['max'])))
                slider.setSingleStep(
                    int(round(box_ranges[label]['step'])))
                slider.setPageStep(
                    int(round(box_ranges[label]['step'])))

                layout.addWidget(slider, il, 1)

                try:
                    state_bind_slider(
                        self, self._state, label, slider,
                        factor=box_ranges[label]['fac'])
                except Exception:
                    state_bind_slider(
                        self, self._state, label, slider)

                le = qw.QLineEdit()
                layout.addWidget(le, il, 2)

                self._state_bind_box(
                    [label], lineedit_to_state, le,
                    [le.editingFinished, le.returnPressed],
                    state_to_lineedit, attribute=label)

            # color
            il += 1
            layout.addWidget(qw.QLabel('Color'), il, 0)

            cb = common.strings_to_combobox(
                ['black', 'white'])

            layout.addWidget(cb, il, 1)
            state_bind_combobox_color(
                self, self._state, 'color', cb)

            # linewidth
            il += 1
            layout.addWidget(qw.QLabel('Line width'), il, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(0)
            slider.setMaximum(100)
            layout.addWidget(slider, il, 1)
            state_bind_slider(
                self, self._state, 'line_width', slider, factor=0.1)

            # tick size
            il += 1
            layout.addWidget(qw.QLabel('tick size'), il, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(1)
            slider.setMaximum(1000)
            layout.addWidget(slider, il, 1)
            state_bind_slider(
                self, self._state, 'tick_size', slider, factor=0.00001)

            # label size
            il += 1
            layout.addWidget(qw.QLabel('label size'), il, 0)

            slider = qw.QSlider(qc.Qt.Horizontal)
            slider.setSizePolicy(
                qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
            slider.setMinimum(1)
            slider.setMaximum(1000)
            layout.addWidget(slider, il, 1)
            state_bind_slider(
                self, self._state, 'label_size', slider, factor=0.00001)

            self._controls = frame

        return self._controls


__all__ = [
    'AxesBoxElement',
    'AxesBoxState'
]
