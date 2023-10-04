# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Snuffler - seismogram browser and workbench.
'''

from pyrocko.gui.snuffler import snuffler


def main(args=None):
    '''
    CLI entry point for Pyrocko's ``snuffler`` app.
    '''
    snuffler.snuffler_from_commandline(args=args)


if __name__ == '__main__':
    main()
