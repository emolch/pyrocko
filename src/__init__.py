# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import

from .info import *  # noqa
__version__ = version  # noqa

grumpy = 0  # noqa


class ExternalProgramMissing(Exception):
    pass
