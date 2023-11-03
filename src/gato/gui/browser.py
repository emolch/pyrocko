# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import difflib
import logging

from pyrocko.guts import String, List
from pyrocko.gui.qt_compat import qw, qc
from pyrocko.gui.util import SmartplotFrame, call_later, get_app
from pyrocko.gui import talkie
from pyrocko.gui.state import state_bind, state_bind_combobox
from pyrocko import gato
from pyrocko.gato import plot
from . import common

guts_prefix = 'gato'

logger = logging.getLogger('gato.gui.browser')


class ArrayInventory(qc.QAbstractTableModel, talkie.TalkieConnectionOwner):
    def __init__(self, state):
        qc.QAbstractTableModel.__init__(self)
        talkie.TalkieConnectionOwner.__init__(self)

        self.state = state
        self.columns = [
            'name', 'type', 'comment', 'n_codes_nsl', 'n_codes', 'str_tmin',
            'str_tmax', 'str_codes_nsl_by_channels']
        self.column_titles = [
            'Name', 'Type', 'Comment', '# Sites', '# Channels', 'Start Date',
            'End Date', 'Channel Group: # Sites']
        self.column_sizes = [100] * len(self.columns)
        self.column_sizes[2] = 350

        self.talkie_connect(self.state, 'arrays', self.update_arrays)

        self.arrays = []
        self.array_infos = []

    def update_arrays(self, *args):

        arrays = self.state.arrays
        sm = difflib.SequenceMatcher(
            None,
            self.arrays,
            arrays)

        ioff = 0
        parent = qc.QModelIndex()
        for tag, i1, i2, j1, j2 in list(sm.get_opcodes()):
            if tag == 'equal':
                pass
            elif tag == 'replace':
                self.arrays[i1+ioff:i2+ioff] = arrays[j1:j2]
                self.array_infos[i1+ioff:i2+ioff] = self.array_infos[j1:j2]

            elif tag == 'delete':
                self.beginRemoveRows(parent, i1+ioff, i2+ioff-1)
                self.arrays[i1+ioff:i2+ioff] = []
                self.array_infos[i1+ioff:i2+ioff] = []
                ioff -= i2-i1
                self.endRemoveRows()

            elif tag == 'insert':
                self.beginInsertRows(parent, i1+ioff, i1+ioff+j2-j1-1)
                self.arrays[i1+ioff:i2+ioff] = arrays[j1:j2]
                self.array_infos[i1+ioff:i2+ioff] = [None] * (j2-j1)
                self.endInsertRows()
                ioff += j2-j1

        self.update_array_infos()

    def get_array(self, index):
        return self.arrays[index.row()]

    def get_array_and_info_by_name(self, name):
        for array, info in zip(self.arrays, self.array_infos):
            if array.name == name:
                return array, info

        return None, None

    def _get_index_by_name(self, name):
        for i, array in enumerate(self.arrays):
            if name == array.name:
                return i

        return None

    def get_index_by_name(self, name):
        i = self._get_index_by_name(name)
        if i is None:
            return qc.QModelIndex()

        return self.index(i, 0)

    def get_array_info(self, index):
        return self.array_infos[index.row()]

    def update_array_infos(self):

        win = get_app().get_main_window()
        channels = win.state.constraints.channels
        if channels:
            codes = ['*.*.*.%s' for channel in channels]
        else:
            codes = None
        tmin = win.state.constraints.tmin_effective
        tmax = win.state.constraints.tmax_effective

        for i in range(len(self.arrays)):
            self.array_infos[i] = self.arrays[i].get_info(
                win.squirrel,
                codes=codes,
                tmin=tmin,
                tmax=tmax)

            istart = self.index(3, i)
            istop = self.index(len(self.columns)-1, i)
            self.dataChanged.emit(istart, istop)

    def rowCount(self, parent):
        return len(self.arrays)

    def columnCount(self, parent):
        return len(self.columns)

    def headerData(self, section, orientation, role):
        if orientation == qc.Qt.Horizontal:
            if role == qc.Qt.DisplayRole:
                return qc.QVariant(self.column_titles[section])
            elif role == qc.Qt.SizeHintRole:
                return qc.QSize(10, 20)

        elif orientation == qc.Qt.Vertical:
            if role == qc.Qt.DisplayRole:
                return qc.QVariant(str(section))

        return qc.QVariant()

    def data(self, index, role):
        irow = index.row()
        icol = index.column()
        column = self.columns[icol]
        array = self.arrays[irow]
        array_info = self.array_infos[irow]

        obj = array if icol < 3 else array_info
        if obj is None:
            return qc.QVariant()

        if role == qc.Qt.BackgroundRole:
            return qc.QVariant()

        elif role == qc.Qt.ForegroundRole:
            return qc.QVariant()

        elif role in (qc.Qt.DisplayRole, qc.Qt.UserRole):
            return qc.QVariant(getattr(obj, column))

        else:
            return qc.QVariant()


