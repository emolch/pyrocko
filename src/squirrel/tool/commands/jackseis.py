# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel jackseis`.
'''

import re
import sys
import logging
import os.path as op

import numpy as num

from pyrocko import io, trace, util
from pyrocko import progress
from pyrocko.has_paths import Path, HasPaths
from pyrocko.guts import Dict, String, Choice, Float, Bool, List, Timestamp, \
    StringChoice, IntChoice, Defer, load_all, clone
from pyrocko.squirrel.dataset import Dataset
from pyrocko.squirrel.client.local import LocalData
from pyrocko.squirrel.error import ToolError, SquirrelError
from pyrocko.squirrel.model import CodesNSLCE, QuantityType
from pyrocko.squirrel.operators.base import NetworkGrouping, StationGrouping, \
    ChannelGrouping, SensorGrouping
from pyrocko.squirrel.tool.common import ldq

tts = util.time_to_str

guts_prefix = 'jackseis'
logger = logging.getLogger('psq.cli.jackseis')


g_filenames_all = set()


def check_append_hook(fn):
    return fn in g_filenames_all


def dset(kwargs, keys, values):
    for k, v in zip(keys, values):
        kwargs[k] = v


def make_task(*args):
    return progress.task(*args, logger=logger)


def parse_rename_rule_from_string(s):
    s = s.strip()
    if re.match(r'^([^:,]*:[^:,]*,?)+', s):
        return dict(
            x.split(':') for x in s.strip(',').split(','))
    else:
        return s


class JackseisError(ToolError):
    pass


class Chain(object):
    def __init__(self, node, parent=None):
        self.node = node
        self.parent = parent

    def mcall(self, name, *args, **kwargs):
        ret = []
        if self.parent is not None:
            ret.append(self.parent.mcall(name, *args, **kwargs))

        ret.append(getattr(self.node, name)(*args, **kwargs))
        return ret

    def fcall(self, name, *args, **kwargs):
        v = getattr(self.node, name)(*args, **kwargs)
        if v is None and self.parent is not None:
            return self.parent.fcall(name, *args, **kwargs)
        else:
            return v

    def get(self, name):
        v = getattr(self.node, name)
        if v is None and self.parent is not None:
            return self.parent.get(name)
        else:
            return v

    def dget(self, name, k):
        v = getattr(self.node, name).get(k, None)
        if v is None and self.parent is not None:
            return self.parent.dget(name, k)
        else:
            return v


class OutputFormatChoice(StringChoice):
    choices = io.allowed_formats('save')


class OutputDataTypeChoice(StringChoice):
    choices = ['int32', 'int64', 'float32', 'float64']
    name_to_dtype = {
        'int32': num.int32,
        'int64': num.int64,
        'float32': num.float32,
        'float64': num.float64}


class TraversalChoice(StringChoice):
    choices = ['network', 'station', 'channel', 'sensor']
    name_to_grouping = {
        'network': NetworkGrouping(),
        'station': StationGrouping(),
        'sensor': SensorGrouping(),
        'channel': ChannelGrouping()}


class InstrumentCorrectionMode(StringChoice):
    choices = ['complete', 'sensor']


class Converter(HasPaths):

    in_dataset = Dataset.T(optional=True)
    in_path = String.T(optional=True)
    in_paths = List.T(String.T(optional=True))

    codes = List.T(CodesNSLCE.T(), optional=True)

    rename = Dict.T(
        String.T(),
        Choice.T([
            String.T(),
            Dict.T(String.T(), String.T())]))
    tmin = Timestamp.T(optional=True)
    tmax = Timestamp.T(optional=True)
    tinc = Float.T(optional=True)

    downsample = Float.T(optional=True)

    quantity = QuantityType.T(optional=True)
    fmin = Float.T(optional=True)
    fmax = Float.T(optional=True)
    fcut_factor = Float.T(optional=True)
    fmin_cut = Float.T(optional=True)
    fmax_cut = Float.T(optional=True)
    instrument_correction_mode = InstrumentCorrectionMode.T(
        default='complete')

    rotate_to_enz = Bool.T(default=False)

    out_path = Path.T(optional=True)
    out_sds_path = Path.T(optional=True)
    out_format = OutputFormatChoice.T(optional=True)
    out_data_type = OutputDataTypeChoice.T(optional=True)
    out_mseed_record_length = IntChoice.T(
        optional=True,
        choices=list(io.mseed.VALID_RECORD_LENGTHS))
    out_mseed_steim = IntChoice.T(
        optional=True,
        choices=[1, 2])
    out_meta_path = Path.T(optional=True)

    traversal = TraversalChoice.T(optional=True)

    parts = List.T(Defer('Converter.T'))

    def get_effective_frequency_taper(self, chain):
        fmin = chain.get('fmin')
        fmax = chain.get('fmax')

        if None in (fmin, fmax):
            if fmin is not None:
                raise JackseisError('Converter: fmax not specified.')
            if fmax is not None:
                raise JackseisError('Converter: fmin not specified.')

            return None

        fcut_factor = chain.get('fcut_factor') or 2.0
        fmin_cut = chain.get('fmin_cut')
        fmax_cut = chain.get('fmax_cut')
        fmin_cut = fmin_cut if fmin_cut is not None else fmin / fcut_factor
        fmax_cut = fmax_cut if fmax_cut is not None else fmax * fcut_factor

        return fmin_cut, fmin, fmax, fmax_cut

    @classmethod
    def add_arguments(cls, p):
        p.add_squirrel_query_arguments(without=['time'])

        p.add_argument(
            '--tinc',
            dest='tinc',
            type=float,
            metavar='SECONDS',
            help='Set time length of output files [s].')

        p.add_argument(
            '--downsample',
            dest='downsample',
            type=float,
            metavar='RATE',
            help='Downsample to RATE [Hz].')

        p.add_argument(
            '--quantity',
            dest='quantity',
            metavar='QUANTITY',
            choices=QuantityType.choices,
            help='''
