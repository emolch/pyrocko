# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import

import sys

from .qt_compat import qc, qg, qw, QSortFilterProxyModel, \
    QItemSelectionModel, QItemSelection, QPixmapCache, use_pyqt5

from .util import EventMarker, PhaseMarker, make_QPolygonF
from pyrocko.plot.beachball import mt2beachball, BeachballError
from pyrocko.moment_tensor import kagan_angle
from pyrocko.plot import tango_colors
from pyrocko import orthodrome

import numpy as num
import logging


def noop(x=None):
    return x


if sys.version_info[0] >= 3 or use_pyqt5:
    qc.QString = str
    qc.QVariant = noop

    def toDateTime(val):
        return val

    def isDateTime(val):
        return isinstance(val, qc.QDateTime)

    def toFloat(val):
        try:
            return float(val), True
        except ValueError:
            return 9e99, False

    def toString(val):
        return str(val).encode('utf-8').decode()

else:
    def toDateTime(val):
        return val.toDateTime()

    def isDateTime(val):
        return val.type() == qc.QVariant.DateTime

    def toFloat(val):
        return val.toFloat()

    def toString(val):
        return str(val).encode('utf-8')


logger = logging.getLogger('pyrocko.gui.marker_editor')

_header_data = [
    'Type', 'Time', 'M', 'Label', 'Depth [km]', 'Lat', 'Lon', 'Kind',
    'Dist [km]', 'NSLCs', 'Polarity', 'Kagan Angle [deg]', 'Event Hash',
    'MT']

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
    '''Takes care of the table's style.'''

    def __init__(self, *args, **kwargs):
        qw.QStyledItemDelegate.__init__(self, *args, **kwargs)
        self.c_alignment = qc.Qt.AlignHCenter
        self.bbcache = QPixmapCache()

    def paint(self, painter, option, index):
        iactive = self.parent().active_event_index
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
            qw.QStyledItemDelegate.paint(self, painter, option, index)

        if iactive is not None and \
                self.parent().model().mapToSource(index).row() == iactive:

            painter.save()

            rect = option.rect
            x1, y1, x2, y2 = rect.getCoords()
            pen = painter.pen()
            pen.setWidth(2)
            pen.setColor(mcolor)
            painter.setPen(pen)
            painter.drawLine(qc.QLineF(x1, y1, x2, y1))
            painter.drawLine(qc.QLineF(x1, y2, x2, y2))
            painter.restore()

    def displayText(self, value, locale):
        if isDateTime(value):
            return toDateTime(value).toUTC().toString(
                'yyyy-MM-dd HH:mm:ss.zzz')
        else:
            return toString(value)

    def marker_from_index(self, index):
        tv = self.parent()
        pv = tv.pile_viewer
        return pv.markers[tv.model().mapToSource(index).row()]

    def bb_data_from_index(self, index):
        marker = self.marker_from_index(index)
        if isinstance(marker, EventMarker):
            return marker.get_event().moment_tensor
        else:
            return None

    def color_from_index(self, index):
        marker = self.marker_from_index(index)
        return qg.QColor(*marker.select_color(marker.color_b))


class MarkerSortFilterProxyModel(QSortFilterProxyModel):
    '''Sorts the table's columns.'''

    def __init__(self, *args, **kwargs):
        QSortFilterProxyModel.__init__(self, *args, **kwargs)
        self.sort(1, qc.Qt.DescendingOrder)

    def lessThan(self, left, right):
        if left.column() in [0, 3, 9, 10, 12]:
            return toString(left.data()) < toString(right.data())
        elif left.column() == 1:
            return toDateTime(left.data()) < toDateTime(right.data())
        else:
            return toFloat(left.data())[0] < toFloat(right.data())[0]

    def headerData(self, col, orientation, role):
        '''Set and format header data.'''
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

    def sort(self, column, order):
        if column != _column_mapping['MT']:
            super(MarkerSortFilterProxyModel, self).sort(column, order)


