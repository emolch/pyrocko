# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
'''Utility functions for Pyrocko.'''
from __future__ import division, print_function

import time
import logging
import os
import sys
import re
import calendar
import math
import fnmatch
import fcntl
import shlex
import optparse
import os.path as op
import platform
import errno

import numpy as num
from scipy import signal
from pyrocko import dummy_progressbar

try:
    from urllib.parse import urlencode, quote, unquote  # noqa
    from urllib.request import (
        Request, build_opener, HTTPDigestAuthHandler, urlopen)  # noqa
    from urllib.error import HTTPError, URLError  # noqa

except ImportError:
    from urllib import urlencode, quote, unquote # noqa
    from urllib2 import (Request, build_opener, HTTPDigestAuthHandler,   # noqa
                         HTTPError, URLError, urlopen)  # noqa


class URLErrorSSL(URLError):

    def __init__(self, urlerror):
        self.__dict__ = urlerror.__dict__.copy()

    def __str__(self):
        return (
            'Requesting web resource failed and the problem could be '
            'related to SSL. Python standard libraries on some older '
            'systems (like Ubuntu 14.04) are known to have trouble '
            'with some SSL setups of today\'s servers: %s'
            % URLError.__str__(self))


def urlopen_ssl_check(*args, **kwargs):
    try:
        return urlopen(*args, **kwargs)
    except URLError as e:
        if str(e).find('SSL') != -1:
            raise URLErrorSSL(e)
        else:
            raise


try:
    long
except NameError:
    long = int


force_dummy_progressbar = False


if platform.system() != 'Darwin':
    from pyrocko import util_ext
else:
    util_ext = None


logger = logging.getLogger('pyrocko.util')

try:
    import progressbar as progressbar_mod
except ImportError:
    from pyrocko import dummy_progressbar as progressbar_mod


try:
    num_full = num.full
except AttributeError:
    def num_full(shape, fill_value, dtype=None, order='C'):
        a = num.empty(shape, dtype=dtype, order=order)
        a.fill(fill_value)
        return a

try:
    num_full_like = num.full_like
except AttributeError:
    def num_full_like(arr, fill_value, dtype=None, order='K', subok=True):
        a = num.empty_like(arr, dtype=dtype, order=order, subok=subok)
        a.fill(fill_value)
        return a


def progressbar_module():
    return progressbar_mod


g_setup_logging_args = 'pyrocko', 'warning'


def setup_logging(programname='pyrocko', levelname='warning'):
    '''
    Initialize logging.

    :param programname: program name to be written in log
    :param levelname: string indicating the logging level ('debug', 'info',
        'warning', 'error', 'critical')

    This function is called at startup by most pyrocko programs to set up a
    consistent logging format. This is simply a shortcut to a call to
    :py:func:`logging.basicConfig()`.
    '''

    global g_setup_logging_args
    g_setup_logging_args = (programname, levelname)

    levels = {'debug': logging.DEBUG,
              'info': logging.INFO,
              'warning': logging.WARNING,
              'error': logging.ERROR,
              'critical': logging.CRITICAL}

    logging.basicConfig(
        level=levels[levelname],
        format=programname+':%(name)-20s - %(levelname)-8s - %(message)s')


def subprocess_setup_logging_args():
    '''
    Get arguments from previous call to setup_logging.

    These can be sent down to a worker process so it can setup its logging
    in the same way as the main process.
    '''
    return g_setup_logging_args


def data_file(fn):
    return os.path.join(os.path.split(__file__)[0], 'data', fn)


class DownloadError(Exception):
    pass


class PathExists(DownloadError):
    pass


def _download(url, fpath, username=None, password=None,
              force=False, method='download', stats=None,
              status_callback=None, entries_wanted=None,
              recursive=False, header=None):

    import requests
    from requests.auth import HTTPBasicAuth
    from requests.exceptions import HTTPError as req_HTTPError

    requests.adapters.DEFAULT_RETRIES = 5
    urljoin = requests.compat.urljoin

    session = requests.Session()
    session.header = header
    session.auth = None if username is None\
        else HTTPBasicAuth(username, password)

    status = {
        'ntotal_files': 0,
        'nread_files': 0,
        'ntotal_bytes_all_files': 0,
        'nread_bytes_all_files': 0,
        'ntotal_bytes_current_file': 0,
        'nread_bytes_current_file': 0,
        'finished': False
    }

    try:
        url_to_size = {}

        if callable(status_callback):
            status_callback(status)

        if not recursive and url.endswith('/'):
            raise DownloadError(
                'URL: %s appears to be a directory'
                ' but recurvise download is False' % url)

        if recursive and not url.endswith('/'):
            url += '/'

        def parse_directory_tree(url, subdir=''):
            r = session.get(urljoin(url, subdir))
            r.raise_for_status()

            entries = re.findall(r'href="([a-zA-Z0-9_.-]+/?)"', r.text)

            files = sorted(set(subdir + fn for fn in entries
                               if not fn.endswith('/')))

            if entries_wanted is not None:
                files = [fn for fn in files
                         if (fn in wanted for wanted in entries_wanted)]

            status['ntotal_files'] += len(files)

            dirs = sorted(set(subdir + dn for dn in entries
                              if dn.endswith('/')
                              and dn not in ('./', '../')))

            for dn in dirs:
                files.extend(parse_directory_tree(
                    url, subdir=dn))

            return files

        def get_content_length(url):
            if url not in url_to_size:
                r = session.head(url, headers={'Accept-Encoding': ''})

                content_length = r.headers.get('content-length', None)
                if content_length is None:
                    logger.debug('Could not get HTTP header '
                                 'Content-Length for %s' % url)

                    content_length = None

                else:
                    content_length = int(content_length)
                    status['ntotal_bytes_all_files'] += content_length
                    if callable(status_callback):
                        status_callback(status)

                url_to_size[url] = content_length

            return url_to_size[url]

        def download_file(url, fn):
            logger.info('starting download of %s...' % url)
            ensuredirs(fn)

            fsize = get_content_length(url)
            status['ntotal_bytes_current_file'] = fsize
            status['nread_bytes_current_file'] = 0
            if callable(status_callback):
                status_callback(status)

            r = session.get(url, stream=True, timeout=5)
            r.raise_for_status()

            frx = 0
            fn_tmp = fn + '.%i.temp' % os.getpid()
            with open(fn_tmp, 'wb') as f:
                for d in r.iter_content(chunk_size=1024):
                    f.write(d)
                    frx += len(d)

                    status['nread_bytes_all_files'] += len(d)
                    status['nread_bytes_current_file'] += len(d)
                    if callable(status_callback):
                        status_callback(status)

            os.rename(fn_tmp, fn)

            if fsize is not None and frx != fsize:
                logger.warning(
                    'HTTP header Content-Length: %i bytes does not match '
                    'download size %i bytes' % (fsize, frx))

            logger.info('finished download of %s' % url)

            status['nread_files'] += 1
            if callable(status_callback):
                status_callback(status)

        if recursive:
            if op.exists(fpath) and not force:
                raise PathExists('path %s already exists' % fpath)

            files = parse_directory_tree(url)

            dsize = 0
            for fn in files:
                file_url = urljoin(url, fn)
                dsize += get_content_length(file_url) or 0

            if method == 'calcsize':
                return dsize

            else:
                for fn in files:
                    file_url = urljoin(url, fn)
                    download_file(file_url, op.join(fpath, fn))

        else:
            status['ntotal_files'] += 1
            if callable(status_callback):
                status_callback(status)

            fsize = get_content_length(url)
            if method == 'calcsize':
                return fsize
            else:
                download_file(url, fpath)

    except req_HTTPError as e:
        logging.warn("http error: %s" % e)
        raise DownloadError('could not download file(s) from: %s' % url)

    finally:
        status['finished'] = True
        if callable(status_callback):
            status_callback(status)
        session.close()


