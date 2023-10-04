# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for enhanced `SAC
<http://ds.iris.edu/ds/nodes/dmc/software/downloads/sac/>`_ pole-zero files.

Enhanced SAC pole-zero files are SAC pole-zero files with additional channel
attributes in the file header comments as they are output e.g. by `rdseed
<https://ds.iris.edu/ds/nodes/dmc/software/downloads/rdseed/>`_.
'''


import time
from collections import defaultdict

from pyrocko import util, pz, response
from pyrocko.io import io_common
from pyrocko.io import stationxml as sxml
from pyrocko.guts import Object, Tuple, String, Timestamp, Float


guts_prefix = 'pf'


class EnhancedSacPzError(io_common.FileLoadError):
    pass


class EnhancedSacPzResponse(Object):
    codes = Tuple.T(4, String.T())
    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)
    lat = Float.T()
    lon = Float.T()
    elevation = Float.T()
    depth = Float.T()
    dip = Float.T()
    azimuth = Float.T()
    input_unit = String.T()
    output_unit = String.T()
    response = response.PoleZeroResponse.T()

    def spans(self, *args):
        if len(args) == 0:
            return True
        elif len(args) == 1:
            return ((self.tmin is None or
                     self.tmin <= args[0]) and
                    (self.tmax is None or
                     args[0] <= self.tmax))

        elif len(args) == 2:
            return ((self.tmin is None or
                     args[1] >= self.tmin) and
                    (self.tmax is None or
                     self.tmax >= args[0]))


def make_stationxml_response(presponse, input_unit, output_unit):
    return sxml.Response.from_pyrocko_pz_response(
        presponse, input_unit, output_unit, 1.0)


this_year = time.gmtime()[0]


def dummy_aware_str_to_time(s, time_format='%Y-%m-%dT%H:%M:%S'):
    try:
        util.str_to_time(s, format=time_format)
    except util.TimeStrError:
        year = int(s[:4])
        if year > this_year + 100:
            return None  # StationXML contained a dummy end date

        raise


def iload_fh(f, time_format='%Y-%m-%dT%H:%M:%S'):
    zeros, poles, constant, comments = pz.read_sac_zpk(file=f,
                                                       get_comments=True)
    d = {}
    for line in comments:
        toks = line.split(':', 1)
        if len(toks) == 2:
            temp = toks[0].strip('* \t')
            for k in ('network', 'station', 'location', 'channel', 'start',
                      'end', 'latitude', 'longitude', 'depth', 'elevation',
                      'dip', 'azimuth', 'input unit', 'output unit'):

                if temp.lower().startswith(k):
                    d[k] = toks[1].strip()

    resp = response.PoleZeroResponse(zeros, poles, constant)

    try:
        yield EnhancedSacPzResponse(
            codes=(d['network'], d['station'], d['location'], d['channel']),
            tmin=util.str_to_time(d['start'], format=time_format),
            tmax=dummy_aware_str_to_time(d['end']),
            lat=float(d['latitude']),
            lon=float(d['longitude']),
            elevation=float(d['elevation']),
            depth=float(d['depth']),
            dip=float(d['dip']),
            azimuth=float(d['azimuth']),
            input_unit=d['input unit'],
            output_unit=d['output unit'],
            response=resp)
    except KeyError as e:
        raise EnhancedSacPzError(
            'cannot get all required information "%s"' % e.args[0])


iload_filename, iload_dirname, iload_glob, iload = util.make_iload_family(
    iload_fh, 'SACPZ', ':py:class:`EnhancedSacPzResponse`')


def make_stationxml(responses, inconsistencies='warn'):
    '''
    Create stationxml from "enhanced" SACPZ information.

    :param responses: iterable yielding
        :py:class:`EnhancedSacPzResponse` objects
    :returns: :py:class:`pyrocko.io.stationxml.FDSNStationXML` object
    '''

    networks = {}
    stations = {}

    station_coords = defaultdict(list)
    station_channels = defaultdict(list)
    for cr in responses:
        net, sta, loc, cha = cr.codes
        station_coords[net, sta].append(
            (cr.codes, cr.lat, cr.lon, cr.elevation))

        station_channels[net, sta].append(sxml.Channel(
            code=cha,
            location_code=loc,
            start_date=cr.tmin,
            end_date=cr.tmax,
            latitude=sxml.Latitude(cr.lat),
            longitude=sxml.Longitude(cr.lon),
            elevation=sxml.Distance(cr.elevation),
            depth=sxml.Distance(cr.depth),
            response=make_stationxml_response(
                cr.response, cr.input_unit, cr.output_unit)))

    for (net, sta), v in sorted(station_coords.items()):
        lat, lon, elevation = util.consistency_merge(
            v,
            message='channel lat/lon/elevation values differ',
            error=inconsistencies)

        if net not in networks:
            networks[net] = sxml.Network(code=net)

        stations[net, sta] = sxml.Station(
            code=sta,
            latitude=sxml.Latitude(lat),
            longitude=sxml.Longitude(lon),
            elevation=sxml.Distance(elevation),
            channel_list=sorted(
                station_channels[net, sta],
                key=lambda c: (c.location_code, c.code)))

        networks[net].station_list.append(stations[net, sta])

    return sxml.FDSNStationXML(
        source='Converted from "enhanced" SACPZ information',
        created=time.time(),
        network_list=[networks[net_] for net_ in sorted(networks.keys())])


if __name__ == '__main__':

    import sys

    util.setup_logging(__name__)

    if len(sys.argv) < 2:
        sys.exit('usage: python -m pyrocko.station.enhanced_sacpz <sacpz> ...')

    sxml_in = make_stationxml(iload(sys.argv[1:]))
    print(sxml_in.dump_xml())
