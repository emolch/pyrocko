# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for RESP files.
'''

import time
import re
import logging

from pyrocko import util, guts
from pyrocko.io import io_common
from pyrocko.io import stationxml as sxml

logger = logging.getLogger('pyrocko.io.resp')


class RespError(io_common.FileLoadError):
    pass


def ppolezero(s):
    v = s.split()
    return sxml.PoleZero(
        number=int(v[0]),
        real=sxml.FloatNoUnit(
            value=float(v[1]),
            plus_error=float(v[3]) or None,
            minus_error=float(v[3]) or None),
        imaginary=sxml.FloatNoUnit(
            value=float(v[2]),
            plus_error=float(v[4]) or None,
            minus_error=float(v[4]) or None))


def pcfu(s):
    v = list(map(float, s.split()))
    return sxml.FloatWithUnit(
        value=float(v[-2]),
        plus_error=float(v[-1]) or None,
        minus_error=float(v[-1]) or None)


def pnc(s):
    v = list(map(float, s.split()))
    return sxml.NumeratorCoefficient(i=int(v[0]), value=float(v[1]))


def punit(s):
    return str(s.split()[0].decode('ascii'))


def psymmetry(s):
    return {
        b'A': 'NONE',
        b'B': 'ODD',
        b'C': 'EVEN'}[s.upper()]


def ptftype(s):
    if s.startswith(b'A'):
        return 'LAPLACE (RADIANS/SECOND)'
    elif s.startswith(b'B'):
        return 'LAPLACE (HERTZ)'
    elif s.startswith(b'D'):
        return 'DIGITAL (Z-TRANSFORM)'
    else:
        raise RespError('Unknown PZ transfer function type.')


def pcftype(s):
    if s.startswith(b'A'):
        return 'ANALOG (RADIANS/SECOND)'
    elif s.startswith(b'B'):
        return 'ANALOG (HERTZ)'
    elif s.startswith(b'D'):
        return 'DIGITAL'
    else:
        raise RespError('Unknown cf transfer function type.')


def pblock_060(content):
    stage_number = int(get1(content, b'04'))
    return stage_number, None


def pblock_053(content):
    stage_number = int(get1(content, b'04'))

    pzs = sxml.PolesZeros(
        pz_transfer_function_type=ptftype(get1(content, b'03')),
        input_units=sxml.Units(name=punit(get1(content, b'05'))),
        output_units=sxml.Units(name=punit(get1(content, b'06'))),
        normalization_factor=float(get1(content, b'07')),
        normalization_frequency=sxml.Frequency(
            value=float(get1(content, b'08'))),

        zero_list=list(map(ppolezero, getn(content, b'10-13'))),
        pole_list=list(map(ppolezero, getn(content, b'15-18'))))

    for i, x in enumerate(pzs.zero_list):
        x.number = i

    for i, x in enumerate(pzs.pole_list):
        x.number = i

    return stage_number, pzs


def pblock_043(content):
    stage_number = -1

    pzs = sxml.PolesZeros(
        pz_transfer_function_type=ptftype(get1(content, b'05')),
        input_units=sxml.Units(name=punit(get1(content, b'06'))),
        output_units=sxml.Units(name=punit(get1(content, b'07'))),
        normalization_factor=float(get1(content, b'08')),
        normalization_frequency=sxml.Frequency(
            value=float(get1(content, b'09'))),

        zero_list=list(map(ppolezero, getn(content, b'11-14'))),
        pole_list=list(map(ppolezero, getn(content, b'16-19'))))

    for i, x in enumerate(pzs.zero_list):
        x.number = i

    for i, x in enumerate(pzs.pole_list):
        x.number = i

    return stage_number, pzs


def pblock_058(content):
    stage_number = int(get1(content, b'03'))

    gain = sxml.Gain(
        value=float(get1(content, b'04')),
        frequency=float(get1(content, b'05').split()[0]))

    return stage_number, gain


def pblock_048(content):
    stage_number = -1

    gain = sxml.Gain(
        value=float(get1(content, b'05')),
        frequency=float(get1(content, b'06').split()[0]))

    return stage_number, gain


def pblock_054(content):
    stage_number = int(get1(content, b'04'))

    cfs = sxml.Coefficients(
        cf_transfer_function_type=pcftype(get1(content, b'03')),
        input_units=sxml.Units(name=punit(get1(content, b'05'))),
        output_units=sxml.Units(name=punit(get1(content, b'06'))),
        numerator_list=list(map(pcfu, getn(content, b'08-09'))),
        denominator_list=list(map(pcfu, getn(content, b'11-12'))))

    return stage_number, cfs


def pblock_044(content):
    stage_number = -1

    cfs = sxml.Coefficients(
        cf_transfer_function_type=pcftype(get1(content, b'05')),
        input_units=sxml.Units(name=punit(get1(content, b'06'))),
        output_units=sxml.Units(name=punit(get1(content, b'07'))),
        numerator_list=list(map(pcfu, getn(content, b'09-10'))),
        denominator_list=list(map(pcfu, getn(content, b'12-13'))))

    return stage_number, cfs


def pblock_057(content):
    stage_number = int(get1(content, b'03'))

    deci = sxml.Decimation(
        input_sample_rate=sxml.Frequency(value=float(get1(content, b'04'))),
        factor=int(get1(content, b'05')),
        offset=int(get1(content, b'06')),
        delay=sxml.FloatWithUnit(value=float(get1(content, b'07'))),
        correction=sxml.FloatWithUnit(value=float(get1(content, b'08'))))

    return stage_number, deci


def pblock_047(content):
    stage_number = -1

    deci = sxml.Decimation(
        input_sample_rate=sxml.Frequency(value=float(get1(content, b'05'))),
        factor=int(get1(content, b'06')),
        offset=int(get1(content, b'07')),
        delay=sxml.FloatWithUnit(value=float(get1(content, b'08'))),
        correction=sxml.FloatWithUnit(value=float(get1(content, b'09'))))

    return stage_number, deci


def pblock_061(content):
    stage_number = int(get1(content, b'03'))

    fir = sxml.FIR(
        name=get1(content, b'04', optional=True),
        input_units=sxml.Units(name=punit(get1(content, b'06'))),
        output_units=sxml.Units(name=punit(get1(content, b'07'))),
        symmetry=psymmetry(get1(content, b'05')),
        numerator_coefficient_list=list(map(pnc, getn(content, b'09'))))

    return stage_number, fir


def pblock_041(content):
    stage_number = -1

    fir = sxml.FIR(
        name=get1(content, b'04', optional=True),
        input_units=sxml.Units(name=punit(get1(content, b'06'))),
        output_units=sxml.Units(name=punit(get1(content, b'07'))),
        symmetry=psymmetry(get1(content, b'05')),
        numerator_coefficient_list=list(map(pnc, getn(content, b'09'))))

    return stage_number, fir


bdefs = {
    b'050': {
        'name': 'Station Identifier Blockette',
    },
    b'052': {
        'name': 'Channel Identifier Blockette',
    },
    b'060': {
        'name': 'Response Reference Information',
        'parse': pblock_060,
    },
    b'053': {
        'name': 'Response (Poles & Zeros) Blockette',
        'parse': pblock_053,
    },
    b'043': {
        'name': 'Response (Poles & Zeros) Dictionary Blockette',
        'parse': pblock_043,
    },
    b'054': {
        'name': 'Response (Coefficients) Blockette',
        'parse': pblock_054,
    },
    b'044': {
        'name': 'Response (Coefficients) Dictionary Blockette',
        'parse': pblock_044,
    },
    b'057': {
        'name': 'Decimation Blockette',
        'parse': pblock_057,
    },
    b'047': {
        'name': 'Decimation Dictionary Blockette',
        'parse': pblock_047,
    },
    b'058': {
        'name': 'Channel Sensitivity/Gain Blockette',
        'parse': pblock_058,
    },
    b'048': {
        'name': 'Channel Sensitivity/Gain Dictionary Blockette',
        'parse': pblock_048,
    },
    b'061': {
        'name': 'FIR Response Blockette',
        'parse': pblock_061,
    },
    b'041': {
        'name': 'FIR Dictionary Blockette',
        'parse': pblock_041,
    },
}


def parse1(f):
    for line in f:
        line = line.rstrip(b'\r\n')
        m = re.match(
            br'\s*(#(.+)|B(\d\d\d)F(\d\d(-\d\d)?)\s+(([^:]+):\s*)?(.*))', line)
        if m:
            if m.group(2):
                pass

            elif m.group(3):
                block = m.group(3)
                field = m.group(4)
                key = m.group(7)
                value = m.group(8)
                yield block, field, key, value


def parse2(f):
    current_b = None
    content = []
    for block, field, key, value in parse1(f):
        if current_b != block or field == b'03':
            if current_b is not None:
                yield current_b, content

            current_b = block
            content = []

        content.append((field, key, value))

    if current_b is not None:
        yield current_b, content


def parse3(f):
    state = [None, None, []]
    for block, content in parse2(f):
        if block == b'050' and state[0] and state[1]:
            yield state
            state = [None, None, []]

        if block == b'050':
            state[0] = content
        elif block == b'052':
            state[1] = content
        else:
            state[2].append((block, content))

    if state[0] and state[1]:
        yield state


def get1(content, field, default=None, optional=False):
    for field_, _, value in content:
        if field_ == field:
            return value
    else:
        if optional:
            return None
        elif default is not None:
            return default
        else:
            raise RespError('Key not found: %s' % field)


def getn(content, field):
    lst = []
    for field_, _, value in content:
        if field_ == field:
            lst.append(value)
    return lst


def pdate(s):
    if len(s) < 17:
        s += b'0000,001,00:00:00'[len(s):]

    if s.startswith(b'2599') or s.startswith(b'2999'):
        return None
    elif s.lower().startswith(b'no'):
        return None
    else:
        t = s.split(b',')
        if len(t) > 2 and t[1] == b'000':
            s = b','.join([t[0], b'001'] + t[2:])

        return util.str_to_time(
            str(s.decode('ascii')), format='%Y,%j,%H:%M:%S.OPTFRAC')


def ploc(s):
    if s == b'??':
        return ''
    else:
        return str(s.decode('ascii'))


def pcode(s):
    return str(s.decode('ascii'))


def gett(lst, t):
    return [x for x in lst if isinstance(x, t)]


def gett1o(lst, t):
    lst = [x for x in lst if isinstance(x, t)]
    if len(lst) == 0:
        return None
    elif len(lst) == 1:
        return lst[0]
    else:
        raise RespError('Duplicate entry.')


def gett1(lst, t):
    lst = [x for x in lst if isinstance(x, t)]
    if len(lst) == 0:
        raise RespError('Entry not found.')
    elif len(lst) == 1:
        return lst[0]
    else:
        raise RespError('Duplicate entry.')


class ChannelResponse(guts.Object):
    '''
    Response information + channel codes and time span.
    '''

    codes = guts.Tuple.T(4, guts.String.T(default=''))
    start_date = guts.Timestamp.T()
    end_date = guts.Timestamp.T()
    response = sxml.Response.T()


def iload_fh(f):
    '''
    Read RESP information from open file handle.
    '''

    for sc, cc, rcs in parse3(f):
        nslc = (
            pcode(get1(sc, b'16')),
            pcode(get1(sc, b'03')),
            ploc(get1(cc, b'03', b'')),
            pcode(get1(cc, b'04')))

        try:
            tmin = pdate(get1(cc, b'22'))
            tmax = pdate(get1(cc, b'23'))
        except util.TimeStrError as e:
            raise RespError('Invalid date in RESP information (%s).' % str(e))

        stage_elements = {}

        istage = -1
        for block, content in rcs:
            if block not in bdefs:
                raise RespError('Unknown block type found: %s' % block)

            istage_temp, x = bdefs[block]['parse'](content)
            if istage_temp != -1:
                istage = istage_temp

            if x is None:
                continue

            x.validate()
            if istage not in stage_elements:
                stage_elements[istage] = []

            stage_elements[istage].append(x)

        istages = sorted(stage_elements.keys())
        stages = []
        totalgain = None
        for istage in istages:
            elements = stage_elements[istage]
            if istage == 0:
                totalgain = gett1(elements, sxml.Gain)
            else:
                stage = sxml.ResponseStage(
                    number=istage,
                    poles_zeros_list=gett(elements, sxml.PolesZeros),
                    coefficients_list=gett(elements, sxml.Coefficients),
                    fir=gett1o(elements, sxml.FIR),
                    decimation=gett1o(elements, sxml.Decimation),
                    stage_gain=gett1o(elements, sxml.Gain))

                stages.append(stage)

        if stages:
            resp = sxml.Response(
                stage_list=stages)

            if totalgain:
                totalgain_value = totalgain.value
                totalgain_frequency = totalgain.frequency

            else:
                totalgain_value = 1.
                gain_frequencies = []
                for stage in stages:
                    totalgain_value *= stage.stage_gain.value
                    gain_frequencies.append(stage.stage_gain.frequency)

                totalgain_frequency = gain_frequencies[0]

                if not all(f == totalgain_frequency for f in gain_frequencies):
                    logger.warning(
                        'No total gain reported and inconsistent gain '
                        'frequency values found in resp file for %s.%s.%s.%s: '
                        'omitting total gain and frequency from created '
                        'instrument sensitivity object.' % nslc)

                    totalgain_value = None
                    totalgain_frequency = None

            resp.instrument_sensitivity = sxml.Sensitivity(
                value=totalgain_value,
                frequency=totalgain_frequency,
                input_units=stages[0].input_units,
                output_units=stages[-1].output_units)

            yield ChannelResponse(
                codes=nslc,
                start_date=tmin,
                end_date=tmax,
                response=resp)

        else:
            logger.warning(
                'Incomplete response information for %s (%s - %s).',
                '.'.join(nslc),
                util.time_to_str(tmin),
                util.time_to_str(tmax))

            yield ChannelResponse(
                codes=nslc,
                start_date=tmin,
                end_date=tmax,
                response=None)


iload_filename, iload_dirname, iload_glob, iload = util.make_iload_family(
    iload_fh, 'RESP', ':py:class:`ChannelResponse`')


def make_stationxml(pyrocko_stations, channel_responses):
    '''
    Create stationxml from pyrocko station list and RESP information.

    :param pyrocko_stations:
        Station information.
    :type pyrocko_stations:
        :py:class:`list` of :py:class:`pyrocko.model.station.Station`

    :param channel_responses:
        iterable yielding :py:class:`ChannelResponse` objects

    :returns: :py:class:`pyrocko.io.stationxml.FDSNStationXML` object with
        merged information

    If no station information is available for any response information, it
    is skipped and a warning is emitted.
    '''
    pstations = dict((s.nsl(), s) for s in pyrocko_stations)
    networks = {}
    stations = {}
    for (net, sta, loc) in sorted(pstations.keys()):
        pstation = pstations[net, sta, loc]
        if net not in networks:
            networks[net] = sxml.Network(code=net)

        if (net, sta) not in stations:
            stations[net, sta] = sxml.Station(
                code=sta,
                latitude=sxml.Latitude(pstation.lat),
                longitude=sxml.Longitude(pstation.lon),
                elevation=sxml.Distance(pstation.elevation))

            networks[net].station_list.append(stations[net, sta])

    for cr in channel_responses:
        net, sta, loc, cha = cr.codes
        if (net, sta, loc) in pstations:
            pstation = pstations[net, sta, loc]
            pchannel = pstation.get_channel(cha)
            extra = {}
            if pchannel is not None:
                if pchannel.azimuth is not None:
                    extra['azimuth'] = sxml.Azimuth(pchannel.azimuth)

                if pchannel.dip is not None:
                    extra['dip'] = sxml.Dip(pchannel.dip)

            channel = sxml.Channel(
                code=cha,
                location_code=loc,
                start_date=cr.start_date,
                end_date=cr.end_date,
                latitude=sxml.Latitude(pstation.lat),
                longitude=sxml.Longitude(pstation.lon),
                elevation=sxml.Distance(pstation.elevation),
                depth=sxml.Distance(pstation.depth),
                response=cr.response,
                **extra)

            stations[net, sta].channel_list.append(channel)
        else:
            logger.warning('No station information for %s.%s.%s.' %
                           (net, sta, loc))

    for station in stations.values():
        station.channel_list.sort(key=lambda c: (c.location_code, c.code))

    return sxml.FDSNStationXML(
        source='Converted from Pyrocko stations file and RESP information',
        created=time.time(),
        network_list=[networks[net_] for net_ in sorted(networks.keys())])


if __name__ == '__main__':
    import sys
    from pyrocko.model.station import load_stations

    util.setup_logging(__name__)

    if len(sys.argv) < 2:
        sys.exit('usage: python -m pyrocko.io.resp <stations> <resp> ...')

    stations = load_stations(sys.argv[1])

    sxml = make_stationxml(stations, iload(sys.argv[2:]))

    print(sxml.dump_xml())
