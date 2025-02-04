# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Squirrel IO adaptor to :py:mod:`pyrocko.io.rug`.
'''

from pyrocko.io.io_common import get_stats, touch  # noqa
from ... import model


def provided_formats():
    return ['rug']


def detect(first512):
    from pyrocko.io import rug

    if rug.detect(first512):
        return 'rug'
    else:
        return None


def iload(format, file_path, segment, content):
    assert format == 'rug'
    from pyrocko.io import rug

    load_data = 'carpet' in content

    if segment is None:
        offset = 0
        nsegments = 0
    else:
        offset = segment
        nsegments = 1

    for offset_, carpet in rug.iload(
            file_path, load_data=load_data,
            offset=offset, nsegments=nsegments):

        nut = model.make_carpet_nut(
            file_segment=offset_,
            file_element=0,
            codes=carpet.codes,
            tmin=carpet.tmin,
            tmax=carpet.tmin + carpet.deltat * carpet.nsamples,
            deltat=carpet.deltat)

        if 'carpet' in content:
            nut.content = carpet

        yield nut
