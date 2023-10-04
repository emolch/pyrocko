# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel init`.
'''

from pyrocko import squirrel as sq


headline = 'Create local environment.'

description = headline + '''

Squirrel based applications can either use the user’s global Squirrel
environment or a project specific local environment. Running this command in a
project's top level directory creates a local environment. Any Squirrel
application started thereafter in this directory or any of its subdirectories,
will use the local enviroment instead of the global one.

The local enviroment consists of a directory ```.squirrel``` which contains
the Squirrel's database and a cache directory.

A local environment can be removed by removing its ```.squirrel``` directory.

The user's global enviroment database resides in Pyrocko’s global cache
directory, by default in ```$HOME/.pyrocko/cache/squirrel```.
'''


def make_subparser(subparsers):
    return subparsers.add_parser(
        'init',
        help=headline,
        description=description)


def setup(parser):
    pass


def run(parser, args):
    sq.init_environment()
