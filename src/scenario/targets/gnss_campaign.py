# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Synthetic GNSS data generator.
'''

import logging
import os.path as op
import numpy as num

from pyrocko import gf, util
from pyrocko.guts import Float, List

from .base import TargetGenerator, NoiseGenerator
from ..station import RandomStationGenerator, StationGenerator

DEFAULT_STORE_ID = 'ak135_static'

logger = logging.getLogger('pyrocko.scenario.targets.gnss_campaign')
guts_prefix = 'pf.scenario'


class GPSNoiseGenerator(NoiseGenerator):
    measurement_duarion_days = Float.T(
        default=2.,
        help='Measurement duration in days')

    def add_noise(self, campaign):
        # https://www.nat-hazards-earth-syst-sci.net/15/875/2015/nhess-15-875-2015.pdf
        waterlevel = 1. - (.99 + .0015 * self.measurement_duarion_days)  # noqa
        logger.warning('GPSNoiseGenerator is a work-in-progress!')

        for ista, sta in enumerate(campaign.stations):
            pass
            # rstate = self.get_rstate(ista)

            # sta.north.sigma = 8e-3
            # sta.east.sigma = 8e-3

            # sta.north.shift += rstate.normal(0., sta.north.sigma)
            # sta.east.shift += rstate.normal(0., sta.east.sigma)


class GNSSCampaignGenerator(TargetGenerator):
    station_generators = List.T(
        StationGenerator.T(),
        default=[RandomStationGenerator.D(
            network_name='GN',
            channels=None)],
        help='The StationGenerator.')

    noise_generator = NoiseGenerator.T(
        default=GPSNoiseGenerator.D(),
        optional=True,
        help='Add Synthetic noise to the GNSS displacements.')

    store_id = gf.StringID.T(
        default=DEFAULT_STORE_ID,
        help='The GF store to use for forward-calculations.')

    def get_stations(self):
        stations = []
        for station_generator in self.station_generators:
            stations.extend(station_generator.get_stations())
        return stations

    def get_targets(self):
        stations = self.get_stations()
        lats = num.array([s.effective_lat for s in stations])
        lons = num.array([s.effective_lon for s in stations])

        target = gf.GNSSCampaignTarget(
            lats=lats,
            lons=lons,
            store_id=self.store_id)

        return [target]

    def get_gnss_campaigns(self, engine, sources, tmin=None, tmax=None):
        try:
            resp = engine.process(
                sources,
                self.get_targets(),
                nthreads=0)
        except gf.meta.OutOfBounds:
            logger.warning('Could not calculate GNSS displacements'
                           " - the GF store's extend is too small!")
            return []

        campaigns = [r.campaign for r in resp.static_results()]

        stacked_campaign = campaigns[0]
        stacked_campaign.name = 'Scenario Campaign'
        for camp in campaigns[1:]:
            for ista, sta in enumerate(camp.stations):
                stacked_campaign.stations[ista].north.shift += sta.north.shift
                stacked_campaign.stations[ista].east.shift += sta.east.shift
                stacked_campaign.stations[ista].up.shift += sta.up.shift

        for ista, sta in enumerate(stacked_campaign.stations):
            sta.code = 'SY%02d' % (ista + 1)

        if self.noise_generator is not None:
            self.noise_generator.add_noise(stacked_campaign)

        return [stacked_campaign]

    def ensure_data(self, engine, sources, path, tmin=None, tmax=None):
        path_gnss = op.join(path, 'gnss')
        util.ensuredir(path_gnss)

        networks = []
        for sg in self.station_generators:
            try:
                networks.append(sg.network_name)
            except AttributeError:
                pass

        fn = op.join(
            path_gnss,
            'campaign-%s.yml' % '_'.join(networks))

        if op.exists(fn):
            return

        campaigns = self.get_gnss_campaigns(engine, sources, tmin, tmax)

        with open(fn, 'w') as f:
            for camp in campaigns:
                camp.dump(stream=f)

    def add_map_artists(self, engine, sources, automap):
        automap.add_gnss_campaign(self.get_gnss_campaigns(engine, sources)[0])
