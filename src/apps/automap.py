# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Automap - create simple maps with GMT.
'''

import sys
import logging
import numpy as num
from pyrocko import util, model, orthodrome as od, gmtpy
from pyrocko import moment_tensor as pmt
from pyrocko.plot import automap

from optparse import OptionParser

km = 1000.
logger = logging.getLogger('pyrocko.apps.automap')

program_name = 'automap'

usage = '''
usage: %s [options] [--] <lat> <lon> <radius_km> <output.(pdf|png)>
       %s [--download-etopo1] [--download-srtmgl3]
'''.strip() % (program_name, program_name)

description = '''Create a simple map with topography.'''


def latlon_arrays(locs):
    return num.array(
        [(x.effective_lat, x.effective_lon) for x in locs]).T


def main(args=None):
    '''
    CLI entry point for Pyrocko's ``automap`` app.
    '''
    if args is None:
        args = sys.argv[1:]

    parser = OptionParser(
        usage=usage,
        description=description)

    parser.add_option(
        '--width',
        dest='width',
        type='float',
        default=20.0,
        metavar='FLOAT',
        help='set width of output image [cm] (%default)')

    parser.add_option(
        '--height',
        dest='height',
        type='float',
        default=15.0,
        metavar='FLOAT',
        help='set height of output image [cm] (%default)')

    parser.add_option(
        '--topo-resolution-min',
        dest='topo_resolution_min',
        type='float',
        default=40.0,
        metavar='FLOAT',
        help='minimum resolution of topography [dpi] (%default)')

    parser.add_option(
        '--topo-resolution-max',
        dest='topo_resolution_max',
        type='float',
        default=200.0,
        metavar='FLOAT',
        help='maximum resolution of topography [dpi] (%default)')

    parser.add_option(
        '--no-grid',
        dest='show_grid',
        default=True,
        action='store_false',
        help="don't show grid lines")

    parser.add_option(
        '--no-topo',
        dest='show_topo',
        default=True,
        action='store_false',
        help="don't show topography")

    parser.add_option(
        '--no-cities',
        dest='show_cities',
        default=True,
        action='store_false',
        help="don't show cities")

    parser.add_option(
        '--no-illuminate',
        dest='illuminate',
        default=True,
        action='store_false',
        help='deactivate artificial illumination of topography')

    parser.add_option(
        '--illuminate-factor-land',
        dest='illuminate_factor_land',
        type='float',
        metavar='FLOAT',
        help='set factor for artificial illumination of land (0.5)')

    parser.add_option(
        '--illuminate-factor-ocean',
        dest='illuminate_factor_ocean',
        type='float',
        metavar='FLOAT',
        help='set factor for artificial illumination of ocean (0.25)')

    parser.add_option(
        '--theme',
        choices=['topo', 'soft'],
        default='topo',
        help='select color theme, available: topo, soft (topo)"')

    parser.add_option(
        '--download-etopo1',
        dest='download_etopo1',
        action='store_true',
        help='download full ETOPO1 topography dataset')

    parser.add_option(
        '--download-srtmgl3',
        dest='download_srtmgl3',
        action='store_true',
        help='download full SRTMGL3 topography dataset')

    parser.add_option(
        '--make-decimated-topo',
        dest='make_decimated',
        action='store_true',
        help='pre-make all decimated topography datasets')

    parser.add_option(
        '--stations',
        dest='stations_fn',
        metavar='FILENAME',
        help='load station coordinates from FILENAME')

    parser.add_option(
        '--events',
        dest='events_fn',
        metavar='FILENAME',
        help='load event coordinates from FILENAME')

    parser.add_option(
        '--debug',
        dest='debug',
        action='store_true',
        default=False,
        help='print debugging information to stderr')

    (options, args) = parser.parse_args(args)

    if options.debug:
        util.setup_logging(program_name, 'debug')
    else:
        util.setup_logging(program_name, 'info')

    if options.download_etopo1:
        import pyrocko.dataset.topo.etopo1
        pyrocko.dataset.topo.etopo1.download()

    if options.download_srtmgl3:
        import pyrocko.dataset.topo.srtmgl3
        pyrocko.dataset.topo.srtmgl3.download()

    if options.make_decimated:
        import pyrocko.dataset.topo
        pyrocko.dataset.topo.make_all_missing_decimated()

    if (options.download_etopo1 or options.download_srtmgl3 or
            options.make_decimated) and len(args) == 0:

        sys.exit(0)

    if options.theme == 'soft':
        color_kwargs = {
            'illuminate_factor_land': options.illuminate_factor_land or 0.2,
            'illuminate_factor_ocean': options.illuminate_factor_ocean or 0.15,
            'color_wet': (216, 242, 254),
            'color_dry': (238, 236, 230),
            'topo_cpt_wet': 'light_sea_uniform',
            'topo_cpt_dry': 'light_land_uniform'}
    elif options.theme == 'topo':
        color_kwargs = {
            'illuminate_factor_land': options.illuminate_factor_land or 0.5,
            'illuminate_factor_ocean': options.illuminate_factor_ocean or 0.25}

    events = []
    if options.events_fn:
        events = model.load_events(options.events_fn)

    stations = []

    if options.stations_fn:
        stations = model.load_stations(options.stations_fn)

    if not (len(args) == 4 or (
            len(args) == 1 and (events or stations))):

        parser.print_help()
        sys.exit(1)

    if len(args) == 4:
        try:
            lat = float(args[0])
            lon = float(args[1])
            radius = float(args[2])*km
        except Exception:
            parser.print_help()
            sys.exit(1)
    else:
        lats, lons = latlon_arrays(stations+events)
        lat, lon = map(float, od.geographic_midpoint(lats, lons))
        radius = float(
            num.max(od.distance_accurate50m_numpy(lat, lon, lats, lons)))
        radius *= 1.1

    m = automap.Map(
        width=options.width,
        height=options.height,
        lat=lat,
        lon=lon,
        radius=radius,
        topo_resolution_max=options.topo_resolution_max,
        topo_resolution_min=options.topo_resolution_min,
        show_topo=options.show_topo,
        show_grid=options.show_grid,
        illuminate=options.illuminate,
        **color_kwargs)

    logger.debug('map configuration:\n%s' % str(m))

    if options.show_cities:
        m.draw_cities()

    if stations:
        lats = [s.lat for s in stations]
        lons = [s.lon for s in stations]

        m.gmt.psxy(
            in_columns=(lons, lats),
            S='t8p',
            G='black',
            *m.jxyr)

        for s in stations:
            m.add_label(s.lat, s.lon, '%s' % '.'.join(
                x for x in s.nsl() if x))

    if events:
        beachball_symbol = 'mt'
        beachball_size = 20.0
        for ev in events:
            if ev.moment_tensor is None:
                m.gmt.psxy(
                    in_rows=[[ev.lon, ev.lat]],
                    S='c12p',
                    G=gmtpy.color('scarletred2'),
                    W='1p,black',
                    *m.jxyr)

            else:
                devi = ev.moment_tensor.deviatoric()
                mt = devi.m_up_south_east()
                mt = mt / ev.moment_tensor.scalar_moment() \
                    * pmt.magnitude_to_moment(5.0)
                m6 = pmt.to6(mt)
                data = (ev.lon, ev.lat, 10) + tuple(m6) + (1, 0, 0)

                if m.gmt.is_gmt5():
                    kwargs = dict(
                        M=True,
                        S='%s%g' % (
                            beachball_symbol[0], beachball_size / gmtpy.cm))
                else:
                    kwargs = dict(
                        S='%s%g' % (
                            beachball_symbol[0], beachball_size*2 / gmtpy.cm))

                m.gmt.psmeca(
                    in_rows=[data],
                    G=gmtpy.color('chocolate1'),
                    E='white',
                    W='1p,%s' % gmtpy.color('chocolate3'),
                    *m.jxyr,
                    **kwargs)

    m.save(args[-1])


if __name__ == '__main__':
    main()
