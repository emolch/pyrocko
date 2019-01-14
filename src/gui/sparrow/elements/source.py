# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, print_function, division

import string

import numpy as num

import vtk

from pyrocko.guts import Bool, Float, Object, String, Tuple

from pyrocko import cake, geometry, gf, table
from pyrocko.orthodrome import latlon_to_ne_numpy
from pyrocko.modelling import OkadaSource, DislocProcessor
from pyrocko.gui.qt_compat import qw, qc, fnpatch

from pyrocko.gui.vtk_util import\
    ArrowPipe, Glyph3DPipe, PolygonPipe, ScatterPipe,\
    make_multi_polyline, vtk_set_input
from .. import state as vstate
from .. import common

from .base import Element, ElementState

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


def get_shift_zero_coord(source, *args):
    """Relative cartesian coordinates with respect to nucleation point.

    Get the north and east shift [m] between the nucleation point and the
    reference point of a rectangular fault (import for Okada routine)

    :param source: Rectangular Source
    ;type source: :py:class:`pyrocko.gf.RectangularSource`
    :param refloc: Location reference point
    :type refloc: :py:class:`pyrocko.orthodrome.Loc`

    :return: Northin and easting from nucleation point to ref_loc
    :rtype: tuple, float
    """
    ref_pt = source.points_on_source(
        points_x=[0.], points_y=[-1.],
        cs='latlon')

    return ref_pt, latlon_to_ne_numpy(ref_pt[0, 0], ref_pt[0, 1], *args)


def patches_to_okadasources(source_geom, source, **kwargs):
    """Compute list of Okada Sources out of given fault patches.

    For a given fault geometry with sub fault (patches), a list of Okada Source
    segments is populated and returned

    :param source_geom: Source geometry of extended source
    :type source_geom: :py:class:`pyrocko.gf.Geometry`
    :param source: Rectangular Source
    ;type source: :py:class:`pyrocko.gf.RectangularSource`

    :return: list of Okada Sources
    ;rtype: list
    """
    points = source_geom.patches.points
    ref_lat = points.get_col('ref_lat')[0]
    ref_lon = points.get_col('ref_lon')[0]

    ref_pt, (north_shift_diff, east_shift_diff) = get_shift_zero_coord(
        source, ref_lat, ref_lon)

    north_shift = points.get_col('north_shift') + north_shift_diff
    east_shift = points.get_col('east_shift') + east_shift_diff
    depth = points.get_col('depth')
    times = points.get_col('times')

    length = num.array([source_geom.patches.dl] * len(north_shift))
    width = num.array([source_geom.patches.dw] * len(north_shift))

    slip = num.array([source.slip] * len(north_shift))
    strike = num.array([source.strike] * len(north_shift))
    dip = num.array([source.dip] * len(north_shift))
    rake = num.array([source.rake] * len(north_shift))

    segments = [OkadaSource(
        lat=ref_pt[0, 0], lon=ref_pt[0, 1],
        north_shift=north_shift[i], east_shift=east_shift[i],
        depth=depth[i], length=length[i], width=width[i],
        time=times[i], slip=slip[i],
        strike=strike[i], dip=dip[i], rake=rake[i], **kwargs)
        for i in range(len(north_shift))]

    return segments, ref_pt


def receiver_to_okadacoords(receiver_geom, dim=2):
    """Build array of coordinate tuples (triples) for each receiver

    For a given receiver geometry, the north and east shift (in 2D) or the
    north, the east shift and the depth are concatenated in array

    :param receiver_geom: Receiver geometry containing lat, lon, depth
    :type receiver_geom: :py:class:`pyrocko.table.Table`
    :param dim: Dimension of coordinate array: 2 - easting, northing,
        3 - easting, northing, depth
    ;type dim: :py:class:`int`

    :return: array of receiver coordinates
    ;rtype: :py:class:`numpy.ndarray`, ``(Nxdim)
    """
    coords = num.empty((len(receiver_geom.get_col('north_shift')), dim))
    coords[:, 0] = receiver_geom.get_col('east_shift')
    coords[:, 1] = receiver_geom.get_col('north_shift')

    if dim == 3:
        coords[:, 2] = receiver_geom.get_col('depth')

    return coords