class MarkerTableView(qw.QTableView):
    def __init__(self, *args, **kwargs):
        qw.QTableView.__init__(self, *args, **kwargs)
        self.setSelectionBehavior(qw.QAbstractItemView.SelectRows)
        self.setHorizontalScrollMode(qw.QAbstractItemView.ScrollPerPixel)
        self.setEditTriggers(qw.QAbstractItemView.DoubleClicked)
        self.setSortingEnabled(True)
        self.setStyleSheet(
            'QTableView{selection-background-color: \
            rgba(130, 130, 130, 100% );}')

        self.sortByColumn(1, qc.Qt.DescendingOrder)
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

        self.active_event_index = None

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

            if use_pyqt5:
                wheel_delta = wheel_event.angleDelta().y()
            else:
                wheel_delta = wheel_event.delta()

            v.setDefaultSectionSize(
                max(12, v.defaultSectionSize()+wheel_delta//60))
            self.scrollTo(ci)
            if v.isVisible():
                self.toggle_numbering(False)
                self.toggle_numbering(True)

        else:
            super(MarkerTableView, self).wheelEvent(wheel_event)

    def set_viewer(self, viewer):
        '''Set a pile_viewer and connect to signals.'''

        self.pile_viewer = viewer

    def keyPressEvent(self, key_event):
        '''Propagate ``key_event`` to pile_viewer, unless up/down pressed.'''
        if key_event.key() in [qc.Qt.Key_Up, qc.Qt.Key_Down]:
            qw.QTableView.keyPressEvent(self, key_event)
            self.pile_viewer.go_to_selection()
        else:
            self.pile_viewer.keyPressEvent(key_event)

    def table_clicked(self, model_index):
        '''Ignore mouse clicks.'''
        pass

    def contextMenuEvent(self, event):
        self.right_click_menu.popup(qg.QCursor.pos())

    def toggle_numbering(self, want):
        if want:
            self.verticalHeader().show()
        else:
            self.verticalHeader().hide()

    def print_menu(self):
        from .qt_compat import qprint
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
        '''Pop-up menu to toggle columns in the :py:class:`MarkerTableView`.'''

        self.header_menu.popup(self.mapToGlobal(point))

    def toggle_columns(self):
        '''Toggle columns depending in checked state. '''
        width = 0
        want_distances = False
        want_angles = False
        for header, ca in self.column_actions.items():
            hide = not ca.isChecked()
            self.setColumnHidden(self.menu_items[header], hide)
            if header == 'Latitude/Longitude':
                self.setColumnHidden(self.menu_items[header]+1, hide)
            if not hide:
                width += _header_sizes[self.menu_labels.index(header)]
            if header == 'Distance [km]':
                want_distances = True
            elif header == 'Kagan Angle [deg]':
                want_angles = True

        if self.active_event_index:
            self.model().sourceModel().update_distances_and_angles(
                [[self.active_event_index]],
                want_distances=want_distances, want_angles=want_angles)
        self.parent().setMinimumWidth(width)

    def set_active_event_index(self, i):
        if i == -1:
            i = None
        self.active_event_index = i
        self.viewport().update()


class MarkerTableModel(qc.QAbstractTableModel):

    def __init__(self, *args, **kwargs):
        qc.QAbstractTableModel.__init__(self, *args, **kwargs)
        self.pile_viewer = None
        self.distances = {}
        self.kagan_angles = {}
        self.last_active_event = None
        self.row_count = 0
        self.proxy_filter = None

    def set_viewer(self, viewer):
        '''Set a pile_viewer and connect to signals.'''

        self.pile_viewer = viewer
        self.pile_viewer.markers_added.connect(
                     self.markers_added)

        self.pile_viewer.markers_removed.connect(
                     self.markers_removed)

        self.pile_viewer.changed_marker_selection.connect(
                     self.update_distances_and_angles)

    def rowCount(self, parent):
        if not self.pile_viewer:
            return 0
        return len(self.pile_viewer.get_markers())

    def columnCount(self, parent):
        return len(_column_mapping)

    def markers_added(self, istart, istop):
        '''Insert rows into table.'''

        self.beginInsertRows(qc.QModelIndex(), istart, istop)
        self.endInsertRows()

    def markers_removed(self, i_from, i_to):
        '''Remove rows from table.'''

        self.beginRemoveRows(qc.QModelIndex(), i_from, i_to)
        self.endRemoveRows()
        self.marker_table_view.updateGeometries()

    def data(self, index, role):
        '''Set data in each of the table's cell.'''

        if not self.pile_viewer:
            return qc.QVariant()

        marker = self.pile_viewer.markers[index.row()]

        if role == qc.Qt.DisplayRole:
            s = ''
            column = index.column()
            if column == _column_mapping['Time']:
                return qc.QVariant(
                    qc.QDateTime.fromMSecsSinceEpoch(marker.tmin*1000))

            elif column == _column_mapping['Type']:
                if isinstance(marker, EventMarker):
                    s = 'Event'
                elif isinstance(marker, PhaseMarker):
                    s = 'Phase'

            elif column == _column_mapping['M']:
                if isinstance(marker, EventMarker):
                    e = marker.get_event()
                    if e.moment_tensor is not None:
                        s = round(e.moment_tensor.magnitude, 1)
                    elif e.magnitude is not None:
                        s = round(e.magnitude, 1)

            elif column == _column_mapping['Label']:
                if isinstance(marker, EventMarker):
                    s = marker.label()
                elif isinstance(marker, PhaseMarker):
                    s = marker.get_label()

            elif column == _column_mapping['Depth [km]']:
                if isinstance(marker, EventMarker):
                    d = marker.get_event().depth
                    if d is not None:
                        s = round(marker.get_event().depth/1000., 1)

            elif column == _column_mapping['Lat']:
                if isinstance(marker, EventMarker):
                    s = round(marker.get_event().lat, 2)

            elif column == _column_mapping['Lon']:
                if isinstance(marker, EventMarker):
                    s = round(marker.get_event().lon, 2)

            elif column == _column_mapping['Kind']:
                s = marker.kind

            elif column == _column_mapping['Dist [km]']:
                if marker in self.distances:
                    s = self.distances[marker]

            elif column == _column_mapping['NSLCs']:
                strs = []
                for nslc_id in marker.get_nslc_ids():
                    strs.append('.'.join(nslc_id))
                s = '|'.join(strs)

            elif column == _column_mapping['Kagan Angle [deg]']:
                if marker in self.kagan_angles:
                    s = round(self.kagan_angles[marker], 1)

            elif column == _column_mapping['MT']:
                return qc.QVariant()

            elif column == _column_mapping['Event Hash']:
                if isinstance(marker, (EventMarker, PhaseMarker)):
                    s = marker.get_event_hash()
                else:
                    return qc.QVariant()

            elif column == _column_mapping['Polarity']:
                if isinstance(marker, (PhaseMarker)):
                    s = marker.get_polarity_symbol()
                else:
                    return qc.QVariant()

            return qc.QVariant(s)

        return qc.QVariant()

    def update_distances_and_angles(self, indices=None, want_angles=False,
                                    want_distances=False):
        '''Calculate and update distances and kagan angles between events.

        :param indices: list of lists of indices (optional)

        Ideally, indices are consecutive for best performance.'''
        want_angles = want_angles or \
            not self.marker_table_view.isColumnHidden(
                _column_mapping['Kagan Angle [deg]'])
        want_distances = want_distances or \
            not self.marker_table_view.isColumnHidden(
                _column_mapping['Dist [km]'])

        if not (want_distances or want_angles):
            return

        indices = indices or [[]]
        indices = [i for ii in indices for i in ii]

        if len(indices) != 1:
            return

        if self.last_active_event == self.pile_viewer.get_active_event():
            return
        else:
            self.last_active_event = self.pile_viewer.get_active_event()

        markers = self.pile_viewer.markers
        nmarkers = len(markers)
        omarker = markers[indices[0]]
        if not isinstance(omarker, EventMarker):
            return
        else:
            oevent = omarker.get_event()

        emarkers = [m for m in markers if isinstance(m, EventMarker)]
        if len(emarkers) < 2:
            return
        else:
            events = [em.get_event() for em in emarkers]
            nevents = len(events)

        if want_distances:
            lats = num.zeros(nevents)
            lons = num.zeros(nevents)
            for i in range(nevents):
                lats[i] = events[i].effective_lat
                lons[i] = events[i].effective_lon

            olats = num.zeros(nevents)
            olons = num.zeros(nevents)
            olats[:] = oevent.effective_lat
            olons[:] = oevent.effective_lon
            dists = orthodrome.distance_accurate50m_numpy(
                lats, lons, olats, olons)
            dists /= 1000.

            dists = [round(x, 1) for x in dists]
            self.distances = dict(zip(emarkers, dists))

        if want_angles:
            if oevent.moment_tensor:
                for em in emarkers:
                    e = em.get_event()
                    if e.moment_tensor:
                        a = kagan_angle(oevent.moment_tensor, e.moment_tensor)
                        self.kagan_angles[em] = a
            else:
                self.kagan_angles = {}

        istart = self.index(0, _column_mapping['Dist [km]'])
        istop = self.index(nmarkers-1, _column_mapping['Kagan Angle [deg]'])

        self.dataChanged.emit(
                  istart,
                  istop)

    def done(self, index):
        self.dataChanged.emit(index, index)
        return True

    def setData(self, index, value, role):
        '''Manipulate :py:class:`EventMarker` instances.'''
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
                values = str(toString(value))
                if values != '':
                    if isinstance(marker, EventMarker):
                        marker.get_event().set_name(values)
                        return self.done(index)

                    if isinstance(marker, PhaseMarker):
                        marker.set_phasename(values)
                        return self.done(index)

        return False

    def flags(self, index):
        '''Set flags for cells which the user can edit.'''

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
        qw.QFrame.__init__(self, *args, **kwargs)
        layout = qw.QGridLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(layout)
        self.marker_table_view = MarkerTableView(self)
        self.delegate = MarkerItemDelegate(self.marker_table_view)
        self.marker_table_view.setItemDelegate(self.delegate)

        self.marker_model = MarkerTableModel()
        self.marker_model.marker_table_view = self.marker_table_view

        self.proxy_filter = MarkerSortFilterProxyModel()
        self.proxy_filter.setDynamicSortFilter(True)
        self.proxy_filter.setSourceModel(self.marker_model)
        self.marker_model.proxy_filter = self.proxy_filter

        self.marker_table_view.setModel(self.proxy_filter)

        header = self.marker_table_view.horizontalHeader()
        for i_s, s in enumerate(_header_sizes):
            if use_pyqt5:
                header.setSectionResizeMode(i_s, qw.QHeaderView.Interactive)
            else:
                header.setResizeMode(i_s, qw.QHeaderView.Interactive)

            header.resizeSection(i_s, s)

        header.setStretchLastSection(True)

        self.selection_model = QItemSelectionModel(self.proxy_filter)
        self.marker_table_view.setSelectionModel(self.selection_model)
        self.selection_model.selectionChanged.connect(
            self.set_selected_markers)

        layout.addWidget(self.marker_table_view, 0, 0)

        self.pile_viewer = None
        self._size_hint = qc.QSize(1, 1)

    def set_viewer(self, viewer):
        '''Set a pile_viewer and connect to signals.'''

        self.pile_viewer = viewer
        self.marker_model.set_viewer(viewer)
        self.marker_table_view.set_viewer(viewer)
        self.pile_viewer.changed_marker_selection.connect(
            self.update_selection_model)

        self.pile_viewer.active_event_marker_changed.connect(
            self.marker_table_view.set_active_event_index)

        self.marker_table_view.toggle_columns()

    def set_selected_markers(self, selected, deselected):
        ''' set markers selected in viewer at selection in table.'''

        selected_markers = []
        for i in self.selection_model.selectedRows():
            selected_markers.append(
                self.pile_viewer.markers[
                    self.proxy_filter.mapToSource(i).row()])

        self.pile_viewer.set_selected_markers(selected_markers)

    def get_marker_model(self):
        '''Return :py:class:`MarkerTableModel` instance'''

        return self.marker_model

    def update_selection_model(self, indices):
        '''Adopt marker selections done in the pile_viewer in the tableview.

        :param indices: list of indices of selected markers.'''
        self.selection_model.clearSelection()
        selections = QItemSelection()
        selection_flags = QItemSelectionModel.SelectionFlags(
            (QItemSelectionModel.Select |
             QItemSelectionModel.Rows |
             QItemSelectionModel.Current))

        for chunk in indices:
            mi_start = self.marker_model.index(min(chunk), 0)
            mi_stop = self.marker_model.index(max(chunk), 0)
            row_selection = self.proxy_filter.mapSelectionFromSource(
                QItemSelection(mi_start, mi_stop))
            selections.merge(row_selection, selection_flags)

        if len(indices) != 0:
            self.marker_table_view.scrollTo(self.proxy_filter.mapFromSource(
                mi_start))
            self.marker_table_view.setCurrentIndex(mi_start)
            self.selection_model.setCurrentIndex(
                mi_start, selection_flags)

        self.selection_model.select(selections, selection_flags)
