# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Traction field parameterizations used by :doc:`PDR source
</topics/pseudo-dynamic-rupture>`.
'''

import logging
import numpy as num
from pyrocko.guts import Object, Float, List, StringChoice, Int
from pyrocko.guts_array import Array

logger = logging.getLogger('pyrocko.gf.tractions')
km = 1e3
d2r = num.pi/180.
r2d = 180./num.pi


def tukey_window(N, alpha):
    assert alpha <= 1.
    window = num.ones(N)
    n = num.arange(N)

    N_f = int((alpha * N)//2)
    window[:N_f] = .5 * (1. - num.cos((2*num.pi * n[:N_f])/(alpha * N)))
    window[(N-N_f):] = window[:N_f][::-1]
    return window


def planck_window(N, epsilon):
    assert epsilon <= 1.
    window = num.ones(N)
    n = num.arange(N)

    N_f = int((epsilon * N))
    window[:N_f] = \
        (1. + num.exp((epsilon * N) / n[:N_f] -
                      (epsilon * N) / ((epsilon * N - n[:N_f]))))**-1.
    window[(N-N_f):] = window[:N_f][::-1]
    return window


class AbstractTractionField(Object):
    '''
    Base class for multiplicative traction fields (tapers).

    Fields of this type a re multiplied in the
    :py:class:`~pyrocko.gf.tractions.TractionComposition`
    '''
    operation = 'mult'

    def get_tractions(self, nx, ny, patches):
        raise NotImplementedError


class TractionField(AbstractTractionField):
    '''
    Base class for additive traction fields.

    Fields of this type are added in the
    :py:class:`~pyrocko.gf.tractions.TractionComposition`
    '''
    operation = 'add'

    def get_tractions(self, nx, ny, patches):
        raise NotImplementedError


class TractionComposition(TractionField):
    '''
    Composition of traction fields.

    :py:class:`~pyrocko.gf.tractions.TractionField` and
    :py:class:`~pyrocko.gf.tractions.AbstractTractionField` can be combined
    to realize a combination of different fields.
    '''
    components = List.T(
        AbstractTractionField.T(),
        default=[],
        help='Ordered list of tractions.')

    def get_tractions(self, nx, ny, patches=None):
        npatches = nx * ny
        tractions = num.zeros((npatches, 3))

        for comp in self.components:
            if comp.operation == 'add':
                tractions += comp.get_tractions(nx, ny, patches)
            elif comp.operation == 'mult':
                tractions *= comp.get_tractions(nx, ny, patches)
            else:
                raise AttributeError(
                    'Component %s has an invalid operation %s.' %
                    (comp, comp.operation))

        return tractions

    def add_component(self, field):
        logger.debug('Adding traction component.')
        self.components.append(field)


class HomogeneousTractions(TractionField):
    '''
    Homogeneous traction field.

    The traction vectors in strike, dip and normal direction are acting
    homogeneously on the rupture plane.
    '''

    strike = Float.T(
        default=1.,
        help='Tractions in strike direction [Pa].')
    dip = Float.T(
        default=1.,
        help='Traction in dip direction (up) [Pa].')
    normal = Float.T(
        default=1.,
        help='Traction in normal direction [Pa].')

    def get_tractions(self, nx, ny, patches=None):
        npatches = nx * ny

        return num.tile(
            (self.strike, self.dip, self.normal), npatches) \
            .reshape(-1, 3)


class DirectedTractions(TractionField):
    '''
    Directed traction field.

    The traction vectors are following a uniform ``rake``.
    '''

    rake = Float.T(
        default=0.,
        help='Rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view. Rake is translated into homogenous tractions '
             'in strike and up-dip direction.')
    traction = Float.T(
        default=1.,
        help='Traction in rake direction [Pa].')

    def get_tractions(self, nx, ny, patches=None):
        npatches = nx * ny

        strike = num.cos(self.rake*d2r) * self.traction
        dip = num.sin(self.rake*d2r) * self.traction
        normal = 0.

        return num.tile((strike, dip, normal), npatches).reshape(-1, 3)


class SelfSimilarTractions(TractionField):
    '''
    Traction model following Power & Tullis (1991).

    The traction vectors are calculated as a sum of 2D-cosines with a constant
    amplitude / wavelength ratio. The wavenumber kx and ky are constant for
    each cosine function. The rank defines the maximum wavenumber used for
    summation. So, e.g. a rank of 3 will lead to a summation of cosines with
    ``kx = ky`` in (1, 2, 3).
    Each cosine has an associated phases, which defines both the phase shift
    and also the shift from the rupture plane centre.
    Finally the summed cosines are translated into shear tractions based on the
    rake and normalized with ``traction_max``.

    '''
    rank = Int.T(
        default=1,
        help='Maximum summed cosine wavenumber/spatial frequency.')

    rake = Float.T(
        default=0.,
        help='Rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view. Rake is translated into homogenous tractions '
             'in strike and up-dip direction.')

    traction_max = Float.T(
        default=1.,
        help='Maximum traction vector length [Pa].')

    phases = Array.T(
        optional=True,
        dtype=num.float64,
        shape=(None,),
        help='Phase shift of the cosines in [rad].')

    def get_phases(self):
        if self.phases is not None:
            if self.phases.shape[0] == self.rank:
                return self.phases

        return (num.random.random(self.rank) * 2. - 1.) * num.pi

    def get_tractions(self, nx, ny, patches=None):
        z = num.zeros((ny, nx))
        phases = self.get_phases()

        for i in range(1, self.rank+1):
            x = num.linspace(-i*num.pi, i*num.pi, nx) + i*phases[i-1]
            y = num.linspace(-i*num.pi, i*num.pi, ny) + i*phases[i-1]
            x, y = num.meshgrid(x, y)
            r = num.sqrt(x**2 + y**2)
            z += 1. / i * num.cos(r + phases[i-1])

        t = num.zeros((nx*ny, 3))
        t[:, 0] = num.cos(self.rake*d2r) * z.ravel(order='F')
        t[:, 1] = num.sin(self.rake*d2r) * z.ravel(order='F')

        t *= self.traction_max / num.max(num.linalg.norm(t, axis=1))

        return t


class FractalTractions(TractionField):
    '''
    Fractal traction field.
    '''

    rseed = Int.T(
        default=None,
        optional=True,
        help='Seed for :py:class:`~numpy.random.RandomState`.'
             'If ``None``, an random seed will be initialized.')

    rake = Float.T(
        default=0.,
        help='Rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view. Rake is translated into homogenous tractions '
             'in strike and up-dip direction.')

    traction_max = Float.T(
        default=1.,
        help='Maximum traction vector length [Pa].')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.rseed is None:
            self.rseed = num.random.randint(0, 2**31-1)
        self._data = None

    def _get_data(self, nx, ny):
        if self._data is None:
            rstate = num.random.RandomState(self.rseed)
            self._data = rstate.rand(nx, ny)

        return self._data

    def get_tractions(self, nx, ny, patches=None):
        if patches is None:
            raise AttributeError(
                'Patches needs to be given for this traction field.')
        npatches = nx * ny
        dx = -patches[0].al1 + patches[0].al2
        dy = -patches[0].aw1 + patches[0].aw2

        # Create random data and get spectrum and power spectrum
        data = self._get_data(nx, ny)
        spec = num.fft.fftshift(num.fft.fft2(data))
        power_spec = (num.abs(spec)/spec.size)**2

        # Get 0-centered wavenumbers (k_rad == 0.) is in the centre
        kx = num.fft.fftshift(num.fft.fftfreq(nx, d=dx))
        ky = num.fft.fftshift(num.fft.fftfreq(ny, d=dy))
        k_rad = num.sqrt(ky[:, num.newaxis]**2 + kx[num.newaxis, :]**2)

        # Define wavenumber bins
        k_bins = num.arange(0, num.max(k_rad), num.max(k_rad)/10.)

        # Set amplitudes within wavenumber bins to power_spec * 1 / k_max
        amps = num.zeros(k_rad.shape)
        amps[k_rad == 0.] = 1.

        for i in range(k_bins.size-1):
            k_min = k_bins[i]
            k_max = k_bins[i+1]
            r = num.logical_and(k_rad > k_min, k_rad <= k_max)
            amps[r] = power_spec.T[r]
            amps = num.sqrt(amps * data.size * num.pi * 4)

        amps[k_rad > k_bins.max()] = power_spec.ravel()[num.argmax(power_spec)]

        # Multiply spectrum by amplitudes and inverse fft into demeaned noise
        spec *= amps.T

        tractions = num.abs(num.fft.ifft2(spec))
        tractions -= num.mean(tractions)
        tractions *= self.traction_max / num.abs(tractions).max()

        t = num.zeros((npatches, 3))
        t[:, 0] = num.cos(self.rake*d2r) * tractions.ravel(order='C')
        t[:, 1] = num.sin(self.rake*d2r) * tractions.ravel(order='C')

        return t


class RectangularTaper(AbstractTractionField):
    width = Float.T(
        default=.2,
        help='Width of the taper as a fraction of the plane.')

    type = StringChoice.T(
        choices=('tukey', ),
        default='tukey',
        help='Type of the taper, default: "tukey".')

    def get_tractions(self, nx, ny, patches=None):
        if self.type == 'tukey':
            x = tukey_window(nx, self.width)
            y = tukey_window(ny, self.width)
            return (x[:, num.newaxis] * y).ravel()[:, num.newaxis]

        raise AttributeError('Unknown type: %s' % self.type)


class DepthTaper(AbstractTractionField):
    depth_start = Float.T(
        help='Depth where the taper begins [m].')

    depth_stop = Float.T(
        help='Depth where taper ends and drops to zero [m].')

    type = StringChoice.T(
        choices=('linear', ),
        default='linear',
        help='Type of the taper, default: "linear".')

    def get_tractions(self, nx, ny, patches):
        assert self.depth_stop > self.depth_start
        depths = num.array([p.depth for p in patches])

        if self.type == 'linear':
            slope = self.depth_stop - self.depth_start
            depths -= self.depth_stop
            depths /= -slope
            depths[depths > 1.] = 1.
            depths[depths < 0.] = 0.
            return depths[:, num.newaxis]


def plot_tractions(tractions, nx=15, ny=12, depth=10*km, component='strike'):
    '''
    Plot traction model for quick inspection.

    :param tractions:
        Traction field or traction composition to be displayed.
    :type tractions:
        :py:class:`pyrocko.gf.tractions.TractionField`

    :param nx:
        Number of patches along strike.
    :type nx:
        int

    :param ny:
        Number of patches down dip.
    :type ny:
        int

    :param depth:
        Depth of the rupture plane center in [m].
    :type depth:
        float

    :param component:
        Choice of traction component to be shown. Available: ``'tx'`` (along
        strike), ``'ty'`` (up dip), ``'tz'`` (normal), ``'absolute'`` (vector
        length).
    :type component:
        str
    '''
    import matplotlib.pyplot as plt
    from pyrocko.modelling.okada import OkadaSource

    comp2idx = dict(
        tx=0, ty=1, tz=2)

    source = OkadaSource(
        lat=0.,
        lon=0.,
        depth=depth,
        al1=-20*km, al2=20*km,
        aw1=-15*km, aw2=15*km,
        strike=120., dip=90., rake=90.,
        slip=5.)

    patches, _ = source.discretize(nx, ny)
    tractions = tractions.get_tractions(nx, ny, patches)

    if component in comp2idx:
        tractions = tractions[:, comp2idx[component]].reshape(nx, ny)
    elif component == 'absolute':
        tractions = num.linalg.norm(tractions, axis=1).reshape(nx, ny)
    else:
        raise ValueError('Given component is not valid.')

    fig = plt.figure()
    ax = fig.gca()

    ax.imshow(tractions)

    plt.show()


__all__ = [
    'AbstractTractionField',
    'TractionField',
    'TractionComposition',
    'HomogeneousTractions',
    'DirectedTractions',
    'FractalTractions',
    'SelfSimilarTractions',
    'RectangularTaper',
    'DepthTaper',
    'plot_tractions']
