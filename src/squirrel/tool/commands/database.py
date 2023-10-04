# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel database`.
'''

import logging

from pyrocko import squirrel as sq
from ..common import SquirrelCommand

logger = logging.getLogger('psq.cli.database')

headline = 'Database inspection and maintenance.'

description = '''%s

Get information about Squirrel's meta-data cache and database. Where it is,
what files it knows about and what index entries are available. It also allows
to do some basic cleanup actions.
''' % headline


class Env(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'env',
            help='Show current Squirrel environment.',
            description='Show current Squirrel environment.')

    def run(self, parser, args):
        env = sq.get_environment()
        env.path_prefix = env.get_basepath()
        print(env)


class Stats(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'stats',
            help='Show information about cached meta-data.',
            description='Show information about cached meta-data.')

    def setup(self, parser):
        parser.add_argument(
            '--full',
            help='Show details.',
            action='store_true')

    def run(self, parser, args):
        s = sq.Squirrel()
        db = s.get_database()
        if args.full:
            print(db.get_stats().dump())
        else:
            print(db.get_stats())


class Files(SquirrelCommand):

    def make_subparser(self, subparsers):
        headline = \
            'Show paths of files for which cached meta-data is available.'

        return subparsers.add_parser(
            'files',
            help=headline,
            description=headline)

    def setup(self, parser):
        parser.add_argument(
            '--nnuts',
            help='Show nut count for each file.',
            action='store_true')

    def run(self, parser, args):
        s = sq.Squirrel()
        db = s.get_database()

        if args.nnuts:
            for path, nnuts in db.iter_nnuts_by_file():
                print(path, nnuts)
        else:
            for path in db.iter_paths():
                print(path)


class Nuts(SquirrelCommand):

    def make_subparser(self, subparsers):
        headline = \
            'Dump index entry summaries.'

        return subparsers.add_parser(
            'nuts',
            help=headline,
            description=headline)

    def run(self, parser, args):
        s = sq.Squirrel()
        db = s.get_database()
        for path, nuts in db.undig_all():
            print(path)
            for nut in nuts:
                print('  ' + nut.summary)


class Cleanup(SquirrelCommand):

    def make_subparser(self, subparsers):
        headline = \
            'Remove leftover volatile data entries.'

        return subparsers.add_parser(
            'cleanup',
            help=headline,
            description=headline)

    def run(self, parser, args):
        s = sq.Squirrel()
        db = s.get_database()
        n_removed = db._remove_volatile()
        logger.info('Number of entries removed: %i' % n_removed)


class Remove(SquirrelCommand):

    def make_subparser(self, subparsers):
        headline = \
            'Remove cached meta-data of files matching given patterns.'

        return subparsers.add_parser(
            'remove',
            help=headline,
            description=headline)

    def setup(self, parser):
        parser.add_argument(
            'paths',
            nargs='+',
            metavar='PATHS',
            help='Glob patterns of paths to be removed (should be quoted to '
                 'prevent the shell from expanding them).')

    def run(self, parser, args):
        s = sq.Squirrel()
        db = s.get_database()

        n_removed = 0
        for path in args.paths:
            n_removed += db.remove_glob(path)

        logger.info('Number of entries removed: %i' % n_removed)


def make_subparser(subparsers):
    return subparsers.add_parser(
        'database',
        help=headline,
        subcommands=[Env(), Stats(), Files(), Nuts(), Cleanup(), Remove()],
        description=description)


def setup(parser):
    pass


def run(parser, args):
    parser.print_help()
