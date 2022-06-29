# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, print_function, division

import string

import numpy as num

from pyrocko.guts import Bool, Float, Object, String

from pyrocko import cake, geometry, gf
from pyrocko.gui.qt_compat import qc, qw
from pyrocko.gui.talkie import TalkieRoot

from pyrocko.gui.vtk_util import \
    ArrowPipe, ColorbarPipe, PolygonPipe, ScatterPipe, OutlinesPipe

from .. import state as vstate
from .. import common
from . import base

guts_prefix = 'sparrow'


d2r = num.pi / 180.


map_anchor = {
    'center': (0.0, 0.0),
    'center_left': (-1.0, 0.0),
    'center_right': (1.0, 0.0),
    'top': (0.0, -1.0),
    'top_left': (-1.0, -1.0),
    'top_right': (1.0, -1.0),
    'bottom': (0.0, 1.0),
    'bottom_left': (-1.0, 1.0),
    'bottom_right': (1.0, 1.0)}


class ProxySource(TalkieRoot):
    pass


for source_cls in [gf.RectangularSource]:

    cls_name = 'Proxy' + source_cls.__name__

    class proxy_source_cls(ProxySource):
        class_name = cls_name

        def __init__(self, **kwargs):
            ProxySource.__init__(self)
            for key, value in self._ranges.items():
                setattr(self, key, value['ini'])

            if kwargs is not None:
                for it in kwargs.items():
                    setattr(self, it[0], it[1])

    proxy_source_cls.__name__ = cls_name
    vars()[cls_name] = proxy_source_cls

    for prop in source_cls.T.properties:
        proxy_source_cls.T.add_property(prop.name, prop)

ProxyRectangularSource = vars()['ProxyRectangularSource']  # silence flake8

ProxyRectangularSource._name = 'RectangularSource'

ProxyRectangularSource._ranges = {
    'lat': {'min': -90., 'max': 90., 'step': 1, 'ini': 0.},
    'lon': {'min': -180., 'max': 180., 'step': 1, 'ini': 0.},
    'depth': {'min': 0., 'max': 600000., 'step': 1000, 'ini': 10000.},
    'width': {'min': 0.1, 'max': 500000., 'step': 1000, 'ini': 10000.},
    'length': {'min': 0.1, 'max': 1000000., 'step': 1000, 'ini': 50000.},
    'strike': {'min': -180., 'max': 180., 'step': 1, 'ini': 0.},
    'dip': {'min': 0., 'max': 90., 'step': 1, 'ini': 45.},
    'rake': {'min': -180., 'max': 180., 'step': 1, 'ini': 0.},
    'nucleation_x':
        {'min': -100., 'max': 100., 'step': 1, 'ini': 0., 'fac': .01},
    'nucleation_y':
        {'min': -100., 'max': 100., 'step': 1, 'ini': 0., 'fac': .01},
    'slip': {'min': 0., 'max': 1000., 'step': 1, 'ini': 1., 'fac': .01}}


class ProxyConfig(Object):
    deltas = num.array([1000., 1000.])
    deltat = Float.T(default=0.5)
    rho = Float.T(default=2800)
    vs = Float.T(default=3600)

    def get_shear_moduli(self, *args, **kwargs):
        points = kwargs.get('points')
        return num.ones(len(points)) * num.power(self.vs, 2) * self.rho


class ProxyStore(Object):
    def __init__(self, **kwargs):
        config = ProxyConfig()
        if kwargs:
            config.deltas = kwargs.get('deltas', config.deltas)
            config.deltat = kwargs.get('deltat', config.deltat)
            config.rho = kwargs.get('rho', config.rho)
            config.vs = kwargs.get('vs', config.vs)

        self.config = config
        self.mode = String.T(default='r')
        self._f_data = None
        self._f_index = None


parameter_label = {
    'time (s)': 'times'}


class SourceState(base.ElementState):
    visible = Bool.T(default=True)
    source_selection = ProxySource.T(default=ProxyRectangularSource())  # noqa
    deltat = Float.T(default=0.5)
    display_parameter = String.T(default='time (s)')
    cpt = base.CPTState.T(default=base.CPTState.D())

    @classmethod
    def get_name(self):
        return 'Source'

    def create(self):
        element = SourceElement()
        return element