def download_file(
        url, fpath, username=None, password=None, status_callback=None,
        **kwargs):
    return _download(
        url, fpath, username, password,
        recursive=False,
        status_callback=status_callback,
        **kwargs)


def download_dir(
        url, fpath, username=None, password=None, status_callback=None,
        **kwargs):

    return _download(
        url, fpath, username, password,
        recursive=True,
        status_callback=status_callback,
        **kwargs)


if hasattr(num, 'float128'):
    hpfloat = num.float128
elif hasattr(num, 'float96'):
    hpfloat = num.float96
else:
    def hpfloat(x):
        raise Exception(
            'NumPy lacks support for float128 or float96 data type on this '
            'platform.')


class Stopwatch(object):
    '''
    Simple stopwatch to measure elapsed wall clock time.

    Usage::

        s = Stopwatch()
        time.sleep(1)
        print s()
        time.sleep(1)
        print s()
    '''

    def __init__(self):
        self.start = time.time()

    def __call__(self):
        return time.time() - self.start


def wrap(text, line_length=80):
    '''
    Paragraph and list-aware wrapping of text.
    '''

    text = text.strip('\n')
    at_lineend = re.compile(r' *\n')
    at_para = re.compile(r'((^|(\n\s*)?\n)(\s+[*] )|\n\s*\n)')

    paragraphs = at_para.split(text)[::5]
    listindents = at_para.split(text)[4::5]
    newlist = at_para.split(text)[3::5]

    listindents[0:0] = [None]
    listindents.append(True)
    newlist.append(None)

    det_indent = re.compile(r'^ *')

    outlines = []
    for ip, p in enumerate(paragraphs):
        if not p:
            continue

        if listindents[ip] is None:
            _indent = det_indent.findall(p)[0]
            findent = _indent
        else:
            findent = listindents[ip]
            _indent = ' ' * len(findent)

        ll = line_length - len(_indent)
        llf = ll

        oldlines = [s.strip() for s in at_lineend.split(p.rstrip())]
        p1 = ' '.join(oldlines)
        possible = re.compile(r'(^.{1,%i}|.{1,%i})( |$)' % (llf, ll))
        for imatch, match in enumerate(possible.finditer(p1)):
            parout = match.group(1)
            if imatch == 0:
                outlines.append(findent + parout)
            else:
                outlines.append(_indent + parout)

        if ip != len(paragraphs)-1 and (
                listindents[ip] is None
                or newlist[ip] is not None
                or listindents[ip+1] is None):

            outlines.append('')

    return outlines


class BetterHelpFormatter(optparse.IndentedHelpFormatter):

    def __init__(self, *args, **kwargs):
        optparse.IndentedHelpFormatter.__init__(self, *args, **kwargs)

    def format_option(self, option):
        '''
        From IndentedHelpFormatter but using a different wrap method.
        '''

        help_text_position = 4 + self.current_indent
        help_text_width = self.width - help_text_position

        opts = self.option_strings[option]
        opts = "%*s%s" % (self.current_indent, "", opts)
        if option.help:
            help_text = self.expand_default(option)

        if self.help_position + len(help_text) + 1 <= self.width:
            lines = [
                '',
                '%-*s %s' % (self.help_position, opts, help_text),
                '']
        else:
            lines = ['']
            lines.append(opts)
            lines.append('')
            if option.help:
                help_lines = wrap(help_text, help_text_width)
                lines.extend(["%*s%s" % (help_text_position, "", line)
                              for line in help_lines])
            lines.append('')

        return "\n".join(lines)

    def format_description(self, description):
        if not description:
            return ''

        if self.current_indent == 0:
            lines = []
        else:
            lines = ['']

        lines.extend(wrap(description, self.width - self.current_indent))
        if self.current_indent == 0:
            lines.append('\n')

        return '\n'.join(
            ['%*s%s' % (self.current_indent, '', line) for line in lines])


def progressbar(label, maxval):
    progressbar_mod = progressbar_module()
    if force_dummy_progressbar:
        progressbar_mod = dummy_progressbar

    widgets = [
        label, ' ',
        progressbar_mod.Bar(marker='-', left='[', right=']'), ' ',
        progressbar_mod.Percentage(), ' ',
        progressbar_mod.ETA()]

    pbar = progressbar_mod.ProgressBar(widgets=widgets, maxval=maxval).start()
    return pbar


def progress_beg(label):
    '''
    Notify user that an operation has started.

    :param label: name of the operation

    To be used in conjuction with :py:func:`progress_end`.
    '''

    sys.stderr.write(label)
    sys.stderr.flush()


def progress_end(label=''):
    '''
    Notify user that an operation has ended.

    :param label: name of the operation

    To be used in conjuction with :py:func:`progress_beg`.
    '''

    sys.stderr.write(' done. %s\n' % label)
    sys.stderr.flush()


class ArangeError(Exception):
    pass


def arange2(start, stop, step, dtype=num.float, epsilon=1e-6, error='raise'):
    '''
    Return evenly spaced numbers over a specified interval.

    Like :py:func:`numpy.arange` but returning floating point numbers by
    default and with defined behaviour when stepsize is inconsistent with
    interval bounds. It is considered inconsistent if the difference between
    the closest multiple of ``step`` and ``stop`` is larger than ``epsilon *
    step``. Inconsistencies are handled according to the ``error`` parameter.
    If it is set to ``'raise'`` an exception of type :py:exc:`ArangeError` is
    raised. If it is set to ``'round'``, ``'floor'``, or ``'ceil'``, ``stop``
    is silently changed to the closest, the next smaller, or next larger
    multiple of ``step``, respectively.
    '''

    assert error in ('raise', 'round', 'floor', 'ceil')

    start = dtype(start)
    stop = dtype(stop)
    step = dtype(step)

    rnd = {'floor': math.floor, 'ceil': math.ceil}.get(error, round)

    n = int(rnd((stop - start) / step)) + 1
    stop_check = start + (n-1) * step

    if error == 'raise' and abs(stop_check - stop) > step * epsilon:
        raise ArangeError(
            'inconsistent range specification: start=%g, stop=%g, step=%g'
            % (start, stop, step))

    x = num.arange(n, dtype=dtype)
    x *= step
    x += start
    return x


