# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Synthetic seismic waveform generator.
'''

import hashlib
import math
import logging
import numpy as num

from os import path as op
from functools import reduce

from pyrocko.guts import StringChoice, Float, List, Bool
from pyrocko.gui.snuffler.marker import PhaseMarker, EventMarker
from pyrocko import gf, model, util, trace, io
from pyrocko.response import DifferentiationResponse
from pyrocko.io.io_common import FileSaveError
from pyrocko import pile

from ..station import StationGenerator, RandomStationGenerator
from .base import TargetGenerator, NoiseGenerator
from ..error import ScenarioError


DEFAULT_STORE_ID = 'global_2s'

logger = logging.getLogger('pyrocko.scenario.targets.waveform')
guts_prefix = 'pf.scenario'


class WaveformNoiseGenerator(NoiseGenerator):

    def get_time_increment(self, deltat):
        return deltat * 1024

    def get_intersecting_snippets(self, deltat, codes, tmin, tmax):
        raise NotImplementedError()

    def add_noise(self, tr):
        for ntr in self.get_intersecting_snippets(
                tr.deltat, tr.nslc_id, tr.tmin, tr.tmax):
            tr.add(ntr)


class WhiteNoiseGenerator(WaveformNoiseGenerator):

    scale = Float.T(default=1e-6)

    def get_seed_offset2(self, deltat, iw, codes):
        m = hashlib.sha1(('%e %i %s.%s.%s.%s' % ((deltat, iw) + codes))
                         .encode('utf8'))
        return int(m.hexdigest(), base=16) % 10000000

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

    station_generators = List.T(
        StationGenerator.T(),
        default=[RandomStationGenerator.D()],
        help='List of StationGenerators.')

    noise_generator = WaveformNoiseGenerator.T(
        default=WhiteNoiseGenerator.D(),
        help='Add Synthetic noise on the waveforms.')

    store_id = gf.StringID.T(
        default=DEFAULT_STORE_ID,
        help='The GF store to use for forward-calculations.')

    seismogram_quantity = StringChoice.T(
        choices=['displacement', 'velocity', 'acceleration', 'counts'],
        default='displacement')

    vmin_cut = Float.T(
        default=2000.,
        help='Minimum velocity to seismic velocity to consider in the model.')
    vmax_cut = Float.T(
        default=8000.,
        help='Maximum velocity to seismic velocity to consider in the model.')

    fmin = Float.T(
        default=0.01,
        help='Minimum frequency/wavelength to resolve in the'
             ' synthetic waveforms.')

    tabulated_phases = List.T(
        gf.meta.TPDef.T(), optional=True,
        help='Define seismic phases to be calculated.')

    tabulated_phases_from_store = Bool.T(
        default=False,
        help='Calculate seismic phase arrivals for all travel-time tables '
             'defined in GF store.')

    tabulated_phases_noise_scale = Float.T(
        default=0.0,
        help='Standard deviation of normally distributed noise added to '
             'calculated phase arrivals.')

    taper = trace.Taper.T(
        optional=True,
        help='Time domain taper applied to synthetic waveforms.')

    compensate_synthetic_offsets = Bool.T(
        default=False,
        help='Center synthetic trace amplitudes using mean of waveform tips.')

    tinc = Float.T(
        optional=True,
        help='Time increment of waveforms.')

    continuous = Bool.T(
        default=True,
        help='Only produce traces that intersect with events.')

    def __init__(self, *args, **kwargs):
        super(WaveformGenerator, self).__init__(*args, **kwargs)
        self._targets = []
        self._piles = {}

    def _get_pile(self, path):
        apath = op.abspath(path)
        assert op.isdir(apath)

        if apath not in self._piles:
            fns = util.select_files(
                [apath], show_progress=False)

            p = pile.Pile()
            if fns:
                p.load_files(fns, fileformat='mseed', show_progress=False)

            self._piles[apath] = p

        return self._piles[apath]

    def get_stations(self):
        stations = []
        for station_generator in self.station_generators:
            stations.extend(station_generator.get_stations())
        return stations

    def get_distance_range(self, sources):
        distances = num.array(
            [sg.get_distance_range(sources)
             for sg in self.station_generators])
        return (distances[:, 0].min(), distances[:, 1].max())

    def get_targets(self):
        if self._targets:
            return self._targets

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
                    north_shift=station.north_shift,
                    east_shift=station.east_shift,
                    depth=station.depth,
                    store_id=self.store_id,
                    optimization='enable',
                    interpolation='nearest_neighbor',
                    azimuth=c_azi,
                    dip=c_dip)

                self._targets.append(target)

        return self._targets

    def get_time_range(self, sources):
        dmin, dmax = self.get_distance_range(sources)

        times = num.array([source.time for source in sources],
                          dtype=util.get_time_dtype())

        tmin_events = num.min(times)
        tmax_events = num.max(times)

        tmin = tmin_events + dmin / self.vmax_cut - 10.0 / self.fmin
        tmax = tmax_events + dmax / self.vmin_cut + 10.0 / self.fmin

        return tmin, tmax

    def get_codes_to_deltat(self, engine, sources):
        deltats = {}

        targets = self.get_targets()
        for source in sources:
            for target in targets:
                deltats[target.codes] = engine.get_store(
                    target.store_id).config.deltat

        return deltats

    def get_useful_time_increment(self, engine, sources):
        _, dmax = self.get_distance_range(sources)
        tinc = dmax / self.vmin_cut + 2.0 / self.fmin

        deltats = set(self.get_codes_to_deltat(engine, sources).values())
        deltat = reduce(util.lcm, deltats)
        tinc = int(round(tinc / deltat)) * deltat
        return tinc

    def get_relevant_sources(self, sources, tmin, tmax):
        dmin, dmax = self.get_distance_range(sources)
        trange = tmax - tmin
        tmax_pad = trange + tmax + dmin / self.vmax_cut
        tmin_pad = tmin - (dmax / self.vmin_cut + trange)

        return [s for s in sources if s.time < tmax_pad and s.time > tmin_pad]

    def get_waveforms(self, engine, sources, tmin, tmax):

        sources_relevant = self.get_relevant_sources(sources, tmin, tmax)
        if not (self.continuous or sources_relevant):
            return []

        trs = {}
        tts = util.time_to_str

        for nslc, deltat in self.get_codes_to_deltat(engine, sources).items():
            tr_tmin = round(tmin / deltat) * deltat
            tr_tmax = (round(tmax / deltat)-1) * deltat
            nsamples = int(round((tr_tmax - tr_tmin) / deltat)) + 1

            tr = trace.Trace(
                *nslc,
                tmin=tr_tmin,
                ydata=num.zeros(nsamples),
                deltat=deltat)

            self.noise_generator.add_noise(tr)

            trs[nslc] = tr

        logger.debug('Forward modelling waveforms between %s - %s...'
                     % (tts(tmin, format='%Y-%m-%d_%H-%M-%S'),
                        tts(tmax, format='%Y-%m-%d_%H-%M-%S')))

        if not sources_relevant:
            return list(trs.values())

        targets = self.get_targets()
        response = engine.process(sources_relevant, targets)
        for source, target, res in response.iter_results(
                get='results'):

            if isinstance(res, gf.SeismosizerError):
                logger.warning(
                    'Out of bounds! \nTarget: %s\nSource: %s\n' % (
                        '.'.join(target.codes)), source)
                continue

            tr = res.trace.pyrocko_trace()

            candidate = trs[target.codes]
            if not candidate.overlaps(tr.tmin, tr.tmax):
                continue

            if self.compensate_synthetic_offsets:
                tr.ydata -= (num.mean(tr.ydata[-3:-1]) +
                             num.mean(tr.ydata[1:3])) / 2.

            if self.taper:
                tr.taper(self.taper)

            resp = self.get_transfer_function(target.codes)
            if resp:
                tr = tr.transfer(transfer_function=resp)

            candidate.add(tr)
            trs[target.codes] = candidate

        return list(trs.values())

    def get_onsets(self, engine, sources, *args, **kwargs):

        targets = {t.codes[:3]: t for t in self.get_targets()}

        markers = []
        for source in sources:
            ev = source.pyrocko_event()
            markers.append(EventMarker(ev))
            for nsl, target in targets.items():
                store = engine.get_store(target.store_id)
                if self.tabulated_phases:
                    tabulated_phases = self.tabulated_phases

                elif self.tabulated_phases_from_store:
                    tabulated_phases = store.config.tabulated_phases
                else:
                    tabulated_phases = []

                for phase in tabulated_phases:
                    t = store.t(phase.id, source, target)
                    if not t:
                        continue

                    noise_scale = self.tabulated_phases_noise_scale
                    if noise_scale != 0.0:
                        t += num.random.normal(scale=noise_scale)

                    t += source.time
                    markers.append(
                        PhaseMarker(
                            phasename=phase.id,
                            tmin=t,
                            tmax=t,
                            event=source.pyrocko_event(),
                            nslc_ids=(nsl+('*',),)
                            )
                        )
        return markers

    def get_transfer_function(self, codes):
        if self.seismogram_quantity == 'displacement':
            return None
        elif self.seismogram_quantity == 'velocity':
            return DifferentiationResponse(1)
        elif self.seismogram_quantity == 'acceleration':
            return DifferentiationResponse(2)
        elif self.seismogram_quantity == 'counts':
            raise NotImplementedError()

    def ensure_data(self, engine, sources, path, tmin=None, tmax=None):
        self.ensure_waveforms(engine, sources, path, tmin, tmax)
        self.ensure_responses(path)

    def ensure_waveforms(self, engine, sources, path, tmin=None, tmax=None):

        path_waveforms = op.join(path, 'waveforms')
        util.ensuredir(path_waveforms)

        p = self._get_pile(path_waveforms)

        nslc_ids = set(target.codes for target in self.get_targets())

        def have_waveforms(tmin, tmax):
            trs_have = p.all(
                tmin=tmin, tmax=tmax,
                load_data=False, degap=False,
                trace_selector=lambda tr: tr.nslc_id in nslc_ids)

            return any(tr.data_len() > 0 for tr in trs_have)

        def add_files(paths):
            p.load_files(paths, fileformat='mseed', show_progress=False)

        path_traces = op.join(
            path_waveforms,
            '%(wmin_year)s',
            '%(wmin_month)s',
            '%(wmin_day)s',
            'waveform_%(network)s_%(station)s_' +
            '%(location)s_%(channel)s_%(tmin)s_%(tmax)s.mseed')

        tmin_all, tmax_all = self.get_time_range(sources)
        tmin = tmin if tmin is not None else tmin_all
        tmax = tmax if tmax is not None else tmax_all
        tts = util.time_to_str

        tinc = self.tinc or self.get_useful_time_increment(engine, sources)
        tmin = num.floor(tmin / tinc) * tinc
        tmax = num.ceil(tmax / tinc) * tinc

        nwin = int(round((tmax - tmin) / tinc))

        pbar = None
        try:
            for iwin in range(nwin):
                tmin_win = tmin + iwin*tinc
                tmax_win = tmin + (iwin+1)*tinc

                if have_waveforms(tmin_win, tmax_win):
                    continue

                if pbar is None:
                    pbar = util.progressbar(
                        'Generating waveforms', (nwin-iwin))

                pbar.update(iwin)

                trs = self.get_waveforms(engine, sources, tmin_win, tmax_win)

                try:
                    wpaths = io.save(
                        trs, path_traces,
                        additional=dict(
                            wmin_year=tts(tmin_win, format='%Y'),
                            wmin_month=tts(tmin_win, format='%m'),
                            wmin_day=tts(tmin_win, format='%d'),
                            wmin=tts(tmin_win, format='%Y-%m-%d_%H-%M-%S'),
                            wmax_year=tts(tmax_win, format='%Y'),
                            wmax_month=tts(tmax_win, format='%m'),
                            wmax_day=tts(tmax_win, format='%d'),
                            wmax=tts(tmax_win, format='%Y-%m-%d_%H-%M-%S')))

                    for wpath in wpaths:
                        logger.debug('Generated file: %s' % wpath)

                    add_files(wpaths)

                except FileSaveError as e:
                    raise ScenarioError(str(e))

        finally:
            if pbar is not None:
                pbar.finish()

    def ensure_responses(self, path):
        from pyrocko.io import stationxml

        path_responses = op.join(path, 'meta')
        util.ensuredir(path_responses)

        fn_stationxml = op.join(path_responses, 'waveform_response.xml')
        i = 0
        while op.exists(fn_stationxml):
            fn_stationxml = op.join(
                path_responses, 'waveform_response-%s.xml' % i)
            i += 1

        logger.debug('Writing waveform meta information to StationXML...')

        stations = self.get_stations()
        sxml = stationxml.FDSNStationXML.from_pyrocko_stations(stations)

        sunit = {
            'displacement': 'M',
            'velocity': 'M/S',
            'acceleration': 'M/S**2',
            'counts': 'COUNTS'}[self.seismogram_quantity]

        response = stationxml.Response(
            instrument_sensitivity=stationxml.Sensitivity(
                value=1.,
                frequency=1.,
                input_units=stationxml.Units(sunit),
                output_units=stationxml.Units('COUNTS')),
            stage_list=[])

        for net, station, channel in sxml.iter_network_station_channels():
            channel.response = response

        sxml.dump_xml(filename=fn_stationxml)

    def add_map_artists(self, engine, sources, automap):
        automap.add_stations(self.get_stations())
