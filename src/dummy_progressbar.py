# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Progressbar replacement class which just outputs progress to log.
'''

import time
import logging


logger = logging.getLogger('pyrocko.progress')


class ProgressBar(object):
    def __init__(self, widgets=['progress'], maxval=1, *args, **kwargs):
        self._widgets = widgets
        self._maxval = maxval
        self._val = 0
        self._time = time.time()

    def label(self):
        for widget in self._widgets:
            if isinstance(widget, str):
                return widget

    def start(self):
        logger.info('%s...' % self.label())
        return self

    def update(self, val):
        self._val = val
        t = time.time()
        if t - self._time > 5.0:
            logger.info('%s:  %i/%i %3.0f%%' % (
                self.label(),
                self._val,
                self._maxval,
                100.*float(self._val) / float(self._maxval)))

            self._time = t

    def finish(self):
        logger.info('%s: done.' % self.label())


class Bar(object):
    def __init__(self, *args, **kwargs):
        pass


class Percentage(object):
    def __init__(self, *args, **kwargs):
        pass


class ETA(object):
    def __init__(self, *args, **kwargs):
        pass
