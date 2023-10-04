# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for KAN files.
'''

import os
import numpy as num

from pyrocko import util, trace
from .io_common import FileLoadError


class KanError(Exception):
    pass


class KanFile:

    nbytes_header = 512

    def __init__(self, *args, **kwargs):
        if args:
            self.read(*args, **kwargs)
        else:
            self.clear()

    def clear(self):
        '''
        Empty file record.
        '''

        # set the required attributes
        self.delta = 1.0
        self.npts = 0
        self.b = 0.0
        self.data = [num.arange(0, dtype=num.int32)]

    def read(self, filename, load_data=True):
        '''
        Read SAC file.

           filename -- Name of KAN file.
           load_data -- If True, the data is read, otherwise only read headers.
        '''
        nbh = KanFile.nbytes_header

        # read in all data
        with open(filename, 'rb') as f:
            if load_data:
                filedata = f.read()
            else:
                filedata = f.read(nbh)

        if len(filedata) < nbh:
            raise KanError('File too short to be a KAN file.')

        header_records = int(filedata[0:8])
        npts = int(filedata[8:20])
        leven = int(filedata[20:28])
        datatype = int(filedata[28:36])
        rate = float(filedata[36:50])
        offset = float(filedata[50:64])
        byte_sex = ('little', 'big')[int(filedata[382:390])]

        assert header_records == 1
        assert leven == 1
        assert datatype == 2
        assert offset == 0.0

        date = str(filedata[393:405].decode('ascii')).strip()
        tim = str(filedata[405:415].decode('ascii')).strip()
        microseconds = int(filedata[415:423])
        ref_time = util.to_time_float(util.ctimegm('%s %s' % (date, tim))) \
            + microseconds/1.0e6

        stationname = os.path.basename(filename)
        stationname = stationname.replace('.kan', '')
        stationname = stationname.replace('.KAN', '')

        self.npts = npts
        self.delta = 1.0/rate
        self.kstnm = stationname
        self.ref_time = ref_time

        if load_data:
            if byte_sex == 'little':
                dtype = '<i4'
            else:
                dtype = '>i4'

            self.data = num.frombuffer(filedata[nbh:], dtype=dtype)

            assert self.data.size == self.npts
        else:
            self.data = None

    def to_trace(self):
        return trace.Trace(
            '', self.kstnm, '', '',
            self.ref_time,
            self.ref_time+self.delta*(self.npts-1),
            self.delta,
            self.data)


def iload(filename, load_data):
    try:
        kanf = KanFile(filename, load_data=load_data)
        tr = kanf.to_trace()
        yield tr

    except (OSError, KanError) as e:
        raise FileLoadError(e)
