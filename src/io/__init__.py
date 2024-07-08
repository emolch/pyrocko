# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Low-level input and output of seismic waveforms, metadata and earthquake
catalogs.

Input and output (IO) for various different file formats is implemented in the
submodules of :py:mod:`pyrocko.io`. :py:mod:`pyrocko.io` itself provides a
simple unified interface to load and save seismic waveforms to a few different
file formats. For a higher-level approach to accessing seismic data see
:doc:`/topics/squirrel`.

.. rubric:: Seismic waveform IO

The data model used for the :py:class:`~pyrocko.trace.Trace` objects in Pyrocko
is most closely matched by the Mini-SEED file format. However, a difference is,
that Mini-SEED limits the length of the network, station, location, and channel
codes to 2, 5, 2, and 3 characters, respectively.

============ =========================== ========= ======== ======
format       format identifier           load      save     note
============ =========================== ========= ======== ======
Mini-SEED    mseed                       yes       yes
SAC          sac                         yes       yes      [#f1]_
SEG Y rev1   segy                        some
SEISAN       seisan, seisan.l, seisan.b  yes                [#f2]_
KAN          kan                         yes                [#f3]_
YAFF         yaff                        yes       yes      [#f4]_
ASCII Table  text                                  yes      [#f5]_
GSE1         gse1                        some
GSE2         gse2                        some
DATACUBE     datacube                    yes
SUDS         suds                        some
CSS          css                         yes
TDMS iDAS    tdms_idas                   yes
HDF5 iDAS    hdf5_idas                   yes
============ =========================== ========= ======== ======

.. rubric:: Notes

.. [#f1] For SAC files, the endianness is guessed. Additional header
    information is stored in the `Trace`'s ``meta`` attribute.
.. [#f2] Seisan waveform files can be in little (``seisan.l``) or big endian
    (``seisan.b``) format. ``seisan`` currently is an alias for ``seisan.l``.
.. [#f3] The KAN file format has only been seen once by the author, and support
    for it may be removed again.
.. [#f4] YAFF is an in-house, experimental file format, which should not be
    released into the wild.
.. [#f5] ASCII tables with two columns (time and amplitude) are output - meta
    information will be lost.

'''

import os
import logging
from pyrocko import util, trace

from . import (mseed, sac, kan, segy, yaff, seisan_waveform, gse1, gcf,
               datacube, suds, css, gse2, tdms_idas, hdf5_idas, hdf5_optodas)
from .io_common import FileLoadError, FileSaveError

import numpy as num


logger = logging.getLogger('pyrocko.io')


def allowed_formats(operation, use=None, default=None):
    if operation == 'load':
        lst = ['detect', 'from_extension', 'mseed', 'sac', 'segy', 'seisan',
               'seisan.l', 'seisan.b', 'kan', 'yaff', 'gse1', 'gse2', 'gcf',
               'datacube', 'suds', 'css', 'tdms_idas', 'hdf5_idas']

    elif operation == 'save':
        lst = ['mseed', 'sac', 'text', 'yaff', 'gse2']

    if use == 'doc':
        return ', '.join("``'%s'``" % fmt for fmt in lst)

    elif use == 'cli_help':
        return ', '.join(fmt + ['', ' [default]'][fmt == default]
                         for fmt in lst)

    else:
        return lst


def load(filename, format='mseed', getdata=True, substitutions=None):
    '''
    Load traces from file.

    :param format: format of the file (%s)
    :param getdata: if ``True`` (the default), read data, otherwise only read
        traces metadata
    :param substitutions:  dict with substitutions to be applied to the traces
        metadata

    :returns: list of loaded traces

    When *format* is set to ``'detect'``, the file type is guessed from the
    first 512 bytes of the file. Only Mini-SEED, SAC, GSE1, and YAFF format are
    detected. When *format* is set to ``'from_extension'``, the filename
    extension is used to decide what format should be assumed. The filename
    extensions considered are (matching is case insensitive): ``'.sac'``,
    ``'.kan'``, ``'.sgy'``, ``'.segy'``, ``'.yaff'``, everything else is
    assumed to be in Mini-SEED format.

    This function calls :py:func:`iload` and aggregates the loaded traces in a
    list.
    '''

    return list(iload(
        filename, format=format, getdata=getdata, substitutions=substitutions))


load.__doc__ %= allowed_formats('load', 'doc')


def detect_format(filename):
    try:
        f = open(filename, 'rb')
        data = f.read(512)
    except OSError as e:
        raise FileLoadError(e)
    finally:
        f.close()

    formats = [
        (yaff, 'yaff'),
        (mseed, 'mseed'),
        (sac, 'sac'),
        (gse1, 'gse1'),
        (gse2, 'gse2'),
        (datacube, 'datacube'),
        (suds, 'suds'),
        (tdms_idas, 'tdms_idas'),
        (hdf5_idas, 'hdf5_idas'),
        (hdf5_optodas, 'hdf5_optodas')]

    for mod, fmt in formats:
        if mod.detect(data):
            return fmt

    raise FileLoadError(UnknownFormat(filename))


def iload(filename, format='mseed', getdata=True, substitutions=None):
    '''
    Load traces from file (iterator version).

    This function works like :py:func:`load`, but returns an iterator which
    yields the loaded traces.
    '''
    load_data = getdata

    toks = format.split('.', 1)
    if len(toks) == 2:
        format, subformat = toks
    else:
        subformat = None

    try:
        mtime = os.stat(filename)[8]
    except OSError as e:
        raise FileLoadError(e)

    def subs(tr):
        make_substitutions(tr, substitutions)
        tr.set_mtime(mtime)
        return tr

    extension_to_format = {
        '.yaff': 'yaff',
        '.sac': 'sac',
        '.kan': 'kan',
        '.segy': 'segy',
        '.sgy': 'segy',
        '.gse': 'gse2',
        '.wfdisc': 'css',
        '.tdms': 'tdms_idas',
        '.h5': 'hdf5_idas',
        '.hdf5': 'hdf5_optodas'
    }

    if format == 'from_extension':
        format = 'mseed'
        extension = os.path.splitext(filename)[1]
        format = extension_to_format.get(extension.lower(), 'mseed')

    if format == 'detect':
        format = detect_format(filename)

    format_to_module = {
        'kan': kan,
        'segy': segy,
        'yaff': yaff,
        'sac': sac,
        'mseed': mseed,
        'seisan': seisan_waveform,
        'gse1': gse1,
        'gse2': gse2,
        'gcf': gcf,
        'datacube': datacube,
        'suds': suds,
        'css': css,
        'tdms_idas': tdms_idas,
        'hdf5_idas': hdf5_idas,
        'hdf5_optodas': hdf5_optodas
    }

    add_args = {
        'seisan': {'subformat': subformat},
    }

    if format not in format_to_module:
        raise UnsupportedFormat(format)

    mod = format_to_module[format]

    for tr in mod.iload(
            filename, load_data=load_data, **add_args.get(format, {})):

        yield subs(tr)


def save(traces, filename_template, format='mseed', additional={},
         stations=None, overwrite=True, **kwargs):
    '''
    Save traces to file(s).

    :param traces: a trace or an iterable of traces to store
    :param filename_template: filename template with placeholders for trace
            metadata. Uses normal python '%%(placeholder)s' string templates.
            The following placeholders are considered: ``network``,
            ``station``, ``location``, ``channel``, ``tmin``
            (time of first sample), ``tmax`` (time of last sample),
            ``tmin_ms``, ``tmax_ms``, ``tmin_us``, ``tmax_us``. The versions
            with '_ms' include milliseconds, the versions with '_us' include
            microseconds.
    :param format: %s
    :param additional: dict with custom template placeholder fillins.
    :param overwrite': if ``False``, raise an exception if file exists
    :returns: list of generated filenames

    .. note::
        Network, station, location, and channel codes may be silently truncated
        to file format specific maximum lengthes.
    '''

    if isinstance(traces, trace.Trace):
        traces = [traces]

    if format == 'from_extension':
        format = os.path.splitext(filename_template)[1][1:]

    if format == 'mseed':
        return mseed.save(traces, filename_template, additional,
                          overwrite=overwrite, **kwargs)

    elif format == 'gse2':
        return gse2.save(traces, filename_template, additional,
                         overwrite=overwrite, **kwargs)

    elif format == 'sac':
        fns = []
        for tr in traces:
            fn = tr.fill_template(filename_template, **additional)
            if not overwrite and os.path.exists(fn):
                raise FileSaveError('file exists: %s' % fn)

            if fn in fns:
                raise FileSaveError('file just created would be overwritten: '
                                    '%s (multiple traces map to same filename)'
                                    % fn)

            util.ensuredirs(fn)

            f = sac.SacFile(from_trace=tr)
            if stations:
                s = stations[tr.network, tr.station, tr.location]
                f.stla = s.lat
                f.stlo = s.lon
                f.stel = s.elevation
                f.stdp = s.depth
                f.cmpinc = s.get_channel(tr.channel).dip + 90.
                f.cmpaz = s.get_channel(tr.channel).azimuth

            f.write(fn)
            fns.append(fn)

        return fns

    elif format == 'text':
        fns = []
        for tr in traces:
            fn = tr.fill_template(filename_template, **additional)
            if not overwrite and os.path.exists(fn):
                raise FileSaveError('file exists: %s' % fn)

            if fn in fns:
                raise FileSaveError('file just created would be overwritten: '
                                    '%s (multiple traces map to same filename)'
                                    % fn)

            util.ensuredirs(fn)
            x, y = tr.get_xdata(), tr.get_ydata()
            num.savetxt(fn, num.transpose((x, y)))
            fns.append(fn)
        return fns

    elif format == 'yaff':
        return yaff.save(traces, filename_template, additional,
                         overwrite=overwrite, **kwargs)
    else:
        raise UnsupportedFormat(format)


save.__doc__ %= allowed_formats('save', 'doc')


class UnknownFormat(Exception):
    def __init__(self, filename):
        Exception.__init__(self, 'Unknown file format: %s' % filename)


class UnsupportedFormat(Exception):
    def __init__(self, format):
        Exception.__init__(self, 'Unsupported file format: %s' % format)


def make_substitutions(tr, substitutions):
    if substitutions:
        tr.set_codes(**substitutions)
