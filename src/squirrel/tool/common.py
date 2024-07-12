# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel command line tool infrastructure and argument parsing.
'''

import os
import sys
import re
import argparse
import logging
import textwrap

from pyrocko import util, progress
from pyrocko.squirrel import error


logger = logging.getLogger('psq.tool.common')

help_time_format = 'Format: ```YYYY-MM-DD HH:MM:SS.FFF```, truncation allowed.'


def unwrap(s):
    if s is None:
        return None
    s = s.strip()
    parts = re.split(r'\n{2,}', s)
    lines = []
    for part in parts:
        plines = part.splitlines()
        if not any(line.startswith('  ') for line in plines):
            lines.append(' '.join(plines))
        else:
            lines.extend(plines)

        lines.append('')

    return '\n'.join(lines)


def wrap(s):
    lines = []
    parts = re.split(r'\n{2,}', s)
    for part in parts:
        plines = part.splitlines()
        if part.startswith('usage:') \
                or all(line.startswith('    ') for line in plines):
            lines.extend(plines)
        else:
            for line in plines:
                if not line:
                    lines.append(line)
                if not line.startswith(' '):
                    lines.extend(
                        textwrap.wrap(line, 79,))
                else:
                    lines.extend(
                        textwrap.wrap(line, 79, subsequent_indent=' '*24))

        lines.append('')

    return '\n'.join(lines)


def wrap_usage(s):
    lines = []
    for line in s.splitlines():
        if not line.startswith('usage:'):
            lines.append(line)
        else:
            lines.extend(textwrap.wrap(line, 79, subsequent_indent=' '*24))

    return '\n'.join(lines)


def formatter_with_width(n):
    class PyrockoHelpFormatter(argparse.RawDescriptionHelpFormatter):
        def __init__(self, *args, **kwargs):
            kwargs['width'] = n
            kwargs['max_help_position'] = 24
            argparse.RawDescriptionHelpFormatter.__init__(
                self, *args, **kwargs)

            # fix alignment problems, with the post-processing wrapping
            self._action_max_length = 24

    return PyrockoHelpFormatter


class PyrockoArgumentParser(argparse.ArgumentParser):
    '''
    Tweaks and extends the standard argument parser to simplify the generation
    of the online docs.

    We want to convert the ``--help`` outputs to ``rst`` for the html docs.
    Problem is that argparse's ``HelpFormatter`` to date have no public
    interface which we could use to achieve this. The solution here is a bit
    clunky but works ok for our purposes. We allow markup like
    :literal:`\\`\\`code\\`\\`` which is kept when producing ``rst`` (by
    parsing the final ``--help`` output) but stripped out when doing normal
    ``--help``. This leads to a problem with the internal output wrapping of
    argparse which it does before the stripping. To solve, we render with
    argparse to a very wide width and do the wrapping in post-processing.
    :literal:`\\`\\`code\\`\\`` is replaced with just ``code`` in normal
    output. :literal:`\\`\\`\\`code\\`\\`\\`` is replaced with ``'code'`` in
    normal output and with :literal:`\\`\\`code\\`\\`` in ``rst`` output.
    ``rst`` output is selected with environment variable
    ``PYROCKO_RST_HELP=1``. The script ``maintenance/argparse_help_to_rst.py``
    extracts the ``rst`` help and generates the ``rst`` files for the docs.
    '''

    def __init__(
            self, prog=None, usage=None, description=None, epilog=None,
            **kwargs):

        kwargs['formatter_class'] = formatter_with_width(1000000)

        description = unwrap(description)
        epilog = unwrap(epilog)

        argparse.ArgumentParser.__init__(
            self, prog=prog, usage=usage, description=description,
            epilog=epilog, **kwargs)

        if hasattr(self, '_action_groups'):
            for group in self._action_groups:
                if group.title == 'positional arguments':
                    group.title = 'Positional arguments'

                elif group.title == 'optional arguments':
                    group.title = 'Optional arguments'

                elif group.title == 'options':
                    group.title = 'Options'

        self.raw_help = False

    def format_help(self, *args, **kwargs):
        s = argparse.ArgumentParser.format_help(self, *args, **kwargs)

        # replace usage with wrapped one from argparse because naive wrapping
        # does not look good.
        formatter_class = self.formatter_class
        self.formatter_class = formatter_with_width(79)
        usage = self.format_usage()
        self.formatter_class = formatter_class

        lines = []
        for line in s.splitlines():
            if line.startswith('usage:'):
                lines.append(usage)
            else:
                lines.append(line)

        s = '\n'.join(lines)

        if os.environ.get('PYROCKO_RST_HELP', '0') == '0':
            s = s.replace('```', "'")
            s = s.replace('``', '')
            s = wrap(s)
        else:
            s = s.replace('```', '``')
            s = wrap_usage(s)

        return s


class SquirrelArgumentParser(PyrockoArgumentParser):
    '''
    Parser for CLI arguments with a some extras for Squirrel based apps.

    :param command:
        Implementation of the command.
    :type command:
        :py:class:`SquirrelCommand` or module providing the same interface

    :param subcommands:
        Implementations of subcommands.
    :type subcommands:
        :py:class:`list` of :py:class:`SquirrelCommand` or modules providing
        the same interface

    :param \\*args:
        Handed through to base class's init.

    :param \\*\\*kwargs:
        Handed through to base class's init.
    '''

    def __init__(self, *args, command=None, subcommands=[], **kwargs):

        self._command = command
        self._subcommands = subcommands
        self._have_selection_arguments = False
        self._have_query_arguments = False

        kwargs['epilog'] = kwargs.get('epilog', '''


