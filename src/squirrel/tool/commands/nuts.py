# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel nuts`.
'''

from ..common import ldq
from pyrocko.squirrel import model

headline = 'Search indexed contents.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'nuts',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments()

    style_choices = ['index', 'summary', 'yaml']

    parser.add_argument(
        '--style',
        dest='style',
        choices=style_choices,
        default='index',
        help='Set style of presentation. Choices: %s' % ldq(style_choices))


def run(parser, args):
    squirrel = args.make_squirrel()
    for nut in squirrel.iter_nuts(**args.squirrel_query):
        if args.style == 'index':
            print(nut.summary)
        else:
            cache_id = 'waveform' \
                if nut.kind_id == model.WAVEFORM \
                else 'default'

            content = squirrel.get_content(nut, cache_id=cache_id)

            if args.style == 'yaml':
                print('# %s' % nut.summary)
                print(content.dump())
            elif args.style == 'summary':
                print(content.summary)

            if cache_id == 'waveform':
                squirrel.clear_accessor(
                    accessor_id='default',
                    cache_id=cache_id)
