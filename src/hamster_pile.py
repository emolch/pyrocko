# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Real-time data acquisition and processing helpers for :py:mod:`pyrocko.pile`.
'''

import os
import logging

from . import pile, io
from . import trace as tracemod

logger = logging.getLogger('pyrocko.hamster_pile')


class Processor(object):
    def __init__(self):
        self._buffers = {}

    def process(self, trace):
        return [trace]

    def get_buffer(self, trace):

        nslc = trace.nslc_id
        if nslc not in self._buffers:
            return None

        trbuf = self._buffers[nslc]
        if (abs((trbuf.tmax+trbuf.deltat) - trace.tmin) < 1.0e-1*trbuf.deltat
                and trbuf.ydata.dtype == trace.ydata.dtype
                and trbuf.deltat == trace.deltat):
            return trbuf
        else:
            return None

    def set_buffer(self, trace):
        nslc = trace.nslc_id
        self._buffers[nslc] = trace

    def empty_buffer(self, trace):
        nslc = trace.nslc_id
        del self._buffers[nslc]

    def flush_buffers(self):
        traces = list(self._buffers.values())
        self._buffers = {}
        return traces


class Renamer(object):
    def __init__(self, mapping):
        self._mapping = mapping

    def process(self, trace):
        target_id = self._mapping(trace)
        if target_id is None:
            return []

        out = trace.copy()
        out.set_codes(*target_id)
        return [out]


class Chain(Processor):
    def __init__(self, *processors):
        self._processors = processors

    def process(self, trace):
        traces = [trace]
        xtraces = []
        for p in self._processors:
            for tr in traces:
                xtraces.extend(p.process(traces))

        return xtraces


class Downsampler(Processor):

    def __init__(self, mapping, deltat):
        Processor.__init__(self)
        self._mapping = mapping
        self._downsampler = tracemod.co_downsample_to(deltat)

    def process(self, trace):
        target_id = self._mapping(trace)
        if target_id is None:
            return []

        ds_trace = self._downsampler.send(trace)
        ds_trace.set_codes(*target_id)
        if ds_trace.data_len() == 0:
            return []

        return [ds_trace]

    def __del__(self):
        self._downsampler.close()


class Grower(Processor):

    def __init__(self, tflush=None):
        Processor.__init__(self)
        self._tflush = tflush

    def process(self, trace):
        buffer = self.get_buffer(trace)
        if buffer is None:
            buffer = trace
            self.set_buffer(buffer)
        else:
            buffer.append(trace.ydata)

        if buffer.tmax - buffer.tmin >= self._tflush:
            self.empty_buffer(buffer)
            return [buffer]

        else:
            return []


class HamsterPile(pile.Pile):

    def __init__(
            self,
            fixation_length=None,
            path=None,
            format='from_extension',
            forget_fixed=False,
            processors=None):

        pile.Pile.__init__(self)
        self._buffers = {}          # keys: nslc,  values: MemTracesFile
        self._fixation_length = fixation_length
        self._format = format
        self._path = path
        self._forget_fixed = forget_fixed
        if processors is None:
            self._processors = [Processor()]
        else:
            self._processors = []
            for p in processors:
                self.add_processor(p)

    def set_fixation_length(self, length):
        '''
        Set length after which the fixation method is called on buffer traces.

        The length should be given in seconds. Give None to disable.
        '''
        self.fixate_all()
        self._fixation_length = length   # in seconds

    def set_save_path(
            self,
            path='dump_%(network)s.%(station)s.%(location)s.%(channel)s_'
                 '%(tmin)s_%(tmax)s.mseed'):

        self.fixate_all()
        self._path = path

    def add_processor(self, processor):
        self.fixate_all()
        self._processors.append(processor)

    def insert_trace(self, trace):
        logger.debug('Received a trace: %s' % trace)

        for p in self._processors:
            for tr in p.process(trace):
                self._insert_trace(tr)

    def _insert_trace(self, trace):
        buf = self._append_to_buffer(trace)
        nslc = trace.nslc_id

        if buf is None:  # create new buffer trace
            if nslc in self._buffers:
                self._fixate(self._buffers[nslc])

            trbuf = trace.copy()
            buf = pile.MemTracesFile(None, [trbuf])
            self.add_file(buf)
            self._buffers[nslc] = buf

        buf.recursive_grow_update([trace])
        trbuf = buf.get_traces()[0]
        if self._fixation_length is not None:
            if trbuf.tmax - trbuf.tmin > self._fixation_length:
                self._fixate(buf)
                del self._buffers[nslc]

    def _append_to_buffer(self, trace):
        '''
        Try to append the trace to the active buffer traces.

        Returns the current buffer trace or None if unsuccessful.
        '''

        nslc = trace.nslc_id
        if nslc not in self._buffers:
            return None

        buf = self._buffers[nslc]
        trbuf = buf.get_traces()[0]
        if (abs((trbuf.tmax+trbuf.deltat) - trace.tmin) < 1.0e-1*trbuf.deltat
                and trbuf.ydata.dtype == trace.ydata.dtype
                and trbuf.deltat == trace.deltat):

            trbuf.append(trace.ydata)
            return buf

        return None

    def fixate_all(self):
        for buf in self._buffers.values():
            self._fixate(buf)

        self._buffers = {}

    def _fixate(self, buf):
        if self._path:
            trbuf = buf.get_traces()[0]
            fns = io.save([trbuf], self._path, format=self._format)

            self.remove_file(buf)
            if not self._forget_fixed:
                self.load_files(
                    fns, show_progress=False, fileformat=self._format)

    def drop_older(self, tmax, delete_disk_files=False):
        self.drop(
            condition=lambda file: file.tmax < tmax,
            delete_disk_files=delete_disk_files)

    def drop(self, condition, delete_disk_files=False):
        candidates = []
        buffers = list(self._buffers.values())
        for file in self.iter_files():
            if condition(file) and file not in buffers:
                candidates.append(file)

        self.remove_files(candidates)
        if delete_disk_files:
            for file in candidates:
                if file.abspath and os.path.exists(file.abspath):
                    os.unlink(file.abspath)

    def __del__(self):
        self.fixate_all()
