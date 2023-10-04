# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel response`.
'''

import logging

from ..common import ldq
from pyrocko.squirrel.error import ToolError

logger = logging.getLogger('psq.cli.response')

headline = 'Print instrument response information.'


def indent(prefix, nfirst, n, message):
    return '\n'.join(
        prefix + ' ' * (nfirst if i == 0 else n) + line
        for i, line in enumerate(message.splitlines()))


def make_subparser(subparsers):
    return subparsers.add_parser(
        'response',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments(without=['kinds'])

    level_choices = ['response', 'stages']

    parser.add_argument(
        '--level',
        choices=level_choices,
        dest='level',
        default='response',
        help='Set level of detail to be printed. Choices: %s'
        % ldq(level_choices))

    parser.add_argument(
        '--problems',
        action='store_true',
        dest='problems',
        default=False,
        help='Print attached warnings and error messages.')

    parser.add_argument(
        '--plot',
        action='store_true',
        dest='plot',
        default=False,
        help='Create Bode plot showing the responses.')

    parser.add_argument(
        '--fmin',
        dest='fmin',
        type=float,
        default=0.01,
        help='Minimum frequency [Hz], default: 0.01')

    parser.add_argument(
        '--fmax',
        dest='fmax',
        type=float,
        default=100.,
        help='Maximum frequency [Hz], default: 100')

    parser.add_argument(
        '--normalize',
        dest='normalize',
        action='store_true',
        help='Normalize response to be 1 on flat part.')

    parser.add_argument(
        '--save',
        dest='out_path',
        help='Save figure to file.')

    parser.add_argument(
        '--dpi',
        dest='dpi',
        type=float,
        default=100.,
        help='DPI setting for pixel image output, default: 100')

    parser.add_argument(
        '--stages',
        dest='stages',
        metavar='START:STOP',
        help='Show response of selected stages. Indexing is Python style: '
             'count starts at zero, negative values count from the end.')

    input_quantity_choices = ['displacement', 'velocity', 'acceleration']

    parser.add_argument(
        '--input-quantity',
        dest='input_quantity',
        choices=input_quantity_choices,
        metavar='QUANTITY',
        help='Show converted response for given input quantity. choices: %s'
        % ldq(input_quantity_choices))

    parser.add_argument(
        '--show-breakpoints',
        dest='show_breakpoints',
        action='store_true',
        default=False,
        help='Show breakpoints of pole-zero responses.')

    parser.add_argument(
        '--index-labels',
        dest='index_labels',
        action='store_true',
        default=False,
        help='Label graphs only by index and print details to terminal '
             'to save space when many labels would be shown. Aggregate '
             'identical responses under a common index.')


def run(parser, args):
    squirrel = args.make_squirrel()

    stages = (None, None)
    if args.stages:
        words = args.stages.split(':')
        try:
            if len(words) == 1:
                stages = (int(words[0]), int(words[0])+1)
            elif len(words) == 2:
                stages = tuple(int(word) if word else None for word in words)
            else:
                raise ValueError()

        except ValueError:
            raise ToolError('Invalid --stages argument.')

    data = []
    for response in squirrel.get_responses(**args.squirrel_query):
        print(response.summary)
        if args.problems:
            for level, message, _ in response.log:
                print('!   %s: %s' % (
                    level.capitalize(),
                    indent('!', 0, 5, message)))

        if args.level == 'stages':
            for stage in response.stages[slice(*stages)]:
                print('  %s' % stage.summary)
                if args.problems:
                    for level, message, _ in stage.log:
                        print('!     %s: %s' % (
                            level.capitalize(),
                            indent('!', 0, 7, message)))

        data.append((
            ', '.join([
                str(response.codes),
                response.str_time_span_short,
                response.summary_log,
                response.summary_quantities]),
            response.get_effective(
                input_quantity=args.input_quantity,
                stages=stages)))

    if args.plot:
        if not data:
            logger.warning('No response objects found.')
            return

        labels, resps = [list(x) for x in zip(*data)]

        from pyrocko.plot.response import plot
        plot(
            resps,
            fmin=args.fmin,
            fmax=args.fmax,
            nf=200,
            normalize=args.normalize,
            labels=labels,
            filename=args.out_path,
            dpi=args.dpi,
            show_breakpoints=args.show_breakpoints,
            separate_combined_labels='print' if args.index_labels else None)
