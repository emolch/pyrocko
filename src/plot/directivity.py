import logging
import numpy as num
import matplotlib.pyplot as plt

from matplotlib.cm import ScalarMappable
from matplotlib.ticker import FuncFormatter

from pyrocko.plot import beachball
from pyrocko.gf.meta import Timing
from pyrocko.gf import LocalEngine, Target, RectangularSource, map_anchor
from pyrocko.util import num_full_like


km = 1e3
r2d = 180. / num.pi
d2r = num.pi / 180.

logger = logging.getLogger(__name__)


QUANTITY_LABEL = {
    'displacement': 'Displacement [m]',
    'velocity': 'Velocity [m/s]',
    'acceleration': 'Acceleration [m/s²]'
}


def get_azimuthal_targets(
        store_id, source, radius,
        azi_begin=0., azi_end=360., dazi=1.,
        interpolation='multilinear',
        components='RTZ', quantity='displacement'):

    assert dazi > 0.
    assert azi_begin < azi_end

    nstations = int((azi_end - azi_begin) // dazi)
    assert nstations > 0

    azimuths = num.linspace(azi_begin, azi_end, nstations)

    coords = num.zeros((2, nstations))
    coords[0, :] = num.cos(azimuths*d2r)
    coords[1, :] = num.sin(azimuths*d2r)
    coords *= radius

    dips = {'R': 0., 'T': 0., 'Z': -90.}
    for comp in components:
        assert comp in dips.keys()

    target_kwargs = dict(
        quantity='displacement',
        interpolation=interpolation,
        store_id=store_id)

    targets = [
        Target(
            lat=source.lat,
            lon=source.lon,
            north_shift=coords[0, iazi] + source.north_shift,
            east_shift=coords[1, iazi] + source.east_shift,
            azimuth={
                'R': azi,
                'T': azi+90.,
                'Z': 0.
            }[channel],
            dip=dips[channel],
            codes=('', 'S%01d' % iazi, '', channel),
            **target_kwargs)
        for iazi, azi in enumerate(azimuths)
        for channel in components]

    for target, azi in zip(targets, azimuths):
        target.azimuth = azi
        target.dazi = dazi

    return targets, azimuths


def get_seismogram_array(
        response, fmin=None, fmax=None,
        component='R', envelope=False):
    resp = response
    assert len(resp.request.sources) == 1, 'more than one source in response'

    tmin = None
    tmax = None
    traces = []

    for _, target, tr in response.iter_results():
        if target.codes[-1] != component:
            continue
        assert hasattr(target, 'azimuth')
        assert target.dazi

        if fmin and fmax:
            tr.bandpass(2, fmin, fmax)
        elif fmin:
            tr.highpass(4, fmin)
        elif fmax:
            tr.lowpass(4, fmax)

        tmin = min(tmin, tr.tmin) if tmin else tr.tmin
        tmax = max(tmax, tr.tmax) if tmax else tr.tmax
        traces.append(tr)

    for tr in traces:
        tr.extend(tmin, tmax, fillmethod='repeat')
        if envelope:
            tr.abshilbert()

    data = num.array([tr.get_ydata() for tr in traces])
    data -= data.mean()
    nsamples = data.shape[1]
    return data, num.linspace(tmin, tmax, nsamples)


def hillshade(array, azimuth, angle_altitude):
    azimuth = 360.0 - azimuth
    azi = azimuth * r2d
    alt = angle_altitude * r2d

    x, y = num.gradient(array)
    slope = num.pi/2. - num.arctan(num.sqrt(x*x + y*y))
    aspect = num.arctan2(-x, y)

    shaded = num.sin(alt)*num.sin(slope) \
        + num.cos(alt)*num.cos(slope)*num.cos((azi - num.pi/2.) - aspect)

    return (shaded + 1.)/2.


def hillshade_seismogram_array(
        seismogram_array, rgba_map,
        shad_lim=(.4, .98), contrast=1., blend_mode='multiply'):
    assert blend_mode in ('multiply', 'screen'), 'unknown blend mode'
    assert shad_lim[0] < shad_lim[1], 'bad shading limits'
    from scipy.ndimage import convolve as im_conv
    # Light source from somewhere above - psychologically the best choice
    # from upper left
    ramp = num.array([[1., 0.], [0., -1.]]) * contrast

    # convolution of two 2D arrays
    shad = im_conv(seismogram_array, ramp.T).ravel()
    shad *= -1.

    # if there are strong artifical edges in the data, shades get
    # dominated by them. Cutting off the largest and smallest 2% of
    # # shades helps
    percentile2 = num.percentile(shad, 2.0)
    percentile98 = num.percentile(shad, 98.0)

    shad[shad > percentile98] = percentile98
    shad[shad < percentile2] = percentile2

    # # normalize shading
    shad -= num.nanmin(shad)
    shad /= num.nanmax(shad)

    # # reduce range to balance gray color
    shad *= shad_lim[1] - shad_lim[0]
    shad += shad_lim[0]

    if blend_mode == 'screen':
        rgba_map[:, :3] = 1. - ((1. - rgba_map[:, :3])*(shad[:, num.newaxis]))
    elif blend_mode == 'multiply':
        rgba_map[:, :3] *= shad[:, num.newaxis]

    return rgba_map


def plot_directivity(
        engine, source, store_id,
        distance=300*km, azi_begin=0., azi_end=360., dazi=1.,
        phase_begin='first{stored:any_P}-10%',
        phase_end='last{stored:any_S}+50',
        quantity='displacement', envelope=False,
        component='R', fmin=0.01, fmax=0.1,
        hillshade=True, cmap=None,
        plot_mt='full', show_phases=True, show_description=True,
        reverse_time=False, show_nucleations=True, axes=None, nthreads=0):
    '''Plot the directivity and radiation characteristics of source models

    Synthetic seismic traces (R, T or Z) are forward-modelled at a defined
    radius, covering the full or partial azimuthal range and projected on a
    polar plot. Difference in the amplitude are enhanced by hillshading
    the data.

    :param engine: Forward modelling engine
    :type engine: :py:class:`~pyrocko.gf.seismosizer.Engine`
    :param source: Parametrized source model
    :type source: :py:class:`~pyrocko.gf.seismosizer.Source`
    :param store_id: Store ID used for forward modelling
    :type store_id: str
    :param distance: Distance in [m]
    :type distance: float
    :param azi_begin: Begin azimuth in [deg]
    :type azi_begin: float
    :param azi_end: End azimuth in [deg]
    :type azi_end: float
    :param dazi: Delta azimuth, bin size [deg]
    :type dazi: float
    :param phase_begin: Start time of the window
    :type phase_begin: :py:class:`~pyrocko.gf.meta.Timing`
    :param phase_end: End time of the window
    :type phase_end: :py:class:`~pyrocko.gf.meta.Timing`
    :param quantity: Seismogram quantity, default ``displacement``
    :type quantity: str
    :param envelope: Plot envelop instead of seismic trace
    :type envelope: bool
    :param component: Forward modelled component, default ``R``. Choose from
        `RTZ`
    :type component: str
    :param fmin: Bandpass lower frequency [Hz], default ``0.01``
    :type fmin: float
    :param fmax: Bandpass upper frequency [Hz], default ``0.1``
    :type fmax: float
    :param hillshade: Enable hillshading, default ``True``
    :type hillshade: bool
    :param cmap: Matplotlit colormap to use, default ``seismic``.
        When ``envelope`` is ``True`` the default colormap will be ``Reds``.
    :type cmap: str
    :param plot_mt: Plot a centered moment tensor, default ``full``.
        Choose from ``full, deviatoric, dc or False``
    :type plot_mt: str, bool
    :param show_phases: Show annotations, default ``True``
    :type show_phases: bool
    :param show_description: Show desciption, default ``True``
    :type show_description: bool
    :param reverse_time: Reverse time axis. First phases arrive at the center,
        default ``False``
    :type reverse_time: bool
    :param show_nucleations: Show nucleation piercing points on the moment
        tensor, default ``True``
    :type show_nucleations: bool
    :param axes: Give axes to plot into
    :type axes: :py:class:`matplotlib.axes.Axes`
    :param nthreads: Number of threads used for forward modelling,
        default ``0`` - all available cores
    :type nthreads: int
    '''

    if axes is None:
        fig = plt.figure()
        ax = fig.add_subplot(111, polar=True)
    else:
        fig = axes.figure
        ax = axes

    if envelope and cmap is None:
        cmap = 'Reds'
    elif cmap is None:
        cmap = 'seismic'

    targets, azimuths = get_azimuthal_targets(
        store_id, source, distance, azi_begin, azi_end, dazi,
        components='R', quantity=quantity)
    store = engine.get_store(store_id)
    mt = source.pyrocko_moment_tensor(store=store, target=targets[0])

    resp = engine.process(source, targets, nthreads=nthreads)
    data, times = get_seismogram_array(
        resp, fmin, fmax,
        component=component, envelope=envelope)

    timing_begin = Timing(phase_begin)
    timing_end = Timing(phase_end)

    nucl_depth = source.depth
    nucl_distance = distance

    anch_x, anch_y = map_anchor[source.anchor]

    if hasattr(source, 'nucleation_x') and hasattr(source, 'nucleation_y'):
        try:
            iter(source.nucleation_x)
            nx = float(source.nucleation_x[0])
            ny = float(source.nucleation_y[0])

        except TypeError:
            nx = source.nucleation_x
            ny = source.nucleation_y

        nucl_distance += nx * source.length/2.
        nucl_depth += ny*num.sin(source.dip*d2r) * source.width/2.

    if hasattr(source, 'anchor'):
        anch_x, anch_y = map_anchor[source.anchor]
        nucl_distance -= anch_x * source.length/2.
        nucl_depth -= anch_y*num.sin(source.dip*d2r) * source.width/2.

    tbegin = store.t(timing_begin, (nucl_depth, nucl_distance))
    tend = store.t(timing_end, (nucl_depth, nucl_distance))
    tsel = num.logical_and(times >= tbegin, times <= tend)

    data = data[:, tsel].T
    times = times[tsel]
    duration = times[-1] - times[0]

    vmax = num.abs(data).max()
    cmw = ScalarMappable(cmap=cmap)
    cmw.set_array(data)
    cmw.set_clim(-vmax, vmax)

    if envelope:
        cmw.set_clim(0., vmax)

    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)

    strike_label = mt.strike1
    if hasattr(source, 'strike'):
        strike_label = source.strike

    try:
        ax.set_rlabel_position(strike_label % 180. - 180.)
    except AttributeError:
        logger.warn('Old matplotlib version: cannot set label positions')

    def r_fmt(v, p):
        if v < tbegin or v > tend:
            return ''
        return '%g s' % v

    ax.yaxis.set_major_formatter(FuncFormatter(r_fmt))
    if reverse_time:
        ax.set_rlim(times[0] - .3*duration, times[-1])
    else:
        ax.set_rlim(times[-1] + .3*duration, times[0])

    ax.grid(zorder=20)

    if isinstance(plot_mt, str):
        mt_size = .15
        beachball.plot_beachball_mpl(
            mt, ax,
            beachball_type=plot_mt, size=mt_size,
            size_units='axes', color_t=(0.7, 0.4, 0.4),
            position=(.5, .5), linewidth=1.)

        if hasattr(source, 'nucleation_x') and hasattr(source, 'nucleation_y')\
                and show_nucleations:
            try:
                iter(source.nucleation_x)
                nucleation_x = source.nucleation_x
                nucleation_y = source.nucleation_y
            except TypeError:
                nucleation_x = [source.nucleation_x]
                nucleation_y = [source.nucleation_y]

            for nx, ny in zip(nucleation_x, nucleation_y):
                angle = float(num.arctan2(ny, nx))
                rtp = num.array([[1., angle, (90.-source.strike)*d2r]])
                points = beachball.numpy_rtp2xyz(rtp)
                x, y = beachball.project(points, projection='lambert').T
                norm = num.sqrt(x**2 + y**2)
                x = x / norm * mt_size/2.
                y = y / norm * mt_size/2.
                ax.plot(x+.5, y+.5, 'x', ms=6, mew=2, mec='darkred', mfc='red',
                        transform=ax.transAxes, zorder=10)

    mesh = ax.pcolormesh(
        azimuths * d2r, times, data,
        cmap=cmw.cmap, shading='gouraud', zorder=0)

    if hillshade:
        mesh.update_scalarmappable()
        color = mesh.get_facecolor()
        color = hillshade_seismogram_array(
            data, color, shad_lim=(.85, 1.), blend_mode='multiply')
        mesh.set_facecolor(color)

    if show_phases:
        _phase_begin = Timing(phase_begin)
        _phase_end = Timing(phase_end)

        for p in (_phase_begin, _phase_end):
            p.offset = 0.
            p.offset_is_slowness = False
            p.offset_is_percent = False

        tphase_first = store.t(_phase_begin, (nucl_depth, nucl_distance))
        tphase_last = store.t(_phase_end, (nucl_depth, nucl_distance))

        theta = num.linspace(0, 2*num.pi, 360)
        tfirst = num_full_like(theta, tphase_first)
        tlast = num_full_like(theta, tphase_last)

        ax.plot(theta, tfirst, color='k', alpha=.3, lw=1., ls='--')
        ax.plot(theta, tlast, color='k', alpha=.3, lw=1., ls='--')

        ax.text(
            300.*d2r, tphase_first, '|'.join(_phase_begin.phase_defs),
            ha='left', color='k', fontsize='small')

        ax.text(
            270.*d2r, tphase_last, '|'.join(_phase_end.phase_defs),
            ha='left', color='k', fontsize='small')

    description = ('Component {component:s}\n'
                   'Distance {distance:g} km').format(
                   component=component, distance=distance / km)

    if show_description:
        if fmin and fmax:
            description += '\nBandpass {fmin:g} - {fmax:g} Hz'.format(
                fmin=fmin, fmax=fmax)
        elif fmin:
            description += '\nHighpass {fmin:g} Hz'.format(fmin=fmin)
        elif fmax:
            description += '\nLowpass {fmax:g} Hz'.format(fmax=fmax)
        ax.text(
            -.05, -.05, description,
            fontsize='small',
            ha='left', va='bottom', transform=ax.transAxes)

    cbar_label = QUANTITY_LABEL[quantity]
    if envelope:
        cbar_label = 'Envelope ' + cbar_label

    cb = fig.colorbar(
        cmw, ax=ax,
        orientation='vertical', shrink=.8, pad=0.11)

    cb.set_label(cbar_label)

    if axes is None:
        plt.show()
    return resp


__all__ = ['plot_directivity']


if __name__ == '__main__':
    engine = LocalEngine(store_superdirs=['.'], use_config=True)

    rect_source = RectangularSource(
        depth=2.6*km,
        strike=240.,
        dip=76.6,
        rake=-.4,
        anchor='top',

        nucleation_x=-.57,
        nucleation_y=-.59,
        velocity=2070.,

        length=27*km,
        width=9.4*km,
        slip=1.4)

    resp = plot_directivity(
        engine, rect_source, 'crust2_ib',
        dazi=5, component='R', quantity='displacement', envelope=True)
