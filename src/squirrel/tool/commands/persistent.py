# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel persistent`.
'''

from pyrocko.squirrel import error, environment, database, base

headline = 'Manage persistent selections.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'persistent',
        help=headline,
        description=headline + '''

Usually, the contents of files given to Squirrel are made available within the
application through a runtime selection which is discarded again when the
application quits. Getting the cached meta-data into the runtime selection can
be a bottleneck for application startup with large datasets. To speed up
startup of Squirrel-based applications, persistent selections created with the
``--persistent`` option can be used.

This command allows to list and delete persistent selections.
''')


def setup(parser):
    parser.add_argument(
        'action',
        choices=['list', 'delete'],
        help='Select action to perform.')

    parser.add_argument(
        'names',
        nargs='*',
        help='Persistent selection names.')


def run(parser, args):
    env = environment.get_environment()
    db = database.get_database(env.expand_path(env.database_path))

    available = sorted(db.get_persistent_names())
    for name in args.names:
        if name not in available:
            raise error.SquirrelError(
                'No such persistent selection: %s' % name)

    if args.action == 'list':
        if not args.names:
            names = available
        else:
            names = args.names

        for name in names:
            print(name)

    elif args.action == 'delete':
        for name in args.names:
            sq = base.Squirrel(persistent=name)
            sq.delete()

    else:
        raise error.SquirrelError('Invalid action: %s' % args.action)