Restitute waveforms to selected ``QUANTITY``. Restitution is performed by
multiplying the waveform spectra with a tapered inverse of the instrument
response transfer function. The frequency band of the taper can be adjusted
using the ``--band`` option. Choices: %s.
'''.strip() % ldq(QuantityType.choices))

        p.add_argument(
            '--band',
            metavar='FMIN,FMAX or FMIN,FMAX,CUTFACTOR or '
                    'FMINCUT,FMIN,FMAX,FMAXCUT',
            help='''
Frequency band used in restitution (see ``--quantity``) or for (acausal)
filtering. Waveform spectra are multiplied with a taper with cosine-shaped
flanks and which is flat between ``FMIN`` and ``FMAX``. The flanks of the taper
drop to zero at ``FMINCUT`` and ``FMAXCUT``. If ``CUTFACTOR`` is given,
``FMINCUT`` and ``FMAXCUT`` are set to ``FMIN/CUTFACTOR`` and
``FMAX*CUTFACTOR`` respectively. ``CUTFACTOR`` defaults to 2.
'''.strip())

        p.add_argument(
            '--instrument-correction-mode',
            dest='instrument_correction_mode',
            choices=['complete', 'sensor'],
            default='complete',
            help='''
Select mode of the instrument correction when performing a restition with
``--quantity``. This option selects which stages of the instrument response
should be considered completely, i.e. including their frequency dependence, and
which stages should be considered by only considering their overall gain
factor. Choices: ``complete`` -- all stages are considered completely
(default). ``sensor`` -- only the first stage of the insrument response is
treated completely. The first stage of the instrument response conventionally
represents the characteristics of the sensor and is usually given in poles and
zeros representation. The frequency response of the FIR filters of the
digitizer's downsampling stages are not considered in ``sensor`` mode. Instead,
replacement gain factors are computed by evaluating the frequency response of
the respective stages at the lower frequency bound of the restitution ``FMIN``
(see ``--band``). The assumption here is, that the decimation FIR filters are
flat at this frequency and representative for the whole pass band.
'''.strip())

        p.add_argument(
            '--rotate-to-enz',
            action='store_true',
            dest='rotate_to_enz',
            help='''
