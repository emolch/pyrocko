import os
import numpy as num
import logging
from pyrocko import trace, util
from struct import unpack

logger = logging.getLogger('css')


'''
See http://nappe.wustl.edu/antelope/css-formats/wfdisc.htm for file format
reference.
'''

storage_types = {
        's4': ('>%ii'),
        'i4': ('<%ii'),
}

template = [
    ('sta', str, (0, 6), 'station code'),
    ('chan', str, (7, 15), 'channel code'),
    ('time', float, (16, 33), 'epoch time of first sample in file'),
    ('wfid', int, (34, 43), 'waveform identifier'),
    ('chanid', int, (44, 52), 'channel identifier'),
    ('jdate', int, (53, 61), 'julian date'),
    ('endtime', float, (62, 79),  'time +(nsamp -1 )/samles'),
    ('nsamp', int, (80, 88), 'number of samples'),
    ('samprate', float, (89, 100), 'sampling rate in samples/sec'),
    ('calib', float, (101, 117), 'nominal calibration'),
    ('calper', float, (118, 134), 'nominal calibration period'),
    ('instype', str, (135, 141), 'instrument code'),
    ('segtype', str, (142, 143), 'indexing method'),
    ('datatype', str, (144, 146), 'numeric storage'),
    ('clip', str, (147, 148), 'clipped flag'),
    ('dir', str, (149, 213), 'directory'),
    ('dfile', str, (214, 246), 'data file'),
    ('foff', int, (247, 257), 'byte offset of data segment within file'),
    ('commid', int, (258, 267), 'comment identifier'),
    ('Iddate', util.stt, (268, 287), 'load date')
]


class CSSWfError(Exception):
    def __init__(self, **kwargs):
        f2str = {
            str: 'string',
            int: 'integer',
            float: 'float',
            util.stt: 'time'
        }
        kwargs['convert'] = f2str[kwargs['convert']]
        error_str = 'Successfully parsed this:\n'
        for k, v in kwargs['d'].items():
            error_str += '%s: %s\n' % (k, v)

        error_str += '\nFailed to parse the marked section:'

        istart = kwargs['istart']
        istop = kwargs['istop']
        npad = 12
        error_mark = ' ' * npad
        error_mark += '^' * (istop - istart)
        error_str += '\n%s\n%s\n' % (kwargs['data'][istart-npad: istop+npad],
                                     error_mark)
        error_str += 'Expected {desc} (format: {convert})\n'.format(**kwargs)
        error_str += \
            'checkout http://nappe.wustl.edu/antelope/css-formats/wfdisc.htm'
        Exception.__init__(self, error_str)
        self.error_arguments = kwargs


class CSSHeaderFile():
    '''
    CSS Header File

    :param filename: filename of css header file

    Note, that all binary data files to which the underlying header file points
    to will be loaded at once. It is therefore recommended to split header
    files for large data sets
    '''
    def __init__(self, filename):

        self.fn = filename
        self.data = []
        self.read()

    def read_wf_file(self, fn, nbytes, dtype, foff=0):
        ''' Read binary waveform file
        :param fn: filename
        :param nbytes: number of bytes to be read
        :param dtype: datatype string
        '''
        with open(fn, 'rb') as f:
            fmt = dtype % nbytes
            f.seek(foff)
            try:
                data = num.array(unpack(fmt, f.read(nbytes * 4)),
                                 dtype=num.int32)
            except:
                logger.exception('Error while unpacking %s' % fn)
                return
        return data

    def read(self, use_template=True):
        ''' read header file

        :param use_template: If *False*, try to extract information bv
            splitting the file on whitespaces. Otherwise (default) use the
            official template.
            (http://nappe.wustl.edu/antelope/css-formats/wfdisc.htm)
        '''
        with open(self.fn, 'r') as f:
            lines = f.readlines()
            for iline, line in enumerate(lines):
                if use_template:
                    d = {}
                    for (ident, convert, (istart, istop), desc) in template:
                        try:
                            d[ident] = convert(line[istart: istop].strip())
                        except:
                            raise CSSWfError(
                                iline=iline+1, data=line,
                                ident=ident, convert=convert,
                                istart=istart+1, istop=istop+1, desc=desc,
                                d=d
                            )
                else:
                    d = {}
                    split = line.split()
                    d['sta'] = template[0][1](split[0])
                    d['chan'] = template[1][1](split[1])
                    d['time'] = template[2][1](split[2])
                    d['nsamp'] = template[7][1](split[7])
                    d['samprate'] = template[8][1](split[8])
                    d['datatype'] = template[-8][1](split[-8])
                    d['dir'] = template[-6][1](split[-6])
                    d['dfile'] = template[-5][1](split[-5])

                fn = os.path.join(d['dir'], d['dfile'])
                if os.path.isfile(fn):
                    self.data.append(d)
                else:
                    logger.info('no such file: %s' % fn)

    def iter_pyrocko_traces(self, load_data=True):
        for idata, d in enumerate(self.data):
            fn = os.path.join(d['dir'], d['dfile'])
            logger.debug('converting %s', d['dfile'])
            try:
                if load_data:
                    ydata = self.read_wf_file(
                            fn, d['nsamp'],
                            storage_types[d['datatype']],
                            d['foff'])
                else:
                    ydata = None

            except IOError as e:
                if e.errno == 2:
                    logger.debug(e)
                    continue
                else:
                    raise e
            dt = 1./d['samprate']
            yield trace.Trace(station=d['sta'],
                              channel=d['chan'],
                              deltat=dt,
                              tmin=d['time'],
                              tmax=d['time'] + d['nsamp']/d['samprate'],
                              ydata=ydata)


def iload(file_name, load_data, **kwargs):
    '''
    :param file_name: css header file name
    :param load_data: whether or not to load binary data
    '''
    wfdisc = CSSHeaderFile(file_name)
    for pyrocko_trace in wfdisc.iter_pyrocko_traces(load_data=load_data):
        yield pyrocko_trace
