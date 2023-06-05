# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import math
import logging

from pyrocko.squirrel.error import SquirrelError
from pyrocko.progress import progress

logger = logging.getLogger('psq.cli.summon')

headline = 'Fill local cache.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'summon',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments()
    parser.add_argument(
        '--channel-priorities',
        dest='channel_priorities',
        metavar='CHA',
        help='''
List of 2-character band/instrument code combinations to try. For example,
giving ```HH,BH``` would first try to get ```HH?``` channels and then fallback
to ```BH?``` if these are not available. The first matching waveforms are
returned. Use in combination with ``--sample-rate-min`` and
``--sample-rate-max`` to constrain the sample rate.
'''.strip())

    parser.add_argument(
        '--sample-rate-min',
        dest='sample_rate_min',
        metavar='FLOAT',
        type=float,
        help='Minimum sample rate [Hz] to consider.')

    parser.add_argument(
        '--sample-rate-max',
        dest='sample_rate_max',
        metavar='FLOAT',
        type=float,
        help='Maximum sample rate [Hz] to consider.')


def run(parser, args):
    d = args.squirrel_query
    squirrel = args.make_squirrel()

    if 'tmin' not in d or 'tmax' not in d:
        raise SquirrelError('Time span required.')

    tinc = 3600.

    channel_priorities = None
    if args.channel_priorities:
        channel_priorities = [
            cha.strip() for cha in args.channel_priorities.split(',')]

    with progress.view():
        nwindows = int(math.ceil((d['tmax'] - d['tmin']) / tinc))
        task = progress.task('Summoning', nwindows)
        iwindow = 0
        for trs in squirrel.chopper_waveforms(
                tinc=tinc,
                load_data=False,
                channel_priorities=channel_priorities,
                sample_rate_min=args.sample_rate_min,
                sample_rate_max=args.sample_rate_max,
                **d):

            iwindow += 1
            task.update(iwindow)

        task.done()

    stats = str(squirrel)
    stats = '\n'.join('  ' + s for s in stats.splitlines())

    logger.info('Squirrel stats:\n%s' % stats)