----

Manual: https://pyrocko.org/docs/current/apps/squirrel

Tutorial: https://pyrocko.org/docs/current/apps/squirrel/tutorial.html

Examples: https://pyrocko.org/docs/current/apps/squirrel/manual.html#examples

🐿️
''')

        kwargs['add_help'] = False
        PyrockoArgumentParser.__init__(self, *args, **kwargs)
        add_standard_arguments(self)
        self._command = None
        self._subcommands = []
        if command:
            self.set_command(command)

        if subcommands:
            self.set_subcommands(subcommands)

    def set_command(self, command):
        command.setup(self)
        self.set_defaults(target=command.run)

    def set_subcommands(self, subcommands):
        subparsers = self.add_subparsers(
            metavar='SUBCOMMAND',
            title='Subcommands')

        for mod in subcommands:
            subparser = mod.make_subparser(subparsers)
            if subparser is None:
                raise Exception(
                    'make_subparser(subparsers) must return the created '
                    'parser.')

            mod.setup(subparser)
            subparser.set_defaults(target=mod.run, subparser=subparser)

    def parse_args(self, args=None, namespace=None):
        '''
        Parse arguments given on command line.

        Extends the functionality of
        :py:meth:`argparse.ArgumentParser.parse_args` to process and handle the
        standard options ``--loglevel``, ``--progress`` and ``--help``.
        '''

        args = PyrockoArgumentParser.parse_args(
            self, args=args, namespace=namespace)

        eff_parser = args.__dict__.get('subparser', self)

        process_standard_arguments(eff_parser, args)

        if eff_parser._have_selection_arguments:
            def make_squirrel():
                return squirrel_from_selection_arguments(args)

            args.make_squirrel = make_squirrel

        if eff_parser._have_query_arguments:
            try:
                args.squirrel_query = squirrel_query_from_arguments(args)
            except (error.SquirrelError, error.ToolError) as e:
                logger.fatal(str(e))
                sys.exit(1)

        return args

    def dispatch(self, args):
        '''
        Dispatch execution to selected command/subcommand.

        :param args:
            Parsed arguments obtained from :py:meth:`parse_args`.

        :returns:
            ``True`` if dispatching was successful, ``False`` otherwise.

        If an exception of type
        :py:exc:`~pyrocko.squirrel.error.SquirrelError` or
        :py:exc:`~pyrocko.squirrel.error.ToolError` is caught, the error is
        logged and the program is terminated with exit code 1.
        '''
        eff_parser = args.__dict__.get('subparser', self)
        target = args.__dict__.get('target', None)

        if target:
            try:
                target(eff_parser, args)
                return True

            except (error.SquirrelError, error.ToolError) as e:
                logger.fatal(str(e))
                sys.exit(1)

        return False

    def run(self, args=None):
        '''
        Parse arguments and dispatch to selected command/subcommand.

        This simply calls :py:meth:`parse_args` and then :py:meth:`dispatch`
        with the obtained ``args``. A usage message is printed if no command is
        selected.
        '''
        args = self.parse_args(args)
        if not self.dispatch(args):
            self.print_help()

    def add_squirrel_selection_arguments(self):
        '''
        Set up command line options commonly used to configure a
        :py:class:`~pyrocko.squirrel.base.Squirrel` instance.

        This will  optional arguments ``--add``, ``--include``, ``--exclude``,
        ``--optimistic``, ``--format``, ``--add-only``, ``--persistent``, and
        ``--dataset``.

        Call ``args.make_squirrel()`` on the arguments returned from
        :py:meth:`parse_args` to finally instantiate and configure the
        :py:class:`~pyrocko.squirrel.base.Squirrel` instance.
        '''
        add_squirrel_selection_arguments(self)
        self._have_selection_arguments = True

    def add_squirrel_query_arguments(self, without=[]):
        '''
        Set up command line options commonly used in squirrel queries.

        This will add optional arguments ``--kinds``, ``--codes``, ``--tmin``,
        ``--tmax``, and ``--time``.

        Once finished with parsing, the query arguments are available as
        ``args.squirrel_query`` on the arguments returned from
        :py:meth:`parse_args`.

        :param without:
            Suppress adding given options.
        :type without:
            :py:class:`list` of :py:class:`str`, choices: ``'tmin'``,
            ``'tmax'``, ``'codes'``, and ``'time'``.
        '''

        add_squirrel_query_arguments(self, without=without)
        self._have_query_arguments = True


def csvtype(choices):
    def splitarg(arg):
        values = arg.split(',')
        for value in values:
            if value not in choices:
                raise argparse.ArgumentTypeError(
                    'Invalid choice: {!r} (choose from {})'
                    .format(value, ', '.join(map(repr, choices))))
        return values
    return splitarg


def dq(x):
    return '``%s``' % x


def ldq(xs):
    return ', '.join(dq(x) for x in xs)


def add_standard_arguments(parser):
    group = parser.add_argument_group('General options')
    group.add_argument(
        '--help', '-h',
        action='help',
        help='Show this help message and exit.')

    loglevel_choices = ['critical', 'error', 'warning', 'info', 'debug']
    loglevel_default = 'info'

    group.add_argument(
        '--loglevel',
        choices=loglevel_choices,
        default=loglevel_default,
        metavar='LEVEL',
        help='Set logger level. Choices: %s. Default: %s.' % (
            ldq(loglevel_choices), dq(loglevel_default)))

    progress_choices = ['terminal', 'log', 'off']
    progress_default = 'terminal'

    group.add_argument(
        '--progress',
        choices=progress_choices,
        default=progress_default,
        metavar='DEST',
        help='Set how progress status is reported. Choices: %s. '
             'Default: %s.' % (
                ldq(progress_choices), dq(progress_default)))


def process_standard_arguments(parser, args):
    loglevel = args.__dict__.pop('loglevel')
    util.setup_logging(parser.prog, loglevel)

    pmode = args.__dict__.pop('progress')
    progress.set_default_viewer(pmode)


def add_squirrel_selection_arguments(parser):
    '''
    Set up command line options commonly used to configure a
    :py:class:`~pyrocko.squirrel.base.Squirrel` instance.

    This will  optional arguments ``--add``, ``--include``, ``--exclude``,
    ``--optimistic``, ``--format``, ``--add-only``, ``--persistent``,
    and ``--dataset`` to a given argument parser.

    Once finished with parsing, call
    :py:func:`squirrel_from_selection_arguments` to finally instantiate and
    configure the :py:class:`~pyrocko.squirrel.base.Squirrel` instance.

    :param parser:
        The argument parser to be configured.
    :type parser:
        argparse.ArgumentParser
    '''
    from pyrocko import squirrel as sq

    group = parser.add_argument_group('Data collection options')

    group.add_argument(
        '--add', '-a',
        dest='paths',
        metavar='PATH',
        nargs='+',
        help='Add files and directories with waveforms, metadata and events. '
             'Content is indexed and added to the temporary (default) or '
             'persistent (see ``--persistent``) data selection.')

    group.add_argument(
        '--include',
        dest='include',
        metavar='REGEX',
        help='Only include files whose paths match the regular expression '
             "``REGEX``. Examples: ``--include='\\.MSEED$'`` would only "
             'match files ending with ```.MSEED```. '
             "``--include='\\.BH[EN]\\.'`` would match paths containing "
             "```.BHE.``` or ```.BHN.```. ``--include='/2011/'`` would "
             'match paths with a subdirectory ```2011``` in their path '
             'hierarchy.')

    group.add_argument(
        '--exclude',
        dest='exclude',
        metavar='REGEX',
        help='Only include files whose paths do not match the regular '
             "expression ``REGEX``. Examples: ``--exclude='/\\.DS_Store/'`` "
             'would exclude anything inside any ```.DS_Store``` subdirectory.')

    group.add_argument(
        '--optimistic', '-o',
        action='store_false',
        dest='check',
        default=True,
        help='Disable checking file modification times for faster startup.')

    group.add_argument(
        '--format', '-f',
        dest='format',
        metavar='FORMAT',
        default='detect',
        choices=sq.supported_formats(),
        help='Assume input files are of given ``FORMAT``. Choices: %s. '
             'Default: %s.' % (
                 ldq(sq.supported_formats()),
                 dq('detect')))

    group.add_argument(
        '--add-only',
        type=csvtype(sq.supported_content_kinds()),
        dest='kinds_add',
        metavar='KINDS',
        help='Restrict meta-data scanning to given content kinds. '
             '``KINDS`` is a comma-separated list of content kinds. '
             'Choices: %s. By default, all content kinds are indexed.'
             % ldq(sq.supported_content_kinds()))

    group.add_argument(
        '--persistent', '-p',
        dest='persistent',
        metavar='NAME',
        help='Create/use persistent selection with given ``NAME``. Persistent '
             'selections can be used to speed up startup of Squirrel-based '
             'applications.')

    group.add_argument(
        '--dataset', '-d',
        dest='datasets',
        default=[],
        action='append',
        metavar='FILE',
        help='Add files, directories and remote sources from dataset '
             'description file. This option can be repeated to add multiple '
             'datasets. Run ```squirrel template``` to obtain examples of '
             'dataset description files.')

    group.add_argument(
        '--upgrade-storage',
        dest='upgrade_storage',
        default=False,
        action='store_true',
        help='Upgrade storage layout of cached data to latest version.')


def squirrel_from_selection_arguments(args):
    '''
    Create a :py:class:`~pyrocko.squirrel.base.Squirrel` instance from command
    line arguments.

    Use :py:func:`add_squirrel_selection_arguments` to configure the parser
    with the necessary options.

    :param args:
        Parsed command line arguments, as returned by
        :py:meth:`argparse.ArgumentParser.parse_args`.

    :returns:
        :py:class:`pyrocko.squirrel.base.Squirrel` instance with paths,
        datasets and remote sources added.

    '''
    from pyrocko.squirrel import base

    squirrel = base.Squirrel(persistent=args.persistent)

    with progress.view():
        if args.paths:
            squirrel.add(
                args.paths,
                check=args.check,
                format=args.format,
                kinds=args.kinds_add or None,
                include=args.include,
                exclude=args.exclude)

        with progress.task('add datasets', logger=logger) as task:
            for dataset_path in task(args.datasets):
                squirrel.add_dataset(
                    dataset_path,
                    check=args.check,
                    upgrade=args.upgrade_storage)

    return squirrel


def add_squirrel_query_arguments(parser, without=[]):
    '''
    Set up command line options commonly used in squirrel queries.

    This will add optional arguments ``--kinds``, ``--codes``, ``--tmin``,
    ``--tmax``, and ``--time``.

    Once finished with parsing, call
    :py:func:`squirrel_query_from_arguments` to get the parsed values.

    :param parser:
        The argument parser to be configured.
    :type parser:
        argparse.ArgumentParser

    :param without:
        Suppress adding given options.
    :type without:
        :py:class:`list` of :py:class:`str`
    '''

    from pyrocko import squirrel as sq

    group = parser.add_argument_group('Data query options')

    if 'kinds' not in without:
        group.add_argument(
            '--kinds',
            type=csvtype(sq.supported_content_kinds()),
            dest='kinds',
            metavar='KINDS',
            help='Content kinds to query. ``KINDS`` is a comma-separated list '
                 'of content kinds. Choices: %s. By default, all content '
                 'kinds are queried.' % ldq(sq.supported_content_kinds()))

    if 'codes' not in without:
        group.add_argument(
            '--codes',
            dest='codes',
            metavar='CODES',
            help='Code patterns to query (``STA``, ``NET.STA``, '
                 '``NET.STA.LOC``, ``NET.STA.LOC.CHA``, or '
                 '``NET.STA.LOC.CHA.EXTRA``). The pattern may contain '
                 'wildcards ``*`` (zero or more arbitrary characters), ``?`` '
                 '(single arbitrary character), and ``[CHARS]`` (any '
                 'character out of ``CHARS``). Multiple patterns can be '
                 'given by separating them with commas.')

    if 'tmin' not in without:
        group.add_argument(
            '--tmin',
            dest='tmin',
            metavar='TIME',
            help='Begin of time interval to query. %s' % help_time_format)

    if 'tmax' not in without:
        group.add_argument(
            '--tmax',
            dest='tmax',
            metavar='TIME',
            help='End of time interval to query. %s' % help_time_format)

    if 'time' not in without:
        group.add_argument(
            '--time',
            dest='time',
            metavar='TIME',
            help='Time instant to query. %s' % help_time_format)


def ce(prefix, func, *args):
    '''
    Convert Exceptions in to ToolError.
    '''
    try:
        return func(*args)
    except Exception as e:
        raise error.ToolError('%s: %s' % (prefix, str(e)))


def squirrel_query_from_arguments(args):
    '''
    Get common arguments to be used in squirrel queries from command line.

    Use :py:func:`add_squirrel_query_arguments` to configure the parser with
    the necessary options.

    :param args:
        Parsed command line arguments, as returned by
        :py:meth:`argparse.ArgumentParser.parse_args`.

    :returns:
        :py:class:`dict` with any parsed option values.
    '''

    from pyrocko import squirrel as sq

    d = {}

    if 'kinds' in args and args.kinds:
        d['kind'] = args.kinds
    if 'tmin' in args and args.tmin:
        d['tmin'] = ce(
            '--tmin', util.str_to_time_fillup, args.tmin)
    if 'tmax' in args and args.tmax:
        d['tmax'] = ce(
            '--tmax', util.str_to_time_fillup, args.tmax)
    if 'time' in args and args.time:
        d['tmin'] = d['tmax'] = ce(
            '--time', util.str_to_time_fillup, args.time)
    if 'codes' in args and args.codes:
        d['codes'] = [
            sq.to_codes_guess(s.strip()) for s in args.codes.split(',')]

    if ('tmin' in d and 'time' in d) or ('tmax' in d and 'time' in d):
        raise error.ToolError(
            'Options --tmin/--tmax and --time are mutually exclusive.')
    return d


class SquirrelCommand(object):
    '''
    Base class for Squirrel-based CLI programs and subcommands.
    '''

    def fail(self, message):
        '''
        Raises :py:exc:`~pyrocko.squirrel.error.ToolError`.

        :py:meth:`SquirrelArgumentParser.run` catches
        :py:exc:`~pyrocko.squirrel.error.ToolError`, logs the error message and
        terminates with an error exit state.
        '''
        raise error.ToolError(message)

    def make_subparser(self, subparsers):
        '''
        To be implemented in subcommand. Create subcommand parser.

        Must return a newly created parser obtained with
        ``subparsers.add_parser(...)``, e.g.::

            def make_subparser(self, subparsers):
                return subparsers.add_parser(
                    'plot', help='Draw a nice plot.')

        '''
        return subparsers.add_parser(
            self.__class__.__name__, help='Undocumented.')

    def setup(self, parser):
        '''
        To be implemented in subcommand. Configure parser.

        :param parser:
            The argument parser to be configured.
        :type parser:
            argparse.ArgumentParser

        Example::

            def setup(self, parser):
                parser.add_squirrel_selection_arguments()
                parser.add_squirrel_query_arguments()
                parser.add_argument(
                    '--fmin',
                    dest='fmin',
                    metavar='FLOAT',
                    type=float,
                    help='Corner of highpass [Hz].')
        '''
        pass

    def run(self, parser, args):
        '''
        To be implemented in subcommand. Main routine of the command.

        :param parser:
            The argument parser to be configured.
        :type parser:
            argparse.ArgumentParser

        :param args:
            Parsed command line arguments, as returned by
            :py:meth:`argparse.ArgumentParser.parse_args`.

        Example::

            def run(self, parser, args):
                print('User has selected fmin = %g Hz' % args.fmin)

                # args.make_squirrel() is available if
                # parser.add_squirrel_selection_arguments() was called during
                # setup().

                sq = args.make_squirrel()

                # args.squirrel_query is available if
                # praser.add_squirrel_query_arguments() was called during
                # setup().

                stations = sq.get_stations(**args.squirrel_query)
        '''
        pass


__all__ = [
    'PyrockoArgumentParser',
    'SquirrelArgumentParser',
    'SquirrelCommand',
    'add_squirrel_selection_arguments',
    'squirrel_from_selection_arguments',
    'add_squirrel_query_arguments',
    'squirrel_query_from_arguments',
]
