# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Frequency response parameterizations useful as transfer functions in signal
processing.
'''

import math
import logging
import uuid

import numpy as num
from scipy import signal

from pyrocko import util, evalresp
from pyrocko.guts import Object, Float, Int, String, Complex, Tuple, List, \
    StringChoice, Bool
from pyrocko.guts_array import Array


guts_prefix = 'pf'

logger = logging.getLogger('pyrocko.response')


def asarray_1d(x, dtype):
    if isinstance(x, (list, tuple)) and x and isinstance(x[0], str):
        return num.asarray(list(map(dtype, x)), dtype=dtype)
    else:
        a = num.asarray(x, dtype=dtype)
        if not a.ndim == 1:
            raise ValueError('Could not convert to 1D array.')
        return a


def finalize_construction(breakpoints):
    breakpoints.sort()
    breakpoints_out = []
    f_last = None
    for f, c in breakpoints:
        if f_last is not None and f == f_last:
            breakpoints_out[-1][1] += c
        else:
            breakpoints_out.append([f, c])

        f_last = f

    breakpoints_out = [(f, c) for (f, c) in breakpoints_out if c != 0]
    return breakpoints_out


class FrequencyResponseCheckpoint(Object):
    frequency = Float.T()
    value = Float.T()


class IsNotScalar(Exception):
    pass


def str_fmax_failsafe(resp):
    try:
        return '%g' % resp.get_fmax()
    except InvalidResponseError:
        return '?'


class FrequencyResponse(Object):
    '''
    Base class for parameterized frequency responses.
    '''

    checkpoints = List.T(
        FrequencyResponseCheckpoint.T())

    def __init__(self, *args, **kwargs):
        Object.__init__(self, *args, **kwargs)
        self.uuid = uuid.uuid4()

    def evaluate(self, freqs):
        '''
        Evaluate the response at given frequencies.

        :param freqs:
            Frequencies [Hz].
        :type freqs:
            :py:class:`numpy.ndarray` of shape ``(N,)`` and dtype
            :py:class:`float`

        :returns:
            Complex coefficients of the response.
        :rtype:
            :py:class:`numpy.ndarray` of shape ``(N,)`` and dtype
            :py:class:`complex`
        '''
        return num.ones(freqs.size, dtype=complex)

    def evaluate1(self, freq):
        '''
        Evaluate the response at a single frequency.

        :param freq:
            Frequency [Hz].
        :type freqs:
            float

        :returns:
            Complex response coefficient.
        :rtype:
            complex
        '''
        return self.evaluate(num.atleast_1d(freq))[0]

    def is_scalar(self):
        '''
        Check if this is a flat response.
        '''

        if type(self) is FrequencyResponse:
            return True
        else:
            return False  # default for derived classes

    def get_scalar(self):
        '''
        Get factor if this is a flat response.
        '''
        if type(self) is FrequencyResponse:
            return 1.0
        else:
            raise IsNotScalar()  # default for derived classes

    def get_fmax(self):
        '''
        Get maximum frequency for which the response is defined.

        :returns:
            ``None`` if the response has no upper limit, otherwise the maximum
            frequency in [Hz] for which the response is valid is returned.
        :rtype:
            float or None
        '''
        return None

    def construction(self):
        return []

    @property
    def summary(self):
        '''
        Short summary with key information about the response object.
        '''
        if type(self) is FrequencyResponse:
            return 'one'
        else:
            return 'unknown'


def str_gain(gain):
    if gain == 1.0:
        return 'one'
    elif isinstance(gain, complex):
        return 'gain{%s}' % repr(gain)
    else:
        return 'gain{%g}' % gain


class Gain(FrequencyResponse):
    '''
    A flat frequency response.
    '''

    constant = Complex.T(default=1.0+0j)

    def evaluate(self, freqs):
        return util.num_full_like(freqs, self.constant, dtype=complex)

    def is_scalar(self):
        return True

    def get_scalar(self):
        return self.constant

    @property
    def summary(self):
        return str_gain(self.constant)


class Evalresp(FrequencyResponse):
    '''
    Calls evalresp and generates values of the instrument response transfer
    function.

    :param respfile: response file in evalresp format
    :param trace: trace for which the response is to be extracted from the file
    :param target: ``'dis'`` for displacement or ``'vel'`` for velocity
    '''

    respfile = String.T()
    nslc_id = Tuple.T(4, String.T())
    target = String.T(default='dis')
    instant = Float.T()
    stages = Tuple.T(2, Int.T(), optional=True)

    def __init__(
            self,
            respfile,
            trace=None,
            target='dis',
            nslc_id=None,
            time=None,
            stages=None,
            **kwargs):

        if trace is not None:
            nslc_id = trace.nslc_id
            time = (trace.tmin + trace.tmax) / 2.

        FrequencyResponse.__init__(
            self,
            respfile=respfile,
            nslc_id=nslc_id,
            instant=time,
            target=target,
            stages=stages,
            **kwargs)

    def evaluate(self, freqs):
        network, station, location, channel = self.nslc_id
        if self.stages is None:
            stages = (-1, 0)
        else:
            stages = self.stages[0]+1, self.stages[1]

        x = evalresp.evalresp(
            sta_list=station,
            cha_list=channel,
            net_code=network,
            locid=location,
            instant=self.instant,
            freqs=freqs,
            units=self.target.upper(),
            file=self.respfile,
            start_stage=stages[0],
            stop_stage=stages[1],
            rtype='CS')

        transfer = x[0][4]
        return transfer

    @property
    def summary(self):
        return 'eresp'


class InverseEvalresp(FrequencyResponse):
    '''
    Calls evalresp and generates values of the inverse instrument response for
    deconvolution of instrument response.

    :param respfile: response file in evalresp format
    :param trace: trace for which the response is to be extracted from the file
    :param target: ``'dis'`` for displacement or ``'vel'`` for velocity
    '''

    respfile = String.T()
    nslc_id = Tuple.T(4, String.T())
    target = String.T(default='dis')
    instant = Float.T()

    def __init__(self, respfile, trace, target='dis', **kwargs):
        FrequencyResponse.__init__(
            self,
            respfile=respfile,
            nslc_id=trace.nslc_id,
            instant=(trace.tmin + trace.tmax)/2.,
            target=target,
            **kwargs)

    def evaluate(self, freqs):
        network, station, location, channel = self.nslc_id
        x = evalresp.evalresp(sta_list=station,
                              cha_list=channel,
                              net_code=network,
                              locid=location,
                              instant=self.instant,
                              freqs=freqs,
                              units=self.target.upper(),
                              file=self.respfile,
                              rtype='CS')

        transfer = x[0][4]
        return 1./transfer

    @property
    def summary(self):
        return 'inv_eresp'


def aslist(x):
    if x is None:
        return []

    try:
        return list(x)
    except TypeError:
        return [x]


class PoleZeroResponse(FrequencyResponse):
    '''
    Evaluates frequency response from pole-zero representation.

    :param zeros: positions of zeros
    :type zeros: :py:class:`list` of :py:class:`complex`
    :param poles: positions of poles
    :type poles: :py:class:`list` of :py:class:`complex`
    :param constant: gain factor
    :type constant: complex

    ::

                           (j*2*pi*f - zeros[0]) * (j*2*pi*f - zeros[1]) * ...
         T(f) = constant * ----------------------------------------------------
                           (j*2*pi*f - poles[0]) * (j*2*pi*f - poles[1]) * ...


    The poles and zeros should be given as angular frequencies, not in Hz.
    '''

    zeros = List.T(Complex.T())
    poles = List.T(Complex.T())
    constant = Complex.T(default=1.0+0j)

    def __init__(
            self,
            zeros=None,
            poles=None,
            constant=1.0+0j,
            **kwargs):

        if zeros is None:
            zeros = []
        if poles is None:
            poles = []

        FrequencyResponse.__init__(
            self,
            zeros=aslist(zeros),
            poles=aslist(poles),
            constant=constant,
            **kwargs)

    def evaluate(self, freqs):
        if hasattr(signal, 'freqs_zpk'):  # added in scipy 0.19.0
            return signal.freqs_zpk(
                self.zeros, self.poles, self.constant, freqs*2.*num.pi)[1]
        else:
            jomeg = 1.0j * 2.*num.pi*freqs

            a = num.ones(freqs.size, dtype=complex)*self.constant
            for z in self.zeros:
                a *= jomeg-z
            for p in self.poles:
                a /= jomeg-p

            return a

    def is_scalar(self):
        return len(self.zeros) == 0 and len(self.poles) == 0

    def get_scalar(self):
        '''
        Get factor if this is a flat response.
        '''
        if self.is_scalar():
            return self.constant
        else:
            raise IsNotScalar()

    def inverse(self):
        return PoleZeroResponse(
            poles=list(self.zeros),
            zeros=list(self.poles),
            constant=1.0/self.constant)

    def to_analog(self):
        b, a = signal.zpk2tf(self.zeros, self.poles, self.constant)
        return AnalogFilterResponse(aslist(b), aslist(a))

    def to_digital(self, deltat, method='bilinear'):
        from scipy.signal import cont2discrete, zpk2tf

        z, p, k, _ = cont2discrete(
            (self.zeros, self.poles, self.constant),
            deltat, method=method)

        b, a = zpk2tf(z, p, k)

        return DigitalFilterResponse(b, a, deltat)

    def to_digital_polezero(self, deltat, method='bilinear'):
        from scipy.signal import cont2discrete

        z, p, k, _ = cont2discrete(
            (self.zeros, self.poles, self.constant),
            deltat, method=method)

        return DigitalPoleZeroResponse(z, p, k, deltat)

    def construction(self):
        breakpoints = []
        for zero in self.zeros:
            f = abs(zero) / (2.*math.pi)
            breakpoints.append((f, 1))

        for pole in self.poles:
            f = abs(pole) / (2.*math.pi)
            breakpoints.append((f, -1))

        return finalize_construction(breakpoints)

    @property
    def summary(self):
        if self.is_scalar():
            return str_gain(self.get_scalar())

        return 'pz{%i,%i}' % (len(self.poles), len(self.zeros))


class DigitalPoleZeroResponse(FrequencyResponse):
    '''
    Evaluates frequency response from digital filter pole-zero representation.

    :param zeros: positions of zeros
    :type zeros: :py:class:`list` of :py:class:`complex`
    :param poles: positions of poles
    :type poles: :py:class:`list` of :py:class:`complex`
    :param constant: gain factor
    :type constant: complex
    :param deltat: sampling interval
    :type deltat: float

    The poles and zeros should be given as angular frequencies, not in Hz.
    '''

    zeros = List.T(Complex.T())
    poles = List.T(Complex.T())
    constant = Complex.T(default=1.0+0j)
    deltat = Float.T()

    def __init__(
            self,
            zeros=None,
            poles=None,
            constant=1.0+0j,
            deltat=None,
            **kwargs):

        if zeros is None:
            zeros = []
        if poles is None:
            poles = []
        if deltat is None:
            raise ValueError(
                'Sampling interval `deltat` must be given for '
                'DigitalPoleZeroResponse.')

        FrequencyResponse.__init__(
            self, zeros=aslist(zeros), poles=aslist(poles), constant=constant,
            deltat=deltat, **kwargs)

    def check_sampling_rate(self):
        if self.deltat == 0.0:
            raise InvalidResponseError(
                'Invalid digital response: sampling rate undefined.')

    def get_fmax(self):
        self.check_sampling_rate()
        return 0.5 / self.deltat

    def evaluate(self, freqs):
        self.check_sampling_rate()
        return signal.freqz_zpk(
            self.zeros, self.poles, self.constant,
            freqs*(2.*math.pi*self.deltat))[1]

    def is_scalar(self):
        return len(self.zeros) == 0 and len(self.poles) == 0

    def get_scalar(self):
        '''
        Get factor if this is a flat response.
        '''
        if self.is_scalar():
            return self.constant
        else:
            raise IsNotScalar()

    def to_digital(self, deltat):
        self.check_sampling_rate()
        from scipy.signal import zpk2tf

        b, a = zpk2tf(self.zeros, self.poles, self.constant)
        return DigitalFilterResponse(b, a, deltat)

    @property
    def summary(self):
        if self.is_scalar():
            return str_gain(self.get_scalar())

        return 'dpz{%i,%i,%s}' % (
            len(self.poles), len(self.zeros), str_fmax_failsafe(self))


class ButterworthResponse(FrequencyResponse):
    '''
    Butterworth frequency response.

    :param corner: corner frequency of the response
    :param order: order of the response
    :param type: either ``high`` or ``low``
    '''

    corner = Float.T(default=1.0)
    order = Int.T(default=4)
    type = StringChoice.T(choices=['low', 'high'], default='low')

    def to_polezero(self):
        z, p, k = signal.butter(
            self.order, self.corner*2.*math.pi,
            btype=self.type, analog=True, output='zpk')

        return PoleZeroResponse(
            zeros=aslist(z),
            poles=aslist(p),
            constant=float(k))

    def to_digital(self, deltat):
        b, a = signal.butter(
            self.order, self.corner*2.*deltat,
            self.type, analog=False)

        return DigitalFilterResponse(b, a, deltat)

    def to_analog(self):
        b, a = signal.butter(
            self.order, self.corner*2.*math.pi,
            self.type, analog=True)

        return AnalogFilterResponse(b, a)

    def to_digital_polezero(self, deltat):
        z, p, k = signal.butter(
            self.order, self.corner*2*deltat,
            btype=self.type, analog=False, output='zpk')

        return DigitalPoleZeroResponse(z, p, k, deltat)

    def evaluate(self, freqs):
        b, a = signal.butter(
            self.order, self.corner*2.*math.pi,
            self.type, analog=True)

        return signal.freqs(b, a, freqs*2.*math.pi)[1]

    @property
    def summary(self):
        return 'butter_%s{%i,%g}' % (
            self.type,
            self.order,
            self.corner)


class SampledResponse(FrequencyResponse):
    '''
    Interpolates frequency response given at a set of sampled frequencies.

    :param frequencies,values: frequencies and values of the sampled response
        function.
    :param left,right: values to return when input is out of range. If set to
        ``None`` (the default) the endpoints are returned.
    '''

    frequencies = Array.T(shape=(None,), dtype=float, serialize_as='list')
    values = Array.T(shape=(None,), dtype=complex, serialize_as='list')
    left = Complex.T(optional=True)
    right = Complex.T(optional=True)

    def __init__(self, frequencies, values, left=None, right=None, **kwargs):
        FrequencyResponse.__init__(
            self,
            frequencies=asarray_1d(frequencies, float),
            values=asarray_1d(values, complex),
            **kwargs)

    def evaluate(self, freqs):
        ereal = num.interp(
            freqs, self.frequencies, num.real(self.values),
            left=self.left, right=self.right)
        eimag = num.interp(
            freqs, self.frequencies, num.imag(self.values),
            left=self.left, right=self.right)
        transfer = ereal + 1.0j*eimag
        return transfer

    def inverse(self):
        '''
        Get inverse as a new :py:class:`SampledResponse` object.
        '''

        def inv_or_none(x):
            if x is not None:
                return 1./x

        return SampledResponse(
            self.frequencies, 1./self.values,
            left=inv_or_none(self.left),
            right=inv_or_none(self.right))

    @property
    def summary(self):
        return 'sampled'


class IntegrationResponse(FrequencyResponse):
    '''
    The integration response, optionally multiplied by a constant gain.

    :param n: exponent (integer)
    :param gain: gain factor (float)

    ::

                    gain
        T(f) = --------------
               (j*2*pi * f)^n
    '''

    n = Int.T(optional=True, default=1)
    gain = Float.T(optional=True, default=1.0)

    def __init__(self, n=1, gain=1.0, **kwargs):
        FrequencyResponse.__init__(self, n=n, gain=gain, **kwargs)

    def evaluate(self, freqs):
        nonzero = freqs != 0.0
        resp = num.zeros(freqs.size, dtype=complex)
        resp[nonzero] = self.gain / (1.0j * 2. * num.pi*freqs[nonzero])**self.n
        return resp

    @property
    def summary(self):
        return 'integration{%i}' % self.n + (
            '*gain{%g}' % self.gain
            if self.gain is not None and self.gain != 1.0
            else '')


class DifferentiationResponse(FrequencyResponse):
    '''
    The differentiation response, optionally multiplied by a constant gain.

    :param n: exponent (integer)
    :param gain: gain factor (float)

    ::

        T(f) = gain * (j*2*pi * f)^n
    '''

    n = Int.T(optional=True, default=1)
    gain = Float.T(optional=True, default=1.0)

    def __init__(self, n=1, gain=1.0, **kwargs):
        FrequencyResponse.__init__(self, n=n, gain=gain, **kwargs)

    def evaluate(self, freqs):
        return self.gain * (1.0j * 2. * num.pi * freqs)**self.n

    @property
    def summary(self):
        return 'differentiation{%i}' % self.n + (
            '*gain{%g}' % self.gain
            if self.gain is not None and self.gain != 1.0
            else '')


class DigitalFilterResponse(FrequencyResponse):
    '''
    Frequency response of an analog filter.

    (see :py:func:`scipy.signal.freqz`).
    '''

    b = List.T(Float.T())
    a = List.T(Float.T())
    deltat = Float.T()
    drop_phase = Bool.T(default=False)

    def __init__(self, b, a, deltat, drop_phase=False, **kwargs):
        FrequencyResponse.__init__(
            self, b=aslist(b), a=aslist(a), deltat=float(deltat),
            drop_phase=drop_phase, **kwargs)

    def check_sampling_rate(self):
        if self.deltat == 0.0:
            raise InvalidResponseError(
                'Invalid digital response: sampling rate undefined.')

    def is_scalar(self):
        return len(self.a) == 1 and len(self.b) == 1

    def get_scalar(self):
        if self.is_scalar():
            return self.b[0] / self.a[0]
        else:
            raise IsNotScalar()

    def get_fmax(self):
        if not self.is_scalar():
            self.check_sampling_rate()
            return 0.5 / self.deltat
        else:
            return None

    def evaluate(self, freqs):
        if self.is_scalar():
            return util.num_full_like(freqs, self.get_scalar(), dtype=complex)

        self.check_sampling_rate()

        ok = freqs <= 0.5/self.deltat
        coeffs = num.zeros(freqs.size, dtype=complex)

        coeffs[ok] = signal.freqz(
            self.b, self.a, freqs[ok]*2.*math.pi * self.deltat)[1]

        coeffs[num.logical_not(ok)] = None
        if self.drop_phase:
            return num.abs(coeffs)
        else:
            return coeffs

    def filter(self, tr):
        self.check_sampling_rate()

        from pyrocko import trace
        trace.assert_same_sampling_rate(self, tr)
        tr_new = tr.copy(data=False)
        tr_new.set_ydata(signal.lfilter(self.b, self.a, tr.get_ydata()))
        return tr_new

    @property
    def summary(self):
        if self.is_scalar():
            return str_gain(self.get_scalar())

        elif len(self.a) == 1:
            return 'fir{%i,<=%sHz}' % (
                len(self.b), str_fmax_failsafe(self))

        else:
            return 'iir{%i,%i,<=%sHz}' % (
                len(self.b), len(self.a), str_fmax_failsafe(self))


class AnalogFilterResponse(FrequencyResponse):
    '''
    Frequency response of an analog filter.

    (see :py:func:`scipy.signal.freqs`).
    '''

    b = List.T(Float.T())
    a = List.T(Float.T())

    def __init__(self, b, a, **kwargs):
        FrequencyResponse.__init__(
            self, b=aslist(b), a=aslist(a), **kwargs)

    def is_scalar(self):
        return len(self.a) == 1 and len(self.b) == 1

    def get_scalar(self):
        if self.is_scalar():
            return self.b[0] / self.a[0]
        else:
            raise IsNotScalar()

    def evaluate(self, freqs):
        return signal.freqs(self.b, self.a, freqs*2.*math.pi)[1]

    def to_digital(self, deltat, method='bilinear'):
        from scipy.signal import cont2discrete
        b, a, _ = cont2discrete((self.b, self.a), deltat, method=method)
        if b.ndim == 2:
            b = b[0]
        return DigitalFilterResponse(b.tolist(), a.tolist(), deltat)

    @property
    def summary(self):
        if self.is_scalar():
            return str_gain(self.get_scalar())

        return 'analog{%i,%i,%g}' % (
            len(self.b), len(self.a), self.get_fmax())


class MultiplyResponse(FrequencyResponse):
    '''
    Multiplication of several :py:class:`FrequencyResponse` objects.
    '''

    responses = List.T(FrequencyResponse.T())

    def __init__(self, responses=None, **kwargs):
        if responses is None:
            responses = []
        FrequencyResponse.__init__(self, responses=responses, **kwargs)

    def get_fmax(self):
        fmaxs = [resp.get_fmax() for resp in self.responses]
        fmaxs = [fmax for fmax in fmaxs if fmax is not None]
        if not fmaxs:
            return None
        else:
            return min(fmaxs)

    def evaluate(self, freqs):
        a = num.ones(freqs.size, dtype=complex)
        for resp in self.responses:
            a *= resp.evaluate(freqs)

        return a

    def is_scalar(self):
        return all(resp.is_scalar() for resp in self.responses)

    def get_scalar(self):
        '''
        Get factor if this is a flat response.
        '''
        if self.is_scalar():
            return num.prod(resp.get_scalar() for resp in self.responses)
        else:
            raise IsNotScalar()

    def simplify(self):
        self.responses = simplify_responses(self.responses)

    def construction(self):
        breakpoints = []
        for resp in self.responses:
            breakpoints.extend(resp.construction())

        return finalize_construction(breakpoints)

    @property
    def summary(self):
        if self.is_scalar(self):
            return str_gain(self.get_scalar())
        else:
            xs = [x.summary for x in self.responses]
            return '(%s)' % ('*'.join(x for x in xs if x != 'one') or 'one')


class DelayResponse(FrequencyResponse):
    '''
    Frequency response of a time delay.
    '''

    delay = Float.T(
        help='Time delay [s]')

    def evaluate(self, freqs):
        return num.exp(-2.0J * self.delay * num.pi * freqs)

    @property
    def summary(self):
        return 'delay{%g}' % self.delay


class InvalidResponseError(Exception):
    pass


class InvalidResponse(FrequencyResponse):

    '''
    Frequency response returning NaN for all frequencies.

    When using :py:meth:`FrequencyResponse.evaluate` for the first time after
    instantiation, the user supplied warning :py:gattr:`message` is emitted.
    '''

    message = String.T(
        help='Warning message to be emitted when the response is used.')

    def __init__(self, message):
        FrequencyResponse.__init__(self, message=message)
        self.have_warned = False

    def evaluate(self, freqs):
        if not self.have_warned:
            logger.warning('Invalid response: %s' % self.message)
            self.have_warned = True

        return util.num_full_like(freqs, None, dtype=num.complex)

    @property
    def summary(self):
        return 'invalid'


def simplify_responses(responses):

    def unpack_multi(responses):
        for resp in responses:
            if isinstance(resp, MultiplyResponse):
                for sub in unpack_multi(resp.responses):
                    yield sub
            else:
                yield resp

    def cancel_pzs(poles, zeros):
        poles_new = []
        zeros_new = list(zeros)
        for p in poles:
            try:
                zeros_new.pop(zeros_new.index(p))
            except ValueError:
                poles_new.append(p)

        return poles_new, zeros_new

    def combine_pzs(responses):
        poles = []
        zeros = []
        constant = 1.0
        out = []
        for resp in responses:
            if isinstance(resp, PoleZeroResponse):
                poles.extend(resp.poles)
                zeros.extend(resp.zeros)
                constant *= resp.constant
            else:
                out.append(resp)

        poles, zeros = cancel_pzs(poles, zeros)
        if poles or zeros:
            out.insert(0, PoleZeroResponse(
                poles=poles, zeros=zeros, constant=constant))
        elif constant != 1.0:
            out.insert(0, Gain(constant=constant))

        return out

    def split(xs, condition):
        out = [], []
        for x in xs:
            out[condition(x)].append(x)

        return out

    def combine_gains(responses):
        non_scalars, scalars = split(responses, lambda resp: resp.is_scalar())
        if scalars:
            factor = num.prod([resp.get_scalar() for resp in scalars])
            yield Gain(constant=factor)

        for resp in non_scalars:
            yield resp

    return list(combine_gains(combine_pzs(unpack_multi(responses))))
