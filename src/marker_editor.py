import numpy as num
from PyQt4 import QtCore as qc
from PyQt4 import QtGui as qg

from pyrocko.gui_util import EventMarker, PhaseMarker, make_QPolygonF
from pyrocko.beachball import mt2beachball, BeachballError
from pyrocko import orthodrome, moment_tensor
from pyrocko.plot import tango_colors
import logging

logger = logging.getLogger('pyrocko.marker_editor')

_header_data = [
    'T', 'Time', 'M', 'Label', 'Depth [km]', 'Lat', 'Lon', 'Kind', 'Dist [km]',
    'Kagan Angle [deg]', 'MT']

_column_mapping = dict(zip(_header_data, range(len(_header_data))))

_string_header = (_column_mapping['Time'], _column_mapping['Label'])

_header_sizes = [70] * len(_header_data)
_header_sizes[0] = 40
_header_sizes[1] = 190
_header_sizes[10] = 20


class BeachballWidget(qg.QWidget):

    def __init__(self, moment_tensor=None, *args, **kwargs):
        qg.QWidget.__init__(self, *args, **kwargs)
        self.colors = {'white': qc.Qt.white,
                       'green': qc.Qt.green,
                       'red': qc.Qt.red,
                       'none': None}
        self.brushs_pens = {}
        for k, c in self.colors.items():
            pen = qg.QPen(c)
            pen.setWidthF(3)
            self.brushs_pens[k] = (qg.QBrush(c), pen)
        self.moment_tensor = moment_tensor
        self.setGeometry(0, 0, 100, 100)
        self.setAttribute(qc.Qt.WA_TranslucentBackground)

    def paintEvent(self, e):
        center = e.rect().center()
        painter = qg.QPainter(self)
        painter.save()
        try:
            data = mt2beachball(self.moment_tensor, size=self.height()/2.2,
                                position=(center.x(), center.y()))
            for pdata in data:
                paths, fill, edges, thickness = pdata
                brush, pen = self.brushs_pens[fill]
                polygon = qg.QPolygonF()
                polygon = make_QPolygonF(*paths.T)
                painter.setRenderHint(qg.QPainter.Antialiasing)
                painter.setBrush(brush)
                painter.setPen(pen)
                painter.drawPolygon(polygon)
        except BeachballError as e:
            logger.exception(e)
        finally:
            painter.restore()

    def to_qpixmap(self):
        return qg.QPixmap().grabWidget(self, self.rect())


class MarkerItemDelegate(qg.QStyledItemDelegate):
    '''Takes care of the table's style.'''

    def __init__(self, *args, **kwargs):
        qg.QStyledItemDelegate.__init__(self, *args, **kwargs)
        self.c_alignment = qc.Qt.AlignHCenter
        self.bbcache = qg.QPixmapCache()

    def paint(self, painter, option, index):
        iactive = self.parent().active_event_index

        if iactive is not None and \
                self.parent().model().mapToSource(index).row() == iactive:
                painter.save()

                rect = option.rect
                x1, y1, x2, y2 = rect.getCoords()
                pen = painter.pen()
                pen.setWidth(2)
                pen.setColor(qg.QColor(*tango_colors['scarletred3']))
                painter.setPen(pen)
                painter.drawLine(qc.QLineF(x1, y1, x2, y1))
                painter.drawLine(qc.QLineF(x1, y2, x2, y2))
                painter.restore()

        if index.column() == 10:
            mt = self.get_mt_from_index(index)
            if mt:
                key = qc.QString(
                    ''.join(map(lambda x: str(round(x, 1)), mt.m6())))
                pixmap = qg.QPixmap()
                found = self.bbcache.find(key, pixmap)
                if found:
                    pixmap = pixmap.scaledToHeight(option.rect.height())
                else:
                    pixmap = BeachballWidget(mt).to_qpixmap()
                    self.bbcache.insert(key, pixmap)
                a, b, c, d = option.rect.getRect()
                painter.save()
                painter.setRenderHint(qg.QPainter.Antialiasing)
                painter.drawPixmap(a+d/2., b, d, d, pixmap)
                painter.restore()

        else:
            qg.QStyledItemDelegate.paint(self, painter, option, index)

    def displayText(self, value, locale):
        if (value.type() == qc.QVariant.DateTime):
            return value.toDateTime().toUTC().toString(
                'yyyy-MM-dd HH:mm:ss.zzz')
        else:
            return value.toString()

    def get_mt_from_index(self, index):
        tv = self.parent()
        pv = tv.pile_viewer
        marker = pv.markers[tv.model().mapToSource(index).row()]
        if isinstance(marker, EventMarker):
            return marker.get_event().moment_tensor
        else:
            return None


