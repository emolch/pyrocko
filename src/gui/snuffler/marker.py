# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import math
import copy
import logging
import sys

import numpy as num

from pyrocko import util, plot, model, trace
from pyrocko.util import TableWriter, TableReader, gmtime_x, mystrftime


logger = logging.getLogger('pyrocko.gui.snuffler.marker')


if sys.version_info[0] >= 3:
    polarity_symbols = {1: u'\u2191', -1: u'\u2193', None: u'', 0: u'\u2195'}
else:
    polarity_symbols = {1: '+', -1: '-', None: '', 0: '0'}


def str_to_float_or_none(s):
    if s == 'None':
        return None
    return float(s)


def str_to_str_or_none(s):
    if s == 'None':
        return None
    return s


def str_to_int_or_none(s):
    if s == 'None':
        return None
    return int(s)


def str_to_bool(s):
    return s.lower() in ('true', 't', '1')


def myctime(timestamp):
    tt, ms = gmtime_x(timestamp)
    return mystrftime(None, tt, ms)


g_color_b = [plot.color(x) for x in (
    'scarletred1', 'scarletred2', 'scarletred3',
    'chameleon1', 'chameleon2', 'chameleon3',
    'skyblue1', 'skyblue2', 'skyblue3',
    'orange1', 'orange2', 'orange3',
    'plum1', 'plum2', 'plum3',
    'chocolate1', 'chocolate2', 'chocolate3',
    'butter1', 'butter2', 'butter3',
    'aluminium3', 'aluminium4', 'aluminium5')]


class MarkerParseError(Exception):
    pass


class MarkerOneNSLCRequired(Exception):
    '''
    Raised when a marker with exactly one NSLC entry is required but there are
    zero or more than one.
    '''
    pass


