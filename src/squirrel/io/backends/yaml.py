# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel IO adaptor to read YAML files.
'''

import logging

from pyrocko.io.io_common import get_stats, touch  # noqa
from pyrocko import model as pmodel
from ... import model

from pyrocko import guts

logger = logging.getLogger('psq.io.yaml')


def provided_formats():
    return ['yaml']


def detect_pyrocko_yaml(first512):
    try:
        first512 = first512.decode('utf-8')
    except UnicodeDecodeError:
        return False

    for line in first512.splitlines():
        if line.startswith('--- !pf.'):
            return True

    return False


def detect(first512):
    if detect_pyrocko_yaml(first512):
        return 'yaml'

    return None


def iload(format, file_path, segment, content):
    for iobj, obj in enumerate(guts.iload_all(filename=file_path)):
        if isinstance(obj, pmodel.Event):
            nut = model.make_event_nut(
                file_segment=0,
                file_element=iobj,
                codes=model.CodesX(obj.catalog or ''),
                tmin=obj.time,
                tmax=obj.time)

            if 'event' in content:
                nut.content = obj

            yield nut
