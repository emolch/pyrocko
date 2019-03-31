# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

# import copy
import operator
import calendar
import numpy as num

from pyrocko.guts import \
    Object, StringChoice, String, List

from pyrocko import table, model  # , automap
from pyrocko.client import fdsn
from pyrocko.gui.qt_compat import qw, fnpatch
# from pyrocko.himesh import HiMesh

# from pyrocko.gui.vtk_util import TrimeshPipe

from .. import common

from .table import TableElement, TableState

guts_prefix = 'sparrow'


attribute_names = [
    'time', 'lat', 'lon', 'northing', 'easting', 'depth', 'magnitude']

attribute_dtypes = [
    'f16', 'f8', 'f8', 'f8', 'f8', 'f8', 'f8']

name_to_icol = dict(
    (name, icol) for (icol, name) in enumerate(attribute_names))

event_dtype = num.dtype(list(zip(attribute_names, attribute_dtypes)))

t_time = num.float


def binned_statistic(values, ibins, function):
    order = num.argsort(ibins)
    values_sorted = values[order]
    ibins_sorted = ibins[order]
    parts = num.concatenate((
        [0],
        num.where(num.diff(ibins_sorted) != 0)[0] + 1,
        [ibins.size]))

    results = []
    ibins_result = []
    for ilow, ihigh in zip(parts[:-1], parts[1:]):
        values_part = values_sorted[ilow:ihigh]
        results.append(function(values_part))
        ibins_result.append(ibins_sorted[ilow])

    return num.array(ibins_result, dtype=num.int), num.array(results)


def load_text(
        filepath,
        column_names=('time', 'lat', 'lon', 'depth', 'magnitude'),
        time_format='seconds'):

    with open(filepath, 'r') as f:
        if column_names == 'from_header':
            line = f.readline()
            column_names = line.split()

        name_to_icol_in = dict(
            (name, icol) for (icol, name) in enumerate(column_names)
            if name in attribute_names)

    data_in = num.loadtxt(filepath, skiprows=1)

    nevents = data_in.shape[0]
    c5 = num.zeros((nevents, 5))
    c5[:, 0] = data_in[:, name_to_icol_in['lat']]
    c5[:, 1] = data_in[:, name_to_icol_in['lon']]
    c5[:, 2] = 0.0
    c5[:, 3] = 0.0
    c5[:, 4] = data_in[:, name_to_icol_in['depth']] * 1000.

    tab = table.Table()
    loc_rec = table.LocationRecipe()
    tab.add_recipe(loc_rec)

    tab.add_col(loc_rec.c5_header, c5)
    for k, unit in [
            ('time', 's'),
            ('magnitude', None)]:

        values = data_in[:, name_to_icol_in[k]]

        if k == 'time' and time_format == 'year':
            values = decimal_year_to_time(values)

        tab.add_col(table.Header(k, unit), values)

    return tab


def decimal_year_to_time(year):
    iyear_start = num.floor(year).astype(num.int)
    iyear_end = iyear_start + 1

    iyear_min = num.min(iyear_start)
    iyear_max = num.max(iyear_end)

    iyear_to_time = num.zeros(iyear_max - iyear_min + 1, dtype=t_time)
    for iyear in range(iyear_min, iyear_max+1):
        iyear_to_time[iyear-iyear_min] = calendar.timegm(
            (iyear, 1, 1, 0, 0, 0))

    tyear_start = iyear_to_time[iyear_start - iyear_min]
    tyear_end = iyear_to_time[iyear_end - iyear_min]

    t = tyear_start + (year - iyear_start) * (tyear_end - tyear_start)

    return t


def oa_to_array(objects, attribute):
    return num.fromiter(
        map(operator.attrgetter(attribute), objects),
        num.float,
        len(objects))


def events_to_table(events):

    c5 = num.zeros((len(events), 5))

    for i, ev in enumerate(events):
        c5[i, :] = ev.lat, ev.lon, 0., 0., ev.depth

    tab = table.Table()
    loc_rec = table.LocationRecipe()
    tab.add_recipe(loc_rec)

    tab.add_col(loc_rec.c5_header, c5)
    for k, unit in [
            ('time', 's'),
            ('magnitude', None)]:

        tab.add_col(table.Header(k, unit), oa_to_array(events, k))

    return tab


