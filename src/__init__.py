# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

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


def make_squirrel(*args, **kwargs):
    from pyrocko.squirrel import Squirrel
    return Squirrel(*args, **kwargs)


def sparrow(*args, **kwargs):
    '''
    Start Sparrow.

    Calls :py:func:`pyrocko.gui.sparrow.main`.
    '''

    check_have_vtk()

    from pyrocko.gui.sparrow.main import main
    return main(*args, **kwargs)


class DependencyMissing(Exception):
    pass


class DependencyMissingVTK(DependencyMissing):
    pass


def check_have_vtk():
    import sys

    try:
        import vtk  # noqa
    except ImportError:
        message = '''VTK is not available.

Either VTK is not installed or it does not support the currently running
version of Python (Python%i).''' % sys.version_info.major

        raise DependencyMissingVTK(message)

    try:
        from vtk.qt.QVTKRenderWindowInteractor \
            import QVTKRenderWindowInteractor

        QVTKRenderWindowInteractor
    except ImportError:
        message = 'The installed version of VTK is incompatible with Qt5.'
        raise DependencyMissing(message)
