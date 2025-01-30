# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from pyrocko.squirrel.error import ToolError


class GatoError(Exception):
    pass


class GatoToolError(ToolError):
    pass