def polylinefit(x, y, n_or_xnodes):
    '''
    Fit piece-wise linear function to data.

    :param x,y: arrays with coordinates of data
    :param n_or_xnodes: int, number of segments or x coordinates of polyline

    :returns: `(xnodes, ynodes, rms_error)` arrays with coordinates of
        polyline, root-mean-square error
    '''

    x = num.asarray(x)
    y = num.asarray(y)

    if isinstance(n_or_xnodes, int):
        n = n_or_xnodes
        xmin = x.min()
        xmax = x.max()
        xnodes = num.linspace(xmin, xmax, n+1)
    else:
        xnodes = num.asarray(n_or_xnodes)
        n = xnodes.size - 1

    assert len(x) == len(y)
    assert n > 0

    ndata = len(x)
    a = num.zeros((ndata+(n-1), n*2))
    for i in range(n):
        xmin_block = xnodes[i]
        xmax_block = xnodes[i+1]
        if i == n-1:  # don't loose last point
            indices = num.where(
                num.logical_and(xmin_block <= x, x <= xmax_block))[0]
        else:
            indices = num.where(
                num.logical_and(xmin_block <= x, x < xmax_block))[0]

        a[indices, i*2] = x[indices]
        a[indices, i*2+1] = 1.0

        w = float(ndata)*100.
        if i < n-1:
            a[ndata+i, i*2] = xmax_block*w
            a[ndata+i, i*2+1] = 1.0*w
            a[ndata+i, i*2+2] = -xmax_block*w
            a[ndata+i, i*2+3] = -1.0*w

    d = num.concatenate((y, num.zeros(n-1)))
    model = num.linalg.lstsq(a, d, rcond=-1)[0].reshape((n, 2))

    ynodes = num.zeros(n+1)
    ynodes[:n] = model[:, 0]*xnodes[:n] + model[:, 1]
    ynodes[1:] += model[:, 0]*xnodes[1:] + model[:, 1]
    ynodes[1:n] *= 0.5

    rms_error = num.sqrt(num.mean((num.interp(x, xnodes, ynodes) - y)**2))

    return xnodes, ynodes, rms_error


def plf_integrate_piecewise(x_edges, x, y):
    '''
    Calculate definite integral of piece-wise linear function on intervals.

    Use trapezoidal rule to calculate definite integral of a piece-wise linear
    function for a series of consecutive intervals. ``x_edges`` and ``x`` must
    be sorted.

    :param x_edges: array with edges of the intervals
    :param x,y: arrays with coordinates of piece-wise linear function's
                 control points
    '''

    x_all = num.concatenate((x, x_edges))
    ii = num.argsort(x_all)
    y_edges = num.interp(x_edges, x, y)
    y_all = num.concatenate((y, y_edges))
    xs = x_all[ii]
    ys = y_all[ii]
    y_all[ii[1:]] = num.cumsum((xs[1:] - xs[:-1]) * 0.5 * (ys[1:] + ys[:-1]))
    return num.diff(y_all[-len(y_edges):])


def diff_fd_1d_4o(dt, data):
    '''
    Approximate first derivative of an array (forth order, central FD).

    :param dt: sampling interval
    :param data: NumPy array with data samples

    :returns: NumPy array with same shape as input

    Interior points are approximated to fourth order, edge points to first
    order right- or left-sided respectively, points next to edge to second
    order central.
    '''
    import scipy.signal

    ddata = num.empty_like(data, dtype=num.float)

    if data.size >= 5:
        ddata[2:-2] = scipy.signal.lfilter(
            [-1., +8., 0., -8., 1.], [1.], data)[4:] / (12.*dt)

    if data.size >= 3:
        ddata[1] = (data[2] - data[0]) / (2. * dt)
        ddata[-2] = (data[-1] - data[-3]) / (2. * dt)

    if data.size >= 2:
        ddata[0] = (data[1] - data[0]) / dt
        ddata[-1] = (data[-1] - data[-2]) / dt

    if data.size == 1:
        ddata[0] = 0.0

    return ddata


def diff_fd_1d_2o(dt, data):
    '''
    Approximate first derivative of an array (second order, central FD).

    :param dt: sampling interval
    :param data: NumPy array with data samples

    :returns: NumPy array with same shape as input

    Interior points are approximated to second order, edge points to first
    order right- or left-sided respectively.

    Uses :py:func:`numpy.gradient`.
    '''

    return num.gradient(data, dt)


def diff_fd_2d_4o(dt, data):
    '''
    Approximate second derivative of an array (forth order, central FD).

    :param dt: sampling interval
    :param data: NumPy array with data samples

    :returns: NumPy array with same shape as input

    Interior points are approximated to fourth order, next-to-edge points to
    second order, edge points repeated.
    '''
    import scipy.signal

    ddata = num.empty_like(data, dtype=num.float)

    if data.size >= 5:
        ddata[2:-2] = scipy.signal.lfilter(
            [-1., +16., -30., +16., -1.], [1.], data)[4:] / (12.*dt**2)

    if data.size >= 3:
        ddata[:2] = (data[2] - 2.0 * data[1] + data[0]) / dt**2
        ddata[-2:] = (data[-1] - 2.0 * data[-2] + data[-3]) / dt**2

    if data.size < 3:
        ddata[:] = 0.0

    return ddata


def diff_fd_2d_2o(dt, data):
    '''
    Approximate second derivative of an array (second order, central FD).

    :param dt: sampling interval
    :param data: NumPy array with data samples

    :returns: NumPy array with same shape as input

    Interior points are approximated to second order, edge points repeated.
    '''
    import scipy.signal

    ddata = num.empty_like(data, dtype=num.float)

    if data.size >= 3:
        ddata[1:-1] = scipy.signal.lfilter(
            [1., -2., 1.], [1.], data)[2:] / (dt**2)

        ddata[0] = ddata[1]
        ddata[-1] = ddata[-2]

    if data.size < 3:
        ddata[:] = 0.0

    return ddata


def diff_fd(n, order, dt, data):
    '''
    Approximate 1st or 2nd derivative of an array.

    :param n: 1 for first derivative, 2 for second
    :param order: order of the approximation 2 and 4 are supported
    :param dt: sampling interval
    :param data: NumPy array with data samples

    :returns: NumPy array with same shape as input

    This is a frontend to the functions :py:func:`diff_fd_1d_2o`,
    :py:func:`diff_fd_1d_4o`, :py:func:`diff_fd_2d_2o`, and
    :py:func:`diff_fd_2d_4o`.

    Raises :py:exc:`ValueError` for unsupported `n` or `order`.
    '''

    funcs = {
        1: {2: diff_fd_1d_2o, 4: diff_fd_1d_4o},
        2: {2: diff_fd_2d_2o, 4: diff_fd_2d_4o}}

    try:
        funcs_n = funcs[n]
    except KeyError:
        raise ValueError(
            'pyrocko.util.diff_fd: '
            'Only 1st and 2sd derivatives are supported.')

    try:
        func = funcs_n[order]
    except KeyError:
        raise ValueError(
            'pyrocko.util.diff_fd: '
            'Order %i is not supported for %s derivative. Supported: %s' % (
                order, ['', '1st', '2nd'][n],
                ', '.join('%i' % order for order in sorted(funcs_n.keys()))))

    return func(dt, data)


class GlobalVars(object):
    reuse_store = dict()
    decitab_nmax = 0
    decitab = {}
    decimate_fir_coeffs = {}
    decimate_iir_coeffs = {}
    re_frac = None


def decimate_coeffs(q, n=None, ftype='iir'):

    q = int(q)

    if n is None:
        if ftype == 'fir':
            n = 30
        else:
            n = 8

    if ftype == 'fir':
        coeffs = GlobalVars.decimate_fir_coeffs
        if (n, 1./q) not in coeffs:
            coeffs[n, 1./q] = signal.firwin(n+1, 1./q, window='hamming')

        b = coeffs[n, 1./q]
        return b, [1.], n

    else:
        coeffs = GlobalVars.decimate_iir_coeffs
        if (n, 0.05, 0.8/q) not in coeffs:
            coeffs[n, 0.05, 0.8/q] = signal.cheby1(n, 0.05, 0.8/q)

        b, a = coeffs[n, 0.05, 0.8/q]
        return b, a, n


