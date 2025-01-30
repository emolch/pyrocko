# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`gato stack`.
'''
import sys
import numpy as num

from pyrocko.squirrel import SquirrelCommand, QuantityType
from pyrocko.guts import Object, Float, Bool, StringChoice

from pyrocko.gato.error import GatoToolError
from pyrocko.gato.array import SensorArrayAndInfoContext, \
    get_named_arrays_dataset

from pyrocko.gato.io import load

from pyrocko.gato.grid.base import Grid
from pyrocko.gato.grid.location import UnstructuredLocationGrid
from pyrocko.gato.delay import GenericDelayTable
from pyrocko.gato.delay.plane_wave import PlaneWaveDM
from pyrocko.gato.tool.common import add_array_selection_arguments, \
    get_matching_arrays

guts_prefix = 'gato'


class WindowChoice(StringChoice):
    choices = ['boxcar', 'hanning']


class CharacteristicFunctionConfig(Object):
    pass


class PreProcessingConfig(Object):

    downsample = Float.T(optional=True)

    quantity = QuantityType.T(optional=True)
    frequency_min = Float.T(optional=True)
    frequency_max = Float.T(optional=True)
    frequency_cut_factor = Float.T(optional=True)
    frequency_cut_min = Float.T(optional=True)
    frequency_cut_max = Float.T(optional=True)
    # instrument_correction_mode = \
    #     InstrumentCorrectionMode.T(default='complete')

    rotate_to_enz = Bool.T(default=False)

    highpass = Float.T(optional=True)
    lowpass = Float.T(optional=True)

    characteristic_function = CharacteristicFunctionConfig.T(optional=True)


def get_waveforms(self, sq, config, **kwargs):
    pass


def chopper_waveforms(self, sq, config, **kwargs):
    pass


def main():
    pass

    # sq.get_processed_waveforms(config, tmin=, tmax=)
    # sq.kget_processed_waveforms(sq, config, tmin=, tmax=)
    #


class StackingConfig(Object):
    time_increment = Float.T()
    time_padding = Float.T()
    source_grid = Grid.T()


class PostProcessingConfig(Object):
    time_smoothing = Float.T()
    time_smoothing_window = WindowChoice.T()


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
            dest='config_paths',
            nargs='+',
            metavar='CONFIG',
            help='Configuration files for geometry and waveform '
                 'preprocessing.')

    def run(self, parser, args):

        arrays = get_matching_arrays(
            args.array_names, args.array_paths, args.use_builtin_arrays)

        config = load(args.config_path, want=None)

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
                source_grid=config.source_grid,
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

                mtrace = batch.as_carpet(codes=info.codes)
                # delta_frequency, ntrans, spectrum =  mtrace.get_spectrum()
                mtrace.snuffle()
                sys.exit()

            print(array)
            print(config)


headline = 'Run stacking or beamforming algorithm.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'stack',
        help=headline,
        subcommands=[DelayAndSumTD()],
        description=headline)


def setup(parser):
    pass


def run(parser, args):
    parser.print_help()
