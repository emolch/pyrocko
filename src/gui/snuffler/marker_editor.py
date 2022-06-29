# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import

from .qt_compat import qc, qg, qw, QPixmapCache

from .marker import EventMarker, PhaseMarker
from ..util import make_QPolygonF
from pyrocko.plot.beachball import mt2beachball, BeachballError
from pyrocko.moment_tensor import kagan_angle
from pyrocko.plot import tango_colors
from pyrocko import orthodrome
from pyrocko.util import time_to_str

import logging

from .marker import g_color_b


def faint(c):
    return tuple(255 - (255 - x) // 5 for x in c)


g_color_b_faint = [faint(c) for c in g_color_b]


def noop(x=None):
    return x


qc.QString = str
qc.QVariant = noop


def toFloat(val):
    try:
        return float(val), True
    except (ValueError, TypeError):
        return 9e99, False


logger = logging.getLogger('pyrocko.gui.snuffler.marker_editor')

_header_data = [
    'T', 'Time', 'M', 'Label', 'Depth [km]', 'Lat', 'Lon', 'Kind', 'Dist [km]',
    'NSLCs', 'Polarity', 'Kagan Angle [deg]', 'Event Hash', 'MT']

_column_mapping = dict(zip(_header_data, range(len(_header_data))))

_string_header = (_column_mapping['Time'], _column_mapping['Label'])

_header_sizes = [70] * len(_header_data)
_header_sizes[0] = 40
_header_sizes[1] = 190
_header_sizes[-1] = 20


class BeachballWidget(qw.QWidget):

    def __init__(self, moment_tensor, color, *args, **kwargs):
        qw.QWidget.__init__(self, *args, **kwargs)
        self.color = color
        self.moment_tensor = moment_tensor
        self.setGeometry(0, 0, 100, 100)
        self.setAttribute(qc.Qt.WA_TranslucentBackground)

        self.flipy = qg.QTransform()
        self.flipy.translate(0, self.height())
        self.flipy.scale(1, -1)

    def paintEvent(self, e):
        center = e.rect().center()
        painter = qg.QPainter(self)
        painter.save()
        painter.setWorldTransform(self.flipy)
        try:
            data = mt2beachball(
                self.moment_tensor, size=self.height()/2.2,
                position=(center.x(), center.y()),
                color_t=self.color, color_p=qc.Qt.white, edgecolor=qc.Qt.black)
            for pdata in data:
                paths, fill, edges, thickness = pdata

                pen = qg.QPen(edges)
                pen.setWidthF(3)
                if fill != 'none':
                    brush = qg.QBrush(fill)
                    painter.setBrush(brush)

                polygon = qg.QPolygonF()
                polygon = make_QPolygonF(*paths.T)
                painter.setRenderHint(qg.QPainter.Antialiasing)
                painter.setPen(pen)
                painter.drawPolygon(polygon)
        except BeachballError as e:
            logger.exception(e)
        finally:
            painter.restore()

    def to_qpixmap(self):
        try:
            return self.grab(self.rect())
        except AttributeError:
            return qg.QPixmap().grabWidget(self, self.rect())


class MarkerItemDelegate(qw.QStyledItemDelegate):

    # Takes care of how table entries are displayed

    def __init__(self, *args, **kwargs):
        qw.QStyledItemDelegate.__init__(self, *args, **kwargs)
        self.c_alignment = qc.Qt.AlignHCenter
        self.bbcache = QPixmapCache()

    def paint(self, painter, option, index):
        mcolor = self.color_from_index(index)

        if index.column() == _column_mapping['MT']:
            mt = self.bb_data_from_index(index)
            if mt:
                key = ''.join([str(round(x, 1)) for x in mt.m6()])
                pixmap = self.bbcache.cached(key)
                if pixmap:
                    pixmap = pixmap.scaledToHeight(option.rect.height())
                else:
                    pixmap = BeachballWidget(
                        moment_tensor=mt,
                        color=qg.QColor(*tango_colors['scarletred3'])
                    ).to_qpixmap()
                    self.bbcache.insert(key, pixmap)
                a, b, c, d = option.rect.getRect()
                painter.save()
                painter.setRenderHint(qg.QPainter.Antialiasing)
                painter.drawPixmap(a+d/2., b, d, d, pixmap)
                painter.restore()

        else:
            if index.column() == 0:
                option.state = option.state & ~qw.QStyle.State_Selected

            qw.QStyledItemDelegate.paint(self, painter, option, index)

        marker = self.parent().model().get_marker(index)

        if marker.active:

            painter.save()

            rect = option.rect
            x1, y1, x2, y2 = rect.getCoords()
            y1 += 1
            pen = painter.pen()
            pen.setWidth(2)
            pen.setColor(mcolor)
            painter.setPen(pen)
            painter.drawLine(qc.QLineF(x1, y1, x2, y1))
            painter.drawLine(qc.QLineF(x1, y2, x2, y2))
            painter.restore()

    def marker_from_index(self, index):
        tv = self.parent()
        pv = tv.pile_viewer
        tvm = tv.model()
        if isinstance(tvm, qc.QSortFilterProxyModel):
            return pv.markers[tvm.mapToSource(index).row()]
        else:
            return pv.markers[index.row()]

    def bb_data_from_index(self, index):
        marker = self.marker_from_index(index)
        if isinstance(marker, EventMarker):
            return marker.get_event().moment_tensor
        else:
            return None

    def color_from_index(self, index):
        marker = self.marker_from_index(index)
        return qg.QColor(*marker.select_color(g_color_b))


class MarkerSortFilterProxyModel(qc.QSortFilterProxyModel):

    # Proxy object between view and model to handle sorting

    def __init__(self, *args, **kwargs):
        qc.QSortFilterProxyModel.__init__(self, *args, **kwargs)
        self.setSortRole(qc.Qt.UserRole)
        self.sort(1, qc.Qt.AscendingOrder)

    def get_marker(self, index):
        return self.sourceModel().get_marker(self.mapToSource(index))


class MarkerTableView(qw.QTableView):
    def __init__(self, *args, **kwargs):
        sortable = kwargs.pop('sortable', True)
        qw.QTableView.__init__(self, *args, **kwargs)
        self.setSelectionBehavior(qw.QAbstractItemView.SelectRows)
        self.setHorizontalScrollMode(qw.QAbstractItemView.ScrollPerPixel)
        self.setEditTriggers(qw.QAbstractItemView.DoubleClicked)
        self.setSortingEnabled(sortable)
        self.setStyleSheet(
            'QTableView{selection-background-color: \
            rgba(130, 130, 130, 100% );}')

        self.sortByColumn(1, qc.Qt.AscendingOrder)
        self.setAlternatingRowColors(True)

        self.setShowGrid(False)
        self.verticalHeader().hide()
        self.pile_viewer = None

        self.clicked.connect(self.table_clicked)
        self.doubleClicked.connect(self.table_double_clicked)

        self.header_menu = qw.QMenu(self)

        show_initially = ['Type', 'Time', 'Magnitude']
        self.menu_labels = ['Type', 'Time', 'Magnitude', 'Label', 'Depth [km]',
                            'Latitude/Longitude', 'Kind', 'Distance [km]',
                            'NSLCs', 'Polarity', 'Kagan Angle [deg]',
                            'Event Hash', 'MT']

        self.menu_items = dict(zip(
            self.menu_labels, [0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13]))

        self.editable_columns = [2, 3, 4, 5, 6, 7]

        self.column_actions = {}
        for hd in self.menu_labels:
            a = qw.QAction(hd, self.header_menu)
            a.triggered.connect(
                self.toggle_columns)
            a.setCheckable(True)
            a.setChecked(hd in show_initially)
            self.header_menu.addAction(a)
            self.column_actions[hd] = a

        a = qw.QAction('Numbering', self.header_menu)
        a.setCheckable(True)
        a.setChecked(False)
        a.triggered.connect(
            self.toggle_numbering)
        self.header_menu.addAction(a)

        header = self.horizontalHeader()
        header.setContextMenuPolicy(qc.Qt.CustomContextMenu)
        header.customContextMenuRequested.connect(
            self.show_context_menu)

        self.right_click_menu = qw.QMenu(self)
        print_action = qw.QAction('Print Table', self.right_click_menu)
        print_action.triggered.connect(self.print_menu)
        self.right_click_menu.addAction(print_action)

    def wheelEvent(self, wheel_event):
        if wheel_event.modifiers() & qc.Qt.ControlModifier:
            height = self.rowAt(self.height())
            ci = self.indexAt(
                qc.QPoint(self.viewport().rect().x(), height))
            v = self.verticalHeader()

            wheel_delta = wheel_event.angleDelta().y()

            v.setDefaultSectionSize(
                max(12, v.defaultSectionSize()+wheel_delta//60))
            self.scrollTo(ci)
            if v.isVisible():
                self.toggle_numbering(False)
                self.toggle_numbering(True)

        else:
            super(MarkerTableView, self).wheelEvent(wheel_event)

    def set_viewer(self, viewer):
        '''
        Set connected pile viewer and hook up signals.
        '''

        self.pile_viewer = viewer

    def keyPressEvent(self, key_event):
        # Propagate key_event to pile_viewer, unless up/down pressed

        if key_event.key() in [qc.Qt.Key_Up, qc.Qt.Key_Down]:
            qw.QTableView.keyPressEvent(self, key_event)
            self.pile_viewer.go_to_selection()
        else:
            self.pile_viewer.keyPressEvent(key_event)

    def table_clicked(self, model_index):
        # Ignore mouse clicks
        pass

    def contextMenuEvent(self, event):
        self.right_click_menu.popup(qg.QCursor.pos())

    def toggle_numbering(self, want):
        if want:
            self.verticalHeader().show()
        else:
            self.verticalHeader().hide()

    def print_menu(self):
        from ..qt_compat import qprint
        printer = qprint.QPrinter(qprint.QPrinter.ScreenResolution)
        printer.setOutputFormat(qprint.QPrinter.NativeFormat)
        printer_dialog = qprint.QPrintDialog(printer, self)
        if printer_dialog.exec_() == qw.QDialog.Accepted:

            scrollbarpolicy = self.verticalScrollBarPolicy()
            self.setVerticalScrollBarPolicy(qc.Qt.ScrollBarAlwaysOff)
            rect = printer.pageRect()
            painter = qg.QPainter()
            painter.begin(printer)
            xscale = rect.width() / (self.width()*1.1)
            yscale = rect.height() / (self.height() * 1.1)
            scale = min(xscale, yscale)
            painter.translate(rect.x() + rect.width()/2.,
                              rect.y() + rect.height()/2.)
            painter.scale(scale, scale)
            painter.translate(-self.width()/2., -self.height()/2.)
            painter.setRenderHints(qg.QPainter.HighQualityAntialiasing |
                                   qg.QPainter.TextAntialiasing)
            self.render(painter)
            painter.end()
            self.setVerticalScrollBarPolicy(scrollbarpolicy)

    def table_double_clicked(self, model_index):
        if model_index.column() in self.editable_columns:
            return
        else:
            self.pile_viewer.go_to_selection()

    def show_context_menu(self, point):
        '''
        Pop-up menu to toggle column visibility.
        '''

        self.header_menu.popup(self.mapToGlobal(point))

    def toggle_columns(self):
        '''
        Toggle columns depending in checked state.
        '''

        width = 0
        for header, ca in self.column_actions.items():
            hide = not ca.isChecked()
            self.setColumnHidden(self.menu_items[header], hide)
            if header == 'Latitude/Longitude':
                self.setColumnHidden(self.menu_items[header]+1, hide)
            if not hide:
                width += _header_sizes[self.menu_labels.index(header)]

        self.parent().setMinimumWidth(width)

    def update_viewport(self):
        self.viewport().update()


class MarkerTableModel(qc.QAbstractTableModel):

    def __init__(self, *args, **kwargs):
        qc.QAbstractTableModel.__init__(self, *args, **kwargs)
        self.pile_viewer = None
        self.distances = {}
        self.kagan_angles = {}
        self.row_count = 0
        self.proxy_filter = None

    def sourceModel(self):
        return self

    def set_viewer(self, viewer):
        '''
        Set connected pile viewer and hook up signals.
        '''

        self.pile_viewer = viewer
        self.pile_viewer.begin_markers_add.connect(
            self.begin_markers_add)
        self.pile_viewer.end_markers_add.connect(
            self.end_markers_add)
        self.pile_viewer.begin_markers_remove.connect(
            self.begin_markers_remove)
        self.pile_viewer.end_markers_remove.connect(
            self.end_markers_remove)

    def rowCount(self, parent=None):
        if not self.pile_viewer:
            return 0
        return len(self.pile_viewer.get_markers())

    def columnCount(self, parent=None):
        return len(_column_mapping)

    def begin_markers_add(self, istart, istop):
        self.beginInsertRows(qc.QModelIndex(), istart, istop)

    def end_markers_add(self):
        self.endInsertRows()

    def begin_markers_remove(self, istart, istop):
        self.beginRemoveRows(qc.QModelIndex(), istart, istop)

    def end_markers_remove(self):
        self.endRemoveRows()
        self.marker_table_view.updateGeometries()

    def headerData(self, col, orientation, role):
        '''
        Get header data entry.
        '''

        if orientation == qc.Qt.Horizontal:
            if role == qc.Qt.DisplayRole:
                return qc.QVariant(_header_data[col])
            elif role == qc.Qt.SizeHintRole:
                return qc.QSize(10, 20)

        elif orientation == qc.Qt.Vertical:
            if role == qc.Qt.DisplayRole:
                return qc.QVariant(str(col))

        else:
            return qc.QVariant()

    def get_marker(self, index):
        return self.pile_viewer.markers[index.row()]

    def data(self, index, role):
        '''
        Get model data entry.
        '''

        if not self.pile_viewer:
            return qc.QVariant()

        marker = self.pile_viewer.markers[index.row()]
        column = index.column()

        if role == qc.Qt.BackgroundRole:
            if marker.active or column == _column_mapping['T']:
                return qg.QBrush(
                    qg.QColor(*marker.select_color(g_color_b_faint)))

        if role == qc.Qt.ForegroundRole:
            if marker.active or column == _column_mapping['T']:
                return qg.QBrush(
                    qg.QColor(*marker.select_color(g_color_b)))

        elif role in (qc.Qt.DisplayRole, qc.Qt.UserRole):

            v = None
            if column == _column_mapping['Time']:
                if role == qc.Qt.UserRole:
                    v = marker.tmin
                else:
                    v = time_to_str(marker.tmin)

            elif column == _column_mapping['T']:
                if isinstance(marker, EventMarker):
                    v = u'\u25ce'
                elif isinstance(marker, PhaseMarker):
                    v = marker.get_label()

            elif column == _column_mapping['M']:
                if isinstance(marker, EventMarker):
                    e = marker.get_event()
                    if e.moment_tensor is not None:
                        v = round(e.moment_tensor.magnitude, 1)
                    elif e.magnitude is not None:
                        v = round(e.magnitude, 1)

            elif column == _column_mapping['Label']:
                if isinstance(marker, EventMarker):
                    v = marker.label()
                elif isinstance(marker, PhaseMarker):
                    v = marker.get_label()

            elif column == _column_mapping['Depth [km]']:
                if isinstance(marker, EventMarker):
                    d = marker.get_event().depth
                    if d is not None:
                        v = round(marker.get_event().depth/1000., 1)

            elif column == _column_mapping['Lat']:
                if isinstance(marker, EventMarker):
                    v = round(marker.get_event().effective_lat, 2)

            elif column == _column_mapping['Lon']:
                if isinstance(marker, EventMarker):
                    v = round(marker.get_event().effective_lon, 2)

            elif column == _column_mapping['Kind']:
                v = marker.kind

            elif column == _column_mapping['Dist [km]']:
                active_event = self.pile_viewer.get_active_event()
                if isinstance(marker, EventMarker) \
                        and active_event is not None:

                    dist = orthodrome.distance_accurate50m(
                        marker.get_event(),
                        active_event)

                    v = dist
                    if role == qc.Qt.DisplayRole:
                        v = '%.5g' % (v/1000.)

            elif column == _column_mapping['NSLCs']:
                strs = []
                for nslc_id in marker.get_nslc_ids():
                    strs.append('.'.join(nslc_id))
                v = '|'.join(strs)

            elif column == _column_mapping['Kagan Angle [deg]']:
                active_event = self.pile_viewer.get_active_event()
                if isinstance(marker, EventMarker) \
                        and active_event is not None \
                        and active_event.moment_tensor is not None \
                        and marker.get_event().moment_tensor is not None:

                    v = kagan_angle(
                        active_event.moment_tensor,
                        marker.get_event().moment_tensor)

                    if role == qc.Qt.DisplayRole:
                        v = '%.1f' % v

            elif column == _column_mapping['MT']:
                return qc.QVariant()

            elif column == _column_mapping['Event Hash']:
                if isinstance(marker, (EventMarker, PhaseMarker)):
                    v = marker.get_event_hash()
                else:
                    return qc.QVariant()

            elif column == _column_mapping['Polarity']:
                if isinstance(marker, (PhaseMarker)):
                    v = marker.get_polarity_symbol()
                else:
                    return qc.QVariant()

            return qc.QVariant(v)

        return qc.QVariant()

    def handle_active_event_changed(self):
        nmarkers = self.rowCount()
        istart = self.index(0, _column_mapping['Dist [km]'])
        istop = self.index(nmarkers-1, _column_mapping['Dist [km]'])
        self.dataChanged.emit(istart, istop)

        istart = self.index(0, _column_mapping['Kagan Angle [deg]'])
        istop = self.index(nmarkers-1, _column_mapping['Kagan Angle [deg]'])
        self.dataChanged.emit(istart, istop)

    def done(self, index):
        self.dataChanged.emit(index, index)
        return True

    def setData(self, index, value, role):
        '''
        Set model data entry.
        '''

        if role == qc.Qt.EditRole:
            imarker = index.row()
            marker = self.pile_viewer.markers[imarker]
            if index.column() in [_column_mapping[c] for c in [
                    'M', 'Lat', 'Lon', 'Depth [km]']]:

                if not isinstance(marker, EventMarker):
                    return False
                else:
                    if index.column() == _column_mapping['M']:
                        valuef, valid = toFloat(value)
                        if valid:
                            e = marker.get_event()
                            if e.moment_tensor is None:
                                e.magnitude = valuef
                            else:
                                e.moment_tensor.magnitude = valuef
                            return self.done(index)

                if index.column() in [_column_mapping['Lon'],
                                      _column_mapping['Lat'],
                                      _column_mapping['Depth [km]']]:
                    if isinstance(marker, EventMarker):
                        valuef, valid = toFloat(value)
                        if valid:
                            if index.column() == _column_mapping['Lat']:
                                marker.get_event().lat = valuef
                            elif index.column() == _column_mapping['Lon']:
                                marker.get_event().lon = valuef
                            elif index.column() == _column_mapping[
                                    'Depth [km]']:
                                marker.get_event().depth = valuef*1000.
                            return self.done(index)

            if index.column() == _column_mapping['Label']:
                values = str(value)
                if values != '':
                    if isinstance(marker, EventMarker):
                        marker.get_event().set_name(values)
                        return self.done(index)

                    if isinstance(marker, PhaseMarker):
                        marker.set_phasename(values)
                        return self.done(index)

        return False

    def flags(self, index):
        '''
        Set flags for cells which the user can edit.
        '''

        if index.column() not in self.marker_table_view.editable_columns:
            return qc.Qt.ItemFlags(33)
        else:
            if isinstance(self.pile_viewer.markers[index.row()], EventMarker):
                if index.column() in self.marker_table_view.editable_columns:
                    return qc.Qt.ItemFlags(35)
            if index.column() == _column_mapping['Label']:
                return qc.Qt.ItemFlags(35)
        return qc.Qt.ItemFlags(33)


class MarkerEditor(qw.QFrame):

    def __init__(self, *args, **kwargs):
        sortable = kwargs.pop('sortable', True)
        qw.QFrame.__init__(self, *args, **kwargs)
        layout = qw.QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.marker_table_view = MarkerTableView(self, sortable=sortable)

        self.delegate = MarkerItemDelegate(self.marker_table_view)
        self.marker_table_view.setItemDelegate(self.delegate)

        self.marker_model = MarkerTableModel()
        self.marker_model.marker_table_view = self.marker_table_view

        if sortable:
            self.proxy_filter = MarkerSortFilterProxyModel()
            self.proxy_filter.setDynamicSortFilter(True)
            self.proxy_filter.setSourceModel(self.marker_model)
            self.marker_model.proxy_filter = self.proxy_filter

            self.marker_table_view.setModel(self.proxy_filter)
        else:
            self.proxy_filter = None
            self.marker_table_view.setModel(self.marker_model)

        header = self.marker_table_view.horizontalHeader()
        for i_s, s in enumerate(_header_sizes):
            header.setSectionResizeMode(i_s, qw.QHeaderView.Interactive)
            header.resizeSection(i_s, s)

        header.setStretchLastSection(True)

        if self.proxy_filter:
            self.selection_model = qc.QItemSelectionModel(self.proxy_filter)
        else:
            self.selection_model = qc.QItemSelectionModel(self.marker_model)

        self.marker_table_view.setSelectionModel(self.selection_model)
        self.selection_model.selectionChanged.connect(
            self.set_selected_markers)

        layout.addWidget(self.marker_table_view, 0, 0)

        self.pile_viewer = None
        self._size_hint = qc.QSize(1, 1)

    def set_viewer(self, viewer):
        '''
        Set the pile viewer and connect signals.
        '''

        self.pile_viewer = viewer
        self.marker_model.set_viewer(viewer)
        self.marker_table_view.set_viewer(viewer)
        self.pile_viewer.marker_selection_changed.connect(
            self.update_selection_model)

        self.pile_viewer.active_event_marker_changed.connect(
             self.marker_model.handle_active_event_changed)

        # self.pile_viewer.active_event_marker_changed.connect(
        #      self.marker_table_view.update_viewport)

        self.marker_table_view.toggle_columns()

    def set_selected_markers(self, selected, deselected):
        '''
        Update selection in viewer to reflect changes in table data.
        '''

        if self.proxy_filter:
            def to_source(x):
                ind = self.proxy_filter.index(x, 0)
                return self.proxy_filter.mapToSource(ind).row()
        else:
            def to_source(x):
                return x

        markers = self.pile_viewer.markers

        for rsel in selected:
            for i in range(rsel.top(), rsel.bottom()+1):
                marker = markers[to_source(i)]
                if not marker.selected:
                    marker.selected = True
                    self.pile_viewer.n_selected_markers += 1

        for rsel in deselected:
            for i in range(rsel.top(), rsel.bottom()+1):
                marker = markers[to_source(i)]
                if marker.selected:
                    marker.selected = False
                    self.pile_viewer.n_selected_markers -= 1

        self.pile_viewer.update()

    def get_marker_model(self):
        '''
        Get the attached Qt table data model.

        :returns: :py:class:`MarkerTableModel` object
        '''

        return self.marker_model

    def update_selection_model(self, indices):
        '''
        Set currently selected table rows.

        :param indices: begin and end+1 indices of contiguous selection chunks
        :type indices: list of tuples
        '''
        self.selection_model.clearSelection()
        selections = qc.QItemSelection()
        selection_flags = qc.QItemSelectionModel.SelectionFlags(int(
            qc.QItemSelectionModel.Select |
            qc.QItemSelectionModel.Rows |
            qc.QItemSelectionModel.Current))

        for chunk in indices:
            mi_start = self.marker_model.index(chunk[0], 0)
            mi_stop = self.marker_model.index(chunk[1]-1, 0)
            if self.proxy_filter:
                row_selection = self.proxy_filter.mapSelectionFromSource(
                    qc.QItemSelection(mi_start, mi_stop))
            else:
                row_selection = qc.QItemSelection(mi_start, mi_stop)
            selections.merge(row_selection, selection_flags)

        if len(indices) != 0:
            if self.proxy_filter:
                self.marker_table_view.scrollTo(
                    self.proxy_filter.mapFromSource(mi_start))
            else:
                self.marker_table_view.scrollTo(mi_start)

            self.marker_table_view.setCurrentIndex(mi_start)
            self.selection_model.setCurrentIndex(
                mi_start, selection_flags)

        self.selection_model.select(selections, selection_flags)
