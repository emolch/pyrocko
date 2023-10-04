# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
'''
Access to the `USGS Global Crustal Database
<https://earthquake.usgs.gov/data/crust>`_.

The USGS Global Crustal Database provides empirical velocity measurements of
the earth for statistical analysis.

.. rubric:: Citation

Mooney, W. D., Laske, G., & Masters, T. G. (1998). CRUST 5.1: A global crustal
model at 5x5. Journal of Geophysical Research: Solid Earth, 103(B1), 727-747.

'''

import numpy as num
import copy
import logging
from os import path

from pyrocko.guts import Object, String, Float, Int
from pyrocko.guts_array import Array

from pyrocko.cake import LayeredModel, Material
from pyrocko.plot.cake_plot import my_model_plot, xscaled, yscaled

from .crustdb_abbr import ageKey, provinceKey, referenceKey, pubYear  # noqa

logger = logging.getLogger('pyrocko.dataset.crustdb')
THICKNESS_HALFSPACE = 2

db_url = 'https://mirror.pyrocko.org/gsc20130501.txt'
km = 1e3
vel_labels = {
    'vp': '$V_P$',
    'p': '$V_P$',
    'vs': '$V_S$',
    's': '$V_S$',
}


class DatabaseError(Exception):
    pass


class ProfileEmpty(Exception):
    pass


def _getCanvas(axes):

    import matplotlib.pyplot as plt

    if axes is None:
        fig = plt.figure()
        return fig, fig.gca()
    return axes.figure, axes


def xoffset_scale(offset, scale, ax):
    from matplotlib.ticker import ScalarFormatter, AutoLocator

    class FormatVelocities(ScalarFormatter):
        @staticmethod
        def __call__(value, pos):
            return u'%.1f' % ((value-offset) * scale)

    class OffsetLocator(AutoLocator):
        def tick_values(self, vmin, vmax):
            return [v + offset for v in
                    AutoLocator.tick_values(self, vmin, vmax)]

    ax.get_xaxis().set_major_formatter(FormatVelocities())
    ax.get_xaxis().set_major_locator(OffsetLocator())


