# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Analytical solutions for elastic wave propagation in a homogeneous full-space.
'''

import math
import logging
import numpy as num
from . import trace
from .guts import Float, Object
from . import ahfullgreen_ext as ext

logger = logging.getLogger('pyrocko.fomosto.ahfullgreen')


guts_prefix = 'pf'


class AhfullgreenError(Exception):
    pass


def make_seismogram(
        vp, vs, density, qp, qs, x, f, m6,
        quantity, deltat, stf=None, wanted_components='ned',
        want_far=True, want_intermediate=True, want_near=True,
        npad_levelling=40, out_alignment=0.):

    if stf is None:
        stf = AhfullgreenSTFImpulse()

    x = num.asarray(x, float)
    f = num.asarray(f, float)
    m6 = num.asarray(m6, float)

    r = math.sqrt(num.sum(x**2))

    tp = r / vp
    ts = r / vs

    if ts < tp:
        raise AhfullgreenError('unsupported material properties: ts < tp')

    tpad = stf.t_cutoff() or deltat * 10.

    tstart = tp - tpad - npad_levelling * deltat
    tstart = out_alignment + round((tstart - out_alignment) / deltat) * deltat

    nt = trace.nextpow2(int(math.ceil(
        (ts - tp + 2 * tpad + 2*npad_levelling * deltat) / deltat)))

    nspec = nt // 2 + 1

    specs = []
    for component in 'ned':
        if component in wanted_components:
            specs.append(num.zeros(nspec, dtype=complex))
        else:
            specs.append(None)

    oc_c = {
        'displacement': 1,  # treated in post processing
        'velocity': 1,
        'acceleration': 2}[quantity]

    out_spec_delta = float(2.0 * math.pi / (nt*deltat))
    out_spec_offset = 0.0

    omega = out_spec_offset + out_spec_delta * num.arange(nspec)
    coeffs_stf = stf(omega/(2.*math.pi)).astype(complex)
    coeffs_stf *= num.exp(1.0j * omega * tstart)

    omega_max = 2.0 * math.pi * 0.5 / deltat
    omega_cut = omega_max * 0.75
    icut = int(num.ceil((omega_cut - out_spec_offset) / out_spec_delta))

    coeffs_stf[icut:] *= 0.5 + 0.5 * num.cos(
        math.pi * num.minimum(
            1.0, (omega[icut:] - omega_cut) / (omega_max - omega_cut)))

    if num.all(x == 0.0):
        logger.warn(
            'Source and receiver are at the same position -> setting GF for '
            'this combination to zero.')
    else:
        ext.add_seismogram(
            float(vp), float(vs), float(density), float(qp), float(qs),
            x, f, m6, oc_c, out_spec_delta, out_spec_offset,
            specs[0], specs[1], specs[2],
            want_far, want_intermediate, want_near)

    outs = []
    for i, component in enumerate('ned'):
        if component not in wanted_components:
            outs.append(None)

        out = num.fft.irfft(coeffs_stf * specs[i], nt)
        out /= deltat
        assert out.size // 2 + 1 == specs[i].size

        m1 = num.mean(
            out[:npad_levelling] * num.linspace(1., 0., npad_levelling))

        out -= m1 * 2.

        if quantity == 'displacement':
            out = num.cumsum(out) * deltat

        outs.append(out)

    outs_wanted = []
    for component in wanted_components:
        i = 'ned'.find(component)
        if i != -1:
            outs_wanted.append(outs[i])
        else:
            outs_wanted.append(None)

    return tstart, outs_wanted


def add_seismogram(
        vp, vs, density, qp, qs, x, f, m6,
        quantity, deltat, out_offset,
        out_n, out_e, out_d, stf=None,
        want_far=True, want_intermediate=True, want_near=True,
        npad_levelling=40):

    ns = [out.size for out in (out_n, out_e, out_d) if out is not None]

    if not all(n == ns[0] for n in ns):
        raise AhfullgreenError('Length of component arrays are not identical.')

    n = ns[0]

    wanted_components = ''.join(
        (c if out is not None else '-')
        for (out, c) in zip((out_n, out_e, out_d), 'ned'))

    tstart, temps = make_seismogram(
        vp, vs, density, qp, qs, x, f, m6,
        quantity, deltat, stf=stf,
        wanted_components=wanted_components,
        want_far=want_far,
        want_intermediate=want_intermediate,
        want_near=want_near,
        npad_levelling=npad_levelling, out_alignment=out_offset)

    for i, out in enumerate((out_n, out_e, out_d)):
        if out is None:
            continue

        temp = temps[i]

        ntemp = temp.size

        tmin = max(out_offset, tstart)
        tmax = min(
            out_offset + (n-1) * deltat,
            tstart + (ntemp-1) * deltat)

        def ind(t, t0):
            return int(round((t-t0)/deltat))

        out[ind(tmin, out_offset):ind(tmax, out_offset)+1] \
            += temp[ind(tmin, tstart):ind(tmax, tstart)+1]

        out[:ind(tmin, out_offset)] += 0.
        out[ind(tmax, out_offset)+1:] += temp[ind(tmax, tstart)]


class AhfullgreenSTF(Object):
    pass


class AhfullgreenSTFImpulse(AhfullgreenSTF):

    def t_cutoff(self):
        return None

    def __call__(self, f):
        return num.ones(f.size, dtype=complex)


class AhfullgreenSTFGauss(AhfullgreenSTF):

    tau = Float.T(default=1.0)

    def t_cutoff(self):
        return self.tau * 2.

    def __call__(self, f):
        omega = f * 2. * math.pi

        return num.exp(-(omega**2 * self.tau**2 / 8.))