class Marker(object):
    '''
    General purpose marker GUI element and base class for
    :py:class:`EventMarker` and :py:class:`PhaseMarker`.

    :param nslc_ids: list of (network, station, location, channel) tuples
        (may contain wildcards)
    :param tmin: start time
    :param tmax: end time
    :param kind: (optional) integer to distinguish groups of markers
        (color-coded)
    '''

    @staticmethod
    def save_markers(markers, fn, fdigits=3):
        '''
        Static method to write marker objects to file.

        :param markers: list of :py:class:`Marker` objects
        :param fn: filename as string
        :param fdigits: number of decimal digits to use for sub-second time
             strings (default 3)
        '''
        f = open(fn, 'w')
        f.write('# Snuffler Markers File Version 0.2\n')
        writer = TableWriter(f)
        for marker in markers:
            a = marker.get_attributes(fdigits=fdigits)
            w = marker.get_attribute_widths(fdigits=fdigits)
            row = []
            for x in a:
                if x is None or x == '':
                    row.append('None')
                else:
                    row.append(x)

            writer.writerow(row, w)

        f.close()

    @staticmethod
    def load_markers(fn):
        '''
        Static method to load markers from file.

        :param filename:  filename as string
        :returns: list of :py:class:`Marker`, :py:class:`EventMarker` or
            :py:class:`PhaseMarker` objects
        '''
        markers = []
        with open(fn, 'r') as f:
            line = f.readline()
            if not line.startswith('# Snuffler Markers File Version'):
                raise MarkerParseError('Not a marker file')

            elif line.startswith('# Snuffler Markers File Version 0.2'):
                reader = TableReader(f)
                while not reader.eof:
                    row = reader.readrow()
                    if not row:
                        continue
                    if row[0] == 'event:':
                        marker = EventMarker.from_attributes(row)
                    elif row[0] == 'phase:':
                        marker = PhaseMarker.from_attributes(row)
                    else:
                        marker = Marker.from_attributes(row)

                    markers.append(marker)
            else:
                logger.warning('Unsupported Markers File Version')

        return markers

    def __init__(self, nslc_ids, tmin, tmax, kind=0):
        self.set(nslc_ids, tmin, tmax)
        self.alerted = False
        self.selected = False
        self.kind = kind
        self.active = False

    def set(self, nslc_ids, tmin, tmax):
        '''
        Set ``nslc_ids``, start time and end time of :py:class:`Marker`.

        :param nslc_ids: list or set of (network, station, location, channel)
            tuples
        :param tmin: start time
        :param tmax: end time
        '''
        self.nslc_ids = nslc_ids
        self.tmin = util.to_time_float(tmin)
        self.tmax = util.to_time_float(tmax)

    def set_kind(self, kind):
        '''
        Set kind of :py:class:`Marker`.

        :param kind: (optional) integer to distinguish groups of markers
                        (color-coded)
        '''
        self.kind = kind

    def get_tmin(self):
        '''
        Get *start time* of :py:class:`Marker`.
        '''
        return self.tmin

    def get_tmax(self):
        '''
        Get *end time* of :py:class:`Marker`.
        '''
        return self.tmax

    def get_nslc_ids(self):
        '''
        Get marker's network-station-location-channel pattern.

        :returns: list or set of (network, station, location, channel) tuples

        The network, station, location, or channel strings may contain wildcard
        expressions.
        '''
        return self.nslc_ids

    def is_alerted(self):
        return self.alerted

    def is_selected(self):
        return self.selected

    def set_alerted(self, state):
        self.alerted = state

    def match_nsl(self, nsl):
        '''
        See documentation of :py:func:`pyrocko.util.match_nslc`.
        '''
        patterns = ['.'.join(x[:3]) for x in self.nslc_ids]
        return util.match_nslc(patterns, nsl)

    def match_nslc(self, nslc):
        '''
        See documentation of :py:func:`pyrocko.util.match_nslc`.
        '''
        patterns = ['.'.join(x) for x in self.nslc_ids]
        return util.match_nslc(patterns, nslc)

    def one_nslc(self):
        '''
        Get single NSLC pattern or raise an exception if there is not exactly
        one.

        If *nslc_ids* contains a single entry, return it. If more than one is
        available, raise :py:exc:`MarkerOneNSLCRequired`.
        '''
        if len(self.nslc_ids) != 1:
            raise MarkerOneNSLCRequired()

        return list(self.nslc_ids)[0]

    def hoover_message(self):
        return ''

    def copy(self):
        '''
        Get a copy of this marker.
        '''
        return copy.deepcopy(self)

    def __str__(self):
        traces = ','.join(['.'.join(nslc_id) for nslc_id in self.nslc_ids])
        st = myctime
        if self.tmin == self.tmax:
            return '%s %i %s' % (st(self.tmin), self.kind, traces)
        else:
            return '%s %s %g %i %s' % (
                st(self.tmin), st(self.tmax), self.tmax-self.tmin, self.kind,
                traces)

    def get_attributes(self, fdigits=3):
        traces = ','.join(['.'.join(nslc_id) for nslc_id in self.nslc_ids])

        def st(t):
            return util.time_to_str(
                t, format='%Y-%m-%d %H:%M:%S.'+'%iFRAC' % fdigits)

        vals = []
        vals.extend(st(self.tmin).split())
        if self.tmin != self.tmax:
            vals.extend(st(self.tmax).split())
            vals.append(self.tmax-self.tmin)

        vals.append(self.kind)
        vals.append(traces)
        return vals

    def get_attribute_widths(self, fdigits=3):
        ws = [10, 9+fdigits]
        if self.tmin != self.tmax:
            ws.extend([10, 9+fdigits, 12])
        ws.extend([2, 15])
        return ws

    @staticmethod
    def parse_attributes(vals):
        tmin = util.str_to_time(vals[0] + ' ' + vals[1])
        i = 2
        tmax = tmin
        if len(vals) == 7:
            tmax = util.str_to_time(vals[2] + ' ' + vals[3])
            i = 5

        kind = int(vals[i])
        traces = vals[i+1]
        if traces == 'None':
            nslc_ids = []
        else:
            nslc_ids = tuple(
                [tuple(nslc_id.split('.')) for nslc_id in traces.split(',')])

        return nslc_ids, tmin, tmax, kind

    @staticmethod
    def from_attributes(vals):
        return Marker(*Marker.parse_attributes(vals))

    def select_color(self, colorlist):

        def cl(x):
            return colorlist[(self.kind*3+x) % len(colorlist)]

        if self.selected:
            return cl(1)

        if self.alerted:
            return cl(1)

        return cl(2)

    def draw(
            self, p, time_projection, y_projection,
            draw_line=True,
            draw_triangle=False,
            **kwargs):

        from ..qt_compat import qc, qg
        from .. import util as gui_util

        color = self.select_color(g_color_b)
        pen = qg.QPen(qg.QColor(*color))
        pen.setWidth(2)
        p.setPen(pen)

        umin = time_projection(self.tmin)
        umax = time_projection(self.tmax)
        v0, v1 = y_projection.get_out_range()
        line = qc.QLineF(umin-1, v0, umax+1, v0)
        p.drawLine(line)

        if self.selected or self.alerted or not self.nslc_ids:
            linepen = qg.QPen(pen)
            if self.selected or self.alerted:
                linepen.setStyle(qc.Qt.CustomDashLine)
                pat = [5., 3.]
                linepen.setDashPattern(pat)
                if self.alerted and not self.selected:
                    linepen.setColor(qg.QColor(150, 150, 150))

            s = 9.
            utriangle = gui_util.make_QPolygonF(
                [-0.577*s, 0., 0.577*s], [0., 1.*s, 0.])
            ltriangle = gui_util.make_QPolygonF(
                [-0.577*s, 0., 0.577*s], [0., -1.*s, 0.])

            def drawline(t):
                u = time_projection(t)
                line = qc.QLineF(u, v0, u, v1)
                p.drawLine(line)

            def drawtriangles(t):
                u = time_projection(t)
                t = qg.QPolygonF(utriangle)
                t.translate(u, v0)
                p.drawConvexPolygon(t)
                t = qg.QPolygonF(ltriangle)
                t.translate(u, v1)
                p.drawConvexPolygon(t)

            if draw_line or self.selected or self.alerted:
                p.setPen(linepen)
                drawline(self.tmin)
                drawline(self.tmax)

            if draw_triangle:
                pen.setStyle(qc.Qt.SolidLine)
                pen.setJoinStyle(qc.Qt.MiterJoin)
                pen.setWidth(2)
                p.setPen(pen)
                p.setBrush(qg.QColor(*color))
                drawtriangles(self.tmin)

    def draw_trace(
            self, viewer, p, tr, time_projection, track_projection, gain,
            outline_label=False):

        from ..qt_compat import qc, qg
        from .. import util as gui_util

        if self.nslc_ids and not self.match_nslc(tr.nslc_id):
            return

        color = self.select_color(g_color_b)
        pen = qg.QPen(qg.QColor(*color))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(qc.Qt.NoBrush)

        def drawpoint(t, y):
            u = time_projection(t)
            v = track_projection(y)
            rect = qc.QRectF(u-2, v-2, 4, 4)
            p.drawRect(rect)

        def drawline(t):
            u = time_projection(t)
            v0, v1 = track_projection.get_out_range()
            line = qc.QLineF(u, v0, u, v1)
            p.drawLine(line)

        try:
            snippet = tr.chop(
                self.tmin, self.tmax,
                inplace=False,
                include_last=True,
                snap=(math.ceil, math.floor))

            vdata = track_projection(gain*snippet.get_ydata())
            udata_min = float(
                time_projection(snippet.tmin))
            udata_max = float(
                time_projection(snippet.tmin+snippet.deltat*(vdata.size-1)))
            udata = num.linspace(udata_min, udata_max, vdata.size)
            qpoints = gui_util.make_QPolygonF(udata, vdata)
            pen.setWidth(1)
            p.setPen(pen)
            p.drawPolyline(qpoints)
            pen.setWidth(2)
            p.setPen(pen)
            drawpoint(*tr(self.tmin, clip=True, snap=math.ceil))
            drawpoint(*tr(self.tmax, clip=True, snap=math.floor))

        except trace.NoData:
            pass

        color = self.select_color(g_color_b)
        pen = qg.QPen(qg.QColor(*color))
        pen.setWidth(2)
        p.setPen(pen)

        drawline(self.tmin)
        drawline(self.tmax)

        label = self.get_label()
        if label:
            label_bg = qg.QBrush(qg.QColor(255, 255, 255))

            u = time_projection(self.tmin)
            v0, v1 = track_projection.get_out_range()
            if outline_label:
                du = -7
            else:
                du = -5
            gui_util.draw_label(
                p, u+du, v0, label, label_bg, 'TR',
                outline=outline_label)

        if self.tmin == self.tmax:
            try:
                drawpoint(self.tmin, tr.interpolate(self.tmin))

            except IndexError:
                pass

    def get_label(self):
        return None

    def convert_to_phase_marker(
            self,
            event=None,
            phasename=None,
            polarity=None,
            automatic=None,
            incidence_angle=None,
            takeoff_angle=None):

        if isinstance(self, PhaseMarker):
            return

        self.__class__ = PhaseMarker
        self._event = event
        self._phasename = phasename
        self._polarity = polarity
        self._automatic = automatic
        self._incidence_angle = incidence_angle
        self._takeoff_angle = takeoff_angle
        if self._event:
            self._event_hash = event.get_hash()
            self._event_time = event.time
        else:
            self._event_hash = None
            self._event_time = None
        self.active = False

    def convert_to_event_marker(self, lat=0., lon=0.):
        if isinstance(self, EventMarker):
            return

        if isinstance(self, PhaseMarker):
            self.convert_to_marker()

        self.__class__ = EventMarker
        self._event = model.Event(lat, lon, time=self.tmin, name='Event')
        self._event_hash = self._event.get_hash()
        self.active = False
        self.tmax = self.tmin
        self.nslc_ids = []


