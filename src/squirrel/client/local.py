# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Data-source definition providing access local data.
'''

import logging

from pyrocko.guts import List, StringChoice, String
from pyrocko import has_paths
from . import base
from .. import io

guts_prefix = 'squirrel'

logger = logging.getLogger('psq.client.local')


class FileFormat(StringChoice):
    choices = ['detect'] + io.supported_formats()


class ContentKind(StringChoice):
    choices = io.base.g_content_kinds


class LocalData(base.Source, has_paths.HasPaths):
    '''
    A collection of local files attachable as a Squirrel data-source.
    '''
    paths = List.T(
        has_paths.Path.T(),
        help='Directory and file paths to add to the Squirrel '
             'instance. See :py:meth:`Squirrel.add() '
             '<pyrocko.squirrel.base.Squirrel.add>`.')
    kinds = List.T(
        ContentKind.T(),
        optional=True,
        help='Content kinds to be added to the Squirrel selection. By default '
             'all known content kinds are added.')
    include = String.T(
        optional=True,
        help='If not ``None``, files are only included if their paths match '
             'the given regular expression pattern.')
    exclude = String.T(
        optional=True,
        help='If not ``None``, files are only included if their paths do not '
             'match the given regular expression pattern.')
    format = FileFormat.T(
        default='detect',
        help='Assume files are of given format.')

    def describe(self):
        return 'localdata'

    def setup(self, squirrel, check=True, upgrade=False):
        squirrel.add(
            self.expand_path(self.paths),
            kinds=self.kinds,
            include=self.include,
            exclude=self.exclude,
            format=self.format,
            check=check)


__all__ = [
    'FileFormat',
    'ContentKind',
    'LocalData']
