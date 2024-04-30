# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Prompt seismological data access with a fluffy tail.

.. image:: /static/squirrel.svg
   :align: left

.. raw:: html

   <div style="clear:both"></div>

This is the reference manual for the Squirrel framework. It describes the API
of the :py:mod:`pyrocko.squirrel` subpackage. For a conceptual overview see
:doc:`/topics/squirrel`. A tutorial describing the API usage is provided at
:doc:`Examples: Squirrel powered data access
</library/examples/squirrel/index>`.

.. rubric:: Usage

Public symbols implemented in the various submodules are aggregated into the
:py:mod:`pyrocko.squirrel` namespace for use in user programs::

    from pyrocko.squirrel import Squirrel

    sq = Squirrel()

.. rubric:: Implementation overview

The central class and interface of the framework is
:py:class:`~pyrocko.squirrel.base.Squirrel`, part of it is implemented in its
base class :py:class:`~pyrocko.squirrel.selection.Selection`. Core
functionality directly talking to the database is implemented in
:py:mod:`~pyrocko.squirrel.base`, :py:mod:`~pyrocko.squirrel.selection` and
:py:mod:`~pyrocko.squirrel.database`. The data model of the framework is
implemented in :py:mod:`~pyrocko.squirrel.model`. User project environment
detection is implemented in :py:mod:`~pyrocko.squirrel.environment`. Portable
dataset description in :py:mod:`~pyrocko.squirrel.dataset`. A unified IO
interface bridging to various Pyrocko modules outside of the Squirrel framework
is available in :py:mod:`~pyrocko.squirrel.io`. Memory cache management is
implemented in :py:mod:`~pyrocko.squirrel.cache`. Compatibility with Pyrocko's
older waveform archive access module is implemented in
:py:mod:`~pyrocko.squirrel.pile`.

'''


from . import base, selection, database, model, io, client, tool, error, \
    environment, dataset, operators, check, storage, streaming

from .base import *  # noqa
from .selection import *  # noqa
from .database import *  # noqa
from .model import *  # noqa
from .io import *  # noqa
from .client import *  # noqa
from .tool import *  # noqa
from .error import *  # noqa
from .environment import *  # noqa
from .dataset import *  # noqa
from .operators import *  # noqa
from .check import *  # noqa
from .storage import *  # noqa
from .streaming import *  # noqa

__all__ = base.__all__ + selection.__all__ + database.__all__ \
    + model.__all__ + io.__all__ + client.__all__ + tool.__all__ \
    + error.__all__ + environment.__all__ + dataset.__all__ \
    + operators.__all__ + check.__all__ + storage.__all__ + streaming.__all__
