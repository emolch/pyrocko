import logging
import math
import numpy as num
import pyrocko.orthodrome as od

from pyrocko.guts import (Object, Float, String, List, StringChoice,
                          DateTimestamp)
from pyrocko.model import Location

guts_prefix = 'pf.gnss'
logger = logging.getLogger('pyrocko.model.gnss')


class GNSSComponent(Object):
    ''' Component of a GNSSStation
    '''
    unit = StringChoice.T(
        choices=['mm', 'cm', 'm'],
        default='m')

    shift = Float.T(
        default=0.,
        help='Shift in unit')

    sigma = Float.T(
        default=0.,
        help='One sigma uncertainty of the measurement')

    def __add__(self, other):
        if not isinstance(other, self.__class__):
            raise AttributeError('Other has to be of instance %s'
                                 % self.__class__)
        comp = self.__class__()
        comp.shift = self.shift + other.shift
        comp.sigma = math.sqrt(self.sigma**2 + other.sigma**2)
        return comp

    def __iadd__(self, other):
        self.shift += other.shift
        self.sigma = math.sqrt(self.sigma**2 + other.sigma**2)
        return self


class GNSSStation(Location):
    ''' Representation of a GNSS station during a campaign measurement

    For more information see
    http://kb.unavco.org/kb/assets/660/UNAVCO_Campaign_GPS_GNSS_Handbook.pdf
    '''

    code = String.T(
        help='Four letter station code',
        optional=True)

    style = StringChoice.T(
        choices=['static', 'rapid_static', 'kinematic'],
        default='static')

    survey_start = DateTimestamp.T(
        optional=True,
        help='Survey start time')

    survey_end = DateTimestamp.T(
        optional=True,
        help='Survey end time')

    correlation_ne = Float.T(
        optional=True,
        help='North-East component correlation')

    correlation_eu = Float.T(
        optional=True,
        help='East-Up component correlation')

    correlation_nu = Float.T(
        optional=True,
        help='North-Up component correlation')

    north = GNSSComponent.T(
        default=GNSSComponent.D())

    east = GNSSComponent.T(
        default=GNSSComponent.D())

    up = GNSSComponent.T(
        default=GNSSComponent.D())

    def __init__(self, *args, **kwargs):
        Location.__init__(self, *args, **kwargs)

    def get_correlation_matrix(self, full=True):
        s = self

        corr = num.zeros((3, 3))
        corr[num.diag_indices_from(corr)] = num.array(
            [c.sigma for c in (s.north, s.east, s.up)])

        if s.correlation_ne is not None:
            corr[0, 1] = s.correlation_ne
        if s.correlation_nu is not None:
            corr[0, 2] = s.correlation_nu
        if s.correlation_eu is not None:
            corr[1, 2] = s.correlation_eu

        if full:
            corr[num.tril_indices_from(corr, k=-1)] = \
                corr[num.triu_indices_from(corr, k=1)]

        return corr


class GNSSCampaign(Object):

    stations = List.T(
        GNSSStation.T(),
        help='List of GNSS campaign measurements')

    name = String.T(
        help='Campaign name',
        default='Unnamed campaign')

    survey_start = DateTimestamp.T(
        optional=True)

    survey_end = DateTimestamp.T(
        optional=True)

    def __init__(self, *args, **kwargs):
        Object.__init__(self, *args, **kwargs)
        self._cov_arr = None

    def add_station(self, station):
        return self.stations.append(station)

    def get_station(self, station_code):
        for sta in self.stations:
            if sta.code == station_code:
                return sta
        raise ValueError('Could not find station %s' % station_code)

    def get_center_latlon(self):
        return od.geographic_midpoint_locations(self.stations)

    def get_radius(self):
        coords = self.coordinates
        return od.distance_accurate50m(
            coords[:, 0].min(), coords[:, 1].min(),
            coords[:, 0].max(), coords[:, 1].max()) / 2.

    def get_correlation_matrix(self):
        logger.warn('gnss.get_covariance_matrix is not fully implemented!')
        if self._cov_arr is None:
            cov_arr = num.zeros((self.nstations*3, self.nstations*3))

            for ista, sta in enumerate(self.stations):
                cov_arr[ista*3:ista*3+3, ista*3:ista*3+3] = \
                    sta.get_correlation_matrix(full=True)

            self._cov_arr = cov_arr
        return self._cov_arr

    @property
    def coordinates(self):
        return num.array([loc.effective_latlon for loc in self.stations])

    @property
    def nstations(self):
        return len(self.stations)
