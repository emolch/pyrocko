# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from pyrocko.gui.qt_compat import qc, qg
import os
from os import path as op
import sys

import numpy as num
import logging
import posixpath
import shutil
import socket

if sys.version_info >= (3, 0):  # noqa
    from http.server import HTTPServer, SimpleHTTPRequestHandler
else:  # noqa
    from BaseHTTPServer import HTTPServer
    from SimpleHTTPServer import SimpleHTTPRequestHandler

from pyrocko.gui.snuffler.snuffling import Snuffling, Switch, Choice, \
    NoViewerSet
from pyrocko.guts import dump_xml
from pyrocko import util, model, orthodrome as ortho
from pyrocko.gui import util as gui_util
from pyrocko import moment_tensor
from pyrocko.plot.automap import Map
from pyrocko.util import unquote
from .xmlMarker import XMLEventMarker, EventMarkerList, XMLStationMarker
from .xmlMarker import StationMarkerList, MarkerLists


g_counter = 0

logger = logging.getLogger('pyrocko.snuffling.map')


def port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0


def get_port():
    port = 9998
    while port < 11000:
        if port_in_use(port):
            port += 1
        else:
            break
    else:
        raise Exception('No free port found')

    return port


def get_magnitude(event):
    if event.magnitude:
        mag = event.magnitude
    elif event.moment_tensor:
        mag = event.moment_tensor.moment_magnitude()
    else:
        mag = 0.
    return float(mag)


def convert_event_marker(marker):
    ev = marker.get_event()
    depth = None
    if ev is not None:
        depth = ev.depth
    else:
        return None

    if depth is None:
        depth = 0.0
    ev_name = ev.name if ev.name else '(Event)'
    xmleventmarker = XMLEventMarker(
        eventname=ev_name,
        longitude=float(ev.effective_lon),
        latitude=float(ev.effective_lat),
        origintime=util.time_to_str(ev.time),
        depth=float(depth),
        magnitude=float(get_magnitude(ev)),
        active=['no', 'yes'][marker.active])

    return xmleventmarker


class RootedHTTPServer(HTTPServer):

    def __init__(self, base_path, *args, **kwargs):
        HTTPServer.__init__(self, *args, **kwargs)
        self.RequestHandlerClass.base_path = base_path


class RootedHTTPRequestHandler(SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        logger.debug('%s - - [%s] %s\n' % (
            self.client_address[0],
            self.log_date_time_string(),
            format % args))

    def translate_path(self, path):
        path = posixpath.normpath(unquote(path))
        words = path.split('/')
        words = filter(None, words)
        path = self.base_path
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir):
                continue
            path = os.path.join(path, word)
        return path


class FileServingWorker(qc.QObject):

    def __init__(self, dirname, *args, **kwargs):
        super(FileServingWorker, self).__init__(*args, **kwargs)
        self.dirname = dirname
        self.httpd = None

    @qc.pyqtSlot(int)
    def run(self, port):
        server_address = ('', port)
        self.httpd = RootedHTTPServer(
            self.dirname, server_address, RootedHTTPRequestHandler)
        sa = self.httpd.socket.getsockname()
        logger.debug('Serving on port %s' % sa[1])
        self.httpd.serve_forever()

    @qc.pyqtSlot()
    def stop(self):
        if self.httpd:
            logger.debug('Shutdown server')
            self.httpd.shutdown()
            self.httpd.socket.close()


class SignalProxy(qc.QObject):
    content_to_serve = qc.pyqtSignal(int)


