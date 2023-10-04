# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Classical seismic ray theory for layered earth models (*layer cake* models).

This module can be used to e.g. calculate arrival times, ray paths, reflection
and transmission coefficients, take-off and incidence angles and geometrical
spreading factors for arbitrary seismic phases. Computations are done for a
spherical earth, even though the module name may suggests something flat.

The main classes defined in this module are:

* :py:class:`Material` - Defines an isotropic elastic material.
* :py:class:`PhaseDef` - Defines a seismic phase arrival / wave propagation
    history.
* :py:class:`Leg` - Continuous propagation in a :py:class:`PhaseDef`.
* :py:class:`Knee` - Conversion/reflection in a :py:class:`PhaseDef`.
* :py:class:`LayeredModel` - Representation of a layer cake model.
* :py:class:`Layer` - A layer in a :py:class:`LayeredModel`.

   * :py:class:`HomogeneousLayer` - A homogeneous :py:class:`Layer`.
   * :py:class:`GradientLayer` - A gradient :py:class:`Layer`.

* :py:class:`Discontinuity` - A discontinuity in a :py:class:`LayeredModel`.

   * :py:class:`Interface` - A :py:class:`Discontinuity` between two
     :py:class:`Layer` instances.
   * :py:class:`Surface` - The surface :py:class:`Discontinuity` on top of
     a :py:class:`LayeredModel`.

* :py:class:`RayPath` - A fan of rays running through a common sequence of
  layers / interfaces.
* :py:class:`Ray` - A specific ray with a specific (ray parameter, distance,
  arrival time) choice.
* :py:class:`RayElement` - An element of a :py:class:`RayPath`.

   * :py:class:`Straight` - A ray segment representing propagation through
     one :py:class:`Layer`.
   * :py:class:`Kink` - An interaction of a ray with a
     :py:class:`Discontinuity`.
'''

from functools import reduce

import os
import logging
import copy
import math
import cmath
import operator
try:
    from StringIO import StringIO
except ImportError:
    from io import StringIO

import glob
import numpy as num
from scipy.optimize import bisect, brentq

from . import util, config


logger = logging.getLogger('cake')

ZEPS = 0.01

P = 1
'''
Constant indicating P wave propagation.
'''

S = 2
'''
Constant indicating S wave propagation
'''

DOWN = 4
'''
Constant indicating downward direction.
'''

UP = -4
'''
Constant indicating upward direction.
'''

DEFAULT_BURGERS = (0., 0., 1.)

earthradius = config.config().earthradius

r2d = 180./math.pi
d2r = 1./r2d
km = 1000.
d2m = d2r*earthradius
m2d = 1./d2m
sprad2spm = 1.0/(r2d*d2m)
sprad2spkm = 1.0/(r2d*d2m/km)
spm2sprad = 1.0/sprad2spm
spkm2sprad = 1.0/sprad2spkm


class CakeError(Exception):
    '''
    Base class for exceptions raised in :py:mod:`pyrocko.cake`.
    '''
    pass


class InvalidArguments(CakeError):
    '''
    Invalid arguments.
    '''
    pass


class Material(object):
    '''
    Isotropic elastic material.

    :param vp: P-wave velocity [m/s]
    :param vs: S-wave velocity [m/s]
    :param rho: density [kg/m^3]
    :param qp: P-wave attenuation Qp
    :param qs: S-wave attenuation Qs
    :param poisson: Poisson ratio
    :param lame: tuple with Lame parameter `lambda` and `shear modulus` [Pa]
    :param qk: bulk attenuation Qk
    :param qmu: shear attenuation Qmu

    :param burgers: Burgers rheology paramerters as `tuple`.
        `transient viscosity` [Pa], <= 0 means infinite value,
        `steady-state viscosity` [Pa] and `alpha`, the ratio between the
        effective and unreleaxed shear modulus, mu1/(mu1 + mu2).
    :type burgers: tuple

    If no velocities and no lame parameters are given, standard crustal values
    of vp = 5800 m/s and vs = 3200 m/s are used.  If no Q values are given,
    standard crustal values of qp = 1456 and qs = 600 are used. If no Burgers
    material parameters are given, transient and steady-state viscosities are
    0 and alpha=1.

    Everything is in SI units (m/s, Pa, kg/m^3) unless explicitly stated.

    The main material properties are considered independant and are accessible
    as attributes (it is allowed to assign to these):

        .. py:attribute:: vp, vs, rho, qp, qs

    Other material properties are considered dependant and can be queried by
    instance methods.
    '''

    def __init__(
            self, vp=None, vs=None, rho=2600., qp=None, qs=None, poisson=None,
            lame=None, qk=None, qmu=None, burgers=None):

        parstore_float(locals(), self, 'vp', 'vs', 'rho', 'qp', 'qs')

        if vp is not None and vs is not None:
            if poisson is not None or lame is not None:
                raise InvalidArguments(
                    'If vp and vs are given, poisson ratio and lame paramters '
                    'should not be given.')

        elif vp is None and vs is None and lame is None:
            self.vp = 5800.
            if poisson is None:
                poisson = 0.25
            self.vs = self.vp / math.sqrt(2.0*(1.0-poisson)/(1.0-2.0*poisson))

        elif vp is None and vs is None and lame is not None:
            if poisson is not None:
                raise InvalidArguments(
                    'Poisson ratio should not be given, when lame parameters '
                    'are given.')

            lam, mu = float(lame[0]), float(lame[1])
            self.vp = math.sqrt((lam + 2.0*mu)/rho)
            self.vs = math.sqrt(mu/rho)

        elif vp is not None and vs is None:
            if poisson is None:
                poisson = 0.25

            if lame is not None:
                raise InvalidArguments(
                    'If vp is given, Lame parameters should not be given.')

            poisson = float(poisson)
            self.vs = vp / math.sqrt(2.0*(1.0-poisson)/(1.0-2.0*poisson))

        elif vp is None and vs is not None:
            if poisson is None:
                poisson = 0.25
            if lame is not None:
                raise InvalidArguments(
                    'If vs is given, Lame parameters should not be given.')

            poisson = float(poisson)
            self.vp = vs * math.sqrt(2.0*(1.0-poisson)/(1.0-2.0*poisson))

        else:
            raise InvalidArguments(
                'Invalid combination of input parameters in material '
                'definition.')

        if qp is not None or qs is not None:
            if not (qk is None and qmu is None):
                raise InvalidArguments(
                    'If qp or qs are given, qk and qmu should not be given.')

            if qp is None:
                if self.vs != 0.0:
                    s = (4.0/3.0)*(self.vs/self.vp)**2
                    self.qp = self.qs / s
                else:
                    self.qp = 1456.

            if qs is None:
                if self.vs != 0.0:
                    s = (4.0/3.0)*(self.vs/self.vp)**2
                    self.qs = self.qp * s
                else:
                    self.vs = 600.

        elif qp is None and qs is None and qk is None and qmu is None:
            if self.vs == 0.:
                self.qs = 0.
                self.qp = 5782e4
            else:
                self.qs = 600.
                s = (4.0/3.0)*(self.vs/self.vp)**2
                self.qp = self.qs/s

        elif qp is None and qs is None and qk is not None and qmu is not None:
            s = (4.0/3.0)*(self.vs/self.vp)**2
            if qmu == 0. and self.vs == 0.:
                self.qp = qk
            else:
                if num.isinf(qk):
                    self.qp = qmu/s
                else:
                    self.qp = 1.0 / (s/qmu + (1.0-s)/qk)
            self.qs = qmu
        else:
            raise InvalidArguments(
                'Invalid combination of input parameters in material '
                'definition.')

        if burgers is None:
            burgers = DEFAULT_BURGERS

        self.burger_eta1 = burgers[0]
        self.burger_eta2 = burgers[1]
        self.burger_valpha = burgers[2]

    def astuple(self):
        '''
        Get independant material properties as a tuple.

        Returns a tuple with ``(vp, vs, rho, qp, qs)``.
        '''
        return self.vp, self.vs, self.rho, self.qp, self.qs

    def __eq__(self, other):
        return self.astuple() == other.astuple()

    def lame(self):
        '''
        Get Lame's parameter lambda and shear modulus.
        '''
        mu = self.vs**2 * self.rho
        lam = self.vp**2 * self.rho - 2.0*mu
        return lam, mu

    def lame_lambda(self):
        '''
        Get Lame's parameter lambda.

        Returned units are [Pa].
        '''
        lam, _ = self.lame()
        return lam

    def shear_modulus(self):
        '''
        Get shear modulus.

        Returned units are [Pa].
        '''
        return self.vs**2 * self.rho

    def poisson(self):
        '''
        Get Poisson's ratio.
        '''
        lam, mu = self.lame()
        return lam / (2.0*(lam+mu))

    def bulk(self):
        '''
        Get bulk modulus.
        '''
        lam, mu = self.lame()
        return lam + 2.0*mu/3.0

    def youngs(self):
        '''
        Get Young's modulus.
        '''
        lam, mu = self.lame()
        return mu * (3.0*lam + 2.0*mu) / (lam+mu)

    def vp_vs_ratio(self):
        '''
        Get vp/vs ratio.
        '''
        return self.vp/self.vs

    def qmu(self):
        '''
        Get shear attenuation coefficient Qmu.
        '''
        return self.qs

    def qk(self):
        '''
        Get bulk attenuation coefficient Qk.
        '''
        if self.vs == 0. and self.qs == 0.:
            return self.qp
        else:
            s = (4.0/3.0)*(self.vs/self.vp)**2
            denom = (1/self.qp - s/self.qs)
            if denom <= 0.0:
                return num.inf
            else:
                return (1.-s)/(1.0/self.qp - s/self.qs)

    def burgers(self):
        '''
        Get Burger parameters.
        '''
        return self.burger_eta1, self.burger_eta2, self.burger_valpha

    def _rayleigh_equation(self, cr):
        cr_a = (cr/self.vp)**2
        cr_b = (cr/self.vs)**2
        if cr_a > 1.0 or cr_b > 1.0:
            return None

        return (2.0-cr_b)**2 - 4.0 * math.sqrt(1.0-cr_a) * math.sqrt(1.0-cr_b)

    def rayleigh(self):
        '''
        Get Rayleigh velocity assuming a homogenous halfspace.

        Returned units are [m/s].
        '''
        return bisect(self._rayleigh_equation, 0.001*self.vs, self.vs)

    def _has_default_burgers(self):
        if self.burger_eta1 == DEFAULT_BURGERS[0] and \
                self.burger_eta2 == DEFAULT_BURGERS[1] and \
                self.burger_valpha == DEFAULT_BURGERS[2]:
            return True
        return False

    def describe(self):
        '''
        Get a readable listing of the material properties.
        '''
        template = '''
