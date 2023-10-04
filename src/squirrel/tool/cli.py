# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel command line tool main program.
'''

import logging

from . import common
from .commands import command_modules


logger = logging.getLogger('psq.cli')


g_program_name = 'squirrel'


def main(args=None):
    run(
        args=args,
        prog=g_program_name,
        subcommands=command_modules,
        description='''
Pyrocko Squirrel - Prompt seismological data access with a fluffy tail.

This is ```squirrel```, a command-line front-end to the Squirrel data access
infrastructure. The Squirrel infrastructure offers meta-data caching, blazingly
fast data lookup for large datasets and transparent online data download to
applications building on it.

In most cases, the Squirrel does its business discretely under the hood and
does not require human interaction or awareness. However, using this tool, some
aspects can be configured for the benefit of greater performance or
convenience, including (1) using a separate (isolated, local) environment for a
specific project, (2) using named selections to speed up access to very large
datasets, (3), pre-scanning/indexing of file collections. It can also be used
to inspect various aspects of a data collection.

This tool's functionality is available through several subcommands. Run
```squirrel SUBCOMMAND --help``` to get further help.''')


def run(
        args=None,
        command=None,
        subcommands=[],
        description='''
Pyrocko Squirrel based script.

Run with --help to get further help.''',
        **kwargs):

    '''
    Setup and run Squirrel-based application.

    The implementation of the tool can be provided by one or multiple
    :py:class:`~pyrocko.squirrel.tool.common.SquirrelCommand` instances. This
    driver function sets up a
    :py:class:`~pyrocko.squirrel.tool.common.SquirrelArgumentParser`, and
    processes command line arguments, and dispatches execution to the selected
    command or subcommand. The program is set up to provide and automatically
    handle ``--help``, ``--loglevel``, and ``--progress``. If an exception of
    type :py:exc:`pyrocko.squirrel.error.SquirrelError` or
    :py:exc:`pyrocko.squirrel.error.ToolError` is caught, the error is logged
    and the program is terminated with exit code 1.

    :param args:
        Arguments passed to
        :py:meth:`~pyrocko.squirrel.tool.common.SquirrelArgumentParser.parse_args`.
        By default uses py:attr:`sys.argv`.
    :type args:
        :py:class:`list` of :py:class:`str`

    :param command:
        Implementation of the command. It must provide ``setup(parser)`` and
        ``run(parser, args)``.
    :type command:
        :py:class:`~pyrocko.squirrel.tool.common.SquirrelCommand` or module

    :param subcommands:
        Configures the program to offer multiple subcommands. The command to
        execute is selected with the first argument passed to ``args``.
        Implementations must provide ``make_subparser(subparsers)``,
        ``setup(parser)``, and ``run(parser, args)``.
    :type subcommands:
        :py:class:`list` of
        :py:class:`~pyrocko.squirrel.tool.common.SquirrelCommand` instances or
        modules

    :param description:
        Description of the program.
    :type description:
        str
    '''

    parser = common.SquirrelArgumentParser(
        command=command,
        subcommands=subcommands,
        description=description, **kwargs)

    return parser.run(args)


__all__ = [
    'main',
    'run',
]
