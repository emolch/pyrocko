# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Access to SEED volumes by interfacing `rdseed
<https://ds.iris.edu/ds/nodes/dmc/software/downloads/rdseed/>`_ (*deprecated*).
'''

import os
import sys
import subprocess
import tempfile
import calendar
import time
import re
import logging
import shutil

from pyrocko import ExternalProgramMissing
from pyrocko import pile, model, util, response
from pyrocko.io import eventdata

pjoin = os.path.join
logger = logging.getLogger('pyrocko.io.rdseed')


def cmp(a, b):
    return (a > b) - (a < b)


def read_station_header_file(fn):

    def m(i, *args):
        if len(ltoks) >= i + len(args) \
                and (tuple(ltoks[i:i+len(args)]) == args):
            return True
        return False

    def f(i):
        return float(toks[i])

    def s(i):
        if len(toks) > i:
            return toks[i]
        else:
            return ''

    with open(fn, 'r') as fi:

        stations = []
        atsec, station, channel = None, None, None

        for line in fi:
            toks = line.split()
            ltoks = line.lower().split()
            if m(2, 'station', 'header'):
                atsec = 'station'
                station = {'channels': []}
                stations.append(station)
                continue

            if m(2, 'station') and m(5, 'channel'):
                atsec = 'channel'
                channel = {}
                station['channels'].append(channel)
                continue

            if atsec == 'station':
                if m(1, 'station', 'code:'):
                    station['station'] = s(3)

                elif m(1, 'network', 'code:'):
                    station['network'] = s(3)

                elif m(1, 'name:'):
                    station['name'] = ' '.join(toks[2:])

            if atsec == 'channel':
                if m(1, 'channel:'):
                    channel['channel'] = s(2)

                elif m(1, 'location:'):
                    channel['location'] = s(2)

                elif m(1, 'latitude:'):
                    station['lat'] = f(2)

                elif m(1, 'longitude:'):
                    station['lon'] = f(2)

                elif m(1, 'elevation:'):
                    station['elevation'] = f(2)

                elif m(1, 'local', 'depth:'):
                    channel['depth'] = f(3)

                elif m(1, 'azimuth:'):
                    channel['azimuth'] = f(2)

                elif m(1, 'dip:'):
                    channel['dip'] = f(2)

    nsl_stations = {}
    for station in stations:
        for channel in station['channels']:
            def cs(k, default=None):
                return channel.get(k, station.get(k, default))

            nsl = station['network'], station['station'], channel['location']
            if nsl not in nsl_stations:
                nsl_stations[nsl] = model.Station(
                    network=station['network'],
                    station=station['station'],
                    location=channel['location'],
                    lat=cs('lat'),
                    lon=cs('lon'),
                    elevation=cs('elevation'),
                    depth=cs('depth', None),
                    name=station['name'])

            nsl_stations[nsl].add_channel(model.Channel(
                channel['channel'],
                azimuth=channel['azimuth'],
                dip=channel['dip']))

    return list(nsl_stations.values())


def cmp_version(a, b):
    ai = [int(x) for x in a.split('.')]
    bi = [int(x) for x in b.split('.')]
    return cmp(ai, bi)


def dumb_parser(data):

    (in_ws, in_kw, in_str) = (1, 2, 3)

    state = in_ws

    rows = []
    cols = []
    accu = ''
    for c in data:
        if state == in_ws:
            if c == '"':
                new_state = in_str

            elif c not in (' ', '\t', '\n', '\r'):
                new_state = in_kw

        if state == in_kw:
            if c in (' ', '\t', '\n', '\r'):
                cols.append(accu)
                accu = ''
                if c in ('\n', '\r'):
                    rows.append(cols)
                    cols = []
                new_state = in_ws

        if state == in_str:
            if c == '"':
                accu += c
                cols.append(accu[1:-1])
                accu = ''
                if c in ('\n', '\r'):
                    rows.append(cols)
                    cols = []
                new_state = in_ws

        state = new_state

        if state in (in_kw, in_str):
            accu += c

    if len(cols) != 0:
        rows.append(cols)

    return rows


class Programs(object):
    rdseed = 'rdseed'
    avail = None

    @staticmethod
    def check():
        if Programs.avail is not None:
            return Programs.avail

        else:
            try:
                rdseed_proc = subprocess.Popen(
                    [Programs.rdseed],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)

                (out, err) = rdseed_proc.communicate()

            except OSError as e:
                if e.errno == 2:
                    reason = "Could not find executable: '%s'." \
                        % Programs.rdseed
                else:
                    reason = str(e)

                logging.debug('Failed to run rdseed program. %s' % reason)
                Programs.avail = False
                return Programs.avail

            ms = [re.search(
                r'Release (\d+(\.\d+(\.\d+)?)?)', s.decode())
                  for s in (err, out)]
            ms = list(filter(bool, ms))
            if not ms:
                logger.error('Cannot determine rdseed version number.')
            else:
                version = ms[0].group(1)
                if cmp_version('4.7.5', version) == 1 \
                        or cmp_version(version, '5.1') == 1:

                    logger.warning(
                        'Module pyrocko.rdseed has not been tested with '
                        'version %s of rdseed.' % version)

            Programs.avail = True
            return Programs.avail


class SeedVolumeNotFound(Exception):
    pass


class SeedVolumeAccess(eventdata.EventDataAccess):

    def __init__(self, seedvolume, datapile=None):

        '''
        Create new SEED Volume access object.

        :param seedvolume: filename of seed volume
        :param datapile: if not ``None``, this should be a
            :py:class:`pile.Pile` object with data traces which are then used
            instead of the data provided by the SEED volume.
            (This is useful for dataless SEED volumes.)
        '''

        eventdata.EventDataAccess.__init__(self, datapile=datapile)
        self.tempdir = None
        Programs.check()

        self.tempdir = None
        self.seedvolume = seedvolume
        if not os.path.isfile(self.seedvolume):
            raise SeedVolumeNotFound()

        self.tempdir = tempfile.mkdtemp('', 'SeedVolumeAccess-')
        self.station_headers_file = os.path.join(
            self.tempdir, 'station_header_infos')
        self._unpack()
        self.shutil = shutil

    def __del__(self):
        if self.tempdir:
            self.shutil.rmtree(self.tempdir)

    def get_pile(self):
        if self._pile is None:
            fns = util.select_files([self.tempdir], include=r'\.SAC$')
            self._pile = pile.Pile()
            self._pile.load_files(fns, fileformat='sac')

        return self._pile

    def get_resp_file(self, tr):
        respfile = pjoin(self.tempdir, 'RESP.%s.%s.%s.%s' % tr.nslc_id)
        if not os.path.exists(respfile):
            raise eventdata.NoRestitution(
                'no response information available for trace %s.%s.%s.%s'
                % tr.nslc_id)

        return respfile

    def get_stationxml(self):
        stations = self.get_pyrocko_stations()
        respfiles = []
        for station in stations:
            for channel in station.get_channels():
                nslc = station.nsl() + (channel.name,)
                respfile = pjoin(self.tempdir, 'RESP.%s.%s.%s.%s' % nslc)
                respfiles.append(respfile)

        from pyrocko.client.fdsn import resp
        sxml = resp.make_stationxml(stations, resp.iload(respfiles))
        return sxml

    def get_restitution(self, tr, allowed_methods):
        if 'evalresp' in allowed_methods:
            respfile = pjoin(self.tempdir, 'RESP.%s.%s.%s.%s' % tr.nslc_id)
            if not os.path.exists(respfile):
                raise eventdata.NoRestitution(
                    'no response information available for trace %s.%s.%s.%s'
                    % tr.nslc_id)

            trans = response.InverseEvalresp(respfile, tr)
            return trans
        else:
            raise eventdata.NoRestitution(
                'no response information available for trace %s.%s.%s.%s'
                % tr.nslc_id)

    def get_pyrocko_response(self, tr, target):
        '''
        Extract the frequency response as :py:class:`response.EvalResp`
        instance for *tr*.

        :param tr: :py:class:`trace.Trace` instance
        '''
        respfile = self.get_resp_file(tr)
        return response.Evalresp(respfile, tr, target)

    def _unpack(self):
        input_fn = self.seedvolume
        output_dir = self.tempdir

        def strerr(s):
            return '\n'.join(['rdseed: '+line.decode()
                              for line in s.splitlines()])
        try:

            # seismograms:
            if self._pile is None:
                rdseed_proc = subprocess.Popen(
                    [Programs.rdseed, '-f', input_fn, '-d', '-z', '3', '-o',
                     '1', '-p', '-R', '-q', output_dir],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)

                (out, err) = rdseed_proc.communicate()
                logging.info(strerr(err))
            else:
                rdseed_proc = subprocess.Popen(
                    [Programs.rdseed, '-f', input_fn, '-z', '3', '-p', '-R',
                     '-q', output_dir],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE)

                (out, err) = rdseed_proc.communicate()
                logging.info(strerr(err))

            # event data:
            rdseed_proc = subprocess.Popen(
                [Programs.rdseed, '-f', input_fn, '-e', '-q', output_dir],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)

            (out, err) = rdseed_proc.communicate()
            logging.info(strerr(err))

            # station summary information:
            rdseed_proc = subprocess.Popen(
                [Programs.rdseed, '-f', input_fn, '-S', '-q', output_dir],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)

            (out, err) = rdseed_proc.communicate()
            logging.info(strerr(err))

            # station headers:
            rdseed_proc = subprocess.Popen(
                [Programs.rdseed, '-f', input_fn, '-s', '-q', output_dir],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE)

            (out, err) = rdseed_proc.communicate()
            with open(self.station_headers_file, 'w') as fout:
                fout.write(out.decode())
            logging.info(strerr(err))

        except OSError as e:
            if e.errno == 2:
                reason = "Could not find executable: '%s'." % Programs.rdseed
            else:
                reason = str(e)

            logging.fatal('Failed to unpack SEED volume. %s' % reason)
            sys.exit(1)

    def _get_events_from_file(self):
        rdseed_event_file = os.path.join(self.tempdir, 'rdseed.events')
        if not os.path.isfile(rdseed_event_file):
            return []

        with open(rdseed_event_file, 'r') as f:
            events = []
            for line in f:
                toks = line.split(', ')
                if len(toks) == 9:
                    datetime = toks[1].split('.')[0]
                    format = '%Y/%m/%d %H:%M:%S'
                    secs = util.to_time_float(calendar.timegm(
                        time.strptime(datetime, format)))
                    e = model.Event(
                        lat=float(toks[2]),
                        lon=float(toks[3]),
                        depth=float(toks[4])*1000.,
                        magnitude=float(toks[8]),
                        time=secs)

                    events.append(e)
                else:
                    raise Exception('Event description in unrecognized format')

        return events

    def _get_stations_from_file(self):
        stations = read_station_header_file(self.station_headers_file)
        return stations

    def _insert_channel_descriptions(self, stations):
        # this is done beforehand in this class
        pass


def check_have_rdseed():
    if not Programs.check():
        raise ExternalProgramMissing(
            'rdseed is not installed or cannot be found')


if __name__ == '__main__':
    print(SeedVolumeAccess(sys.argv[1]).get_stationxml().dump_xml())