class MapMaker(Snuffling):

    def help(self):
        return '''
<html>
<body>
<h1>Map event and stations with OpenStreetMap or Google Maps</h1>
<p>
Invokes the standard browser if "Open in external browser" is selected.
Some browsers do not allow javascript to open and read the xml-file
containing the necessary information due to the "Same-Origin-Policy".
In that case you need to reset your standard browser. I.e.: Firefox on
Linux do: <tt>xdg-settings set default-web-browser firefox.desktop</tt>
</p>
<p>
Clicking one of the plate boundary lines shows a reference regarding that
plate boundary.
</p>
<p>
The plate boundary database is based on the work done by Peter Bird, who
kindly permitted usage. <br>
<p>
This snuffling can also be called from the command line, if it is stored in
the default pyrocko location under $HOME/.snufflings<br>
e.g.:
<p>
<code>
python $HOME/.snufflings/map/snuffling.py --stations=stations.pf
--events=events_test.pf
</code>
<h2>References</h2>
<i>50. Bird, P. (2003) An updated digital model of plate
boundaries, Geochemistry Geophysics Geosystems, 4(3), 1027,
doi:10.1029/2001GC000252.
</i>
</p>
<br>
Also available at
<a href="http://peterbird.name/publications/2003_PB2002/2003_PB2002.htm">
    http://www.peterbird.name</a>
<p>
Please note, that in the current implementation the orogens (cross-hatched
areas in
<a href="http://peterbird.name/publications/2003_PB2002/Figure_01.gif">
figure 1</a>)
are not distinguished from plate boundaries.  The orogens are meant to
mark areas where the plate model is known to be incomplete
(and/or inapplicable).<br>
This matter will be pointed out in future releases of this snuffling.
</body>
</html>
'''

    def setup(self):
        self.set_name('Map')
        self.add_parameter(Switch('Only active event', 'only_active', False))
        self.add_parameter(Switch('Open in external browser',
                                  'open_external', False))
        self.add_parameter(Choice('Provider', 'map_kind', 'OpenStreetMap',
                                  ['OpenStreetMap', 'GMT', 'Google Maps']))

        self.set_live_update(False)
        self.figcount = 0
        self.thread = qc.QThread()
        self.marker_tempdir = self.tempdir()

        self.file_serving_worker = FileServingWorker(self.marker_tempdir)
        self.file_serving_worker.moveToThread(self.thread)
        self.data_proxy = SignalProxy()
        self.data_proxy.content_to_serve.connect(
            self.file_serving_worker.run)
        self.thread.start()
        self.port = None

        self.viewer_connected = False

    def call(self):
        if self.port is None:
            self.port = get_port()

        if not self.viewer_connected:
            self.get_viewer().about_to_close.connect(
                self.file_serving_worker.stop)
            self.viewer_connected = True

        self.cleanup()

        try:
            viewer = self.get_viewer()
            cli_mode = False
        except NoViewerSet:
            viewer = None
            cli_mode = True

        if not cli_mode:
            if self.only_active:
                _, active_stations = \
                    self.get_active_event_and_stations()
            else:
                active_stations = viewer.stations.values()
        elif cli_mode:
            active_stations = self.stations

        station_list = []
        if active_stations:
            for stat in active_stations:
                is_blacklisted = util.match_nslc(viewer.blacklist, stat.nsl())
                if (viewer and not is_blacklisted) or cli_mode:
                    xml_station_marker = XMLStationMarker(
                        nsl='.'.join(stat.nsl()),
                        longitude=float(stat.effective_lon),
                        latitude=float(stat.effective_lat),
                        active='yes')

                    station_list.append(xml_station_marker)

        active_station_list = StationMarkerList(stations=station_list)

        if self.only_active:
            markers = [viewer.get_active_event_marker()]
        else:
            if cli_mode:
                markers = self.markers
            else:
                markers = self.get_selected_markers()
                if len(markers) == 0:
                    tmin, tmax = self.get_selected_time_range(fallback=True)
                    markers = [m for m in viewer.get_markers()
                               if isinstance(m, gui_util.EventMarker) and
                               m.tmin >= tmin and m.tmax <= tmax]

        ev_marker_list = []
        for m in markers:
            if not isinstance(m, gui_util.EventMarker):
                continue
            xmleventmarker = convert_event_marker(m)
            if xmleventmarker is None:
                continue
            ev_marker_list.append(xmleventmarker)

        event_list = EventMarkerList(events=ev_marker_list)
        event_station_list = MarkerLists(
            station_marker_list=active_station_list,
            event_marker_list=event_list)

        event_station_list.validate()
        if self.map_kind != 'GMT':
            tempdir = self.marker_tempdir
            if self.map_kind == 'Google Maps':
                map_fn = 'map_googlemaps.html'
            elif self.map_kind == 'OpenStreetMap':
                map_fn = 'map_osm.html'

            url = 'http://localhost:' + str(self.port) + '/%s' % map_fn

            files = ['loadxmldoc.js', 'map_util.js', 'plates.kml', map_fn]
            snuffling_dir = op.dirname(op.abspath(__file__))
            for entry in files:
                shutil.copy(os.path.join(snuffling_dir, entry),
                            os.path.join(tempdir, entry))
            logger.debug('copied data to %s' % tempdir)
            markers_fn = os.path.join(self.marker_tempdir, 'markers.xml')
            self.data_proxy.content_to_serve.emit(self.port)
            dump_xml(event_station_list, filename=markers_fn)

            if self.open_external:
                qg.QDesktopServices.openUrl(qc.QUrl(url))
            else:
                global g_counter
                g_counter += 1
                self.web_frame(
                    url,
                    name='Map %i (%s)' % (g_counter, self.map_kind))
        else:
            lats_all = []
            lons_all = []

            slats = []
            slons = []
            slabels = []
            for s in active_stations:
                slats.append(s.effective_lat)
                slons.append(s.effective_lon)
                slabels.append('.'.join(s.nsl()))

            elats = []
            elons = []
            elats = []
            elons = []
            psmeca_input = []
            markers = self.get_selected_markers()
            for m in markers:
                if isinstance(m, gui_util.EventMarker):
                    e = m.get_event()
                    elats.append(e.effective_lat)
                    elons.append(e.effective_lon)
                    if e.moment_tensor is not None:
                        mt = e.moment_tensor.m6()
                        psmeca_input.append(
                            (e.effective_lon, e.effective_lat,
                             e.depth/1000., mt[0], mt[1],
                             mt[2], mt[3], mt[4], mt[5],
                             1., e.effective_lon, e.effective_lat, e.name))
                    else:
                        if e.magnitude is None:
                            moment = -1.
                        else:
                            moment = moment_tensor.magnitude_to_moment(
                                e.magnitude)
                            psmeca_input.append(
                                (e.effective_lon, e.effective_lat,
                                 e.depth/1000.,
                                 moment/3., moment/3., moment/3.,
                                 0., 0., 0., 1.,
                                 e.effective_lon, e.effective_lat, e.name))

            lats_all.extend(elats)
            lons_all.extend(elons)
            lats_all.extend(slats)
            lons_all.extend(slons)

            lats_all = num.array(lats_all)
            lons_all = num.array(lons_all)

            if len(lats_all) == 0:
                return

            center_lat, center_lon = ortho.geographic_midpoint(
                lats_all, lons_all)
            ntotal = len(lats_all)
            clats = num.ones(ntotal) * center_lat
            clons = num.ones(ntotal) * center_lon
            dists = ortho.distance_accurate50m_numpy(
                clats, clons, lats_all, lons_all)

            maxd = num.max(dists) or 0.
            m = Map(
                lat=center_lat, lon=center_lon,
                radius=max(10000., maxd) * 1.1,
                width=35, height=25,
                show_grid=True,
                show_topo=True,
                color_dry=(238, 236, 230),
                topo_cpt_wet='light_sea_uniform',
                topo_cpt_dry='light_land_uniform',
                illuminate=True,
                illuminate_factor_ocean=0.15,
                show_rivers=False,
                show_plates=False)

            m.gmt.psxy(in_columns=(slons, slats), S='t15p', G='black', *m.jxyr)
            for i in range(len(active_stations)):
                m.add_label(slats[i], slons[i], slabels[i])

            m.gmt.psmeca(
                in_rows=psmeca_input, S='m1.0', G='red', C='5p,0/0/0', *m.jxyr)

            tmpdir = self.tempdir()

            self.outfn = os.path.join(tmpdir, '%i.png' % self.figcount)
            m.save(self.outfn)
            f = self.pixmap_frame(self.outfn)  # noqa
            # f = self.svg_frame(self.outfn, name='XX')

    def configure_cli_parser(self, parser):

        parser.add_option(
            '--events',
            dest='events_filename',
            default=None,
            metavar='FILENAME',
            help='Read markers from FILENAME')

        parser.add_option(
            '--markers',
            dest='markers_filename',
            default=None,
            metavar='FILENAME',
            help='Read markers from FILENAME')

        parser.add_option(
            '--stations',
            dest='stations_filename',
            default=None,
            metavar='FILENAME',
            help='Read stations from FILENAME')

        parser.add_option(
            '--provider',
            dest='map_provider',
            default='google',
            help='map provider [google | osm] (default=osm)')

    def __del__(self):
        self.file_serving_worker.stop()
        self.thread.quit()
        self.thread.wait()


def __snufflings__():
    return [MapMaker()]


if __name__ == '__main__':
    util.setup_logging('map.py', 'info')
    s = MapMaker()
    options, args, parser = s.setup_cli()
    s.markers = []

    if options.stations_filename:
        stations = model.load_stations(options.stations_filename)
        s.stations = stations
    else:
        s.stations = None

    if options.events_filename:
        events = model.load_events(filename=options.events_filename)
        markers = [gui_util.EventMarker(e) for e in events]
        s.markers.extend(markers)

    if options.markers_filename:
        markers = gui_util.load_markers(options.markers_filename)
        s.markers.extend(markers)
    s.open_external = True
    mapmap = {'google': 'Google Maps', 'osm': 'OpenStreetMap'}
    s.map_kind = mapmap[options.map_provider]
    s.call()
