# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel stationxml`.
'''

from pyrocko.squirrel.tool.common import ldq, dq

headline = 'Export station metadata as StationXML.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'stationxml',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments()

    level_choices = ('network', 'station', 'channel', 'response')
    level_default = 'response'

    parser.add_argument(
        '--level',
        dest='level',
        choices=level_choices,
        default=level_default,
        help='Set level of detail to be returned. Choices: %s. '
             'Default: %s.' % (
                 ldq(level_choices),
                 dq(level_default)))

    on_error_choices = ('raise', 'warn', 'ignore')
    on_error_default = 'raise'

    parser.add_argument(
        '--on-error',
        dest='on_error',
        choices=on_error_choices,
        default=on_error_default,
        help='How to handle metadata errors. Choices: %s. '
             'Default: %s.' % (
                 ldq(on_error_choices),
                 dq(on_error_default)))

    out_format_choices = ('xml', 'yaml')
    out_format_default = 'xml'

    parser.add_argument(
        '--out-format',
        dest='out_format',
        choices=out_format_choices,
        default=out_format_default,
        help='Set format of output. Choices: %s. '
             'Default: %s.' % (
                 ldq(out_format_choices),
                 dq(out_format_default)))


def run(parser, args):
    squirrel = args.make_squirrel()

    sx = squirrel.get_stationxml(
        **args.squirrel_query,
        level=args.level,
        on_error=args.on_error)

    if args.out_format == 'xml':
        print(sx.dump_xml())
    elif args.out_format == 'yaml':
        print(sx.dump())
    else:
        assert False
