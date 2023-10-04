# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from ..snuffling import Snuffling, Param, Choice
from ..marker import EventMarker

from pyrocko.client import catalog, fdsn
from pyrocko.io import quakeml


class CatalogSearch(Snuffling):

    def help(self):
        return '''
<html>
<head>
<style type="text/css">
body { margin-left:10px };
</style>
</head>
<body>
    <h1 align="center">Catalog Search</h1>
<p>
    Retrieve event data from online catalogs.
</p>
    <b>Parameters:</b><br />
    <b>&middot; Catalog</b>  -  Online database to search for events.<br />
    <b>&middot; Min Magnitude</b>  -
    Only consider events with magnitude greater than chosen..<br />
</p>
<p>
    Data from the folowing catalogs can be retrieved:<br />
    &middot;
    <a href="http://geofon.gfz-potsdam.de/eqinfo/list.php">GEOFON</a><br />
    &middot;
    <a href="http://www.globalcmt.org/">Global CMT</a><br />
    &middot;
    <a href="http://earthquake.usgs.gov/regional/neic/">USGS</a><br />
</p>
<p>
    The USGS catalog allows to destinguish between 'Preliminary
    Determination of Epicenters' (PDE) and 'Quick Epicenters Determination'
    (PDE-Q). Latter one includes events of approximately the last six
    weeks. For detailed information about both catalog versions have a look
    at <a href="http://earthquake.usgs.gov/research/data/pde.php">'The
    Preliminary Determination of Epicenters (PDE) Bulletin'</a>.
</p>
</body>
</html>
        '''

    def setup(self):

        self.catalogs = {
            'GEOFON': catalog.Geofon(),
            'USGS/NEIC US': catalog.USGS('us'),
            'Global-CMT': catalog.GlobalCMT(),
            'Saxony (Uni-Leipzig)': catalog.Saxony(),
            }

        fdsn_has_events = ['ISC', 'SCEDC', 'NCEDC', 'IRIS', 'GEONET']

        catkeys = sorted(self.catalogs.keys())
        catkeys.extend(fdsn_has_events)

        self.set_name('Catalog Search')
        self.add_parameter(Choice('Catalog', 'catalog', catkeys[0], catkeys))
        self.add_parameter(Param('Min Magnitude', 'magmin', 0, 0, 10))
        self.set_live_update(False)

    def call(self):

        viewer = self.get_viewer()
        tmin, tmax = viewer.get_time_range()

        cat = self.catalogs.get(self.catalog, None)
        if cat:
            event_names = cat.get_event_names(
                time_range=(tmin, tmax),
                magmin=self.magmin)
            for event_name in event_names:
                event = cat.get_event(event_name)
                marker = EventMarker(event)
                self.add_markers([marker])
        else:
            request = fdsn.event(
                starttime=tmin, endtime=tmax, site=self.catalog.lower(),
                minmagnitude=self.magmin)

            qml = quakeml.QuakeML.load_xml(request)
            events = qml.get_pyrocko_events()

            for event in events:
                marker = EventMarker(event)
                self.add_markers([marker])


def __snufflings__():

    return [CatalogSearch()]
