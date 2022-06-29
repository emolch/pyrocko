# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

# import copy
import logging
import operator
import calendar
import numpy as num

from pyrocko.guts import \
    Object, StringChoice, String, List, Float

from pyrocko import table, model  # , automap
from pyrocko.client import fdsn, catalog
from pyrocko.gui.qt_compat import qw
from pyrocko.plot import beachball
# from pyrocko.himesh import HiMesh

# from pyrocko.gui.vtk_util import TrimeshPipe

from .. import common

from .table import TableElement, TableState

logger = logging.getLogger('pyrocko.gui.sparrow.elements.catalog')

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


def eventtags_to_array(events, tab):

    ks = set()
    event_tags = []
    for ev in events:
        tags = ev.tags_as_dict()
        ks.update(tags.keys())
        event_tags.append(tags)

    for k in sorted(ks):
        column = [tags.get(k, None) for tags in event_tags]
        if all(isinstance(v, int) for v in column):
            dtype = int
        elif all(isinstance(v, float) for v in column):
            dtype = float
        else:
            dtype = num.string_
            column = [v or '' for v in column]

        arr = num.array(column, dtype=dtype)

        tab.add_col(table.Header('tag_%s' % k), arr)


def eventextras_to_array(events, tab):
    n_extras = num.array([len(ev.extras) for ev in events])
    evts_all_extras = num.arange(len(events))[n_extras != 0]

    if evts_all_extras.shape[0] == 0:
        return tab

    ev0 = events[evts_all_extras[0]]

    if num.unique(n_extras).shape[0] > 1:
        msg = 'Not all events have equal number of extras.'
        if num.unique(n_extras).shape[0] == 2 and num.min(n_extras) == 0:
            logger.warn(msg + ' Zero length lists are filled with NaNs.')
        else:
            raise IndexError(
                msg + ' Several non-zero shapes detected. Please check.')

    for key, val in ev0.extras.items():
        dtype = num.string_
        values = num.array(['' for x in range(n_extras.shape[0])], dtype=dtype)

        if type(val) is float:
            dtype, values = num.float, num.ones_like(n_extras) * num.nan

        elif type(val) is int:
            dtype = num.int64
            values = num.ones_like(n_extras, dtype=num.int64) * num.nan

        header = 'extra_%s' % key
        values[evts_all_extras] = num.array([
            events[iev].extras[key] for iev in evts_all_extras], dtype=dtype)

        tab.add_col(table.Header(header), values)


def events_to_table(events):
    c5 = num.zeros((len(events), 5))
    m6 = None

    for i, ev in enumerate(events):
        c5[i, :] = (
            ev.lat, ev.lon, ev.north_shift, ev.east_shift, ev.depth)

        if ev.moment_tensor:
            if m6 is None:
                m6 = num.zeros((len(events), 6))
                m6[:, 0:3] = 1.0

            m6[i, :] = beachball.deco_part(ev.moment_tensor, 'deviatoric').m6()

    tab = table.Table()

    ev_rec = table.EventRecipe()
    tab.add_recipe(ev_rec)
    tab.add_col(ev_rec.get_header('c5'), c5)

    for k in ['time', 'magnitude']:
        tab.add_col(ev_rec.get_header(k), oa_to_array(events, k))

    if events:
        eventtags_to_array(events, tab)
        eventextras_to_array(events, tab)

    if m6 is not None:
        mt_rec = table.MomentTensorRecipe()
        tab.add_recipe(mt_rec)
        tab.add_col(mt_rec.m6_header, m6)

    return tab


class LoadingChoice(StringChoice):
    choices = [choice.upper() for choice in [
        'file',
        'fdsn']]


class FDSNSiteChoice(StringChoice):
    choices = [key.upper() for key in fdsn.g_site_abbr.keys()]


class CatalogSelection(Object):
    pass


class MemoryCatalogSelection(CatalogSelection):

    def __init__(self, events=None):
        if events is None:
            events = []

        self._events = events

    def get_table(self):
        return events_to_table(self._events)


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


g_catalogs = {
    'Geofon': catalog.Geofon(),
    'USGS/NEIC US': catalog.USGS('us'),
    'Global-CMT': catalog.GlobalCMT(),
    'Saxony (Uni-Leipzig)': catalog.Saxony()
}

g_fdsn_has_events = ['ISC', 'SCEDC', 'NCEDC', 'IRIS', 'GEONET']

g_sites = sorted(g_catalogs.keys())
g_sites.extend(g_fdsn_has_events)


class OnlineCatalogSelection(CatalogSelection):
    site = String.T()
    tmin = Float.T()
    tmax = Float.T()
    magnitude_min = Float.T(optional=True)

    def get_table(self):
        logger.info('Getting events from "%s" catalog.' % self.site)

        cat = g_catalogs.get(self.site, None)
        try:
            if cat:
                kwargs = {}
                if self.magnitude_min is not None:
                    kwargs['magmin'] = self.magnitude_min

                events = cat.get_events(
                    time_range=(self.tmin, self.tmax), **kwargs)

            else:
                kwargs = {}
                if self.magnitude_min is not None:
                    kwargs['minmagnitude'] = self.magnitude_min

                request = fdsn.event(
                    starttime=self.tmin,
                    endtime=self.tmax,
                    site=self.site, **kwargs)

                from pyrocko.io import quakeml
                qml = quakeml.QuakeML.load_xml(request)
                events = qml.get_pyrocko_events()

            logger.info('Got %i event%s from "%s" catalog.' % (
                len(events), '' if len(events) == 1 else 's', self.site))

        except Exception as e:
            logger.error(
                'Getting events from "%s" catalog failed: %s' % (
                    self.site, str(e)))

            events = []

        return events_to_table(events)


class CatalogState(TableState):
    selection = CatalogSelection.T(optional=True)

    @classmethod
    def get_name(self):
        return 'Catalog'

    def create(self):
        element = CatalogElement()
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

        fns, _ = qw.QFileDialog.getOpenFileNames(
            self._parent, caption, options=common.qfiledialog_options)

        self._state.selection = FileCatalogSelection(
            paths=[str(fn) for fn in fns])

    def open_catalog_load_dialog(self):
        dialog = qw.QDialog(self._parent)
        dialog.setWindowTitle('Get events from online catalog.')

        layout = qw.QHBoxLayout(dialog)

        layout.addWidget(qw.QLabel('Site'))

        cb = qw.QComboBox()
        for i, s in enumerate(g_sites):
            cb.insertItem(i, s)

        layout.addWidget(cb)

        pb = qw.QPushButton('Cancel')
        pb.clicked.connect(dialog.reject)
        layout.addWidget(pb)

        pb = qw.QPushButton('Ok')
        pb.clicked.connect(dialog.accept)
        layout.addWidget(pb)

        dialog.exec_()

        site = str(cb.currentText())

        vstate = self._parent.state

        if dialog.result() == qw.QDialog.Accepted:
            self._state.selection = OnlineCatalogSelection(
                site=site,
                tmin=vstate.tmin,
                tmax=vstate.tmax)

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

            pb_file = qw.QPushButton('Online Catalog')

            layout.addWidget(lab, 0, 0)
            layout.addWidget(pb_file, 0, 2)

            pb_file.clicked.connect(self.open_catalog_load_dialog)

        return self._controls


__all__ = [
    'CatalogSelection',
    'FileCatalogSelection',
    'MemoryCatalogSelection',
    'CatalogElement',
    'CatalogState',
]
