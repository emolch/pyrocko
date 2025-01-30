# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Main entry point for Gato GUI.
'''

import gc
from .window import GatoWindow


def main(make_squirrel, instant_close=False):
    '''
    Launch Gato GUI.
    '''

    from pyrocko import util, progress
    from pyrocko.gui import util as gui_util

    util.setup_logging('gato', 'info')
    progress.set_default_viewer('gui')

    global win

    app = gui_util.get_app()
    win = GatoWindow(make_squirrel=make_squirrel, instant_close=instant_close)
    app.set_main_window(win)

    gui_util.app.install_sigint_handler()

    try:
        gui_util.app.exec_()
    finally:
        gui_util.app.uninstall_sigint_handler()
        app.unset_main_window()
        del win
        gc.collect()
