from subprocess import check_call, CalledProcessError
import logging


from pyrocko.guts import Object, String, Float, Bytes, clone, \
    dump_all, load_all

from pyrocko.gui.qt_compat import qw, qc, qg, get_em
from .state import ViewerState, Interpolator, interpolateables
from vtk.util.numpy_support import vtk_to_numpy
import vtk
from . import common

guts_prefix = 'sparrow'

logger = logging.getLogger('pyrocko.gui.sparrow.snapshots')

thumb_size = 128, 72


def to_rect(r):
    return [float(x) for x in (r.left(), r.top(), r.width(), r.height())]


def fit_to_rect(frame, size, halign='center', valign='center'):
    fl, ft, fw, fh = to_rect(frame)
    rw, rh = size.width(), size.height()

    ft += 1
    fh -= 1

    fl += 1
    fw -= 1

    fa = fh / fw
    ra = rh / rw

    if fa <= ra:
        rh = fh
        rw = rh / ra
        if halign == 'left':
            rl = fl
        elif halign == 'center':
            rl = fl + 0.5 * (fw - rw)
        elif halign == 'right':
            rl = fl + fw - rw

        rt = ft
    else:
        rw = fw
        rh = rw * ra
        rl = fl
        if valign == 'top':
            rt = ft
        elif valign == 'center':
            rt = ft + 0.5 * (fh - rh)
        elif valign == 'bottom':
            rt = ft + fh - rh

    return qc.QRectF(rl, rt, rw, rh)


def getitem_or_none(items, i):
    try:
        return items[i]
    except IndexError:
        return None


def iround(f):
    return int(round(f))


class SnapshotItemDelegate(qw.QStyledItemDelegate):
    def __init__(self, model, parent):
        qw.QStyledItemDelegate.__init__(self, parent=parent)
        self.model = model

    def sizeHint(self, option, index):
        item = self.model.get_item_or_none(index)
        if isinstance(item, Snapshot):
            return qc.QSize(*thumb_size)
        else:
            return qw.QStyledItemDelegate.sizeHint(self, option, index)

    def paint(self, painter, option, index):
        app = common.get_app()
        item = self.model.get_item_or_none(index)
        em = get_em(painter)
        frect = option.rect.adjusted(0, 0, 0, 0)
        nb = iround(em*0.5)
        trect = option.rect.adjusted(nb, nb, -nb, -nb)

        if isinstance(item, Snapshot):

            old_pen = painter.pen()
            if option.state & qw.QStyle.State_Selected:
                bg_brush = app.palette().brush(
                    qg.QPalette.Active, qg.QPalette.Highlight)

                fg_pen = qg.QPen(app.palette().color(
                    qg.QPalette.Active, qg.QPalette.HighlightedText))

                painter.fillRect(frect, bg_brush)
                painter.setPen(fg_pen)

            else:
                bg_brush = app.palette().brush(
                    qg.QPalette.Active, qg.QPalette.AlternateBase)

                painter.fillRect(frect, bg_brush)

            # painter.drawRect(frect)
            img = item.get_image()
            if img is not None:
                prect = fit_to_rect(frect, img.size(), halign='right')
                painter.drawImage(prect, img)

            painter.drawText(
                trect,
                qc.Qt.AlignLeft | qc.Qt.AlignTop,
                item.name)

            painter.setPen(
                app.palette().brush(
                    qg.QPalette.Disabled
                    if item.duration is None
                    else qg.QPalette.Active,
                    qg.QPalette.Text).color())

            ed = item.effective_duration
            painter.drawText(
                trect,
                qc.Qt.AlignLeft | qc.Qt.AlignBottom,
                '%.2f s' % ed if ed != 0.0 else '')

            painter.setPen(old_pen)

        else:
            qw.QStyledItemDelegate.paint(self, painter, option, index)

            # painter.drawText(
            #     trect,
            #     qc.Qt.AlignRight | qc.Qt.AlignTop,
            #     '%.2f' % item.effective_duration)

    def editorEvent(self, event, model, option, index):

        item = self.model.get_item_or_none(index)

        if isinstance(event, qg.QMouseEvent) \
                and event.button() == qc.Qt.RightButton:

            menu = qw.QMenu()

            for name, duration in [
                    ('Auto', None),
                    ('0 s', 0.0),
                    ('1/2 s', 0.5),
                    ('1 s', 1.0),
                    ('3 s', 3.0),
                    ('5 s', 5.0),
                    ('10 s', 10.0),
                    ('60 s', 60.0)]:

                def make_triggered(duration):
                    def triggered():
                        item.duration = duration

                    return triggered

                action = qw.QAction(name, menu)
                action.triggered.connect(make_triggered(duration))
                menu.addAction(action)

            action = qw.QAction('Custom...', menu)

            def triggered():
                self.parent().edit(index)

            action.triggered.connect(triggered)

            menu.addAction(action)
            menu.exec_(event.globalPos())

            return True

        else:
            return qw.QStyledItemDelegate.editorEvent(
                self, event, model, option, index)

    def createEditor(self, parent, option, index):
        return qw.QLineEdit(parent=parent)

    def setModelData(self, editor, model, index):
        item = self.model.get_item_or_none(index)
        if item:
            try:
                item.duration = max(float(editor.text()), 0.0)
            except ValueError:
                item.duration = None

    def setEditorData(self, editor, index):
        item = self.model.get_item_or_none(index)
        if item:
            editor.setText(
                'Auto' if item.duration is None else '%g' % item.duration)


