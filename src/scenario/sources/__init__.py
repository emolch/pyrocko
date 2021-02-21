# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, division, print_function

from .base import *  # noqa
from .dcsource import *  # noqa
from .rectangularsource import *  # noqa
from .pseudodynrupture import *  # noqa

AVAILABLE_SOURCES = [
    DCSourceGenerator, RectangularSourceGenerator,  # noqa
    PseudoDynamicRuptureGenerator]  # noqa