class EventMarker(Marker):
    '''
    GUI element representing a seismological event.

    :param event: A :py:class:`~pyrocko.model.event.Event` object containing
        meta information of a seismological event
    :param kind: (optional) integer to distinguish groups of markers
    :param event_hash:  (optional) hash code of event (see:
        :py:meth:`~pyrocko.model.event.Event.get_hash`)
    '''

    def __init__(self, event, kind=0, event_hash=None):
        Marker.__init__(self, [], event.time, event.time, kind)
        self._event = event
        self.active = False
        self._event_hash = event_hash

    def get_event_hash(self):
        if self._event_hash is not None:
            return self._event_hash
        else:
            return self._event.get_hash()

    def label(self):
        t = []
        mag = self._event.magnitude
        if mag is not None:
            t.append('M%3.1f' % mag)

        reg = self._event.region
        if reg is not None:
            t.append(reg)

        nam = self._event.name
        if nam is not None:
            t.append(nam)

        s = ' '.join(t)
        if not s:
            s = '(Event)'
        return s

    def draw(self, p, time_projection, y_projection, with_label=False):
        Marker.draw(
            self, p, time_projection, y_projection,
            draw_line=False,
            draw_triangle=True)

        if with_label:
            self.draw_label(p, time_projection, y_projection)

    def draw_label(self, p, time_projection, y_projection):
        from ..qt_compat import qg
        from .. import util as gui_util

        u = time_projection(self.tmin)
        v0, v1 = y_projection.get_out_range()
        label_bg = qg.QBrush(qg.QColor(255, 255, 255))
        gui_util.draw_label(
            p, u, v0-10., self.label(), label_bg, 'CB',
            outline=self.active)

    def get_event(self):
        '''
        Return an instance of the :py:class:`~pyrocko.model.event.Event`
        associated to this :py:class:`EventMarker`
        '''
        return self._event

    def draw_trace(self, viewer, p, tr, time_projection, track_projection,
                   gain):
        pass

    def hoover_message(self):
        ev = self.get_event()
        evs = []
        for k in 'magnitude lat lon depth name region catalog'.split():
            if ev.__dict__[k] is not None and ev.__dict__[k] != '':
                if k == 'depth':
                    sv = '%g km' % (ev.depth * 0.001)
                else:
                    sv = '%s' % ev.__dict__[k]
                evs.append('%s = %s' % (k, sv))

        return ', '.join(evs)

    def get_attributes(self, fdigits=3):
        attributes = ['event:']
        attributes.extend(Marker.get_attributes(self, fdigits=fdigits))
        del attributes[-1]
        e = self._event
        attributes.extend([
            e.get_hash(), e.lat, e.lon, e.depth, e.magnitude, e.catalog,
            e.name, e.region])

        return attributes

    def get_attribute_widths(self, fdigits=3):
        ws = [6]
        ws.extend(Marker.get_attribute_widths(self, fdigits=fdigits))
        del ws[-1]
        ws.extend([14, 12, 12, 12, 4, 5, 0, 0])
        return ws

    @staticmethod
    def from_attributes(vals):

        nslc_ids, tmin, tmax, kind = Marker.parse_attributes(
            vals[1:] + ['None'])
        lat, lon, depth, magnitude = [
            str_to_float_or_none(x) for x in vals[5:9]]
        catalog, name, region = [
            str_to_str_or_none(x) for x in vals[9:]]
        e = model.Event(
            lat, lon, time=tmin, name=name, depth=depth, magnitude=magnitude,
            region=region, catalog=catalog)
        marker = EventMarker(
            e, kind, event_hash=str_to_str_or_none(vals[4]))
        return marker


