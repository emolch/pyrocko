# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Live stream reader for a few USB/serial digitizers.
'''

import time
import logging
import math
import numpy as num
from scipy import stats
import threading
try:
    import queue
except ImportError:
    import Queue as queue

from pyrocko import trace, util

logger = logging.getLogger('pyrocko.streaming.serial_hamster')


class QueueIsEmpty(Exception):
    pass


class Queue(object):
    def __init__(self, nmax):
        self.nmax = nmax
        self.queue = []

    def push_back(self, val):
        self.queue.append(val)
        while len(self.queue) > self.nmax:
            self.queue.pop(0)

    def mean(self):
        if not self.queue:
            raise QueueIsEmpty()
        return sum(self.queue)/float(len(self.queue))

    def median(self):
        if not self.queue:
            raise QueueIsEmpty()
        n = len(self.queue)
        s = sorted(self.queue)
        if n % 2 != 0:
            return s[n//2]
        else:
            return (s[n//2-1]+s[n//2])/2.0

    def add(self, w):
        self.queue = [v+w for v in self.queue]

    def empty(self):
        self.queue[:] = []

    def __len__(self):
        return len(self.queue)

    def capacity(self):
        return self.nmax

    def __str__(self):
        return ' '.join('%g' % v for v in self.queue)


class SerialHamsterError(Exception):
    pass


class SerialHamster(object):

    def __init__(
            self, port=0, baudrate=9600, timeout=5, buffersize=128,
            start_string=None,
            network='', station='TEST', location='', channels=['Z'],
            disallow_uneven_sampling_rates=True,
            deltat=None,
            deltat_tolerance=0.01,
            in_file=None,
            lookback=5,
            min_detection_size=5,
            tune_to_quickones=True):

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.buffersize = buffersize
        self.ser = None
        self.values = [[]]*len(channels)
        self.times = []
        self.fixed_deltat = deltat
        self.deltat = None
        self.deltat_tolerance = deltat_tolerance
        self.tmin = None
        self.previous_deltats = Queue(nmax=lookback)
        self.previous_tmin_offsets = Queue(nmax=lookback)
        self.ncontinuous = 0
        self.disallow_uneven_sampling_rates = disallow_uneven_sampling_rates
        self.network = network
        self.station = station
        self.location = location
        self.channels = channels
        self.in_file = in_file    # for testing
        self.listeners = []
        self.quit_requested = False
        self.tune_to_quickones = tune_to_quickones
        self.start_string = start_string

        self.min_detection_size = min_detection_size

    def add_listener(self, obj):
        self.listeners.append(util.smart_weakref(obj))

    def clear_listeners(self):
        self.listeners = []

    def acquisition_start(self):
        if self.ser is not None:
            self.stop()

        logger.debug(
            'Starting serial hamster (port=%s, baudrate=%i, timeout=%f)'
            % (self.port, self.baudrate, self.timeout))

        if self.in_file is None:
            import serial
            try:
                self.ser = serial.Serial(
                    port=self.port,
                    baudrate=self.baudrate,
                    timeout=self.timeout)

                self.send_start()

            except serial.serialutil.SerialException:
                raise SerialHamsterError(
                    'Cannot open serial port %s' % self.port)
        else:
            self.ser = self.in_file

    def send_start(self):
        ser = self.ser
        if self.start_string is not None:
            ser.write(self.start_string.encode('ascii'))

    def acquisition_stop(self):
        if self.ser is not None:
            logger.debug('Stopping serial hamster')
            if self.in_file is None:
                self.ser.close()
            self.ser = None
        self._flush_buffer()

    def acquisition_request_stop(self):
        pass

    def process(self):
        if self.ser is None:
            return False

        try:
            line = self.ser.readline()
            if line == '':
                raise SerialHamsterError(
                    'Failed to read from serial port %s' % self.port)
        except Exception:
            raise SerialHamsterError(
                'Failed to read from serial port %s' % self.port)

        t = time.time()

        for tok in line.split():
            try:
                val = float(tok)
            except Exception:
                logger.warning('Got something unexpected on serial line. ' +
                               'Current line: "%s". ' % line +
                               'Could not convert string to float: "%s"' % tok)
                continue

            self.values[0].append(val)
            self.times.append(t)

            if len(self.values[0]) >= self.buffersize:
                self._flush_buffer()

        return True

    def _regression(self, t):
        toff = t[0]
        t = t-toff
        i = num.arange(t.size, dtype=float)
        r_deltat, r_tmin, r, tt, stderr = stats.linregress(i, t)
        if self.tune_to_quickones:
            for ii in range(2):
                t_fit = r_tmin+r_deltat*i
                quickones = num.where(t < t_fit)
                if quickones[0].size < 2:
                    break
                i = i[quickones]
                t = t[quickones]
                r_deltat, r_tmin, r, tt, stderr = stats.linregress(i, t)

        return r_deltat, r_tmin+toff

    def _flush_buffer(self):

        if len(self.times) < self.min_detection_size:
            return

        t = num.array(self.times, dtype=float)
        r_deltat, r_tmin = self._regression(t)

        if self.disallow_uneven_sampling_rates:
            r_deltat = 1./round(1./r_deltat)

        # check if deltat is consistent with expectations
        if self.deltat is not None and self.fixed_deltat is None:
            try:
                p_deltat = self.previous_deltats.median()
                if (((self.disallow_uneven_sampling_rates
                      and abs(1./p_deltat - 1./self.deltat) > 0.5)
                     or (not self.disallow_uneven_sampling_rates
                         and abs((self.deltat - p_deltat)/self.deltat)
                         > self.deltat_tolerance))
                    and len(self.previous_deltats)
                        > 0.5*self.previous_deltats.capacity()):

                    self.deltat = None
                    self.previous_deltats.empty()
            except QueueIsEmpty:
                pass

        self.previous_deltats.push_back(r_deltat)

        # detect sampling rate
        if self.deltat is None:
            if self.fixed_deltat is not None:
                self.deltat = self.fixed_deltat
            else:
                self.deltat = r_deltat
                # must also set new time origin if sampling rate changes
                self.tmin = None
                logger.info(
                    'Setting new sampling rate to %g Hz '
                    '(sampling interval is %g s)' % (
                        1./self.deltat, self.deltat))

        # check if onset has drifted / jumped
        if self.deltat is not None and self.tmin is not None:
            continuous_tmin = self.tmin + self.ncontinuous*self.deltat

            tmin_offset = r_tmin - continuous_tmin
            try:
                toffset = self.previous_tmin_offsets.median()
                if abs(toffset) > self.deltat*0.7 \
                        and len(self.previous_tmin_offsets) \
                        > 0.5*self.previous_tmin_offsets.capacity():

                    soffset = int(round(toffset/self.deltat))
                    logger.info(
                        'Detected drift/jump/gap of %g sample%s' % (
                            soffset, ['s', ''][abs(soffset) == 1]))

                    if soffset == 1:
                        for values in self.values:
                            values.append(values[-1])
                        self.previous_tmin_offsets.add(-self.deltat)
                        logger.info(
                            'Adding one sample to compensate time drift')
                    elif soffset == -1:
                        for values in self.values:
                            values.pop(-1)
                        self.previous_tmin_offsets.add(+self.deltat)
                        logger.info(
                            'Removing one sample to compensate time drift')
                    else:
                        self.tmin = None
                        self.previous_tmin_offsets.empty()

            except QueueIsEmpty:
                pass

            self.previous_tmin_offsets.push_back(tmin_offset)

        # detect onset time
        if self.tmin is None and self.deltat is not None:
            self.tmin = r_tmin
            self.ncontinuous = 0
            logger.info(
                'Setting new time origin to %s' % util.time_to_str(self.tmin))

        if self.tmin is not None and self.deltat is not None:
            for channel, values in zip(self.channels, self.values):
                v = num.array(values, dtype=num.int32)

                tr = trace.Trace(
                    network=self.network,
                    station=self.station,
                    location=self.location,
                    channel=channel,
                    tmin=self.tmin + self.ncontinuous*self.deltat,
                    deltat=self.deltat,
                    ydata=v)

                self.got_trace(tr)
            self.ncontinuous += v.size

            self.values = [[]] * len(self.channels)
            self.times = []

    def got_trace(self, tr):
        logger.debug('Completed trace from serial hamster: %s' % tr)

        # deliver payload to registered listeners
        for ref in self.listeners:
            obj = ref()
            if obj:
                obj.insert_trace(tr)


class CamSerialHamster(SerialHamster):

    def __init__(self, baudrate=115200, channels=['N'], *args, **kwargs):
        SerialHamster.__init__(
            self, disallow_uneven_sampling_rates=False, deltat_tolerance=0.001,
            baudrate=baudrate, channels=channels, *args, **kwargs)

    def send_start(self):
        try:
            ser = self.ser
            ser.write('99,e\n')
            a = ser.readline()
            if not a:
                raise SerialHamsterError(
                    'Camera did not respond to command "99,e"')

            logger.debug(
                'Sent command "99,e" to cam; received answer: "%s"'
                % a.strip())

            ser.write('2,e\n')
            a = ser.readline()
            if not a:
                raise SerialHamsterError(
                    'Camera did not respond to command "2,e"')

            logger.debug(
                'Sent command "2,e" to cam; received answer: "%s"' % a.strip())
            ser.write('2,01\n')
            ser.write('2,f400\n')
        except Exception:
            raise SerialHamsterError(
                'Initialization of camera acquisition failed.')

    def process(self):
        ser = self.ser

        if ser is None:
            return False

        ser.write('2,X\n')
        isamp = 0
        while True:
            data = ser.read(2)
            if len(data) != 2:
                raise SerialHamsterError(
                    'Failed to read from serial line interface.')

            uclow = ord(data[0])
            uchigh = ord(data[1])

            if uclow == 0xff and uchigh == 0xff:
                break

            v = uclow + (uchigh << 8)

            self.times.append(time.time())
            self.values[isamp % len(self.channels)].append(v)
            isamp += 1

            if len(self.values[-1]) >= self.buffersize:
                self._flush_buffer()

        return True


class USBHB628Hamster(SerialHamster):

    def __init__(self, baudrate=115200, channels=[(0, 'Z')], *args, **kwargs):
        SerialHamster.__init__(
            self,
            baudrate=baudrate,
            channels=[x[1] for x in channels],
            tune_to_quickones=False,
            *args, **kwargs)

        self.channel_map = dict([(c[0], j) for (j, c) in enumerate(channels)])
        self.first_initiated = None
        self.ntaken = 0

    def process(self):
        import serial

        ser = self.ser

        if ser is None:
            return False

        t = time.time()

        # determine next appropriate sampling instant
        if self.first_initiated is not None:
            ts = self.first_initiated + self.fixed_deltat * self.ntaken
            if t - ts > self.fixed_deltat*10:
                logger.warning(
                    'lagging more than ten samples on serial line %s - '
                    'resetting' % self.port)

                self.first_initiated = None

        if not self.first_initiated:
            ts = math.ceil(t/self.fixed_deltat)*self.fixed_deltat
            self.first_initiated = ts
            self.ntaken = 0

        # wait for next sampling instant
        while t < ts:
            time.sleep(max(0., ts-t))
            t = time.time()

        if t - ts > self.fixed_deltat:
            logger.warning(
                'lagging more than one sample on serial line %s' % self.port)

        # get the sample
        ser.write('c09')
        ser.flush()
        try:
            data = [ord(x) for x in ser.read(17)]
            if len(data) != 17:
                raise SerialHamsterError('Reading from serial line failed.')

        except serial.serialutil.SerialException:
            raise SerialHamsterError('Reading from serial line failed.')

        self.ntaken += 1

        for ichan in range(8):
            if ichan in self.channel_map:
                v = data[ichan*2] + (data[ichan*2+1] << 8)
                self.values[self.channel_map[ichan]].append(v)

        self.times.append(t)

        if len(self.times) >= self.buffersize:
            self._flush_buffer()

        return True


class AcquisitionThread(threading.Thread):
    def __init__(self, post_process_sleep=0.0):
        threading.Thread.__init__(self)
        self.queue = queue.Queue()
        self.post_process_sleep = post_process_sleep
        self._sun_is_shining = True

    def run(self):
        while True:
            try:
                self.acquisition_start()
                while self._sun_is_shining:
                    t0 = time.time()
                    self.process()
                    t1 = time.time()
                    if self.post_process_sleep != 0.0:
                        time.sleep(max(0, self.post_process_sleep-(t1-t0)))

                self.acquisition_stop()
                break

            except SerialHamsterError as e:

                logger.error(str(e))
                logger.error('Acquistion terminated, restart in 5 s')
                self.acquisition_stop()
                time.sleep(5)
                if not self._sun_is_shining:
                    break

    def stop(self):
        self._sun_is_shining = False

        logger.debug('Waiting for thread to terminate...')
        self.wait()
        logger.debug('Thread has terminated.')

    def got_trace(self, tr):
        self.queue.put(tr)

    def poll(self):
        items = []
        try:
            while True:
                items.append(self.queue.get_nowait())

        except queue.Empty:
            pass

        return items


class Acquisition(
        SerialHamster, AcquisitionThread):

    def __init__(self, *args, **kwargs):
        SerialHamster.__init__(self, *args, **kwargs)
        AcquisitionThread.__init__(self, post_process_sleep=0.001)

    def got_trace(self, tr):
        logger.debug('acquisition got trace rate %g Hz, duration %g s' % (
            1.0/tr.deltat, tr.tmax - tr.tmin))
        AcquisitionThread.got_trace(self, tr)