P wave velocity     [km/s]    : %12g
S wave velocity     [km/s]    : %12g
P/S wave vel. ratio           : %12g
Lame lambda         [GPa]     : %12g
Lame shear modulus  [GPa]     : %12g
Poisson ratio                 : %12g
Bulk modulus        [GPa]     : %12g
Young's modulus     [GPa]     : %12g
Rayleigh wave vel.  [km/s]    : %12g
Density             [g/cm**3] : %12g
Qp P-wave attenuation         : %12g
Qs S-wave attenuation (Qmu)   : %12g
Qk bulk attenuation           : %12g
transient viscos., eta1 [GPa] : %12g
st.-state viscos., eta2 [GPa] : %12g
relaxation: valpha            : %12g
'''.strip()

        return template % (
            self.vp/km,
            self.vs/km,
            self.vp/self.vs,
            self.lame_lambda()*1e-9,
            self.shear_modulus()*1e-9,
            self.poisson(),
            self.bulk()*1e-9,
            self.youngs()*1e-9,
            self.rayleigh()/km,
            self.rho/km,
            self.qp,
            self.qs,
            self.qk(),
            self.burger_eta1*1e-9,
            self.burger_eta2*1e-9,
            self.burger_valpha)

    def __str__(self):
        vp, vs, rho, qp, qs = self.astuple()
        return '%10g km/s  %10g km/s %10g g/cm^3 %10g %10g' % (
            vp/km, vs/km, rho/km, qp, qs)

    def __repr__(self):
        return 'Material(vp=%s, vs=%s, rho=%s, qp=%s, qs=%s)' % \
            tuple(repr(x) for x in (
                self.vp, self.vs, self.rho, self.qp, self.qs))


class Leg(object):
    '''
    Represents a continuous piece of wave propagation in a phase definition.

     **Attributes:**

     To be considered as read-only.

        .. py:attribute:: departure

           One of the constants :py:const:`UP` or :py:const:`DOWN` indicating
           upward or downward departure.

        .. py:attribute:: mode

           One of the constants :py:const:`P` or :py:const:`S`, indicating the
           propagation mode.

        .. py:attribute:: depthmin

           ``None``, a number (a depth in [m]) or a string (an interface name),
           minimum depth.

        .. py:attribute:: depthmax

           ``None``, a number (a depth in [m]) or a string (an interface name),
           maximum depth.

    '''

    def __init__(self, departure=None, mode=None):
        self.departure = departure
        self.mode = mode
        self.depthmin = None
        self.depthmax = None

    def set_depthmin(self, depthmin):
        self.depthmin = depthmin

    def set_depthmax(self, depthmax):
        self.depthmax = depthmax

    def __str__(self):
        def sd(d):
            if isinstance(d, float):
                return '%g km' % (d/km)
            else:
                return 'interface %s' % d

        s = '%s mode propagation, departing %s' % (
            smode(self.mode).upper(), {
                UP: 'upward', DOWN: 'downward'}[self.departure])

        sc = []
        if self.depthmax is not None:
            sc.append('deeper than %s' % sd(self.depthmax))
        if self.depthmin is not None:
            sc.append('shallower than %s' % sd(self.depthmin))

        if sc:
            s = s + ' (may not propagate %s)' % ' or '.join(sc)

        return s


class InvalidKneeDef(CakeError):
    '''
    Invalid definition of a cake :py:class:`Knee`.
    '''
    pass


class Knee(object):
    '''
    Represents a change in wave propagation within a :py:class:`PhaseDef`.

    **Attributes:**

    To be considered as read-only.

        .. py:attribute:: depth

           Depth at which the conversion/reflection should happen. this can be
           a string or a number.

        .. py:attribute:: direction

           One of the constants :py:const:`UP` or :py:const:`DOWN` to indicate
           the incoming direction.

        .. py:attribute:: in_mode

           One of the constants :py:const:`P` or :py:const:`S` to indicate the
           type of mode of the incoming wave.

        .. py:attribute:: out_mode

           One of the constants :py:const:`P` or :py:const:`S` to indicate the
           type of mode of the outgoing wave.

        .. py:attribute:: conversion

           Boolean, whether there is a mode conversion involved.

        .. py:attribute:: reflection

           Boolean, whether there is a reflection involved.

        .. py:attribute:: headwave

           Boolean, whether there is headwave propagation involved.

    '''

    defaults = dict(
        depth='surface',
        direction=UP,
        conversion=True,
        reflection=False,
        headwave=False,
        in_setup_state=True)

    defaults_surface = dict(
        depth='surface',
        direction=UP,
        conversion=False,
        reflection=True,
        headwave=False,
        in_setup_state=True)

    def __init__(self, *args):
        if args:
            (self.depth, self.direction, self.reflection, self.in_mode,
             self.out_mode) = args

            self.conversion = self.in_mode != self.out_mode
            self.in_setup_state = False

    def default(self, k):
        depth = self.__dict__.get('depth', 'surface')
        if depth == 'surface':
            return Knee.defaults_surface[k]
        else:
            return Knee.defaults[k]

    def __setattr__(self, k, v):
        if self.in_setup_state and k in self.__dict__:
            raise InvalidKneeDef('%s has already been set' % k)
        else:
            self.__dict__[k] = v

    def __getattr__(self, k):
        if k.startswith('__'):
            raise AttributeError(k)

        if k not in self.__dict__:
            return self.default(k)

    def set_modes(self, in_leg, out_leg):

        if out_leg.departure == UP and (
                (self.direction == UP) == self.reflection):

            raise InvalidKneeDef(
                'cannot enter %s from %s and emit ray upwards' % (
                    ['conversion', 'reflection'][self.reflection],
                    {UP: 'below', DOWN: 'above'}[self.direction]))

        if out_leg.departure == DOWN and (
                (self.direction == DOWN) == self.reflection):

            raise InvalidKneeDef(
                'cannot enter %s from %s and emit ray downwards' % (
                    ['conversion', 'reflection'][self.reflection],
                    {UP: 'below', DOWN: 'above'}[self.direction]))

        self.in_mode = in_leg.mode
        self.out_mode = out_leg.mode

    def at_surface(self):
        return self.depth == 'surface'

    def matches(self, discontinuity, mode, direction):
        '''
        Check whether it is relevant to a given combination of interface,
        propagation mode, and direction.
        '''

        if isinstance(self.depth, float):
            if abs(self.depth - discontinuity.z) > ZEPS:
                return False
        else:
            if discontinuity.name != self.depth:
                return False

        return self.direction == direction and self.in_mode == mode

    def out_direction(self):
        '''
        Get outgoing direction.

        Returns one of the constants :py:const:`UP` or :py:const:`DOWN`.
        '''

        if self.reflection:
            return - self.direction
        else:
            return self.direction

    def __str__(self):
        x = []
        if self.reflection:
            if self.at_surface():
                x.append('surface')
            else:
                if not self.headwave:
                    if self.direction == UP:
                        x.append('underside')
                    else:
                        x.append('upperside')

        if self.headwave:
            x.append('headwave propagation along')
        elif self.reflection and self.conversion:
            x.append('reflection with conversion from %s to %s' % (
                smode(self.in_mode).upper(), smode(self.out_mode).upper()))
            if not self.at_surface():
                x.append('at')
        elif self.reflection:
            x.append('reflection')
            if not self.at_surface():
                x.append('at')
        elif self.conversion:
            x.append('conversion from %s to %s at' % (
                smode(self.in_mode).upper(), smode(self.out_mode).upper()))
        else:
            x.append('passing through')

        if isinstance(self.depth, float):
            x.append('interface in %g km depth' % (self.depth/1000.))
        else:
            if not self.at_surface():
                x.append('%s' % self.depth)

        if not self.reflection:
            if self.direction == UP:
                x.append('on upgoing path')
            else:
                x.append('on downgoing path')

        return ' '.join(x)


class Head(Knee):
    def __init__(self, *args):
        if args:
            z, in_direction, mode = args
            Knee.__init__(self, z, in_direction, True, mode, mode)
        else:
            Knee.__init__(self)

    def __str__(self):
        x = ['propagation as headwave']
        if isinstance(self.depth, float):
            x.append('at interface in %g km depth' % (self.depth/1000.))
        else:
            x.append('at %s' % self.depth)

        return ' '.join(x)


class UnknownClassicPhase(CakeError):
    '''
    Raised when an invalid classic phase name has been specified.'
    '''
    def __init__(self, phasename):
        self.phasename = phasename

    def __str__(self):
        return 'Unknown classic phase name: %s' % self.phasename


class PhaseDefParseError(CakeError):
    '''
    Exception raised when an error occures during parsing of a phase
    definition string.
    '''

    def __init__(self, definition, position, exception):
        self.definition = definition
        self.position = position
        self.exception = exception

    def __str__(self):
        return 'Invalid phase definition: "%s" (at character %i: %s)' % (
            self.definition, self.position+1, str(self.exception))


class PhaseDef(object):

    '''
    Definition of a seismic phase arrival, based on ray propagation path.

    :param definition: string representation of the phase in Cake's phase
        syntax

    Seismic phases are conventionally named e.g. P, Pn, PP, PcP, etc. In Cake,
    a slightly different terminology is adapted, which allows to specify
    arbitrary conversion/reflection histories for seismic ray paths. The
    conventions used here are inspired by those used in the TauP toolkit, but
    are not completely compatible with those.

    The definition of a seismic ray propagation path in Cake's phase syntax is
    a string consisting of an alternating sequence of *legs* and *knees*.

    A *leg* represents seismic wave propagation without any conversions,
    encountering only super-critical reflections. Legs are denoted by ``P``,
    ``p``,  ``S``, or ``s``. The capital letters are used when the take-off of
    the *leg* is in downward direction, while the lower case letters indicate a
    take-off in upward direction.

    A *knee* is an interaction with an interface. It can be a mode conversion,
    a reflection, or propagation as a headwave or diffracted wave.

       * conversion is simply denoted as: ``(INTERFACE)`` or ``DEPTH``
       * upperside reflection: ``v(INTERFACE)`` or ``vDEPTH``
       * underside reflection: ``^(INTERFACE)`` or ``^DEPTH``
       * normal kind headwave or diffracted wave: ``v_(INTERFACE)`` or
         ``v_DEPTH``

    The interface may be given by name or by depth: INTERFACE is the name of an
    interface defined in the model, DEPTH is the depth of an interface in
    [km] (the interface closest to that depth is chosen).  If two legs appear
    consecutively without an explicit *knee*, surface interaction is assumed.

    The phase definition may end with a backslash ``\\``, to indicate that the
    ray should arrive at the receiver from above instead of from below. It is
    possible to restrict the maximum and minimum depth of a *leg* by appending
    ``<(INTERFACE)`` or ``<DEPTH`` or ``>(INTERFACE)`` or ``>DEPTH`` after the
    leg character, respectively.

    **Examples:**

        * ``P`` - like the classical P, but includes PKP, PKIKP, Pg
        * ``P<(moho)`` - like classical Pg, but must leave source downwards
        * ``pP`` - leaves source upward, reflects at surface, then travels as P
        * ``P(moho)s`` - conversion from P to S at the Moho on upgoing path
        * ``P(moho)S`` - conversion from P to S at the Moho on downgoing path
        * ``Pv12p`` - P with reflection at 12 km deep interface (or the
          interface closest to that)
        * ``Pv_(moho)p`` - classical Pn
        * ``Pv_(cmb)p`` - classical Pdiff
        * ``P^(conrad)P`` - underside reflection of P at the Conrad
          discontinuity

    **Usage:**

        >>> from pyrocko.cake import PhaseDef
        # must escape the backslash
        >>> my_crazy_phase = PhaseDef('pPv(moho)sP\\\\')
        >>> print my_crazy_phase
        Phase definition "pPv(moho)sP\":
         - P mode propagation, departing upward
         - surface reflection
         - P mode propagation, departing downward
         - upperside reflection with conversion from P to S at moho
         - S mode propagation, departing upward
         - surface reflection with conversion from S to P
         - P mode propagation, departing downward
         - arriving at target from above

    .. note::

        (1) These conventions might be extended in a way to allow to fix wave
            propagation to SH mode, possibly by specifying SH, or a single
            character (e.g. H) instead of S. This would be benificial for the
            selection of conversion and reflection coefficients, which
            currently only deal with the P-SV case.
    '''

    allowed_characters_pattern = r'[0-9a-zA-Z_()<>^v\\.]+'
    allowed_characters_pattern_classic = r'[a-zA-Z0-9]+'

    @staticmethod
    def classic_definitions():
        defs = {}
        # PmP, PmS, PcP, PcS, SmP, ...
        for r in 'mc':
            for a, b in 'PP PS SS SP'.split():
                defs[a+r+b] = [
                    '%sv(%s)%s' % (a, {'m': 'moho', 'c': 'cmb'}[r], b.lower())]

        # Pg, P, S, Sg
        for a in 'PS':
            defs[a+'g'] = ['%s<(moho)' % x for x in (a, a.lower())]
            defs[a] = ['%s<(cmb)(moho)%s' % (x, x.lower()) for x in (
                a, a.lower())]

            defs[a.lower()] = [a.lower()]

        for a, b in 'PP PS SS SP'.split():
            defs[a+'K'+b] = ['%s(cmb)P<(icb)(cmb)%s' % (a, b.lower())]
            defs[a+'KIK'+b] = ['%s(cmb)P(icb)P(icb)p(cmb)%s' % (a, b.lower())]
            defs[a+'KJK'+b] = ['%s(cmb)P(icb)S(icb)p(cmb)%s' % (a, b.lower())]
            defs[a+'KiK'+b] = ['%s(cmb)Pv(icb)p(cmb)%s' % (a, b.lower())]

        # PP, SS, PS, SP, PPP, ...
        for a in 'PS':
            for b in 'PS':
                for c in 'PS':
                    defs[a+b+c] = [''.join(defs[x][0] for x in a+b+c)]

                defs[a+b] = [''.join(defs[x][0] for x in a+b)]

        # Pc, Pdiff, Sc, ...
        for x in 'PS':
            defs[x+'c'] = defs[x+'diff'] = [x+'v_(cmb)'+x.lower()]
            defs[x+'n'] = [x+'v_(moho)'+x.lower()]

        # depth phases
        for k in list(defs.keys()):
            if k not in 'ps':
                for x in 'ps':
                    defs[x+k] = [x + defs[k][0]]

        return defs

    @staticmethod
    def classic(phasename):
        '''
        Get phase definitions based on classic phase name.

        :param phasename: classic name of a phase
        :returns: list of PhaseDef objects

        This returns a list of PhaseDef objects, because some classic phases
        (like e.g. Pg) can only be represented by two Cake style PhaseDef
        objects (one with downgoing and one with upgoing first leg).
        '''

        defs = PhaseDef.classic_definitions()
        if phasename not in defs:
            raise UnknownClassicPhase(phasename)

        return [PhaseDef(d, classicname=phasename) for d in defs[phasename]]

    def __init__(self, definition=None, classicname=None):

        state = 0
        sdepth = ''
        sinterface = ''
        depthmax = depthmin = None
        depthlim = None
        depthlimtype = None
        sdepthlim = ''
        events = []
        direction_stop = UP
        need_leg = True
        ic = 0
        if definition is not None:
            knee = Knee()
            try:
                for ic, c in enumerate(definition):

                    if state in (0, 1):

                        if c in '0123456789.':
                            need_leg = True
                            state = 1
                            sdepth += c
                            continue

                        elif state == 1:
                            knee.depth = float(sdepth)*1000.
                            state = 0

                    if state == 2:
                        if c == ')':
                            knee.depth = sinterface
                            state = 0
                        else:
                            sinterface += c

                        continue

                    if state in (3, 4):

                        if state == 3:
                            if c in '0123456789.':
                                sdepthlim += c
                                continue
                            elif c == '(':
                                state = 4
                                continue
                            else:
                                depthlim = float(sdepthlim)*1000.
                                if depthlimtype == '<':
                                    depthmax = depthlim
                                else:
                                    depthmin = depthlim
                                state = 0

                        elif state == 4:
                            if c == ')':
                                depthlim = sdepthlim
                                if depthlimtype == '<':
                                    depthmax = depthlim
                                else:
                                    depthmin = depthlim
                                state = 0
                                continue
                            else:
                                sdepthlim += c
                                continue

                    if state == 0:

                        if c == '(':
                            need_leg = True
                            state = 2
                            continue

                        elif c in '<>':
                            state = 3
                            depthlim = None
                            sdepthlim = ''
                            depthlimtype = c
                            continue

                        elif c in 'psPS':
                            leg = Leg()
                            if c in 'ps':
                                leg.departure = UP
                            else:
                                leg.departure = DOWN
                            leg.mode = imode(c)

                            if events:
                                in_leg = events[-1]
                                if depthmin is not None:
                                    in_leg.set_depthmin(depthmin)
                                    depthmin = None
                                if depthmax is not None:
                                    in_leg.set_depthmax(depthmax)
                                    depthmax = None

                                if in_leg.mode != leg.mode:
                                    knee.conversion = True
                                else:
                                    knee.conversion = False

                                if not knee.reflection:
                                    if c in 'ps':
                                        knee.direction = UP
                                    else:
                                        knee.direction = DOWN

                                knee.set_modes(in_leg, leg)
                                knee.in_setup_state = False
                                events.append(knee)
                                knee = Knee()
                                sdepth = ''
                                sinterface = ''

                            events.append(leg)
                            need_leg = False
                            continue

                        elif c == '^':
                            need_leg = True
                            knee.direction = UP
                            knee.reflection = True
                            continue

                        elif c == 'v':
                            need_leg = True
                            knee.direction = DOWN
                            knee.reflection = True
                            continue

                        elif c == '_':
                            need_leg = True
                            knee.headwave = True
                            continue

                        elif c == '\\':
                            direction_stop = DOWN
                            continue

                        else:
                            raise PhaseDefParseError(
                                definition, ic, 'invalid character: "%s"' % c)

                if state == 3:
                    depthlim = float(sdepthlim)*1000.
                    if depthlimtype == '<':
                        depthmax = depthlim
                    else:
                        depthmin = depthlim
                    state = 0

            except (ValueError, InvalidKneeDef) as e:
                raise PhaseDefParseError(definition, ic, e)

            if state != 0 or need_leg:
                raise PhaseDefParseError(
                    definition, ic, 'unfinished expression')

            if events and depthmin is not None:
                events[-1].set_depthmin(depthmin)
            if events and depthmax is not None:
                events[-1].set_depthmax(depthmax)

        self._definition = definition
        self._classicname = classicname
        self._events = events
        self._direction_stop = direction_stop

    def __iter__(self):
        for ev in self._events:
            yield ev

    def append(self, ev):
        self._events.append(ev)

    def first_leg(self):
        '''
        Get the first leg in phase definition.
        '''
        return self._events[0]

    def last_leg(self):
        '''
        Get the last leg in phase definition.
        '''
        return self._events[-1]

    def legs(self):
        '''
        Iterate over the continuous pieces of wave propagation (legs) defined
        within this phase definition.
        '''

        return (leg for leg in self if isinstance(leg, Leg))

    def knees(self):
        '''
        Iterate over conversions and reflections (knees) defined within this
        phase definition.
        '''
        return (knee for knee in self if isinstance(knee, Knee))

    def definition(self):
        '''
        Get original definition of the phase.
        '''
        return self._definition

    def given_name(self):
        '''
        Get entered classic name if any, or original definition of the phase.
        '''

        if self._classicname:
            return self._classicname
        else:
            return self._definition

    def direction_start(self):
        return self.first_leg().departure

    def direction_stop(self):
        return self._direction_stop

    def headwave_knee(self):
        for el in self:
            if type(el) == Knee and el.headwave:
                return el
        return None

    def used_repr(self):
        '''
        Translate into textual representation (cake phase syntax).
        '''
        def strdepth(x):
            if isinstance(x, float):
                return '%g' % (x/1000.)
            else:
                return '(%s)' % x

        x = []
        for el in self:
            if type(el) == Leg:
                if el.departure == UP:
                    x.append(smode(el.mode).lower())
                else:
                    x.append(smode(el.mode).upper())

                if el.depthmax is not None:
                    x.append('<'+strdepth(el.depthmax))

                if el.depthmin is not None:
                    x.append('>'+strdepth(el.depthmin))

            elif type(el) == Knee:
                if el.reflection and not el.at_surface():
                    if el.direction == DOWN:
                        x.append('v')
                    else:
                        x.append('^')
                if el.headwave:
                    x.append('_')
                if not el.at_surface():
                    x.append(strdepth(el.depth))

            elif type(el) == Head:
                x.append('_')
                x.append(strdepth(el.depth))

        if self._direction_stop == DOWN:
            x.append('\\')

        return ''.join(x)

    def __repr__(self):
        if self._definition is not None:
            return "PhaseDef('%s')" % self._definition
        else:
            return "PhaseDef('%s')" % self.used_repr()

    def __str__(self):
        orig = ''
        used = self.used_repr()
        if self._definition != used:
            orig = ' (entered as "%s")' % self._definition

        sarrive = '\n - arriving at target from %s' % ('below', 'above')[
            self._direction_stop == DOWN]

        return 'Phase definition "%s"%s:\n - ' % (used, orig) + \
            '\n - '.join(str(ev) for ev in self) + sarrive

    def copy(self):
        '''
        Get a deep copy of it.
        '''
        return copy.deepcopy(self)


def to_phase_defs(phases):
    if isinstance(phases, (str, PhaseDef)):
        phases = [phases]

    phases_out = []
    for phase in phases:
        if isinstance(phase, str):
            phases_out.extend(PhaseDef(x.strip()) for x in phase.split(','))
        elif isinstance(phase, PhaseDef):
            phases_out.append(phase)
        else:
            raise PhaseDefParseError('invalid phase definition')

    return phases_out


def csswap(x):
    return cmath.sqrt(1.-x**2)


def psv_surface_ind(in_mode, out_mode):
    '''
    Get indices to select the appropriate element from scatter matrix for free
    surface.
    '''

    return (int(in_mode == S), int(out_mode == S))


def psv_surface(material, p, energy=False):
    '''
    Scatter matrix for free surface reflection/conversions.

    :param material: material, object of type :py:class:`Material`
    :param p: flat ray parameter [s/m]
    :param energy: bool, when ``True`` energy normalized coefficients are
        returned
    :returns: Scatter matrix

    The scatter matrix is ordered as follows::

        [[PP, PS],
         [SP, SS]]

    The formulas given in Aki & Richards are used.
    '''

    vp, vs, rho = material.vp, material.vs, material.rho
    sinphi = p * vp
    sinlam = p * vs
    cosphi = csswap(sinphi)
    coslam = csswap(sinlam)

    if vs == 0.0:
        scatter = num.array([[-1.0, 0.0], [0.0, 1.0]])

    else:
        vsp_term = (1.0/vs**2 - 2.0*p**2)
        pcc_term = 4.0 * p**2 * cosphi/vp * coslam/vs
        denom = vsp_term**2 + pcc_term

        scatter = num.array([
            [- vsp_term**2 + pcc_term, 4.0*p*coslam/vp*vsp_term],
            [4.0*p*cosphi/vs*vsp_term, vsp_term**2 - pcc_term]],
            dtype=complex) / denom

    if not energy:
        return scatter
    else:
        eps = 1e-16
        normvec = num.array([vp*rho*cosphi+eps, vs*rho*coslam+eps])
        escatter = scatter*num.conj(scatter) * num.real(
            (normvec[:, num.newaxis]) / (normvec[num.newaxis, :]))
        return num.real(escatter)


def psv_solid_ind(in_direction, out_direction, in_mode, out_mode):
    '''
    Get indices to select the appropriate element from scatter matrix for
    solid-solid interface.
    '''

    return (
        (out_direction == DOWN)*2 + (out_mode == S),
        (in_direction == UP)*2 + (in_mode == S))


def psv_solid(material1, material2, p, energy=False):
    '''
    Scatter matrix for solid-solid interface.

    :param material1: material above, object of type :py:class:`Material`
    :param material2: material below, object of type :py:class:`Material`
    :param p: flat ray parameter [s/m]
    :param energy: bool, when ``True`` energy normalized coefficients are
        returned
    :returns: Scatter matrix

    The scatter matrix is ordered as follows::

       [[P1P1, S1P1, P2P1, S2P1],
        [P1S1, S1S1, P2S1, S2S1],
        [P1P2, S1P2, P2P2, S2P2],
        [P1S2, S1S2, P2S2, S2S2]]

    The formulas given in Aki & Richards are used.
    '''

    vp1, vs1, rho1 = material1.vp, material1.vs, material1.rho
    vp2, vs2, rho2 = material2.vp, material2.vs, material2.rho

    sinphi1 = p * vp1
    cosphi1 = csswap(sinphi1)
    sinlam1 = p * vs1
    coslam1 = csswap(sinlam1)
    sinphi2 = p * vp2
    cosphi2 = csswap(sinphi2)
    sinlam2 = p * vs2
    coslam2 = csswap(sinlam2)

    # from aki and richards
    M = num.array([
        [-vp1*p, -coslam1, vp2*p, coslam2],
        [cosphi1, -vs1*p, cosphi2, -vs2*p],
        [2.0*rho1*vs1**2*p*cosphi1, rho1*vs1*(1.0-2.0*vs1**2*p**2),
         2.0*rho2*vs2**2*p*cosphi2, rho2*vs2*(1.0-2.0*vs2**2*p**2)],
        [-rho1*vp1*(1.0-2.0*vs1**2*p**2), 2.0*rho1*vs1**2*p*coslam1,
         rho2*vp2*(1.0-2.0*vs2**2*p**2), -2.0*rho2*vs2**2*p*coslam2]],
        dtype=complex)
    N = M.copy()
    N[0] *= -1.0
    N[3] *= -1.0

    scatter = num.dot(num.linalg.inv(M), N)

    if not energy:
        return scatter
    else:
        eps = 1e-16
        if vs1 == 0.:
            vs1 = vp1*1e-16
        if vs2 == 0.:
            vs2 = vp2*1e-16
        normvec = num.array([
            vp1*rho1*(cosphi1+eps), vs1*rho1*(coslam1+eps),
            vp2*rho2*(cosphi2+eps), vs2*rho2*(coslam2+eps)], dtype=complex)
        escatter = scatter*num.conj(scatter) * num.real(
            normvec[:, num.newaxis] / normvec[num.newaxis, :])

        return num.real(escatter)


class BadPotIntCoefs(CakeError):
    '''
    Raised when the potential interpolation for gradient layers has failed.
    '''
    pass


def potint_coefs(c1, c2, r1, r2):  # r2 > r1
    eps = r2*1e-9
    if c1 == 0. and c2 == 0.:
        c1c2 = 1.
    else:
        c1c2 = c1/c2
    b = math.log(c1c2)/math.log((r1+eps)/r2)
    if abs(b) > 10.:
        raise BadPotIntCoefs()
    a = c1/(r1+eps)**b
    return a, b


def imode(s):
    if s.lower() == 'p':
        return P
    elif s.lower() == 's':
        return S


def smode(i):
    if i == P:
        return 'p'
    elif i == S:
        return 's'


class PathFailed(CakeError):
    '''
    Raised when the ray path computation failed.
    '''
    pass


class SurfaceReached(PathFailed):
    '''
    Raised when the ray hits the surface before completing the phase
    requirements.
    '''
    pass


class BottomReached(PathFailed):
    '''
    Raised when the ray exits the bottom of the model before completing the
    phase requirements.
    '''
    pass


class MaxDepthReached(PathFailed):
    '''
    Raised when the phase's maximum depth has been exceeded.
    '''
    pass


class MinDepthReached(PathFailed):
    '''
    Raised when the phase's minimum depth has been underrun.
    '''
    pass


class Trapped(PathFailed):
    '''
    Raised when the ray has been trapped and therefore cannot satisfy the phase
    requirements.
    '''
    pass


class NotPhaseConform(PathFailed):
    '''
    Raised when the phase requirements cannot be met.
    '''
    pass


class CannotPropagate(PathFailed):
    '''
    Raised when the phase requirements cannot be met.
    '''
    def __init__(self, direction, ilayer):
        PathFailed.__init__(self)
        self._direction = direction
        self._ilayer = ilayer

    def __str__(self):
        return 'Cannot enter layer %i from %s' % (
            self._ilayer, {
                UP: 'below',
                DOWN: 'above'}[self._direction])


class Layer(object):
    '''
    Representation of a layer in a layered earth model.

    :param ztop: depth of top of layer
    :param zbot: depth of bottom of layer
    :param name: name of layer (optional)

    Subclasses are: :py:class:`HomogeneousLayer` and :py:class:`GradientLayer`.
    '''

    def __init__(self, ztop, zbot, name=None):
        self.ztop = ztop
        self.zbot = zbot
        self.zmid = (self.ztop + self.zbot) * 0.5
        self.name = name
        self.ilayer = None

    def _update_potint_coefs(self):
        potint_p = potint_s = False
        try:
            self._ppic = potint_coefs(
                self.mbot.vp, self.mtop.vp,
                radius(self.zbot), radius(self.ztop))
            potint_p = True
        except BadPotIntCoefs:
            pass

        potint_s = False
        try:
            self._spic = potint_coefs(
                self.mbot.vs, self.mtop.vs,
                radius(self.zbot), radius(self.ztop))
            potint_s = True
        except BadPotIntCoefs:
            pass

        assert P == 1 and S == 2
        self._use_potential_interpolation = (None, potint_p, potint_s)

    def potint_coefs(self, mode):
        '''
        Get coefficients for potential interpolation.

        :param mode: mode of wave propagation, :py:const:`P` or :py:const:`S`
        :returns: coefficients ``(a, b)``
        '''

        if mode == P:
            return self._ppic
        else:
            return self._spic

    def contains(self, z):
        '''
        Tolerantly check if a given depth is within the layer
        (including boundaries).
        '''

        return self.ztop <= z <= self.zbot or \
            self.at_bottom(z) or self.at_top(z)

    def inner(self, z):
        '''
        Tolerantly check if a given depth is within the layer
        (not including boundaries).
        '''

        return self.ztop <= z <= self.zbot and not \
            self.at_bottom(z) and not \
            self.at_top(z)

    def at_bottom(self, z):
        '''
        Tolerantly check if given depth is at the bottom of the layer.
        '''

        return abs(self.zbot - z) < ZEPS

    def at_top(self, z):
        '''
        Tolerantly check if given depth is at the top of the layer.
        '''
        return abs(self.ztop - z) < ZEPS

    def pflat_top(self, p):
        '''
        Convert spherical ray parameter to local flat ray parameter for top of
        layer.
        '''
        return p / (earthradius-self.ztop)

    def pflat_bottom(self, p):
        '''
        Convert spherical ray parameter to local flat ray parameter for bottom
        of layer.
        '''
        return p / (earthradius-self.zbot)

    def pflat(self, p, z):
        '''
        Convert spherical ray parameter to local flat ray parameter for
        given depth.
        '''
        return p / (earthradius-z)

    def v_potint(self, mode, z):
        a, b = self.potint_coefs(mode)
        return a*(earthradius-z)**b

    def u_potint(self, mode, z):
        a, b = self.potint_coefs(mode)
        return 1./(a*(earthradius-z)**b)

    def xt_potint(self, p, mode, zpart=None):
        '''
        Get travel time and distance for for traversal with given mode and ray
        parameter.

        :param p: ray parameter (spherical)
        :param mode: mode of propagation (:py:const:`P` or :py:const:`S`)
        :param zpart: if given, tuple with two depths to restrict computation
            to a part of the layer

        This implementation uses analytic formulas valid for a spherical earth
        in the case where the velocity c within the layer is given by potential
        interpolation of the form

            c(z) = a*z^b
        '''
        utop, ubot = self.u_top_bottom(mode)
        a, b = self.potint_coefs(mode)
        ztop = self.ztop
        zbot = self.zbot
        if zpart is not None:
            utop = self.u(mode, zpart[0])
            ubot = self.u(mode, zpart[1])
            ztop, zbot = zpart
            utop = 1./(a*(earthradius-ztop)**b)
            ubot = 1./(a*(earthradius-zbot)**b)

        r1 = radius(zbot)
        r2 = radius(ztop)
        burger_eta1 = r1 * ubot
        burger_eta2 = r2 * utop
        if b != 1:
            def cpe(eta):
                return num.arccos(num.minimum(p/num.maximum(eta, p/2), 1.0))

            def sep(eta):
                return num.sqrt(num.maximum(eta**2 - p**2, 0.0))

            x = (cpe(burger_eta2)-cpe(burger_eta1))/(1.0-b)
            t = (sep(burger_eta2)-sep(burger_eta1))/(1.0-b)
        else:
            lr = math.log(r2/r1)
            sap = num.sqrt(1.0/a**2 - p**2)
            x = p/sap * lr
            t = 1./(a**2 * sap)

        x *= r2d

        return x, t

    def test(self, p, mode, z):
        '''
        Check if wave mode can exist for given ray parameter at given depth
        within the layer.
        '''
        return (self.u(mode, z)*radius(z) - p) > 0.

    def tests(self, p, mode):
        utop, ubot = self.u_top_bottom(mode)
        return (
            (utop * radius(self.ztop) - p) > 0.,
            (ubot * radius(self.zbot) - p) > 0.)

    def zturn_potint(self, p, mode):
        '''
        Get turning depth for given ray parameter and propagation mode.
        '''

        a, b = self.potint_coefs(mode)
        r = num.exp(num.log(a*p)/(1.0-b))
        return earthradius-r

    def propagate(self, p, mode, direction):
        '''
        Propagate ray through layer.

        :param p: ray parameter
        :param mode: propagation mode
        :param direction: in direction (:py:const:`UP` or :py:const:`DOWN`
        '''
        if direction == DOWN:
            zin, zout = self.ztop, self.zbot
        else:
            zin, zout = self.zbot, self.ztop

        if self.v(mode, zin) == 0.0 or not self.test(p, mode, zin):
            raise CannotPropagate(direction, self.ilayer)

        if not self.test(p, mode, zout):
            return -direction
        else:
            return direction

    def resize(self, depth_min=None, depth_max=None):
        '''
        Change layer thinkness and interpolate material if required.
        '''
        if depth_min:
            mtop = self.material(depth_min)

        if depth_max:
            mbot = self.material(depth_max)

        self.mtop = mtop if depth_min else self.mtop
        self.mbot = mbot if depth_max else self.mbot
        self.ztop = depth_min if depth_min else self.ztop
        self.zbot = depth_max if depth_max else self.zbot
        self.zmid = self.ztop + (self.zbot - self.ztop)/2.


class DoesNotTurn(CakeError):
    pass


def radius(z):
    return earthradius - z


class HomogeneousLayer(Layer):
    '''
    Representation of a homogeneous layer in a layered earth model.

    Base class: :py:class:`Layer`.
    '''

    def __init__(self, ztop, zbot, m, name=None):
        Layer.__init__(self, ztop, zbot, name=name)
        self.m = m
        self.mtop = m
        self.mbot = m
        self._update_potint_coefs()

    def copy(self, ztop=None, zbot=None):
        if ztop is None:
            ztop = self.ztop

        if zbot is None:
            zbot = self.zbot

        return HomogeneousLayer(ztop, zbot, self.m, name=self.name)

    def material(self, z):
        return self.m

    def u(self, mode, z=None):
        if self._use_potential_interpolation[mode] and z is not None:
            return self.u_potint(mode, z)

        if mode == P:
            return 1./self.m.vp
        if mode == S:
            return 1./self.m.vs

    def u_top_bottom(self, mode):
        u = self.u(mode)
        return u, u

    def v(self, mode, z=None):
        if self._use_potential_interpolation[mode] and z is not None:
            return self.v_potint(mode, z)

        if mode == P:
            v = self.m.vp
        if mode == S:
            v = self.m.vs

        if num.isscalar(z):
            return v
        else:
            return filled(v, len(z))

    def v_top_bottom(self, mode):
        v = self.v(mode)
        return v, v

    def xt(self, p, mode, zpart=None):
        if self._use_potential_interpolation[mode]:
            return self.xt_potint(p, mode, zpart)

        u = self.u(mode)
        pflat = self.pflat_bottom(p)
        if zpart is None:
            dz = (self.zbot - self.ztop)
        else:
            dz = abs(zpart[1]-zpart[0])

        u = self.u(mode)
        eps = u*0.001
        denom = num.sqrt(u**2 - pflat**2) + eps

        x = r2d*pflat/(earthradius-self.zmid) * dz / denom
        t = u**2 * dz / denom
        return x, t

    def zturn(self, p, mode):
        if self._use_potential_interpolation[mode]:
            return self.zturn_potint(p, mode)

        raise DoesNotTurn()

    def split(self, z):
        upper = HomogeneousLayer(self.ztop, z, self.m, name=self.name)
        lower = HomogeneousLayer(z, self.zbot, self.m, name=self.name)
        upper.ilayer = self.ilayer
        lower.ilayer = self.ilayer
        return upper, lower

    def __str__(self):
        if self.name:
            name = self.name + ' '
        else:
            name = ''

        calcmode = ''.join('HP'[self._use_potential_interpolation[mode]]
                           for mode in (P, S))

        return '  (%i) homogeneous layer %s(%g km - %g km) [%s]\n    %s' % (
            self.ilayer, name, self.ztop/km, self.zbot/km, calcmode, self.m)


class GradientLayer(Layer):
    '''
    Representation of a gradient layer in a layered earth model.

    Base class: :py:class:`Layer`.
    '''

    def __init__(self, ztop, zbot, mtop, mbot, name=None):
        Layer.__init__(self, ztop, zbot, name=name)
        self.mtop = mtop
        self.mbot = mbot
        self._update_potint_coefs()

    def copy(self, ztop=None, zbot=None):
        if ztop is None:
            ztop = self.ztop

        if zbot is None:
            zbot = self.zbot

        return GradientLayer(ztop, zbot, self.mtop, self.mbot, name=self.name)

    def interpolate(self, z, ptop, pbot):
        return ptop + (z - self.ztop)*(pbot - ptop)/(self.zbot-self.ztop)

    def material(self, z):
        dtop = self.mtop.astuple()
        dbot = self.mbot.astuple()
        d = [
            self.interpolate(z, ptop, pbot)
            for (ptop, pbot) in zip(dtop, dbot)]

        return Material(*d)

    def u_top_bottom(self, mode):
        if mode == P:
            return 1./self.mtop.vp, 1./self.mbot.vp
        if mode == S:
            return 1./self.mtop.vs, 1./self.mbot.vs

    def u(self, mode, z):
        if self._use_potential_interpolation[mode]:
            return self.u_potint(mode, z)

        if mode == P:
            return 1./self.interpolate(z, self.mtop.vp, self.mbot.vp)
        if mode == S:
            return 1./self.interpolate(z, self.mtop.vs, self.mbot.vs)

    def v_top_bottom(self, mode):
        if mode == P:
            return self.mtop.vp, self.mbot.vp
        if mode == S:
            return self.mtop.vs, self.mbot.vs

    def v(self, mode, z):
        if self._use_potential_interpolation[mode]:
            return self.v_potint(mode, z)

        if mode == P:
            return self.interpolate(z, self.mtop.vp, self.mbot.vp)
        if mode == S:
            return self.interpolate(z, self.mtop.vs, self.mbot.vs)

    def xt(self, p, mode, zpart=None):
        if self._use_potential_interpolation[mode]:
            return self.xt_potint(p, mode, zpart)

        utop, ubot = self.u_top_bottom(mode)
        b = (1./ubot - 1./utop)/(self.zbot - self.ztop)

        pflat = self.pflat_bottom(p)
        if zpart is not None:
            utop = self.u(mode, zpart[0])
            ubot = self.u(mode, zpart[1])

        peps = 1e-16
        pdp = pflat + peps

        def func(u):
            eta = num.sqrt(num.maximum(u**2 - pflat**2, 0.0))
            xx = eta/u
            tt = num.where(
                pflat <= u,
                num.log(u+eta) - num.log(pdp) - eta/u,
                0.0)

            return xx, tt

        xxtop, tttop = func(utop)
        xxbot, ttbot = func(ubot)

        x = (xxtop - xxbot) / (b*pdp)
        t = (tttop - ttbot) / b + pflat*x

        x *= r2d/(earthradius - self.zmid)
        return x, t

    def zturn(self, p, mode):
        if self._use_potential_interpolation[mode]:
            return self.zturn_potint(p, mode)
        pflat = self.pflat_bottom(p)
        vtop, vbot = self.v_top_bottom(mode)
        return (1./pflat - vtop) * (self.zbot - self.ztop) / \
            (vbot-vtop) + self.ztop

    def split(self, z):
        mmid = self.material(z)
        upper = GradientLayer(self.ztop, z, self.mtop, mmid, name=self.name)
        lower = GradientLayer(z, self.zbot, mmid, self.mbot, name=self.name)
        upper.ilayer = self.ilayer
        lower.ilayer = self.ilayer
        return upper, lower

    def __str__(self):
        if self.name:
            name = self.name + ' '
        else:
            name = ''

        calcmode = ''.join('HP'[self._use_potential_interpolation[mode]]
                           for mode in (P, S))

        return '''  (%i) gradient layer %s(%g km - %g km) [%s]
    %s
    %s''' % (
            self.ilayer,
            name,
            self.ztop/km,
            self.zbot/km,
            calcmode,
            self.mtop,
            self.mbot)


class Discontinuity(object):
    '''
    Base class for discontinuities in layered earth model.

    Subclasses are: :py:class:`Interface` and :py:class:`Surface`.
    '''

    def __init__(self, z, name=None):
        self.z = z
        self.zbot = z
        self.ztop = z
        self.name = name

    def change_depth(self, z):
        self.z = z
        self.zbot = z
        self.ztop = z

    def copy(self):
        return copy.deepcopy(self)


class Interface(Discontinuity):
    '''
    Representation of an interface in a layered earth model.

    Base class: :py:class:`Discontinuity`.
    '''

    def __init__(self, z, mabove, mbelow, name=None):
        Discontinuity.__init__(self, z, name)
        self.mabove = mabove
        self.mbelow = mbelow

    def __str__(self):
        if self.name is None:
            return 'interface'
        else:
            return 'interface "%s"' % self.name

    def u_top_bottom(self, mode):
        if mode == P:
            return reci_or_none(self.mabove.vp), reci_or_none(self.mbelow.vp)
        if mode == S:
            return reci_or_none(self.mabove.vs), reci_or_none(self.mbelow.vs)

    def critical_ps(self, mode):
        uabove, ubelow = self.u_top_bottom(mode)
        return (
            mult_or_none(uabove, radius(self.z)),
            mult_or_none(ubelow, radius(self.z)))

    def propagate(self, p, mode, direction):
        uabove, ubelow = self.u_top_bottom(mode)
        if direction == DOWN:
            if ubelow is not None and ubelow*radius(self.z) - p >= 0:
                return direction
            else:
                return -direction
        if direction == UP:
            if uabove is not None and uabove*radius(self.z) - p >= 0:
                return direction
            else:
                return -direction

    def pflat(self, p):
        return p / (earthradius-self.z)

    def efficiency(self, in_direction, out_direction, in_mode, out_mode, p):
        scatter = psv_solid(
            self.mabove, self.mbelow, self.pflat(p), energy=True)
        return scatter[
            psv_solid_ind(in_direction, out_direction, in_mode, out_mode)]


class Surface(Discontinuity):
    '''
    Representation of the surface discontinuity in a layered earth model.

    Base class: :py:class:`Discontinuity`.
    '''

    def __init__(self, z, mbelow):
        Discontinuity.__init__(self, z, 'surface')
        self.z = z
        self.mbelow = mbelow

    def propagate(self, p, mode, direction):
        return direction  # no implicit reflection at surface

    def u_top_bottom(self, mode):
        if mode == P:
            return None, reci_or_none(self.mbelow.vp)
        if mode == S:
            return None, reci_or_none(self.mbelow.vs)

    def critical_ps(self, mode):
        _, ubelow = self.u_top_bottom(mode)
        return None, mult_or_none(ubelow, radius(self.z))

    def pflat(self, p):
        return p / (earthradius-self.z)

    def efficiency(self, in_direction, out_direction, in_mode, out_mode, p):
        if in_direction == DOWN or out_direction == UP:
            return 0.0
        else:
            return psv_surface(
                self.mbelow, self.pflat(p), energy=True)[
                    psv_surface_ind(in_mode, out_mode)]

    def __str__(self):
        return 'surface'


class Walker(object):
    def __init__(self, elements):
        self._elements = elements
        self._i = 0

    def current(self):
        return self._elements[self._i]

    def go(self, direction):
        if direction == UP:
            self.up()
        else:
            self.down()

    def down(self):
        if self._i < len(self._elements)-1:
            self._i += 1
        else:
            raise BottomReached()

    def up(self):
        if self._i > 0:
            self._i -= 1
        else:
            raise SurfaceReached()

    def goto_layer(self, layer):
        self._i = self._elements.index(layer)


class RayElement(object):
    '''
    An element of a :py:class:`RayPath`.
    '''

    def __eq__(self, other):
        return type(self) == type(other) and self.__dict__ == other.__dict__

    def is_straight(self):
        return isinstance(self, Straight)

    def is_kink(self):
        return isinstance(self, Kink)


class Straight(RayElement):
    '''
    A ray segment representing wave propagation through one :py:class:`Layer`.
    '''

    def __init__(self, direction_in, direction_out, mode, layer):
        self.mode = mode
        self._direction_in = direction_in
        self._direction_out = direction_out
        self.layer = layer

    def angle_in(self, p, endgaps=None):
        z = self.z_in(endgaps)
        dir = self.eff_direction_in(endgaps)
        v = self.layer.v(self.mode, z)
        pf = self.layer.pflat(p, z)

        if dir == DOWN:
            return num.arcsin(v*pf)*r2d
        else:
            return 180.-num.arcsin(v*pf)*r2d

    def angle_out(self, p, endgaps=None):
        z = self.z_out(endgaps)
        dir = self.eff_direction_out(endgaps)
        v = self.layer.v(self.mode, z)
        pf = self.layer.pflat(p, z)

        if dir == DOWN:
            return 180.-num.arcsin(v*pf)*r2d
        else:
            return num.arcsin(v*pf)*r2d

    def pflat_in(self, p, endgaps=None):
        return p / (earthradius-self.z_in(endgaps))

    def pflat_out(self, p, endgaps=None):
        return p / (earthradius-self.z_out(endgaps))

    def test(self, p, z):
        return self.layer.test(p, self.mode, z)

    def z_in(self, endgaps=None):
        if endgaps is not None:
            return endgaps[0]
        else:
            lyr = self.layer
            return (lyr.ztop, lyr.zbot)[self._direction_in == UP]

    def z_out(self, endgaps=None):
        if endgaps is not None:
            return endgaps[1]
        else:
            lyr = self.layer
            return (lyr.ztop, lyr.zbot)[self._direction_out == DOWN]

    def turns(self):
        return self._direction_in != self._direction_out

    def eff_direction_in(self, endgaps=None):
        if endgaps is None:
            return self._direction_in
        else:
            return endgaps[2]

    def eff_direction_out(self, endgaps=None):
        if endgaps is None:
            return self._direction_out
        else:
            return endgaps[3]

    def zturn(self, p):
        lyr = self.layer
        return lyr.zturn(p, self.mode)

    def u_in(self, endgaps=None):
        return self.layer.u(self.mode, self.z_in(endgaps))

    def u_out(self, endgaps=None):
        return self.layer.u(self.mode, self.z_out(endgaps))

    def critical_p_in(self, endgaps=None):
        z = self.z_in(endgaps)
        return self.layer.u(self.mode, z)*radius(z)

    def critical_p_out(self, endgaps=None):
        z = self.z_out(endgaps)
        return self.layer.u(self.mode, z)*radius(z)

    def xt(self, p, zpart=None):
        x, t = self.layer.xt(p, self.mode, zpart=zpart)
        if self._direction_in != self._direction_out and zpart is None:
            x *= 2.
            t *= 2.
        return x, t

    def xt_gap(self, p, zstart, zstop, samedir):
        z1, z2 = zstart, zstop
        if z1 > z2:
            z1, z2 = z2, z1

        x, t = self.layer.xt(p, self.mode, zpart=(z1, z2))

        if samedir:
            return x, t
        else:
            xfull, tfull = self.xt(p)
            return xfull-x, tfull-t

    def __hash__(self):
        return hash((
            self._direction_in,
            self._direction_out,
            self.mode,
            id(self.layer)))


class HeadwaveStraight(Straight):
    def __init__(self, direction_in, direction_out, mode, interface):
        Straight.__init__(self, direction_in, direction_out, mode, None)

        self.interface = interface

    def z_in(self, zpart=None):
        return self.interface.z

    def z_out(self, zpart=None):
        return self.interface.z

    def zturn(self, p):
        return filled(self.interface.z, len(p))

    def xt(self, p, zpart=None):
        return 0., 0.

    def x2t_headwave(self, xstretch):
        xstretch_m = xstretch*d2r*radius(self.interface.z)
        return min_not_none(*self.interface.u_top_bottom(self.mode))*xstretch_m


class Kink(RayElement):
    '''
    An interaction of a ray with a :py:class:`Discontinuity`.
    '''

    def __init__(
            self,
            in_direction,
            out_direction,
            in_mode,
            out_mode,
            discontinuity):

        self.in_direction = in_direction
        self.out_direction = out_direction
        self.in_mode = in_mode
        self.out_mode = out_mode
        self.discontinuity = discontinuity

    def reflection(self):
        return self.in_direction != self.out_direction

    def conversion(self):
        return self.in_mode != self.out_mode

    def efficiency(self, p, out_direction=None, out_mode=None):

        if out_direction is None:
            out_direction = self.out_direction

        if out_mode is None:
            out_mode = self.out_mode

        return self.discontinuity.efficiency(
            self.in_direction, out_direction, self.in_mode, out_mode, p)

    def __str__(self):
        r, c = self.reflection(), self.conversion()
        if r and c:
            return '|~'
        if r:
            return '|'
        if c:
            return '~'
        return '_'

    def __hash__(self):
        return hash((
            self.in_direction,
            self.out_direction,
            self.in_mode,
            self.out_mode,
            id(self.discontinuity)))


class PRangeNotSet(CakeError):
    pass


class RayPath(object):
    '''
    Representation of a fan of rays running through a common sequence of
    layers / interfaces.
    '''

    def __init__(self, phase):
        self.elements = []
        self.phase = phase
        self._pmax = None
        self._pmin = None
        self._p = None
        self._is_headwave = False

    def set_is_headwave(self, is_headwave):
        self._is_headwave = is_headwave

    def copy(self):
        '''
        Get a copy of it.
        '''

        c = copy.copy(self)
        c.elements = list(self.elements)
        return c

    def endgaps(self, zstart, zstop):
        '''
        Get information needed for end point adjustments.
        '''

        return (
            zstart,
            zstop,
            self.phase.direction_start(),
            self.phase.direction_stop())

    def append(self, element):
        self.elements.append(element)

    def _check_have_prange(self):
        if self._pmax is None:
            raise PRangeNotSet()

    def set_prange(self, pmin, pmax, dp):
        self._pmin, self._pmax = pmin, pmax
        self._prange_dp = dp

    def used_phase(self, p=None, eps=1.):
        '''
        Calculate phase definition from ray path.
        '''

        used = PhaseDef()
        fleg = self.phase.first_leg()
        used.append(Leg(fleg.departure, fleg.mode))
        n_elements_n = [None] + self.elements + [None]
        for before, element, after in zip(
                n_elements_n[:-2],
                n_elements_n[1:-1],
                n_elements_n[2:]):

            if element.is_kink() and HeadwaveStraight not in (
                    type(before),
                    type(after)):

                if element.reflection() or element.conversion():
                    z = element.discontinuity.z
                    used.append(Knee(
                        z,
                        element.in_direction,
                        element.out_direction != element.in_direction,
                        element.in_mode,
                        element.out_mode))

                    used.append(Leg(element.out_direction, element.out_mode))

            elif type(element) is HeadwaveStraight:
                z = element.interface.z
                k = Knee(
                    z,
                    before.in_direction,
                    after.out_direction != before.in_direction,
                    before.in_mode,
                    after.out_mode)

                k.headwave = True
                used.append(k)
                used.append(Leg(after.out_direction, after.out_mode))

            if (p is not None and before and after
                    and element.is_straight()
                    and before.is_kink()
                    and after.is_kink()
                    and element.turns()
                    and not before.reflection() and not before.conversion()
                    and not after.reflection() and not after.conversion()):

                ai = element.angle_in(p)
                if 90.0-eps < ai and ai < 90+eps:
                    used.append(
                        Head(
                            before.discontinuity.z,
                            before.out_direction,
                            element.mode))
                    used.append(
                        Leg(-before.out_direction, element.mode))

        used._direction_stop = self.phase.direction_stop()
        used._definition = self.phase.definition()

        return used

    def pmax(self):
        '''
        Get maximum valid ray parameter.
        '''
        self._check_have_prange()
        return self._pmax

    def pmin(self):
        '''
        Get minimum valid ray parameter.
        '''
        self._check_have_prange()
        return self._pmin

    def xmin(self):
        '''
        Get minimal distance.
        '''
        self._analyse()
        return self._xmin

    def xmax(self):
        '''
        Get maximal distance.
        '''
        self._analyse()
        return self._xmax

    def kinks(self):
        '''
        Iterate over propagation mode changes (reflections/transmissions).
        '''
        return (k for k in self.elements if isinstance(k, Kink))

    def straights(self):
        '''
        Iterate over ray segments.
        '''
        return (s for s in self.elements if isinstance(s, Straight))

    def headwave_straight(self):
        for s in self.elements:
            if type(s) is HeadwaveStraight:
                return s

    def first_straight(self):
        '''
        Get first ray segment.
        '''
        for s in self.elements:
            if isinstance(s, Straight):
                return s

    def last_straight(self):
        '''
        Get last ray segment.
        '''
        for s in reversed(self.elements):
            if isinstance(s, Straight):
                return s

    def efficiency(self, p):
        '''
        Get product of all conversion/reflection coefficients encountered on
        path.
        '''
        return reduce(
            operator.mul, (k.efficiency(p) for k in self.kinks()), 1.)

    def spreading(self, p, endgaps):
        '''
        Get geometrical spreading factor.
        '''
        if self._is_headwave:
            return 0.0

        self._check_have_prange()
        dp = self._prange_dp * 0.01
        assert self._pmax - self._pmin > dp

        if p + dp > self._pmax:
            p = p-dp

        x0, t = self.xt(p, endgaps)
        x1, t = self.xt(p+dp, endgaps)
        x0 *= d2r
        x1 *= d2r
        if x1 == x0:
            return num.nan

        dp_dx = dp/(x1-x0)

        x = x0
        if x == 0.:
            x = x1
            p = dp

        first = self.first_straight()
        last = self.last_straight()
        return num.abs(dp_dx) * first.pflat_in(p, endgaps) / (
            4.0 * math.pi * num.sin(x) *
            (earthradius-first.z_in(endgaps)) *
            (earthradius-last.z_out(endgaps))**2 *
            first.u_in(endgaps)**2 *
            num.abs(num.cos(first.angle_in(p, endgaps)*d2r)) *
            num.abs(num.cos(last.angle_out(p, endgaps)*d2r)))

    def make_p(self, dp=None, n=None, nmin=None):
        assert dp is None or n is None

        if self._pmin == self._pmax:
            return num.array([self._pmin])

        if dp is None:
            dp = self._prange_dp

        if n is None:
            n = int(round((self._pmax-self._pmin)/dp)) + 1

        if nmin is not None:
            n = max(n, nmin)

        ppp = num.linspace(self._pmin, self._pmax, n)
        return ppp

    def xt_endgaps(self, p, endgaps, which='both'):
        '''
        Get amount of distance/traveltime to be subtracted at the generic ray
        path's ends.
        '''

        zstart, zstop, dirstart, dirstop = endgaps
        firsts = self.first_straight()
        lasts = self.last_straight()
        xs, ts = firsts.xt_gap(
            p, zstart, firsts.z_in(), dirstart == firsts._direction_in)
        xe, te = lasts.xt_gap(
            p, zstop, lasts.z_out(), dirstop == lasts._direction_out)

        if which == 'both':
            return xs + xe, ts + te
        elif which == 'left':
            return xs, ts
        elif which == 'right':
            return xe, te

    def xt_endgaps_ptest(self, p, endgaps):
        '''
        Check if ray parameter is valid at source and receiver.
        '''

        zstart, zstop, dirstart, dirstop = endgaps
        firsts = self.first_straight()
        lasts = self.last_straight()
        return num.logical_and(firsts.test(p, zstart), lasts.test(p, zstop))

    def xt(self, p, endgaps):
        '''
        Calculate distance and traveltime for given ray parameter.
        '''

        if isinstance(p, num.ndarray):
            sx = num.zeros(p.size)
            st = num.zeros(p.size)
        else:
            sx = 0.0
            st = 0.0

        for s in self.straights():
            x, t = s.xt(p)
            sx += x
            st += t

        if endgaps:
            dx, dt = self.xt_endgaps(p, endgaps)
            sx -= dx
            st -= dt

        return sx, st

    def xt_limits(self, p):
        '''
        Calculate limits of distance and traveltime for given ray parameter.
        '''

        if isinstance(p, num.ndarray):
            sx = num.zeros(p.size)
            st = num.zeros(p.size)
            sxe = num.zeros(p.size)
            ste = num.zeros(p.size)
        else:
            sx = 0.0
            st = 0.0
            sxe = 0.0
            ste = 0.0

        sfirst = self.first_straight()
        slast = self.last_straight()

        for s in self.straights():
            if s is not sfirst and s is not slast:
                x, t = s.xt(p)
                sx += x
                st += t

        sends = [sfirst]
        if sfirst is not slast:
            sends.append(slast)

        for s in sends:
            x, t = s.xt(p)
            sxe += x
            ste += t

        return sx, (sx + sxe), st, (st + ste)

    def iter_zxt(self, p):
        '''
        Iterate over (depth, distance, traveltime) at each layer interface on
        ray path.
        '''

        sx = num.zeros(p.size)
        st = num.zeros(p.size)
        ok = False
        for s in self.straights():
            yield s.z_in(), sx.copy(), st.copy()

            x, t = s.xt(p)
            sx += x
            st += t
            ok = True

        if ok:
            yield s.z_out(), sx.copy(), st.copy()

    def zxt_path_subdivided(
            self, p, endgaps,
            points_per_straight=20,
            x_for_headwave=None):

        '''
        Get geometrical representation of ray path.
        '''

        if self._is_headwave:
            assert p.size == 1
            x, t = self.xt(p, endgaps)
            xstretch = x_for_headwave-x
            nout = xstretch.size
        else:
            nout = p.size

        dxl, dtl = self.xt_endgaps(p, endgaps, which='left')
        dxr, dtr = self.xt_endgaps(p, endgaps, which='right')

        # first create full path including the endgaps
        sx = num.zeros(nout) - dxl
        st = num.zeros(nout) - dtl
        zxt = []
        for s in self.straights():
            n = points_per_straight

            back = None
            zin, zout = s.z_in(), s.z_out()
            if type(s) is HeadwaveStraight:
                z = zin
                for i in range(n):
                    xs = float(i)/(n-1) * xstretch
                    ts = s.x2t_headwave(xs)
                    zxt.append((filled(z, xstretch.size), sx+xs, st+ts))
            else:
                if zin != zout:  # normal traversal
                    zs = num.linspace(zin, zout, n).tolist()
                    for z in zs:
                        x, t = s.xt(p, zpart=sorted([zin, z]))
                        zxt.append((filled(z, nout), sx + x, st + t))

                else:  # ray turns in layer
                    zturn = s.zturn(p)
                    back = []
                    for i in range(n):
                        z = zin + (zturn - zin) * num.sin(
                            float(i)/(n-1)*math.pi/2.0) * 0.999

                        if zturn[0] >= zin:
                            x, t = s.xt(p, zpart=[zin, z])
                        else:
                            x, t = s.xt(p, zpart=[z, zin])
                        zxt.append((z, sx + x, st + t))
                        back.append((z, x, t))

            if type(s) is HeadwaveStraight:
                x = xstretch
                t = s.x2t_headwave(xstretch)
            else:
                x, t = s.xt(p)

            sx += x
            st += t
            if back:
                for z, x, t in reversed(back):
                    zxt.append((z, sx - x, st - t))

        # gather results as arrays with such that x[ip, ipoint]
        fanz, fanx, fant = [], [], []
        for z, x, t in zxt:
            fanz.append(z)
            fanx.append(x)
            fant.append(t)

        z = num.array(fanz).T
        x = num.array(fanx).T
        t = num.array(fant).T

        # cut off the endgaps, add exact endpoints
        xmax = x[:, -1] - dxr
        tmax = t[:, -1] - dtr
        zstart, zstop = endgaps[:2]
        zs, xs, ts = [], [], []
        for i in range(nout):
            t_ = t[i]
            indices = num.where(num.logical_and(0. <= t_, t_ <= tmax[i]))[0]
            n = indices.size + 2
            zs_, xs_, ts_ = [num.empty(n, dtype=float) for j in range(3)]
            zs_[1:-1] = z[i, indices]
            xs_[1:-1] = x[i, indices]
            ts_[1:-1] = t[i, indices]
            zs_[0], zs_[-1] = zstart, zstop
            xs_[0], xs_[-1] = 0., xmax[i]
            ts_[0], ts_[-1] = 0., tmax[i]
            zs.append(zs_)
            xs.append(xs_)
            ts.append(ts_)

        return zs, xs, ts

    def _analyse(self):
        if self._p is not None:
            return

        p = self.make_p(nmin=20)
        xmin, xmax, tmin, tmax = self.xt_limits(p)

        self._x, self._t, self._p = xmax, tmax, p
        self._xmin, self._xmax = xmin.min(), xmax.max()
        self._tmin, self._tmax = tmin.min(), tmax.max()

    def draft_pxt(self, endgaps):
        self._analyse()

        if not self._is_headwave:
            cp, cx, ct = self._p, self._x, self._t
            pcrit = min(
                self.critical_pstart(endgaps),
                self.critical_pstop(endgaps))

            if pcrit < self._pmin:
                empty = num.array([], dtype=float)
                return empty, empty, empty

            elif pcrit >= self._pmax:
                dx, dt = self.xt_endgaps(cp, endgaps)
                return cp, cx-dx, ct-dt

            else:
                n = num.searchsorted(cp, pcrit) + 1
                rp, rx, rt = num.empty((3, n), dtype=float)
                rp[:-1] = cp[:n-1]
                rx[:-1] = cx[:n-1]
                rt[:-1] = ct[:n-1]
                rp[-1] = pcrit
                rx[-1], rt[-1] = self.xt(pcrit, endgaps)
                dx, dt = self.xt_endgaps(rp, endgaps)
                rx[:-1] -= dx[:-1]
                rt[:-1] -= dt[:-1]
                return rp, rx, rt

        else:
            dx, dt = self.xt_endgaps(self._p, endgaps)
            p, x, t = self._p, self._x - dx, self._t - dt
            p, x, t = p[0], x[0], t[0]
            xh = num.linspace(0., x*10-x, 10)
            th = self.headwave_straight().x2t_headwave(xh)
            return filled(p, xh.size), x+xh, t+th

    def interpolate_x2pt_linear(self, x, endgaps):
        '''
        Get approximate ray parameter and traveltime for distance.
        '''

        self._analyse()

        if self._is_headwave:
            dx, dt = self.xt_endgaps(self._p, endgaps)
            xmin = self._x[0] - dx[0]
            tmin = self._t[0] - dt[0]
            el = self.headwave_straight()
            xok = x[x >= xmin]
            th = el.x2t_headwave(xstretch=(xok-xmin)) + tmin
            return [
                (x_, self._p[0], t, None) for (x_, t) in zip(xok, th)]

        else:
            if num.all(x < self._xmin) or num.all(self._xmax < x):
                return []

            rp, rx, rt = self.draft_pxt(endgaps)

            xp = interp(x, rx, rp, 0)
            xt = interp(x, rx, rt, 0)

            if (rp.size and
                    len(xp) == 0 and
                    rx[0] == 0.0 and
                    any(x == 0.0) and
                    rp[0] == 0.0):

                xp = [(0.0, rp[0])]
                xt = [(0.0, rt[0])]

            return [
                (x_, p, t, (rp, rx, rt)) for ((x_, p), (_, t)) in zip(xp, xt)]

    def __eq__(self, other):
        if len(self.elements) != len(other.elements):
            return False

        return all(a == b for a, b in zip(self.elements, other.elements))

    def __hash__(self):
        return hash(
            tuple(hash(x) for x in self.elements) +
            (self.phase.definition(), ))

    def __str__(self, p=None, eps=1.):
        x = []
        start_i = None
        end_i = None
        turn_i = None

        def append_layers(si, ei, ti):
            if si == ei and (ti is None or ti == si):
                x.append('%i' % si)
            else:
                if ti is not None:
                    x.append('(%i-%i-%i)' % (si, ti, ei))
                else:
                    x.append('(%i-%i)' % (si, ei))

        for el in self.elements:
            if type(el) is Straight:
                if start_i is None:
                    start_i = el.layer.ilayer
                if el._direction_in != el._direction_out:
                    turn_i = el.layer.ilayer
                end_i = el.layer.ilayer

            elif isinstance(el, Kink):
                if start_i is not None:
                    append_layers(start_i, end_i, turn_i)
                    start_i = None
                    turn_i = None

                x.append(str(el))

        if start_i is not None:
            append_layers(start_i, end_i, turn_i)

        su = '(%s)' % self.used_phase(p=p, eps=eps).used_repr()

        return '%-15s %-17s %s' % (self.phase.definition(), su, ''.join(x))

    def critical_pstart(self, endgaps):
        '''
        Get critical ray parameter for source depth choice.
        '''

        return self.first_straight().critical_p_in(endgaps)

    def critical_pstop(self, endgaps):
        '''
        Get critical ray parameter for receiver depth choice.
        '''

        return self.last_straight().critical_p_out(endgaps)

    def ranges(self, endgaps):
        '''
        Get valid ranges of ray parameter, distance, and traveltime.
        '''
        p, x, t = self.draft_pxt(endgaps)
        return p.min(), p.max(), x.min(), x.max(), t.min(), t.max()

    def describe(self, endgaps=None, as_degrees=False):
        '''
        Get textual representation.
        '''

        self._analyse()

        if as_degrees:
            xunit = 'deg'
            xfact = 1.
        else:
            xunit = 'km'
            xfact = d2m/km

        sg = '''  Ranges for all depths in source and receiver layers:
   - x [%g, %g] %s
   - t [%g, %g] s
   - p [%g, %g] s/deg
''' % (
            self._xmin*xfact,
            self._xmax*xfact,
            xunit,
            self._tmin,
            self._tmax,
            self._pmin/r2d,
            self._pmax/r2d)

        if endgaps is not None:
            pmin, pmax, xmin, xmax, tmin, tmax = self.ranges(endgaps)
            ss = '''  Ranges for given source and receiver depths:
\n   - x [%g, %g] %s
\n   - t [%g, %g] s
\n   - p [%g, %g] s/deg
\n''' % (xmin*xfact, xmax*xfact, xunit, tmin, tmax, pmin/r2d, pmax/r2d)

        else:
            ss = ''

        return '%s\n' % self + ss + sg


class RefineFailed(CakeError):
    pass


class Ray(object):
    '''
    Representation of a ray with a specific (path, ray parameter, distance,
    arrival time) choice.

    **Attributes:**

        .. py:attribute:: path

           :py:class:`RayPath` object containing complete propagation history.

        .. py:attribute:: p

           Ray parameter (spherical) [s/rad]

        .. py:attribute:: x

           Radial distance [deg]

        .. py:attribute:: t

           Traveltime [s]

        .. py:attribute:: endgaps

           Needed for source/receiver depth adjustments in many
           :py:class:`RayPath` methods.
    '''

    def __init__(self, path, p, x, t, endgaps, draft_pxt):
        self.path = path
        self.p = p
        self.x = x
        self.t = t
        self.endgaps = endgaps
        self.draft_pxt = draft_pxt

    def given_phase(self):
        '''
        Get phase definition which was used to create the ray.

        :returns: :py:class:`PhaseDef` object
        '''

        return self.path.phase

    def used_phase(self):
        '''
        Compute phase definition from propagation path.

        :returns: :py:class:`PhaseDef` object
        '''

        return self.path.used_phase(self.p)

    def refine(self):
        if self.path._is_headwave:
            return

        if self.t == 0.0 and self.p == 0.0 and self.x == 0.0:
            return

        cp, cx, ct = self.draft_pxt
        ip = num.searchsorted(cp, self.p)
        if not (0 < ip < cp.size):
            raise RefineFailed()

        pl, ph = cp[ip-1], cp[ip]
        p_to_t = {}
        i = [0]

        def f(p):
            i[0] += 1
            x, t = self.path.xt(p, self.endgaps)
            p_to_t[p] = t
            return self.x - x

        try:
            self.p = brentq(f, pl, ph)
            self.t = p_to_t[self.p]

        except ValueError:
            raise RefineFailed()

    def t_and_attributes(self, attributes):
        d = {
            'takeoff_angle': lambda: self.takeoff_angle(),
            'incidence_angle': lambda: self.incidence_angle(),
            't': lambda: self.t,
            'p': lambda: self.p}

        return tuple(d[k]() for k in ['t'] + attributes)

    def takeoff_angle(self):
        '''
        Get takeoff angle of ray.

        The angle is returned in [degrees].
        '''

        return self.path.first_straight().angle_in(self.p, self.endgaps)

    def incidence_angle(self):
        '''
        Get incidence angle of ray.

        The angle is returned in [degrees].
        '''

        return self.path.last_straight().angle_out(self.p, self.endgaps)

    def efficiency(self):
        '''
        Get conversion/reflection efficiency of the ray.

        A value between 0 and 1 is returned, reflecting the relative amount of
        energy which is transmitted along the ray and not lost by reflections
        or conversions.
        '''

        return self.path.efficiency(self.p)

    def spreading(self):
        '''
        Get geometrical spreading factor.
        '''

        return self.path.spreading(self.p, self.endgaps)

    def surface_sphere(self):
        x1, y1 = 0., earthradius - self.endgaps[0]
        r2 = earthradius - self.endgaps[1]
        x2, y2 = r2*math.sin(self.x*d2r), r2*math.cos(self.x*d2r)
        return ((x2-x1)**2 + (y2-y1)**2)*4.0*math.pi

    def zxt_path_subdivided(self, points_per_straight=20):
        '''
        Get geometrical representation of ray path.

        Three arrays (depth, distance, time) with points on the ray's path of
        propagation are returned. The number of points which are used in each
        ray segment (passage through one layer) may be controlled by the
        ``points_per_straight`` parameter.
        '''
        return self.path.zxt_path_subdivided(
            num.atleast_1d(self.p), self.endgaps,
            points_per_straight=points_per_straight,
            x_for_headwave=num.atleast_1d(self.x))

    def __str__(self, as_degrees=False):
        if as_degrees:
            sd = '%6.3g deg' % self.x
        else:
            sd = '%7.5g km' % (self.x*(d2r*earthradius/km))

        return '%7.5g s/deg %s %6.4g s %5.1f %5.1f %3.0f%% %3.0f%% %s' % (
            self.p/r2d,
            sd,
            self.t,
            self.takeoff_angle(),
            self.incidence_angle(),
            100*self.efficiency(),
            100*self.spreading()*self.surface_sphere(),
            self.path.__str__(p=self.p))


def anything_to_crust2_profile(crust2_profile):
    from pyrocko.dataset import crust2x2
    if isinstance(crust2_profile, tuple):
        lat, lon = [float(x) for x in crust2_profile]
        return crust2x2.get_profile(lat, lon)
    elif isinstance(crust2_profile, str):
        return crust2x2.get_profile(crust2_profile)
    elif isinstance(crust2_profile, crust2x2.Crust2Profile):
        return crust2_profile
    else:
        assert False, 'crust2_profile must be (lat, lon) a profile ' \
            'key or a crust2x2 Profile object)'


class DiscontinuityNotFound(CakeError):
    def __init__(self, depth_or_name):
        CakeError.__init__(self)
        self.depth_or_name = depth_or_name

    def __str__(self):
        return 'Cannot find discontinuity from given depth or name: %s' % \
            self.depth_or_name


class LayeredModelError(CakeError):
    pass


class LayeredModel(object):
    '''
    Representation of a layer cake model.

    There are several ways to initialize an instance of this class.

    1. Use the module function :py:func:`load_model` to read a model from a
       file.
    2. Create an empty model with the default constructor and append layers and
       discontinuities with the :py:meth:`append` method (from top to bottom).
    3. Use the constructor :py:meth:`LayeredModel.from_scanlines`, to
       automatically create the :py:class:`Layer` and :py:class:`Discontinuity`
       objects from a given velocity profile.

    An earth model is represented by as stack of :py:class:`Layer` and
    :py:class:`Discontinuity` objects.  The method :py:meth:`arrivals` returns
    :py:class:`Ray` objects which may be e.g. queried for arrival times of
    specific phases. Each ray is associated with a :py:class:`RayPath` object.
    Ray objects share common ray paths if they have the same
    conversion/reflection/propagation history. Creating the ray path objects is
    relatively expensive (this is done in :py:meth:`gather_paths`), but they
    are cached for reuse in successive invocations.
    '''

    def __init__(self):
        self._surface_material = None
        self._elements = []
        self.nlayers = 0
        self._np = 10000
        self._pdepth = 5
        self._pathcache = {}

    def copy_with_elevation(self, elevation):
        '''
        Get copy of the model with surface layer stretched to given elevation.

        :param elevation: new surface elevation in [m]

        Elevation is positiv upward, contrary to the layered models downward
        `z` axis.
        '''

        c = copy.deepcopy(self)
        c._pathcache = {}
        surface = c._elements[0]
        toplayer = c._elements[1]

        assert toplayer.zbot > -elevation

        surface.z = -elevation
        c._elements[1] = toplayer.copy(ztop=-elevation)
        c._elements[1].ilayer = 0
        return c

    def zeq(self, z1, z2):
        return abs(z1-z2) < ZEPS

    def append(self, element):
        '''
        Add a layer or discontinuity at bottom of model.

        :param element: object of subclass of  :py:class:`Layer` or
            :py:class:`Discontinuity`.
        '''

        if isinstance(element, Layer):
            if element.zbot >= earthradius:
                element.zbot = earthradius - 1.

            if element.ztop >= earthradius:
                raise CakeError('Layer deeper than earthradius')

            element.ilayer = self.nlayers
            self.nlayers += 1

        self._elements.append(element)

    def elements(self, direction=DOWN):
        '''
        Iterate over all elements of the model.

        :param direction: direction of traversal :py:const:`DOWN` or
            :py:const:`UP`.

        Objects derived from the :py:class:`Discontinuity` and
        :py:class:`Layer` classes are yielded.
        '''

        if direction == DOWN:
            return iter(self._elements)
        else:
            return reversed(self._elements)

    def layers(self, direction=DOWN):
        '''
        Iterate over all layers of model.

        :param direction: direction of traversal :py:const:`DOWN` or
            :py:const:`UP`.

        Objects derived from the :py:class:`Layer` class are yielded.
        '''

        if direction == DOWN:
            return (el for el in self._elements if isinstance(el, Layer))
        else:
            return (
                el for el in reversed(self._elements) if isinstance(el, Layer))

    def layer(self, z, direction=DOWN):
        '''
        Get layer for given depth.

        :param z: depth [m]
        :param direction: direction of traversal :py:const:`DOWN` or
            :py:const:`UP`.

        Returns first layer which touches depth ``z`` (tolerant at boundaries).
        '''

        for layer in self.layers(direction):
            if layer.contains(z):
                return layer
        else:
            raise CakeError('Failed extracting layer at depth z=%s' % z)

    def walker(self):
        return Walker(self._elements)

    def material(self, z, direction=DOWN):
        '''
        Get material at given depth.

        :param z: depth [m]
        :param direction: direction of traversal :py:const:`DOWN` or
            :py:const:`UP`
        :returns: object of type :py:class:`Material`

        If given depth ``z`` happens to be at an interface, the material of the
        first layer with respect to the the traversal ordering is returned.
        '''

        lyr = self.layer(z, direction)
        return lyr.material(z)

    def discontinuities(self):
        '''
        Iterate over all discontinuities of the model.'''

        return (el for el in self._elements if isinstance(el, Discontinuity))

    def discontinuity(self, name_or_z):
        '''
        Get discontinuity by name or depth.

        :param name_or_z: name of discontinuity or depth [m] as float value
        '''

        if isinstance(name_or_z, float):
            candi = sorted(
                self.discontinuities(), key=lambda i: abs(i.z-name_or_z))
        else:
            candi = [i for i in self.discontinuities() if i.name == name_or_z]

        if not candi:
            raise DiscontinuityNotFound(name_or_z)

        return candi[0]

    def adapt_phase(self, phase):
        '''
        Adapt a phase definition for use with this model.

        This returns a copy of the phase definition, where named
        discontinuities are replaced with the actual depth of these, as defined
        in the model.
        '''

        phase = phase.copy()
        for knee in phase.knees():
            if knee.depth != 'surface':
                knee.depth = self.discontinuity(knee.depth).z
        for leg in phase.legs():
            if leg.depthmax is not None and isinstance(leg.depthmax, str):
                leg.depthmax = self.discontinuity(leg.depthmax).z

        return phase

    def path(self, p, phase, layer_start, layer_stop):
        '''
        Get ray path for given combination of ray parameter, phase definition,
        source and receiver layers.

        :param p: ray parameter (spherical) [s/rad]
        :param phase: phase definition (:py:class:`PhaseDef` object)
        :param layer_start: layer with source
        :param layer_stop: layer with receiver
        :returns: :py:class:`RayPath` object

        If it is not possible to find a solution, an exception of type
        :py:exc:`NotPhaseConform`, :py:exc:`MinDepthReached`,
        :py:exc:`MaxDepthReached`, :py:exc:`CannotPropagate`,
        :py:exc:`BottomReached` or :py:exc:`SurfaceReached` is raised.
        '''

        phase = self.adapt_phase(phase)
        knees = phase.knees()
        legs = phase.legs()
        next_knee = next_or_none(knees)
        leg = next_or_none(legs)
        assert leg is not None

        direction = leg.departure
        direction_stop = phase.direction_stop()
        mode = leg.mode
        mode_stop = phase.last_leg().mode

        walker = self.walker()
        walker.goto_layer(layer_start)
        current = walker.current()

        ttop, tbot = current.tests(p, mode)
        if not ttop and not tbot:
            raise CannotPropagate(direction, current.ilayer)

        if (direction == DOWN and not ttop) or (direction == UP and not tbot):
            direction = -direction

        path = RayPath(phase)
        trapdetect = set()
        while True:
            at_layer = isinstance(current, Layer)
            at_discontinuity = isinstance(current, Discontinuity)

            # detect trapped wave
            k = (id(next_knee), id(current), direction, mode)
            if k in trapdetect:
                raise Trapped()

            trapdetect.add(k)

            if at_discontinuity:
                oldmode, olddirection = mode, direction
                headwave = False
                if next_knee is not None and next_knee.matches(
                        current, mode, direction):

                    headwave = next_knee.headwave
                    direction = next_knee.out_direction()
                    mode = next_knee.out_mode
                    next_knee = next_or_none(knees)
                    leg = next(legs)

                else:  # implicit reflection/transmission
                    direction = current.propagate(p, mode, direction)

                if headwave:
                    path.set_is_headwave(True)

                    path.append(Kink(
                        olddirection, olddirection, oldmode, oldmode, current))

                    path.append(HeadwaveStraight(
                        olddirection, direction, oldmode, current))

                    path.append(Kink(
                        olddirection, direction, oldmode, mode, current))

                else:
                    path.append(Kink(
                        olddirection, direction, oldmode, mode, current))

            if at_layer:
                direction_in = direction
                direction = current.propagate(p, mode, direction_in)

                zturn = None
                if direction_in != direction:
                    zturn = current.zturn(p, mode)

                zmin, zmax = leg.depthmin, leg.depthmax
                if zmin is not None or zmax is not None:
                    if direction_in != direction:
                        if zmin is not None and zturn <= zmin:
                            raise MinDepthReached()
                        if zmax is not None and zturn >= zmax:
                            raise MaxDepthReached()
                    else:
                        if zmin is not None and current.ztop <= zmin:
                            raise MinDepthReached()
                        if zmax is not None and current.zbot >= zmax:
                            raise MaxDepthReached()

                path.append(Straight(direction_in, direction, mode, current))

                if next_knee is None and mode == mode_stop and \
                        current is layer_stop:

                    if zturn is None:
                        if direction == direction_stop:
                            break
                    else:
                        break

            walker.go(direction)
            current = walker.current()

        return path

    def gather_paths(self, phases=PhaseDef('P'), zstart=0.0, zstop=0.0):
        '''
        Get all possible ray paths for given source and receiver depths for one
        or more phase definitions.

        :param phases: a :py:class:`PhaseDef` object or a list of such objects.
            Comma-separated strings and lists of such strings are also accepted
            and are converted to :py:class:`PhaseDef` objects for convenience.
        :param zstart: source depth [m]
        :param zstop: receiver depth [m]
        :returns: a list of :py:class:`RayPath` objects

        Results of this method are cached internally. Cached results are
        returned, when a given combination of source layer, receiver layer and
        phase definition has been used before.
        '''

        eps = 1e-7  # num.finfo(float).eps * 1000.

        phases = to_phase_defs(phases)

        paths = []
        for phase in phases:

            layer_start = self.layer(zstart, -phase.direction_start())
            layer_stop = self.layer(zstop, phase.direction_stop())

            pathcachekey = (phase.definition(), layer_start, layer_stop)

            if pathcachekey in self._pathcache:
                phase_paths = self._pathcache[pathcachekey]
            else:
                hwknee = phase.headwave_knee()
                if hwknee:
                    name_or_z = hwknee.depth
                    interface = self.discontinuity(name_or_z)
                    mode = hwknee.in_mode
                    in_direction = hwknee.direction

                    pabove, pbelow = interface.critical_ps(mode)

                    p = min_not_none(pabove, pbelow)

                    # diffracted wave:
                    if in_direction == DOWN and (
                            pbelow is None or pbelow >= pabove):

                        p *= (1.0 - eps)

                    path = self.path(p, phase, layer_start, layer_stop)
                    path.set_prange(p, p, 1.)

                    phase_paths = [path]

                else:
                    try:
                        pmax_start = max([
                            radius(z)/layer_start.v(phase.first_leg().mode, z)
                            for z in (layer_start.ztop, layer_start.zbot)])

                        pmax_stop = max([
                            radius(z)/layer_stop.v(phase.last_leg().mode, z)
                            for z in (layer_stop.ztop, layer_stop.zbot)])

                        pmax = min(pmax_start, pmax_stop)

                        pedges = [0.]
                        for layer in self.layers():
                            for z in (layer.ztop, layer.zbot):
                                for mode in (P, S):
                                    for eps2 in [eps]:
                                        v = layer.v(mode, z)
                                        if v != 0.0:
                                            p = radius(z)/v
                                            if p <= pmax:
                                                pedges.append(p*(1.0-eps2))
                                                pedges.append(p)
                                                pedges.append(p*(1.0+eps2))

                        pedges = num.unique(sorted(pedges))

                        phase_paths = {}
                        cached = {}
                        counter = [0]

                        def p_to_path(p):
                            if p in cached:
                                return cached[p]

                            try:
                                counter[0] += 1
                                path = self.path(
                                    p, phase, layer_start, layer_stop)

                                if path not in phase_paths:
                                    phase_paths[path] = []

                                phase_paths[path].append(p)

                            except PathFailed:
                                path = None

                            cached[p] = path
                            return path

                        def recurse(pmin, pmax, i=0):
                            if i > self._pdepth:
                                return
                            path1 = p_to_path(pmin)
                            path2 = p_to_path(pmax)
                            if path1 is None and path2 is None and i > 0:
                                return
                            if path1 is None or path2 is None or \
                                    hash(path1) != hash(path2):

                                recurse(pmin, (pmin+pmax)/2., i+1)
                                recurse((pmin+pmax)/2., pmax, i+1)

                        for (pl, ph) in zip(pedges[:-1], pedges[1:]):
                            recurse(pl, ph)

                        for path, ps in phase_paths.items():
                            path.set_prange(
                                min(ps), max(ps), pmax/(self._np-1))

                        phase_paths = list(phase_paths.keys())

                    except ZeroDivisionError:
                        phase_paths = []

                self._pathcache[pathcachekey] = phase_paths

            paths.extend(phase_paths)

        paths.sort(key=lambda x: x.pmin())
        return paths

    def arrivals(
            self,
            distances=[],
            phases=PhaseDef('P'),
            zstart=0.0,
            zstop=0.0,
            refine=True):

        '''
        Compute rays and traveltimes for given distances.

        :param distances: list or array of distances [deg]
        :param phases: a :py:class:`PhaseDef` object or a list of such objects.
            Comma-separated strings and lists of such strings are also accepted
            and are converted to :py:class:`PhaseDef` objects for convenience.
        :param zstart: source depth [m]
        :param zstop: receiver depth [m]
        :param refine: bool flag, whether to use bisectioning to improve
            (p, x, t) estimated from interpolation
        :returns: a list of :py:class:`Ray` objects, sorted by
            (distance, arrival time)
        '''

        distances = num.asarray(distances, dtype=float)

        arrivals = []
        for path in self.gather_paths(phases, zstart=zstart, zstop=zstop):

            endgaps = path.endgaps(zstart, zstop)
            for x, p, t, draft_pxt in path.interpolate_x2pt_linear(
                    distances, endgaps):

                arrivals.append(Ray(path, p, x, t, endgaps, draft_pxt))

        if refine:
            refined = []
            for ray in arrivals:

                if ray.path._is_headwave:
                    refined.append(ray)

                try:
                    ray.refine()
                    refined.append(ray)

                except RefineFailed:
                    pass

            arrivals = refined

        arrivals.sort(key=lambda x: (x.x, x.t))
        return arrivals

    @classmethod
    def from_scanlines(cls, producer):
        '''
        Create layer cake model from sequence of materials at depths.

        :param producer: iterable yielding (depth, material, name) tuples

        Creates a new :py:class:`LayeredModel` object and uses its
        :py:meth:`append` method to add layers and discontinuities as needed.
        '''

        self = cls()
        for z, material, name in producer:

            if not self._elements:
                self.append(Surface(z, material))
            else:
                element = self._elements[-1]
                if self.zeq(element.zbot, z):
                    assert isinstance(element, Layer)
                    self.append(
                        Interface(z, element.mbot, material, name=name))

                else:
                    if isinstance(element, Discontinuity):
                        ztop = element.z
                        mtop = element.mbelow
                    elif isinstance(element, Layer):
                        ztop = element.zbot
                        mtop = element.mbot

                    if mtop == material:
                        layer = HomogeneousLayer(
                            ztop, z, material, name=name)
                    else:
                        layer = GradientLayer(
                            ztop, z, mtop, material, name=name)

                    self.append(layer)

        return self

    def to_scanlines(self, get_burgers=False):
        def fmt(z, m):
            if not m._has_default_burgers() or get_burgers:
                return (z, m.vp, m.vs, m.rho, m.qp, m.qs,
                        m.burger_eta1, m.burger_eta2, m.burger_valpha)
            return (z, m.vp, m.vs, m.rho, m.qp, m.qs)

        last = None
        lines = []
        for element in self.elements():
            if isinstance(element, Layer):
                if not isinstance(last, Layer):
                    lines.append(fmt(element.ztop, element.mtop))

                lines.append(fmt(element.zbot, element.mbot))

            last = element

        if not isinstance(last, Layer):
            lines.append(fmt(last.z, last.mbelow))

        return lines

    def iter_material_parameter(self, get):
        assert get in ('vp', 'vs', 'rho', 'qp', 'qs', 'z')
        if get == 'z':
            for layer in self.layers():
                yield layer.ztop
                yield layer.zbot
        else:
            getter = operator.attrgetter(get)
            for layer in self.layers():
                yield getter(layer.mtop)
                yield getter(layer.mbot)

    def profile(self, get):
        '''
        Get parameter profile along depth of the earthmodel.

        :param get: property to be queried (
            ``'vp'``, ``'vs'``, ``'rho'``, ``'qp'``, or ``'qs'``, or ``'z'``)
        :type get: str
        '''

        return num.array(list(self.iter_material_parameter(get)))

    def min(self, get='vp'):
        '''
        Find minimum value of a material property or depth.

        :param get: property to be queried (
            ``'vp'``, ``'vs'``, ``'rho'``, ``'qp'``, or ``'qs'``, or ``'z'``)
        '''

        return min(self.iter_material_parameter(get))

    def max(self, get='vp'):
        '''
        Find maximum value of a material property or depth.

        :param get: property to be queried (
            ``'vp'``, ``'vs'``, ``'rho'``, ``'qp'``, ``'qs'``, or ``'z'``)
        '''

        return max(self.iter_material_parameter(get))

    def simplify_layers(self, layers, max_rel_error=0.001):
        if len(layers) <= 1:
            return layers

        ztop = layers[0].ztop
        zbot = layers[-1].zbot
        zorigs = [layer.ztop for layer in layers]
        zorigs.append(zbot)
        zs = num.linspace(ztop, zbot, 100)
        data = []
        for z in zs:
            if z == ztop:
                direction = UP
            else:
                direction = DOWN

            mat = self.material(z, direction)
            data.append(mat.astuple())

        data = num.array(data, dtype=float)
        data_means = num.mean(data, axis=0)
        nmax = len(layers) // 2
        accept = False

        zcut_best = []
        for n in range(1, nmax+1):
            ncutintervals = 20
            zdelta = (zbot-ztop)/ncutintervals
            if n == 2:
                zcuts = [
                    [ztop, ztop + i*zdelta, zbot]
                    for i in range(1, ncutintervals)]
            elif n == 3:
                zcuts = []
                for j in range(1, ncutintervals):
                    for i in range(j+1, ncutintervals):
                        zcuts.append(
                            [ztop, ztop + j*zdelta, ztop + i*zdelta, zbot])
            else:
                zcuts = []
                zcuts.append(num.linspace(ztop, zbot, n+1))
                if zcut_best:
                    zcuts.append(sorted(num.linspace(
                        ztop, zbot, n).tolist() + zcut_best[1]))
                    zcuts.append(sorted(num.linspace(
                        ztop, zbot, n-1).tolist() + zcut_best[2]))

            best = None
            for icut, zcut in enumerate(zcuts):
                rel_par_errors = num.zeros(5)
                mpar_nodes = num.zeros((n+1, 5))

                for ipar in range(5):
                    znodes, vnodes, error_rms = util.polylinefit(
                        zs, data[:, ipar], zcut)

                    mpar_nodes[:, ipar] = vnodes
                    if data_means[ipar] == 0.0:
                        rel_par_errors[ipar] = -1
                    else:
                        rel_par_errors[ipar] = error_rms/data_means[ipar]

                rel_error = rel_par_errors.max()
                if best is None or rel_error < best[0]:
                    best = (rel_error, zcut, mpar_nodes)

            rel_error, zcut, mpar_nodes = best

            zcut_best.append(list(zcut))
            zcut_best[-1].pop(0)
            zcut_best[-1].pop()

            if rel_error <= max_rel_error:
                accept = True
                break

        if not accept:
            return layers

        rel_error, zcut, mpar_nodes = best

        material_nodes = []
        for i in range(n+1):
            material_nodes.append(Material(*mpar_nodes[i, :]))

        out_layers = []
        for i in range(n):
            mtop = material_nodes[i]
            mbot = material_nodes[i+1]
            ztop = zcut[i]
            zbot = zcut[i+1]
            if mtop == mbot:
                lyr = HomogeneousLayer(ztop, zbot, mtop)
            else:
                lyr = GradientLayer(ztop, zbot, mtop, mbot)

            out_layers.append(lyr)
        return out_layers

    def simplify(self, max_rel_error=0.001):
        '''
        Get representation of model with lower resolution.

        Returns an approximation of the model. All discontinuities are kept,
        but layer stacks with continuous model parameters are represented, if
        possible, by a lower number of layers.  Piecewise linear functions are
        fitted against the original model parameter's piecewise linear
        functions.  Successively larger numbers of layers are tried, until the
        difference to the original model is below ``max_rel_error``. The
        difference is measured as the RMS error of the fit normalized by the
        mean of the input (i.e. the fitted curves should deviate, on average,
        less than 0.1% from the input curves if ``max_rel_error`` = 0.001).
        '''

        mod_simple = LayeredModel()

        glayers = []
        for element in self.elements():

            if isinstance(element, Discontinuity):
                for layer in self.simplify_layers(
                        glayers, max_rel_error=max_rel_error):

                    mod_simple.append(layer)

                glayers = []
                mod_simple.append(element)
            else:
                glayers.append(element)

        for layer in self.simplify_layers(
                glayers, max_rel_error=max_rel_error):
            mod_simple.append(layer)

        return mod_simple

    def extract(self, depth_min=None, depth_max=None):
        '''
        Extract :py:class:`LayeredModel` from :py:class:`LayeredModel`.

        :param depth_min: depth of upper cut or name of :py:class:`Interface`
        :param depth_max: depth of lower cut or name of :py:class:`Interface`

        Interpolates a :py:class:`GradientLayer` at ``depth_min`` and/or
        ``depth_max``.
        '''

        if isinstance(depth_min, str):
            depth_min = self.discontinuity(depth_min).z

        if isinstance(depth_max, str):
            depth_max = self.discontinuity(depth_max).z

        mod_extracted = LayeredModel()

        for element in self.elements():
            element = element.copy()
            do_append = False
            if (depth_min is None or depth_min <= element.ztop) \
                    and (depth_max is None or depth_max >= element.zbot):
                mod_extracted.append(element)
                continue

            if depth_min is not None:
                if element.ztop < depth_min and depth_min < element.zbot:
                    _, element = element.split(depth_min)
                    do_append = True

            if depth_max is not None:
                if element.zbot > depth_max and depth_max > element.ztop:
                    element, _ = element.split(depth_max)
                    do_append = True

            if do_append:
                mod_extracted.append(element)

        return mod_extracted

    def replaced_crust(self, crust2_profile=None, crustmod=None):
        if crust2_profile is not None:
            profile = anything_to_crust2_profile(crust2_profile)
            crustmod = LayeredModel.from_scanlines(
                from_crust2x2_profile(profile))

        newmod = LayeredModel()
        for element in crustmod.extract(depth_max='moho').elements():
            if element.name != 'moho':
                newmod.append(element)
            else:
                moho1 = element

        mod = self.extract(depth_min='moho')
        first = True
        for element in mod.elements():
            if element.name == 'moho':
                if element.z <= moho1.z:
                    mbelow = mod.material(moho1.z, direction=UP)
                else:
                    mbelow = element.mbelow

                moho = Interface(moho1.z, moho1.mabove, mbelow, name='moho')
                newmod.append(moho)
            else:
                if first:
                    if isinstance(element, Layer) and element.zbot > moho.z:
                        newmod.append(GradientLayer(
                            moho.z,
                            element.zbot,
                            moho.mbelow,
                            element.mbot,
                            name=element.name))

                        first = False
                else:
                    newmod.append(element)
        return newmod

    def perturb(self, rstate=None, keep_vp_vs=False, zmax=None, **kwargs):
        '''
        Create a perturbed variant of the earth model.

        Randomly change the thickness and material parameters of the earth
        model from a uniform distribution.

        :param kwargs: Maximum change fraction (e.g. 0.1) of the parameters.
            Name the parameter, prefixed by ``p``. Supported parameters are
            ``ph, pvp, pvs, prho, pqs, pqp``.
        :type kwargs: dict
        :param rstate: Random state to draw from, defaults to ``None``
        :type rstate: :class:`numpy.random.RandomState`
        :param keep_vp_vs: Keep the Vp/Vs ratio, defaults to False
        :type keep_vp_vs: bool

        :returns: A new, perturbed earth model
        :rtype: :class:`~pyrocko.cake.LayeredModel`

        .. code-block :: python

            perturbed_model = model.perturb(ph=.1, pvp=.05, prho=.1)
        '''

        if rstate is None:
            rstate = num.random.RandomState()

        def factor(k):
            try:
                pval = kwargs[k]
                return rstate.uniform(1.0-pval, 1.0+pval)
            except KeyError:
                return 1.0

        def perturb_material(mat):
            mat_new = copy.deepcopy(mat)
            for param in kwargs:
                if param != 'ph':
                    value = getattr(mat, param[1:])
                    setattr(mat_new, param[1:], value*factor(param))

            if keep_vp_vs:
                mat_new.vs = mat_new.vp * (mat.vs / mat.vp)

            return mat_new

        model_new = LayeredModel()
        elements = list(self.elements())
        assert isinstance(elements[0], Surface)
        z = elements[0].z
        mat = None
        for element in elements:
            element_new = copy.deepcopy(element)
            if isinstance(element_new, Discontinuity):
                element_new.z = z

            elif isinstance(element_new, Layer):
                element_new.ztop = z
                if zmax is None or element.zbot < zmax:
                    z += (element_new.zbot-element_new.ztop) * factor('ph')
                else:
                    z += (element_new.zbot-element_new.ztop)
                element_new.zbot = z

                if mat is None or element.mtop != mat:
                    mat = element.mtop
                    if zmax is None or element.ztop < zmax:
                        mat_new = perturb_material(mat)
                    else:
                        mat_new = copy.deepcopy(mat)

                element_new.mtop = mat_new

                if element.mbot != mat:
                    mat = element.mbot
                    if zmax is None or element.zbot < zmax:
                        mat_new = perturb_material(mat)
                    else:
                        mat_new = copy.deepcopy(mat)

                element_new.mbot = mat_new

            model_new.append(element_new)

        return model_new

    def require_homogeneous(self):
        elements = list(self.elements())

        if len(elements) != 2:
            raise LayeredModelError(
                'Homogeneous model required but found more than one layer in '
                'earthmodel.')

        if not isinstance(elements[1], HomogeneousLayer):
            raise LayeredModelError(
                'Homogeneous model required but element #1 is not of type '
                'HomogeneousLayer.')

        return elements[1].m

    def __str__(self):
        return '\n'.join(str(element) for element in self._elements)


def read_hyposat_model(fn):
    '''
    Reader for HYPOSAT earth model files.

    To be used as producer in :py:meth:`LayeredModel.from_scanlines`.

    Interface names are translated as follows: ``'MOHO'`` -> ``'moho'``,
    ``'CONR'`` -> ``'conrad'``
    '''

    with open(fn, 'r') as f:
        translate = {'MOHO': 'moho', 'CONR': 'conrad'}
        lname = None
        for iline, line in enumerate(f):
            if iline == 0:
                continue

            z, vp, vs, name = util.unpack_fixed('f10, f10, f10, a4', line)
            if not name:
                name = None
            material = Material(vp*1000., vs*1000.)

            tname = translate.get(lname, lname)
            yield z*1000., material, tname

            lname = name


def read_nd_model(fn):
    '''
    Reader for TauP style '.nd' (named discontinuity) files.

    To be used as producer in :py:meth:`LayeredModel.from_scanlines`.

    Interface names are translated as follows: ``'mantle'`` -> ``'moho'``,
    ``'outer-core'`` -> ``'cmb'``, ``'inner-core'`` -> ``'icb'``.

    The format has been modified to include Burgers materials parameters in
    columns 7 (burger_eta1), 8 (burger_eta2) and 9. eta(3).
    '''
    with open(fn, 'r') as f:
        for x in read_nd_model_fh(f):
            yield x


def read_nd_model_str(s):
    f = StringIO(s)
    for x in read_nd_model_fh(f):
        yield x
    f.close()


def read_nd_model_fh(f):
    translate = {'mantle': 'moho', 'outer-core': 'cmb', 'inner-core': 'icb'}
    name = None
    for line in f:
        toks = line.split()
        if len(toks) == 9 or len(toks) == 6 or len(toks) == 4:
            z, vp, vs, rho = [float(x) for x in toks[:4]]
            qp, qs = None, None
            burgers = None
            if len(toks) == 6 or len(toks) == 9:
                qp, qs = [float(x) for x in toks[4:6]]
            if len(toks) == 9:
                burgers = \
                    [float(x) for x in toks[6:]]

            material = Material(
                vp*1000., vs*1000., rho*1000., qp, qs,
                burgers=burgers)

            yield z*1000., material, name
            name = None
        elif len(toks) == 1:
            name = translate.get(toks[0], toks[0])

    f.close()


def from_crust2x2_profile(profile, depthmantle=50000):
    from pyrocko.dataset import crust2x2

    default_qp_qs = {
        'soft sed.': (50., 50.),
        'hard sed.': (200., 200.),
        'upper crust': (600., 400.),
    }

    z = 0.
    for i in range(8):
        dz, vp, vs, rho = profile.get_layer(i)
        name = crust2x2.Crust2Profile.layer_names[i]
        if name in default_qp_qs:
            qp, qs = default_qp_qs[name]
        else:
            qp, qs = None, None

        material = Material(vp, vs, rho, qp, qs)
        iname = None
        if i == 7:
            iname = 'moho'
        if dz != 0.0:
            yield z, material, iname
            if i != 7:
                yield z+dz, material, name
            else:
                yield z+depthmantle, material, name

            z += dz


def write_nd_model_fh(mod, fh):
    def fmt(z, mat):
        rstr = ' '.join(
            util.gform(x, 4)
            for x in (
                z/1000.,
                mat.vp/1000.,
                mat.vs/1000.,
                mat.rho/1000.,
                mat.qp, mat.qs))
        if not mat._has_default_burgers():
            rstr += ' '.join(
                util.gform(x, 4)
                for x in (
                    mat.burger_eta1,
                    mat.burger_eta2,
                    mat.burger_valpha))
        return rstr.rstrip() + '\n'

    translate = {
        'moho': 'mantle',
        'cmb': 'outer-core',
        'icb': 'inner-core'}

    last = None
    for element in mod.elements():
        if isinstance(element, Interface):
            if element.name is not None:
                n = translate.get(element.name, element.name)
                fh.write('%s\n' % n)

        elif isinstance(element, Layer):
            if not isinstance(last, Layer):
                fh.write(fmt(element.ztop, element.mtop))

            fh.write(fmt(element.zbot, element.mbot))

        last = element

    if not isinstance(last, Layer):
        fh.write(fmt(last.z, last.mbelow))


def write_nd_model_str(mod):
    f = StringIO()
    write_nd_model_fh(mod, f)
    return f.getvalue()


def write_nd_model(mod, fn):
    with open(fn, 'w') as f:
        write_nd_model_fh(mod, f)


def builtin_models():
    return sorted([
        os.path.splitext(os.path.basename(x))[0]
        for x in glob.glob(builtin_model_filename('*'))])


def builtin_model_filename(modelname):
    return util.data_file(os.path.join('earthmodels', modelname+'.nd'))


def load_model(fn='ak135-f-continental.m', format='nd', crust2_profile=None):
    '''
    Load layered earth model from file.

    :param fn: filename
    :param format: format
    :param crust2_profile: ``(lat, lon)`` or
        :py:class:`pyrocko.dataset.crust2x2.Crust2Profile` object, merge model
        with crustal profile. If ``fn`` is forced to be ``None`` only the
        converted CRUST2.0 profile is returned.
    :returns: object of type :py:class:`LayeredModel`

    The following formats are currently supported:

    ============== ===========================================================
    format         description
    ============== ===========================================================
    ``'nd'``       'named discontinuity' format used by the TauP programs
    ``'hyposat'``  format used by the HYPOSAT location program
    ============== ===========================================================

    The naming of interfaces is translated from the file format's native naming
    to Cake's own convention (See :py:func:`read_nd_model` and
    :py:func:`read_hyposat_model` for details).  Cake likes the following
    internal names: ``'conrad'``, ``'moho'``, ``'cmb'`` (core-mantle boundary),
    ``'icb'`` (inner core boundary).
    '''

    if fn is not None:
        if format == 'nd':
            if not os.path.exists(fn) and fn in builtin_models():
                fn = builtin_model_filename(fn)
            reader = read_nd_model(fn)
        elif format == 'hyposat':
            reader = read_hyposat_model(fn)
        else:
            assert False, 'unsupported model format'

        mod = LayeredModel.from_scanlines(reader)
        if crust2_profile is not None:
            return mod.replaced_crust(crust2_profile)

        return mod

    else:
        assert crust2_profile is not None
        profile = anything_to_crust2_profile(crust2_profile)
        return LayeredModel.from_scanlines(
            from_crust2x2_profile(profile))


def castagna_vs_to_vp(vs):
    '''
    Calculate vp from vs using Castagna's relation.

    Castagna's relation (the mudrock line) is an empirical relation for vp/vs
    for siliciclastic rocks (i.e. sandstones and shales). [Castagna et al.,
    1985]

        vp = 1.16 * vs + 1360 [m/s]

    :param vs: S-wave velocity [m/s]
    :returns: P-wave velocity [m/s]
    '''

    return vs*1.16 + 1360.0


def castagna_vp_to_vs(vp):
    '''
    Calculate vp from vs using Castagna's relation.

    Castagna's relation (the mudrock line) is an empirical relation for vp/vs
    for siliciclastic rocks (i.e. sandstones and shales). [Castagna et al.,
    1985]

        vp = 1.16 * vs + 1360 [m/s]

    :param vp: P-wave velocity [m/s]
    :returns: S-wave velocity [m/s]
    '''

    return (vp - 1360.0) / 1.16


def evenize(x, y, minsize=10):
    if x.size < minsize:
        return x
    ry = (y.max()-y.min())
    if ry == 0:
        return x
    dx = (x[1:] - x[:-1])/(x.max()-x.min())
    dy = (y[1:] + y[:-1])/ry

    s = num.zeros(x.size)
    s[1:] = num.cumsum(num.sqrt(dy**2 + dx**2))
    s2 = num.linspace(0, s[-1], x.size)
    x2 = num.interp(s2, s, x)
    x2[0] = x[0]
    x2[-1] = x[-1]
    return x2


def filled(v, *args, **kwargs):
    '''
    Create NumPy array filled with given value.

    This works like :py:func:`numpy.ones` but initializes the array with ``v``
    instead of ones.
    '''
    x = num.empty(*args, **kwargs)
    x.fill(v)
    return x


def next_or_none(i):
    try:
        return next(i)
    except StopIteration:
        return None


def reci_or_none(x):
    try:
        return 1./x
    except ZeroDivisionError:
        return None


def mult_or_none(a, b):
    if a is None or b is None:
        return None
    return a*b


def min_not_none(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return min(a, b)


def xytups(xx, yy):
    d = []
    for x, y in zip(xx, yy):
        if num.isfinite(y):
            d.append((x, y))
    return d


def interp(x, xp, fp, monoton):
    if monoton == 1:
        return xytups(
            x, num.interp(x, xp, fp, left=num.nan, right=num.nan))
    elif monoton == -1:
        return xytups(
            x, num.interp(x, xp[::-1], fp[::-1], left=num.nan, right=num.nan))
    else:
        fs = []
        for xv in x:
            indices = num.where(num.logical_or(
                num.logical_and(xp[:-1] >= xv, xv > xp[1:]),
                num.logical_and(xp[:-1] <= xv, xv < xp[1:])))[0]

            for i in indices:
                xr = (xv - xp[i])/(xp[i+1]-xp[i])
                fv = xr*fp[i] + (1.-xr)*fp[i+1]
                fs.append((xv, fv))

        return fs


def float_or_none(x):
    if x is not None:
        return float(x)


def parstore_float(thelocals, obj, *args):
    for k, v in thelocals.items():
        if k != 'self' and (not args or k in args):
            setattr(obj, k, float_or_none(v))