class SnapshotListView(qw.QListView):

    def startDrag(self, supported):
        if supported & (qc.Qt.CopyAction | qc.Qt.MoveAction):
            drag = qg.QDrag(self)
            selected_indexes = self.selectedIndexes()
            mime_data = self.model().mimeData(selected_indexes)
            drag.setMimeData(mime_data)
            drag.exec(qc.Qt.MoveAction)

    def dropEvent(self, *args):
        mod = self.model()
        selected_items = [
            mod.get_item_or_none(index) for index in self.selectedIndexes()]

        selected_items = [item for item in selected_items if item is not None]

        result = qw.QListView.dropEvent(self, *args)

        indexes = [mod.get_index_for_item(item) for item in selected_items]

        smod = self.selectionModel()
        smod.clear()
        scroll_index = None
        for index in indexes:
            if index is not None:
                smod.select(index, qc.QItemSelectionModel.Select)
                if scroll_index is None:
                    scroll_index = index

        if scroll_index is not None:
            self.scrollTo(scroll_index)

        return result


class SnapshotsPanel(qw.QFrame):

    def __init__(self, viewer):
        qw.QFrame.__init__(self)
        layout = qw.QGridLayout()
        self.setLayout(layout)

        self.model = SnapshotsModel()

        self.viewer = viewer

        lv = SnapshotListView()
        lv.sizePolicy().setVerticalPolicy(qw.QSizePolicy.Expanding)
        lv.setModel(self.model)
        lv.doubleClicked.connect(self.goto_snapshot)
        lv.setSelectionMode(qw.QAbstractItemView.ExtendedSelection)
        lv.setDragDropMode(qw.QAbstractItemView.InternalMove)
        lv.setEditTriggers(qw.QAbstractItemView.NoEditTriggers)
        lv.viewport().setAcceptDrops(True)
        self.item_delegate = SnapshotItemDelegate(self.model, lv)
        lv.setItemDelegate(self.item_delegate)
        self.list_view = lv
        layout.addWidget(lv, 0, 0, 1, 3)

        pb = qw.QPushButton('New')
        pb.clicked.connect(self.take_snapshot)
        layout.addWidget(pb, 1, 0, 1, 1)

        pb = qw.QPushButton('Replace')
        pb.clicked.connect(self.replace_snapshot)
        layout.addWidget(pb, 1, 1, 1, 1)

        pb = qw.QPushButton('Delete')
        pb.clicked.connect(self.delete_snapshots)
        layout.addWidget(pb, 1, 2, 1, 1)

        pb = qw.QPushButton('Import')
        pb.clicked.connect(self.import_snapshots)
        layout.addWidget(pb, 2, 0, 1, 1)

        pb = qw.QPushButton('Export')
        pb.clicked.connect(self.export_snapshots)
        layout.addWidget(pb, 2, 1, 1, 1)

        pb = qw.QPushButton('Animate')
        pb.clicked.connect(self.animate_snapshots)
        layout.addWidget(pb, 2, 2, 1, 1)

        pb = qw.QPushButton('Movie')
        pb.clicked.connect(self.render_movie)
        layout.addWidget(pb, 3, 1, 1, 1)

        self.window_to_image_filter = None

    def get_snapshot_image(self):
        if not self.window_to_image_filter:
            wif = vtk.vtkWindowToImageFilter()
            wif.SetInput(self.viewer.renwin)
            wif.SetInputBufferTypeToRGBA()
            wif.ReadFrontBufferOff()
            self.window_to_image_filter = wif

            writer = vtk.vtkPNGWriter()
            writer.SetInputConnection(wif.GetOutputPort())
            writer.SetWriteToMemory(True)
            self.png_writer = writer

        self.viewer.renwin.Render()
        self.window_to_image_filter.Modified()
        self.png_writer.Write()
        data = vtk_to_numpy(self.png_writer.GetResult()).tobytes()
        img = qg.QImage()
        img.loadFromData(data)
        return img

    def get_snapshot_thumbnail(self):
        return self.get_snapshot_image().scaled(
            thumb_size[0], thumb_size[1],
            qc.Qt.KeepAspectRatio, qc.Qt.SmoothTransformation)

    def get_snapshot_thumbnail_png(self):
        img = self.get_snapshot_thumbnail()

        ba = qc.QByteArray()
        buf = qc.QBuffer(ba)
        buf.open(qc.QIODevice.WriteOnly)
        img.save(buf, format='PNG')
        return ba.data()

    def take_snapshot(self):
        self.model.add_snapshot(
            Snapshot(
                state=clone(self.viewer.state),
                thumb=self.get_snapshot_thumbnail_png()))

    def replace_snapshot(self):
        state = clone(self.viewer.state)
        selected_indexes = self.list_view.selectedIndexes()

        if len(selected_indexes) == 1:
            self.model.replace_snapshot(
                selected_indexes[0],
                Snapshot(
                    state,
                    thumb=self.get_snapshot_thumbnail_png()))

        self.list_view.update()

    def goto_snapshot(self, index):
        item = self.model.get_item_or_none(index)
        if isinstance(item, Snapshot):
            self.viewer.set_state(item.state)
        elif isinstance(item, Transition):
            snap1 = self.model.get_item_or_none(index.row()-1)
            snap2 = self.model.get_item_or_none(index.row()+1)
            if isinstance(snap1, Snapshot) and isinstance(snap2, Snapshot):
                ip = Interpolator(
                    [0.0, item.effective_duration],
                    [snap1.state, snap2.state])

                self.viewer.start_animation(ip)

    def delete_snapshots(self):
        selected_indexes = self.list_view.selectedIndexes()
        self.model.remove_snapshots(selected_indexes)

    def animate_snapshots(self, **kwargs):
        selected_indexes = self.list_view.selectedIndexes()
        items = self.model.get_series(selected_indexes)

        time_state = []
        item_previous = None
        t = 0.0
        for i, item in enumerate(items):
            item_next = getitem_or_none(items, i+1)
            item_previous = getitem_or_none(items, i-1)

            if isinstance(item, Snapshot):
                time_state.append((t, item.state))
                if item.effective_duration > 0:
                    time_state.append((t+item.effective_duration, item.state))

                t += item.effective_duration

            elif isinstance(item, Transition):
                if None not in (item_previous, item_next) \
                        and item.effective_duration != 0.0:

                    t += item.effective_duration

            item_previous = item

        if len(time_state) < 2:
            return

        ip = Interpolator(*zip(*time_state))

        self.viewer.start_animation(
            ip, output_path=kwargs.get('output_path', None))

    def render_movie(self):
        try:
            check_call(['ffmpeg', '-loglevel', 'panic'])
        except CalledProcessError:
            pass
        except (TypeError, FileNotFoundError):
            logger.warn(
                'Package ffmpeg needed for movie rendering. Please install it '
                '(e.g. on linux distr. via sudo apt-get ffmpeg.) and retry.')
            return

        caption = 'Export Movie'
        fn_out, _ = qw.QFileDialog.getSaveFileName(
            self, caption, 'movie.mp4',
            options=common.qfiledialog_options)

        if fn_out:
            self.animate_snapshots(output_path=fn_out)

    def export_snapshots(self):
        caption = 'Export Snapshots'
        fn, _ = qw.QFileDialog.getSaveFileName(
            self, caption, options=common.qfiledialog_options)

        selected_indexes = self.list_view.selectedIndexes()
        items = self.model.get_series(selected_indexes)

        if fn:
            dump_all(items, filename=fn)

    def add_snapshots(self, snapshots):
        self.model.append_series(snapshots)

    def load_snapshots(self, path):
        items = load_snapshots(path)
        self.add_snapshots(items)

    def import_snapshots(self):
        caption = 'Import Snapshots'
        path, _ = qw.QFileDialog.getOpenFileName(
            self, caption, options=common.qfiledialog_options)

        if path:
            self.load_snapshots(path)