def decimate(x, q, n=None, ftype='iir', zi=None, ioff=0):
    '''
    Downsample the signal x by an integer factor q, using an order n filter

    By default, an order 8 Chebyshev type I filter is used or a 30 point FIR
    filter with hamming window if ftype is 'fir'.

    :param x: the signal to be downsampled (1D NumPy array)
    :param q: the downsampling factor
    :param n: order of the filter (1 less than the length of the filter for a
         'fir' filter)
    :param ftype: type of the filter; can be 'iir' or 'fir'

    :returns: the downsampled signal (1D NumPy array)

    '''

    b, a, n = decimate_coeffs(q, n, ftype)

    if zi is None or zi is True:
        zi_ = num.zeros(max(len(a), len(b))-1, dtype=num.float)
    else:
        zi_ = zi

    y, zf = signal.lfilter(b, a, x, zi=zi_)

    if zi is not None:
        return y[n//2+ioff::q].copy(), zf
    else:
        return y[n//2+ioff::q].copy()


class UnavailableDecimation(Exception):
    '''
    Exception raised by :py:func:`decitab` for unavailable decimation factors.
    '''

    pass


def gcd(a, b, epsilon=1e-7):
    '''
    Greatest common divisor.
    '''

    while b > epsilon*a:
        a, b = b, a % b

    return a


def lcm(a, b):
    '''
    Least common multiple.
    '''

    return a*b // gcd(a, b)


def mk_decitab(nmax=100):
    '''
    Make table with decimation sequences.

    Decimation from one sampling rate to a lower one is achieved by a
    successive application of :py:func:`decimation` with small integer
    downsampling factors (because using large downampling factors can make the
    decimation unstable or slow). This function sets up a table with downsample
    sequences for factors up to ``nmax``.
    '''

    tab = GlobalVars.decitab
    for i in range(1, 10):
        for j in range(1, i+1):
            for k in range(1, j+1):
                for l_ in range(1, k+1):
                    for m in range(1, l_+1):
                        p = i*j*k*l_*m
                        if p > nmax:
                            break
                        if p not in tab:
                            tab[p] = (i, j, k, l_, m)
                    if i*j*k*l_ > nmax:
                        break
                if i*j*k > nmax:
                    break
            if i*j > nmax:
                break
        if i > nmax:
            break

    GlobalVars.decitab_nmax = nmax


def zfmt(n):
    return '%%0%ii' % (int(math.log10(n - 1)) + 1)


def _year_to_time(year):
    tt = (year, 1, 1, 0, 0, 0)
    return calendar.timegm(tt)


def _working_year(year):
    try:
        tt = (year, 1, 1, 0, 0, 0)
        t = calendar.timegm(tt)
        tt2_ = time.gmtime(t)
        tt2 = tuple(tt2_)[:6]
        if tt != tt2:
            return False

        s = '%i-01-01 00:00:00' % year
        s2 = time.strftime('%Y-%m-%d %H:%M:%S', tt2_)
        if s != s2:
            return False

    except Exception:
        return False

    return True


g_working_system_time_range = None


def get_working_system_time_range():
    '''
    Check time range supported by the systems's time conversion functions.

    Returns system time stamps of start of year of first/last fully supported
    year span. If this is before 1900 or after 2100, return first/last century
    which is fully supported.

    :returns: ``(tmin, tmax, year_min, year_max)``
    '''

    global g_working_system_time_range

    if g_working_system_time_range is None:
        year0 = 2000
        year_min = year0
        year_max = year0

        itests = list(range(101))
        for i in range(19):
            itests.append(200 + i*100)

        for i in itests:
            if not _working_year(year0 - i):
                break
            else:
                year_min = year0 - i

        for i in itests:
            if not _working_year(year0 + i + 1):
                break
            else:
                year_max = year0 + i

        g_working_system_time_range = (
            _year_to_time(year_min),
            _year_to_time(year_max),
            year_min, year_max)

    return g_working_system_time_range


def is_working_time(t):
    tmin, tmax, _, _ = get_working_system_time_range()
    return tmin <= t <= tmax


def julian_day_of_year(timestamp):
    '''
    Get the day number after the 1st of January of year in ``timestamp``.

    :returns: day number as int
    '''

    return time.gmtime(int(timestamp)).tm_yday


def day_start(timestamp):
    '''
    Get beginning of day for any point in time.

    :param timestamp: time instant as system timestamp (in seconds)

    :returns: instant of day start as system timestamp
    '''

    tt = time.gmtime(int(timestamp))
    tts = tt[0:3] + (0, 0, 0) + tt[6:9]
    return calendar.timegm(tts)


def month_start(timestamp):
    '''
    Get beginning of month for any point in time.

    :param timestamp: time instant as system timestamp (in seconds)

    :returns: instant of month start as system timestamp
    '''

    tt = time.gmtime(int(timestamp))
    tts = tt[0:2] + (1, 0, 0, 0) + tt[6:9]
    return calendar.timegm(tts)


def year_start(timestamp):
    '''
    Get beginning of year for any point in time.

    :param timestamp: time instant as system timestamp (in seconds)

    :returns: instant of year start as system timestamp
    '''

    tt = time.gmtime(int(timestamp))
    tts = tt[0:1] + (1, 1, 0, 0, 0) + tt[6:9]
    return calendar.timegm(tts)


def iter_days(tmin, tmax):
    '''
    Yields begin and end of days until given time span is covered.

    :param tmin,tmax: input time span

    :yields: tuples with (begin, end) of days as system timestamps
    '''

    t = day_start(tmin)
    while t < tmax:
        tend = day_start(t + 26*60*60)
        yield t, tend
        t = tend


def iter_months(tmin, tmax):
    '''
    Yields begin and end of months until given time span is covered.

    :param tmin,tmax: input time span

    :yields: tuples with (begin, end) of months as system timestamps
    '''

    t = month_start(tmin)
    while t < tmax:
        tend = month_start(t + 24*60*60*33)
        yield t, tend
        t = tend


def iter_years(tmin, tmax):
    '''
    Yields begin and end of years until given time span is covered.

    :param tmin,tmax: input time span

    :yields: tuples with (begin, end) of years as system timestamps
    '''

    t = year_start(tmin)
    while t < tmax:
        tend = year_start(t + 24*60*60*369)
        yield t, tend
        t = tend


def decitab(n):
    '''
    Get integer decimation sequence for given downampling factor.

    :param n: target decimation factor

    :returns: tuple with downsampling sequence
    '''

    if n > GlobalVars.decitab_nmax:
        mk_decitab(n*2)
    if n not in GlobalVars.decitab:
        raise UnavailableDecimation('ratio = %g' % n)
    return GlobalVars.decitab[n]


def ctimegm(s, format="%Y-%m-%d %H:%M:%S"):
    '''
    Convert string representing UTC time to system time.

    :param s: string to be interpreted
    :param format: format string passed to :py:func:`strptime`

    :returns: system time stamp

    Interpretes string with format ``'%Y-%m-%d %H:%M:%S'``, using strptime.

    .. note::
       This function is to be replaced by :py:func:`str_to_time`.
    '''

    return calendar.timegm(time.strptime(s, format))


def gmctime(t, format="%Y-%m-%d %H:%M:%S"):
    '''
    Get string representation from system time, UTC.

    Produces string with format ``'%Y-%m-%d %H:%M:%S'``, using strftime.

    .. note::
       This function is to be repaced by :py:func:`time_to_str`.
    '''

    return time.strftime(format, time.gmtime(t))


def gmctime_v(t, format="%a, %d %b %Y %H:%M:%S"):
    '''
    Get string representation from system time, UTC. Same as
    :py:func:`gmctime` but with a more verbose default format.

    .. note::
       This function is to be replaced by :py:func:`time_to_str`.
    '''

    return time.strftime(format, time.gmtime(t))


def gmctime_fn(t, format="%Y-%m-%d_%H-%M-%S"):
    '''
    Get string representation from system time, UTC. Same as
    :py:func:`gmctime` but with a default usable in filenames.

    .. note::
       This function is to be replaced by :py:func:`time_to_str`.
    '''

    return time.strftime(format, time.gmtime(t))


class TimeStrError(Exception):
    pass


class FractionalSecondsMissing(TimeStrError):
    '''
    Exception raised by :py:func:`str_to_time` when the given string lacks
    fractional seconds.
    '''

    pass


class FractionalSecondsWrongNumberOfDigits(TimeStrError):
    '''
    Exception raised by :py:func:`str_to_time` when the given string has an
    incorrect number of digits in the fractional seconds part.
    '''

    pass


def _endswith_n(s, endings):
    for ix, x in enumerate(endings):
        if s.endswith(x):
            return ix
    return -1


def str_to_time(s, format='%Y-%m-%d %H:%M:%S.OPTFRAC'):
    '''
    Convert string representing UTC time to floating point system time.

    :param s: string representing UTC time
    :param format: time string format
    :returns: system time stamp as floating point value

    Uses the semantics of :py:func:`time.strptime` but allows for fractional
    seconds. If the format ends with ``'.FRAC'``, anything after a dot is
    interpreted as fractional seconds. If the format ends with ``'.OPTFRAC'``,
    the fractional part, including the dot is made optional. The latter has the
    consequence, that the time strings and the format may not contain any other
    dots. If the format ends with ``'.xFRAC'`` where x is 1, 2, or 3, it is
    ensured, that exactly that number of digits are present in the fractional
    seconds.
    '''

    if util_ext is not None:
        try:
            t, tfrac = util_ext.stt(s, format)
        except util_ext.UtilExtError as e:
            raise TimeStrError(
                '%s, string=%s, format=%s' % (str(e), s, format))

        return t+tfrac

    fracsec = 0.
    fixed_endings = '.FRAC', '.1FRAC', '.2FRAC', '.3FRAC'

    iend = _endswith_n(format, fixed_endings)
    if iend != -1:
        dotpos = s.rfind('.')
        if dotpos == -1:
            raise FractionalSecondsMissing(
                'string=%s, format=%s' % (s, format))

        if iend > 0 and iend != (len(s)-dotpos-1):
            raise FractionalSecondsWrongNumberOfDigits(
                'string=%s, format=%s' % (s, format))

        format = format[:-len(fixed_endings[iend])]
        fracsec = float(s[dotpos:])
        s = s[:dotpos]

    elif format.endswith('.OPTFRAC'):
        dotpos = s.rfind('.')
        format = format[:-8]
        if dotpos != -1 and len(s[dotpos:]) > 1:
            fracsec = float(s[dotpos:])

        if dotpos != -1:
            s = s[:dotpos]

    try:
        return calendar.timegm(time.strptime(s, format)) + fracsec
    except ValueError as e:
        raise TimeStrError('%s, string=%s, format=%s' % (str(e), s, format))


stt = str_to_time


def time_to_str(t, format='%Y-%m-%d %H:%M:%S.3FRAC'):
    '''
    Get string representation for floating point system time.

    :param t: floating point system time
    :param format: time string format
    :returns: string representing UTC time

    Uses the semantics of :py:func:`time.strftime` but additionally allows for
    fractional seconds. If ``format`` contains ``'.xFRAC'``, where ``x`` is a
    digit between 1 and 9, this is replaced with the fractional part of ``t``
    with ``x`` digits precision.
    '''

    if isinstance(format, int):
        if format > 0:
            format = '%Y-%m-%d %H:%M:%S.' + '%iFRAC' % format
        else:
            format = '%Y-%m-%d %H:%M:%S'

    if util_ext is not None:
        t0 = math.floor(t)
        try:
            return util_ext.tts(int(t0), t - t0, format)
        except util_ext.UtilExtError as e:
            raise TimeStrError(
                '%s, timestamp=%f, format=%s' % (str(e), t, format))

    if not GlobalVars.re_frac:
        GlobalVars.re_frac = re.compile(r'\.[1-9]FRAC')
        GlobalVars.frac_formats = dict(
            [('.%sFRAC' % x, '%.'+x+'f') for x in '123456789'])

    ts = float(num.floor(t))
    tfrac = t-ts

    m = GlobalVars.re_frac.search(format)
    if m:
        sfrac = (GlobalVars.frac_formats[m.group(0)] % tfrac)
        if sfrac[0] == '1':
            ts += 1.

        format, nsub = GlobalVars.re_frac.subn(sfrac[1:], format, 1)

    return time.strftime(format, time.gmtime(ts))


tts = time_to_str


def mystrftime(fmt=None, tt=None, milliseconds=0):

    if fmt is None:
        fmt = '%Y-%m-%d %H:%M:%S .%r'

    if tt is None:
        tt = time.time()

    fmt = fmt.replace('%r', '%03i' % int(round(milliseconds)))
    fmt = fmt.replace('%u', '%06i' % int(round(milliseconds*1000)))
    fmt = fmt.replace('%n', '%09i' % int(round(milliseconds*1000000)))
    return time.strftime(fmt, tt)


def gmtime_x(timestamp):
    etimestamp = float(num.floor(timestamp))
    tt = time.gmtime(etimestamp)
    ms = (timestamp-etimestamp)*1000
    return tt, ms


def plural_s(n):
    if n == 1:
        return ''
    else:
        return 's'


def ensuredirs(dst):
    '''
    Create all intermediate path components for a target path.

    :param dst: target path

    The leaf part of the target path is not created (use :py:func:`ensuredir`
    if a the target path is a directory to be created).
    '''

    d, x = os.path.split(dst.rstrip(os.sep))
    dirs = []
    while d and not os.path.exists(d):
        dirs.append(d)
        d, x = os.path.split(d)

    dirs.reverse()

    for d in dirs:
        try:
            os.mkdir(d)
        except OSError as e:
            if not e.errno == errno.EEXIST:
                raise


def ensuredir(dst):
    '''
    Create directory and all intermediate path components to it as needed.

    :param dst: directory name

    Nothing is done if the given target already exists.
    '''

    if os.path.exists(dst):
        return

    dst.rstrip(os.sep)

    ensuredirs(dst)
    try:
        os.mkdir(dst)
    except OSError as e:
        if not e.errno == errno.EEXIST:
            raise


def reuse(x):
    '''
    Get unique instance of an object.

    :param x: hashable object
    :returns: reference to x or an equivalent object

    Cache object ``x`` in a global dict for reuse, or if x already
    is in that dict, return a reference to it.
    '''

    grs = GlobalVars.reuse_store
    if x not in grs:
        grs[x] = x
    return grs[x]


def deuse(x):
    grs = GlobalVars.reuse_store
    if x in grs:
        del grs[x]


class Anon(object):
    '''
    Dict-to-object utility.

    Any given arguments are stored as attributes.

    Example::

        a = Anon(x=1, y=2)
        print a.x, a.y
    '''

    def __init__(self, **dict):
        for k in dict:
            self.__dict__[k] = dict[k]


def select_files(paths, selector=None, regex=None, show_progress=True):
    '''
    Recursively select files.

    :param paths: entry path names
    :param selector: callback for conditional inclusion
    :param regex: pattern for conditional inclusion
    :param show_progress: if True, indicate start and stop of processing
    :returns: list of path names

    Recursively finds all files under given entry points ``paths``. If
    parameter ``regex`` is a regular expression, only files with matching path
    names are included. If additionally parameter ``selector`` is given a
    callback function, only files for which the callback returns ``True`` are
    included. The callback should take a single argument. The callback is
    called with a single argument, an object, having as attributes, any named
    groups given in ``regex``.

    Examples

    To find all files ending in ``'.mseed'`` or ``'.msd'``::

        select_files(paths,
            regex=r'\\.(mseed|msd)$')

    To find all files ending with ``'$Year.$DayOfYear'``, having set 2009 for
    the year::

        select_files(paths,
            regex=r'(?P<year>\\d\\d\\d\\d)\\.(?P<doy>\\d\\d\\d)$',
            selector=(lambda x: int(x.year) == 2009))
    '''

    if show_progress:
        progress_beg('selecting files...')
        if logger.isEnabledFor(logging.DEBUG):
            sys.stderr.write('\n')

    good = []
    if regex:
        rselector = re.compile(regex)

    def addfile(path):
        if regex:
            logger.debug("looking at filename: '%s'" % path)
            m = rselector.search(path)
            if m:
                infos = Anon(**m.groupdict())
                logger.debug("   regex '%s' matches." % regex)
                for k, v in m.groupdict().items():
                    logger.debug(
                        "      attribute '%s' has value '%s'" % (k, v))
                if selector is None or selector(infos):
                    good.append(os.path.abspath(path))

            else:
                logger.debug("   regex '%s' does not match." % regex)
        else:
            good.append(os.path.abspath(path))

    if isinstance(paths, str):
        paths = [paths]

    for path in paths:
        if os.path.isdir(path):
            for (dirpath, dirnames, filenames) in os.walk(path):
                for filename in filenames:
                    addfile(op.join(dirpath, filename))
        else:
            addfile(path)

    if show_progress:
        progress_end('%i file%s selected.' % (len(good), plural_s(len(good))))

    return good


def base36encode(number, alphabet='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'):
    '''
    Convert positive integer to a base36 string.
    '''

    if not isinstance(number, (int, long)):
        raise TypeError('number must be an integer')
    if number < 0:
        raise ValueError('number must be positive')

    # Special case for small numbers
    if number < 36:
        return alphabet[number]

    base36 = ''
    while number != 0:
        number, i = divmod(number, 36)
        base36 = alphabet[i] + base36

    return base36


def base36decode(number):
    '''
    Decode base36 endcoded positive integer.
    '''

    return int(number, 36)


class UnpackError(Exception):
    '''
    Exception raised when :py:func:`unpack_fixed` encounters an error.
    '''

    pass


ruler = ''.join(['%-10i' % i for i in range(8)]) \
    + '\n' + '0123456789' * 8 + '\n'


def unpack_fixed(format, line, *callargs):
    '''
    Unpack fixed format string, as produced by many fortran codes.

    :param format: format specification
    :param line: string to be processed
    :param callargs: callbacks for callback fields in the format

    The format is described by a string of comma-separated fields. Each field
    is defined by a character for the field type followed by the field width. A
    questionmark may be appended to the field description to allow the argument
    to be optional (The data string is then allowed to be filled with blanks
    and ``None`` is returned in this case).

    The following field types are available:

    ====  ================================================================
    Type  Description
    ====  ================================================================
    A     string (full field width is extracted)
    a     string (whitespace at the beginning and the end is removed)
    i     integer value
    f     floating point value
    @     special type, a callback must be given for the conversion
    x     special field type to skip parts of the string
    ====  ================================================================
    '''

    ipos = 0
    values = []
    icall = 0
    for form in format.split(','):
        form = form.strip()
        optional = form[-1] == '?'
        form = form.rstrip('?')
        typ = form[0]
        ln = int(form[1:])
        s = line[ipos:ipos+ln]
        cast = {
            'x': None,
            'A': str,
            'a': lambda x: x.strip(),
            'i': int,
            'f': float,
            '@': 'extra'}[typ]

        if cast == 'extra':
            cast = callargs[icall]
            icall += 1

        if cast is not None:
            if optional and s.strip() == '':
                values.append(None)
            else:
                try:
                    values.append(cast(s))
                except Exception:
                    mark = [' '] * 80
                    mark[ipos:ipos+ln] = ['^'] * ln
                    mark = ''.join(mark)
                    raise UnpackError(
                        'Invalid cast to type "%s" at position [%i:%i] of '
                        'line: \n%s%s\n%s' % (
                            typ, ipos, ipos+ln, ruler, line.rstrip(), mark))

        ipos += ln

    return values


_pattern_cache = {}


def _nslc_pattern(pattern):
    if pattern not in _pattern_cache:
        rpattern = re.compile(fnmatch.translate(pattern), re.I)
        _pattern_cache[pattern] = rpattern
    else:
        rpattern = _pattern_cache[pattern]

    return rpattern


def match_nslc(patterns, nslc):
    '''
    Match network-station-location-channel code against pattern or list of
    patterns.

    :param patterns: pattern or list of patterns
    :param nslc: tuple with (network, station, location, channel) as strings

    :returns: ``True`` if the pattern matches or if any of the given patterns
        match; or ``False``.

    The patterns may contain shell-style wildcards: \\*, ?, [seq], [!seq].

    Example::

        match_nslc('*.HAM3.*.BH?', ('GR', 'HAM3', '', 'BHZ'))   # -> True
    '''

    if isinstance(patterns, str):
        patterns = [patterns]

    if not isinstance(nslc, str):
        s = '.'.join(nslc)
    else:
        s = nslc

    for pattern in patterns:
        if _nslc_pattern(pattern).match(s):
            return True

    return False


def match_nslcs(patterns, nslcs):
    '''
    Get network-station-location-channel codes that match given pattern or any
    of several given patterns.

    :param patterns: pattern or list of patterns
    :param nslcs: list of (network, station, location, channel) tuples

    See also :py:func:`match_nslc`
    '''

    matching = []
    for nslc in nslcs:
        if match_nslc(patterns, nslc):
            matching.append(nslc)

    return matching


class SoleError(Exception):
    '''
    Exception raised by objects of type :py:class:`Sole`, when an concurrent
    instance is running.
    '''

    pass


class Sole(object):
    '''
    Use POSIX advisory file locking to ensure that only a single instance of a
    program is running.

    :param pid_path: path to lockfile to be used

    Usage::

        from pyrocko.util import Sole, SoleError, setup_logging
        import os

        setup_logging('my_program')

        pid_path =  os.path.join(os.environ['HOME'], '.my_program_lock')
        try:
            sole = Sole(pid_path)

        except SoleError, e:
            logger.fatal( str(e) )
            sys.exit(1)
    '''

    def __init__(self, pid_path):
        self._pid_path = pid_path
        self._other_running = False
        ensuredirs(self._pid_path)
        self._lockfile = None
        self._os = os
        self._fcntl = fcntl

        try:
            self._lockfile = os.open(self._pid_path, os.O_CREAT | os.O_WRONLY)
        except Exception:
            raise SoleError(
                'Cannot open lockfile (path = %s)' % self._pid_path)

        try:
            fcntl.lockf(self._lockfile, fcntl.LOCK_EX | fcntl.LOCK_NB)

        except IOError:
            self._other_running = True
            try:
                f = open(self._pid_path, 'r')
                pid = f.read().strip()
                f.close()
            except Exception:
                pid = '?'

            raise SoleError('Other instance is running (pid = %s)' % pid)

        try:
            os.ftruncate(self._lockfile, 0)
            os.write(self._lockfile, '%i\n' % os.getpid())
            os.fsync(self._lockfile)

        except Exception:
            # the pid is only stored for user information, so this is allowed
            # to fail
            pass

    def __del__(self):
        if not self._other_running:
            if self._lockfile is not None:
                self._fcntl.lockf(self._lockfile, self._fcntl.LOCK_UN)
                self._os.close(self._lockfile)
            try:
                self._os.unlink(self._pid_path)
            except Exception:
                pass


re_escapequotes = re.compile(r"(['\\])")


def escapequotes(s):
    return re_escapequotes.sub(r"\\\1", s)


class TableWriter(object):
    '''
    Write table of space separated values to a file.

    :param f: file like object

    Strings containing spaces are quoted on output.
    '''

    def __init__(self, f):
        self._f = f

    def writerow(self, row, minfieldwidths=None):

        '''
        Write one row of values to underlying file.

        :param row: iterable of values
        :param minfieldwidths: minimum field widths for the values

        Each value in in ``row`` is converted to a string and optionally padded
        with blanks. The resulting strings are output separated with blanks. If
        any values given are strings and if they contain whitespace, they are
        quoted with single quotes, and any internal single quotes are
        backslash-escaped.
        '''

        out = []

        for i, x in enumerate(row):
            w = 0
            if minfieldwidths and i < len(minfieldwidths):
                w = minfieldwidths[i]

            if isinstance(x, str):
                if re.search(r"\s|'", x):
                    x = "'%s'" % escapequotes(x)

                x = x.ljust(w)
            else:
                x = str(x).rjust(w)

            out.append(x)

        self._f.write(' '.join(out).rstrip() + '\n')


class TableReader(object):

    '''
    Read table of space separated values from a file.

    :param f: file-like object

    This uses Pythons shlex module to tokenize lines. Should deal correctly
    with quoted strings.
    '''

    def __init__(self, f):
        self._f = f
        self.eof = False

    def readrow(self):
        '''
        Read one row from the underlying file, tokenize it with shlex.

        :returns: tokenized line as a list of strings.
        '''

        line = self._f.readline()
        if not line:
            self.eof = True
            return []
        s = shlex.shlex(line, posix=True)
        s.whitespace_split = True
        s.whitespace = ' \t\n\r\f\v'  # compatible with re's \s
        row = []
        while True:
            x = s.get_token()
            if x is None:
                break
            row.append(x)

        return row


def gform(number, significant_digits=3):
    '''
    Pretty print floating point numbers.

    Align floating point numbers at the decimal dot.

    ::

      |  -d.dde+xxx|
      |  -d.dde+xx |
      |-ddd.       |
      | -dd.d      |
      |  -d.dd     |
      |  -0.ddd    |
      |  -0.0ddd   |
      |  -0.00ddd  |
      |  -d.dde-xx |
      |  -d.dde-xxx|
      |         nan|


    The formatted string has length ``significant_digits * 2 + 6``.
    '''

    no_exp_range = (pow(10., -1),
                    pow(10., significant_digits))
    width = significant_digits+significant_digits-1+1+1+5

    if (no_exp_range[0] <= abs(number) < no_exp_range[1]) or number == 0.:
        s = ('%#.*g' % (significant_digits, number)).rstrip('0')
    else:
        s = '%.*E' % (significant_digits-1, number)
    s = (' '*(-s.find('.')+(significant_digits+1))+s).ljust(width)
    if s.strip().lower() == 'nan':
        s = 'nan'.rjust(width)
    return s


def human_bytesize(value):

    exts = 'Bytes kB MB GB TB PB EB ZB YB'.split()

    if value == 1:
        return '1 Byte'

    for i, ext in enumerate(exts):
        x = float(value) / 1000**i
        if round(x) < 10. and not value < 1000:
            return '%.1f %s' % (x, ext)
        if round(x) < 1000.:
            return '%.0f %s' % (x, ext)

    return '%i Bytes' % value


re_compatibility = re.compile(
    r'!pyrocko\.(trace|gf\.(meta|seismosizer)|fomosto\.' +
    r'(dummy|poel|qseis|qssp))\.'
)


def pf_is_old(fn):
    oldstyle = False
    with open(fn, 'r') as f:
        for line in f:
            if re_compatibility.search(line):
                oldstyle = True

    return oldstyle


def pf_upgrade(fn):
    need = pf_is_old(fn)
    if need:
        fn_temp = fn + '.temp'

        with open(fn, 'r') as fin:
            with open(fn_temp, 'w') as fout:
                for line in fin:
                    line = re_compatibility.sub('!pf.', line)
                    fout.write(line)

        os.rename(fn_temp, fn)

    return need


def read_leap_seconds(tzfile='/usr/share/zoneinfo/right/UTC'):
    '''
    Extract leap second information from tzdata.

    Based on example at http://stackoverflow.com/questions/19332902/\
            extract-historic-leap-seconds-from-tzdata

    See also 'man 5 tzfile'.
    '''

    from struct import unpack, calcsize
    out = []
    with open(tzfile, 'rb') as f:
        # read header
        fmt = '>4s c 15x 6l'
        (magic, format, ttisgmtcnt, ttisstdcnt, leapcnt, timecnt,
            typecnt, charcnt) = unpack(fmt, f.read(calcsize(fmt)))
        assert magic == 'TZif'.encode('US-ASCII'), 'Not a timezone file'

        # skip over some uninteresting data
        fmt = '>%(timecnt)dl %(timecnt)dB %(ttinfo)s %(charcnt)ds' % dict(
            timecnt=timecnt, ttinfo='lBB'*typecnt, charcnt=charcnt)
        f.read(calcsize(fmt))

        # read leap-seconds
        fmt = '>2l'
        for i in range(leapcnt):
            tleap, nleap = unpack(fmt, f.read(calcsize(fmt)))
            out.append((tleap-nleap+1, nleap))

    return out


class LeapSecondsError(Exception):
    pass


class LeapSecondsOutdated(LeapSecondsError):
    pass


class InvalidLeapSecondsFile(LeapSecondsOutdated):
    pass


def parse_leap_seconds_list(fn):
    data = []
    texpires = None
    try:
        t0 = int(round(str_to_time('1900-01-01 00:00:00')))
    except TimeStrError:
        t0 = int(round(str_to_time('1970-01-01 00:00:00'))) - 2208988800

    tnow = int(round(time.time()))

    if not op.exists(fn):
        raise LeapSecondsOutdated('no leap seconds file found')

    try:
        with open(fn, 'rb') as f:
            for line in f:
                if line.strip().startswith(b'<!DOCTYPE'):
                    raise InvalidLeapSecondsFile('invalid leap seconds file')

                if line.startswith(b'#@'):
                    texpires = int(line.split()[1]) + t0
                elif line.startswith(b'#') or len(line) < 5:
                    pass
                else:
                    toks = line.split()
                    t = int(toks[0]) + t0
                    nleap = int(toks[1]) - 10
                    data.append((t, nleap))

    except IOError:
        raise LeapSecondsError('cannot read leap seconds file %s' % fn)

    if texpires is None or tnow > texpires:
        raise LeapSecondsOutdated('leap seconds list is outdated')

    return data


def read_leap_seconds2():
    from pyrocko import config
    conf = config.config()
    fn = conf.leapseconds_path
    url = conf.leapseconds_url
    # check for outdated default URL
    if url == 'http://www.ietf.org/timezones/data/leap-seconds.list':
        url = 'https://www.ietf.org/timezones/data/leap-seconds.list'
        logger.info(
            'Leap seconds default URL is now: %s\nUsing new default.' % url)

    for i in range(3):
        try:
            return parse_leap_seconds_list(fn)

        except LeapSecondsOutdated:
            try:
                logger.info('updating leap seconds list...')
                download_file(url, fn)

            except Exception as e:
                raise LeapSecondsError(
                    'cannot download leap seconds list from %s to %s (%s)'
                    % (url, fn, e))

    raise LeapSecondsError('Could not retrieve/read leap seconds file.')


def gps_utc_offset(t_utc):
    '''Time offset t_gps - t_utc for a given t_utc.'''
    ls = read_leap_seconds2()
    i = 0
    if t_utc < ls[0][0]:
        return ls[0][1] - 1 - 9

    while i < len(ls) - 1:
        if ls[i][0] <= t_utc and t_utc < ls[i+1][0]:
            return ls[i][1] - 9
        i += 1

    return ls[-1][1] - 9


def utc_gps_offset(t_gps):
    '''Time offset t_utc - t_gps for a given t_gps.'''
    ls = read_leap_seconds2()

    if t_gps < ls[0][0] + ls[0][1] - 9:
        return - (ls[0][1] - 1 - 9)

    i = 0
    while i < len(ls) - 1:
        if ls[i][0] + ls[i][1] - 9 <= t_gps \
                and t_gps < ls[i+1][0] + ls[i+1][1] - 9:
            return - (ls[i][1] - 9)
        i += 1

    return - (ls[-1][1] - 9)


def make_iload_family(iload_fh, doc_fmt='FMT', doc_yielded_objects='FMT'):
    import itertools
    import glob
    from pyrocko.io.io_common import FileLoadError

    def iload_filename(filename, **kwargs):
        try:
            with open(filename, 'rb') as f:
                for cr in iload_fh(f, **kwargs):
                    yield cr

        except FileLoadError as e:
            e.set_context('filename', filename)
            raise

    def iload_dirname(dirname, **kwargs):
        for entry in os.listdir(dirname):
            fpath = op.join(dirname, entry)
            if op.isfile(fpath):
                for cr in iload_filename(fpath, **kwargs):
                    yield cr

    def iload_glob(pattern, **kwargs):

        for fn in glob.iglob(pattern):
            for cr in iload_filename(fn, **kwargs):
                yield cr

    def iload(source, **kwargs):
        if isinstance(source, str):
            if op.isdir(source):
                return iload_dirname(source, **kwargs)
            elif op.isfile(source):
                return iload_filename(source, **kwargs)
            else:
                return iload_glob(source, **kwargs)

        elif hasattr(source, 'read'):
            return iload_fh(source, **kwargs)
        else:
            return itertools.chain.from_iterable(
                iload(subsource, **kwargs) for subsource in source)

    iload_filename.__doc__ = '''
        Read %s information from named file.
    ''' % doc_fmt

    iload_dirname.__doc__ = '''
        Read %s information from directory of %s files.
    ''' % (doc_fmt, doc_fmt)

    iload_glob.__doc__ = '''
        Read %s information from files matching a glob pattern.
    ''' % doc_fmt

    iload.__doc__ = '''
        Load %s information from given source(s)

        The ``source`` can be specified as the name of a %s file, the name of a
        directory containing %s files, a glob pattern of %s files, an open
        filehandle or an iterator yielding any of the forementioned sources.

        This function behaves as a generator yielding %s objects.
    ''' % (doc_fmt, doc_fmt, doc_fmt, doc_fmt, doc_yielded_objects)

    for f in iload_filename, iload_dirname, iload_glob, iload:
        f.__module__ = iload_fh.__module__

    return iload_filename, iload_dirname, iload_glob, iload


class Inconsistency(Exception):
    pass


def consistency_check(list_of_tuples, message='values differ:'):
    '''
    Check for inconsistencies.

    Given a list of tuples, check that all tuple elements except for first one
    match. E.g. ``[('STA.N', 55.3, 103.2), ('STA.E', 55.3, 103.2)]`` would be
    valid because the coordinates at the two channels are the same.
    '''

    if len(list_of_tuples) >= 2:
        if any(t[1:] != list_of_tuples[0][1:] for t in list_of_tuples[1:]):
            raise Inconsistency('%s\n' % message + '\n'.join(
                '  %s: %s' % (t[0], ', '.join('%g' % x for x in t[1:]))
                for t in list_of_tuples))


class defaultzerodict(dict):
    def __missing__(self, k):
        return 0


def mostfrequent(x):
    c = defaultzerodict()
    for e in x:
        c[e] += 1

    return sorted(list(c.keys()), key=lambda k: c[k])[-1]


def consistency_merge(list_of_tuples,
                      message='values differ:',
                      error='raise',
                      merge=mostfrequent):

    assert error in ('raise', 'warn', 'ignore')

    if len(list_of_tuples) == 0:
        raise Exception('cannot merge empty sequence')

    try:
        consistency_check(list_of_tuples, message)
        return list_of_tuples[0][1:]
    except Inconsistency as e:
        if error == 'raise':
            raise

        elif error == 'warn':
            logger.warning(str(e))

        return tuple([merge(x) for x in list(zip(*list_of_tuples))[1:]])


def parse_md(f):
    try:
        with open(op.join(
                op.dirname(op.abspath(f)),
                  'README.md'), 'r') as readme:
            mdstr = readme.read()
    except IOError as e:
        return 'Failed to get README.md: %s' % e

    # Remve the title
    mdstr = re.sub(r'^# .*\n?', '', mdstr)
    # Append sphinx reference to `pyrocko.` modules
    mdstr = re.sub(r'`pyrocko\.(.*)`', r':py:mod:`pyrocko.\1`', mdstr)
    # Convert Subsections to toc-less rubrics
    mdstr = re.sub(r'## (.*)\n', r'.. rubric:: \1\n', mdstr)
    return mdstr


def mpl_show(plt):
    import matplotlib
    if matplotlib.get_backend().lower() == 'agg':
        logger.warning('Cannot show() when using matplotlib "agg" backend')
    else:
        plt.show()
