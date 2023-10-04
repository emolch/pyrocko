# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel codes`.
'''


from pyrocko.squirrel.model import to_kind


headline = 'Get summary of available station/channel codes.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'codes',
        help=headline,
        description=headline)


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments(without=['time', 'tmin', 'tmax'])


def run(parser, args):
    from pyrocko import squirrel as sq

    squirrel = args.make_squirrel()

    kwargs = args.squirrel_query
    kinds = kwargs.pop('kind', sq.supported_content_kinds())
    codes_query = kwargs.pop('codes', None)

    for kind in kinds:
        for kind_id, codes, deltat, _, count in sorted(
                squirrel._iter_codes_info(kind=kind, codes=codes_query)):
            print(to_kind(kind_id), codes, deltat, count)
