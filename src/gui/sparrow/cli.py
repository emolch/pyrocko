from __future__ import print_function, absolute_import

import sys
import logging
from optparse import OptionParser
from io import StringIO

import pyrocko
from pyrocko import util


logger = logging.getLogger('pyrocko.gui.sparrow.cli')
km = 1e3


def d2u(d):
    if isinstance(d, dict):
        return dict((k.replace('-', '_'), v) for (k, v) in d.items())
    else:
        return d.replace('-', '_')


subcommand_descriptions = {
    'view': 'open viewer (default)',
    'version': 'print version number',
}

subcommand_usages = {
    'view': 'view [options] <files> ...',
    'version': 'version',
}

subcommands = list(subcommand_descriptions.keys())

program_name = 'sparrow'

usage_tdata = d2u(subcommand_descriptions)
usage_tdata['program_name'] = program_name
usage_tdata['version_number'] = pyrocko.__version__


usage = '''%(program_name)s <subcommand> [options] [--] <arguments> ...

A quick little bird to visualize geophysical data.

The Sparrow is part of Pyrocko version %(version_number)s.

Subcommands:

    view            %(view)s
    version         %(version)s

To get further help and a list of available options for any subcommand run:

    %(program_name)s <subcommand> --help

Where does your journey go today?!
''' % usage_tdata


def main(args=None):
    if not args:
        args = sys.argv

    help_triggers = ['--help', '-h', 'help']

    args = list(args)
    if len(args) < 2 or args[1] not in subcommands + help_triggers:
        args[1:1] = ['view']

    args.pop(0)
    command = args.pop(0)

    if command in subcommands:
        globals()['command_' + d2u(command)](args)

    elif command in help_triggers:
        if command == 'help' and args:
            acommand = args[0]
            if acommand in subcommands:
                globals()['command_' + acommand](['--help'])

        sys.exit('Usage: %s' % usage)

    else:
        die('No such subcommand: %s' % command)


def add_common_options(parser):
    parser.add_option(
        '--loglevel',
        action='store',
        dest='loglevel',
        type='choice',
        choices=('critical', 'error', 'warning', 'info', 'debug'),
        default='info',
        help='set logger level to '
             '"critical", "error", "warning", "info", or "debug". '
             'Default is "%default".')


def process_common_options(command, parser, options):
    util.setup_logging(program_name, options.loglevel)


def cl_parse(command, args, setup=None, details=None):
    usage = subcommand_usages[command]
    descr = subcommand_descriptions[command]

    if isinstance(usage, str):
        usage = [usage]

    susage = '%s %s' % (program_name, usage[0])
    for s in usage[1:]:
        susage += '\n%s%s %s' % (' '*7, program_name, s)

    description = descr[0].upper() + descr[1:] + '.'

    if details:
        description = description + '\n\n%s' % details

    parser = OptionParser(usage=susage, description=description)

    if setup:
        setup(parser)

    add_common_options(parser)
    (options, args) = parser.parse_args(args)
    process_common_options(command, parser, options)
    return parser, options, args


def die(message, err='', prelude=''):
    if prelude:
        prelude = prelude + '\n'

    if err:
        err = '\n' + err

    sys.exit('%s%s failed: %s%s' % (prelude, program_name, message, err))


def help_and_die(parser, message):
    sio = StringIO()
    parser.print_help(sio)
    die(message, prelude=sio.getvalue())


def command_view(args):
    def setup(parser):
        parser.add_option(
            '--no-depth-peeling',
            dest='use_depth_peeling',
            action='store_false',
            default=True,
            help='disable use of VTKs depth peeling (e.g. if the hardware '
                 'doesn\'t support it).')

    parser, options, args = cl_parse('view', args, setup)

    pyrocko.sparrow(use_depth_peeling=options.use_depth_peeling)


def command_version(args):
    def setup(parser):
        parser.add_option(
            '--short', dest='short', action='store_true',
            help='only print Pyrocko\'s version number')

    parser, options, args = cl_parse('version', args, setup)

    from pyrocko.print_version import print_version
    print_version(not options.short)


if __name__ == '__main__':
    main()