def okada_surface_displacement(
        source_geom, disp_window, source, dim=2, **kwargs):
    """Calculate Displacement due to Okada Sources for in certain window

    For a given source geometry and source, the surface displacements in 3D are
    calculated. The grid for displacement calculation is defined via a
    LatLonWindow.
    Assisiting functions are `:py:func:`patches_to_okadasources`,
    :py:func:`receiver_to_okadacoords`,
    :py:func:`DisplacementWindow.get_raster` and
    :py:func:`pyrocko.modelling.okada.DislocProcessor.process

    :param source_geom: Geometry of the source and its patches
    :type source_geom: :py:class:`pyrocko.gf.Geometry`
    :param disp_window: Definition of the Displacement Calculation Grid
    :type disp_window:
        :py:class:`pyrocko.gui.sparrow.elements.source.DisplacementWindow`
    :param source: Given extended source model
    :type source: :py:class:`pyrocko.gf.Source`
    :param dim: Dimension of the receiver coordinates
    :type dim: :py:class:`int`

    :return: Geometry of the Receiver and the calculated dislocations
    :rtype: :py:class:`pyrocko.table.Table` and :py:class:`dict`
    """
    segs, ref_pt = patches_to_okadasources(source_geom, source, **kwargs)

    receiver_geom = disp_window.get_raster(ref_pt[0, 0], ref_pt[0, 1])

    coords = receiver_to_okadacoords(
        receiver_geom, dim=dim)

    return receiver_geom, DislocProcessor.process(segs, coords)


class LatLonWindow(ElementState):
    pass


class DisplacementWindow(LatLonWindow):
    ne_corner = Tuple.T(default=(0.1, 0.1))
    sw_corner = Tuple.T(default=(-0.1, -0.1))
    n_grdpoints = Tuple.T(default=(10, 10))

    @property
    def corners(self):
        return num.vstack((self.ne_corner, self.sw_corner))

    def get_raster(self, ref_lat, ref_lon):
        raster = table.Table()
        raster.add_recipe(table.LocationRecipe())

        diff = num.array(latlon_to_ne_numpy(
            ref_lat, ref_lon, self.corners[:, 0], self.corners[:, 1]))
        north_diff = diff[0, 0] - diff[0, 1]
        east_diff = diff[1, 0] - diff[1, 1]

        n_north = int(self.n_grdpoints[0])
        n_east = int(self.n_grdpoints[1])

        dn = north_diff / (n_north - 1)
        de = east_diff / (n_east - 1)

        c5 = num.empty((n_north * n_east, 5))
        c5[:, 0] = ref_lat
        c5[:, 1] = ref_lon

        for inorth in range(n_north):
            for ieast in range(n_east):
                idx = inorth * n_east + ieast
                c5[idx, 2] = diff[0, 0] - inorth * dn
                c5[idx, 3] = diff[1, 0] - ieast * de

        c5[:, 4] = 0.

        raster.add_col((
            'c5', '',
            ('ref_lat', 'ref_lon', 'north_shift', 'east_shift', 'depth')),
            c5)

        return raster


class SourceOutlinesPipe(object):
    def __init__(self, source_geom, RGB, cs='latlondepth'):

        self.mapper = vtk.vtkDataSetMapper()
        self._polyline_grid = {}

        lines = []

        latlon = source_geom.outline.vertices.get_col('latlon')
        depth = source_geom.outline.vertices.get_col('depth')

        points = num.concatenate(
            (latlon, depth.reshape(len(depth), 1)),
            axis=1)
        points = num.concatenate((points, points[0].reshape(1, -1)), axis=0)

        lines.append(points)

        if cs == 'latlondepth':
            self._polyline_grid = make_multi_polyline(
                lines_latlondepth=lines)
        elif cs == 'latlon':
            self._polyline_grid = make_multi_polyline(
                lines_latlon=lines)

        vtk_set_input(self.mapper, self._polyline_grid)

        actor = vtk.vtkActor()
        actor.SetMapper(self.mapper)

        prop = actor.GetProperty()
        prop.SetDiffuseColor(RGB)
        prop.SetOpacity(1.)

        self.actor = actor


