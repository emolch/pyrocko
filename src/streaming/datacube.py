# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Live stream reader for `DiGOS DATA-CUBE³
<https://digos.eu/the-seismic-data-recorder/>`_ digitizers
'''

import time
import logging
import numpy as num
from pyrocko import util, trace

logger = logging.getLogger('pyrocko.streaming.datacube')

cube_rates = num.array([50., 100., 200., 400., 800.], dtype=float)


def quotechars(chars):
    return ''.join(['.', chr(c)][chr(c).isalnum()] for c in chars)


def hexdump(chars, sep=' ', width=16):
    while chars:
        line = chars[:width]
        chars = chars[width:]
        line = line.ljust(width, b'\000')

        print('%s%s%s' % (
            sep.join('%02x' % c for c in line),
            sep, quotechars(line)))


def read_wait(s, nread):
    buf = b''
    while True:
        buf += s.read(nread - len(buf))
        if len(buf) == nread:
            return buf

        logger.info('Incomplete read from serial port. Waiting...')
        time.sleep(1.0)


def read_blocktype(s):
    buf = read_wait(s, 1)
    return buf[0] >> 4


def determine_nchannels(s):
    while True:
        datablock_starts = []
        for i in range(1024):
            datablock_starts.append(read_blocktype(s) in (8, 9))

        if len(datablock_starts) > 50:
            dd = num.diff(num.where(datablock_starts)[0]) - 1
            dd = dd[dd % 4 == 0]

            if dd.size > 50:
                nchannels = dd // 4
                nchannels_hist, _ = num.histogram(nchannels, num.arange(5)-1)
                nchannels = num.argmax(nchannels_hist)
                if nchannels_hist[nchannels] > 50:
                    return nchannels

        logger.info('Could not determine number of channels. Retrying...')


def sync(s, nchannels, nok_want=10):
    nok = 0
    while nok < nok_want:
        blocktype = read_blocktype(s)
        if blocktype in (8, 9):
            read_wait(s, 4*nchannels)
            nok += 1
        elif blocktype == 10:
            read_wait(s, 79)
            nok += 1
        else:
            nok = 0


def read_sample(s, nchannels):

    b = read_wait(s, nchannels*4)

    sample = []

    for i in range(nchannels):
        v = b[i*4 + 0] << 17
        v += b[i*4 + 1] << 10
        v += b[i*4 + 2] << 3
        v += b[i*4 + 3]
        v -= (v & 0x800000) << 1
        sample.append(v)

    return sample


class SerialCubeError(Exception):
    pass


class SerialCube(object):

    def __init__(
            self,
            device='/dev/ttyUSB0',
            network='',
            station='CUBE',
            location='',
            timeout=5.0):

        # fixed
        self._network = network
        self._station = station
        self._location = location
        self._device = device
        self._timeout = timeout
        self._baudrate = 115200
        self._nsamples_buffer = 100

        # state
        self._init_state()

    def _init_state(self):
        self._serial = None
        self._nchannels = None
        self._tstart = None
        self._rate = None
        self._buffer = None
        self._isamples_buffer = None
        self._nsamples_read = 0

    def acquisition_start(self):
        import serial
        assert self._serial is None
        try:
            self._serial = serial.Serial(
                port=self._device,
                baudrate=self._baudrate,
                timeout=self._timeout)

        except serial.serialutil.SerialException as e:
            raise SerialCubeError(
                'Opening serial interface failed: %s' % str(e))

        nchannels = determine_nchannels(self._serial)
        logger.info('Number of channels: %i' % nchannels)

        sync(self._serial, nchannels)
        self._nchannels = nchannels

    def acquisition_stop(self):
        assert self._serial is not None
        self._serial.close()
        self._init_state()

    def process(self):
        assert self._serial is not None

        blocktype = read_blocktype(self._serial)
        if blocktype in (8, 9):
            if self._buffer is None:
                self._buffer = num.zeros(
                    (self._nsamples_buffer, self._nchannels),
                    dtype=num.float32)
                if self._tstart is None:
                    self._tstart = time.time()

                self._isamples_buffer = 0

            self._buffer[self._isamples_buffer, :] = read_sample(
                self._serial, self._nchannels)

            self._isamples_buffer += 1

        elif blocktype == 10:
            read_wait(self._serial, 79)

        if self._isamples_buffer == self._nsamples_buffer:
            if self._rate is None:
                tdur = time.time() - self._tstart
                assert tdur > 0.
                rate_approx = self._nsamples_buffer / tdur
                self._rate = cube_rates[
                    num.argmin(num.abs(rate_approx - cube_rates))]

                logger.info('Sample rate [Hz]: %g' % self._rate)

            deltat = 1.0 / self._rate
            t = self._tstart + self._nsamples_read * deltat
            for ichannel in range(self._nchannels):
                tr = trace.Trace(
                    self._network,
                    self._station,
                    self._location,
                    'p%i' % ichannel,
                    ydata=self._buffer[:, ichannel],
                    tmin=t,
                    deltat=1.0/self._rate)

                self.got_trace(tr)

            self._nsamples_read += self._nsamples_buffer
            self._buffer = None
            self._isamples_buffer = None

    def got_trace(self, tr):
        logger.info(
            'Got trace from DATA-CUBE: %s, mean: %g, std: %g' % (
                tr.summary, num.mean(tr.ydata), num.std(tr.ydata)))


def main():
    import sys
    util.setup_logging('main', 'info')
    if len(sys.argv) != 2:
        sys.exit('usage: python -m pyrocko.streaming.datacube DEVICE')

    device = sys.argv[1]
    cs = SerialCube(device)
    try:
        cs.acquisition_start()
    except SerialCubeError as e:
        sys.exit(str(e))

    try:
        while True:
            cs.process()

    except KeyboardInterrupt:
        pass

    finally:
        cs.acquisition_stop()


if __name__ == '__main__':
    main()
