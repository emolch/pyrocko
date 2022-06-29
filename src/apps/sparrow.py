# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import sys
import pyrocko


def main():
    try:
        pyrocko.sparrow()

    except pyrocko.DependencyMissingVTK as e:
        message = str(e)

        if sys.version_info.major in (2, 3):
            message += '''

If you have installed Pyrocko under Python2 AND Python3, you can try to start
Sparrow as

    sparrow%i
''' % {3: 2, 2: 3}[sys.version_info.major]

        sys.exit(message)

    except pyrocko.DependencyMissing as e:
        sys.exit(str(e))
