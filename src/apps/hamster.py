# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Hamster - a simple seismic datalogger.
'''

import os
import sys
import signal
import logging
import time

from pyrocko import hamster_pile, util
from pyrocko.streaming import serial_hamster
from optparse import OptionParser
pjoin = os.path.join

logger = logging.getLogger('pyrocko.apps.hamster')


def main(args=None):
    '''
    CLI entry point for Pyrocko's ``hamster`` app.
    '''
    if args is None:
        args = sys.argv[1:]

    parser = OptionParser(
        usage='hamster [options] datadir',
        description='''
Datalogger program for the A/D converter of the "School Seismometer" connected
to a serial port. This program expects whitespace-separated ascii numbers on a
serial interface and stores the received data as MSEED files in the directory
datadir. It automatically detects the sampling rate and uses the system clock
as reference for time synchronization. If a change, gap, or jump of the
sampling rate is detected, a new data trace is started. Small drifts of the
sampling rate are compensated by adding or removing single samples when
necessary.
'''.strip())

    parser.add_option(
        '--port', dest='port', default='/dev/ttyS0', metavar='STR',
        help='device name of the serial port to be used (%default)')

    parser.add_option(
        '--baudrate', dest='baudrate', default='9600', metavar='INT',
        help='baudrate for serial port (%default)')

    parser.add_option(
        '--timeout', dest='timeout', default='5', metavar='FLOAT',
        help='serial port timeout in seconds (%default)')

    parser.add_option(
        '--filelength', dest='filelength', default='3600', metavar='FLOAT',
        help='approx file length in seconds (%default)')

    parser.add_option(
        '--network', dest='network', default='', metavar='STR',
        help='network name (%default)')
    parser.add_option(
        '--station', dest='station', default='STA', metavar='STR',
        help='station name (%default)')
    parser.add_option(
        '--location', dest='location', default='', metavar='STR',
        help='location name (%default)')
    parser.add_option(
        '--channel', dest='channel', default='N', metavar='STR',
        help='channel name (%default)')

    parser.add_option(
        '--blocksize', dest='buffersize', default=128, metavar='INT',
        help='block size for time synchronization (%default)')

    parser.add_option(
        '--lookback', dest='lookback', default=5, metavar='INT',
        help='number of previous blocks to consider (%default)')

    parser.add_option(
        '--debug', dest='debug', action='store_true', default=False,
        help='enable debugging output')

    options, args = parser.parse_args(args)
    if len(args) < 2:
        parser.error('required argument missing')
    directory = args[1]

    if options.debug:
        util.setup_logging('hamster', 'debug')
    else:
        util.setup_logging('hamster', 'warning')

    pile = hamster_pile.HamsterPile()
    pile.set_fixation_length(float(options.filelength))

    fn = 'data_%(network)s_%(station)s_%(location)s_%(channel)s_' \
         '%(tmin)s_%(tmax)s.mseed'

    pile.set_save_path(pjoin(directory, fn))

    # testsource = Popen(['./test_datasource.py'], stdout=PIPE)

    while True:
        try:
            hamster = serial_hamster.Acquisition(
                port=options.port,
                baudrate=int(options.baudrate),
                timeout=float(options.timeout),
                network=options.network,
                station=options.station,
                location=options.location,
                channel=options.channel,
                buffersize=options.buffersize,
                lookback=options.lookback,
                # in_file=testsource.stdout,
            )

            hamster.add_listener(pile)
            signal.signal(signal.SIGINT, hamster.quit_soon)
            hamster.start()
            pile.fixate_all()
            sys.exit()

        except serial_hamster.SerialHamsterError as e:

            pile.fixate_all()
            hamster.stop()
            hamster.clear_listeners()
            logger.error(str(e))
            logger.error('Acquistion terminated, restart in 5 s')
            time.sleep(5)
            if not hamster.sun_is_shining():
                sys.exit()


if __name__ == '__main__':
    main()
