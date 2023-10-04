# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Drum - interactive drum plot to display continuous seismic waveforms.
'''

from __future__ import absolute_import, print_function, division


def main():
    '''
    CLI entry point for Pyrocko's ``drum`` app.
    '''
    from pyrocko.gui.drum import cli
    cli.main()
