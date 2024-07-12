# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel info`.
'''

import logging
import sys

from pyrocko import squirrel as sq
from ..common import SquirrelCommand, ldq

logger = logging.getLogger('psq.cli.info')

headline = 'General information.'

description = '''%s

Get auxilliary information, e.g. about the supported storage schemes.
''' % headline


class StorageSchemeInfo(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'storage-scheme',
            help='Show information about builtin storage schemes.',
            description='Show information about builtin storage schemes.')

    def setup(self, parser):
        parser.add_argument(
            'scheme_name',
            nargs='?',
            choices=sq.StorageSchemeChoice.choices,
            metavar='SCHEME',
            help='Show expected characteristics of a builtin storage scheme. '
                 'Choices: %s' % ldq(
                    sq.StorageSchemeChoice.choices))

    def run(self, parser, args):
        if not args.scheme_name:
            for scheme_name in sq.StorageSchemeChoice.choices:
                print(scheme_name)

            sys.exit()

        scheme = sq.get_storage_scheme(args.scheme_name)
        print(scheme)
        print(sq.StorageSchemeLayout.describe_header())
        for rate in [
                0.1, 0.5, 1.0, 2.0, 10., 20., 50., 100., 125., 200., 400.,
                800., 1000., 10000.]:

            deltat = 1.0 / rate
            layout = scheme.select_layout(deltat)
            print(layout.describe(deltat))


def make_subparser(subparsers):
    return subparsers.add_parser(
        'info',
        help=headline,
        subcommands=[StorageSchemeInfo()],
        description=description)


def setup(parser):
    pass


def run(parser, args):
    parser.print_help()
