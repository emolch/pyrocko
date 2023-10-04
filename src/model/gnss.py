# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
GNSS station and campaign data model.
'''

import logging
import math
import numpy as num
from collections import OrderedDict

import pyrocko.orthodrome as od

from pyrocko.guts import (Object, Float, String, List, StringChoice,
                          DateTimestamp)
from pyrocko.model import Location

guts_prefix = 'pf.gnss'
logger = logging.getLogger('pyrocko.model.gnss')


class GNSSComponent(Object):
    '''
    Component of a GNSSStation
    '''
    unit = StringChoice.T(
        choices=['mm', 'cm', 'm'],
        help='Unit of displacement',
        default='m')

    shift = Float.T(
        default=0.,
        help="Component's shift in unit")

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
    '''
    Representation of a GNSS station during a campaign measurement

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
        default=0.,
        help='North-East component correlation')

    correlation_eu = Float.T(
        default=0.,
        help='East-Up component correlation')

    correlation_nu = Float.T(
        default=0.,
        help='North-Up component correlation')

    north = GNSSComponent.T(
        optional=True)

    east = GNSSComponent.T(
        optional=True)

    up = GNSSComponent.T(
        optional=True)

    def __eq__(self, other):
        try:
            return self.code == other.code
        except AttributeError:
            return False

    def get_covariance_matrix(self):
        components = self.components.values()
        ncomponents = self.ncomponents

        covar = num.zeros((ncomponents, ncomponents))
        for ic1, comp1 in enumerate(components):
            for ic2, comp2 in enumerate(components):
                corr = self._get_comp_correlation(comp1, comp2)
                covar[ic1, ic2] = corr * comp1.sigma * comp2.sigma

        # This floating point operation is inaccurate:
        # corr * comp1.sigma * comp2.sigma != corr * comp2.sigma * comp1.sigma
        #
        # Hence this identity
        covar[num.tril_indices_from(covar, k=-1)] = \
            covar[num.triu_indices_from(covar, k=1)]

        return covar

    def get_correlation_matrix(self):
        components = self.components.values()
        ncomponents = self.ncomponents

        corr = num.zeros((ncomponents, ncomponents))
        corr[num.diag_indices_from(corr)] = num.array(
            [c.sigma for c in components])

        for ic1, comp1 in enumerate(components):
            for ic2, comp2 in enumerate(components):
                if comp1 is comp2:
                    continue
                corr[ic1, ic2] = self._get_comp_correlation(comp1, comp2)

        # See comment at get_covariance_matrix
        corr[num.tril_indices_from(corr, k=-1)] = \
            corr[num.triu_indices_from(corr, k=1)]

        return corr

    def get_displacement_data(self):
        return num.array([c.shift for c in self.components.values()])

    def get_component_mask(self):
        return num.array(
            [False if self.__getattribute__(name) is None else True
             for name in ('north', 'east', 'up')], dtype=bool)

    @property
    def components(self):
        return OrderedDict(
            [(name, self.__getattribute__(name))
             for name in ('north', 'east', 'up')
             if self.__getattribute__(name) is not None])

    @property
    def ncomponents(self):
        return len(self.components)

    def _get_comp_correlation(self, comp1, comp2):
        if comp1 is comp2:
            return 1.

        s = self

        correlation_map = {
            (s.north, s.east): s.correlation_ne,
            (s.east, s.up): s.correlation_eu,
            (s.north, s.up): s.correlation_nu
        }

        return correlation_map.get(
            (comp1, comp2),
            correlation_map.get((comp2, comp1), False))


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
        self._cov_mat = None
        self._cor_mat = None

    def add_station(self, station):
        self._cor_mat = None
        self._cov_mat = None
        return self.stations.append(station)

    def remove_station(self, station_code):
        try:
            station = self.get_station(station_code)
            self.stations.remove(station)
            self._cor_mat = None
            self._cov_mat = None
        except ValueError:
            logger.warning('Station {} does not exist in campaign, '
                           'do nothing.'.format(station_code))

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

    def get_covariance_matrix(self):
        if self._cov_mat is None:
            ncomponents = self.ncomponents
            cov_arr = num.zeros((ncomponents, ncomponents))

            idx = 0
            for ista, sta in enumerate(self.stations):
                ncomp = sta.ncomponents
                cov_arr[idx:idx+ncomp, idx:idx+ncomp] = \
                    sta.get_covariance_matrix()
                idx += ncomp

            self._cov_mat = cov_arr
        return self._cov_mat

    def get_correlation_matrix(self):
        if self._cor_mat is None:
            ncomponents = self.ncomponents
            cor_arr = num.zeros((ncomponents, ncomponents))

            idx = 0
            for ista, sta in enumerate(self.stations):
                ncomp = sta.ncomponents
                cor_arr[idx:idx+ncomp, idx:idx+ncomp] = \
                    sta.get_correlation_matrix()
                idx += ncomp

            self._cor_mat = cor_arr
        return self._cor_mat

    def get_component_mask(self):
        return num.concatenate(
            [s.get_component_mask() for s in self.stations])

    def dump(self, *args, **kwargs):
        self.regularize()
        return Object.dump(self, *args, **kwargs)

    @property
    def coordinates(self):
        return num.array([loc.effective_latlon for loc in self.stations])

    @property
    def nstations(self):
        return len(self.stations)

    @property
    def ncomponents(self):
        return sum([s.ncomponents for s in self.stations])
