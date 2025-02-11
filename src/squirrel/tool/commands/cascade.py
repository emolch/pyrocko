# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel cascade`.
'''

import logging


from pyrocko import progress

logger = logging.getLogger('psq.cli.cascade')

headline = 'Create hierarchical data overviews.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'cascade',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments()

    parser.add_argument(
        '--levels',
        dest='nlevels',
        type=int,
        metavar='INT',
        default=4,
        help='Number of levels to create.')

    parser.add_argument(
        '--fold',
        dest='nfold',
        type=int,
        metavar='INT',
        default=2,
        help='Decimation factor applied in each level.')


def run(parser, args):
    from pyrocko.squirrel.cascade import cascade

    squirrel = args.make_squirrel()
    with progress.view():
        cascade(
            squirrel,
            nlevels=args.nlevels,
            nfold=args.nfold,
            **args.squirrel_query)
