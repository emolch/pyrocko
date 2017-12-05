from pyrocko.guts import (Object, Float, String, List, StringChoice,
                          DateTimestamp)
from pyrocko.model import Location


class GNSSComponent(Object):
    unit = StringChoice.T(
        choices=['mm', 'cm', 'm'],
        default='m')

    shift = Float.T(
        default=0.,
        help='Shift in unit')

    error = Float.T(
        default=0.,
        help='Error of the measurement')


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
        optional=True)

    survey_end = DateTimestamp.T(
        optional=True)

    north = GNSSComponent.T(
        default=GNSSComponent.D())

    east = GNSSComponent.T(
        default=GNSSComponent.D())

    up = GNSSComponent.T(
        default=GNSSComponent.D())

    def __init__(self, *args, **kwargs):
        Location.__init__(self, *args, **kwargs)


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

    def add_station(self, station):
        return self.stations.append(station)