Rotate waveforms to east-north-vertical (ENZ) coordinate system. The samples
in the input data must be properly aligned and the channel orientations must
by set in the station metadata (StationXML). Output channels are renamed with
last letter replaced by ``E``, ``N``, and ``Z`` respectively.
'''.strip())

        p.add_argument(
            '--out-path',
            dest='out_path',
            metavar='TEMPLATE',
            help='''
Set output path to ``TEMPLATE``. Available placeholders are ``%%n``: network,
``%%s``: station, ``%%l``: location, ``%%c``: channel, ``%%b``: begin time,
``%%e``: end time, ``%%j``: julian day of year. The following additional
placeholders use the current processing window's begin and end times rather
than trace begin and end times (to suppress producing many small files for
gappy traces), ``%%(wmin_year)s``, ``%%(wmin_month)s``, ``%%(wmin_day)s``,
``%%(wmin)s``, ``%%(wmin_jday)s``, ``%%(wmax_year)s``, ``%%(wmax_month)s``,
``%%(wmax_day)s``, ``%%(wmax)s``, ``%%(wmax_jday)s``. Example: ``--out-path
'data/%%s/trace-%%s-%%c.mseed'``
'''.strip())

        p.add_argument(
            '--out-sds-path',
            dest='out_sds_path',
            metavar='PATH',
            help='''
