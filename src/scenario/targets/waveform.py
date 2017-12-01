from builtins import range
import hashlib
import math
import logging
import numpy as num
from functools import reduce

from pyrocko.guts import StringChoice, Float
from pyrocko import gf, model, util, trace

from .station import StationGenerator, RandomStationGenerator
from .base import TargetGenerator
from ..base import Generator

DEFAULT_STORE_ID = 'global_2s'

logger = logging.getLogger('pyrocko.scenario.targets.waveform')
guts_prefix = 'pf.scenario'


class NoiseGenerator(Generator):

    def get_time_increment(self, deltat):
        return deltat * 1024

    def get_intersecting_snippets(self, deltat, codes, tmin, tmax):
        raise NotImplemented()

    def add_noise(self, tr):
        for ntr in self.get_intersecting_snippets(
                tr.deltat, tr.nslc_id, tr.tmin, tr.tmax):
            tr.add(ntr)


class WhiteNoiseGenerator(NoiseGenerator):

    scale = Float.T(default=1e-6)

    def get_seed_offset2(self, deltat, iw, codes):
        m = hashlib.sha1(('%e %i %s.%s.%s.%s' % ((deltat, iw) + codes))
                         .encode('utf8'))
        return int(m.hexdigest(), base=16) % 1000

    def get_intersecting_snippets(self, deltat, codes, tmin, tmax):
        tinc = self.get_time_increment(deltat)
        iwmin = int(math.floor(tmin / tinc))
        iwmax = int(math.floor(tmax / tinc))

        trs = []
        for iw in range(iwmin, iwmax+1):
            seed_offset = self.get_seed_offset2(deltat, iw, codes)
            rstate = self.get_rstate(seed_offset)

            n = int(round(tinc // deltat))

            trs.append(trace.Trace(
                codes[0], codes[1], codes[2], codes[3],
                deltat=deltat,
                tmin=iw*tinc,
                ydata=rstate.normal(loc=0, scale=self.scale, size=n)))

        return trs


class WaveformGenerator(TargetGenerator):

    station_generator = StationGenerator.T(
        default=RandomStationGenerator.D())

    noise_generator = NoiseGenerator.T(
        default=WhiteNoiseGenerator.D())

    store_id = gf.StringID.T(
        default=DEFAULT_STORE_ID,
        optional=True)

    seismogram_quantity = StringChoice.T(
        choices=['displacement', 'velocity', 'acceleration', 'counts'],
        default='displacement')

    vmin_cut = Float.T(default=2000.)
    vmax_cut = Float.T(default=8000.)

    fmin = Float.T(default=0.01)

    def get_stations(self):
        return self.station_generator.get_stations()

    def get_targets(self):
        targets = []
        for station in self.get_stations():
            channel_data = []
            channels = station.get_channels()
            if channels:
                for channel in channels:
                    channel_data.append([
                        channel.name,
                        channel.azimuth,
                        channel.dip])

            else:
                for c_name in ['BHZ', 'BHE', 'BHN']:
                    channel_data.append([
                        c_name,
                        model.guess_azimuth_from_name(c_name),
                        model.guess_dip_from_name(c_name)])

            for c_name, c_azi, c_dip in channel_data:

                target = gf.Target(
                    codes=(
                        station.network,
                        station.station,
                        station.location,
                        c_name),
                    quantity='displacement',
                    lat=station.lat,
                    lon=station.lon,
                    depth=station.depth,
                    store_id=self.store_id,
                    optimization='enable',
                    interpolation='nearest_neighbor',
                    azimuth=c_azi,
                    dip=c_dip)

                targets.append(target)

        return targets

    def get_station_distance_range(self, sources):
        dists = []
        for source in sources:
            for station in self.get_stations():
                dists.append(
                    source.distance_to(station))

        return num.min(dists), num.max(dists)

    def get_time_range(self, sources):
        dmin, dmax = self.get_station_distance_range(sources)

        times = num.array([source.time for source in sources],
                          dtype=num.float)

        tmin_events = num.min(times)
        tmax_events = num.max(times)

        tmin = tmin_events + dmin / self.vmax_cut - 10.0 / self.fmin
        tmax = tmax_events + dmax / self.vmin_cut + 10.0 / self.fmin

        return tmin, tmax

    def get_codes_to_deltat(self, engine, sources):
        deltats = {}
        for source in sources:
            for target in self.get_targets():
                deltats[target.codes] = engine.get_store(
                    target.store_id).config.deltat

        return deltats

    def get_useful_time_increment(self, engine, sources):
        _, dmax = self.get_station_distance_range(sources)
        tinc = dmax / self.vmin_cut + 2.0 / self.fmin

        deltats = set(self.get_codes_to_deltat(engine, sources).values())

        deltat = reduce(util.lcm, deltats)
        tinc = int(round(tinc / deltat)) * deltat
        return tinc

    def get_waveforms(self, engine, sources):
        logger.info('Calculating waveforms...')
        trs = {}
        tmin, tmax = self.get_time_range(sources)

        for nslc, deltat in self.get_codes_to_deltat(engine, sources).items():
            tr_tmin = int(round(tmin / deltat)) * deltat
            tr_tmax = (int(round(tmax / deltat))-1) * deltat
            n = int(round((tr_tmax - tr_tmin) / deltat)) + 1

            tr = trace.Trace(
                nslc[0], nslc[1], nslc[2], nslc[3],
                tmin=tr_tmin,
                ydata=num.zeros(n),
                deltat=deltat)

            self.noise_generator.add_noise(tr)

            trs[nslc] = tr

        for source in sources:
            targets = self.get_targets()
            resp = engine.process(source, targets)

            for _, target, tr in resp.iter_results():
                resp = self.get_transfer_function(target.codes)
                if resp:
                    tr = tr.transfer(transfer_function=resp)

                trs[target.codes].add(tr)

        return list(trs.values())

    def get_transfer_function(self, codes):
        if self.seismogram_quantity == 'displacement':
            return None
        elif self.seismogram_quantity == 'velocity':
            return trace.DifferentiationResponse(1)
        elif self.seismogram_quantity == 'acceleration':
            return trace.DifferentiationResponse(2)
        elif self.seismogram_quantity == 'counts':
            raise NotImplemented()
