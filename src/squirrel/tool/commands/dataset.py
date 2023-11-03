import logging

from pyrocko.util import glob_filter, GlobFilterNoMatch
from pyrocko import squirrel
from ..common import SquirrelCommand

logger = logging.getLogger('psq.cli.dataset')

headline = 'Dataset managment.'

description = '''%s

Get information about built-in datasets.
''' % headline


def add_argument_dataset_names(parser, nargs):
    parser.add_argument(
        dest='dataset_names',
        nargs=nargs,
        metavar='NAMES',
        help='List only datasets with names matching given (glob-style) '
             'patterns.')


def get_matching_builtin_datasets(name_patterns):
    datasets = squirrel.dataset.get_builtin_datasets()
    try:
        return [
            (name, datasets[name])
            for name in sorted(glob_filter(
                name_patterns, datasets.keys(), raise_if_nomatch=True))]
    except GlobFilterNoMatch as e:
        raise squirrel.ToolError(str(e)) from None


class List(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'list',
            help='List builtin datasets.',
            description='List builtin datasets.')

    def setup(self, parser):
        add_argument_dataset_names(parser, '*')

    def run(self, parser, args):
        for (name, ds) in get_matching_builtin_datasets(args.dataset_names):
            print('%-25s %s' % (name, ds.comment or ''))


class Show(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'show',
            help='Print dataset description.',
            description='Print dataset description.')

    def setup(self, parser):
        add_argument_dataset_names(parser, '+')

    def run(self, parser, args):
        for (name, ds) in get_matching_builtin_datasets(args.dataset_names):
            print('# %s' % name)
            print(ds)


class Sources(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'sources',
            help='List sources attached to Squirrel through datasets.',
            description='List sources attached to Squirrel through datasets.')

    def setup(self, parser):
        parser.add_squirrel_selection_arguments()

    def run(self, parser, args):
        squirrel = args.make_squirrel()
        for source in squirrel.get_sources():
            print(source.info())


def make_subparser(subparsers):
    return subparsers.add_parser(
        'dataset',
        help=headline,
        subcommands=[List(), Show(), Sources()],
        description=description)


def setup(parser):
    pass


def run(parser, args):
    parser.print_help()