class ArrayBrowserState(talkie.TalkieRoot):
    arrays = List.T(
        gato.SensorArray.T(),
        help='List of arrays')

    current_array_name = String.T(
        optional=True,
        help='Name of the currently selected array.')

    arf_plot = plot.ArrayResponseFunctionPlotState.T(
        default=plot.ArrayResponseFunctionPlotState.D(),
        help='Array response function plot settings.')

    geometry_plot = plot.GeometryPlotState.T(
        default=plot.GeometryPlotState.D(),
        help='Geometry plot settings.')


class ArrayBrowser(qw.QSplitter, talkie.TalkieConnectionOwner):

    current_array_changed = qc.pyqtSignal()
    current_array_info_changed = qc.pyqtSignal()

    def __init__(self, state, **kwargs):
        qw.QSplitter.__init__(self, qc.Qt.Vertical)
        talkie.TalkieConnectionOwner.__init__(self)

        self.state = state

        self.inventory = inventory = ArrayInventory(self.state)

        array_table = qw.QTableView()
        array_table.setModel(inventory)

        array_table.setShowGrid(False)
        array_table.setSelectionBehavior(qw.QAbstractItemView.SelectRows)
        array_table.verticalHeader().hide()

        selection = qc.QItemSelectionModel(inventory)
        array_table.setSelectionModel(selection)

        def update_state(widget, state):
            current_array = self.inventory.get_array(selection.currentIndex())
            self.state.current_array_name \
                = current_array.name if current_array else None

        def update_widget(state, widget):
            index = self.inventory.get_index_by_name(
                self.state.current_array_name)

            selection.setCurrentIndex(index, qc.QItemSelectionModel.Current)

        state_bind(
            self, self.state, ['current_array_name'], update_state,
            array_table, [selection.currentRowChanged], update_widget)

        def remove_selection():
            indices = [index.row() for index in selection.selectedRows()]

            arrays = self.state.arrays
            ioff = 0
            for i in indices:
                if arrays[i+ioff].name == self.state.current_array_name:
                    self.state.current_array_name = None

                arrays[i+ioff:i+ioff+1] = []
                ioff -= 1

            self.state.arrays = arrays

        menu = qw.QMenu()
        menu.addAction('Remove', remove_selection)

        array_table.setContextMenuPolicy(qc.Qt.CustomContextMenu)

        def exec_menu(pos):
            menu.exec_(self.mapToGlobal(pos))

        array_table.customContextMenuRequested.connect(exec_menu)

        header = array_table.horizontalHeader()
        for i_s, s in enumerate(inventory.column_sizes):
            header.resizeSection(i_s, s)

        header.setStretchLastSection(True)

        self.array_table = array_table

        self.geometry = geometry = SmartplotFrame(
            plot_cls=plot.GeometryPlot,
            plot_args=(self.state.geometry_plot,))
        self.arf = arf = SmartplotFrame(
            plot_cls=plot.ArrayResponseFunctionPlot,
            plot_args=(self.state.arf_plot,))

        lab = qw.QLabel('View:')
        cbox = qw.QComboBox()
        cbox.addItems(plot.ProjectionChoice.choices)

        frame = qw.QFrame()
        frame.setLayout(qw.QHBoxLayout())
        frame.layout().setContentsMargins(0, 0, 0, 0)
        frame.layout().addWidget(lab)
        frame.layout().addWidget(cbox)

        geometry.toolbar.addWidget(frame)

        state_bind_combobox(self, state, 'geometry_plot.projection', cbox)

        self.addWidget(array_table)

        plots_frame = qw.QFrame()
        self.addWidget(plots_frame)
        layout = qw.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        plots_frame.setLayout(layout)

        self._geometry_items = []
        layout.addWidget(geometry)
        layout.addWidget(arf)

        self.current_array = None
        self.current_array_info = None

        self.talkie_connect(
            self.state, ['current_array_name'], self.update_current_array)

        # slider = qw.QSlider(qc.Qt.Horizontal)
        # self.arf.toolbar_frame.layout().addWidget(slider)

    def update_array_infos_later(self):
        call_later(self.update_array_infos, 200)

    def update_array_infos(self):
        self.inventory.update_array_infos()
        self.update_current_array()

    def update_current_array(self, *args):
        self.current_array, self.current_array_info = \
            self.inventory.get_array_and_info_by_name(
                self.state.current_array_name)

        self.current_array_changed.emit()
        self.current_array_info_changed.emit()

        self.update_plots()

    def update_plots(self):
        array = self.current_array
        info = self.current_array_info
        self.geometry.plot.set_array(array, info)
        self.arf.plot.set_array(array, info)

    def builtin_arrays(self, type=None):
        return [
            array for array in gato.get_named_arrays().values()
            if type is None or array.type == type]

    def add_arrays_check(self, arrays):
        names_have = set(array.name for array in self.state.arrays)
        arrays_add = []
        for array in arrays:
            if array.name in names_have:
                logger.warning(
                    'Duplicate insert: array with name %s already '
                    'exists.' % array.name)
            else:
                arrays_add.append(array)
                names_have.add(array.name)

        self.state.arrays.extend(arrays_add)
        if arrays_add:
            self.state.current_array_name = arrays_add[0].name

    def add_menu_entries(self, menu):

        def add_array_from_available_sensors():
            sq = get_app().get_main_window().squirrel
            sensors = sq.get_sensors()
            codes = set()
            for sensor in sensors:
                codes.add(sensor.codes)

            array = gato.SensorArray(
                name='Ad hoc array',
                codes=sorted(codes))

            self.add_arrays_check([array])

        def add_arrays_from_file():
            fns, _ = qw.QFileDialog.getOpenFileNames(
                get_app().get_main_window(),
                'Select one or more files containing Gato array definitions.',
                options=common.qfiledialog_options)

            if fns:
                arrays = []
                for fn in fns:
                    arrays.extend(gato.load_all(fn, want=gato.SensorArray))

                if arrays:
                    self.add_arrays_check(arrays)

        def make_add_arrays(arrays):

            def add_arrays():
                win = get_app().get_main_window()
                win.add_named_arrays_dataset()
                self.add_arrays_check(arrays)

            return add_arrays

        menu1 = menu.addMenu('Add Arrays')
        menu1.addAction('From Available', add_array_from_available_sensors)
        menu1.addAction('From File', add_arrays_from_file)

        menu2 = menu1.addMenu('Builtin')

        for title, type in [
                ('Seismic', 'seismic'),
                ('Infrasound', 'infrasound'),
                ('Hydrophone', 'hydrophone')]:

            menu3 = menu2.addMenu(title)
            arrays = self.builtin_arrays(type)
            menu3.addAction('All', make_add_arrays(arrays))
            menu3.addSeparator()
            for array in arrays:
                menu3.addAction(array.name, make_add_arrays([array]))
