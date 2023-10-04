# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Sparrow - geospatial data visualization.
'''


def main():
    '''
    CLI entry point for Pyrocko's ``sparrow`` app.
    '''
    from pyrocko.gui.sparrow import cli
    cli.main()
