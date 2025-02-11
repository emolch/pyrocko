# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import os
import re
import math
import numpy as num
from pyrocko import util
from pyrocko.io import rug
from pyrocko.trace import NoData
from pyrocko.plot import nice_time_tick_inc_approx_secs


def level_codes_check(ilevel, codes):
    if ilevel == 0:
        assert not re.match(r'-L\d\d$', codes.extra)
        return codes.replace(extra=codes.extra + '-L00')
    else:
        assert codes.extra.endswith('-L%02i' % (ilevel-1))
        return codes.replace(extra=codes.extra[:-4] + '-L%02i' % ilevel)


def cascade(
        squirrel,
        nlevels,
        nfold=2,
        kinds=None,
        codes=None,
        tmin=None,
        tmax=None,
        accessor_id='default'):

    assert kinds is None or kinds == ['carpet']

    tmin_content, tmax_content = squirrel.get_time_span(['carpet'])
    nsamples_block = nfold * 1000
    time_format = '%Y-%m-%d_%H-%M-%S'

    def _process(ilevels, codes):
        ilevel, *ilevels = ilevels

        codes_next = set()

        paths = []
        codes_info = squirrel.get_codes_info('carpet', codes)
        for (pattern, kind_codes_id, codes_cand, deltat) in codes_info:
            tinc = nice_time_tick_inc_approx_secs(deltat * nsamples_block)
            tpad = deltat * nfold
            for batch in util.iter_windows(
                    tmin=tmin,
                    tmax=tmax,
                    tinc=tinc,
                    tmin_content=tmin_content,
                    tmax_content=tmax_content,
                    snap_window=True):

                for carpet in squirrel.get_carpets(
                        tmin=batch.tmin-tpad,
                        tmax=batch.tmax+tpad,
                        kind_codes_ids=[kind_codes_id],
                        accessor_id=accessor_id):

                    try:
                        folded = carpet.fold(
                            carpet.deltat*nfold,
                            method=num.max)

                        folded = folded.chop(
                            batch.tmin,
                            batch.tmax,
                            snap=(math.ceil, math.ceil))
                    except NoData:
                        continue

                    if folded.nsamples == 0:
                        continue

                    folded.codes = level_codes_check(ilevel, carpet.codes)
                    codes_next.add(folded.codes)

                    path = os.path.join(
                        'cascade',
                        'L%02i' % ilevel,
                        'cascade_{tmin}_{tmax}_{codes}.rug'.format(
                            tmin=util.time_to_str(
                                folded.tmin, format=time_format),
                            tmax=util.time_to_str(
                                folded.tmax, format=time_format),
                            codes=folded.codes))

                    util.ensuredirs(path)
                    paths.extend(rug.save([folded], path))

        squirrel.advance_accessor(accessor_id, 'carpet')
        squirrel.add(paths)

        if ilevels:
            _process(ilevels, list(codes_next))

    _process(list(range(nlevels)), codes)
