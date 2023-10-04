# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for `SAC
<http://ds.iris.edu/ds/nodes/dmc/software/downloads/sac/>`_ pole-zero files.

See also :py:mod:`~pyrocko.io.enhanced_sacpz`.
'''

import math
import numpy as num
try:
    from StringIO import StringIO as BytesIO
except ImportError:
    from io import BytesIO

from pyrocko import trace

d2r = math.pi/180.


class SacPoleZeroError(Exception):
    pass


def read_sac_zpk(filename=None, file=None, string=None, get_comments=False):
    '''
    Read SAC pole-zero file.

    :returns: ``(zeros, poles, constant)`` or
        ``(zeros, poles, constant, comments)`` if ``get_comments`` is True.
    '''

    if filename is not None:
        f = open(filename, 'rb')

    elif file is not None:
        f = file

    elif string is not None:
        f = BytesIO(string)

    sects = ('ZEROS', 'POLES', 'CONSTANT')
    sectdata = {'ZEROS': [], 'POLES': []}
    npoles = 0
    nzeros = 0
    constant = 1.0
    atsect = None
    comments = []
    for iline, line in enumerate(f):
        line = str(line.decode('ascii'))
        toks = line.split()
        if len(toks) == 0:
            continue

        if toks[0][0] in '*#':
            comments.append(line)
            continue

        if len(toks) != 2:
            f.close()
            raise SacPoleZeroError(
                'Expected 2 tokens in line %i of file %s'
                % (iline+1, filename))

        if toks[0].startswith('*'):
            continue

        lsect = toks[0].upper()
        if lsect in sects:
            atsect = lsect
            sectdata[atsect] = []
            if lsect.upper() == 'ZEROS':
                nzeros = int(toks[1])
            elif toks[0].upper() == 'POLES':
                npoles = int(toks[1])
            elif toks[0].upper() == 'CONSTANT':
                constant = float(toks[1])
        else:
            if atsect:
                sectdata[atsect].append(
                    complex(float(toks[0]), float(toks[1])))

    if f != file:
        f.close()

    poles = sectdata['POLES']
    zeros = sectdata['ZEROS']
    npoles_ = len(poles)
    nzeros_ = len(zeros)
    if npoles_ > npoles:
        raise SacPoleZeroError(
            'Expected %i poles but found %i in pole-zero file "%s"'
            % (npoles, npoles_, filename))
    if nzeros_ > nzeros:
        raise SacPoleZeroError(
            'Expected %i zeros but found %i in pole-zero file "%s"'
            % (nzeros, nzeros_, filename))

    if npoles_ < npoles:
        poles.extend([complex(0.)]*(npoles-npoles_))

    if nzeros_ < npoles:
        zeros.extend([complex(0.)]*(nzeros-nzeros_))

    if len(poles) == 0 and len(zeros) == 0:
        raise SacPoleZeroError(
            'No poles and zeros found in file "%s"' % (filename))

    if not num.all(num.isfinite(poles)):
        raise SacPoleZeroError(
            'Not finite pole(s) found in pole-zero file "%s"'
            % filename)

    if not num.all(num.isfinite(zeros)):
        raise SacPoleZeroError(
            'Not finite zero(s) found in pole-zero file "%s"'
            % filename)

    if not num.isfinite(constant):
        raise SacPoleZeroError(
            'Ivalid constant (%g) found in pole-zero file "%s"'
            % (constant, filename))

    if get_comments:
        return zeros, poles, constant, comments
    else:
        return zeros, poles, constant


def write_sac_zpk(zeros, poles, constant, filename):
    if hasattr(filename, 'write'):
        f = filename
    else:
        f = open('w', filename)

    def write_complex(x):
        f.write('%12.8g %12.8g\n' % (complex(x).real, complex(x).imag))

    f.write('POLES %i\n' % len(poles))
    for p in poles:
        if p != 0.0:
            write_complex(p)

    f.write('ZEROS %i\n' % len(zeros))
    for z in zeros:
        if z != 0.0:
            write_complex(z)

    f.write('CONSTANT %12.8g\n' % constant)
    if not hasattr(filename, 'write'):
        f.close()


def evaluate(zeros, poles, constant, fmin=0.001, fmax=100., nf=100):

    logfmin = math.log(fmin)
    logfmax = math.log(fmax)
    logf = num.linspace(logfmin, logfmax, nf)
    f = num.exp(logf)
    trans = trace.PoleZeroResponse(zeros, poles, constant)
    return f, trans.evaluate(f)


def evaluate_at(zeros, poles, constant, f):
    jomeg = 1.0j * 2. * math.pi * f

    a = constant
    for z in zeros:
        a *= jomeg-z
    for p in poles:
        a /= jomeg-p

    return a


def read_to_pyrocko_response(filename=None, file=None, string=None):
    '''
    Read SAC pole-zero file into Pyrocko response object.

    :returns: Response as a :py:class:~pyrocko.trace.PoleZeroResponse` object.
    '''

    from pyrocko import trace

    zeros, poles, constant = read_sac_zpk(
        filename=filename, file=file, string=string)
    return trace.PoleZeroResponse(zeros, poles, constant)


def read_to_stationxml_response(
        input_unit, output_unit, normalization_frequency=1.0,
        filename=None, file=None, string=None):
    '''
    Read SAC pole-zero file into StationXML response object.

    :param input_unit: Input unit to be reported in the StationXML response.
    :type input_unit: str
    :param output_unit: Output unit to be reported in the StationXML response.
    :type output_unit: str
    :param normalization_frequency: Frequency where the normalization factor
        for the StationXML response should be computed.
    :type normalization_frequency: float

    :returns: Response as a :py:class:~pyrocko.io.stationxml.Response` object
        with a single pole-zero response stage.
    '''

    from pyrocko.io import stationxml

    presponse = read_to_pyrocko_response(
        filename=filename, file=file, string=string)

    return stationxml.Response.from_pyrocko_pz_response(
        presponse, input_unit, output_unit, normalization_frequency)


def plot_amplitudes_zpk(
        zpks, filename_pdf,
        fmin=0.001,
        fmax=100.,
        nf=100,
        fnorm=None):

    from pyrocko.plot import gmtpy

    p = gmtpy.LogLogPlot(width=30*gmtpy.cm, yexp=0)
    for i, (zeros, poles, constant) in enumerate(zpks):
        f, h = evaluate(zeros, poles, constant, fmin, fmax, nf)
        if fnorm is not None:
            h /= evaluate_at(zeros, poles, constant, fnorm)

        amp = num.abs(h)
        p.plot((f, amp), '-W2p,%s' % gmtpy.color(i))

    p.save(filename_pdf)


def plot_phases_zpk(zpks, filename_pdf, fmin=0.001, fmax=100., nf=100):

    from pyrocko.plot import gmtpy

    p = gmtpy.LogLinPlot(width=30*gmtpy.cm)
    for i, (zeros, poles, constant) in enumerate(zpks):
        f, h = evaluate(zeros, poles, constant, fmin, fmax, nf)
        phase = num.unwrap(num.angle(h)) / d2r
        p.plot((f, phase), '-W1p,%s' % gmtpy.color(i))

    p.save(filename_pdf)
