# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Synthetic InSAR data generator.
'''

import numpy as num
import logging
from os import path as op

from datetime import datetime
from pyrocko import gf, util
from pyrocko import orthodrome as od
from pyrocko.guts import Float, Timestamp, Tuple, StringChoice, Bool, Object,\
    String
from pyrocko.util import num_full

from .base import TargetGenerator, NoiseGenerator
from ..base import get_gsshg

DEFAULT_STORE_ID = 'ak135_static'

km = 1e3
d2r = num.pi/180.

logger = logging.getLogger('pyrocko.scenario.targets.insar')
guts_prefix = 'pf.scenario'


class ScenePatch(Object):
    center_lat = Float.T(
        help='Center latitude anchor.')
    center_lon = Float.T(
        help='center longitude anchor.')
    time_master = Timestamp.T(
        help='Timestamp of the master.')
    time_slave = Timestamp.T(
        help='Timestamp of the slave.')
    inclination = Float.T(
        help='Orbital inclination towards the equatorial plane [deg].')
    apogee = Float.T(
        help='Apogee of the satellite in [m].')
    swath_width = Float.T(
        help='Swath width in [m].')
    track_length = Float.T(
        help='Track length in [m].')
    incident_angle = Float.T(
        help='Ground incident angle in [deg].')
    resolution = Tuple.T(
        help='Resolution of raster in east x north [px].')
    orbital_node = StringChoice.T(
        ['Ascending', 'Descending'],
        help='Orbit heading.')
    mask_water = Bool.T(
        default=True,
        help='Mask water bodies.')

    class SatelliteGeneratorTarget(gf.SatelliteTarget):

        def __init__(self, scene_patch, *args, **kwargs):
            gf.SatelliteTarget.__init__(self, *args, **kwargs)

            self.scene_patch = scene_patch

        def post_process(self, *args, **kwargs):
            resp = gf.SatelliteTarget.post_process(self, *args, **kwargs)

            from kite import Scene
            from kite.scene import SceneConfig, FrameConfig, Meta

            patch = self.scene_patch

            grid, _ = patch.get_grid()

            displacement = num.empty_like(grid)
            displacement.fill(num.nan)
            displacement[patch.get_mask()] = resp.result['displacement.los']

            theta, phi = patch.get_incident_angles()

            llLat, llLon = patch.get_ll_anchor()
            urLat, urLon = patch.get_ur_anchor()
            dLon = num.abs(llLon - urLon) / patch.resolution[0]
            dLat = num.abs(llLat - urLat) / patch.resolution[1]

            scene_config = SceneConfig(
                meta=Meta(
                    scene_title='Pyrocko Scenario Generator - {orbit} ({time})'
                                .format(orbit=self.scene_patch.orbital_node,
                                        time=datetime.now()),
                    orbital_node=patch.orbital_node,
                    scene_id='pyrocko_scenario_%s'
                             % self.scene_patch.orbital_node,
                    satellite_name='Sentinel-1 (pyrocko-scenario)'),
                frame=FrameConfig(
                    llLat=float(llLat),
                    llLon=float(llLon),
                    dN=float(dLat),
                    dE=float(dLon),
                    spacing='degree'))

            scene = Scene(
                displacement=displacement,
                theta=theta,
                phi=phi,
                config=scene_config)

            resp.scene = scene

            return resp

    def __init__(self, *args, **kwargs):
        Object.__init__(self, *args, **kwargs)
        self._mask_water = None

    @property
    def width(self):
        track_shift = num.abs(
            num.cos(self.inclination*d2r) * self.track_length)

        return self.swath_width + track_shift

    def get_ll_anchor(self):
        return od.ne_to_latlon(self.center_lat, self.center_lon,
                               -self.track_length/2, -self.width/2)

    def get_ur_anchor(self):
        return od.ne_to_latlon(self.center_lat, self.center_lon,
                               self.track_length/2, self.width/2)

    def get_ul_anchor(self):
        return od.ne_to_latlon(self.center_lat, self.center_lon,
                               self.track_length/2, -self.width/2)

    def get_lr_anchor(self):
        return od.ne_to_latlon(self.center_lat, self.center_lon,
                               -self.track_length/2, self.width/2)

    def get_corner_coordinates(self):
        inc = self.inclination

        llLat, llLon = self.get_ll_anchor()
        urLat, urLon = self.get_ur_anchor()

        if self.orbital_node == 'Ascending':

            ulLat, ulLon = od.ne_to_latlon(
                self.center_lat, self.center_lon,
                self.track_length/2,
                -num.tan(inc*d2r) * self.width/2)
            lrLat, lrLon = od.ne_to_latlon(
                self.center_lat, self.center_lon,
                -self.track_length/2,
                num.tan(inc*d2r) * self.width/2)

        elif self.orbital_node == 'Descending':
            urLat, urLon = od.ne_to_latlon(
                self.center_lat, self.center_lon,
                self.track_length/2,
                num.tan(inc*d2r) * self.width/2)
            llLat, llLon = od.ne_to_latlon(
                self.center_lat, self.center_lon,
                -self.track_length/2,
                -num.tan(inc*d2r) * self.width/2)

        return ((llLat, llLon), (ulLat, ulLon),
                (urLat, urLon), (lrLat, lrLon))

    def get_grid(self):
        '''
        Return relative positions of scatterer.

        :param track: Acquisition track, from `'asc'` or `'dsc'`.
        :type track: str
        '''
        easts = num.linspace(0, self.width,
                             self.resolution[0])
        norths = num.linspace(0, self.track_length,
                              self.resolution[1])

        return num.meshgrid(easts, norths)

    def get_mask_track(self):
        east_shifts, north_shifts = self.get_grid()
        norths = north_shifts[:, 0]
        track = num.abs(num.cos(self.inclination*d2r)) * norths

        track_mask = num.logical_and(
            east_shifts > track[:, num.newaxis],
            east_shifts < (track + self.swath_width)[:, num.newaxis])

        if self.orbital_node == 'Ascending':
            track_mask = num.fliplr(track_mask)

        return track_mask

    def get_mask_water(self):
        if self._mask_water is None:
            east_shifts, north_shifts = self.get_grid()

            east_shifts -= east_shifts[0, -1]/2
            north_shifts -= north_shifts[-1, -1]/2

            latlon = od.ne_to_latlon(self.center_lat, self.center_lon,
                                     north_shifts.ravel(), east_shifts.ravel())
            points = num.array(latlon).T
            self._mask_water = get_gsshg().get_land_mask(points)\
                .reshape(*east_shifts.shape)

        return self._mask_water

    def get_mask(self):
        mask_track = self.get_mask_track()
        if self.mask_water:
            mask_water = self.get_mask_water()
            return num.logical_and(mask_track, mask_water)
        return mask_track

    def get_incident_angles(self):
        # theta: elevation angle towards satellite from horizon in radians.
        # phi:  Horizontal angle towards satellite' :abbr:`line of sight (LOS)`
        #       in [rad] from East.
        east_shifts, _ = self.get_grid()

        phi = num.empty_like(east_shifts)
        theta = num.empty_like(east_shifts)

        east_shifts += num.tan(self.incident_angle*d2r) * self.apogee
        theta = num.arctan(east_shifts/self.apogee)

        if self.orbital_node == 'Ascending':
            phi.fill(self.inclination*d2r + num.pi/2)
        elif self.orbital_node == 'Descending':
            phi.fill(2*num.pi-(self.inclination*d2r + 3/2*num.pi))
            theta = num.fliplr(theta)
        else:
            raise AttributeError(
                'Orbital node %s not defined!' % self.orbital_node)

        theta[~self.get_mask()] = num.nan
        phi[~self.get_mask()] = num.nan

        return theta, phi

    def get_target(self):
        gE, gN = self.get_grid()
        mask = self.get_mask()

        east_shifts = gE[mask].ravel()
        north_shifts = gN[mask].ravel()
        llLat, llLon = self.get_ll_anchor()

        ncoords = east_shifts.size

        theta, phi = self.get_incident_angles()

        theta = theta[mask].ravel()
        phi = phi[mask].ravel()

        if ncoords == 0:
            logger.warning('InSAR taget has no valid points,'
                           " maybe it's all water?")

        return self.SatelliteGeneratorTarget(
            scene_patch=self,
            lats=num_full(ncoords, fill_value=llLat),
            lons=num_full(ncoords, fill_value=llLon),
            east_shifts=east_shifts,
            north_shifts=north_shifts,
            theta=theta,
            phi=phi)


class AtmosphericNoiseGenerator(NoiseGenerator):

    amplitude = Float.T(
        default=1.,
        help='Amplitude of the atmospheric noise.')

    beta = [5./3, 8./3, 2./3]
    regimes = [.15, .99, 1.]

    def get_noise(self, scene):
        nE = scene.frame.rows
        nN = scene.frame.cols

        if (nE+nN) % 2 != 0:
            raise ArithmeticError('Dimensions of synthetic scene must '
                                  'both be even!')

        dE = scene.frame.dE
        dN = scene.frame.dN

        rfield = num.random.rand(nE, nN)
        spec = num.fft.fft2(rfield)

        kE = num.fft.fftfreq(nE, dE)
        kN = num.fft.fftfreq(nN, dN)
        k_rad = num.sqrt(kN[:, num.newaxis]**2 + kE[num.newaxis, :]**2)

        regimes = num.array(self.regimes)

        k0 = 0.
        k1 = regimes[0] * k_rad.max()
        k2 = regimes[1] * k_rad.max()

        r0 = num.logical_and(k_rad > k0, k_rad < k1)
        r1 = num.logical_and(k_rad >= k1, k_rad < k2)
        r2 = k_rad >= k2

        beta = num.array(self.beta)
        # From Hanssen (2001)
        #   beta+1 is used as beta, since, the power exponent
        #   is defined for a 1D slice of the 2D spectrum:
        #   austin94: "Adler, 1981, shows that the surface profile
        #   created by the intersection of a plane and a
        #   2-D fractal surface is itself fractal with
        #   a fractal dimension  equal to that of the 2D
        #   surface decreased by one."
        beta += 1.
        # From Hanssen (2001)
        #   The power beta/2 is used because the power spectral
        #   density is proportional to the amplitude squared
        #   Here we work with the amplitude, instead of the power
        #   so we should take sqrt( k.^beta) = k.^(beta/2)  RH
        # beta /= 2.

        amp = num.zeros_like(k_rad)
        amp[r0] = k_rad[r0] ** -beta[0]
        amp[r0] /= amp[r0].max()

        amp[r1] = k_rad[r1] ** -beta[1]
        amp[r1] /= amp[r1].max() / amp[r0].min()

        amp[r2] = k_rad[r2] ** -beta[2]
        amp[r2] /= amp[r2].max() / amp[r1].min()

        amp[k_rad == 0.] = amp.max()

        spec *= self.amplitude * num.sqrt(amp)
        noise = num.abs(num.fft.ifft2(spec))
        noise -= num.mean(noise)

        return noise


class InSARGenerator(TargetGenerator):
    # https://sentinel.esa.int/web/sentinel/user-guides/sentinel-1-sar/acquisition-modes/interferometric-wide-swath
    store_id = String.T(
        default=DEFAULT_STORE_ID,
        help='Store ID for these stations.')

    inclination = Float.T(
        default=98.2,
        help='Inclination of the satellite orbit towards equatorial plane'
             ' in [deg]. Defaults to Sentinel-1 (98.1 deg).')
    apogee = Float.T(
        default=693.*km,
        help='Apogee of the satellite in [m]. '
             'Defaults to Sentinel-1 (693 km).')
    swath_width = Float.T(
        default=250*km,
        help='Swath width in [m]. '
             'Defaults to Sentinel-1 Interfeometric Wide Swath Mode (IW).'
             ' (IW; 250 km).')
    track_length = Float.T(
        default=250*km,
        help='Track length in [m]. Defaults to 200 km.')
    incident_angle = Float.T(
        default=29.1,
        help='Near range incident angle in [deg]. Defaults to 29.1 deg;'
             ' Sentinel IW mode (29.1 - 46.0 deg).')
    resolution = Tuple.T(
        default=(250, 250),
        help='Resolution of raster in east x north [px].')
    mask_water = Bool.T(
        default=True,
        help='Mask out water bodies.')
    noise_generator = NoiseGenerator.T(
        default=AtmosphericNoiseGenerator.D(),
        help='Add atmospheric noise model after Hansen, 2001.')

    def get_scene_patches(self):
        center_lat, center_lon = self.get_center_latlon()

        scene_patches = []
        for direction in ('Ascending', 'Descending'):
            patch = ScenePatch(
                center_lat=center_lat,
                center_lon=center_lon,
                time_master=0,
                time_slave=0,
                inclination=self.inclination,
                apogee=self.apogee,
                swath_width=self.swath_width,
                track_length=self.track_length,
                incident_angle=self.incident_angle,
                resolution=self.resolution,
                orbital_node=direction,
                mask_water=self.mask_water)
            scene_patches.append(patch)

        return scene_patches

    def get_targets(self):
        targets = [s.get_target() for s in self.get_scene_patches()]

        for t in targets:
            t.store_id = self.store_id

        return targets

    def get_insar_scenes(self, engine, sources, tmin=None, tmax=None):
        logger.debug('Forward modelling InSAR displacement...')

        scenario_tmin, scenario_tmax = self.get_time_range(sources)

        try:
            resp = engine.process(
                sources,
                self.get_targets(),
                nthreads=0)
        except gf.meta.OutOfBounds:
            logger.warning('Could not calculate InSAR displacements'
                           " - the GF store's extend is too small!")
            return []

        scenes = [res.scene for res in resp.static_results()]

        tmin, tmax = self.get_time_range(sources)
        for sc in scenes:
            sc.meta.time_master = util.to_time_float(tmin)
            sc.meta.time_slave = util.to_time_float(tmax)

        scenes_asc = [sc for sc in scenes
                      if sc.config.meta.orbital_node == 'Ascending']
        scenes_dsc = [sc for sc in scenes
                      if sc.config.meta.orbital_node == 'Descending']

        def stack_scenes(scenes):
            base = scenes[0]
            for sc in scenes[1:]:
                base += sc
            return base

        scene_asc = stack_scenes(scenes_asc)
        scene_dsc = stack_scenes(scenes_dsc)

        if self.noise_generator:
            scene_asc.displacement += self.noise_generator.get_noise(scene_asc)
            scene_dsc.displacement += self.noise_generator.get_noise(scene_dsc)

        return scene_asc, scene_dsc

    def ensure_data(self, engine, sources, path, tmin=None, tmax=None):

        path_insar = op.join(path, 'insar')
        util.ensuredir(path_insar)

        tmin, tmax = self.get_time_range(sources)
        tts = util.time_to_str

        fn_tpl = op.join(path_insar, 'colosseo-scene-{orbital_node}_%s_%s'
                         % (tts(tmin, '%Y-%m-%d'), tts(tmax, '%Y-%m-%d')))

        def scene_fn(track):
            return fn_tpl.format(orbital_node=track.lower())

        for track in ('ascending', 'descending'):
            fn = '%s.yml' % scene_fn(track)

            if op.exists(fn):
                logger.debug('Scene exists: %s' % fn)
                continue

            scenes = self.get_insar_scenes(engine, sources, tmin, tmax)
            for sc in scenes:
                fn = scene_fn(sc.config.meta.orbital_node)
                logger.debug('Writing %s' % fn)
                sc.save('%s.npz' % fn)

    def add_map_artists(self, engine, sources, automap):
        logger.warning('InSAR mapping is not implemented!')
        return None
