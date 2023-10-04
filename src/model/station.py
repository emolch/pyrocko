# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Simple representation of a seismic station (Pyrocko classic).

.. note::

    An improved data model for seismic stations is available in
    :py:mod:`pyrocko.squirrel.model`. This module will stay available for
    backward compatibility. Conversion from Squirrel-based to Pyrocko
    classic can be achieved with
    :py:meth:`pyrocko.squirrel.model.Station.get_pyrocko_station`. '''

import math
import copy
import logging
import numpy as num

from pyrocko import orthodrome
from pyrocko.orthodrome import wrap
from pyrocko.guts import Object, Float, String, List, dump_all

from .location import Location

logger = logging.getLogger('pyrocko.model.station')

guts_prefix = 'pf'

d2r = num.pi / 180.


class ChannelsNotOrthogonal(Exception):
    pass


def guess_azimuth_from_name(channel_name):
    if channel_name.endswith('N'):
        return 0.
    elif channel_name.endswith('E'):
        return 90.
    elif channel_name.endswith('Z'):
        return 0.

    return None


def guess_dip_from_name(channel_name):
    if channel_name.endswith('N'):
        return 0.
    elif channel_name.endswith('E'):
        return 0.
    elif channel_name.endswith('Z'):
        return -90.

    return None


def guess_azimuth_dip_from_name(channel_name):
    return guess_azimuth_from_name(channel_name), \
        guess_dip_from_name(channel_name)


def mkvec(x, y, z):
    return num.array([x, y, z], dtype=float)


def are_orthogonal(enus, eps=0.05):
    return all(abs(x) < eps for x in [
        num.dot(enus[0], enus[1]),
        num.dot(enus[1], enus[2]),
        num.dot(enus[2], enus[0])])


def fill_orthogonal(enus):

    nmiss = sum(x is None for x in enus)

    if nmiss == 1:
        for ic in range(len(enus)):
            if enus[ic] is None:
                enus[ic] = num.cross(enus[(ic-2) % 3], enus[(ic-1) % 3])

    if nmiss == 2:
        for ic in range(len(enus)):
            if enus[ic] is not None:
                xenu = enus[ic] + mkvec(1, 1, 1)
                enus[(ic+1) % 3] = num.cross(enus[ic], xenu)
                enus[(ic+2) % 3] = num.cross(enus[ic], enus[(ic+1) % 3])

    if nmiss == 3:
        # holy camoly..
        enus[0] = mkvec(1, 0, 0)
        enus[1] = mkvec(0, 1, 0)
        enus[2] = mkvec(0, 0, 1)


class Channel(Object):
    name = String.T()
    azimuth = Float.T(optional=True)
    dip = Float.T(optional=True)
    gain = Float.T(default=1.0)

    def __init__(self, name, azimuth=None, dip=None, gain=1.0):
        if azimuth is None:
            azimuth = guess_azimuth_from_name(name)
        if dip is None:
            dip = guess_dip_from_name(name)

        Object.__init__(
            self,
            name=name,
            azimuth=float_or_none(azimuth),
            dip=float_or_none(dip),
            gain=float(gain))

    @property
    def ned(self):
        if None in (self.azimuth, self.dip):
            return None

        n = math.cos(self.azimuth*d2r)*math.cos(self.dip*d2r)
        e = math.sin(self.azimuth*d2r)*math.cos(self.dip*d2r)
        d = math.sin(self.dip*d2r)
        return mkvec(n, e, d)

    @property
    def enu(self):
        if None in (self.azimuth, self.dip):
            return None

        n = math.cos(self.azimuth*d2r)*math.cos(self.dip*d2r)
        e = math.sin(self.azimuth*d2r)*math.cos(self.dip*d2r)
        d = math.sin(self.dip*d2r)
        return mkvec(e, n, -d)

    def __str__(self):
        return '%s %f %f %g' % (self.name, self.azimuth, self.dip, self.gain)


class Station(Location):
    network = String.T()
    station = String.T()
    location = String.T()
    name = String.T(default='')
    channels = List.T(Channel.T())

    def __init__(self, network='', station='', location='',
                 lat=0.0, lon=0.0,
                 elevation=0.0, depth=0.0,
                 north_shift=0.0, east_shift=0.0,
                 name='', channels=None):

        Location.__init__(
            self,
            network=network, station=station, location=location,
            lat=float(lat), lon=float(lon),
            elevation=float(elevation),
            depth=float(depth),
            north_shift=float(north_shift),
            east_shift=float(east_shift),
            name=name or '',
            channels=channels or [])

        self.dist_deg = None
        self.dist_m = None
        self.azimuth = None
        self.backazimuth = None

    def copy(self):
        return copy.deepcopy(self)

    def set_event_relative_data(self, event, distance_3d=False):
        surface_dist = self.distance_to(event)
        if distance_3d:
            if event.depth is None:
                logger.warning('No event depth given: using 0 m.')
                dd = 0.0 - self.depth
            else:
                dd = event.depth - self.depth

            self.dist_m = math.sqrt(dd**2 + surface_dist**2)
        else:
            self.dist_m = surface_dist

        self.dist_deg = surface_dist / orthodrome.earthradius_equator * \
            orthodrome.r2d

        self.azimuth, self.backazimuth = event.azibazi_to(self)

    def set_channels_by_name(self, *args):
        self.set_channels([])
        for name in args:
            self.add_channel(Channel(name))

    def set_channels(self, channels):
        self.channels = []
        for ch in channels:
            self.add_channel(ch)

    def get_channels(self):
        return list(self.channels)

    def get_channel_names(self):
        return set(ch.name for ch in self.channels)

    def remove_channel_by_name(self, name):
        todel = [ch for ch in self.channels if ch.name == name]
        for ch in todel:
            self.channels.remove(ch)

    def add_channel(self, channel):
        self.remove_channel_by_name(channel.name)
        self.channels.append(channel)
        self.channels.sort(key=lambda ch: ch.name)

    def get_channel(self, name):
        for ch in self.channels:
            if ch.name == name:
                return ch

        return None

    def rotation_ne_to_rt(self, in_channel_names, out_channel_names):

        angle = wrap(self.backazimuth + 180., -180., 180.)
        in_channels = [self.get_channel(name) for name in in_channel_names]
        out_channels = [
            Channel(out_channel_names[0],
                    wrap(self.backazimuth+180., -180., 180.),  0., 1.),
            Channel(out_channel_names[1],
                    wrap(self.backazimuth+270., -180., 180.),  0., 1.)]
        return angle, in_channels, out_channels

    def _projection_to(
            self, to, in_channel_names, out_channel_names, use_gains=False):

        in_channels = [self.get_channel(name) for name in in_channel_names]

        # create orthogonal vectors for missing components, such that this
        # won't break projections when components are missing.

        vecs = []
        for ch in in_channels:
            if ch is None:
                vecs.append(None)
            else:
                vec = getattr(ch, to)
                if use_gains:
                    vec /= ch.gain
                vecs.append(vec)

        fill_orthogonal(vecs)
        if not are_orthogonal(vecs):
            raise ChannelsNotOrthogonal(
                'components are not orthogonal: station %s.%s.%s, '
                'channels %s, %s, %s'
                % (self.nsl() + tuple(in_channel_names)))

        m = num.hstack([vec2[:, num.newaxis] for vec2 in vecs])

        m = num.where(num.abs(m) < num.max(num.abs(m))*1e-16, 0., m)

        if to == 'ned':
            out_channels = [
                Channel(out_channel_names[0], 0.,   0., 1.),
                Channel(out_channel_names[1], 90.,  0., 1.),
                Channel(out_channel_names[2], 0.,  90., 1.)]

        elif to == 'enu':
            out_channels = [
                Channel(out_channel_names[0], 90.,  0., 1.),
                Channel(out_channel_names[1], 0.,   0., 1.),
                Channel(out_channel_names[2], 0., -90., 1.)]

        return m, in_channels, out_channels

    def guess_channel_groups(self):
        cg = {}
        for channel in self.get_channels():
            if len(channel.name) >= 1:
                kind = channel.name[:-1]
                if kind not in cg:
                    cg[kind] = []
                cg[kind].append(channel.name[-1])

        def allin(a, b):
            return all(x in b for x in a)

        out_groups = []
        for kind, components in cg.items():
            for sys in ('ENZ', '12Z', 'XYZ', 'RTZ', '123'):
                if allin(sys, components):
                    out_groups.append(tuple([kind+c for c in sys]))

        return out_groups

    def guess_projections_to_enu(self, out_channels=('E', 'N', 'U'), **kwargs):
        proj = []
        for cg in self.guess_channel_groups():
            try:
                proj.append(self.projection_to_enu(
                    cg, out_channels=out_channels, **kwargs))

            except ChannelsNotOrthogonal as e:
                logger.warning(str(e))

        return proj

    def guess_projections_to_rtu(
            self, out_channels=('R', 'T', 'U'), backazimuth=None, **kwargs):

        if backazimuth is None:
            backazimuth = self.backazimuth
        out_channels_ = [
            Channel(
                out_channels[0], wrap(backazimuth+180., -180., 180.),  0., 1.),
            Channel(
                out_channels[1], wrap(backazimuth+270., -180., 180.),  0., 1.),
            Channel(
                out_channels[2], 0.,  -90., 1.)]

        proj = []
        for (m, in_channels, _) in self.guess_projections_to_enu(**kwargs):
            phi = (backazimuth + 180.)*d2r
            r = num.array([[math.sin(phi),  math.cos(phi), 0.0],
                           [math.cos(phi), -math.sin(phi), 0.0],
                           [0.0, 0.0, 1.0]])
            proj.append((num.dot(r, m), in_channels, out_channels_))

        return proj

    def projection_to_enu(
            self,
            in_channels,
            out_channels=('E', 'N', 'U'),
            **kwargs):

        return self._projection_to('enu', in_channels, out_channels, **kwargs)

    def projection_to_ned(
            self,
            in_channels,
            out_channels=('N', 'E', 'D'),
            **kwargs):

        return self._projection_to('ned', in_channels, out_channels, **kwargs)

    def projection_from_enu(
            self,
            in_channels=('E', 'N', 'U'),
            out_channels=('X', 'Y', 'Z'),
            **kwargs):

        m, out_channels, in_channels = self._projection_to(
            'enu', out_channels, in_channels, **kwargs)

        return num.linalg.inv(m), in_channels, out_channels

    def projection_from_ned(
            self,
            in_channels=('N', 'E', 'D'),
            out_channels=('X', 'Y', 'Z'),
            **kwargs):

        m, out_channels, in_channels = self._projection_to(
            'ned', out_channels, in_channels, **kwargs)

        return num.linalg.inv(m), in_channels, out_channels

    def nsl_string(self):
        return '.'.join((self.network, self.station, self.location))

    def nsl(self):
        return self.network, self.station, self.location

    def cannot_handle_offsets(self):
        if self.north_shift != 0.0 or self.east_shift != 0.0:
            logger.warning(
                'Station %s.%s.%s has a non-zero Cartesian offset. Such '
                'offsets cannot be saved in the basic station file format. '
                'Effective lat/lons are saved only. Please save the stations '
                'in YAML format to preserve the reference-and-offset '
                'coordinates.' % self.nsl())

    def oldstr(self):
        self.cannot_handle_offsets()
        nsl = '%s.%s.%s' % (self.network, self.station, self.location)
        s = '%-15s  %14.5f %14.5f %14.1f %14.1f %s' % (
            nsl, self.effective_lat, self.effective_lon, self.elevation,
            self.depth, self.name)
        return s


def dump_stations(stations, filename):
    '''
    Write stations file.

    :param stations: list of :py:class:`Station` objects
    :param filename: filename as str
    '''
    f = open(filename, 'w')
    for sta in stations:
        f.write(sta.oldstr()+'\n')
        for cha in sta.get_channels():
            azimuth = 'NaN'
            if cha.azimuth is not None:
                azimuth = '%7g' % cha.azimuth

            dip = 'NaN'
            if cha.dip is not None:
                dip = '%7g' % cha.dip

            f.write('%5s %14s %14s %14g\n' % (
                cha.name, azimuth, dip, cha.gain))

    f.close()


def dump_stations_yaml(stations, filename):
    '''
    Write stations file in YAML format.

    :param stations: list of :py:class:`Station` objects
    :param filename: filename as str
    '''

    dump_all(stations, filename=filename)


def float_or_none(s):
    if s is None:
        return None
    elif isinstance(s, str) and s.lower() == 'nan':
        return None
    else:
        return float(s)


def detect_format(filename):
    with open(filename, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or line.startswith('%'):
                continue
            if line.startswith('--- !pf.Station'):
                return 'yaml'
            else:
                return 'basic'

    return 'basic'


def load_stations(filename, format='detect'):
    '''
    Read stations file.

    :param filename: filename
    :returns: list of :py:class:`Station` objects
    '''

    if format == 'detect':
        format = detect_format(filename)

    if format == 'yaml':
        from pyrocko import guts
        stations = [
            st for st in guts.load_all(filename=filename)
            if isinstance(st, Station)]

        return stations

    elif format == 'basic':
        stations = []
        f = open(filename, 'r')
        station = None
        channel_names = []
        for (iline, line) in enumerate(f):
            toks = line.split(None, 5)
            if line.strip().startswith('#') or line.strip() == '':
                continue

            if len(toks) == 5 or len(toks) == 6:
                net, sta, loc = toks[0].split('.')
                lat, lon, elevation, depth = [float(x) for x in toks[1:5]]
                if len(toks) == 5:
                    name = ''
                else:
                    name = toks[5].rstrip()

                station = Station(
                    net, sta, loc, lat, lon,
                    elevation=elevation, depth=depth, name=name)

                stations.append(station)
                channel_names = []

            elif len(toks) == 4 and station is not None:
                name, azi, dip, gain = (
                    toks[0],
                    float_or_none(toks[1]),
                    float_or_none(toks[2]),
                    float(toks[3]))
                if name in channel_names:
                    logger.warning(
                        'redefined channel! (line: %i, file: %s)' %
                        (iline + 1, filename))
                else:
                    channel_names.append(name)

                channel = Channel(name, azimuth=azi, dip=dip, gain=gain)
                station.add_channel(channel)

            else:
                logger.warning('skipping invalid station/channel definition '
                               '(line: %i, file: %s' % (iline + 1, filename))

        f.close()
        return stations

    else:
        from pyrocko.io.io_common import FileLoadError
        raise FileLoadError('unknown event file format: %s' % format)


def dump_kml(objects, filename):
    station_template = '''
  <Placemark>
    <name>%(network)s.%(station)s.%(location)s</name>
    <description></description>
    <styleUrl>#msn_S</styleUrl>
    <Point>
      <coordinates>%(elon)f,%(elat)f,%(elevation)f</coordinates>
    </Point>
  </Placemark>
