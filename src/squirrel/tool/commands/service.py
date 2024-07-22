# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Implementation of :app:`squirrel service`.
'''

import logging
from pyrocko.squirrel.service import server


logger = logging.getLogger('psq.cli.service')

headline = 'Fire up web UI.'


def make_subparser(subparsers):
    return subparsers.add_parser(
        'service',
        help=headline,
        description=headline + '''


''')


def setup(parser):
    parser.add_squirrel_selection_arguments()
    parser.add_squirrel_query_arguments(without='kinds')

    parser.add_argument(
        '--port',
        dest='port',
        type=int,
        default=2323,
        metavar='INT',
        help='Set the port to bind to.')

    parser.add_argument(
        '--host',
        dest='host',
        default='localhost',
        help='IP address to bind to, or ```public``` to bind to what appears '
             'to be the public IP of the host in the local network, '
             'or ```all``` to bind to all available interfaces, or '
             '```localhost``` (default).')

    parser.add_argument(
        '--open',
        dest='open',
        action='store_true',
        default=False,
        help='Open in web browser.')

    parser.add_argument(
        '--page',
        dest='page_path',
        metavar='PATH',
        help='Serve custom pages from PATH.')

    parser.add_argument(
        '--debug',
        dest='debug',
        action='store_true',
        default=False,
        help='Activate debug mode. In debug mode, server tracebacks are shown '
             'in the browser, verbosity level of the server logger is '
             'increased, auto-restart on module change is activated, and '
             'static pages are served from the Pyrocko sources directory (if '
             'available and not overridden with ``--page``) rather than from '
             'the installed files.')


def run(parser, args):
    squirrel = args.make_squirrel()
    gates = {
        'default': server.Gate.from_query_arguments(**args.squirrel_query),
    }

    server.run(
        squirrel=squirrel,
        gates=gates,
        host=args.host,
        port=args.port,
        open=args.open,
        debug=args.debug,
        page_path=args.page_path)
