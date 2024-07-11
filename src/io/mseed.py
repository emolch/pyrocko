# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Read/write MiniSEED files (wraps `libmseed
<https://github.com/EarthScope/libmseed>`_).
'''


from collections import defaultdict
from struct import unpack
import os
import re
import math
import logging

from pyrocko import trace
from pyrocko.util import reuse, ensuredirs
from .io_common import FileLoadError, FileSaveError

logger = logging.getLogger('pyrocko.io.mseed')

MSEED_HEADER_BYTES = 64
VALID_RECORD_LENGTHS = tuple(2**exp for exp in range(8, 20))


class CodeTooLong(FileSaveError):
    pass


def iload(filename, load_data=True, offset=0, segment_size=0, nsegments=0):
    from pyrocko import mseed_ext

    have_zero_rate_traces = False
    try:
        isegment = 0
        while isegment < nsegments or nsegments == 0:
            tr_tuples = mseed_ext.get_traces(
                filename, load_data, offset, segment_size)

            if not tr_tuples:
                break

            for tr_tuple in tr_tuples:
                network, station, location, channel = tr_tuple[1:5]
                tmin = float(tr_tuple[5])/float(mseed_ext.HPTMODULUS)
                tmax = float(tr_tuple[6])/float(mseed_ext.HPTMODULUS)
                try:
                    deltat = reuse(1.0/float(tr_tuple[7]))
                except ZeroDivisionError:
                    have_zero_rate_traces = True
                    continue

                ydata = tr_tuple[8]

                tr = trace.Trace(
                    network.strip(),
                    station.strip(),
                    location.strip(),
                    channel.strip(),
                    tmin,
                    tmax,
                    deltat,
                    ydata)

                tr.meta = {
                    'offset_start': offset,
                    'offset_end': tr_tuple[9],
                    'last': tr_tuple[10],
                    'segment_size': segment_size
                }

                yield tr

            if tr_tuple[10]:
                break

            offset = tr_tuple[9]
            isegment += 1

    except (OSError, mseed_ext.MSeedError) as e:
        raise FileLoadError(str(e)+' (file: %s)' % filename)

    if have_zero_rate_traces:
        logger.warning(
            'Ignoring traces with sampling rate of zero in file %s '
            '(maybe LOG traces)' % filename)


def as_tuple(tr, dataquality='D'):
    from pyrocko import mseed_ext
    itmin = int(round(tr.tmin*mseed_ext.HPTMODULUS))
    itmax = int(round(tr.tmax*mseed_ext.HPTMODULUS))
    srate = 1.0/tr.deltat
    return (tr.network, tr.station, tr.location, tr.channel,
            itmin, itmax, srate, dataquality, tr.get_ydata())


def save(
        traces,
        filename_template,
        additional={},
        overwrite=True,
        dataquality='D',
        record_length=4096,
        append=False,
        check_append=False,
        check_append_hook=None,
        check_overlaps=True,
        steim=1):

    from pyrocko import mseed_ext

    assert record_length in VALID_RECORD_LENGTHS
    assert dataquality in ('D', 'E', 'C', 'O', 'T', 'L'), 'invalid dataquality'

    # nifty logic for overwrite, append, check_append_hook(fn):
    # file exists:
    #   overwrite, append
    #   0, 0 => fail
    #   0, 1, None => append
    #   0, 1, 0 => fail
    #   0, 1, 1 => append
    #   1, 0 => truncate
    #   1, 1, None => append
    #   1, 1, 0 => truncate, append
    #   1, 1, 1 => append

    if not append:
        check_append = False
        check_append_hook = None

    fn_tr = defaultdict(list)
    for tr in traces:
        for code, maxlen, val in zip(
                ['network', 'station', 'location', 'channel'],
                [2, 5, 2, 3],
                tr.nslc_id):

            if len(val) > maxlen:
                raise CodeTooLong(
                    '%s code too long to be stored in MSeed file: %s' %
                    (code, val))

        fn = tr.fill_template(filename_template, **additional)
        if os.path.exists(fn):
            if not overwrite:
                if not append or (
                        append and check_append_hook
                        and not check_append_hook(fn)):

                    raise FileSaveError('File exists: %s' % fn)

            else:
                if not append or (
                        append and check_append_hook
                        and not check_append_hook(fn)):

                    os.unlink(fn)

        fn_tr[fn].append(tr)

    for fn, traces_thisfile in fn_tr.items():
        if check_overlaps:
            try:
                trace.check_overlaps(
                    traces_thisfile,
                    message='Traces to be stored would overlap.\n  File: %s'
                    % fn)
            except trace.OverlappingTraces as e:
                raise FileSaveError(str(e)) from e

        if check_append:
            if os.path.exists(fn):
                traces_infile = list(iload(fn, load_data=False))
                try:
                    trace.check_overlaps(
                        traces_thisfile,
                        traces_infile,
                        message='Trace to be stored would overlap with '
                                'trace already stored in file.\n  File: %s'
                        % fn)
                except trace.OverlappingTraces as e:
                    raise FileSaveError(str(e)) from e

        trtups = []
        traces_thisfile.sort(key=lambda a: a.full_id)
        for tr in traces_thisfile:
            trtups.append(as_tuple(tr, dataquality))

        ensuredirs(fn)
        try:
            mseed_ext.store_traces(trtups, fn, record_length, append, steim)
        except mseed_ext.MSeedError as e:
            raise FileSaveError(
                str(e) + " (while storing traces to file '%s')" % fn)

    return list(fn_tr.keys())


tcs = {}


def get_bytes(traces, dataquality='D', record_length=4096, steim=1):
    from pyrocko import mseed_ext

    assert record_length in VALID_RECORD_LENGTHS
    assert dataquality in ('D', 'E', 'C', 'O', 'T', 'L'), 'invalid dataquality'

    nbytes_approx = 0
    rl = record_length
    trtups = []
    for tr in traces:
        for code, maxlen, val in zip(
                ['network', 'station', 'location', 'channel'],
                [2, 5, 2, 3],
                tr.nslc_id):

            if len(val) > maxlen:
                raise CodeTooLong(
                    '%s code too long to be stored in MSeed file: %s' %
                    (code, val))

        nbytes_approx += math.ceil(
            tr.ydata.nbytes / (rl-MSEED_HEADER_BYTES)) * rl
        trtups.append(as_tuple(tr, dataquality))

    return mseed_ext.mseed_bytes(trtups, nbytes_approx, record_length, steim)


def detect(first512):

    if len(first512) < 256:
        return False

    rec = first512

    try:
        sequence_number = int(rec[:6])
    except Exception:
        return False
    if sequence_number < 0:
        return False

    type_code = rec[6:7]
    if type_code in b'DRQM':
        bads = []
        for sex in '<>':
            bad = False
            fmt = sex + '6s1s1s5s2s3s2s10sH2h4Bl2H'
            vals = unpack(fmt, rec[:48])
            fmt_btime = sex + 'HHBBBBH'
            tvals = unpack(fmt_btime, vals[7])
            if tvals[1] < 1 or tvals[1] > 367 or tvals[2] > 23 or \
                    tvals[3] > 59 or tvals[4] > 60 or tvals[6] > 9999:
                bad = True

            bads.append(bad)

        if all(bads):
            return False

    else:
        if type_code not in b'VAST':
            return False

        continuation_code = rec[7:8]
        if continuation_code != b' ':
            return False

        blockette_type = rec[8:8+3].decode()
        if not re.match(r'^\d\d\d$', blockette_type):
            return False

        try:
            blockette_length = int(rec[11:11+4])
        except Exception:
            return False

        if blockette_length < 7:
            return False

    return True
