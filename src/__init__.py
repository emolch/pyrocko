# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
A toolbox and library for seismology.
'''

import sys

try:
    from .info import *  # noqa
    __version__ = version  # noqa
except ImportError:
    pass  # not available in dev mode

grumpy = 0  # noqa


def get_logger():
    from .util import logging
    return logging.getLogger('pyrocko')


class ExternalProgramMissing(Exception):
    pass


def app_init(
        log_level='info',
        progress_viewer='terminal',
        program_name=None,
        multiprocessing_start_method='spawn'):

    '''
    Setup logging and progress indicators for Pyrocko scripts.

    This is a shortcut for calling :py:func:`pyrocko.util.setup_logging` and
    :py:func:`pyrocko.progress.set_default_viewer`.

    :param program_name:
        ``programname`` argument for :py:func:`pyrocko.util.setup_logging`
    :type program_name:
        str

    :param log_level:
        ``levelname`` argument for :py:func:`pyrocko.util.setup_logging`
    :type log_level:
        str

    :param progress_viewer:
        ``viewer`` argument for
        :py:func:`pyrocko.progress.set_default_viewer`
    '''
    from pyrocko import util, progress
    if program_name is None:
        program_name = sys.argv[0]

    util.setup_logging(sys.argv[0], log_level)
    progress.set_default_viewer(progress_viewer)
    import multiprocessing
    multiprocessing.set_start_method(multiprocessing_start_method)


def make_squirrel(*args, **kwargs):
    from pyrocko.squirrel import Squirrel
    return Squirrel(*args, **kwargs)


def snuffle(*args, **kwargs):
    '''
    Start Snuffler.

    Calls :py:func:`pyrocko.gui.snuffler.snuffler.snuffle`
    '''

    from pyrocko import deps

    deps.require('PyQt5.Qt')

    from pyrocko.gui.snuffler import snuffler
    return snuffler.snuffle(*args, **kwargs)


def sparrow(*args, **kwargs):
    '''
    Start Sparrow.

    Calls :py:func:`pyrocko.gui.sparrow.main`.
    '''

    from pyrocko import deps

    deps.require('vtk')
    deps.require('PyQt5.Qt')
    # deps.import_optional('kite', 'InSAR visualization')

    from pyrocko.gui.sparrow.main import main
    return main(*args, **kwargs)


def drum(*args, **kwargs):
    '''
    Start Drum Plot.

    Calls :py:func:`pyrocko.gui.drum.main`.
    '''

    from pyrocko import deps

    deps.require('PyQt5.Qt')
    deps.require('serial')

    from pyrocko.gui.drum.main import main
    return main(*args, **kwargs)