class VelocityProfile(Object):
    uid = Int.T(
        optional=True,
        help='Unique ID of measurement')

    lat = Float.T(
        help='Latitude [deg]')
    lon = Float.T(
        help='Longitude [deg]')
    elevation = Float.T(
        default=num.nan,
        help='Elevation [m]')
    vp = Array.T(
        shape=(None, 1),
        help='P Wave velocities [m/s]')
    vs = Array.T(
        shape=(None, 1),
        help='S Wave velocities [m/s]')
    d = Array.T(
        shape=(None, 1),
        help='Interface depth, top [m]')
    h = Array.T(
        shape=(None, 1),
        help='Interface thickness [m]')

    heatflow = Float.T(
        optional=True,
        help='Heatflow [W/m^2]')
    geographical_location = String.T(
        optional=True,
        help='Geographic Location')
    geological_province = String.T(
        optional=True,
        help='Geological Province')
    geological_age = String.T(
        optional=True,
        help='Geological Age')
    measurement_method = Int.T(
        optional=True,
        help='Measurement method')
    publication_reference = String.T(
        optional=True,
        help='Publication Reference')
    publication_year__ = Int.T(
        help='Publication Date')

    def __init__(self, *args, **kwargs):
        Object.__init__(self, *args, **kwargs)

        self.h = num.abs(self.d - num.roll(self.d, -1))
        self.h[-1] = 0
        self.nlayers = self.h.size

        self.geographical_location = '%s (%s)' % (
            provinceKey(self.geographical_location),
            self.geographical_location)

        self.vs[self.vs == 0] = num.nan
        self.vp[self.vp == 0] = num.nan

        self._step_vp = num.repeat(self.vp, 2)
        self._step_vs = num.repeat(self.vs, 2)
        self._step_d = num.roll(num.repeat(self.d, 2), -1)
        self._step_d[-1] = self._step_d[-2] + THICKNESS_HALFSPACE

    @property
    def publication_year__(self):
        return pubYear(self.publication_reference)

    def interpolateProfile(self, depths, phase='p', stepped=True):
        '''
        Get a continuous velocity function at arbitrary depth.

        :param depth: Depths to interpolate
        :type depth: :class:`numpy.ndarray`
        :param phase: P or S wave velocity, **p** or **s**
        :type phase: str
        :param stepped: Use a stepped velocity function or gradient
        :type stepped: bool
        :returns: velocities at requested depths
        :rtype: :class:`numpy.ndarray`
        '''

        if phase not in ['s', 'p']:
            raise AttributeError("Phase has to be either 'p' or 's'.")

        if phase == 'p':
            vel = self._step_vp if stepped else self.vp
        elif phase == 's':
            vel = self._step_vs if stepped else self.vs
        d = self._step_d if stepped else self.d

        if vel.size == 0:
            raise ProfileEmpty('Phase %s does not contain velocities' % phase)

        try:
            res = num.interp(depths, d, vel,
                             left=num.nan, right=num.nan)
        except ValueError:
            raise ValueError('Could not interpolate velocity profile.')

        return res

    def plot(self, axes=None):
        '''
        Plot the velocity profile, see :class:`pyrocko.cake`.

        :param axes: Axes to plot into.
        :type axes: :class:`matplotlib.axes.Axes`
        '''

        import matplotlib.pyplot as plt

        fig, ax = _getCanvas(axes)
        my_model_plot(self.getLayeredModel(), axes=axes)
        ax.set_title('Global Crustal Database\n'
                     'Velocity Structure at {p.lat:.4f}N, '
                     ' {p.lat:.4f}E (uid {p.uid})'.format(p=self))
        if axes is None:
            plt.show()

    def getLayeredModel(self):
        '''
        Get a layered model, see :class:`pyrocko.cake.LayeredModel`.
        '''
        def iterLines():
            for il, m in enumerate(self.iterLayers()):
                yield self.d[il], m, ''

        return LayeredModel.from_scanlines(iterLines())

    def iterLayers(self):
        '''
        Iterator yielding a :class:`pyrocko.cake.Material` for each layer.
        '''
        for il in range(self.nlayers):
            yield Material(vp=self.vp[il],
                           vs=self.vs[il])

    @property
    def geog_loc_long(self):
        return provinceKey(self.geog_loc)

    @property
    def geol_age_long(self):
        return ageKey(self.geol_age)

    @property
    def has_s(self):
        return num.any(self.vp)

    @property
    def has_p(self):
        return num.any(self.vs)

    def _csv(self):
        output = ''
        for d in range(len(self.h)):
            output += (
                    '{p.uid}, {p.lat}, {p.lon},'
                    ' {vp}, {vs}, {h}, {d}, {p.publication_reference}\n'
            ).format(
                p=self,
                vp=self.vp[d], vs=self.vs[d], h=self.h[d], d=self.d[d])
        return output


