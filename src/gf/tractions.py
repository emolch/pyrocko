import logging
import numpy as num
from pyrocko.guts import Object, Float, List, StringChoice

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
    operation = 'mult'

    def get_tractions(self, nx, ny, patches):
        raise NotImplementedError


class TractionField(AbstractTractionField):
    operation = 'add'

    def get_tractions(self, nx, ny, patches):
        raise NotImplementedError


class TractionComposition(TractionField):

    components = List.T(
        AbstractTractionField.T(),
        default=[],
        help='Ordered list of tractions')

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
        logger.debug('adding traction component')
        self.components.append(field)


class UniformTractions(TractionField):
    traction = Float.T(
        default=1.,
        help='Uniform traction in strike, dip and normal direction [Pa]')

    def get_tractions(self, nx, ny, patches=None):
        npatches = nx * ny
        return num.full((npatches, 3), self.traction)


class HomogeneousTractions(TractionField):
    strike = Float.T(
        default=1.,
        help='Tractions in strike direction [Pa]')
    dip = Float.T(
        default=1.,
        help='Traction in dip direction (up) [Pa]')
    normal = Float.T(
        default=1.,
        help='Traction in normal direction [Pa]')

    def get_tractions(self, nx, ny, patches=None):
        npatches = nx * ny

        return num.tile(
            (self.strike, self.dip, self.normal), npatches) \
            .reshape(-1, 3)


class DirectedTractions(TractionField):
    rake = Float.T(
        default=0.,
        help='rake angle in [deg], '
             'measured counter-clockwise from right-horizontal '
             'in on-plane view. Rake is translated into homogenous tractions '
             'in strike and up-dip direction.')
    traction = Float.T(
        default=1.,
        help='Traction in rake direction [Pa]')

    def get_tractions(self, nx, ny, patches=None):
        npatches = nx * ny

        strike = num.cos(self.rake*d2r) * self.traction
        dip = num.sin(self.rake*d2r) * self.traction
        normal = 0.

        return num.tile((strike, dip, normal), npatches).reshape(-1, 3)


class RectangularTaper(AbstractTractionField):
    width = Float.T(
        default=.2,
        help='Width of the taper as a fraction of the plane.')
    type = StringChoice.T(
        choices=('tukey', ),
        default='tukey',
        help='Type of the taper, default "tukey"')

    def get_tractions(self, nx, ny, patches=None):
        if self.type == 'tukey':
            x = tukey_window(nx, self.width)
            y = tukey_window(ny, self.width)
            return (x[:, num.newaxis] * y).ravel()[:, num.newaxis]

        raise AttributeError('unknown type %s' % self.type)


class DepthTaper(AbstractTractionField):
    depth_start = Float.T(
        help='Depth where the taper begins [km]')

    depth_stop = Float.T(
        help='Depth where taper stops, and drops to 0. [km]')

    type = StringChoice.T(
        choices=('linear', ),
        default='linear',
        help='Type of the taper, default "linear"')

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
    import matplotlib.pyplot as plt
    from pyrocko.modelling.okada import OkadaSource

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
    tractions = tractions[:, 0].reshape(nx, ny)

    fig = plt.figure()
    ax = fig.gca()

    ax.imshow(tractions)

    plt.show()


if __name__ == '__main__':
    tractions = TractionComposition(
        components=[
            UniformTractions(traction=45e3),
            RectangularTaper(),
            DepthTaper(depth_start=10.*km, depth_stop=30.*km)
        ])

    plot_tractions(tractions)
