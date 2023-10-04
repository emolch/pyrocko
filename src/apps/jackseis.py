# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Jackseis - manipulate seismic waveform archives.
'''

import sys
import re
import os
import logging
import signal
import math
from copy import copy
from optparse import OptionParser, Option, OptionValueError

import numpy as num

from pyrocko import util, config, pile, model, io, trace
from pyrocko.io import stationxml

pjoin = os.path.join

logger = logging.getLogger('pyrocko.apps.jackseis')

program_name = 'jackseis'

usage = program_name + ' <inputs> ... [options]'

description = '''A simple tool to manipulate waveform archive data.'''

tfmt = 'YYYY-mm-dd HH:MM:SS[.xxx]'
tts = util.time_to_str
stt = util.str_to_time_fillup


def die(message):
    sys.exit('%s: error: %s' % (program_name, message))


name_to_dtype = {
    'int32': num.int32,
    'int64': num.int64,
    'float32': num.float32,
    'float64': num.float64}


output_units = {
    'acceleration': 'M/S**2',
    'velocity': 'M/S',
    'displacement': 'M'}


def str_to_seconds(s):
    if s.endswith('s'):
        return float(s[:-1])
    elif s.endswith('m'):
        return float(s[:-1])*60.
    elif s.endswith('h'):
        return float(s[:-1])*3600.
    elif s.endswith('d'):
        return float(s[:-1])*3600.*24.
    else:
        return float(s)


def nice_seconds_floor(s):
    nice = [1., 10., 60., 600., 3600., 3.*3600., 12*3600., 24*3600., 48*3600.]
    p = s
    for x in nice:
        if s < x:
            return p

        p = x

    return s


def check_record_length(option, opt, value):
    try:
        reclen = int(value)
        if reclen in io.mseed.VALID_RECORD_LENGTHS:
            return reclen
    except Exception:
        pass
    raise OptionValueError(
        'invalid record length %s. (choose from %s)'
        % (reclen, ', '.join(str(b) for b in io.mseed.VALID_RECORD_LENGTHS)))


def check_steim(option, opt, value):
    try:
        compression = int(value)
        if compression in (1, 2):
            return compression
    except Exception:
        pass
    raise OptionValueError(
        'invalid STEIM compression %s. (choose from 1, 2)' % compression)


class JackseisOptions(Option):
    TYPES = Option.TYPES + ('record_length', 'steim')
    TYPE_CHECKER = copy(Option.TYPE_CHECKER)
    TYPE_CHECKER['record_length'] = check_record_length
    TYPE_CHECKER['steim'] = check_steim


def process(get_pile, options):
    tinc = None
    if options.tinc is not None:
        if tinc in ('huge', 'auto'):
            tinc = options.tinc
        else:
            try:
                tinc = str_to_seconds(options.tinc)
            except Exception:
                die('invalid argument to --tinc')

    tmin = None
    if options.tmin is not None:
        try:
            tmin = stt(options.tmin)
        except Exception:
            die('invalid argument to --tmin. '
                'Expected format is "%s" % tfmt')

    tmax = None
    if options.tmax is not None:
        try:
            tmax = stt(options.tmax)
        except Exception:
            die('invalid argument to --tmax. '
                'Expected format is "%s"' % tfmt)

    target_deltat = None
    if options.downsample is not None:
        try:
            target_deltat = 1.0 / float(options.downsample)
        except Exception:
            die('invalid argument to --downsample')

    replacements = []
    for k, rename_k, in [
            ('network', options.rename_network),
            ('station', options.rename_station),
            ('location', options.rename_location),
            ('channel', options.rename_channel)]:

        for patrep in rename_k:
            m = re.match(r'/([^/]+)/([^/]*)/', patrep)
            if not m:
                die('invalid argument to --rename-%s. '
                    'Expected format is /PATTERN/REPLACEMENT/' % k)

            replacements.append((k, m.group(1), m.group(2)))

    sx = None
    if options.station_xml_fns:
        sxs = []
        for station_xml_fn in options.station_xml_fns:
            sxs.append(stationxml.load_xml(filename=station_xml_fn))

        sx = stationxml.primitive_merge(sxs)

    events = []
    for event_fn in options.event_fns:
        events.extend(model.load_events(event_fn))

    p = get_pile()

    if p.tmin is None:
        die('data selection is empty')

    if tinc == 'auto':
        tinc = nice_seconds_floor(p.get_deltatmin() * 1000000.)

    if options.snap:
        if tmin is None:
            tmin = p.tmin

        if tinc is not None:
            tmin = int(math.floor(tmin / tinc)) * tinc

    output_path = options.output_path
    output_dir = options.output_dir

    if output_path and not output_dir and os.path.isdir(output_path):
        output_dir = output_path  # compat. with old behaviour

    if output_dir and not output_path:
        output_path = 'trace_%(network)s-%(station)s-' \
                      '%(location)s-%(channel)s_%(wmin)s.' + \
                      options.output_format

    if output_dir and output_path:
        output_path = pjoin(output_dir, output_path)

    if not output_path:
        die('--output not given')

    fmin, fmax = map(float, options.str_fmin_fmax.split(','))
    tfade_factor = 2.0
    ffade_factor = 1.5
    if options.output_quantity:
        tpad = 2*tfade_factor/fmin
    else:
        tpad = 0.

    if target_deltat is not None:
        tpad += target_deltat * 10.

    if tinc is None:
        if ((tmax or p.tmax) - (tmin or p.tmin)) \
                / p.get_deltatmin() > 100000000.:
            die('use --tinc=huge to really produce such large output files '
                'or use --tinc=INC to split into smaller files.')

    kwargs = dict(tmin=tmin, tmax=tmax, tinc=tinc, tpad=tpad, style='batch')

    if options.traversal == 'channel-by-channel':
        it = p.chopper_grouped(gather=lambda tr: tr.nslc_id, **kwargs)

    elif options.traversal == 'station-by-station':
        it = p.chopper_grouped(gather=lambda tr: tr.nslc_id[:2], **kwargs)

    else:
        it = p.chopper(**kwargs)

    abort = []

    def got_sigint(signum, frame):
        abort.append(True)

    old = signal.signal(signal.SIGINT, got_sigint)

    save_kwargs = {}
    if options.output_format == 'mseed':
        save_kwargs['record_length'] = options.record_length
        save_kwargs['steim'] = options.steim

    def process_traces(batch):
        traces = batch.traces
        if traces:
            twmin = batch.tmin
            twmax = batch.tmax
            logger.info('processing %s - %s, %i traces' %
                        (tts(twmin), tts(twmax), len(traces)))

            if options.sample_snap:
                for tr in traces:
                    tr.snap(interpolate=options.sample_snap == 'interpolate')

            if target_deltat is not None:
                out_traces = []
                for tr in traces:
                    try:
                        tr.downsample_to(
                            target_deltat,
                            snap=True,
                            demean=False,
                            allow_upsample_max=4)

                        if options.output_data_type == 'same':
                            tr.ydata = tr.ydata.astype(tr.ydata.dtype)

                        out_traces.append(tr)

                    except (trace.TraceTooShort, trace.NoData):
                        pass

                traces = out_traces

            if options.output_quantity:
                out_traces = []
                tfade = tfade_factor / fmin
                ftap = (fmin / ffade_factor, fmin, fmax, ffade_factor * fmax)
                for tr in traces:
                    try:
                        response = sx.get_pyrocko_response(
                            tr.nslc_id,
                            timespan=(tr.tmin, tr.tmax),
                            fake_input_units=output_units[
                                options.output_quantity])

                        rest_tr = tr.transfer(
                            tfade, ftap, response, invert=True, demean=True)

                        out_traces.append(rest_tr)

                    except stationxml.NoResponseInformation as e:
                        logger.warning(
                            'Cannot restitute: %s (no response)' % str(e))

                    except stationxml.MultipleResponseInformation as e:
                        logger.warning(
                            'Cannot restitute: %s (multiple responses found)'
                            % str(e))

                    except (trace.TraceTooShort, trace.NoData):
                        logger.warning(
                            'Trace too short: %s' % '.'.join(tr.nslc_id))

                traces = out_traces

            if options.scale is not None:
                for tr in traces:
                    tr.ydata = options.scale * tr.ydata

            if options.output_data_type != 'same':
                for tr in traces:
                    tr.ydata = tr.ydata.astype(
                        name_to_dtype[options.output_data_type])

            if replacements:
                for tr in traces:
                    r = {}
                    for k, pat, repl in replacements:
                        oldval = getattr(tr, k)
                        newval, n = re.subn(pat, repl, oldval)
                        if n:
                            r[k] = newval

                    tr.set_codes(**r)

            if output_path:
                otraces = []
                for tr in traces:
                    try:
                        otr = tr.chop(twmin, twmax, inplace=False)
                        otraces.append(otr)
                    except trace.NoData:
                        pass

                try:
                    io.save(otraces, output_path, format=options.output_format,
                            overwrite=options.force,
                            additional=dict(
                                wmin_year=tts(twmin, format='%Y'),
                                wmin_month=tts(twmin, format='%m'),
                                wmin_day=tts(twmin, format='%d'),
                                wmin_jday=tts(twmin, format='%j'),
                                wmin=tts(twmin, format='%Y-%m-%d_%H-%M-%S'),
                                wmax_year=tts(twmax, format='%Y'),
                                wmax_month=tts(twmax, format='%m'),
                                wmax_day=tts(twmax, format='%d'),
                                wmax_jday=tts(twmax, format='%j'),
                                wmax=tts(twmax, format='%Y-%m-%d_%H-%M-%S')),
                            **save_kwargs)
                except io.FileSaveError as e:
                    die(str(e))

    for batch in it:
        process_traces(batch)
        if abort:
            break

    signal.signal(signal.SIGINT, old)

    if abort:
        die('interrupted.')


def main(args=None):
    '''
    CLI entry point for Pyrocko's ``jackseis`` app.
    '''
    if args is None:
        args = sys.argv[1:]

    parser = OptionParser(
        usage=usage,
        description=description,
        option_class=JackseisOptions,
        formatter=util.BetterHelpFormatter())

    parser.add_option(
        '--format',
        dest='format',
        default='detect',
        choices=io.allowed_formats('load'),
        help='assume input files are of given FORMAT. Choices: %s' %
             io.allowed_formats('load', 'cli_help', 'detect'))

    parser.add_option(
        '--pattern',
        dest='regex',
        metavar='REGEX',
        help='only include files whose paths match REGEX')

    parser.add_option(
        '--stationxml',
        dest='station_xml_fns',
        action='append',
        default=[],
        metavar='STATIONXML',
        help='read station metadata from file STATIONXML')

    parser.add_option(
        '--event', '--events',
        dest='event_fns',
        action='append',
        default=[],
        metavar='EVENT',
        help='read event information from file EVENT')

    parser.add_option(
        '--cache',
        dest='cache_dir',
        default=config.config().cache_dir,
        metavar='DIR',
        help='use directory DIR to cache trace metadata '
             "(default='%default')")

    parser.add_option(
        '--quiet',
        dest='quiet',
        action='store_true',
        default=False,
        help='disable output of progress information')

    parser.add_option(
        '--debug',
        dest='debug',
        action='store_true',
        default=False,
        help='print debugging information to stderr')

    parser.add_option(
        '--tmin',
        dest='tmin',
        help='start time as "%s"' % tfmt)

    parser.add_option(
        '--tmax',
        dest='tmax',
        help='end time as "%s"' % tfmt)

    parser.add_option(
        '--tinc',
        dest='tinc',
        help='set time length of output files [s] or "auto" to automatically '
             'choose an appropriate time increment or "huge" to allow to use '
             'a lot of system memory to merge input traces into huge output '
             'files.')

    parser.add_option(
        '--downsample',
        dest='downsample',
        metavar='RATE',
        help='downsample to RATE [Hz]')

    parser.add_option(
        '--scale',
        dest='scale',
        type=float,
        metavar='FACTOR',
        help='scale seismograms with given FACTOR. Changes data type to '
             'float64. Use --output-data-type to change again after scaling.')

    parser.add_option(
        '--output',
        dest='output_path',
        metavar='TEMPLATE',
        help='set output path to TEMPLATE. Available placeholders '
             'are %n: network, %s: station, %l: location, %c: channel, '
             '%b: begin time, %e: end time, %j: julian day of year. The '
             'following additional placeholders use the window begin and end '
             'times rather than trace begin and end times (to suppress '
             'producing many small files for gappy traces), %(wmin_year)s, '
             '%(wmin_month)s, %(wmin_day)s, %(wmin)s, %(wmin_jday)s, '
             '%(wmax_year)s, %(wmax_month)s, %(wmax_day)s, %(wmax)s, '
             "%(wmax_jday)s. Example: --output='data/%s/trace-%s-%c.mseed'")

    parser.add_option(
        '--output-dir',
        metavar='TEMPLATE',
        dest='output_dir',
        help='set output directory to TEMPLATE (see --output for details) '
             'and automatically choose filenames. '
             'Produces files like TEMPLATE/NET-STA-LOC-CHA_BEGINTIME.FORMAT')

    parser.add_option(
        '--output-format',
        dest='output_format',
        default='mseed',
        choices=io.allowed_formats('save'),
        help='set output file format. Choices: %s' %
             io.allowed_formats('save', 'cli_help', 'mseed'))

    parser.add_option(
        '--force',
        dest='force',
        action='store_true',
        default=False,
        help='force overwriting of existing files')

    parser.add_option(
        '--no-snap',
        dest='snap',
        action='store_false',
        default=True,
        help='do not start output files at even multiples of file length')

    parser.add_option(
        '--traversal',
        dest='traversal',
        choices=('station-by-station', 'channel-by-channel', 'chronological'),
        default='station-by-station',
        help='set traversal order for traces processing. '
             "Choices are 'station-by-station' [default], "
             "'channel-by-channel', and 'chronological'. Chronological "
             'traversal uses more processing memory but makes it possible to '
             'join multiple stations into single output files')

    parser.add_option(
        '--rename-network',
        action='append',
        default=[],
        dest='rename_network',
        metavar='/PATTERN/REPLACEMENT/',
        help='update network code, can be given more than once')

    parser.add_option(
        '--rename-station',
        action='append',
        default=[],
        dest='rename_station',
        metavar='/PATTERN/REPLACEMENT/',
        help='update station code, can be given more than once')

    parser.add_option(
        '--rename-location',
        action='append',
        default=[],
        dest='rename_location',
        metavar='/PATTERN/REPLACEMENT/',
        help='update location code, can be given more than once')

    parser.add_option(
        '--rename-channel',
        action='append',
        default=[],
        dest='rename_channel',
        metavar='/PATTERN/REPLACEMENT/',
        help='update channel code, can be given more than once')

    parser.add_option(
        '--output-data-type',
        dest='output_data_type',
        choices=('same', 'int32', 'int64', 'float32', 'float64'),
        default='same',
        metavar='DTYPE',
        help='set data type. Choices: same [default], int32, '
             'int64, float32, float64. The output file format must support '
             'the given type.')

    parser.add_option(
        '--output-steim',
        dest='steim',
        type='steim',
        default=2,
        metavar='STEIM_COMPRESSION',
        help='set the mseed STEIM compression. Choices: 1 or 2. '
             'Default is STEIM-2, which can compress full range int32. '
             'NOTE: STEIM-2 is limited to 30 bit dynamic range.')

    parser.add_option(
        '--output-record-length',
        dest='record_length',
        type='record_length',
        default=4096,
        metavar='RECORD_LENGTH',
        help='set the mseed record length in bytes. Choices: %s. '
             'Default is 4096 bytes, which is commonly used for archiving.'
             % ', '.join(str(b) for b in io.mseed.VALID_RECORD_LENGTHS))

    quantity_choices = ('acceleration', 'velocity', 'displacement')
    parser.add_option(
        '--output-quantity',
        dest='output_quantity',
        choices=quantity_choices,
        help='deconvolve instrument transfer function. Choices: %s'
        % ', '.join(quantity_choices))

    parser.add_option(
        '--restitution-frequency-band',
        default='0.001,100.0',
        dest='str_fmin_fmax',
        metavar='FMIN,FMAX',
        help='frequency band for instrument deconvolution as FMIN,FMAX in Hz. '
        'Default: "%default"')

    sample_snap_choices = ('shift', 'interpolate')
    parser.add_option(
        '--sample-snap',
        dest='sample_snap',
        choices=sample_snap_choices,
        help='shift/interpolate traces so that samples are at even multiples '
        'of sampling rate. Choices: %s' % ', '.join(sample_snap_choices))

    (options, args) = parser.parse_args(args)

    if len(args) == 0:
        parser.print_help()
        sys.exit(1)

    if options.debug:
        util.setup_logging(program_name, 'debug')
    elif options.quiet:
        util.setup_logging(program_name, 'warning')
    else:
        util.setup_logging(program_name, 'info')

    def get_pile():
        return pile.make_pile(
            paths=args,
            selector=None,
            regex=options.regex,
            fileformat=options.format,
            cachedirname=options.cache_dir,
            show_progress=not options.quiet)

    return process(get_pile, options)


if __name__ == '__main__':
    main()