class Item(Object):
    duration = Float.T(optional=True)

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self.auto_duration = 0.0

    @property
    def effective_duration(self):
        if self.duration is not None:
            return self.duration
        else:
            return self.auto_duration


class Snapshot(Item):
    name = String.T()
    state = ViewerState.T()
    thumb = Bytes.T(optional=True)

    isnapshot = 0

    def __init__(self, state, name=None, thumb=None, **kwargs):

        if name is None:
            Snapshot.isnapshot += 1
            name = '%i' % Snapshot.isnapshot

        Item.__init__(self, state=state, name=name, thumb=thumb, **kwargs)
        self._img = None

    def get_name(self):
        return self.name

    def get_image(self):
        if self.thumb is not None and not self._img:
            img = qg.QImage()
            img.loadFromData(self.thumb)
            self._img = img

        return self._img


class Transition(Item):

    def __init__(self, **kwargs):
        Item.__init__(self, **kwargs)
        self.animate = []

    def get_name(self):
        ed = self.effective_duration
        return '%s %s' % (
            'T' if self.animate and self.effective_duration > 0.0 else '',
            '%.2f s' % ed if ed != 0.0 else '')

    @property
    def name(self):
        return self.get_name()


class SnapshotsModel(qc.QAbstractListModel):

    def __init__(self):
        qc.QAbstractListModel.__init__(self)
        self._items = []

    def supportedDropActions(self):
        return qc.Qt.MoveAction

    def rowCount(self, parent=None):
        return len(self._items)

    def insertRows(self, index):
        pass

    def mimeTypes(self):
        return ['text/plain']

    def mimeData(self, indices):
        objects = [self._items[i.row()] for i in indices]
        serialized = dump_all(objects)
        md = qc.QMimeData()
        md.setText(serialized)
        md._item_objects = objects
        return md

    def dropMimeData(self, md, action, row, col, index):
        i = index.row()
        items = getattr(md, '_item_objects', [])
        self.beginInsertRows(qc.QModelIndex(), i, i)
        self._items[i:i] = items
        self.endInsertRows()
        n = len(items)
        joff = 0
        for j in range(len(self._items)):
            if (j < i or j >= i+n) and self._items[j+joff] in items:
                self.beginRemoveRows(qc.QModelIndex(), j+joff, j+joff)
                self._items[j+joff:j+joff+1] = []
                self.endRemoveRows()
                joff -= 1

        self.repair_transitions()
        return True

    def removeRows(self, i, n, parent):
        return True

    def flags(self, index):
        if index.isValid():
            i = index.row()
            if isinstance(self._items[i], Snapshot):
                return qc.Qt.ItemFlags(
                    qc.Qt.ItemIsSelectable
                    | qc.Qt.ItemIsEnabled
                    | qc.Qt.ItemIsDragEnabled
                    | qc.Qt.ItemIsEditable)

            else:
                return qc.Qt.ItemFlags(
                    qc.Qt.ItemIsEnabled
                    | qc.Qt.ItemIsEnabled
                    | qc.Qt.ItemIsDropEnabled
                    | qc.Qt.ItemIsEditable)
        else:
            return qc.QAbstractListModel.flags(self, index)

    def data(self, index, role):
        app = common.get_app()
        i = index.row()
        item = self._items[i]
        is_snap = isinstance(item, Snapshot)
        if role == qc.Qt.DisplayRole:
            if is_snap:
                return qc.QVariant(str(item.get_name()))
            else:
                return qc.QVariant(str(item.get_name()))

        elif role == qc.Qt.ToolTipRole:
            if is_snap:
                # return qc.QVariant(str(item.state))
                return qc.QVariant()
            else:
                if item.animate:
                    label = 'Interpolation: %s' % \
                        ', '.join(x[0] for x in item.animate)
                else:
                    label = 'Not interpolable.'

                return qc.QVariant(label)

        elif role == qc.Qt.TextAlignmentRole and not is_snap:
            return qc.QVariant(qc.Qt.AlignRight)

        elif role == qc.Qt.ForegroundRole and not is_snap:
            if item.duration is None:
                return qc.QVariant(app.palette().brush(
                    qg.QPalette.Disabled, qg.QPalette.Text))
            else:
                return qc.QVariant(app.palette().brush(
                    qg.QPalette.Active, qg.QPalette.Text))

        else:
            qc.QVariant()

    def headerData(self):
        pass

    def add_snapshot(self, snapshot):
        self.beginInsertRows(
            qc.QModelIndex(), self.rowCount(), self.rowCount())
        self._items.append(snapshot)
        self.endInsertRows()
        self.repair_transitions()

    def replace_snapshot(self, index, snapshot):
        self._items[index.row()] = snapshot
        self.dataChanged.emit(index, index)
        self.repair_transitions()

    def remove_snapshots(self, indexes):
        indexes = sorted(indexes, key=lambda index: index.row())
        ioff = 0
        for index in indexes:
            i = index.row()
            self.beginRemoveRows(qc.QModelIndex(), i+ioff, i+ioff)
            self._items[i+ioff:i+ioff+1] = []
            self.endRemoveRows()
            ioff -= 1

        self.repair_transitions()

    def repair_transitions(self):
        items = self._items
        i = 0
        need = 0
        while i < len(items):
            if need == 0:
                if not isinstance(items[i], Transition):
                    self.beginInsertRows(qc.QModelIndex(), i, i)
                    items[i:i] = [Transition()]
                    self.endInsertRows()
                else:
                    i += 1
                    need = 1
            elif need == 1:
                if not isinstance(items[i], Snapshot):
                    self.beginRemoveRows(qc.QModelIndex(), i, i)
                    items[i:i+1] = []
                    self.endRemoveRows()
                else:
                    i += 1
                    need = 0

        if len(items) == 1:
            self.beginRemoveRows(qc.QModelIndex(), 0, 0)
            items[:] = []
            self.endRemoveRows()

        elif len(items) > 1:
            if not isinstance(items[-1], Transition):
                self.beginInsertRows(
                    qc.QModelIndex(), self.rowCount(), self.rowCount())
                items.append(Transition())
                self.endInsertRows()

        self.update_auto_durations()

    def update_auto_durations(self):
        items = self._items
        for i, item in enumerate(items):
            if isinstance(item, Transition):
                if 0 < i < len(items)-1:
                    item.animate = interpolateables(
                        items[i-1].state, items[i+1].state)

                    if item.animate:
                        item.auto_duration = 3.
                    else:
                        item.auto_duration = 0.

        for i, item in enumerate(items):
            if isinstance(item, Snapshot):
                if 0 < i < len(items)-1:
                    if items[i-1].effective_duration == 0 \
                            and items[i+1].effective_duration == 0:
                        item.auto_duration = 3.
                    else:
                        item.auto_duration = 0.

    def get_index_for_item(self, item):
        for i, candidate in enumerate(self._items):
            if candidate is item:
                return self.createIndex(i, 0)

        return None

    def get_item_or_none(self, index):
        if not isinstance(index, int):
            i = index.row()
        else:
            i = index

        try:
            return self._items[i]
        except IndexError:
            return None

    def get_series(self, indexes):
        items = self._items

        ilist = sorted([index.row() for index in indexes])
        if len(ilist) <= 1:
            ilist = list(range(0, len(self._items)))

        ilist = [i for i in ilist if isinstance(items[i], Snapshot)]
        if len(ilist) == 0:
            return []

        i = ilist[0]

        series = []
        while ilist:
            i = ilist.pop(0)
            series.append(items[i])
            if ilist and ilist[0] == i+2:
                series.append(items[i+1])

        return series

    def append_series(self, items):
        self.beginInsertRows(
            qc.QModelIndex(),
            self.rowCount(), self.rowCount() + len(items) - 1)

        self._items.extend(items)
        self.endInsertRows()

        self.repair_transitions()


def load_snapshots(path):
    items = load_all(filename=path)
    for i in range(len(items)):
        if not isinstance(
                items[i], (ViewerState, Snapshot, Transition)):

            logger.warn(
                'Only Snapshot, Transition and ViewerState objects '
                'are accepted. Object #%i from file %s ignored.'
                % (i, path))

        if isinstance(items[i], ViewerState):
            items[i] = Snapshot(items[i])

    for item in items:
        if isinstance(item, Snapshot):
            item.state.sort_elements()

    return items
