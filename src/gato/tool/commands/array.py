# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`gato array`.
'''

from pyrocko import progress

from pyrocko.squirrel import SquirrelCommand, Squirrel
from pyrocko.squirrel.tool.common import dq, ldq

from pyrocko.gato.array import \
    get_named_arrays_dataset, SensorArray, SensorArrayType


from pyrocko.gato.tool.common import add_array_selection_arguments, \
    get_matching_arrays


class List(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'list',
            help='List array setups.',
            description='List array setups.')

    def setup(self, parser):
        add_array_selection_arguments(parser)

        style_choices = ['summary', 'yaml', 'name']

        parser.add_argument(
            '--style',
            dest='style',
            choices=style_choices,
            default='summary',
            help='Set style of presentation. Choices: %s' % ldq(style_choices))

    def run(self, parser, args):
        arrays = get_matching_arrays(
            args.array_names, args.array_paths, args.use_builtin_arrays)

        for array in arrays.values():
            if args.style == 'name':
                print(array.name)
            elif args.style == 'summary':
                print(array.summary2)
            else:
                print('#', array.summary2)
                print(array)


class Info(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'info',
            help='Print information about array.',
            description='Print information about array.')

    def setup(self, parser):
        add_array_selection_arguments(parser)

        style_choices = ['summary', 'yaml']

        parser.add_argument(
            '--style',
            dest='style',
            choices=style_choices,
            default='summary',
            help='Set style of presentation. Choices: %s' % ldq(style_choices))

        parser.add_squirrel_query_arguments(without=['codes', 'kinds'])

    def run(self, parser, args):

        arrays = get_matching_arrays(
            args.array_names, args.array_paths, args.use_builtin_arrays)
        names = sorted(arrays.keys())

        sq = Squirrel()
        sq.add_dataset(get_named_arrays_dataset(names))

        with progress.view():
            sq.update()

        print('#', ' | '.join([
            'name',
            'type',
            'num. sites',
            'num. channels',
            'start date',
            'end date',
            'interstation distances min, 10%, 50%, 90%, max [km]',
            'channel group: num. sites']))

        for name, array in arrays.items():
            info = array.get_info(sq, **args.squirrel_query)
            if args.style == 'summary':
                print(' | '.join((array.summary, info.summary)))
            elif args.style == 'yaml':
                print('#', ' | '.join((array.summary, info.summary)))
                print(info)


class Sensors(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'sensors',
            help='Print information about sensors of an array.',
            description='Print information about sensors of an array.')

    def setup(self, parser):
        add_array_selection_arguments(parser)

        style_choices = ['summary', 'yaml']

        parser.add_argument(
            '--style',
            dest='style',
            choices=style_choices,
            default='summary',
            help='Set style of presentation. Choices: %s' % ldq(style_choices))

        parser.add_squirrel_query_arguments(without=['codes', 'kinds'])

    def run(self, parser, args):

        arrays = get_matching_arrays(
            args.array_names, args.array_paths, args.use_builtin_arrays)

        names = sorted(arrays.keys())

        sq = Squirrel()
        sq.add_dataset(get_named_arrays_dataset(names))

        with progress.view():
            sq.update()

        for name, array in arrays.items():
            info = array.get_info(sq, **args.squirrel_query)
            for sensor in info.sensors:
                if args.style == 'summary':
                    print(sensor.summary)
                elif args.style == 'yaml':
                    print('# ' + sensor.summary)
                    print(sensor)


class Create(SquirrelCommand):

    def make_subparser(self, subparsers):
        return subparsers.add_parser(
            'create',
            help='New array definition based on available metadata.',
            description='''New array definition based on available metadata.

Create a named selection of sensors to be used as a Gato array from
available station metadata.
''')

    def setup(self, parser):

        parser.add_argument(
            '--name',
            dest='name',
            help='Set array name.')

        array_types = SensorArrayType.choices
        parser.add_argument(
            '--type',
            metavar='TYPE',
            default='seismic',
            choices=array_types,
            help='Set array type. Default: %s. Choices: %s' % (
                dq('seismic'),
                ldq(array_types)))

        parser.add_argument(
            '--comment',
            dest='comment',
            help='Set comment.')

        parser.add_squirrel_selection_arguments()
        parser.add_squirrel_query_arguments()

    def run(self, parser, args):
        sq = args.make_squirrel()
        sensors = sq.get_sensors(**args.squirrel_query)
        codes = set()
        for sensor in sensors:
            codes.add(sensor.codes)

        array = SensorArray(
            name=args.name,
            codes=sorted(codes),
            type=args.type,
            comment=args.comment)

        print(array)


headline = 'Manage array setups.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'array',
        help=headline,
        subcommands=[List(), Info(), Sensors(), Create()],
        description=headline + '''

Inspect array configurations, list builtin and custom arrays and define new
array setups.
''')


def setup(parser):
    pass


def run(parser, args):
    parser.print_help()
