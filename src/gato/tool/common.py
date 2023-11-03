# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Gato command line tool utilities.
'''

from pyrocko.util import glob_filter, GlobFilterNoMatch

from pyrocko.gato.array import \
    get_named_arrays, SensorArray
from pyrocko.gato.error import GatoToolError
from pyrocko.gato.io import load_all


def add_array_selection_arguments(parser):

    parser.add_argument(
        '--custom',
        dest='array_paths',
        nargs='+',
        metavar='PATH',
        default=[],
        help='Add array definitions from file.')

    parser.add_argument(
        '--builtin',
        dest='use_builtin_arrays',
        action='store_true',
        help='Add builtin array definitions.')

    parser.add_argument(
        '--arrays',
        dest='array_names',
        metavar='NAME',
        nargs='+',
        help='Select arrays to be used by names or glob-patterns. The arrays '
             'must be defined using --custom or/and --builtin.')


def get_matching_arrays(name_patterns, array_paths, use_builtin_arrays):
    arrays = {}
    if use_builtin_arrays:
        arrays.update(get_named_arrays())

    for array_path in array_paths:
        for array in load_all(array_path, want=SensorArray):
            array.set_defined_in(array_path)

            if array.name in arrays:
                raise GatoToolError(
                    'Duplicate array name: %s\n'
                    '  defined in: %s\n'
                    '  also defined in: %s' % (
                        array.name,
                        arrays[array.name].get_defined_in(),
                        array.get_defined_in()))

            if array.name.startswith(':'):
                raise GatoToolError(
                    'Invalid array name: "%s". Names starting with ":" are '
                    'reserved for built-in arrays.' % array.name)

            arrays[array.name] = array

    names = [array.name for array in arrays.values()]
    try:
        matching_names = set(glob_filter(
            name_patterns, names, raise_if_nomatch=True))
    except GlobFilterNoMatch as e:
        raise GatoToolError(str(e)) from None

    return dict(
        (array.name, array)
        for array in arrays.values()
        if array.name in matching_names)
