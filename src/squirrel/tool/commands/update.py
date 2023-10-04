# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel update`.
'''

import logging

# from pyrocko.squirrel.error import SquirrelError
from pyrocko.squirrel import model

logger = logging.getLogger('psq.cli.update')

headline = 'Update remote sources inventories.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'update',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments()

    parser.add_argument(
        '--promises',
        action='store_true',
        dest='promises',
        default=False,
        help='Update waveform promises.')

    parser.add_argument(
        '--responses',
        action='store_true',
        dest='responses',
        default=False,
        help='Update responses.')


def run(parser, args):
    d = args.squirrel_query
    squirrel = args.make_squirrel()

    tmin = d.get('tmin', model.g_tmin)
    tmax = d.get('tmax', model.g_tmax)
    codes = d.get('codes', None)

    squirrel.update(tmin=tmin, tmax=tmax)
    if args.promises:
        squirrel.update_waveform_promises(tmin=tmin, tmax=tmax, codes=codes)

    if args.responses:
        squirrel.update_responses()

    stats = str(squirrel)
    stats = '\n'.join('  ' + s for s in stats.splitlines())

    logger.info('Squirrel stats:\n%s' % stats)
