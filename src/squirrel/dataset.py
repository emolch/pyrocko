# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Portable dataset description.

The :py:class:`Dataset` class defines sets of local and remote data-sources to
be used in combination in Squirrel-based programs. By convention,
Squirrel-based programs accept the ``--dataset`` option to read such dataset
descriptions from file. To add a dataset programmatically, to a
:py:class:`~pyrocko.squirrel.base.Squirrel` instance, use
:py:meth:`~pyrocko.squirrel.base.Squirrel.add_dataset`.
'''

import os.path as op
import logging

from pyrocko.guts import List, load, StringPattern

from ..has_paths import HasPaths
from .client.base import Source
from .error import SquirrelError
from .selection import re_persistent_name
from .operators.base import Operator

guts_prefix = 'squirrel'

logger = logging.getLogger('psq.dataset')


class PersistentID(StringPattern):
    pattern = re_persistent_name


class Dataset(HasPaths):
    '''
    Dataset description.
    '''
    sources = List.T(Source.T())
    operators = List.T(Operator.T())

    def setup(self, squirrel, check=True):
        for source in self.sources:
            squirrel.add_source(
                source, check=check)

        for operator in self.operators:
            squirrel.add_operator(operator)

        squirrel.update_operator_mappings()


def read_dataset(path):
    '''
    Read dataset description file.
    '''
    try:
        dataset = load(filename=path)
    except OSError:
        raise SquirrelError(
            'Cannot read dataset file: %s' % path)

    if not isinstance(dataset, Dataset):
        raise SquirrelError('Invalid dataset file "%s".' % path)

    dataset.set_basepath(op.dirname(path) or '.')
    return dataset


__all__ = [
    'PersistentID',
    'Dataset',
    'read_dataset',
]
