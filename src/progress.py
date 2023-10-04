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

from .get_terminal_size import get_terminal_size

logger = logging.getLogger('pyrocko.progress')

# TODO: Refactor so that if multiple viewers are attached, they can do
# their updates independently of each other (at independent time intervals).

# TODO: Refactor so that different viewers can render task states differently.

# spinner = u'\u25dc\u25dd\u25de\u25df'
# spinner = '⣾⣽⣻⢿⡿⣟⣯⣷'
spinner = '◴◷◶◵'
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


g_force_viewer_off = False

g_viewer = 'terminal'


def set_default_viewer(viewer):
    global g_viewer
    g_viewer = viewer


class StatusViewer(object):

    def __init__(self, parent=None):
        self._parent = parent

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.stop()

    def stop(self):
        if self._parent:
            self._parent.hide(self)

    def draw(self, lines):
        pass


class TerminalStatusViewer(StatusViewer):
    def __init__(self, parent=None):
        self._terminal_size = get_terminal_size()
        self._height = 0
        self._state = 0
        self._parent = parent

    def print(self, s):
        print(s, end='', file=sys.stderr)

    def flush(self):
        print('', end='', flush=True, file=sys.stderr)

    def start(self):
        sx, sy = self._terminal_size
        self._state = 1

    def stop(self):
        if self._state == 1:
            sx, sy = self._terminal_size
            self._resize(0)
            self.print(ansi_move_to % (sy-self._height, 1))
            self.flush()

        self._state = 2
        if self._parent:
            self._parent.hide(self)

    def _start_show(self):
        sx, sy = self._terminal_size
        self.print(ansi_move_to % (sy-self._height+1, 1))

    def _end_show(self):
        sx, sy = self._terminal_size
        self.print(ansi_move_to % (sy-self._height, 1))
        self.print(ansi_clear_right)

    def _resize(self, height):
        sx, sy = self._terminal_size
        k = height - self._height
        if k > 0:
            self.print(ansi_scroll_up * k)
            self.print(ansi_window % (1, sy-height))
        if k < 0:
            self.print(ansi_window % (1, sy-height))
            self.print(ansi_scroll_down * abs(k))

        self._height = height

    def draw(self, lines):
        if self._state == 0:
            self.start()

        if self._state != 1:
            return

        self._terminal_size = get_terminal_size()
        sx, sy = self._terminal_size
        nlines = len(lines)
        self._resize(nlines)
        self._start_show()

        for iline, line in enumerate(reversed(lines)):
            if len(line) > sx - 1:
                line = line[:sx-1]

            self.print(ansi_clear_right + line)
            if iline != nlines - 1:
                self.print(ansi_next_line)

        self._end_show()
        self.flush()


class LogStatusViewer(StatusViewer):

    def draw(self, lines):
        if lines:
            logger.info(
                'Progress:\n%s' % '\n'.join('  '+line for line in lines))


class DummyStatusViewer(StatusViewer):
    pass


class Task(object):
    def __init__(
            self, progress, id, name, n, state='working', logger=None,
            group=None):

        self._id = id
        self._name = name
        self._condition = ''
        self._ispin = 0
        self._i = None
        self._n = n
        self._done = False
        assert state in ('waiting', 'working')
        self._state = state
        self._progress = progress
        self._logger = logger
        self._tcreate = time.time()
        self._group = group

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

    def log(self, s):
        if self._logger is not None:
            self._logger.info(s)

    def get_group_time_start(self):
        if self._group:
            return self._group.get_group_time_start()
        else:
            return self._tcreate

    def task(self, *args, **kwargs):
        kwargs['group'] = self
        return self._progress.task(*args, **kwargs)

    def update(self, i=None, condition=''):
        self._state = 'working'

        self._condition = condition

        if i is not None:
            if self._n is not None:
                i = min(i, self._n)

            self._i = i

        self._progress._update()

    def done(self, condition=''):
        self.duration = time.time() - self._tcreate

        if self._state in ('done', 'failed'):
            return

        self._condition = condition
        self._state = 'done'
        self._progress._end(self)
        self.log(str(self))

    def fail(self, condition=''):
        self.duration = time.time() - self._tcreate

        if self._state in ('done', 'failed'):
            return

        self._condition = condition
        self._state = 'failed'
        self._progress._end(self)
        self.log(str(self))

    def _str_state(self):
        s = self._state
        if s == 'waiting':
            return '  '
        elif s == 'working':
            self._ispin += 1
            return spinner[self._ispin % len(spinner)] + ' '
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

    def __str__(self):
        return '%s%-23s %-11s %s%-4s  %s' % (
            self._str_state(),
            self._name,
            self._str_progress(),
            self._str_bar(),
            self._str_percent(),
            self._str_condition())


class Progress(object):

    def __init__(self):
        self._current_id = 0
        self._current_group_id = 0
        self._tasks = {}
        self._tasks_done = []
        self._last_update = 0.0
        self._terms = []

    def view(self, viewer=None):
        if g_force_viewer_off or self._terms:
            viewer = 'off'
        elif viewer is None:
            viewer = g_viewer

        try:
            term = g_viewer_classes[viewer](self)
        except KeyError:
            raise ValueError('Invalid viewer choice: %s' % viewer)

        self._terms.append(term)
        return term

    def hide(self, term):
        self._update(force=True)
        self._terms.remove(term)

    def task(self, name, n=None, logger=None, group=None):
        self._current_id += 1
        task = Task(
            self, self._current_id, name, n, logger=logger, group=group)
        self._tasks[task._id] = task
        self._update(force=True)
        return task

    def _end(self, task):
        del self._tasks[task._id]
        self._tasks_done.append(task)
        self._update(force=True)

    def _update(self, force=False):
        now = time.time()
        if self._last_update + 0.1 < now or force:
            self._tasks_done = []

            lines = self._lines()
            for term in self._terms:
                term.draw(lines)

            self._last_update = now

    def _lines(self):
        task_ids = sorted(self._tasks)
        lines = []
        for task_id in task_ids:
            task = self._tasks[task_id]
            lines.extend(str(task).splitlines())

        return lines


g_viewer_classes = {
    'terminal': TerminalStatusViewer,
    'log': LogStatusViewer,
    'off': DummyStatusViewer}

progress = Progress()
