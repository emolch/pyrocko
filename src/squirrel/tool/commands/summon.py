# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel summon`.
'''

import math
import logging

from pyrocko.squirrel.error import SquirrelError
from pyrocko import progress, guts, util

logger = logging.getLogger('psq.cli.summon')

headline = 'Fill local cache.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'summon',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments()
    parser.add_argument(
        '--channel-priorities',
        dest='channel_priorities',
        metavar='CHA',
        help='''
List of 2-character band/instrument code combinations to try. For example,
giving ```HH,BH``` would first try to get ```HH?``` channels and then fallback
to ```BH?``` if these are not available. The first matching waveforms are
returned. Use in combination with ``--sample-rate-min`` and
``--sample-rate-max`` to constrain the sample rate.
'''.strip())

    parser.add_argument(
        '--sample-rate-min',
        dest='sample_rate_min',
        metavar='FLOAT',
        type=float,
        help='Minimum sample rate [Hz] to consider.')

    parser.add_argument(
        '--sample-rate-max',
        dest='sample_rate_max',
        metavar='FLOAT',
        type=float,
        help='Maximum sample rate [Hz] to consider.')

    parser.add_argument(
        '--get-events',
        dest='get_events',
        action='store_true',
        help='Get only time spans with events.')

    parser.add_argument(
        '--event-time-span',
        dest='event_time_span',
        metavar='DURATION,DURATION',
        help='Set time span to be completed for events, e.g. `-30m,2h`.')


def run(parser, args):
    d = args.squirrel_query
    squirrel = args.make_squirrel()

    if args.get_events:
        events = squirrel.get_events(
            tmin=d.get('tmin', None),
            tmax=d.get('tmax', None))

        if not args.event_time_span:
            raise SquirrelError(
                'Time span setting needed. Currently --event-time-span is '
                'required when using --get-events.')

        try:
            span_tmin, span_tmax = [
                guts.parse_duration(s)
                for s in args.event_time_span.split(',')]

        except Exception:
            raise SquirrelError(
                'Invalid argument to --event-time-span: %s'
                % args.event_time_span)

        groups = [
            (event.time + span_tmin, event.time + span_tmax, event.name)
            for event in events]
    else:
        if 'tmin' not in d or 'tmax' not in d:
            raise SquirrelError('Time span required.')

        groups = [(d['tmin'], d['tmax'], '')]

    d.pop('tmin', None)
    d.pop('tmax', None)

    tinc = 3600.

    channel_priorities = None
    if args.channel_priorities:
        channel_priorities = [
            cha.strip() for cha in args.channel_priorities.split(',')]

    with progress.view():
        task_group = progress.task('Group', len(groups))

        for group_tmin, group_tmax, group_name in task_group(groups):
            if group_name:
                logger.info('Summoning group: %s (%s - %s)' % (
                    group_name,
                    util.time_to_str(group_tmin),
                    util.time_to_str(group_tmax)))

            tmin = math.floor(group_tmin / tinc) * tinc
            tmax = math.ceil(group_tmax / tinc) * tinc
            nwindows = int(round((tmax - tmin) / tinc))
            task = progress.task('Summoning', nwindows)
            iwindow = 0
            try:
                for trs in squirrel.chopper_waveforms(
                        tinc=tinc,
                        load_data=False,
                        channel_priorities=channel_priorities,
                        sample_rate_min=args.sample_rate_min,
                        sample_rate_max=args.sample_rate_max,
                        tmin=tmin,
                        tmax=tmax,
                        **d):

                    iwindow += 1
                    task.update(iwindow)

            finally:
                task.done()

    stats = str(squirrel)
    stats = '\n'.join('  ' + s for s in stats.splitlines())

    logger.info('Squirrel stats:\n%s' % stats)
