# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Inform users about the progress and success/fail state of long-running tasks.
'''

import sys
import time
import logging
import threading

from shutil import get_terminal_size

logger = logging.getLogger('pyrocko.progress')

g_spinners = [
    '⣾⣽⣻⢿⡿⣟⣯⣷',
    '◴◷◶◵',
    '\u25dc\u25dd\u25de\u25df',
    '0123456789']


skull = u'\u2620'
check = u'\u2714'
cross = u'\u2716'
bar = u'[- ]'
blocks = u'\u2588\u2589\u258a\u258b\u258c\u258d\u258e\u258f '

symbol_done = check
symbol_failed = cross  # skull

ansi_up = u'\033[%iA'
ansi_down = u'\033[%iB'
ansi_left = u'\033[%iC'
ansi_right = u'\033[%iD'
ansi_next_line = u'\033E'
ansi_previous_line = u'\033[1F'

ansi_erase_display = u'\033[2J'
ansi_window = u'\033[%i;%ir'
ansi_move_to = u'\033[%i;%iH'

ansi_clear_down = u'\033[0J'
ansi_clear_up = u'\033[1J'
ansi_clear = u'\033[2J'

ansi_clear_right = u'\033[0K'

ansi_scroll_up = u'\033D'
ansi_scroll_down = u'\033M'

ansi_reset = u'\033c'

ansi_save = u'\033 7'
ansi_restore = u'\033 8'


g_force_viewer_off = False

g_viewer = 'terminal'


def set_default_viewer(viewer):
    '''
    Set default viewer for progress indicators.

    :param viewer:
        Name of viewer, choices: ``'terminal'``, ``'gui'``, ``'log'``,
        ``'off'``, default: ``'terminal'``.
    :type viewer:
        str
    '''

    global g_viewer
    assert viewer in g_viewer_classes
    g_viewer = viewer


class StatusViewer(object):

    def __init__(self, parent, interval=0.1, delay=1.0):
        self._parent = parent
        self._interval = interval
        self._delay = delay
        self._last_update = 0.0
        self._created = time.time()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self._cleanup()

        if self._parent:
            self._parent._remove_viewer(self)

    def _cleanup(self):
        pass

    def update(self, force):
        now = time.time()
        if now < self._created + self._delay:
            return

        if self._last_update + self._interval < now or force:
            self._draw()
            self._last_update = now

    def _idle(self):
        pass

    def _draw(self):
        pass


class DummyStatusViewer(StatusViewer):
    pass


class LogStatusViewer(StatusViewer):

    def __init__(self, parent):
        StatusViewer.__init__(self, parent, delay=5., interval=5.)

    def _draw(self):
        lines = self._parent._render('log')
        if lines:
            logger.info(
                'Progress:\n%s' % '\n'.join('  '+line for line in lines))


class TerminalStatusViewer(StatusViewer):
    def __init__(self, parent):
        StatusViewer.__init__(self, parent)
        self._terminal_size = get_terminal_size()
        self._height = 0
        self._state = 0
        self._nlines_max = 0
        self._isatty = sys.stdout.isatty()

    def _cleanup(self):
        if self._state == 1:
            sx, sy = self._terminal_size
            self._reset()
            self._flush()

        self._state = 2

    def _draw(self):
        lines = self._parent._render('terminal')
        if self._state == 0:
            self._state = 1

        if self._state != 1:
            return

        self._terminal_size = get_terminal_size()
        sx, sy = self._terminal_size
        nlines = len(lines)
        if self._nlines_max < nlines:
            self._nlines_max = nlines
            self._resize(self._nlines_max)

        self._start_show()

        for i in range(self._nlines_max - nlines):
            lines.append('')

        for iline, line in enumerate(reversed(lines)):
            if len(line) > sx - 1:
                line = line[:sx-1]

            self._print(ansi_clear_right + line)
            if iline != self._nlines_max - 1:
                self._print(ansi_next_line)

        self._end_show()
        self._flush()

    def _print(self, s):
        if self._isatty:
            print(s, end='', file=sys.stderr)

    def _flush(self):
        if self._isatty:
            print('', end='', flush=True, file=sys.stderr)

    def _reset(self):
        sx, sy = self._terminal_size
        self._print(ansi_window % (1, sy))
        self._print(ansi_move_to % (sy-self._height, 1))
        self._print(ansi_clear_down)
        self._height = 0

    def _resize(self, height):
        sx, sy = self._terminal_size
        k = height - self._height
        if k > 0:
            self._print(ansi_scroll_up * k)
            self._print(ansi_window % (1, sy-height))
        if k < 0:
            self._print(ansi_window % (1, sy-height))
            self._print(ansi_scroll_down * abs(k))

        self._height = height

    def _start_show(self):
        sx, sy = self._terminal_size
        self._print(ansi_move_to % (sy-self._height+1, 1))

    def _end_show(self):
        sx, sy = self._terminal_size
        self._print(ansi_move_to % (sy-self._height, 1))
        self._print(ansi_clear_right)


def make_TaskView():
    from pyrocko.gui.qt_compat import qw, qg

    class TaskView(qw.QFrame):
        def __init__(self, task):
            qw.QFrame.__init__(self)
            layout = qw.QGridLayout()
            self._task = task
            label = qw.QLabel(task._render('terminal'))
            label.setFont(qg.QFont('monospace'))
            layout.addWidget(label, 0, 0)
            self._label = label
            self.setLayout(layout)

        def update_progress(self):
            self._label.setText(self._task._render('terminal'))

    return TaskView


TaskView = None


def get_TaskView():
    global TaskView
    if TaskView is None:
        TaskView = make_TaskView()

    return TaskView


def make_GUIStatusViewer():
    from pyrocko.gui.qt_compat import qc, qw
    from pyrocko.gui import util as gui_util

    class DontShrinkFrame(qw.QFrame):

        def __init__(self):
            qw.QFrame.__init__(self)
            self._size = None

        def sizeHint(self):
            size = qw.QFrame.sizeHint(self)
            if self._size is not None:
                size = qc.QSize(
                    size.width(),
                    max(self._size.height(), size.height()))

            self._size = size
            return size

    class GUIStatusViewer(StatusViewer):

        def __init__(self, parent):
            StatusViewer.__init__(self, parent)

            frame = DontShrinkFrame()
            frame.setWindowTitle('Progress')
            layout_outer = qw.QVBoxLayout()
            frame.setLayout(layout_outer)

            dummy = qw.QFrame()
            dummy.setSizePolicy(qw.QSizePolicy(
                qw.QSizePolicy.Expanding,
                qw.QSizePolicy.Expanding))
            layout_outer.addWidget(dummy)

            layout = qw.QVBoxLayout()

            layout_outer.insertLayout(-1, layout)

            layout.setDirection(qw.QBoxLayout.BottomToTop)

            self._frame = frame
            self._layout = layout
            self._task_views = {}
            self._timers = []
            self._last_size = None

        def _cleanup(self):
            pass

        def _draw(self):

            if not threading.current_thread().name == 'MainThread':
                return

            tasks = self._parent._tasks
            task_views = self._task_views

            add = [
                task_id for task_id in tasks if task_id not in task_views]

            for task_id in add:
                self._add_task_view(task_id)

            remove = [
                task_id for task_id in task_views if task_id not in tasks]

            for task_id in remove:
                self._remove_task_view(task_id)

            if task_views and not self._frame.isVisible():
                self._frame.show()

            if not task_views and self._layout.count() == 0 \
                    and self._frame.isVisible():
                self._frame.hide()

            for task_view in task_views.values():
                task_view.update_progress()

            app = gui_util.get_app()
            app.processEvents()

        def _add_task_view(self, task_id):
            view = get_TaskView()(self._parent._tasks[task_id])
            self._task_views[task_id] = view
            self._layout.addWidget(view)

        def _remove_task_view(self, task_id):
            view = self._task_views.pop(task_id)

            timer = qc.QTimer()
            self._timers.append(timer)

            def do_remove():
                view.hide()
                self._layout.removeWidget(view)
                self._timers.remove(timer)

            if False:
                timer.setSingleShot(True)
                timer.setInterval(500)
                timer.timeout.connect(do_remove)
                timer.start()
            else:
                do_remove()

        def _idle(self):
            self._draw()

    return GUIStatusViewer


GUIStatusViewer = None


def get_GUIStatusViewer():
    global GUIStatusViewer
    if GUIStatusViewer is None:
        GUIStatusViewer = make_GUIStatusViewer()

    return GUIStatusViewer


def get_gui_status_viewer(parent):
    from pyrocko import gui_util
    app = gui_util.get_app()
    win = app.get_main_window()
    if win and hasattr(win, 'get_status_viewer'):
        viewer = win.get_status_viewer(parent)
        if viewer:
            return viewer

    return get_GUIStatusViewer()(parent)


class Task(object):
    def __init__(
            self, progress, id, name, n, state='working', logger=None,
            group=None, spinner=g_spinners[0]):

        self._id = id
        self._name = name
        self._condition = ''
        self._ispin0 = 0
        self._ispin0_last = 0
        self._ispin = 0
        self._spinner = spinner
        self._i = None
        self._n = n
        self._done = False
        assert state in ('waiting', 'working')
        self._state = state
        self._progress = progress
        self._logger = logger
        self._tcreate = time.time()
        self._group = group
        self._lock = threading.RLock()
        self._views = {}
        self.update(0)

    def __enter__(self):
        return self

    def __exit__(self, type, value, tb):
        if type is None:
            self.done()
        else:
            self.fail()

    def __call__(self, it):
        try:
            self._n = len(it)
        except TypeError:
            self._n = None

        clean = False
        try:
            n = 0
            for obj in it:
                self.update(n)
                yield obj
                n += 1

            self.update(n)
            clean = True

        finally:
            if clean:
                self.done()
            else:
                self.fail()

    def task(self, *args, **kwargs):
        kwargs['group'] = self
        return self._progress.task(*args, **kwargs)

    def update(self, i=None, condition=''):
        with self._lock:
            self._ispin0 += 1
            self._state = 'working'
            self._condition = condition
            if i is not None:
                if self._n is not None:
                    i = min(i, self._n)

                self._i = i

            self._progress._update(False)

    def done(self, condition=''):
        with self._lock:
            self.duration = time.time() - self._tcreate

            if self._state in ('done', 'failed'):
                return

            self._condition = condition
            self._state = 'done'
            self._log(str(self))
            self._progress._task_end(self)

    def fail(self, condition=''):
        with self._lock:
            self.duration = time.time() - self._tcreate

            if self._state in ('done', 'failed'):
                return

            self._condition = condition
            self._state = 'failed'
            self._log(str(self))
            self._progress._task_end(self)

    def _log(self, s):
        if self._logger is not None:
            self._logger.debug(s)

    def _get_group_time_start(self):
        if self._group:
            return self._group._get_group_time_start()
        else:
            return self._tcreate

    def _str_state(self):
        s = self._state
        if s == 'waiting':
            return '  '
        elif s == 'working':
            if self._ispin0_last != self._ispin0:
                self._ispin += 1
                self._ispin0_last = self._ispin0

            return self._spinner[self._ispin % len(self._spinner)] + ' '
        elif s == 'done':
            return symbol_done + ' '
        elif s == 'failed':
            return symbol_failed + ' '
        else:
            return '? '

    def _idisplay(self):
        i = self._i
        if self._n is not None and i > self._n:
            i = self._n
        return i

    def _str_progress(self):
        if self._i is None:
            return self._state
        elif self._n is None:
            if self._state != 'working':
                return '... %s (%i)' % (self._state, self._idisplay())
            else:
                return '%i' % self._idisplay()
        else:
            if self._state == 'working':
                nw = len(str(self._n))
                return (('%' + str(nw) + 'i / %i') % (
                    self._idisplay(), self._n)).center(11)

            elif self._state == 'failed':
                return '... %s (%i / %i)' % (
                    self._state, self._idisplay(), self._n)
            else:
                return '... %s (%i)' % (self._state, self._n)

    def _str_percent(self):
        if self._state == 'working' and self._n is not None and self._n >= 4 \
                and self._i is not None:
            return '%3.0f%%' % ((100. * self._i) / self._n)
        else:
            return ''

    def _str_condition(self):
        if self._condition:
            return '%s' % self._condition
        else:
            return ''

    def _str_bar(self):
        if self._state == 'working' and self._n is not None and self._n >= 4 \
                and self._i is not None:
            nb = 20
            fb = nb * float(self._i) / self._n
            ib = int(fb)
            ip = int((fb - ib) * (len(blocks)-1))
            if ib == 0 and ip == 0:
                ip = 1  # indication of start
            s = blocks[0] * ib
            if ib < nb:
                s += blocks[-1-ip] + (nb - ib - 1) * blocks[-1] + blocks[-2]

            # s = ' ' + bar[0] + bar[1] * ib + bar[2] * (nb - ib) + bar[3]
            return s
        else:
            return ''

    def _render(self, style):
        if style == 'terminal':
            return '%s%-40s %-11s %s%-4s  %s' % (
                self._str_state(),
                self._name,
                self._str_progress(),
                self._str_bar(),
                self._str_percent(),
                self._str_condition())

        elif style == 'log':
            return '%s: %-40s %s%-4s  %s' % (
                self._state,
                self._name,
                self._str_progress(),
                self._str_percent(),
                self._str_condition())
        else:
            return ''

    def __str__(self):
        return '%s%-40s %s%-4s  %s' % (
            self._str_state(),
            self._name,
            self._str_progress(),
            self._str_percent(),
            self._str_condition())


class Progress(object):

    def __init__(self):
        self._current_id = 0
        self._tasks = {}
        self._viewers = []
        self._lock = threading.RLock()
        self._isatty = sys.stdout.isatty()

    def view(self, viewer=None):
        if g_force_viewer_off or self._viewers:
            viewer = 'off'
        elif viewer is None:
            viewer = g_viewer

        if not self._isatty and viewer == 'terminal':
            logger.debug('No tty attached, switching to log progress viewer.')
            viewer = 'log'

        try:
            viewer = g_viewer_classes[viewer](self)
        except KeyError:
            raise ValueError('Invalid viewer choice: %s' % viewer)

        self._viewers.append(viewer)
        return viewer

    def task(self, name, n=None, logger=None, group=None):
        with self._lock:
            self._current_id += 1
            task = Task(
                self, self._current_id, name, n, logger=logger, group=group)
            self._tasks[task._id] = task
            self._update(True)
            return task

    def idle(self):
        for viewer in self._viewers:
            viewer._idle()

    def _remove_viewer(self, viewer):
        self._update(True)
        self._viewers.remove(viewer)

    def _task_end(self, task):
        with self._lock:
            self._update(True)
            del self._tasks[task._id]
            self._update(True)

    def _update(self, force):
        with self._lock:
            for viewer in self._viewers:
                viewer.update(force)

    def _render(self, style):
        task_ids = sorted(self._tasks)
        lines = []
        for task_id in task_ids:
            task = self._tasks[task_id]
            lines.extend(task._render(style).splitlines())

        return lines

    def _debug_log(self):
        logger.debug(
            'Viewers: %s\n  Tasks active: %i\n  Tasks total: %i',
            ', '.join(viewer.__class__.__name__ for viewer in self._viewers)
            if self._viewers else 'none',
            len(self._tasks),
            self._current_id)


g_viewer_classes = {
    'terminal': TerminalStatusViewer,
    'gui': get_gui_status_viewer,
    'log': LogStatusViewer,
    'off': DummyStatusViewer}

g_progress = Progress()
progress = g_progress  # compatibility
view = g_progress.view
task = g_progress.task
idle = g_progress.idle