'''

    f = open(filename, 'w')
    f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    f.write('<kml xmlns="http://www.opengis.net/kml/2.2">\n')
    f.write('<Document>\n')
    f.write(''' <Style id="sh_S">
                <IconStyle>
                        <scale>1.3</scale>
                        <Icon>
                                <href>http://maps.google.com/mapfiles/kml/paddle/S.png</href>
                        </Icon>
                        <hotSpot x="32" y="1" xunits="pixels" yunits="pixels"/>
                </IconStyle>
                <ListStyle>
                        <ItemIcon>
                                <href>http://maps.google.com/mapfiles/kml/paddle/S-lv.png</href>
                        </ItemIcon>
                </ListStyle>
        </Style>
        <Style id="sn_S">
                <IconStyle>
                        <scale>1.1</scale>
                        <Icon>
                                <href>http://maps.google.com/mapfiles/kml/paddle/S.png</href>
                        </Icon>
                        <hotSpot x="32" y="1" xunits="pixels" yunits="pixels"/>
                </IconStyle>
                <ListStyle>
                        <ItemIcon>
                                <href>http://maps.google.com/mapfiles/kml/paddle/S-lv.png</href>
                        </ItemIcon>
                </ListStyle>
        </Style>
        <StyleMap id="msn_S">
                <Pair>
                        <key>normal</key>
                        <styleUrl>#sn_S</styleUrl>
                </Pair>
                <Pair>
                        <key>highlight</key>
                        <styleUrl>#sh_S</styleUrl>
                </Pair>
        </StyleMap>
''')
    for obj in objects:

        if isinstance(obj, Station):
            d = obj.__dict__.copy()
            d['elat'], d['elon'] = obj.effective_latlon
            f.write(station_template % d)

    f.write('</Document>')
    f.write('</kml>\n')
    f.close()
