# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`gato beam`.
'''
import os
import sys
import numpy as num

from pyrocko.squirrel import SquirrelCommand
from pyrocko.guts import Object, Float, Bool

from pyrocko.gato.error import GatoToolError
from pyrocko.gato.array import SensorArrayAndInfoContext, \
    get_named_arrays_dataset

from pyrocko.gato.io import load
from pyrocko.gato.grid.slowness import SlownessGrid
from pyrocko.gato.grid.location import UnstructuredLocationGrid
from pyrocko.gato.delay import GenericDelayTable
from pyrocko.gato.delay.plane_wave import PlaneWaveDM
from pyrocko.gato.tool.common import add_array_selection_arguments, \
    get_matching_arrays

guts_prefix = 'gato'


class ProcOpts(Object):

    # filter options
    highpass = Float.T(optional=True)
    lowpass = Float.T(optional=True)
    transfer_removal = Bool.T(default=False)
    transfer_f1 = Float.T(default=0.001)
    transfer_f2 = Float.T(default=0.01)
    transfer_f3 = Float.T(default=100.)
    transfer_f4 = Float.T(default=200.)
    # window options
    tinc = Float.T(default=60.)
    winstep = Float.T(default=30.)
    # stack option
    stacklen = Float.T(default=86400.)
    # preprocessing options:
    taper = Float.T(default=0.2)
    prewhiten = Bool.T(default=False)
    slowness_grid = SlownessGrid.T()
    # to be continued ...


def get_matching_configuration(name_patterns):

    config_name = name_patterns[0]
    if config_name == 'teleseismic':
        config = 'teleseismic'
    elif config_name == 'regional':
        config = 'regional'
    elif config_name == 'local':
        config = 'local'
    elif (os.path.exists(config_name) and os.path.isfile(config_name)):
        config = read_config_from_file(config_name)
    else:
        config = None
    return config


def read_config_from_file(path):
    # parse yaml file
    print("==================", path)
    procopts = None
    procopts = load(filename=path)
    return procopts


class DelayAndSumTD(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'time-domain',
            help='Compute delay and sum operation in time domain.',
            description='Compute delay and sum operation in time domain.')

    def setup(self, parser):
        add_array_selection_arguments(parser)

        parser.add_squirrel_selection_arguments()
        parser.add_squirrel_query_arguments(without=['kinds'])

        parser.add_argument(
            dest='config_name',
            metavar='CONFIG',
            help='TODO: processing conf name or file name')

    def run(self, parser, args):

        arrays = get_matching_arrays(
            args.array_names, args.array_paths, args.use_builtin_arrays)

        config = load(args.config_name, want=ProcOpts)

        sq = args.make_squirrel()
        sq.add_dataset(get_named_arrays_dataset(sorted(arrays.keys())))

        downloads_enabled = False
        sq.downloads_enabled = downloads_enabled

        if not sq.have_waveforms(**args.squirrel_query):
            raise GatoToolError(
                'No waveforms available for given dataset configuration and '
                'query constraints.')

        tmin_data, tmax_data = sq.get_time_span(
            kinds=['waveform', 'waveform_promise'] if downloads_enabled
            else ['waveform'],
            dummy_limits=False)

        squirrel_query = dict(args.squirrel_query)

        if squirrel_query.get('tmin', None) is None:
            squirrel_query['tmin'] = tmin_data

        if squirrel_query.get('tmax', None) is None:
            squirrel_query['tmax'] = tmax_data

        for array in arrays.values():
            info = array.get_info(sq, **squirrel_query)

            if info.n_codes == 0:
                raise GatoToolError(
                    'No sensors match given combination of array definition '
                    'and available metadata. Context:\n'
                    + str(SensorArrayAndInfoContext(array=array, info=info)))

            receiver_grid = UnstructuredLocationGrid.from_locations(
                info.sensors, ignore_position_duplicates=False)

            gdt = GenericDelayTable(
                source_grid=config.slowness_grid,
                receiver_grid=receiver_grid,
                method=PlaneWaveDM())

            print(gdt)
            print(receiver_grid.coordinates)

            delays = gdt.get_delays()

            tpad_overlap = 0.
            tpad_delay = num.max(num.abs(delays))
            tpad_restitution = 2.0 / config.transfer_f2

            tpad = tpad_overlap + tpad_delay + tpad_restitution

            # overlap_fraction = 2*tpad / tinc
            for batch in sq.chopper_waveforms(
                    snap_window=True,
                    tinc=config.tinc,
                    tpad=tpad,
                    **args.squirrel_query):

                mtrace = batch.as_multitrace(codes=info.codes)
                mtrace.snuffle()
                sys.exit()

            print(array)
            print(config)


class DelayAndSumFD(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'frequency-domain',
            help='Compute delay and sum operation in frequency domain.',
            description='Compute delay and sum operation in frequency domain.')

    def setup(self, parser):
        parser.add_squirrel_selection_arguments()
        parser.add_squirrel_query_arguments(without=['kinds'])

        parser.add_argument(
            dest='array_name',
            metavar='NAME',
            help='TODO: array name or file name')

        parser.add_argument(
            dest='config_name',
            metavar='CONFIG',
            help='TODO: processing conf name or file name')

    def run(self, parser, args):
        pass


headline = 'Run beamforming.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'beam',
        help=headline,
        subcommands=[DelayAndSumTD(), DelayAndSumFD()],
        description=headline + '''

Apply beamforming algorithm in time or frequency domain.
''')


def setup(parser):
    pass


def run(parser, args):
    parser.print_help()
