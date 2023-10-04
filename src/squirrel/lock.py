# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Directory locking utility.
'''

import os
import logging

op = os.path
logger = logging.getLogger('psq.lock')


class LockDir(object):

    def __init__(self, path):
        self._path = path
        self._lockfile = op.join(path, '.buried')

    def __enter__(self):
        if op.exists(self._lockfile):
            raise EnvironmentError('Directory "%s" is locked' % self._path)

        with open(self._lockfile, 'wb') as f:
            f.write(b'')
        logger.debug('Locked directory "%s"', self._path)
        return self

    def __exit__(self, type, value, traceback):
        try:
            os.remove(self._lockfile)
            logger.debug('Unlocked directory "%s"', self._path)
        except FileNotFoundError:
            logger.warning(
                'Lockfile "%s" was removed unintentionally', self._lockfile)
