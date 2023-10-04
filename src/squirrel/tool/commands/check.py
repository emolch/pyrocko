# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel check`.
'''

import sys

from pyrocko.squirrel.check import do_check, SquirrelCheckProblemType

from ..common import csvtype, dq, ldq

headline = 'Check dataset consistency.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'check',
        help=headline,
        description=headline + '''

A report listing potential dataset/metadata problems for a given data
collection is printed to standard output. The following problems are detected:

%s
''' % '\n'.join(
            '  [%s]: %s' % (k, v)
            for (k, v) in SquirrelCheckProblemType.types.items()))


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments(without=['kinds'])
    parser.add_argument(
        '--ignore',
        type=csvtype(SquirrelCheckProblemType.choices),
        metavar='TYPE,...',
        help='Problem types to be ignored. Choices: %s.'
        % ldq(SquirrelCheckProblemType.choices))

    parser.add_argument(
        '--verbose', '-v',
        action='count',
        dest='verbosity',
        default=0,
        help='Verbose mode for textual output. Multiple ``-v`` options '
             'increase the verbosity. The maximum is 2. At level 1, ``ok`` '
             'indicators are printed for entries with no problem. At level 2, '
             'availability information is shown for each entry.')

    format_default = 'text'
    format_choices = ['text', 'yaml']

    parser.add_argument(
        '--out-format',
        choices=format_choices,
        default=format_default,
        dest='output_format',
        metavar='FMT',
        help='Specifies how output is presented. Choices: %s. '
             'Default: %s.' % (ldq(format_choices), dq(format_default)))


def run(parser, args):
    squirrel = args.make_squirrel()

    check = do_check(
        squirrel,
        ignore=args.ignore or [],
        **args.squirrel_query)

    if args.output_format == 'text':
        print(check.get_text(verbosity=args.verbosity))
    elif args.output_format == 'yaml':
        print(check)
    else:
        assert False

    sys.exit(0 if check.get_nproblems() == 0 else 1)
