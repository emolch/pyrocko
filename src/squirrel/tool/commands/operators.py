# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel operators`.
'''

guts_prefix = 'squirrel'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'operators',
        help='Print available operator mappings.')


def setup(parser):
    parser.add_squirrel_selection_arguments()


def run(parser, args):
    squirrel = args.make_squirrel()

    def scodes(codes):
        css = list(zip(*codes))
        if sum(not all(c == cs[0] for c in cs) for cs in css) == 1:
            return '.'.join(
                cs[0] if all(c == cs[0] for c in cs) else '(%s)' % ','.join(cs)
                for cs in css)
        else:
            return ', '.join(str(c) for c in codes)

    for operator, in_codes, out_codes in squirrel.get_operator_mappings():
        print('%s <- %s <- %s' % (
            scodes(out_codes), operator.name, scodes(in_codes)))
