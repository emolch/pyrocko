# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`gato gui`.
'''


headline = 'Gato graphical user interface.'

description = headline + '''

Start the graphical user interface of Gato.
'''


def make_subparser(subparsers):
    return subparsers.add_parser(
        'gui',
        help=headline,
        description=description)


def setup(parser):
    parser.add_argument(
        '--instant-close',
        dest='instant_close',
        default=False,
        action='store_true',
        help='Close window without confimation.')

    parser.add_squirrel_selection_arguments()


def run(parser, args):
    from pyrocko.gato.gui.main import main

    def make_squirrel():
        return args.make_squirrel()

    main(make_squirrel=make_squirrel, instant_close=args.instant_close)
