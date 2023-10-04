# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel IO adaptor for virtual files.
'''

import time
from collections import defaultdict
from pyrocko.io.io_common import FileLoadError


def provided_formats():
    return ['virtual']


def detect(first512):
    return None


class UniqueKeyRequired(Exception):
    pass


def get_stats(file_path):
    try:
        return float(data_mtimes[file_path]), 0
    except KeyError:
        raise FileLoadError(file_path)


def touch(file_path):
    try:
        data_mtimes[file_path] = time.time()
    except KeyError:
        raise FileLoadError(file_path)


data = defaultdict(list)
data_mtimes = {}


def add_nuts(nuts):
    file_paths = set()
    for nut in nuts:
        file_paths.add(nut.file_path)
        data[nut.file_path].append(nut)

    for file_path in file_paths:
        data[file_path].sort(
            key=lambda nut: (nut.file_segment, nut.file_element))
        ks = set()
        for nut in data[file_path]:
            k = nut.file_segment, nut.file_element
            if k in ks:
                raise UniqueKeyRequired()

            ks.add(k)

        mtime = max(nut.file_mtime or 0 for nut in data[file_path])
        old_mtime = data_mtimes.get(file_path, None)
        if old_mtime is None:
            data_mtimes[file_path] = mtime
        else:
            data_mtimes[file_path] = old_mtime + 1


def remove(file_paths):
    for file_path in file_paths:
        del data[file_path]


def iload(format, file_path, segment, content):
    assert format == 'virtual'

    for nut in data[file_path]:
        if segment is None or segment == nut.file_segment:
            yield nut
