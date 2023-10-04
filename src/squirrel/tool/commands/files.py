# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel files`.
'''

headline = 'Lookup files providing given content selection.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'files',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_argument(
        '--relative',
        action='store_true',
        default=False,
        help='Reveal path as it is stored in the database. This is relative '
             'for files inside a Squirrel environment.')

    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments()


def run(parser, args):
    d = args.squirrel_query
    squirrel = args.make_squirrel()

    paths = set()
    if d:
        for nut in squirrel.iter_nuts(**d):
            paths.add(nut.file_path)

        db = squirrel.get_database()
        for path in sorted(paths):
            print(db.relpath(path) if args.relative else path)

    else:
        for path in squirrel.iter_paths(raw=args.relative):
            print(path)
