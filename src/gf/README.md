
## Pyrocko-GF: storage and calculation of synthetic seismograms

The `pyrocko.gf` subpackage splits functionality into several submodules:

* The `pyrocko.gf.store` module deals with the storage, retrieval and summation of Green's functions.
* The `pyrocko.gf.meta` module provides data structures for the meta information associated with the Green's function stores and implements various the Green's function lookup indexing schemes.
* The `pyrocko.gf.builder` module defines a common base for Green's function store builders.
* The `pyrocko.gf.seismosizer` module provides high level synthetic seismogram synthesis.

All classes defined in the `pyrocko.gf` submodules are imported into the
`pyrocko.gf` namespace, so user scripts may simply use ``from pyrocko
import gf`` or ``from pyrocko.gf import *`` for convenience.
