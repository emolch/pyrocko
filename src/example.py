# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Example data download helpers.
'''

import os
from pyrocko import util
import logging


logger = logging.getLogger('pyrocko.example')


def get_example_data(filename, url=None, recursive=False):
    '''
    Download example data file needed in tutorials.

    The file is downloaded to given ``filename``. If there already exists a
    file with that name, nothing is done.

    :param filename: name of the required file
    :param url: if not ``None`` get file from given URL otherwise fetch it from
        http://data.pyrocko.org/examples/<filename>.
    :returns: ``filename``
    '''

    if not os.path.exists(filename):
        url = 'http://data.pyrocko.org/examples/' + filename
        if recursive:
            util.download_dir(url, filename)
        else:
            util.download_file(url, filename)

    return filename