class ProxySource(ElementState):
    pass


for source_cls in [gf.RectangularSource]:

    cls_name = 'Proxy' + source_cls.__name__

    class proxy_source_cls(ProxySource):
        class_name = cls_name

        def __init__(self, **kwargs):
            ProxySource.__init__(self)
            for key, value in self._ranges.iteritems():
                setattr(self, key, value['ini'])

            if kwargs is not None:
                for it in kwargs.items():
                    setattr(self, it[0], it[1])

    proxy_source_cls.__name__ = cls_name
    vars()[cls_name] = proxy_source_cls

    for prop in source_cls.T.properties:
        proxy_source_cls.T.add_property(prop.name, prop)


ProxyRectangularSource._name = 'RectangularSource'

ProxyRectangularSource._ranges = {
    'lat': {'min': -90., 'max': 90., 'step': 1, 'ini': 0.},
    'lon': {'min': -180., 'max': 180., 'step': 1, 'ini': 0.},
    'depth': {'min': 0., 'max': 600000., 'step': 1000, 'ini': 10000.},
    'width': {'min': 0., 'max': 500000., 'step': 1000, 'ini': 10000.},
    'length': {'min': 0., 'max': 1000000., 'step': 1000, 'ini': 50000.},
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
    'Time (s)': 'times'}


class SourceState(ElementState):
    visible = Bool.T(default=True)
    contour = Bool.T(default=False)
    source_selection = ProxySource.T(default=ProxyRectangularSource())  # noqa
    deltat = Float.T(default=0.5)
    display_parameter = String.T(default='Time (s)')
    disp_window = LatLonWindow.T(default=DisplacementWindow())
    disp_arrow_size = Float.T(default=1.)

    @classmethod
    def get_name(self):
        return 'Source'

    def create(self):
        element = SourceElement()
        element.bind_state(self)
        return element


