# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Handling of pre-computed Green's functions and calculation of synthetic
seismograms.

The `pyrocko.gf` subpackage splits functionality into several main submodules:

* The :py:class:`pyrocko.gf.store` module deals with the storage, retrieval and
  summation of Green's functions.
* The :py:class:`pyrocko.gf.meta` module provides data structures for the meta
  information associated with the Green's function stores and implements
  various the Green's function lookup indexing schemes.
* The :py:class:`pyrocko.gf.builder` module defines a common base for Green's
  function store builders.
* The :py:class:`pyrocko.gf.seismosizer` module provides high level synthetic
  seismogram synthesis.
* The :py:class:`pyrocko.gf.targets` module provides data structures for
  different receiver types.

All classes defined in the `pyrocko.gf` submodules are imported into the
`pyrocko.gf` namespace, so user scripts may simply use ``from pyrocko
import gf`` or ``from pyrocko.gf import *`` for convenience.
'''

from .error import *  # noqa
from .meta import *  # noqa
from .store import *  # noqa
from .builder import *  # noqa
from .seismosizer import *  # noqa
from .targets import *  # noqa
from . import tractions # noqa