class MarkerSortFilterProxyModel(qg.QSortFilterProxyModel):
    '''Sorts the table's columns.'''

    def __init__(self, *args, **kwargs):
        qg.QSortFilterProxyModel.__init__(self, *args, **kwargs)
        self.sort(1, qc.Qt.DescendingOrder)

    def lessThan(self, left, right):
        if left.column() == 1:
            return left.data().toDateTime() < right.data().toDateTime()
        elif left.column() == 3:
            return left.data().toString() < right.data().toString()
        else:
            return left.data().toFloat()[0] < right.data().toFloat()[0]


class MarkerTableView(qg.QTableView):
    def __init__(self, *args, **kwargs):
        qg.QTableView.__init__(self, *args, **kwargs)
        self.setSelectionBehavior(qg.QAbstractItemView.SelectRows)
        self.setHorizontalScrollMode(qg.QAbstractItemView.ScrollPerPixel)
        self.setEditTriggers(qg.QAbstractItemView.DoubleClicked)
        self.setSortingEnabled(True)
        self.setStyleSheet(
            'QTableView{selection-background-color: \
            rgba(130, 130, 130, 100% );}')

        self.sortByColumn(1, qc.Qt.DescendingOrder)
        self.setAlternatingRowColors(True)

        self.setShowGrid(False)
        self.verticalHeader().hide()
        self.pile_viewer = None

        self.connect(self, qc.SIGNAL('clicked(QModelIndex)'), self.clicked)
        self.connect(
            self,
            qc.SIGNAL('doubleClicked(QModelIndex)'),
            self.double_clicked)

        self.header_menu = qg.QMenu(self)

        show_initially = ['Type', 'Time', 'Magnitude']
        self.menu_labels = ['Type', 'Time', 'Magnitude', 'Label', 'Depth [km]',
                            'Latitude/Longitude', 'Kind', 'Distance [km]',
                            'Kagan Angle [deg]', 'MT']
        self.menu_items = dict(zip(self.menu_labels,
                                   [0, 1, 2, 3, 4, 5, 7, 8, 9, 10]))

        self.editable_columns = [2, 3, 4, 5, 6, 7]

        self.column_actions = {}
        for hd in self.menu_labels:
            a = qg.QAction(qc.QString(hd), self.header_menu)
            self.connect(a, qc.SIGNAL('triggered(bool)'), self.toggle_columns)
            a.setCheckable(True)
            if hd in show_initially:
                a.setChecked(True)
            else:
                a.setChecked(False)
            self.header_menu.addAction(a)
            self.column_actions[hd] = a

        header = self.horizontalHeader()
        header.setContextMenuPolicy(qc.Qt.CustomContextMenu)
        self.connect(
            header,
            qc.SIGNAL('customContextMenuRequested(QPoint)'),
            self.show_context_menu)

        self.active_event_index = None

        self.right_click_menu = qg.QMenu(self)
        print_action = qg.QAction('Print Table', self.right_click_menu)
        print_action.triggered.connect(self.print_menu)
        self.right_click_menu.addAction(print_action)

    def set_viewer(self, viewer):
        '''Set a pile_viewer and connect to signals.'''

        self.pile_viewer = viewer

    def keyPressEvent(self, key_event):
        '''Propagate ``key_event`` to pile_viewer, unless up/down pressed.'''
        if key_event.key() in [qc.Qt.Key_Up, qc.Qt.Key_Down]:
            qg.QTableView.keyPressEvent(self, key_event)
            self.pile_viewer.go_to_selection()
        else:
            self.pile_viewer.keyPressEvent(key_event)

    def clicked(self, model_index):
        '''Ignore mouse clicks.'''
        pass

    def contextMenuEvent(self, event):
        self.right_click_menu.popup(qg.QCursor.pos())

    def print_menu(self):
        printer = qg.QPrinter(qg.QPrinter.ScreenResolution)
        printer_dialog = qg.QPrintDialog(printer, self)
        if printer_dialog.exec_() == qg.QDialog.Accepted:
            rect = printer.pageRect()
            painter = qg.QPainter()
            painter.begin(printer)
            xscale = rect.width() / (self.width()*1.1)
            yscale = rect.height() / (self.height() * 1.1)
            scale = min(xscale, yscale)
            painter.translate(rect.x() + rect.width()/2,
                              rect.y() + rect.height()/2)
            painter.scale(scale, scale)
            painter.translate(-self.width()/2, -self.height()/2)
            painter.setRenderHints(qg.QPainter.HighQualityAntialiasing |
                                   qg.QPainter.TextAntialiasing)
            self.render(painter)
            painter.end()

    def double_clicked(self, model_index):
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
        self.connect(self.pile_viewer,
                     qc.SIGNAL('markers_added(int,int)'),
                     self.markers_added)

        self.connect(self.pile_viewer,
                     qc.SIGNAL('markers_removed(int, int)'),
                     self.markers_removed)

        self.connect(self.pile_viewer,
                     qc.SIGNAL('changed_marker_selection'),
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

    def headerData(self, col, orientation, role):
        '''Set and format header data.'''

        if orientation == qc.Qt.Horizontal:
            if role == qc.Qt.DisplayRole:
                return qc.QVariant(_header_data[col])
            elif role == qc.Qt.SizeHintRole:
                return qc.QSize(10, 20)
        else:
            return qc.QVariant()

    def data(self, index, role):
        '''Set data in each of the table's cell.'''

        if not self.pile_viewer:
            return qc.QVariant()

        marker = self.pile_viewer.markers[index.row()]

        if role == qc.Qt.DisplayRole:
            s = ''
            if index.column() == _column_mapping['Time']:
                return qc.QVariant(
                    qc.QDateTime.fromMSecsSinceEpoch(marker.tmin*1000))

            elif index.column() == _column_mapping['T']:
                if isinstance(marker, EventMarker):
                    s = qc.QString('E')
                elif isinstance(marker, PhaseMarker):
                    s = qc.QString('P')

            elif index.column() == _column_mapping['M']:
                if isinstance(marker, EventMarker):
                    e = marker.get_event()
                    if e.moment_tensor is not None:
                        s = round(e.moment_tensor.magnitude, 1)
                    elif e.magnitude is not None:
                        s = round(e.magnitude, 1)

            elif index.column() == _column_mapping['Label']:
                if isinstance(marker, EventMarker):
                    s = qc.QString(marker.label())
                elif isinstance(marker, PhaseMarker):
                    s = qc.QString(marker.get_label())

            elif index.column() == _column_mapping['Depth [km]']:
                if isinstance(marker, EventMarker):
                    d = marker.get_event().depth
                    if d is not None:
                        s = round(marker.get_event().depth/1000., 1)

            elif index.column() == _column_mapping['Lat']:
                if isinstance(marker, EventMarker):
                    s = round(marker.get_event().lat, 2)

            elif index.column() == _column_mapping['Lon']:
                if isinstance(marker, EventMarker):
                    s = round(marker.get_event().lon, 2)

            elif index.column() == _column_mapping['Kind']:
                s = marker.kind

            elif index.column() == _column_mapping['Dist [km]']:
                if marker in self.distances.keys():
                    s = self.distances[marker]

            elif index.column() == _column_mapping['Kagan Angle [deg]']:
                if marker in self.kagan_angles.keys():
                    s = round(self.kagan_angles[marker], 1)

            elif index.column() == _column_mapping['MT']:
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
            for i in xrange(nevents):
                lats[i] = events[i].lat
                lons[i] = events[i].lon

            olats = num.zeros(nevents)
            olons = num.zeros(nevents)
            olats[:] = oevent.lat
            olons[:] = oevent.lon
            dists = orthodrome.distance_accurate50m_numpy(
                lats, lons, olats, olons)
            dists /= 1000.
            dists = map(lambda x: round(x, 1), dists)
            self.distances = dict(zip(emarkers, dists))

        if want_angles:
            if oevent.moment_tensor:
                for em in emarkers:
                    e = em.get_event()
                    if e.moment_tensor:
                        a = moment_tensor.kagan_angle(
                            oevent.moment_tensor, e.moment_tensor)
                        self.kagan_angles[em] = a
            else:
                self.kagan_angles = {}

        istart = self.index(0, 0)
        istop = self.index(nmarkers-1, len(_header_data)-1)

        self.emit(qc.SIGNAL('dataChanged(QModelIndex, QModelIndex)'),
                  istart,
                  istop)

    def done(self):
        self.emit(qc.SIGNAL('dataChanged'))
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
                        valuef, valid = value.toFloat()
                        if valid:
                            e = marker.get_event()
                            if e.moment_tensor is None:
                                e.magnitude = valuef
                            else:
                                e.moment_tensor.magnitude = valuef
                            return self.done()

                if index.column() in [_column_mapping['Lon'],
                                      _column_mapping['Lat'],
                                      _column_mapping['Depth [km]']]:
                    if isinstance(marker, EventMarker):
                        valuef, valid = value.toFloat()
                        if valid:
                            if index.column() == _column_mapping['Lat']:
                                marker.get_event().lat = valuef
                            elif index.column() == _column_mapping['Lon']:
                                marker.get_event().lon = valuef
                            elif index.column() == _column_mapping[
                                    'Depth [km]']:
                                marker.get_event().depth = valuef*1000.
                            return self.done()

            if index.column() == _column_mapping['Label']:
                values = str(value.toString())
                if values != '':
                    if isinstance(marker, EventMarker):
                        marker.get_event().set_name(values)
                        return self.done()

                    if isinstance(marker, PhaseMarker):
                        marker.set_phasename(values)
                        return self.done()

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


class MarkerEditor(qg.QFrame):

    def __init__(self, *args, **kwargs):
        qg.QFrame.__init__(self, *args, **kwargs)
        layout = qg.QGridLayout()
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
            header.setResizeMode(i_s, qg.QHeaderView.Interactive)
            header.resizeSection(i_s, s)

        header.setStretchLastSection(True)

        self.selection_model = qg.QItemSelectionModel(self.proxy_filter)
        self.marker_table_view.setSelectionModel(self.selection_model)
        self.connect(
            self.selection_model,
            qc.SIGNAL('selectionChanged(QItemSelection,QItemSelection)'),
            self.set_selected_markers)

        layout.addWidget(self.marker_table_view, 0, 0)

        self.pile_viewer = None
        self._size_hint = qc.QSize(1, 1)

    def set_viewer(self, viewer):
        '''Set a pile_viewer and connect to signals.'''

        self.pile_viewer = viewer
        self.marker_model.set_viewer(viewer)
        self.marker_table_view.set_viewer(viewer)
        self.connect(
            self.pile_viewer,
            qc.SIGNAL('changed_marker_selection'),
            self.update_selection_model)

        self.connect(
            self.pile_viewer,
            qc.SIGNAL('active_event_marker_changed(int)'),
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
        selections = qg.QItemSelection()
        selection_flags = qg.QItemSelectionModel.SelectionFlags(
            (qg.QItemSelectionModel.Select |
             qg.QItemSelectionModel.Rows |
             qg.QItemSelectionModel.Current))

        for chunk in indices:
            mi_start = self.marker_model.index(min(chunk), 0)
            mi_stop = self.marker_model.index(max(chunk), 0)
            row_selection = self.proxy_filter.mapSelectionFromSource(
                qg.QItemSelection(mi_start, mi_stop))
            selections.merge(row_selection, selection_flags)

        if len(indices) != 0:
            self.marker_table_view.scrollTo(self.proxy_filter.mapFromSource(
                mi_start))
            self.marker_table_view.setCurrentIndex(mi_start)
            self.selection_model.setCurrentIndex(
                mi_start, selection_flags)

        self.selection_model.select(selections, selection_flags)