class SourceElement(Element):

    def __init__(self):
        Element.__init__(self)
        self._parent = None
        self._pipe = []
        self._controls = None
        self._points = num.array([])

    def _state_bind_source(self, *args, **kwargs):
        vstate.state_bind(self, self._state.source_selection, *args, **kwargs)

    def _state_bind_store(self, *args, **kwargs):
        vstate.state_bind(self, self._state, *args, **kwargs)

    def bind_state(self, state):
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'visible')
        state.add_listener(upd, 'contour')
        state.add_listener(upd, 'source_selection')
        state.add_listener(upd, 'deltat')
        state.add_listener(upd, 'display_parameter')
        state.add_listener(upd, 'disp_window')
        state.add_listener(upd, 'disp_arrow_size')
        self._state = state

    def unbind_state(self):
        self._listeners = []

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
                    self._parent.remove_actor(pipe.actor)
                self._pipe = []

            if self._controls:
                self._parent.remove_panel(self._controls)
                self._controls = None

            self._parent.update_view()
            self._parent = None

    def open_set_displacement_dialog(self):
        from ..state import state_bind_slider
        disp_win = self._state.disp_window

        dialog = qw.QDialog(self._parent)
        dialog.setWindowTitle('Set corners of displacement calculation window')

        def lineedit_to_tuple(widget):
            sel = str(widget.text())
            return tuple(map(float, sel.split(', ')))

        def tuple_to_lineedit(tuple, widget):
            sel = widget.selectedText() == widget.text()
            widget.setText('%g, %g' % (tuple[0], tuple[1]))
            if sel:
                widget.selectAll()

        layout = qw.QGridLayout(dialog)

        layout.addWidget(qw.QLabel('N-E corner:'), 0, 0)
        le_ne = qw.QLineEdit()
        tuple_to_lineedit(disp_win.ne_corner, le_ne)
        layout.addWidget(le_ne, 0, 1)

        layout.addWidget(qw.QLabel('S-W corner:'), 1, 0)
        le_sw = qw.QLineEdit()
        tuple_to_lineedit(disp_win.sw_corner, le_sw)
        layout.addWidget(le_sw, 1, 1)

        layout.addWidget(qw.QLabel('Num. grid points (N, E):'), 2, 0)
        le_grd = qw.QLineEdit()
        tuple_to_lineedit(disp_win.n_grdpoints, le_grd)
        layout.addWidget(le_grd, 2, 1)

        layout.addWidget(qw.QLabel('Arrow size:'), 3, 0)
        slider = qw.QSlider(qc.Qt.Horizontal)
        slider.setSizePolicy(
            qw.QSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Fixed))
        slider.setMinimum(1)
        slider.setMaximum(5)
        slider.setSingleStep(1)
        slider.setPageStep(1)
        state_bind_slider(self, self._state, 'disp_arrow_size', slider)
        layout.addWidget(slider, 3, 1)

        pb = qw.QPushButton('Cancel')
        pb.clicked.connect(dialog.reject)
        layout.addWidget(pb, 4, 0)

        pb = qw.QPushButton('Ok')
        pb.clicked.connect(dialog.accept)
        layout.addWidget(pb, 4, 1)

        dialog.exec_()

        if dialog.result() == qw.QDialog.Accepted:
            ne_c = lineedit_to_tuple(le_ne)
            sw_c = lineedit_to_tuple(le_sw)
            n_grdpoints = lineedit_to_tuple(le_grd)

            self._state.disp_window = DisplacementWindow(
                ne_corner=ne_c, sw_corner=sw_c, n_grdpoints=n_grdpoints)

    def open_file_load_dialog(self):
        caption = 'Select one file to open'
        fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options))

        if fns:
            self.load_file(str(fns[0]))
        else:
            return

    def load_file(self, path):
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
            fn, _ = fnpatch(qw.QFileDialog.getSaveFileName(
                self._parent, caption, options=common.qfiledialog_options))
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

    def update_disloc(self, source_geom, source, dim=2, **kwargs):
        state = self._state
        receiver_geom, disloc = okada_surface_displacement(
            source_geom, state.disp_window, source, dim=dim, **kwargs)

        vertices = geometry.arr_vertices(
            receiver_geom.get_col('xyz'))

        vectors = num.concatenate((
            disloc['displacement.n'][:, num.newaxis],
            disloc['displacement.e'][:, num.newaxis],
            disloc['displacement.d'][:, num.newaxis]),
            axis=1)

        vectors = geometry.ned2xyz(
            vectors, num.concatenate((
                receiver_geom.get_col('latlon'),
                receiver_geom.get_col('depth')[:, num.newaxis]), axis=1),
            planetradius=cake.earthradius)
        vectors = geometry.arr_vertices(vectors)

        self._pipe.append(
            Glyph3DPipe(
                vertices, vectors,
                sizefactor=state.disp_arrow_size))

        if isinstance(self._pipe[-1].actor, list):
            self._parent.add_actor_list(self._pipe[-1].actor)
        else:
            self._parent.add_actor(self._pipe[-1].actor)

    def update_raster(self, source_geom, param):
        patches = source_geom.patches

        vertices = geometry.arr_vertices(
            patches.vertices.get_col('xyz'))

        values = patches.faces.get_col(parameter_label[param])
        faces = num.array([
            list(face) for face in patches.faces.get_col('patch_faces')])

        self._pipe.append(
            PolygonPipe(
                vertices, faces,
                values=values, contour=self._state.contour, cbar_title=param))

        if isinstance(self._pipe[-1].actor, list):
            self._parent.add_actor_list(self._pipe[-1].actor)
        else:
            self._parent.add_actor(self._pipe[-1].actor)

    def update_rake_arrow(self, fault):
        source = self._state.source_selection
        rake = source.rake * d2r

        nucl_x = source.nucleation_x
        nucl_y = source.nucleation_y

        wd_ln = source.width / source.length

        endpoint = [None] * 2
        endpoint[0] = nucl_x + num.cos(rake) * wd_ln
        endpoint[1] = nucl_y + num.sin(-rake)

        points = geometry.latlondepth2xyz(
            fault.points_on_source(
                points_x=[nucl_x, endpoint[0]],
                points_y=[nucl_y, endpoint[1]],
                cs='latlondepth'),
            planetradius=cake.earthradius)
        vertices = geometry.arr_vertices(points)
        self._pipe.append(ArrowPipe(vertices[0], vertices[1]))
        self._parent.add_actor(self._pipe[-1].actor)

    def update(self, *args):
        state = self._state
        source = state.source_selection
        source_list = gf.source_classes

        store = ProxyStore(
            deltat=self._state.deltat)
        store.config.deltas = num.array(
            [(store.config.deltat * store.config.vs) + 1] * 2)

        if self._pipe:
            for pipe in self._pipe:
                try:
                    self._parent.remove_actor(pipe.actor)
                except Exception:
                    for actor in pipe.actor:
                        self._parent.remove_actor(actor)

            self._pipe = []

        if state.visible:
            for i, a in enumerate(source_list):
                if a.__name__ is source._name:
                    fault = a(
                        **{prop: source.__dict__[prop]
                            for prop in source.T.propnames})
                    source_geom = fault.geometry(store)

                    source_geom.refine_outline(0.1)
                    self._pipe.append(
                        SourceOutlinesPipe(
                            source_geom, (1., 1., 1.),
                            cs='latlondepth'))
                    self._parent.add_actor(self._pipe[-1].actor)

                    self._pipe.append(
                        SourceOutlinesPipe(
                            source_geom, (.6, .6, .6),
                            cs='latlon'))
                    self._parent.add_actor(self._pipe[-1].actor)

                    for point, color in zip((
                            (source.nucleation_x,
                             source.nucleation_y),
                            map_anchor[source.anchor]),
                            (num.array([[1., 0., 0.]]),
                             num.array([[0., 0., 1.]]))):

                        points = geometry.latlondepth2xyz(
                            fault.points_on_source(
                                points_x=[point[0]], points_y=[point[1]],
                                cs='latlondepth'),
                            planetradius=cake.earthradius)

                        vertices = geometry.arr_vertices(points)
                        self._pipe.append(ScatterPipe(vertices))
                        self._pipe[-1].set_colors(color)
                        self._parent.add_actor(self._pipe[-1].actor)


                    self.update_disloc(source_geom, fault, dim=2)
                    self.update_raster(source_geom, state.display_parameter)
                    self.update_rake_arrow(fault)

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
                if sel:
                    widget.selectAll()

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
                    slider.setMinimum(source._ranges[label]['min'])
                    slider.setMaximum(source._ranges[label]['max'])
                    slider.setSingleStep(source._ranges[label]['step'])
                    slider.setPageStep(source._ranges[label]['step'])
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
                slider.setMinimum(1.)
                slider.setMaximum(1000.)
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
            layout.addWidget(cb, il, 1, 1, 2)
            state_bind_combobox(
                self, self._state, 'display_parameter', cb)

            il += 1
            pb = qw.QPushButton('Displacement Win.')
            layout.addWidget(pb, il, 1)
            pb.clicked.connect(self.open_set_displacement_dialog)

            pb = qw.QPushButton('Move Source Here')
            layout.addWidget(pb, il, 2)
            pb.clicked.connect(self.update_loc)

            il += 1
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

            cb = qw.QCheckBox('Contour')
            layout.addWidget(cb, il, 1)
            state_bind_checkbox(self, self._state, 'contour', cb)

            pb = qw.QPushButton('Remove')
            layout.addWidget(pb, il, 2)
            pb.clicked.connect(self.unset_parent)

            il += 1
            layout.addWidget(qw.QFrame(), il, 0, 1, 3)

        self._controls = frame

        return self._controls


__all__ = [
    'SourceElement',
    'SourceState',
]
