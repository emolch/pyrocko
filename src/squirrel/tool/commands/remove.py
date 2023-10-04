# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel remove`.
'''

import logging

from ..common import SquirrelCommand

logger = logging.getLogger('psq.cli.remove')

headline = 'Remove entries from selection or database.'

description = '''%s

Allows selective removal of cached metadata from Squirrel's database.

Currently only removal of waveform promises is supported.
''' % headline


class Promises(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'promises',
            help='Remove all waveform promises in the selection.',
            description='Remove all waveform promises in the selection.')

    def setup(self, parser):
        parser.add_squirrel_selection_arguments()

    def run(self, parser, args):
        s = args.make_squirrel()
        s.remove_waveform_promises(from_database='global')


def make_subparser(subparsers):
    return subparsers.add_parser(
        'remove',
        help=headline,
        subcommands=[Promises()],
        description=description)


def setup(parser):
    pass


def run(parser, args):
    parser.print_help()
