# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import

import calendar
import logging
import numpy as num
from scipy import signal

from pyrocko import util, trace

unpack_fixed = util.unpack_fixed

logger = logging.getLogger('pyrocko.io.seisan_response')

d2r = num.pi/180.


class SeisanResponseFileError(Exception):
    pass


class SeisanResponseFile(object):

    def __init__(self):
        pass

    def read(self, filename):

        f = open(filename, 'rb')
        line = f.readline()
        line = str(line.decode('ascii'))

        station, component, century, deltayear, doy, month, day, hr, mi, sec \
            = unpack_fixed(
                'a5,a4,@1,i2,x1,i3,x1,i2,x1,i2,x1,i2,x1,i2,x1,f6',
                line[0:35],
                lambda s: {' ': 1900, '0': 1900, '1': 2000}[s])

        # is_accelerometer = line[6] == 'A'

        latitude, longitude, elevation, filetype, cf_flag = \
            unpack_fixed(
                'f8?,x1,f9?,x1,f5?,x2,@1,a1',
                line[50:80],
                lambda s: {
                    ' ': 'gains-and-filters',
                    't': 'tabulated',
                    'p': 'poles-and-zeros'}[s.lower()])

        line = f.readline()
        line = str(line.decode('ascii'))

        comment = line.strip()
        tmin = util.to_time_float(calendar.timegm(
            (century+deltayear, 1, doy, hr, mi, int(sec)))) + sec-int(sec)

        if filetype == 'gains-and-filters':

            line = f.readline()
            line = str(line.decode('ascii'))

            period, damping, sensor_sensitivity, amplifier_gain, \
                digitizer_gain, gain_1hz, filter1_corner, filter1_order, \
                filter2_corner, filter2_order = unpack_fixed(
                    'f8,f8,f8,f8,f8,f8,f8,f8,f8,f8',
                    line)

            filter_defs = [
                filter1_corner,
                filter1_order,
                filter2_corner,
                filter2_order]

            line = f.readline()
            line = str(line.decode('ascii'))

            filter_defs.extend(
                unpack_fixed('f8,f8,f8,f8,f8,f8,f8,f8,f8,f8', line))

            filters = []
            for order, corner in zip(filter_defs[1::2], filter_defs[0::2]):
                if order != 0.0:
                    filters.append((order, corner))

        if filetype in ('gains-and-filters', 'tabulated'):
            data = ([], [], [])
            for iy in range(3):
                for ix in range(3):
                    line = f.readline()
                    line = str(line.decode('ascii'))

                    data[ix].extend(unpack_fixed(
                        'f8,f8,f8,f8,f8,f8,f8,f8,f8,f8', line))

            response_table = num.array(data, dtype=num.float)

        if filetype == 'poles-and-zeros':
            assert False, 'poles-and-zeros file type not implemented yet ' \
                          'for seisan response file format'

        f.close()

        if num.all(num.abs(response_table[2]) <= num.pi):
            logger.warning(
                'assuming tabulated phases are given in radians instead of '
                'degrees')

            cresp = response_table[1] * (
                num.cos(response_table[2])
                + 1.0j*num.sin(response_table[2]))
        else:
            cresp = response_table[1] * (
                num.cos(response_table[2]*d2r)
                + 1.0j*num.sin(response_table[2]*d2r))

        self.station = station
        self.component = component
        self.tmin = tmin
        self.latitude = latitude
        self.longitude = longitude
        self.elevation = elevation
        self.filetype = filetype
        self.comment = comment
        self.period = period
        self.damping = damping
        self.sensor_sensitivity = sensor_sensitivity
        self.amplifier_gain = amplifier_gain
        self.digitizer_gain = digitizer_gain
        self.gain_1hz = gain_1hz
        self.filters = filters

        self.sampled_response = trace.SampledResponse(
            response_table[0], cresp)

        self._check_tabulated_response(filename=filename)

    def response(self, freqs, method='from-filetype', type='displacement'):

        freqs = num.asarray(freqs)
        want_scalar = False
        if freqs.ndim == 0:
            freqs = num.array([freqs])
            want_scalar = True

        if method == 'from-filetype':
            method = self.filetype

        if method == 'gains-and-filters':
            dresp = self._response_prototype_and_filters(freqs) \
                / abs(self._response_prototype_and_filters([1.0])[0]) \
                * self.gain_1hz

        elif method == 'tabulated':
            dresp = self._response_tabulated(freqs) \
                / abs(self._response_tabulated([1.0])[0]) * self.gain_1hz

        elif method == 'poles-and-zeros':
            raise Exception(
                'fix me! poles-and-zeros response in seisan is broken: where '
                'should the "normalization" come from?')

            # dresp = self._response_from_poles_and_zeros(freqs) *normalization

        elif method == 'gains':
            dresp = num.ones(freqs.size) * self.gain_total() * 1.0j * 2. \
                * num.pi * freqs

        else:
            assert False, 'invalid response method specified'

        if type == 'velocity':
            dresp /= 1.0j * 2. * num.pi * freqs

        if want_scalar:
            return dresp[0]
        else:
            return dresp

    def gain_total(self):
        return self.sensor_sensitivity * 10.**(self.amplifier_gain/20.) \
            * self.digitizer_gain

    def _prototype_response_velocity(self, s):
        omega0 = 2. * num.pi / self.period
        return s**2/(omega0**2 + s**2 + 2.0*s*omega0*self.damping)

    def _response_prototype_and_filters(self, freqs):
        freqs = num.asarray(freqs, dtype=num.float)
        iomega = 1.0j * 2. * num.pi * freqs

        trans = iomega * self._prototype_response_velocity(iomega)

        for (order, corner) in self.filters:
            if order < 0. or corner < 0.:
                b, a = signal.butter(
                    abs(order), [abs(corner)], btype='high', analog=1)
            else:
                b, a = signal.butter(
                    order, [corner], btype='low', analog=1)

            trans *= signal.freqs(b, a, freqs)[1]

        return trans

    def _response_tabulated(self, freqs):
        freqs = num.asarray(freqs, dtype=num.float)
        return self.sampled_response.evaluate(freqs)

    def _response_from_poles_and_zeros(self, freqs):
        assert False, 'poles-and-zeros file type not implemented yet for ' \
                      'seisan response file format'
        return None

    def _check_tabulated_response(self, filename='?'):
        if self.filetype == 'gains-and-filters':
            freqs = self.sampled_response.frequencies()

            trans_gaf = self.response(freqs, method='gains-and-filters')
            atrans_gaf = num.abs(trans_gaf)

            trans_tab = self.response(freqs, method='tabulated')
            atrans_tab = num.abs(trans_tab)

            if num.any(num.abs(atrans_gaf-atrans_tab)
                       / num.abs(atrans_gaf+atrans_tab) > 1./100.):

                logger.warning(
                    'inconsistent amplitudes in tabulated response '
                    '(in file "%s") (max |a-b|/|a+b| is %g' % (
                        filename,
                        num.amax(num.abs(atrans_gaf-atrans_tab)
                                 / abs(atrans_gaf+atrans_tab))))

            else:
                if num.any(num.abs(trans_gaf-trans_tab)
                           > abs(trans_gaf+trans_tab)/100.):

                    logger.warning(
                        'inconsistent phase values in tabulated response '
                        '(in file "%s"' % filename)

    def __str__(self):

        return '''--- Seisan Response File ---
station: %s
component: %s
start time: %s
latitude: %f
longitude: %f
elevation: %f
filetype: %s
comment: %s
sensor period: %g
sensor damping: %g
sensor sensitivity: %g
amplifier gain: %g
digitizer gain: %g
gain at 1 Hz: %g
filters: %s
''' % (self.station, self.component, util.time_to_str(self.tmin),
            self.latitude, self.longitude, self.elevation, self.filetype,
            self.comment, self.period, self.damping, self.sensor_sensitivity,
            self.amplifier_gain, self.digitizer_gain, self.gain_1hz,
            self.filters)

    def plot_amplitudes(self, filename_pdf, type='displacement'):

        from pyrocko.plot import gmtpy

        p = gmtpy.LogLogPlot()
        f = self.sampled_response.frequencies()
        atab = num.abs(self.response(f, method='tabulated', type=type))
        acom = num.abs(self.response(f, method='gains-and-filters', type=type))
        aconst = num.abs(self.response(f, method='gains', type=type))

        p.plot((f, atab), '-W2p,red')
        p.plot((f, acom), '-W1p,blue')
        p.plot((f, aconst), '-W1p,green')
        p.save(filename_pdf)

    def plot_phases(self, filename_pdf, type='displacement'):

        from pyrocko.plot import gmtpy

        p = gmtpy.LogLinPlot()
        f = self.sampled_response.frequencies()
        atab = num.unwrap(num.angle(self.response(
            f, method='tabulated', type=type))) / d2r
        acom = num.unwrap(num.angle(self.response(
            f, method='gains-and-filters', type=type))) / d2r
        aconst = num.unwrap(num.angle(self.response(
            f, method='gains', type=type))) / d2r

        p.plot((f, atab), '-W2p,red')
        p.plot((f, acom), '-W1p,blue')
        p.plot((f, aconst), '-W1p,green')
        p.save(filename_pdf)
