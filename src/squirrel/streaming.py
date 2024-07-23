# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Real-time streaming support.
'''

import logging
import math
import time

import numpy as num

from pyrocko import trace, util, io


logger = logging.getLogger('psq.streaming')


class Injector(trace.States):

    def __init__(
            self, squirrel,
            fixation_length=None,
            path=None,
            format='from_extension',
            forget_fixed=False):

        trace.States.__init__(self)
        self._squirrel = squirrel
        self._fixation_length = fixation_length
        self._format = format
        self._path = path
        self._forget_fixed = forget_fixed
        util.experimental_feature_used('pyrocko.squirrel.streaming')

    def set_fixation_length(self, length):
        '''
        Set length after which the fixation method is called on buffer traces.

        The length should be given in seconds. Give None to disable.
        '''
        self.clear_all()
        self._fixation_length = length   # in seconds

    def set_save_path(
            self,
            path='dump_%(network)s.%(station)s.%(location)s.%(channel)s_'
                 '%(tmin)s_%(tmax)s.mseed'):

        self.clear_all()
        self._path = path

    def inject(self, trace):
        logger.debug('Received a trace: %s' % trace)

        entry = self.get(trace)
        if entry is None:
            buf = trace.copy()
            handle = self._squirrel.add_volatile_waveforms([buf])
            self.set(trace, (buf, handle))

        else:
            buf, handle = entry
            self._squirrel.remove(handle)
            buf.append(trace.ydata)
            handle = self._squirrel.add_volatile_waveforms([buf])

            self.set(trace, (buf, handle))

        if self._fixation_length is not None:
            if buf.tmax - buf.tmin > self._fixation_length:
                new_buf = self._fixate(buf, complete=False)
                if new_buf is None:
                    self.clear(trace, prevent_free=True)
                else:
                    self.set(trace, new_buf, prevent_free=True)

    def free(self, entry):
        self._fixate(entry)

    def _fixate(self, entry, complete=True):
        buf, handle = entry
        new_buf = None
        if self._path:
            self._squirrel.remove(handle)

            if self._fixation_length is not None:
                ttmin = buf.tmin
                ytmin = util.year_start(ttmin)
                n = int(math.floor((ttmin - ytmin) / self._fixation_length))
                tmin = ytmin + n*self._fixation_length
                traces = []
                t = tmin
                while t <= buf.tmax:
                    try:
                        traces.append(
                            buf.chop(
                                t,
                                t+self._fixation_length,
                                inplace=False,
                                snap=(math.ceil, math.ceil)))

                    except trace.NoData:
                        pass
                    t += self._fixation_length

                if abs(traces[-1].tmax - (t - buf.deltat)) < \
                        buf.deltat/100. or complete:

                    self._squirrel.remove_file(handle)

                else:  # reinsert incomplete last part
                    new_buf = traces.pop()
                    self._squirrel.add_volatile_waveforms([new_buf])

            else:
                traces = [buf]

            fns = io.save(traces, self._path, format=self._format)

            if not self._forget_fixed:
                self.squirrel.add(fns)

        return new_buf

    def __del__(self):
        self.clear_all()


def real_time_wait(
        sq,
        time_end_next,
        patience=1.0,
        time_sleep=1.0,
        time_delay_nowait=300):

    while True:
        time_now = time.time()

        sq.harvest_streams()
        injector = sq.get_injector()

        if time_end_next < time_now - time_delay_nowait:
            break

        if not injector:
            if time_end_next < time_now:
                break

            time.sleep(time_sleep)
            continue

        times = num.fromiter(
            sq.get_injector().get_times().values(), dtype=float)

        if times.size == 0:
            logger.debug('Streams: waiting for data.')
            time.sleep(time_sleep)
            continue

        times_min, times_median, times_max = num.percentile(
            times, [0, 50, 100])
        times_mad = num.median(num.abs(times - times_median))
        time_cut = times_median - times_mad * 2.0 * patience
        ncomplete = num.sum(time_end_next < times)

        logger.debug(
            'Streams: time lags (min, max, median, mad) [s]: '
            '%5.1f, %5.1f, %5.1f, %5.1f, complete/total: %i/%i',

            time_now - times_max,
            time_now - times_min,
            time_now - times_median,
            times_mad, ncomplete, times.size)

        if time_end_next < time_cut:
            logger.debug(
                'Time lag window to real time [s]: %.1f',
                time_now - time_end_next)

            break

        logger.debug('Streams: waiting for more data.')
        time.sleep(time_sleep)


__all__ = [
    'Injector',
    'real_time_wait',
]
