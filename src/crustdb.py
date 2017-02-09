#!/bin/python
# -*- coding: utf-8 -*-
import numpy as num
import matplotlib.pyplot as plt
import copy
import logging
from os import path
from .guts import Object, String, Float, Int
from .guts_array import Array
from .crustdb_abbr import ageKey, provinceKey, referenceKey, pubYear  # noqa
from .cake import LayeredModel, Material
from .cake_plot import my_model_plot, xscaled, yscaled

logger = logging.getLogger('pyrocko.crustdb')
THICKNESS_HALFSPACE = 2
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


def getCanvas(axes):
    if axes is None:
        fig = plt.figure()
        return fig, fig.gca()
    return axes.figure, axes


class VelocityProfile(Object):
    '''
    Single velocity profile representation from the Global Crustal Database

    https://earthquake.usgs.gov/data/crust/

    .. note ::

        **Citation:**

        W.D. Mooney, G. Laske and G. Masters, CRUST 5.1: A global crustal model
        at 5°x5°. J. Geophys. Res., 103, 727-747, 1998.
    '''
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
        function veloc_at_depth returns a continuous velocity function over
        depth

        :param depth: numpy.ndarray vector of depths
        :type depth: :class:`numpy.ndarray`
        :param phase: P or S wave velocity, ``['p', 's']``
        :type phase: str, optional
        :returns: velocities at requested depth
        :rtype: :py:`numpy.ndarray`
        '''

        if phase not in ['s', 'p']:
            raise AttributeError('Phase has to be either \'p\' or \'s\'.')

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
        fig, ax = getCanvas(axes)
        my_model_plot(self.getLayeredModel(), axes=axes)
        ax.set_title('Global Crustal Database\n'
                     'Velocity Structure at {p.lat:.4f}N, '
                     ' {p.lat:.4f}E (uid {p.uid})'.format(p=self))
        if axes is None:
            plt.show()

    def getLayeredModel(self):

        def iterLines():
            for il, m in enumerate(self.iterLayers):
                yield self.d[il], m, ''

        return LayeredModel.from_scanlines(iterLines())

    def iterLayers(self):
        '''Iterator return a :class:`pyrocko.cake.Material`'''
        for il in xrange(self.nlayers):
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

    def get_weeded(self):
        '''Get layers used in the profile.'''
        weeded = num.zeros((self.nlayers, 4))
        weeded[:, 0] = self.d
        weeded[:, 1] = self.vp
        weeded[:, 2] = self.vs

    def _csv(self):
        output = ''
        for d in xrange(len(self.h)):
            # uid, Lat, Lon, vp, vs, H, Depth, Reference
            output += ('{p.uid}, {p.lat}, {p.lon},'
                       ' {vp}, {vs}, {h}, {d}, {self.reference}').format(
                p=self,
                vp=self.vs[d], vs=self.vp[d], h=self.h[d], d=self.d[d])
        return output


class CrustDB(object):
    '''
    CrustDB  is a container for VelocityProfiles and provides functions for
    spatial selection, querying, processing and visualising data.
    '''

    def __init__(self, database_file=None):
        self.profiles = []
        self._velocity_matrix_cache = {}
        self.data_matrix = None
        self.name = None

        if database_file:
            self._read(database_file)
        else:
            self._read(path.join(path.dirname(__file__),
                                 'data/gsc20130501.txt'))

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
        rstr = "Container contains %d velocity profiles:\n\n" % self.nprofiles
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

    def velocityMatrix(self, drange=(0, 60000.), ddepth=100., phase='p'):
        '''Create a regular sampled velocity matrix

        :param drange: Depth range, ``(dmin, dmax)``,
            defaults to ``(0, 6000.)``
        :type drange: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``,
            defaults to ``p``
        :type phase: str

        :returns:
        :rtype: tuple, (sample_depth, :class:`numpy.ndarray`)
        '''
        dmin, dmax = drange
        uid = '.'.join(map(repr, (dmin, dmax, ddepth, phase)))
        sdepth = num.linspace(dmin, dmax, (dmax - dmin) / ddepth)
        ndepth = sdepth.size

        if uid not in self._velocity_matrix_cache:
            vel_mat = num.empty((self.nprofiles, ndepth))
            for ip, profile in enumerate(self.profiles):
                vel_mat[ip, :] = profile.interpolateProfile(sdepth,
                                                            phase=phase)
            self._velocity_matrix_cache[uid] = num.ma.masked_invalid(vel_mat)

        return sdepth, self._velocity_matrix_cache[uid]

    def rmsRank(self, ref_profile, drange=(0, 3500.), ddepth=100., phase='p'):
        '''Correlates ``ref_profile`` to each profile in the database

        :param ref_profile: Reference profile
        :type ref_profile: :class:`VelocityProfile`
        :param drange: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0, 35000.)``
        :type drange: tuple, optional
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str

        :returns rms: RMS factor length of N_profiles
        :rtype: :class:`numpy.ndarray`
        '''
        if not isinstance(ref_profile, VelocityProfile):
            raise ValueError('ref_profile is not a VelocityProfile')

        sdepth, vel_matrix = self.velocityMatrix(drange, ddepth, phase=phase)
        ref_vel = ref_profile.interpolateProfile(sdepth, phase=phase)

        rms = num.empty(self.nprofiles)
        for p in xrange(self.nprofiles):
            profile = vel_matrix[p, :]
            rms[p] = num.sqrt(profile**2 - ref_vel**2).sum() / ref_vel.size
        return rms

    def histogram2d(self, drange=(0., 60000.), vrange=(5500., 8500.),
                    ddepth=100., dvbin=100., ddbin=2000., phase='p'):
        '''Create a 2D Histogram of all the velocity profiles

        Check :func:`numpy.histogram2d` for more information.

        :param drange: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0., 60000.)``
        :type drange: tuple
        :param vrange: Depth range, ``(vmin, vmax)``,
            defaults to ``(5500., 8500.)``
        :type vrange: tuple
        :param ddepth: Stepping in [km], defaults to ``100.``
        :type ddepth: float
        :param dvbin: Bin size in velocity dimension [m/s], defaults to 100.
        :type dvbin: float
        :param dvbin: Bin size in depth dimension [m], defaults to 2000.
        :type dvbin: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str

        :return: 2D histogram
        :rtype: :class:`numpy.ndarray`
        '''
        sdepth, v_vec = self.velocityMatrix(drange, ddepth, phase=phase)
        v_vec = v_vec.flatten()
        d_vec = num.tile(sdepth, self.nprofiles)

        # Velocity and depth bins
        vbins = int((vrange[1] - vrange[0]) / dvbin)
        dbins = int((drange[1] - drange[0]) / ddbin)

        return num.histogram2d(v_vec, d_vec,
                               range=(vrange, drange),
                               bins=(vbins, dbins),
                               normed=False)

    def meanVelocity(self, drange=(0., 60000.), ddepth=100., phase='p'):
        '''Mean velocity profile plus std variation

        :param drange: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0., 60000.)``
        :type drange: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str

        :returns: depth vector, mean velocities, standard deviations
        :rtype: tuple of :class:`numpy.ndarray`
        '''
        sdepth, v_mat = self.velocityMatrix(drange, ddepth, phase=phase)
        v_mean = num.ma.mean(v_mat, axis=0)
        v_std = num.ma.std(v_mat, axis=0)

        return sdepth, v_mean.flatten(), v_std.flatten()

    def modeVelocity(self, drange=(0., 60000.), ddepth=100., phase='p'):
        '''Mode velocity profile plus std variation

        :param drange: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0., 60000.)``
        :type drange: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str

        :returns: depth vector, mode velocity, number of counts at each depth
        :rtype: tuple of :class:`numpy.ndarray`
        '''
        import scipy.stats

        sdepth, v_mat = self.velocityMatrix(drange, ddepth)
        v_mode, v_counts = scipy.stats.mstats.mode(v_mat, axis=0)
        return sdepth, v_mode.flatten(), v_counts.flatten()

    def medianVelocity(self, drange=(0., 60000.), ddepth=100., phase='p'):
        '''Median velocity profile plus std variation

        :param drange: Depth range in [m], ``(dmin, dmax)``,
            defaults to ``(0., 60000.)``
        :type drange: tuple
        :param ddepth: Stepping in [m], defaults to ``100.``
        :type ddepth: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str

        :returns: depth vector, median velocities, standard deviations
        :rtype: tuple of :class:`numpy.ndarray`
        '''
        sdepth, v_mat = self.velocityMatrix(drange, ddepth, phase=phase)
        v_mean = num.ma.median(v_mat, axis=0)
        v_std = num.ma.std(v_mat, axis=0)

        return sdepth, v_mean.flatten(), v_std.flatten()

    def plotHistogram(self, vrange=(5500., 8500.), bins=6*5, phase='vp',
                      axes=None):
        '''Plot 1D histogram of seismic velocities in the container

        :param vrange: Velocity range, defaults to (5.5, 8.5)
        :type vrange: tuple, optional
        :param bins: bins, defaults to 30 (see :func:`numpy.histogram`)
        :type bins: int, optional
        :param phase: Property to plot out of ``['vp', 'vs']``,
            defaults to 'vp'
        :type phase: str, optional
        :param figure: Figure to plot in, defaults to None
        :type figure: :class:`matplotlib.Figure`, optional
        '''
        fig, ax = getCanvas(axes)

        if phase not in ['vp', 'vs']:
            raise AttributeError('phase has to be either vp or vs')

        data = self._dataMatrix()[phase]

        ax.hist(data, weights=self.data_matrix['h'],
                range=vrange, bins=bins,
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

    def plot(self, drange=(0, 60000.), ddepth=100.,
             ddbin=2000., dvbin=100.,
             vrange=(5500., 8500.), percent=False,
             show_mode=True, show_mean=True, show_median=True,
             show_cbar=True,
             aspect=.02,
             phase='p',
             axes=None):
        ''' Plot a two 2D Histogram of seismic velocities

        :param drange: Depth range, ``(dmin, dmax)``, defaults to ``(0, 60)``
        :type drange: tuple
        :param vrange: Velocity range, ``(vmin, vmax)``
        :type vrange: tuple
        :param ddepth: Stepping in [m], defaults to ``.1``
        :type ddepth: float
        :param dvbin: Bin size in velocity dimension [m/s], defaults to .1
        :type dvbin: float
        :param dvbin: Bin size in depth dimension [m], defaults to 2000.
        :type dvbin: float
        :param phase: Phase to calculate ``p`` or ``s``, defaults to ``p``
        :type phase: str

        :param drange: Min/Max Tuple of depth range to examine
        :param ddepth: Stepping in depth
        :param vrange: Min/Max Tuple of velocity range to examine
        :show_mode: Boolean wheather to plot the Mode
        :show_mean: Boolean wheather to plot the Mean
        '''
        fig, ax = getCanvas(axes)

        ax = fig.gca()

        vmin, vmax = vrange
        dmin, dmax = drange

        vfield, xedg, yedg = self.histogram2d(vrange=vrange, drange=drange,
                                              ddepth=ddepth, dvbin=dvbin,
                                              ddbin=ddbin)
        vfield /= (ddbin / ddepth)

        if percent:
            vfield /= vfield.sum(axis=1)[num.newaxis, :]

        grid_ext = [xedg[0], xedg[-1], yedg[-1], yedg[0]]
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

        if show_mode:
            sdepth, vel_mode, _ = self.modeVelocity(drange=drange,
                                                    ddepth=ddepth)
            ax.plot(vel_mode[sdepth < dmax] + ddepth/2,
                    sdepth[sdepth < dmax],
                    alpha=.8, color='w', label='Mode')

        if show_mean:
            sdepth, vel_mean, _ = self.meanVelocity(drange=drange,
                                                    ddepth=ddepth)
            ax.plot(vel_mean[sdepth < dmax] + ddepth/2,
                    sdepth[sdepth < dmax],
                    alpha=.8, color='w', linestyle='--', label='Mean')

        if show_median:
            sdepth, vel_median, _ = self.medianVelocity(drange=drange,
                                                        ddepth=ddepth)
            ax.plot(vel_median[sdepth < dmax] + ddepth/2,
                    sdepth[sdepth < dmax],
                    alpha=.8, color='w', linestyle=':', label='Median')

        ax.xaxis.set_ticks(num.arange(vmin, vrange[1], .5) + dvbin / 2)
        ax.xaxis.set_ticklabels(num.arange(vmin, vrange[1], .5))
        ax.grid(True, which="both", color="w", linewidth=.8, alpha=.4)

        ax.text(.025, .025, '%d Profiles' % self.nprofiles,
                color='w', alpha=.7,
                transform=ax.transAxes, fontsize=9, va='bottom', ha='left')

        ax.set_title('Crustal Velocity Distribution')
        ax.set_xlabel('%s [km/s]' % vel_labels[phase])
        ax.set_ylabel('Depth [km]')
        xscaled(1./km, ax)
        yscaled(1./km, ax)
        ax.set_xlim(vrange)

        if self.name is not None:
            ax.set_title('%s for %s' % (ax.get_title(), self.name))

        if show_mode or show_mean:
            leg = ax.legend(loc=1, fancybox=True, fontsize=10)
            leg.get_frame().set_alpha(.6)

        if axes is None:
            plt.show()

    def plotVelocitySurf(self, v_max, d_min=0, d_max=60, figure=None):
        '''
        Function triangulates a depth surface at velocity :v_max:

        :param v_max: maximal velocity, type float
        :param dz: depth is sampled in dz steps, type float
        :param d_max: maximum depth, type int
        :param d_min: minimum depth, type int
        :param phase: phase to query for, type string NOT YET IMPLEMENTED!!!
        :param figure: Plot into an existing matplotlib.figure
        '''
        m = self._basemap(figure)

        d = self.exceedVelocity(v_max, d_min, d_max)
        lons = self.lons()[d > 0]
        lats = self.lats()[d > 0]
        d = d[d > 0]

        m.pcolor(lons, lats, d, latlon=True, tri=True,
                 shading='faceted', alpha=1)
        m.colorbar()
        return self._basemapFinish(m, figure)

    def plotMap(self, outfile, **kwargs):
        from . import gmtpy
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
        ''' Returns the last depth ``v_max`` has not been exceeded.

        :param v_max: maximal velocity
        :type vmax: float
        :param dz: depth is sampled in dz steps
        :type dz: float
        :param d_max: maximum depth
        :type d_max: int
        :param d_min: minimum depth
        :type d_min: int

        :return: Lat, Lon, Depth and uid where ``v_max`` is exceeded
        :rtype: list(num.array)
        '''
        self.profile_exceed_velocity = num.empty(len(self.profiles))
        self.profile_exceed_velocity[:] = num.nan

        for _p, profile in enumerate(self.profiles):
            for _i in xrange(len(profile.d)):
                if profile.d[_i] <= d_min\
                        or profile.d[_i] >= d_max:
                    continue
                if profile.vp[_i] < v_max:
                    continue
                else:
                    self.profile_exceed_velocity[_p] = profile.d[_i]
                    break
        return self.profile_exceed_velocity

    def selectRegion(self, west, east, south, north):
        '''
        function select_region selects a region by geographic coordinates

        :param west: west edge of region
        :type west: float
        :param east: east edge of region
        :type east: float
        :param south: south edge of region
        :type south: float
        :param north: north edge of region
        :type north: float

        :returns: All profile keys within desired region
        :rtype: :class:`numpy.ndarray`
        '''
        # Select Region by lat and lon
        #

        r_container = self._emptyCopy()

        for profile in self.profiles:
            if profile.lon >= west and profile.lon <= east \
                    and profile.lat <= north and profile.lat >= south:
                r_container.append(profile)

        return r_container

    def selectPolygon(self, poly):
        '''Select a polygon from the database

        The algorithm is called the _Ray Casting Method_

        :param poly: Latitude Longitude pairs of the polygon
        :type param: list of :class:`numpy.ndarray`

        :return: An new instance of :class:`CrustDB` with selected profiles
        :rtype: self selection:
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
        '''Select profiles at :param lat, lon: within a :param radius:

        :param lat: Latitude in [deg]
        :type lat: float
        :param lon: Longitude in [deg]
        :type lon: float
        :param radius: Radius in [deg]
        :type radius: float

        :return: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            if num.sqrt((lat - profile.lat)**2 +
                        (lon - profile.lon)**2) <= radius:
                r_container.append(profile)

        return r_container

    def selectMinLayers(self, nlayers):
        '''Select profiles with more than ``nlayers``

        :param nlayers: Minimum number of layers
        :type nlayers: int

        :return: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            if profile.nlayers >= nlayers:
                r_container.append(profile)

        return r_container

    def selectMaxLayers(self, nlayers):
        '''
        selects profiles with more than :param nlayers:

        :param nlayers: Maximum number of layers
        :type nlayers: int

        :return: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            if profile.nlayers <= nlayers:
                r_container.append(profile)

        return r_container

    def selectMinDepth(self, depth):
        '''Select profiles describing layers deeper than ``depth``

        :param depth: Minumum depth
        :type depth: float

        :return: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            if profile.d.max() >= depth:
                r_container.append(profile)
        return r_container

    def selectMaxDepth(self, depth):
        '''Select profiles describing layers shallower than ``depth``

        :param depth: Maximum depth
        :type depth: float

        :return: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            if profile.d.max() <= depth:
                r_container.append(profile)
        return r_container

    def selectVp(self):
        '''Select profiles describing P Wave velocity

        :return: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            if not num.all(num.isnan(profile.vp)):
                r_container.append(profile)
        return r_container

    def selectVs(self):
        '''Select profiles describing P Wave velocity

        :return: Selected profiles
        :rtype: :class:`CrustDB`
        '''
        r_container = self._emptyCopy()

        for profile in self.profiles:
            if not num.all(num.isnan(profile.vs)):
                r_container.append(profile)
        return r_container

    def _emptyCopy(self):
        r_container = CrustDB()
        r_container.name = self.name
        return r_container

    def exportCSV(self, filename=None):
        '''Export a CSV file as specified in the header below

        :param filename: Export filename
        :type filename: str
        '''
        with open(filename, 'w') as file:
            file.write('# uid, Lat, Lon, vp, vs, H, Depth, Reference\n')
            for profile in self.profiles:
                file.write(profile._csv())

    def exportYAML(self, filename=None):
        '''Exports a readable file YAML :filename:

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

    def _read(self, database_file):
        '''Reads in the the GSN databasefile and puts it in CrustDB

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
            return [], [], [], [], 0., 0., meta

        def add_record(vp, vs, h, d, lat, lon, meta):
            self.append(VelocityProfile(
                vp=num.array(vp) * km,
                vs=num.array(vs) * km,
                h=num.array(h) * km,
                d=num.array(d) * km,
                lat=lat, lon=lon,
                **meta))

        vp, vs, h, d, lat, lon, meta = get_empty_record()
        rec_line = 0
        with open(database_file, 'r') as database:
            for line, dbline in enumerate(database.readlines()):
                if dbline.isspace():
                    if not len(d) == 0:
                        add_record(vp, vs, h, d, lat, lon, meta)
                    if not len(vp) == len(h):
                        raise DatabaseError(
                            'Inconsistent database, check line %d!\n\tDebug: '
                            % line, lat, lon, vp, vs, h, d, meta)

                    vp, vs, h, d, lat, lon, meta = get_empty_record()
                    rec_line = 0
                else:
                    try:
                        if rec_line == 0:
                            lat = float(dbline[8:13])
                            if dbline[13] == "S":
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
                        if rec_line == 1:
                            lon = float(dbline[7:13])
                            if dbline[13] == "W":
                                lon = -lon
                            # Additional meta data
                            meta['geological_age'] = dbline[54:58].strip()
                            meta['publication_reference'] =\
                                dbline[66:72].strip()
                            meta['geological_province'] = dbline[74:78].strip()
                        try:
                            vp.append(float(dbline[17:21]))
                            vs.append(float(dbline[23:27]))
                            h.append(float(dbline[28:34]))
                            d.append(float(dbline[35:41]))
                        except ValueError:
                            pass
                    except ValueError:
                        logger.warning(
                            'Could not interpret line %d, skipping\n%s' %
                            (line, dbline))
                        while not database.readlines():
                            pass
                        vp, vs, h, d, lat, lon, meta = get_empty_record()
                    rec_line += 1
            # Append last profile
            add_record(vp, vs, h, d, lat, lon, meta)
            logger.info('Loaded %d profiles from Global Crustal Database' %
                        self.nprofiles)
