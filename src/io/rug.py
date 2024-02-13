# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
'''
File IO module for RUG Carpet format.
'''

import os
from struct import unpack

from os import SEEK_SET

from pyrocko.file import (File, numtype2type, NoDataAvailable,
                          size_record_header, FileError)
from pyrocko.util import ensuredirs
from pyrocko import multitrace
from pyrocko.squirrel.model import CodesNSLCE
from .io_common import FileLoadError, FileSaveError

record_formats = {
    'carpet_header': {
        'network': 'string',
        'station': 'string',
        'location': 'string',
        'channel': 'string',
        'extra': 'string',
        'tmin': 'time_string',
        'deltat': 'f8',
        'nsamples': 'i8',
        'ncomponents': 'i8',
    },
    'carpet_comp_codes': {
        'network': 'string',
        'station': 'string',
        'location': 'string',
        'channel': 'string',
        'extra': 'string',
    },
    'carpet_comp_axis': {
        'name': 'string',
        'data': '@f8',
    },
    'carpet_data': {
        'data': ('@i2', '@i4', '@i8', '@i2', '@i4', '@i8',  '@f4', '@f8'),
    },
}


def extract(tr, format):
    d = {}
    for k in format.keys():
        d[k] = getattr(tr, k)
    return d


class RugLoadError(FileLoadError):
    pass


EMPTY_CODES = CodesNSLCE()


class CarpetFileIO(File):

    def __init__(self, file):
        File.__init__(
            self, file,
            type_label='YAFF',
            version='0000',
            record_formats=record_formats)

    def get_type(self, key, value):
        return numtype2type[value.dtype.type]

    def codes_from_dict(self, d):
        return CodesNSLCE(
            d['network'],
            d['station'],
            d['location'],
            d['channel'],
            d['extra'])

    def carpet_from_dict(self, d):
        data = d['data']
        if data is not None:
            data = data.reshape((d['ncomponents'], d['nsamples']))

        component_codes = d['component_codes']

        if not component_codes:
            component_codes = None

        if data is None and component_codes is None:
            component_codes = [CodesNSLCE()] * d['ncomponents']

        return multitrace.Carpet(
            nsamples=d['nsamples'],
            codes=self.codes_from_dict(d),
            component_codes=component_codes,
            component_axes=d['component_axes'],
            deltat=d['deltat'],
            tmin=d['tmin'],
            data=data,
        )

    def to_header_dict(self, carpet):
        return {
            'network': carpet.codes.network,
            'station': carpet.codes.station,
            'location': carpet.codes.location,
            'channel': carpet.codes.channel,
            'extra': carpet.codes.extra,
            'tmin': carpet.tmin,
            'deltat': carpet.deltat,
            'ncomponents': carpet.data.shape[0],
            'nsamples': carpet.data.shape[1],
        }

    def to_component_codes_dict(self, codes):
        return {
            'network': codes.network,
            'station': codes.station,
            'location': codes.location,
            'channel': codes.channel,
            'extra': codes.extra,
        }

    def to_component_axis_dict(self, pair):
        return {
            'name': pair[0],
            'data': pair[1],
        }

    def to_data_dict(self, data):
        return {
            'data': data,
        }

    def load(self, load_data=True):
        state = 0
        d = None
        offset = 0
        while True:
            try:
                position = self._f.tell()
                r = self.next_record()
                if state == 0:
                    if d is not None:
                        yield offset, self.carpet_from_dict(d)

                    if not r.type == 'carpet_header':
                        raise RugLoadError(
                            'Expected record of type "%s" but got "%s".' % (
                                'carpet_header', r.type))

                    d = r.unpack()
                    d['component_codes'] = []
                    d['component_axes'] = {}
                    d['data'] = None
                    state = 1
                    offset = position

                elif state == 1:
                    if r.type == 'carpet_comp_codes':
                        d['component_codes'].append(
                            self.codes_from_dict(r.unpack()))
                    elif r.type == 'carpet_comp_axis':
                        if load_data:
                            d_ca = r.unpack()
                            d['component_axes'][d_ca['name']] = d_ca['data']
                    elif r.type == 'carpet_data':
                        if load_data:
                            d['data'] = r.unpack()['data']
                        state = 0
                    else:
                        raise RugLoadError(
                            'Expected record of type "%s", "%s", or "%s" but '
                            'got "%s".' % (
                                'carpet_comp_codes',
                                'carpet_comp_axis',
                                'carpet_data',
                                r.type))

            except NoDataAvailable:
                break

        if d is not None:
            yield offset, self.carpet_from_dict(d)

    def save(self, carpets):
        for carpet in carpets:
            r = self.add_record('carpet_header', make_hash=True)
            r.pack(self.to_header_dict(carpet))
            r.close()
            if not all(
                    codes == EMPTY_CODES
                    for codes in carpet.component_codes):

                for codes in carpet.component_codes:
                    r = self.add_record('carpet_comp_codes', make_hash=True)
                    r.pack(self.to_component_codes_dict(codes))
                    r.close()

            for pair in carpet.component_axes.items():
                r = self.add_record('carpet_comp_axis', make_hash=True)
                r.pack(self.to_component_axis_dict(pair))
                r.close()

            r = self.add_record('carpet_data', make_hash=True)
            r.pack(self.to_data_dict(carpet.data))
            r.close()


def iload(filename, load_data=True, offset=0, nsegments=0):
    try:
        f = open(filename, 'rb')
        f.seek(offset, SEEK_SET)
        tf = CarpetFileIO(f)
        isegment = 0
        for carpet in tf.load(load_data=load_data):
            yield carpet
            isegment += 1
            if isegment == nsegments:
                break

    except (OSError, FileError) as e:
        raise FileLoadError(e)

    finally:
        tf.close()
        f.close()


def save(
        carpets,
        filename_template,
        additional={},
        max_open_files=10,
        overwrite=True):

    fns = set()
    open_files = {}

    def close_files():
        while open_files:
            open_files.popitem()[1].close()

    for carpet in carpets:
        fn = carpet.fill_template(
            filename_template,
            **additional)

        if fn not in open_files:
            if len(open_files) >= max_open_files:
                close_files()

            if fn not in fns:
                if not overwrite and os.path.exists(fn):
                    raise FileSaveError('file exists: %s' % fn)

                ensuredirs(fn)

            open_files[fn] = open(fn, ['wb', 'ab'][fn in fns])
            fns.add(fn)

        tf = CarpetFileIO(open_files[fn])
        tf.save([carpet])
        tf.close()

    close_files()

    return list(fns)


def detect(first512):

    if len(first512) < size_record_header:
        return False

    label, version, size_record, size_payload, hash, type = unpack(
        '>4s4sQQ20s20s', first512[:size_record_header])

    if label == b'YAFF' and version == b'0000' \
            and type.strip() == b'carpet_header':
        return True

    return False
