# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for GSE2.0 (IMS) waveform files.
'''

import os
import random

from .io_common import FileLoadError, FileSaveError
from pyrocko.util import ensuredirs


def detect(first512):
    lines = first512.lstrip().splitlines()
    if len(lines) >= 2:
        if lines[0].startswith(b'WID2 '):
            return True

        if lines[0].startswith(b'BEGIN GSE2'):
            return True

        if lines[0].startswith(b'DATA_TYPE WAVEFORM GSE2'):
            return True

    return False


def iload(filename, load_data=True):

    from . import ims

    try:
        with open(filename, 'rb') as f:

            r = ims.Reader(f, load_data=load_data, version='GSE2.0',
                           dialect=None)

            for sec in r:
                if isinstance(sec, ims.WID2Section):
                    tr = sec.pyrocko_trace(checksum_error='warn')
                    yield tr

    except (OSError, ims.DeserializeError) as e:
        fle = FileLoadError(e)
        fle.set_context('filename', filename)
        raise fle


def randomid():
    return ''.join(chr(random.randint(97, 122)) for _ in range(20))


def save(traces, filename_template, additional={}, max_open_files=10,
         overwrite=True):

    from pyrocko import info
    from . import ims

    fns = set()
    open_files = {}

    def close_files():
        while open_files:
            open_files.popitem()[1].close()

    for tr in traces:
        fn = tr.fill_template(filename_template, **additional)
        if fn not in open_files:
            if len(open_files) >= max_open_files:
                close_files()

            if fn not in fns:
                if not overwrite and os.path.exists(fn):
                    raise FileSaveError('file exists: %s' % fn)

                ensuredirs(fn)

            open_files[fn] = open(fn, ['wb', 'ab'][fn in fns])
            writer = ims.Writer(open_files[fn])
            writer.write(
                ims.MessageHeader(
                    version='GSE2.1',
                    type='DATA',
                    msg_id=ims.MsgID(
                        msg_id_string=randomid(),
                        msg_id_source='Pyrocko_%s' % info.version)))

            writer.write(ims.WaveformSection(
                datatype=ims.DataType(
                    type='WAVEFORM',
                    format='GSE2.1')))

            fns.add(fn)

        sec = ims.WID2Section.from_pyrocko_trace(tr, None, None, None, None)
        writer = ims.Writer(open_files[fn])
        writer.write(sec)

    for fn in fns:
        if fn not in open_files:
            open_files[fn] = open(fn, 'ab')

        writer = ims.Writer(open_files[fn])
        writer.write(ims.Stop())
        open_files.pop(fn).close()

    return list(fns)