class CrustDB(object):
    '''
    CrustDB is a container for :class:`VelocityProfile` and provides
    functions for spatial selection, querying, processing and visualising
    data from the Global Crustal Database.
    '''

    def __init__(self, database_file=None, parent=None):
        self.profiles = []
        self._velocity_matrix_cache = {}
        self.data_matrix = None
        self.name = None
        self.database_file = database_file

        if parent is not None:
            pass
        elif database_file is not None:
            self._read(database_file)
        else:
            self._read(self._getRepositoryDatabase())

    def __len__(self):
        return len(self.profiles)

    def __setitem__(self, key, value):
        if not isinstance(value, VelocityProfile):
            raise TypeError('Element is not a VelocityProfile')
        self.profiles[key] = value

    def __delitem__(self, key):
        self.profiles.remove(key)

    def __getitem__(self, key):
        return self.profiles[key]

    def __str__(self):
        rstr = 'Container contains %d velocity profiles:\n\n' % self.nprofiles
        return rstr

    @property
    def nprofiles(self):
        return len(self.profiles)

    def append(self, value):
        if not isinstance(value, VelocityProfile):
            raise TypeError('Element is not a VelocityProfile')
        self.profiles.append(value)

    def copy(self):
        return copy.deepcopy(self)

    def lats(self):
        return num.array(
            [p.lat for p in self.profiles])

    def lons(self):
        return num.array(
            [p.lon for p in self.profiles])

    def _dataMatrix(self):
        if self.data_matrix is not None:
            return self.data_matrix

        self.data_matrix = num.core.records.fromarrays(
            num.vstack([
                num.concatenate([p.vp for p in self.profiles]),
                num.concatenate([p.vs for p in self.profiles]),
                num.concatenate([p.h for p in self.profiles]),
                num.concatenate([p.d for p in self.profiles])
            ]),
            names='vp, vs, h, d')
        return self.data_matrix

    def velocityMatrix(self, depth_range=(0, 60000.), ddepth=100., phase='p'):
        '''
        Create a regular sampled velocity matrix.

        :param depth_range: Depth range, ``(dmin, dmax)``,
            defaults to ``(0, 6000.)``
        :type depth_range: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``,
            defaults to ``p``
        :type phase: str
        :returns: Sample depths, veloctiy matrix
        :rtype: tuple, (sample_depth, :class:`numpy.ndarray`)
        '''
        dmin, dmax = depth_range
        uid = '.'.join(map(repr, (dmin, dmax, ddepth, phase)))
        sdepth = num.linspace(dmin, dmax, int((dmax - dmin) / ddepth))
        ndepth = sdepth.size

        if uid not in self._velocity_matrix_cache:
            vel_mat = num.empty((self.nprofiles, ndepth))
            for ip, profile in enumerate(self.profiles):
                vel_mat[ip, :] = profile.interpolateProfile(sdepth,
                                                            phase=phase)
            self._velocity_matrix_cache[uid] = num.ma.masked_invalid(vel_mat)

        return sdepth, self._velocity_matrix_cache[uid]

    def rmsRank(self, ref_profile, depth_range=(0, 3500.), ddepth=100.,
                phase='p'):
        '''
        Correlates ``ref_profile`` to each profile in the database.

        :param ref_profile: Reference profile
        :type ref_profile: :class:`VelocityProfile`
        :param depth_range: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0, 35000.)``
        :type depth_range: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str
        :returns: RMS factor length of N_profiles
        :rtype: :class:`numpy.ndarray`
        '''
        if not isinstance(ref_profile, VelocityProfile):
            raise ValueError('ref_profile is not a VelocityProfile')

        sdepth, vel_matrix = self.velocityMatrix(depth_range, ddepth,
                                                 phase=phase)
        ref_vel = ref_profile.interpolateProfile(sdepth, phase=phase)

        rms = num.empty(self.nprofiles)
        for p in range(self.nprofiles):
            profile = vel_matrix[p, :]
            rms[p] = num.sqrt(profile**2 - ref_vel**2).sum() / ref_vel.size
        return rms

    def histogram2d(self, depth_range=(0., 60000.), vel_range=None,
                    ddepth=100., dvbin=100., ddbin=2000., phase='p'):
        '''
        Create a 2D Histogram of all the velocity profiles.

        Check :func:`numpy.histogram2d` for more information.

        :param depth_range: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0., 60000.)``
        :type depth_range: tuple
        :param vel_range: Depth range, ``(vmin, vmax)``,
            defaults to ``(5500., 8500.)``
        :type vel_range: tuple
        :param ddepth: Stepping in [km], defaults to ``100.``
        :type ddepth: float
        :param dvbin: Bin size in velocity dimension [m/s], defaults to 100.
        :type dvbin: float
        :param dvbin: Bin size in depth dimension [m], defaults to 2000.
        :type dvbin: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str

        :returns: :func:`numpy.histogram2d`
        :rtype: tuple
        '''
        sdepth, v_mat = self.velocityMatrix(depth_range, ddepth, phase=phase)
        d_vec = num.tile(sdepth, self.nprofiles)

        # Velocity and depth bins
        if vel_range is None:
            vel_range = ((v_mat.min() // 1e2) * 1e2,
                         (v_mat.max() // 1e2) * 1e2)
        nvbins = int((vel_range[1] - vel_range[0]) / dvbin)
        ndbins = int((depth_range[1] - depth_range[0]) / ddbin)

        return num.histogram2d(v_mat.flatten(), d_vec,
                               range=(vel_range, depth_range),
                               bins=[nvbins, ndbins],
                               density=False)

    def meanVelocity(self, depth_range=(0., 60000.), ddepth=100., phase='p'):
        '''
        Get mean and standard deviation of velocity profile.

        :param depth_range: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0., 60000.)``
        :type depth_range: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str
        :returns: depth vector, mean velocities, standard deviations
        :rtype: :py:class:`tuple` of :class:`numpy.ndarray`
        '''
        sdepth, v_mat = self.velocityMatrix(depth_range, ddepth, phase=phase)
        v_mean = num.ma.mean(v_mat, axis=0)
        v_std = num.ma.std(v_mat, axis=0)

        return sdepth, v_mean.flatten(), v_std.flatten()

    def modeVelocity(self, depth_range=(0., 60000.), ddepth=100., phase='p'):
        '''
        Get mode velocity profile and standard deviation.

        :param depth_range: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0., 60000.)``
        :type depth_range: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str
        :returns: depth vector, mode velocity, number of counts at each depth
        :rtype: :py:class:`tuple` of :class:`numpy.ndarray`
        '''
        import scipy.stats

        sdepth, v_mat = self.velocityMatrix(depth_range, ddepth, phase=phase)
        v_mode, v_counts = scipy.stats.mstats.mode(v_mat, axis=0)
        return sdepth, v_mode.flatten(), v_counts.flatten()

    def medianVelocity(self, depth_range=(0., 60000.), ddepth=100., phase='p'):
        '''
        Median velocity profile plus std variation.

        :param depth_range: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0., 60000.)``
        :type depth_range: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str
        :returns: depth vector, median velocities, standard deviations
        :rtype: :py:class:`tuple` of :class:`numpy.ndarray`
        '''
        sdepth, v_mat = self.velocityMatrix(depth_range, ddepth, phase=phase)
        v_mean = num.ma.median(v_mat, axis=0)
        v_std = num.ma.std(v_mat, axis=0)

        return sdepth, v_mean.flatten(), v_std.flatten()

    def plotHistogram(self, vel_range=None, bins=36, phase='vp',
                      axes=None):
        '''
        Plot 1D histogram of seismic velocities in the container.

        :param vel_range: Velocity range, defaults to (5.5, 8.5)
        :type vel_range: tuple
        :param bins: bins, defaults to 30 (see :func:`numpy.histogram`)
        :type bins: int
        :param phase: Property to plot out of ``['vp', 'vs']``,
            defaults to 'vp'
        :type phase: str
        :param figure: Figure to plot in, defaults to None
        :type figure: :class:`matplotlib.figure.Figure`
        '''

        import matplotlib.pyplot as plt

        fig, ax = _getCanvas(axes)

        if phase not in ['vp', 'vs']:
            raise AttributeError('phase has to be either vp or vs')

        data = self._dataMatrix()[phase]

        ax.hist(data, weights=self.data_matrix['h'],
                range=vel_range, bins=bins,
                color='g', alpha=.5)
        ax.text(.95, .95, '%d Profiles' % self.nprofiles,
                transform=ax.transAxes, fontsize=10,
                va='top', ha='right', alpha=.7)

        ax.set_title('Distribution of %s' % vel_labels[phase])
        ax.set_xlabel('%s [km/s]' % vel_labels[phase])
        ax.set_ylabel('Cumulative occurrence [N]')
        xscaled(1./km, ax)
        ax.yaxis.grid(alpha=.4)

        if self.name is not None:
            ax.set_title('%s for %s' % (ax.get_title(), self.name))

        if axes is None:
            plt.show()

    def plot(self, depth_range=(0, 60000.), ddepth=100., ddbin=2000.,
             vel_range=None, dvbin=100.,
             percent=False,
             plot_mode=True, plot_median=True, plot_mean=False,
             show_cbar=True,
             aspect=.02,
             phase='p',
             axes=None):
        '''
        Plot a two 2D Histogram of seismic velocities.

        :param depth_range: Depth range, ``(dmin, dmax)``,
            defaults to ``(0, 60)``
        :type depth_range: tuple
        :param vel_range: Velocity range, ``(vmin, vmax)``
        :type vel_range: tuple
        :param ddepth: Stepping in [m], defaults to ``.1``
        :type ddepth: float
        :param dvbin: Bin size in velocity dimension [m/s], defaults to .1
        :type dvbin: float
        :param dvbin: Bin size in depth dimension [m], defaults to 2000.
        :type dvbin: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str
        :param plot_mode: Plot the Mode
        :type plot_mode: bool
        :param plot_mean: Plot the Mean
        :type plot_mean: bool
        :param plot_median: Plot the Median
        :type plot_median: bool
        :param axes: Axes to plot into, defaults to None
        :type axes: :class:`matplotlib.axes.Axes`
        '''

        import matplotlib.pyplot as plt

        fig, ax = _getCanvas(axes)

        ax = fig.gca()

        if vel_range is not None:
            vmin, vmax = vel_range
        dmin, dmax = depth_range

        vfield, vedg, dedg = self.histogram2d(vel_range=vel_range,
                                              depth_range=depth_range,
                                              ddepth=ddepth, dvbin=dvbin,
                                              ddbin=ddbin, phase=phase)
        vfield /= (ddbin / ddepth)

        if percent:
            vfield /= vfield.sum(axis=1)[num.newaxis, :]

        grid_ext = [vedg[0], vedg[-1], dedg[-1], dedg[0]]
        histogram = ax.imshow(vfield.swapaxes(0, 1),
                              interpolation='nearest',
                              extent=grid_ext, aspect=aspect)

        if show_cbar:
            cticks = num.unique(
                num.arange(0, vfield.max(), vfield.max() // 10).round())
            cbar = fig.colorbar(histogram, ticks=cticks, format='%1i',
                                orientation='horizontal')
            if percent:
                cbar.set_label('Percent')
            else:
                cbar.set_label('Number of Profiles')

        if plot_mode:
            sdepth, vel_mode, _ = self.modeVelocity(depth_range=depth_range,
                                                    ddepth=ddepth, phase=phase)
            ax.plot(vel_mode[sdepth < dmax] + ddepth/2,
                    sdepth[sdepth < dmax],
                    alpha=.8, color='w', label='Mode')

        if plot_mean:
            sdepth, vel_mean, _ = self.meanVelocity(depth_range=depth_range,
                                                    ddepth=ddepth, phase=phase)
            ax.plot(vel_mean[sdepth < dmax] + ddepth/2,
                    sdepth[sdepth < dmax],
                    alpha=.8, color='w', linestyle='--', label='Mean')

        if plot_median:
            sdepth, vel_median, _ = self.medianVelocity(
                                        depth_range=depth_range,
                                        ddepth=ddepth, phase=phase)
            ax.plot(vel_median[sdepth < dmax] + ddepth/2,
                    sdepth[sdepth < dmax],
                    alpha=.8, color='w', linestyle=':', label='Median')

        ax.grid(True, which='both', color='w', linewidth=.8, alpha=.4)

        ax.text(.025, .025, '%d Profiles' % self.nprofiles,
                color='w', alpha=.7,
                transform=ax.transAxes, fontsize=9, va='bottom', ha='left')

        ax.set_title('Crustal Velocity Distribution')
        ax.set_xlabel('%s [km/s]' % vel_labels[phase])
        ax.set_ylabel('Depth [km]')
        yscaled(1./km, ax)
        xoffset_scale(dvbin/2, 1./km, ax)
        ax.set_xlim(vel_range)

        if self.name is not None:
            ax.set_title('%s for %s' % (ax.get_title(), self.name))

        if plot_mode or plot_mean or plot_median:
            leg = ax.legend(loc=1, fancybox=True, prop={'size': 10.})
            leg.get_frame().set_alpha(.6)

        if axes is None:
            plt.show()

    def plotVelocitySurface(self, v_max, d_min=0., d_max=6000., axes=None):
        '''
        Plot a triangulated a depth surface exceeding velocity.
        '''

        import matplotlib.pyplot as plt

        fig, ax = _getCanvas(axes)
        d = self.exceedVelocity(v_max, d_min, d_max)
        lons = self.lons()[d > 0]
        lats = self.lats()[d > 0]
        d = d[d > 0]

        ax.tricontourf(lats, lons, d)

        if axes is None:
            plt.show()

    def plotMap(self, outfile, **kwargs):
        from pyrocko.plot import gmtpy
        lats = self.lats()
        lons = self.lons()
        s, n, w, e = (lats.min(), lats.max(), lons.min(), lons.max())

        def darken(c, f=0.7):
            return (c[0]*f, c[1]*f, c[2]*f)

        gmt = gmtpy.GMT()
        gmt.psbasemap(B='40/20',
                      J='M0/12',
                      R='%f/%f/%f/%f' % (w, e, s, n))
        gmt.pscoast(R=True, J=True,
                    D='i', S='216/242/254', A=10000,
                    W='.2p')
        gmt.psxy(R=True, J=True,
                 in_columns=[lons, lats],
                 S='c2p', G='black')
        gmt.save(outfile)

    def exceedVelocity(self, v_max, d_min=0, d_max=60):
        '''
        Returns the last depth ``v_max`` has not been exceeded.

        :param v_max: maximal velocity
        :type vmax: float
        :param dz: depth is sampled in dz steps
        :type dz: float
        :param d_max: maximum depth
        :type d_max: int
        :param d_min: minimum depth
        :type d_min: int
        :returns: Lat, Lon, Depth and uid where ``v_max`` is exceeded
        :rtype: :py:class:`list` of :py:class:`numpy.ndarray`
        '''
        self.profile_exceed_velocity = num.empty(len(self.profiles))
        self.profile_exceed_velocity[:] = num.nan

        for ip, profile in enumerate(self.profiles):
            for il in range(len(profile.d)):
                if profile.d[il] <= d_min\
                        or profile.d[il] >= d_max:
                    continue
                if profile.vp[il] < v_max:
                    continue
                else:
                    self.profile_exceed_velocity[ip] = profile.d[il]
                    break
        return self.profile_exceed_velocity

    def selectRegion(self, west, east, south, north):
        '''
        Select profiles within a region by geographic corner coordinates.

        :param west: west corner
        :type west: float
        :param east: east corner
        :type east: float
        :param south: south corner
        :type south: float
        :param north: north corner
        :type north: float
        :returns: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            if profile.lon >= west and profile.lon <= east \
                    and profile.lat <= north and profile.lat >= south:
                r_container.append(profile)

        return r_container

    def selectPolygon(self, poly):
        '''
        Select profiles within a polygon.

        The algorithm is called the **Ray Casting Method**

        :param poly: Latitude Longitude pairs of the polygon
        :type param: list of :class:`numpy.ndarray`
        :returns: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            x = profile.lon
            y = profile.lat

            inside = False
            p1x, p1y = poly[0]
            for p2x, p2y in poly:
                if y >= min(p1y, p2y):
                    if y <= max(p1y, p2y):
                        if x <= max(p1x, p2x):
                            if p1y != p2y:
                                xints = (y - p1y) * (p2x - p1x) / \
                                    (p2y - p1y) + p1x
                            if p1x == p2x or x <= xints:
                                inside = not inside
                p1x, p1y = p2x, p2y
            if inside:
                r_container.append(profile)

        return r_container

    def selectLocation(self, lat, lon, radius=10):
        '''
        Select profiles at a geographic location within a ``radius``.

        :param lat: Latitude in [deg]
        :type lat: float
        :param lon: Longitude in [deg]
        :type lon: float
        :param radius: Radius in [deg]
        :type radius: float
        :returns: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()
        logger.info('Selecting location %f, %f (r=%f)...' % (lat, lon, radius))
        for profile in self.profiles:
            if num.sqrt((lat - profile.lat)**2 +
                        (lon - profile.lon)**2) <= radius:
                r_container.append(profile)

        return r_container

    def selectMinLayers(self, nlayers):
        '''
        Select profiles with more than ``nlayers``.

        :param nlayers: Minimum number of layers
        :type nlayers: int
        :returns: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()
        logger.info('Selecting minimum %d layers...' % nlayers)

        for profile in self.profiles:
            if profile.nlayers >= nlayers:
                r_container.append(profile)

        return r_container

    def selectMaxLayers(self, nlayers):
        '''
        Select profiles with more than ``nlayers``.

        :param nlayers: Maximum number of layers
        :type nlayers: int
        :returns: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()
        logger.info('Selecting maximum %d layers...' % nlayers)

        for profile in self.profiles:
            if profile.nlayers <= nlayers:
                r_container.append(profile)

        return r_container

    def selectMinDepth(self, depth):
        '''
        Select profiles describing layers deeper than ``depth``.

        :param depth: Minumum depth in [m]
        :type depth: float
        :returns: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()
        logger.info('Selecting minimum depth %f m...' % depth)

        for profile in self.profiles:
            if profile.d.max() >= depth:
                r_container.append(profile)
        return r_container

    def selectMaxDepth(self, depth):
        '''
        Select profiles describing layers shallower than ``depth``.

        :param depth: Maximum depth in [m]
        :type depth: float
        :returns: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()
        logger.info('Selecting maximum depth %f m...' % depth)

        for profile in self.profiles:
            if profile.d.max() <= depth:
                r_container.append(profile)
        return r_container

    def selectVp(self):
        '''
        Select profiles describing P wave velocity.

        :returns Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()
        logger.info('Selecting profiles providing Vp...')

        for profile in self.profiles:
            if not num.all(num.isnan(profile.vp)):
                r_container.append(profile)
        return r_container

    def selectVs(self):
        '''
        Select profiles describing P wave velocity.

        :returns: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()
        logger.info('Selecting profiles providing Vs...')

        for profile in self.profiles:
            if not num.all(num.isnan(profile.vs)):
                r_container.append(profile)
        return r_container

    def _emptyCopy(self):
        r_container = CrustDB(parent=self)
        r_container.name = self.name
        return r_container

    def exportCSV(self, filename=None):
        '''
        Export as CSV file.

        :param filename: Export filename
        :type filename: str
        '''
        with open(filename, 'w') as file:
            file.write('# uid, Lat, Lon, vp, vs, H, Depth, Reference\n')
            for profile in self.profiles:
                file.write(profile._csv())

    def exportYAML(self, filename=None):
        '''
        Export as YAML file.

        :param filename: Export filename
        :type filename: str
        '''
        with open(filename, 'w') as file:
            for profile in self.profiles:
                file.write(profile.__str__())

    @classmethod
    def readDatabase(cls, database_file):
        db = cls()
        CrustDB._read(db, database_file)
        return db

    @staticmethod
    def _getRepositoryDatabase():
        from pyrocko import config

        name = path.basename(db_url)
        data_path = path.join(config.config().crustdb_dir, name)
        if not path.exists(data_path):
            from pyrocko import util
            util.download_file(db_url, data_path, None, None)

        return data_path

    def _read(self, database_file):
        '''
        Reads in the the GSN database file and puts it in CrustDB.

        File format:

   uid  lat/lon  vp    vs    hc     depth
    2   29.76N   2.30   .00   2.00    .00  s  25.70   .10    .00  NAC-CO   5 U
        96.31W   3.94   .00   5.30   2.00  s  33.00   MCz  39.00  61C.3    EXC
                 5.38   .00  12.50   7.30  c
                 6.92   .00  13.20  19.80  c
                 8.18   .00    .00  33.00  m

    3   34.35N   3.00   .00   3.00    .00  s  35.00  1.60    .00  NAC-BR   4 R
       117.83W   6.30   .00  16.50   3.00     38.00   MCz  55.00  63R.1    ORO
                 7.00   .00  18.50  19.50
                 7.80   .00    .00  38.00  m


        :param database_file: path to database file, type string

        '''

        def get_empty_record():
            meta = {
                'uid': num.nan,
                'geographical_location': None,
                'geological_province': None,
                'geological_age': None,
                'elevation': num.nan,
                'heatflow': num.nan,
                'measurement_method': None,
                'publication_reference': None
            }
            # vp, vs, h, d, lat, lon, meta
            return (num.zeros(128, dtype=num.float32),
                    num.zeros(128, dtype=num.float32),
                    num.zeros(128, dtype=num.float32),
                    num.zeros(128, dtype=num.float32),
                    0., 0., meta)

        nlayers = []

        def add_record(vp, vs, h, d, lat, lon, meta, nlayer):
            if nlayer == 0:
                return
            self.append(VelocityProfile(
                vp=vp[:nlayer] * km,
                vs=vs[:nlayer] * km,
                h=h[:nlayer] * km,
                d=d[:nlayer] * km,
                lat=lat, lon=lon,
                **meta))
            nlayers.append(nlayer)

        vp, vs, h, d, lat, lon, meta = get_empty_record()
        ilayer = 0
        with open(database_file, 'r') as database:
            for line, dbline in enumerate(database):
                if dbline.isspace():
                    if not len(d) == 0:
                        add_record(vp, vs, h, d, lat, lon, meta, ilayer)
                    if not len(vp) == len(h):
                        raise DatabaseError(
                            'Inconsistent database, check line %d!\n\tDebug: '
                            % line, lat, lon, vp, vs, h, d, meta)

                    vp, vs, h, d, lat, lon, meta = get_empty_record()
                    ilayer = 0
                else:
                    try:
                        if ilayer == 0:
                            lat = float(dbline[8:13])
                            if dbline[13] == b'S':
                                lat = -lat
                            # Additional meta data
                            meta['uid'] = int(dbline[0:6])
                            meta['elevation'] = float(dbline[52:57])
                            meta['heatflow'] = float(dbline[58:64])
                            if meta['heatflow'] == 0.:
                                meta['heatflow'] = None
                            meta['geographical_location'] =\
                                dbline[66:72].strip()
                            meta['measurement_method'] = dbline[77]
                        if ilayer == 1:
                            lon = float(dbline[7:13])
                            if dbline[13] == b'W':
                                lon = -lon
                            # Additional meta data
                            meta['geological_age'] = dbline[54:58].strip()
                            meta['publication_reference'] =\
                                dbline[66:72].strip()
                            meta['geological_province'] = dbline[74:78].strip()
                        try:
                            vp[ilayer] = dbline[17:21]
                            vs[ilayer] = dbline[23:27]
                            h[ilayer] = dbline[28:34]
                            d[ilayer] = dbline[35:41]
                        except ValueError:
                            pass
                    except ValueError:
                        logger.warning(
                            'Could not interpret line %d, skipping\n%s' %
                            (line, dbline))
                        while not database.readlines():
                            pass
                        vp, vs, h, d, lat, lon, meta = get_empty_record()
                    ilayer += 1
            # Append last profile
            add_record(vp, vs, h, d, lat, lon, meta, ilayer)
            logger.info('Loaded %d profiles from %s' %
                        (self.nprofiles, database_file))
