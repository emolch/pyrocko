# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel spectrogram`.
'''

import os
import logging


from pyrocko import progress, util
from pyrocko.squirrel.error import ToolError

logger = logging.getLogger('psq.cli.summon')

headline = 'Calculate multi-resolution spectrograms.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'spectrogram',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments()

    parser.add_argument(
        '--block-size-exponent',
        dest='nblock_exponent',
        type=int,
        metavar='INT',
        default=10,
        help='Set block size used to calculate FFTs as a power-of-two '
             'exponent. Default: 10 (2**10 = 1024).')

    parser.add_argument(
        '--levels',
        dest='nlevels',
        type=int,
        metavar='INT',
        default=9,
        help='Set number of levels for the multi-resolution spectrograms.')

    parser.add_argument(
        '--weighting-exponent',
        dest='weighting_exponent',
        type=int,
        metavar='INT',
        default=4,
        help='Set exponent for the the weighting function which is used to '
             'merge the multi-resolution spectrogram components.')

    parser.add_argument(
        '--tinc',
        dest='tinc',
        type=float,
        metavar='SECONDS',
        default=3600.,
        help='Set time length of output files [s].')

    parser.add_argument(
        '--show-construction',
        dest='show_construction',
        action='store_true',
        default=False,
        help='Show multi-resolutiion spectrogram construction plots (for '
             'debugging purposes).')


def run(parser, args):
    from pyrocko.io import rug
    from pyrocko.squirrel import MultiSpectrogramOperator, Pow2Windowing

    d = args.squirrel_query
    squirrel = args.make_squirrel()

    musop = MultiSpectrogramOperator(
        windowing=Pow2Windowing(
            nblock=2**args.nblock_exponent,
            nlevels=args.nlevels,
            weighting_exponent=args.weighting_exponent))

    musop.set_input(squirrel)

    sq_tmin, sq_tmax = squirrel.get_time_span(['waveform'], dummy_limits=False)
    if None in (sq_tmin, sq_tmax):
        raise ToolError(
            'No data. Add data with --add, --dataset or --persistent.')

    tmin = d.get('tmin', sq_tmin)
    tmax = d.get('tmax', sq_tmax)

    tinc = args.tinc

    nwindows = int(round((tmax - tmin) / tinc)) + 1

    time_format = '%Y-%m-%d_%H-%M-%S'

    with progress.view():
        task = progress.task('Calculating spectrograms', logger=logger)
        for iwindow in task(range(nwindows)):
            groups = musop.get_spectrogram_groups(
                codes=d.get('codes'),
                tmin=tmin+iwindow*tinc,
                tmax=tmin+(iwindow+1)*tinc)

            for group in groups:
                if args.show_construction:
                    group.plot_construction()

                fslice = slice(2, None)

                carpet = group \
                    .get_multi_spectrogram() \
                    .crop(fslice=fslice)

                path = os.path.join(
                    'spectrograms',
                    'spectrogram_{tmin}_{tmax}_{codes}.rug'.format(
                        tmin=util.time_to_str(carpet.tmin, format=time_format),
                        tmax=util.time_to_str(carpet.tmax, format=time_format),
                        codes=carpet.codes))

                util.ensuredirs(path)
                rug.save([carpet], path)
