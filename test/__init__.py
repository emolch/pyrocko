from __future__ import division, print_function, absolute_import
import os
from . import common
import pyrocko

pyrocko.grumpy = 2

from pyrocko import util  # noqa

if not int(os.environ.get('MPL_SHOW', False)):
    common.matplotlib_use_agg()