class LoadingChoice(StringChoice):
    choices = [choice.upper() for choice in [
        'file',
        'fdsn']]


class FDSNSiteChoice(StringChoice):
    choices = [key.upper() for key in fdsn.g_site_abbr.keys()]


class CatalogSelection(Object):
    pass


class FileCatalogSelection(CatalogSelection):
    paths = List.T(String.T())

    def get_table(self):
        from pyrocko.io import quakeml

        events = []
        for path in self.paths:
            fn_ext = path.split('.')[-1].lower()
            if fn_ext in ['xml', 'qml', 'quakeml']:
                qml = quakeml.QuakeML.load_xml(filename=path)
                events.extend(qml.get_pyrocko_events())

            if fn_ext in ['dat', 'csv']:
                assert len(self.paths) == 1
                tab = load_text(
                    path, column_names='from_header', time_format='year')

                return tab

            else:
                events.extend(model.load_events(path))

        return events_to_table(events)


class CatalogState(TableState):
    selection = CatalogSelection.T(optional=True)

    @classmethod
    def get_name(self):
        return 'Catalog'

    def create(self):
        element = CatalogElement()
        element.bind_state(self)
        return element


class CatalogElement(TableElement):

    def __init__(self, *args, **kwargs):
        TableElement.__init__(self, *args, **kwargs)
        self._selection_view = None
        # self._himesh = HiMesh(order=6)

        # cpt_data = [
        #     (0.0, 0.0, 0.0, 0.0),
        #     (1.0, 0.9, 0.9, 0.2)]
        #
        # self.cpt_mesh = automap.CPT(
        #     levels=[
        #         automap.CPTLevel(
        #             vmin=a[0],
        #             vmax=b[0],
        #             color_min=[255*x for x in a[1:]],
        #             color_max=[255*x for x in b[1:]])
        #         for (a, b) in zip(cpt_data[:-1], cpt_data[1:])])

    def get_name(self):
        return 'Catalog'

    def bind_state(self, state):
        TableElement.bind_state(self, state)
        upd = self.update
        self._listeners.append(upd)
        state.add_listener(upd, 'selection')

    def update(self, *args):
        state = self._state
        # ifaces = None
        if self._selection_view is not state.selection:
            self.set_table(state.selection.get_table())
            self._selection_view = state.selection

            # ifaces = self._himesh.points_to_faces(self._table.get_col('xyz'))

        TableElement.update(self, *args)

        # if ifaces is not None:
        #     ifaces_x, sizes = binned_statistic(
        #         ifaces, ifaces, lambda part: part.shape[0])
        #
        #     vertices = self._himesh.get_vertices()
        #     # vertices *= 0.95
        #     faces = self._himesh.get_faces()
        #
        #     values = num.zeros(faces.shape[0])
        #     values[ifaces_x] = num.log(1+sizes)
        #
        #     self._mesh = TrimeshPipe(vertices, faces, values=values)
        #     cpt = copy.deepcopy(self.cpt_mesh)
        #     cpt.scale(num.min(values), num.max(values))
        #     self._mesh.set_cpt(cpt)
        #     self._mesh.set_opacity(0.5)

        #     self._parent.add_actor(self._mesh.actor)

    def open_file_dialog(self):
        caption = 'Select one or more files to open'

        fns, _ = fnpatch(qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options))

        self._state.selection = FileCatalogSelection(
            paths=[str(fn) for fn in fns])

    def _get_table_widgets_start(self):
        return 1  # used as y arg in addWidget calls

    def _get_controls(self):
        if not self._controls:
            frame = TableElement._get_controls(self)  # sets self._controls
            layout = frame.layout()

            lab = qw.QLabel('Load from:')
            pb_file = qw.QPushButton('File')

            layout.addWidget(lab, 0, 0)
            layout.addWidget(pb_file, 0, 1)

            pb_file.clicked.connect(self.open_file_dialog)

        return self._controls


__all__ = [
    'CatalogSelection',
    'FileCatalogSelection',
    'CatalogElement',
    'CatalogState',
]
