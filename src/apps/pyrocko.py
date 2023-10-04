# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Pyrocko - package introspection.
'''

import sys
import logging

logger = logging.getLogger('main')


def main(args=None):
    '''
    CLI entry point for Pyrocko's ``pyrocko`` app.
    '''
    logging.basicConfig(
        level=logging.INFO,
        format='pyrocko:%(name)-25s - %(levelname)-8s - %(message)s')

    try:
        from pyrocko import squirrel

        class PrintVersion(squirrel.SquirrelCommand):
            def make_subparser(self, subparsers):
                return subparsers.add_parser(
                    'version',
                    help='Print version.',
                    description='Print version.')

            def setup(self, parser):
                parser.add_argument(
                    '--long',
                    dest='long',
                    action='store_true',
                    help='Print long version string.')

            def run(self, parser, args):
                import pyrocko
                if args.long:
                    print(pyrocko.long_version)
                else:
                    print(pyrocko.__version__)

        class PrintDependencies(squirrel.SquirrelCommand):
            def make_subparser(self, subparsers):
                return subparsers.add_parser(
                    'dependencies',
                    help='Print versions of available dependencies.',
                    description='Print versions of available dependencies.')

            def setup(self, parser):
                pass

            def run(self, parser, args):
                from pyrocko import deps
                deps.print_dependencies()

        class PrintInfo(squirrel.SquirrelCommand):
            def make_subparser(self, subparsers):
                return subparsers.add_parser(
                    'info',
                    help='Print information about Pyrocko installation(s).',
                    description='Print information about Pyrocko '
                                'installation(s).')

            def setup(self, parser):
                pass

            def run(self, parser, args):
                from pyrocko import deps
                print()
                print('Python executable:\n  %s' % sys.executable)
                print()
                deps.print_installations()

        squirrel.run(
            args=args,
            prog='pyrocko',
            subcommands=[
                PrintVersion(),
                PrintDependencies(),
                PrintInfo()],
            description='Tools for seismology.')

    except ImportError as e:
        from pyrocko import deps
        logger.info('\n' + deps.str_dependencies())
        logger.info('\n' + deps.str_installations())

        try:
            deps.require_all('required')

        except deps.MissingPyrockoDependency as e2:
            logger.fatal(str(e2))
            sys.exit(1)

        logger.fatal(str(e))
        sys.exit(1)


if __name__ == '__main__':
    main()