class PhaseMarker(Marker):
    '''
    A PhaseMarker is a GUI-element representing a seismological phase arrival

    :param nslc_ids: list of (network, station, location, channel) tuples (may
        contain wildcards)
    :param tmin: start time
    :param tmax: end time
    :param kind: (optional) integer to distinguish groups of markers
        (color-coded)
    :param event: a :py:class:`~pyrocko.model.event.Event` object containing
        meta information of a seismological event
    :param event_hash: (optional) hash code of event (see:
        :py:meth:`~pyrocko.model.event.Event.get_hash`)
    :param event_time: (optional) time of the associated event
    :param phasename: (optional) name of the phase associated with the marker
    :param polarity: (optional) polarity of arriving phase
    :param automatic: (optional)
    :param incident_angle: (optional) incident angle of phase
    :param takeoff_angle: (optional) take off angle of phase
    '''
    def __init__(
            self, nslc_ids, tmin, tmax,
            kind=0,
            event=None,
            event_hash=None,
            event_time=None,
            phasename=None,
            polarity=None,
            automatic=None,
            incidence_angle=None,
            takeoff_angle=None):

        Marker.__init__(self, nslc_ids, tmin, tmax, kind)
        self._event = event
        self._event_hash = event_hash
        self._event_time = event_time
        self._phasename = phasename
        self._automatic = automatic
        self._incidence_angle = incidence_angle
        self._takeoff_angle = takeoff_angle

        self.set_polarity(polarity)

    def draw_trace(self, viewer, p, tr, time_projection, track_projection,
                   gain):

        Marker.draw_trace(
            self, viewer, p, tr, time_projection, track_projection, gain,
            outline_label=(
                self._event is not None and
                self._event == viewer.get_active_event()))

    def get_label(self):
        t = []
        if self._phasename is not None:
            t.append(self._phasename)
        if self._polarity is not None:
            t.append(self.get_polarity_symbol())

        if self._automatic:
            t.append('@')

        return ''.join(t)

    def get_event(self):
        '''
        Return an instance of the :py:class:`~pyrocko.model.event.Event`
        associated to this :py:class:`EventMarker`
        '''
        return self._event

    def get_event_hash(self):
        if self._event_hash is not None:
            return self._event_hash
        else:
            if self._event is None:
                return None
            else:
                return self._event.get_hash()

    def get_event_time(self):
        if self._event is not None:
            return self._event.time
        else:
            return self._event_time

    def set_event_hash(self, event_hash):
        self._event_hash = event_hash

    def set_event(self, event):
        self._event = event
        if event is not None:
            self.set_event_hash(event.get_hash())

    def get_phasename(self):
        return self._phasename

    def set_phasename(self, phasename):
        self._phasename = phasename

    def set_polarity(self, polarity):
        if polarity not in [1, -1, 0, None]:
            raise ValueError('polarity has to be 1, -1, 0 or None')
        self._polarity = polarity

    def get_polarity_symbol(self):
        return polarity_symbols.get(self._polarity, '')

    def get_polarity(self):
        return self._polarity

    def convert_to_marker(self):
        del self._event
        del self._event_hash
        del self._phasename
        del self._polarity
        del self._automatic
        del self._incidence_angle
        del self._takeoff_angle
        self.active = False
        self.__class__ = Marker

    def hoover_message(self):
        toks = []
        for k in 'incidence_angle takeoff_angle polarity'.split():
            v = getattr(self, '_' + k)
            if v is not None:
                toks.append('%s = %s' % (k, v))

        return ', '.join(toks)

    def get_attributes(self, fdigits=3):
        attributes = ['phase:']
        attributes.extend(Marker.get_attributes(self, fdigits=fdigits))

        et = None, None
        if self._event:
            et = self._st(self._event.time, fdigits).split()
        elif self._event_time:
            et = self._st(self._event_time, fdigits).split()

        attributes.extend([
            self.get_event_hash(), et[0], et[1], self._phasename,
            self._polarity, self._automatic])

        return attributes

    def _st(self, t, fdigits):
        return util.time_to_str(
            t, format='%Y-%m-%d %H:%M:%S.'+'%iFRAC' % fdigits)

    def get_attribute_widths(self, fdigits=3):
        ws = [6]
        ws.extend(Marker.get_attribute_widths(self, fdigits=fdigits))
        ws.extend([14, 12, 12, 8, 4, 5])
        return ws

    @staticmethod
    def from_attributes(vals):
        if len(vals) == 14:
            nbasicvals = 7
        else:
            nbasicvals = 4
        nslc_ids, tmin, tmax, kind = Marker.parse_attributes(
            vals[1:1+nbasicvals])

        i = 8
        if len(vals) == 14:
            i = 11

        event_hash = str_to_str_or_none(vals[i-3])
        event_sdate = str_to_str_or_none(vals[i-2])
        event_stime = str_to_str_or_none(vals[i-1])

        if event_sdate is not None and event_stime is not None:
            event_time = util.str_to_time(event_sdate + ' ' + event_stime)
        else:
            event_time = None

        phasename = str_to_str_or_none(vals[i])
        polarity = str_to_int_or_none(vals[i+1])
        automatic = str_to_bool(vals[i+2])
        marker = PhaseMarker(nslc_ids, tmin, tmax, kind, event=None,
                             event_hash=event_hash, event_time=event_time,
                             phasename=phasename, polarity=polarity,
                             automatic=automatic)
        return marker


def load_markers(filename):
    '''
    Load markers from file.

    :param filename:  filename as string
    :returns: list of :py:class:`Marker` Objects
    '''

    return Marker.load_markers(filename)


def save_markers(markers, filename, fdigits=3):
    '''
    Save markers to file.

    :param markers: list of :py:class:`Marker` Objects
    :param filename: filename as string
    :param fdigits: number of decimal digits to use for sub-second time strings
    '''

    return Marker.save_markers(markers, filename, fdigits=fdigits)


def associate_phases_to_events(markers):
    '''
    Reassociate phases to events after import from markers file.
    '''

    hash_to_events = {}
    time_to_events = {}
    for marker in markers:
        if isinstance(marker, EventMarker):
            ev = marker.get_event()
            hash_to_events[marker.get_event_hash()] = ev
            time_to_events[ev.time] = ev

    for marker in markers:
        if isinstance(marker, PhaseMarker):
            h = marker.get_event_hash()
            t = marker.get_event_time()
            if marker.get_event() is None:
                if h is not None and h in hash_to_events:
                    marker.set_event(hash_to_events[h])
                    marker.set_event_hash(None)
                elif t is not None and t in time_to_events:
                    marker.set_event(time_to_events[t])
                    marker.set_event_hash(None)
