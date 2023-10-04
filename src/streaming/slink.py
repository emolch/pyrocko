# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Live stream reader for SeedLink streams (via `slinktool
<https://www.seiscomp.de/doc/apps/slinktool.html>`_).
'''

import subprocess
import time
import os
import signal
import select
import logging
import tempfile

from pyrocko.io import mseed

logger = logging.getLogger('pyrocko.streaming.slink')
RECORD_LENGTH = 512


def preexec():
    os.setpgrp()


class SlowSlinkError(Exception):
    pass


class SlowSlink(object):
    def __init__(self, host='geofon.gfz-potsdam.de', port=18000):
        self.host = host
        self.port = port
        self.running = False
        self.stream_selectors = []

    def query_streams(self):
        cmd = ['slinktool',  '-Q', self.host+':'+str(self.port)]
        logger.debug('Running %s' % ' '.join(cmd))
        try:
            slink = subprocess.Popen(cmd, stdout=subprocess.PIPE)
        except OSError as e:
            raise SlowSlinkError('Could not start "slinktool": %s' % str(e))

        (a, b) = slink.communicate()
        streams = []
        for line in a.splitlines():
            line = line.decode()
            toks = line.split()
            if len(toks) == 9:
                net, sta, loc, cha = toks[0], toks[1], '', toks[2]
            else:
                net, sta, loc, cha = toks[0], toks[1], toks[2], toks[3]
            streams.append((net, sta, loc, cha))
        return streams

    def add_stream(self, network, station, location, channel):
        self.stream_selectors.append(
            '%s_%s:%s.D' % (network, station, channel))

    def add_raw_stream_selector(self, stream_selector):
        self.stream_selectors.append(stream_selector)

    def acquisition_start(self):
        assert not self.running
        if self.stream_selectors:
            streams = ['-S', ','.join(self.stream_selectors)]
        else:
            streams = []

        cmd = ['slinktool', '-o', '-'] \
            + streams + [self.host+':'+str(self.port)]

        logger.debug('Starting %s' % ' '.join(cmd))
        self.running = True
        self.header = None
        self.vals = []
        try:
            self.slink = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                preexec_fn=preexec,
                close_fds=True)
        except OSError as e:
            raise SlowSlinkError('Could not start "slinktool": %s' % str(e))

        logger.debug('Started.')

    def acquisition_stop(self):
        self.acquisition_request_stop()

    def acquisition_request_stop(self):
        if not self.running:
            return

        self.running = False  # intentionally before the kill

        os.kill(self.slink.pid, signal.SIGTERM)
        logger.debug('Waiting for slinktool to terminate...')
        it = 0
        while self.slink.poll() == -1:
            time.sleep(0.01)
            if it == 200:
                logger.debug(
                    'Waiting for slinktool to terminate... trying harder...')
                os.kill(self.slink.pid, signal.SIGKILL)

            it += 1

        logger.debug('Done, slinktool has terminated')

    def process(self):
        try:
            ready, _, _ = select.select([self.slink.stdout], [], [], .2)
            if not ready:
                return False

            line = self.slink.stdout.read(RECORD_LENGTH)

            with tempfile.NamedTemporaryFile(prefix='slink-stream') as f:
                f.write(line)
                f.flush()

                traces = mseed.iload(f.name)
                for tr in traces:
                    self.got_trace(tr)

                return True

        except Exception as e:
            logger.debug(e)
            return False

    def got_trace(self, tr):
        logger.info('Got trace from slinktool: %s' % tr)