class SourceElement(base.Element):

    def __init__(self):
        base.Element.__init__(self)
        self._parent = None
        self._pipe = []
        self._controls = None
        self._points = num.array([])

        self.cpt_handler = base.CPTHandler()

    def _state_bind_source(self, *args, **kwargs):
        vstate.state_bind(self, self._state.source_selection, *args, **kwargs)

    def _state_bind_store(self, *args, **kwargs):
        vstate.state_bind(self, self._state, *args, **kwargs)

    def bind_state(self, state):
        base.Element.bind_state(self, state)
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'source_selection')
        state.add_listener(upd, 'deltat')
        state.add_listener(upd, 'display_parameter')
        self.cpt_handler.bind_state(state.cpt, upd)

    def unbind_state(self):
        self._listeners = []
        self._state = None
        self.cpt_handler.unbind_state()

    def get_name(self):
        return 'Source'

    def set_parent(self, parent):
        self._parent = parent
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)
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

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def open_file_load_dialog(self):
        caption = 'Select one file to open'
        fns, _ = qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options)

        if fns:
            try:
                self.load_file(str(fns[0]))
            except gf.FileNotFoundError as e:
                raise e

        else:
            return

    def load_source_file(self, path):
        loaded_source = gf.load(filename=path)
        source = ProxyRectangularSource(
            **{prop: getattr(loaded_source, prop)
                for prop in loaded_source.T.propnames
                if getattr(loaded_source, prop)})

        self._parent.remove_panel(self._controls)
        self._controls = None
        self._state.source_selection = source
        self._parent.add_panel(
            self.get_name(), self._get_controls(), visible=True)

        self.update()

    def open_file_save_dialog(self, fn=None):
        caption = 'Choose a file name to write source'
        if not fn:
            fn, _ = qw.QFileDialog.getSaveFileName(
                self._parent, caption, options=common.qfiledialog_options)
        if fn:
            self.save_file(str(fn))

    def save_file(self, path):
        source = self._state.source_selection
        source2dump = gf.RectangularSource(
            **{prop: getattr(source, prop) for prop in source.T.propnames})

        if path.split('.')[-1].lower() in ['xml']:
            source2dump.dump_xml(filename=path)
        else:
            source2dump.dump(filename=path)

    def update_loc(self, *args):
        pstate = self._parent.state
        state = self._state

        source = state.source_selection
        source.lat = pstate.lat
        source.lon = pstate.lon

        self._state.source_selection.source = source

        self.update()

    def update_source(self, store):
        state = self._state

        source = state.source_selection
        source_list = gf.source_classes

        for i, a in enumerate(source_list):
            if a.__name__ is source._name:
                fault = a(
                    **{prop: source.__dict__[prop]
                        for prop in source.T.propnames})

                source_geom = fault.geometry(store)

                self._update_outlines(source_geom)
                self._update_scatter(source, fault)
                self._update_raster(source_geom, state.display_parameter)
                self._update_rake_arrow(fault)

    def _update_outlines(self, source_geom):

        if source_geom.outlines:
            self._pipe.append(OutlinesPipe(
                source_geom, color=(1., 1., 1.), cs='latlondepth'))
            self._parent.add_actor(
                self._pipe[-1].actor)

            self._pipe.append(OutlinesPipe(
                source_geom, color=(0.6, 0.6, 0.6), cs='latlon'))
            self._parent.add_actor(
                self._pipe[-1].actor)

    def _update_scatter(self, source, fault):
        for point, color in zip(
                ((source.nucleation_x,
                  source.nucleation_y),
                 map_anchor[source.anchor]),
                (num.array([[1., 0., 0.]]),
                 num.array([[0., 0., 1.]]))):

            points = geometry.latlondepth2xyz(
                fault.xy_to_coord(
                    x=[point[0]], y=[point[1]],
                    cs='latlondepth'),
                planetradius=cake.earthradius)

            vertices = geometry.arr_vertices(points)
            p = ScatterPipe(vertices)
            p.set_symbol('sphere')
            p.set_colors(color)
            self._pipe.append(p)
            self._parent.add_actor(p.actor)

    def _update_raster(self, source_geom, param):
        vertices = geometry.arr_vertices(
            source_geom.get_vertices(col='xyz'))

        faces = source_geom.get_faces()

        if parameter_label[param] == 'times' and \
                source_geom.has_property('t_arrival'):

            self.cpt_handler._values = source_geom.get_property('t_arrival')
            cbar_title = 'T arr [s]'

        self.cpt_handler.update_cpt()

        poly_pipe = PolygonPipe(
            vertices, faces,
            values=self.cpt_handler._values, lut=self.cpt_handler._lookuptable)

        self._pipe.append(poly_pipe)
        self._parent.add_actor(self._pipe[-1].actor)

        if cbar_title is not None:
            cbar_pipe = ColorbarPipe(
                parent_pipe=poly_pipe, cbar_title=cbar_title,
                lut=self.cpt_handler._lookuptable)

            self._pipe.append(cbar_pipe)
            self._parent.add_actor(self._pipe[-1].actor)

    def _update_rake_arrow(self, fault):
        source = self._state.source_selection
        rake = source.rake * d2r

        nucl_x = source.nucleation_x
        nucl_y = source.nucleation_y

        wd_ln = source.width / source.length

        endpoint = [None] * 2
        endpoint[0] = nucl_x + num.cos(rake) * wd_ln
        endpoint[1] = nucl_y + num.sin(-rake)

        points = geometry.latlondepth2xyz(
            fault.xy_to_coord(
                x=[nucl_x, endpoint[0]],
                y=[nucl_y, endpoint[1]],
                cs='latlondepth'),
            planetradius=cake.earthradius)
        vertices = geometry.arr_vertices(points)

        self._pipe.append(ArrowPipe(vertices[0], vertices[1]))
        self._parent.add_actor(self._pipe[-1].actor)

    def update(self, *args):
        state = self._state

        store = ProxyStore(
            deltat=state.deltat)
        store.config.deltas = num.array(
            [(store.config.deltat * store.config.vs) + 1] * 2)

        if self._pipe:
            for pipe in self._pipe:
                self._parent.remove_actor(pipe.actor)

            self._pipe = []

        if state.visible:
            self.update_source(store)

        self._parent.update_view()

    def _get_controls(self):
        if not self._controls:
            from ..state import \
                state_bind_checkbox, state_bind_slider, state_bind_combobox
            from pyrocko import gf

            source = self._state.source_selection

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

            for il, label in enumerate(source.T.propnames):
                if label in source._ranges.keys():

                    layout.addWidget(qw.QLabel(
                        string.capwords(label) + ':'), il, 0)

                    slider = qw.QSlider(qc.Qt.Horizontal)
                    slider.setSizePolicy(
                        qw.QSizePolicy(
                            qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
                    slider.setMinimum(
                        int(round(source._ranges[label]['min'])))
                    slider.setMaximum(
                        int(round(source._ranges[label]['max'])))
                    slider.setSingleStep(
                        int(round(source._ranges[label]['step'])))
                    slider.setPageStep(
                        int(round(source._ranges[label]['step'])))

                    layout.addWidget(slider, il, 1)
                    try:
                        state_bind_slider(
                            self, self._state.source_selection, label, slider,
                            factor=source._ranges[label]['fac'])
                    except Exception:
                        state_bind_slider(
                            self, self._state.source_selection, label, slider)

                    le = qw.QLineEdit()
                    layout.addWidget(le, il, 2)

                    self._state_bind_source(
                        [label], lineedit_to_state, le,
                        [le.editingFinished, le.returnPressed],
                        state_to_lineedit, attribute=label)

            for label, name in zip(
                    ['GF dt:'], ['deltat']):
                il += 1
                layout.addWidget(qw.QLabel(label), il, 0)
                slider = qw.QSlider(qc.Qt.Horizontal)
                slider.setSizePolicy(
                    qw.QSizePolicy(
                        qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
                slider.setMinimum(1)
                slider.setMaximum(1000)
                slider.setSingleStep(1)
                slider.setPageStep(1)
                layout.addWidget(slider, il, 1)
                state_bind_slider(
                    self, self._state, name, slider, factor=0.01)

                le = qw.QLineEdit()
                layout.addWidget(le, il, 2)

                self._state_bind_store(
                    [name], lineedit_to_state, le,
                    [le.editingFinished, le.returnPressed],
                    state_to_lineedit, attribute=name)

            il += 1
            layout.addWidget(qw.QLabel('Anchor:'), il, 0)

            cb = qw.QComboBox()
            for i, s in enumerate(gf.RectangularSource.anchor.choices):
                cb.insertItem(i, s)
            layout.addWidget(cb, il, 1, 1, 2)
            state_bind_combobox(
                self, self._state.source_selection, 'anchor', cb)

            il += 1
            layout.addWidget(qw.QLabel('Display Param.:'), il, 0)

            cb = qw.QComboBox()
            for i, s in enumerate(parameter_label.keys()):
                cb.insertItem(i, s)
            layout.addWidget(cb, il, 1)
            state_bind_combobox(
                self, self._state, 'display_parameter', cb)

            self.cpt_handler.cpt_controls(
                self._parent, self._state.cpt, layout)

            il = layout.rowCount() + 1
            pb = qw.QPushButton('Move Source Here')
            layout.addWidget(pb, il, 0)
            pb.clicked.connect(self.update_loc)

            pb = qw.QPushButton('Load')
            layout.addWidget(pb, il, 1)
            pb.clicked.connect(self.open_file_load_dialog)

            pb = qw.QPushButton('Save')
            layout.addWidget(pb, il, 2)
            pb.clicked.connect(self.open_file_save_dialog)

            il += 1
            cb = qw.QCheckBox('Show')
            layout.addWidget(cb, il, 0)
            state_bind_checkbox(self, self._state, 'visible', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, il, 2)
            pb.clicked.connect(self.remove)

            il += 1
            layout.addWidget(qw.QFrame(), il, 0, 1, 3)

        self._controls = frame

        self.cpt_handler._update_cpt_combobox()
        self.cpt_handler._update_cptscale_lineedit()

        return self._controls


__all__ = [
    'SourceElement',
    'SourceState',
]
