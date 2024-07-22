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

from pyrocko.guts import List, load, StringPattern, String

from ..has_paths import HasPaths
from .client.base import Source
from .client.catalog import CatalogSource
from .client.fdsn import FDSNSource
from .error import SquirrelError
from .selection import re_persistent_name
from .operators.base import Operator

guts_prefix = 'squirrel'

logger = logging.getLogger('psq.dataset')

km = 1000.


class PersistentID(StringPattern):
    pattern = re_persistent_name


def make_builtin_datasets():
    datasets = {}
    for site in ['isc', 'geofon', 'gcmt']:
        for magnitude_min in [4.0, 5.0, 6.0, 7.0]:
            name = 'events-%s-m%g' % (site, magnitude_min)
            datasets[name] = Dataset(
                sources=[
                    CatalogSource(
                        catalog=site,
                        query_args=dict(magmin=magnitude_min))],
                comment='Event catalog: %s, minimum magnitude: %g' % (
                    site, magnitude_min))

    for site in ['geofon', 'gcmt']:
        depth_min = 100*km
        for magnitude_min in [6.0, 7.0]:
            name = 'events-%s-m%g-d%g' % (site, magnitude_min, depth_min/km)
            datasets[':' + name] = Dataset(
                sources=[
                    CatalogSource(
                        catalog=site,
                        query_args=dict(
                            magmin=magnitude_min,
                            depthmin=depth_min))],
                comment='Event catalog: %s, minimum magnitude: %g, '
                        'minimum depth: %g km' % (
                    site,
                    magnitude_min,
                    depth_min/km))

    for site, network, cha in [
            ('bgr', 'gr', 'lh'),
            ('up', None, None)]:
        name = 'fdsn-' + '-'.join(
            x for x in (site, network, cha) if x is not None)

        query_args = {}
        comments = ['FDSN: %s' % site]

        if network is not None:
            query_args['network'] = network.upper()
            comments.append('network: %s' % query_args['network'])

        if cha is not None:
            query_args['channel'] = cha.upper() + '?'
            comments.append('channels: %s' % query_args['channel'])

        datasets[':' + name] = Dataset(
            sources=[FDSNSource(site=site, query_args=query_args)],
            comment=', '.join(comments))

    for site, net, sta in [
            ('bgr', 'gr', 'bfo')]:
        name = 'fdsn-%s-%s-%s' % (site, net, sta)
        sta = sta.upper()
        net = net.upper()
        datasets[name] = Dataset(
            sources=[
                FDSNSource(
                    site=site,
                    query_args=dict(network=net, station=sta))],
            comment='FDSN: %s, network: %s, '
                    'station: %s' % (site, net, sta))

    return datasets


g_builtin_datasets = None


def get_builtin_datasets():
    global g_builtin_datasets
    g_builtin_datasets = make_builtin_datasets()
    return g_builtin_datasets


class Dataset(HasPaths):
    '''
    Dataset description.
    '''
    sources = List.T(Source.T())
    operators = List.T(Operator.T())
    comment = String.T(optional=True)

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

    if path.startswith(':'):
        name = path[1:]
        datasets = get_builtin_datasets()
        try:
            return datasets[name]
        except KeyError:
            raise SquirrelError(
                ('No dataset name given. '
                 if not name else 'Named dataset not found: %s' % name) +
                '\n  Use `squirrel dataset` to get information about '
                'available datasets. Available:\n'
                '    %s' % '\n    '.join(
                    sorted(datasets.keys())))

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