Set output path to create an SDS archive
(https://www.seiscomp.de/seiscomp3/doc/applications/slarchive/SDS.html), rooted
at PATH. Implies ``--tinc 86400``. Example: ``--out-sds-path data/sds``
'''.strip())

        p.add_argument(
            '--out-format',
            dest='out_format',
            choices=io.allowed_formats('save'),
            metavar='FORMAT',
            help='Set output file format. Choices: %s' % io.allowed_formats(
                'save', 'cli_help', 'mseed'))

        p.add_argument(
            '--out-data-type',
            dest='out_data_type',
            choices=OutputDataTypeChoice.choices,
            metavar='DTYPE',
            help='Set numerical data type. Choices: %s. The output file '
                 'format must support the given type. By default, the data '
                 'type is kept unchanged.' % ldq(
                    OutputDataTypeChoice.choices))

        p.add_argument(
            '--out-mseed-record-length',
            dest='out_mseed_record_length',
            type=int,
            choices=io.mseed.VALID_RECORD_LENGTHS,
            metavar='INT',
            help='Set the Mini-SEED record length in bytes. Choices: %s. '
                 'Default is 4096 bytes, which is commonly used for archiving.'
                 % ldq(str(b) for b in io.mseed.VALID_RECORD_LENGTHS))

        p.add_argument(
            '--out-mseed-steim',
            dest='out_mseed_steim',
            type=int,
            choices=(1, 2),
            metavar='INT',
            help='Set the Mini-SEED STEIM compression. Choices: ``1`` or '
                 '``2``. Default is STEIM-2. Note: STEIM-2 is limited to 30 '
                 'bit dynamic range.')

        p.add_argument(
            '--out-meta-path',
            dest='out_meta_path',
            metavar='PATH',
            help='Set output path for station metadata (StationXML) export.')

        p.add_argument(
            '--traversal',
            dest='traversal',
            metavar='GROUPING',
            choices=TraversalChoice.choices,
            help='By default the outermost processing loop is over time. '
                 'Add outer loop with given GROUPING. Choices: %s'
                 % ldq(TraversalChoice.choices))

        p.add_argument(
            '--rename-network',
            dest='rename_network',
            metavar='REPLACEMENT',
            help="""
Replace network code. REPLACEMENT can be a string for direct replacement, a
mapping for selective replacement, or a regular expression for tricky
replacements. Examples: Direct replacement: ```XX``` - set all network codes to
```XX```. Mapping: ```AA:XX,BB:YY``` - replace ```AA``` with ```XX``` and
```BB``` with ```YY```. Regular expression: ```/A(\\d)/X\\1/``` - replace
```A1``` with ```X1``` and ```A2``` with ```X2``` etc.
""".strip())

        p.add_argument(
            '--rename-station',
            dest='rename_station',
            metavar='REPLACEMENT',
            help='Replace station code. See ``--rename-network``.')

        p.add_argument(
            '--rename-location',
            dest='rename_location',
            metavar='REPLACEMENT',
            help='Replace location code. See ``--rename-network``.')

        p.add_argument(
            '--rename-channel',
            dest='rename_channel',
            metavar='REPLACEMENT',
            help='Replace channel code. See ``--rename-network``.')

        p.add_argument(
            '--rename-extra',
            dest='rename_extra',
            metavar='REPLACEMENT',
            help='Replace extra code. See ``--rename-network``. Note: the '
                 '```extra``` code is not available in Mini-SEED.')

    @classmethod
    def from_arguments(cls, args):
        kwargs = args.squirrel_query

        rename = {}
        for (k, v) in [
                ('network', args.rename_network),
                ('station', args.rename_station),
                ('location', args.rename_location),
                ('channel', args.rename_channel),
                ('extra', args.rename_extra)]:

            if v is not None:
                rename[k] = parse_rename_rule_from_string(v)

        if args.band:
            try:
                values = list(map(float, args.band.split(',')))
                if len(values) not in (2, 3, 4):
                    raise ValueError()

                if len(values) == 2:
                    dset(kwargs, 'fmin fmax'.split(), values)
                elif len(values) == 3:
                    dset(kwargs, 'fmin fmax fcut_factor'.split(), values)
                elif len(values) == 4:
                    dset(kwargs, 'fmin_cut fmin fmax fmax_cut'.split(), values)

            except ValueError:
                raise JackseisError(
                    'Invalid argument to --band: %s' % args.band) from None

        obj = cls(
            downsample=args.downsample,
            quantity=args.quantity,
            instrument_correction_mode=args.instrument_correction_mode,
            rotate_to_enz=args.rotate_to_enz,
            out_format=args.out_format,
            out_path=args.out_path,
            tinc=args.tinc,
            out_sds_path=args.out_sds_path,
            out_data_type=args.out_data_type,
            out_mseed_record_length=args.out_mseed_record_length,
            out_mseed_steim=args.out_mseed_steim,
            out_meta_path=args.out_meta_path,
            traversal=args.traversal,
            rename=rename,
            **kwargs)

        obj.validate()
        return obj

    def add_dataset(self, sq):
        if self.in_dataset is not None:
            sq.add_dataset(self.in_dataset)

        if self.in_path is not None:
            ds = Dataset(sources=[LocalData(paths=[self.in_path])])
            ds.set_basepath_from(self)
            sq.add_dataset(ds)

        if self.in_paths:
            ds = Dataset(sources=[LocalData(paths=self.in_paths)])
            ds.set_basepath_from(self)
            sq.add_dataset(ds)

    def get_effective_rename_rules(self, chain):
        d = {}
        for k in ['network', 'station', 'location', 'channel']:
            v = chain.dget('rename', k)
            if isinstance(v, str):
                m = re.match(r'/([^/]+)/([^/]*)/', v)
                if m:
                    try:
                        v = (re.compile(m.group(1)), m.group(2))
                    except Exception:
                        raise JackseisError(
                            'Invalid replacement pattern: /%s/' % m.group(1))

            d[k] = v

        return d

    def get_effective_out_path(self):
        nset = sum(x is not None for x in (
            self.out_path,
            self.out_sds_path))

        if nset > 1:
            raise JackseisError(
                'More than one out of [out_path, out_sds_path] set.')

        is_sds = False
        if self.out_path:
            out_path = self.out_path

        elif self.out_sds_path:
            out_path = op.join(
                self.out_sds_path,
                '%(wmin_year)s/%(network_safe)s/%(station_safe)s/%(channel_safe)s.D'
                '/%(network_safe)s.%(station)s.%(location)s.%(channel)s.D'
                '.%(wmin_year)s.%(wmin_jday)s')
            is_sds = True
        else:
            out_path = None

        if out_path is not None:
            return self.expand_path(out_path), is_sds
        else:
            return None

    def get_effective_out_meta_path(self):
        if self.out_meta_path is not None:
            return self.expand_path(self.out_meta_path)
        else:
            return None

    def do_rename(self, rules, tr):
        rename = {}
        for k in ['network', 'station', 'location', 'channel']:
            v = rules.get(k, None)
            if isinstance(v, str):
                rename[k] = v
            elif isinstance(v, dict):
                try:
                    oldval = getattr(tr, k)
                    rename[k] = v[oldval]
                except KeyError:
                    raise ToolError(
                        'No mapping defined for %s code "%s".' % (k, oldval))

            elif isinstance(v, tuple):
                pat, repl = v
                oldval = getattr(tr, k)
                newval, n = pat.subn(repl, oldval)
                if n:
                    rename[k] = newval

        tr.set_codes(**rename)

    def convert(self, args, chain=None):
        if chain is None:
            defaults = clone(g_defaults)
            defaults.set_basepath_from(self)
            chain = Chain(defaults)

        chain = Chain(self, chain)

        if self.parts:
            task = make_task('Jackseis parts')
            for part in task(self.parts):
                part.convert(args, chain)

            del task

        else:
            sq = args.make_squirrel()

            cli_overrides = Converter.from_arguments(args)
            cli_overrides.set_basepath('.')

            chain = Chain(cli_overrides, chain)

            chain.mcall('add_dataset', sq)

            tmin = chain.get('tmin')
            tmax = chain.get('tmax')
            tinc = chain.get('tinc')
            codes = chain.get('codes')
            downsample = chain.get('downsample')
            rotate_to_enz = chain.get('rotate_to_enz')
            out_path, is_sds = chain.fcall('get_effective_out_path') \
                or (None, False)

            if is_sds:
                if tinc is None:
                    logger.warning(
                        'Setting time window to 1 hour to generate SDS.')
                    tinc = 3600.0

                else:
                    eps = 1e-6
                    if (86400.0+eps) % tinc > 2.*eps:
                        raise JackseisError(
                            'Day length is not a multiple of the time '
                            'window (--tinc).')

            out_format = chain.get('out_format')
            out_data_type = chain.get('out_data_type')

            out_meta_path = chain.fcall('get_effective_out_meta_path')

            if out_meta_path is not None:
                sx = sq.get_stationxml(codes=codes, tmin=tmin, tmax=tmax)
                util.ensuredirs(out_meta_path)
                sx.dump_xml(filename=out_meta_path)
                if out_path is None:
                    return

            target_deltat = None
            if downsample is not None:
                target_deltat = 1.0 / float(downsample)

            save_kwargs = {}
            if out_format == 'mseed':
                save_kwargs['record_length'] = chain.get(
                    'out_mseed_record_length')
                save_kwargs['steim'] = chain.get(
                    'out_mseed_steim')

            traversal = chain.get('traversal')
            if traversal is not None:
                grouping = TraversalChoice.name_to_grouping[traversal]
            else:
                grouping = None

            frequency_taper = self.get_effective_frequency_taper(chain)

            if frequency_taper is not None:
                if frequency_taper[0] != 0.0:
                    frequency_taper_tpad = 1.0 / frequency_taper[0]
                else:
                    if frequency_taper[1] == 0.0:
                        raise JackseisError(
                            'Converter: fmin must be greater than zero.')

                    frequency_taper_tpad = 2.0 / frequency_taper[1]
            else:
                frequency_taper_tpad = 0.0

            quantity = chain.get('quantity')
            ic_mode = chain.get('instrument_correction_mode')

            do_transfer = \
                quantity is not None or frequency_taper is not None

            tpad = 0.0
            if target_deltat is not None:
                tpad += target_deltat * 50.

            if do_transfer:
                tpad += frequency_taper_tpad

            task = None
            rename_rules = self.get_effective_rename_rules(chain)
            for batch in sq.chopper_waveforms(
                    tmin=tmin, tmax=tmax, tpad=tpad, tinc=tinc,
                    codes=codes,
                    snap_window=True,
                    grouping=grouping):

                if task is None:
                    task = make_task(
                        'Jackseis blocks', batch.n * batch.ngroups)

                tlabel = '%s%s - %s' % (
                    'groups %i / %i: ' % (batch.igroup, batch.ngroups)
                    if batch.ngroups > 1 else '',
                    util.time_to_str(batch.tmin),
                    util.time_to_str(batch.tmax))

                task.update(batch.i + batch.igroup * batch.n, tlabel)

                twmin = batch.tmin
                twmax = batch.tmax

                traces = batch.traces

                if target_deltat is not None:
                    downsampled_traces = []
                    for tr in traces:
                        try:
                            tr.downsample_to(
                                target_deltat, snap=True, demean=False,
                                allow_upsample_max=4)

                            downsampled_traces.append(tr)

                        except (trace.TraceTooShort, trace.NoData) as e:
                            logger.warning(str(e))

                    traces = downsampled_traces

                if do_transfer:
                    restituted_traces = []
                    for tr in traces:
                        try:
                            if quantity is not None:
                                resp = sq.get_response(tr).get_effective(
                                    input_quantity=quantity,
                                    mode=ic_mode,
                                    gain_frequency=frequency_taper[1])
                            else:
                                resp = None

                            restituted_traces.append(tr.transfer(
                                frequency_taper_tpad,
                                frequency_taper,
                                transfer_function=resp,
                                invert=True))

                        except (trace.NoData, trace.TraceTooShort,
                                SquirrelError) as e:
                            logger.warning(str(e))

                    traces = restituted_traces

                if rotate_to_enz:
                    sensors = sq.get_sensors(
                        tmin=twmin,
                        tmax=twmax,
                        codes=list(set(tr.codes for tr in traces)))

                    rotated_traces = []
                    for sensor in sensors:
                        sensor_traces = [
                            tr for tr in traces
                            if tr.codes.matches(sensor.codes)]

                        rotated_traces.extend(
                            sensor.project_to_enz(sensor_traces))

                    traces = rotated_traces

                for tr in traces:
                    self.do_rename(rename_rules, tr)

                if out_data_type:
                    for tr in traces:
                        tr.ydata = tr.ydata.astype(
                            OutputDataTypeChoice.name_to_dtype[out_data_type])

                chopped_traces = []
                for tr in traces:
                    try:
                        otr = tr.chop(twmin, twmax, inplace=False)
                        chopped_traces.append(otr)
                    except trace.NoData:
                        pass

                traces = chopped_traces

                if out_path is not None:
                    try:

                        g_filenames_all.update(io.save(
                            traces, out_path,
                            format=out_format,
                            overwrite=args.force,
                            append=True,
                            check_append=True,
                            check_append_hook=check_append_hook
                            if not args.append else None,
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
                            **save_kwargs))

                    except io.FileSaveError as e:
                        raise JackseisError(str(e))

                else:
                    for tr in traces:
                        print(tr.summary_stats)

            if task:
                task.done()


g_defaults = Converter(
    out_mseed_record_length=4096,
    out_format='mseed',
    out_mseed_steim=2)


headline = 'Convert waveform archive data.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'jackseis',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()

    parser.add_argument(
        '--config',
        dest='config_path',
        metavar='NAME',
        help='File containing `jackseis.Converter` settings.')

    parser.add_argument(
        '--dump-config',
        dest='dump_config',
        action='store_true',
        default=False,
        help='''
Print configuration file snippet representing given command line arguments to
standard output and exit. Only command line options affecting the conversion
are included in the dump. Additional ``--config`` settings, data collection and
data query options are ignored.
'''.strip())

    parser.add_argument(
        '--force',
        dest='force',
        action='store_true',
        default=False,
        help='Force overwriting of existing files.')

    parser.add_argument(
        '--append',
        dest='append',
        action='store_true',
        default=False,
        help='Append to existing files. This only works for mseed files. '
             'Checks are preformed to ensure that appended traces have no '
             'overlap with already existing traces.')

    Converter.add_arguments(parser)


def run(parser, args):
    if args.dump_config:
        converter = Converter.from_arguments(args)
        print(converter)
        sys.exit(0)

    if args.config_path:
        try:
            converters = load_all(filename=args.config_path)
        except Exception as e:
            raise ToolError(str(e))

        for converter in converters:
            if not isinstance(converter, Converter):
                raise ToolError(
                    'Config file should only contain '
                    '`jackseis.Converter` objects.')

            converter.set_basepath(op.dirname(args.config_path))

    else:
        converter = Converter()
        converter.set_basepath('.')
        converters = [converter]

    with progress.view():
        task = make_task('Jackseis jobs')
        for converter in task(converters):
            converter.convert(args)
