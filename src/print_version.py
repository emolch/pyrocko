# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Installation troubleshooting support module.

.. note::

    This module has been superseded by the :app:`pyrocko` command line tool.


    .. code-block::
        :caption: Get the installed version of Pyrocko

        pyrocko version

        # or when using a specific interpreter:
        python -m pyrocko.apps.pyrocko version

    .. code-block::
        :caption: Get the install versions of Pyrocko's prerequisites

        pyrocko dependencies

        # or when using a specific interpreter:
        python -m pyrocko.apps.pyrocko dependencies


Running this module from the command line will print the version of the
installed Pyrocko package or of its prerequisites.


.. code-block::
    :caption: Print the installed version of Pyrocko

    python -m pyrocko.print_version

.. code-block::
    :caption: Print the installed versions of Pyrocko's prerequisites

    python -m pyrocko.print_version deps

'''


import sys


def print_version(deps=False):
    import pyrocko
    if deps:
        print('pyrocko: %s' % pyrocko.long_version)
        try:
            import numpy
            print('numpy: %s' % numpy.__version__)
        except ImportError:
            print('numpy: N/A')

        try:
            import scipy
            print('scipy: %s' % scipy.__version__)
        except ImportError:
            print('scipy: N/A')

        try:
            import matplotlib
            print('matplotlib: %s' % matplotlib.__version__)
        except ImportError:
            print('matplotlib: N/A')

        try:
            from pyrocko.gui.qt_compat import Qt
            print('PyQt: %s' % Qt.PYQT_VERSION_STR)
            print('Qt: %s' % Qt.QT_VERSION_STR)
        except ImportError:
            print('PyQt: N/A')
            print('Qt: N/A')

        try:
            import vtk
            print('VTK: %s' % vtk.VTK_VERSION)
        except ImportError:
            print('VTK: N/A')

        print('python: %s.%s.%s' % sys.version_info[:3])

    elif sys.argv[1:] == ['short']:
        print(pyrocko.version)
    else:
        print(pyrocko.long_version)


if __name__ == '__main__':
    print_version(sys.argv[1:] == ['deps'])
