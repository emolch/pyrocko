import unittest
import tempfile
import numpy as num
import urllib2
import logging
from pyrocko import util, trace, iris_ws
from pyrocko.fdsn import station as fdsn_station, ws as fdsn_ws

import common

logger = logging.getLogger('pyrocko.test.test_fdsn.py')

stt = util.str_to_time


class FDSNStationTestCase(unittest.TestCase):

    def test_read_samples(self):
        ok = False
        for fn in ['geeil.iris.xml', 'geeil.geofon.xml']:
            fpath = common.test_data_file(fn)
            x = fdsn_station.load_xml(filename=fpath)
            for network in x.network_list:
                assert network.code == 'GE'
                for station in network.station_list:
                    assert station.code == 'EIL'
                    for channel in station.channel_list:
                        assert channel.code[:2] == 'BH'
                        for stage in channel.response.stage_list:
                            ok = True

            assert ok

            pstations = x.get_pyrocko_stations()
            assert len(pstations) in (3, 4)
            for s in x.get_pyrocko_stations():
                assert len(s.get_channels()) == 3

            assert len(x.get_pyrocko_stations(
                time=stt('2010-01-15 10:00:00'))) == 1

            new = fdsn_station.FDSNStationXML.from_pyrocko_stations(pstations)
            assert len(new.get_pyrocko_stations()) in (3, 4)
            for s in new.get_pyrocko_stations():
                assert len(s.get_channels()) == 3

    def test_retrieve(self):
        for site in ['geofon', 'iris']:
            fsx = fdsn_ws.station(site=site,
                                  network='GE',
                                  station='EIL',
                                  level='channel')

            assert len(fsx.get_pyrocko_stations(
                time=stt('2010-01-15 10:00:00'))) == 1

    def test_read_big(self):
        for site in ['iris']:
            fpath = common.test_data_file('%s_1014-01-01_all.xml' % site)
            fdsn_station.load_xml(filename=fpath)

    def OFF_test_response(self):
        tmin = stt('2014-01-01 00:00:00')
        tmax = stt('2014-01-02 00:00:00')
        sx = fdsn_ws.station(
            site='iris',
            network='II',
            channel='?HZ',
            startbefore=tmin,
            endafter=tmax,
            level='channel', format='text', matchtimeseries=True)

        for nslc in sx.nslc_code_list:
            print nslc
            net, sta, loc, cha = nslc
            sxr = fdsn_ws.station(
                site='iris',
                network=net,
                station=sta,
                location=loc,
                channel=cha,
                startbefore=tmin,
                endafter=tmax,
                level='response', matchtimeseries=True)

            fi = iris_ws.ws_resp(
                network=net,
                station=sta,
                location=loc,
                channel=cha,
                tmin=tmin,
                tmax=tmax)

            _, fn = tempfile.mkstemp()
            fo = open(fn, 'w')
            while True:
                d = fi.read(1024)
                if not d:
                    break

                fo.write(d)

            fo.close()

            resp_sx = sxr.get_pyrocko_response(
                nslc, timespan=(tmin, tmax),
                fake_input_units='M/S')

            resp_er = trace.Evalresp(fn, target='vel', nslc_id=nslc, time=tmin)
            fmin = 0.001
            fmax = 100.

            for _, _, channel in sxr.iter_network_station_channels(
                    net, sta, loc, cha, timespan=(tmin, tmax)):
                if channel.response:
                    fmax = channel.sample_rate.value * 0.5

            f = num.exp(num.linspace(num.log(fmin), num.log(fmax), 500))
            try:
                t_sx = resp_sx.evaluate(f)
                t_er = resp_er.evaluate(f)
                import pylab as lab

                abs_dif = num.abs(num.abs(t_sx) - num.abs(t_er)) / num.max(
                    num.abs(t_er))

                mda = num.mean(abs_dif[f < 0.5*fmax])

                pha_dif = num.abs(num.angle(t_sx) - num.angle(t_er))

                mdp = num.mean(pha_dif[f < 0.5*fmax])

                print mda, mdp

                if mda > 0.03 or mdp > 0.04:
                    lab.gcf().add_subplot(2, 1, 1)
                    lab.plot(f, num.abs(t_sx), color='black')
                    lab.plot(f, num.abs(t_er), color='red')
                    lab.xscale('log')
                    lab.yscale('log')

                    lab.gcf().add_subplot(2, 1, 2)
                    lab.plot(f, num.angle(t_sx), color='black')
                    lab.plot(f, num.angle(t_er), color='red')
                    lab.xscale('log')
                    lab.show()

                else:
                    print 'ok'
            except:
                print 'failed: ', nslc

    def test_url_alive(self):
        '''
        Test urls which are used as references in pyrocko if they still exist.
        '''
        to_check = [
            ('http://nappe.wustl.edu/antelope/css-formats/wfdisc.htm',
             'pyrocko.css'),
            ('http://www.ietf.org/timezones/data/leap-seconds.list',
             'pyrocko.config'),
            ('http://stackoverflow.com/questions/2417794/', 'cake_plot'),
            ('http://igppweb.ucsd.edu/~gabi/rem.html', 'crust2x2_data'),
            ('http://kinherd.org/pyrocko_data/gsc20130501.txt', 'crustdb'),
            ('http://download.geonames.org/export/dump/', 'geonames'),
            ('http://emolch.github.io/gmtpy/', 'gmtpy'),
            ('http://www.apache.org/licenses/LICENSE-2.0', 'kagan.py'),
            ('http://www.opengis.net/kml/2.2', 'model'),
            ('http://maps.google.com/mapfiles/kml/paddle/S.png', 'model'),
            ('http://de.wikipedia.org/wiki/Orthodrome', 'orthodrome'),
            ('http://peterbird.name/oldFTP/PB2002', 'tectonics'),
            ('http://gsrm.unavco.org/model', 'tectonics'),
            ('http://stackoverflow.com/questions/19332902/', 'util'),
        ]

        for url in to_check:
            try:
                fdsn_ws._request(url[0])
            except urllib2.HTTPError as e:
                logger.warn('%s - %s referenced in pyrocko.%s' %
                            (e, url[0], url[1]))


if __name__ == '__main__':
    util.setup_logging('test_fdsn', 'warning')
    unittest.main()
