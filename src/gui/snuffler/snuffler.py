# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Effective seismological trace viewer.
'''

import os
import sys
import logging
import gc
import tempfile
import shutil
import glob

from os.path import join as pjoin
from optparse import OptionParser


from pyrocko import deps
from pyrocko import pile as pile_mod
from pyrocko import util
from pyrocko import model
from pyrocko import config
from pyrocko import io
from pyrocko.io import stationxml

from . import marker


logger = logging.getLogger('pyrocko.gui.snuffler.snuffler')


def extend_paths(paths):
    paths_r = []
    for p in paths:
        paths_r.extend(glob.glob(p))
    return paths_r


def snuffle(pile=None, **kwargs):
    '''
    View pile in a snuffler window.

    :param pile: :py:class:`~pyrocko.pile.Pile` object to be visualized
    :param stations: list of `pyrocko.model.Station` objects or ``None``
    :param events: list of `pyrocko.model.Event` objects or ``None``
    :param markers: list of `pyrocko.gui.snuffler.util.Marker` objects or
        ``None``
    :param ntracks: float, number of tracks to be shown initially (default: 12)
    :param marker_editor_sortable: bool, whether to allow sorting in marker
        table (default True). Disabling this will give better performance
        when working with many markers.
    :param follow: time interval (in seconds) for real time follow mode or
        ``None``
    :param controls: bool, whether to show the main controls (default:
        ``True``)
    :param opengl: bool, whether to use opengl (default: ``None`` - automatic
        choice).
    :param paths: list of files and directories to search for trace files
    :param pattern: regex which filenames must match
    :param format: format of input files
    :param cache_dir: cache directory with trace meta information
    :param force_cache: bool, whether to use the cache when attribute spoofing
        is active
    :param store_path: filename template, where to store trace data from input
        streams
    :param store_interval: float, time interval (in seconds) between stream
        buffer dumps
    :param want_markers: bool, whether markers should be returned
    :param launch_hook: callback function called before snuffler window is
        shown
    :param instant_close: bool, whether to bypass close window confirmation
        dialog
    '''
    from .snuffler_app import SnufflerWindow, \
        setup_acquisition_sources, PollInjector

    if pile is None:
        pile = pile_mod.make_pile()

    from pyrocko.gui import util as gui_util
    app = gui_util.get_app()

    kwargs_load = {}
    for k in ('paths', 'regex', 'format', 'cache_dir', 'force_cache'):
        try:
            kwargs_load[k] = kwargs.pop(k)
        except KeyError:
            pass

    store_path = kwargs.pop('store_path', None)
    store_interval = kwargs.pop('store_interval', 600)
    want_markers = kwargs.pop('want_markers', False)
    launch_hook = kwargs.pop('launch_hook', None)

    win = SnufflerWindow(pile, **kwargs)
    app.set_main_window(win)

    if launch_hook:
        if not isinstance(launch_hook, list):
            launch_hook = [launch_hook]
        for hook in launch_hook:
            hook(win)

    sources = []
    pollinjector = None
    tempdir = None
    if 'paths' in kwargs_load:
        sources.extend(setup_acquisition_sources(kwargs_load['paths']))
        if sources:
            if store_path is None:
                tempdir = tempfile.mkdtemp('', 'snuffler-tmp-')
                store_path = pjoin(
                    tempdir,
                    'trace-%(network)s.%(station)s.%(location)s.%(channel)s.'
                    '%(tmin_ms)s.mseed')
            elif os.path.isdir(store_path):
                store_path = pjoin(
                    store_path,
                    'trace-%(network)s.%(station)s.%(location)s.%(channel)s.'
                    '%(tmin_ms)s.mseed')

            interval = min(
                source.get_wanted_poll_interval() for source in sources)

            pollinjector = PollInjector(
                pile,
                fixation_length=store_interval,
                path=store_path,
                interval=interval)

            for source in sources:
                source.start()
                pollinjector.add_source(source)

        win.get_view().load(**kwargs_load)

    if not win.is_closing():
        app.install_sigint_handler()
        try:
            app.exec_()

        finally:
            app.uninstall_sigint_handler()
            app.set_main_window(None)

    for source in sources:
        source.stop()

    if pollinjector:
        pollinjector.fixate_all()

    ret = win.return_tag()

    if want_markers:
        markers = win.get_view().get_markers()

    del win
    gc.collect()

    if tempdir:
        shutil.rmtree(tempdir)

    if want_markers:
        return ret, markers
    else:
        return ret


def snuffler_from_commandline(args=None):
    if args is None:
        args = sys.argv[1:]

    usage = '''usage: %prog [options] waveforms ...'''
    parser = OptionParser(usage=usage)

    parser.add_option(
        '--format',
        dest='format',
        default='detect',
        choices=io.allowed_formats('load'),
        help='assume input files are of given FORMAT. Choices: %s'
             % io.allowed_formats('load', 'cli_help', 'detect'))

    parser.add_option(
        '--pattern',
        dest='regex',
        metavar='REGEX',
        help='only include files whose paths match REGEX')

    parser.add_option(
        '--stations',
        dest='station_fns',
        action='append',
        default=[],
        metavar='STATIONS',
        help='read station information from file STATIONS')

    parser.add_option(
        '--stationxml',
        dest='stationxml_fns',
        action='append',
        default=[],
        metavar='STATIONSXML',
        help='read station information from XML file STATIONSXML')

    parser.add_option(
        '--event', '--events',
        dest='event_fns',
        action='append',
        default=[],
        metavar='EVENT',
        help='read event information from file EVENT')

    parser.add_option(
        '--markers',
        dest='marker_fns',
        action='append',
        default=[],
        metavar='MARKERS',
        help='read marker information file MARKERS')

    parser.add_option(
        '--follow',
        type='float',
        dest='follow',
        metavar='N',
        help='follow real time with a window of N seconds')

    parser.add_option(
        '--cache',
        dest='cache_dir',
        default=config.config().cache_dir,
        metavar='DIR',
        help='use directory DIR to cache trace metadata '
             "(default='%default')")

    parser.add_option(
        '--force-cache',
        dest='force_cache',
        action='store_true',
        default=False,
        help='use the cache even when trace attribute spoofing is active '
             '(may have silly consequences)')

    parser.add_option(
        '--store-path',
        dest='store_path',
        metavar='PATH_TEMPLATE',
        help='store data received through streams to PATH_TEMPLATE')

    parser.add_option(
        '--store-interval',
        type='float',
        dest='store_interval',
        default=600,
        metavar='N',
        help='dump stream data to file every N seconds [default: %default]')

    parser.add_option(
        '--ntracks',
        type='int',
        dest='ntracks',
        default=24,
        metavar='N',
        help='initially use N waveform tracks in viewer [default: %default]')

    parser.add_option(
        '--disable-marker-sorting',
        action='store_false',
        dest='marker_editor_sortable',
        default=True,
        help='disable sorting in marker table for improved performance with '
             '100000+ markers')

    parser.add_option(
        '--hptime',
        choices=('on', 'off', 'config'),
        dest='hp_time',
        default='config',
        metavar='on|off|config',
        help='set high precision time mode [default: %default]')

    parser.add_option(
        '--opengl',
        dest='opengl',
        action='store_true',
        default=None,
        help='use OpenGL for drawing')

    parser.add_option(
        '--no-opengl',
        dest='opengl',
        action='store_false',
        default=None,
        help='do not use OpenGL for drawing')

    parser.add_option(
        '--debug',
        dest='debug',
        action='store_true',
        default=False,
        help='print debugging information to stderr')

    options, args = parser.parse_args(list(args))

    if options.debug:
        util.setup_logging('snuffler', 'debug')
    else:
        util.setup_logging('snuffler', 'info')

    if options.hp_time in ('on', 'off'):
        util.use_high_precision_time(options.hp_time == 'on')

    this_pile = pile_mod.Pile()
    stations = []
    for stations_fn in extend_paths(options.station_fns):
        stations.extend(model.station.load_stations(stations_fn))

    for stationxml_fn in extend_paths(options.stationxml_fns):
        stations.extend(
            stationxml.load_xml(
                filename=stationxml_fn).get_pyrocko_stations())

    events = []
    for event_fn in extend_paths(options.event_fns):
        events.extend(model.load_events(event_fn))

    markers = []
    for marker_fn in extend_paths(options.marker_fns):
        markers.extend(marker.load_markers(marker_fn))

    import pyrocko

    try:
        return pyrocko.snuffle(
            this_pile,
            stations=stations,
            events=events,
            markers=markers,
            ntracks=options.ntracks,
            marker_editor_sortable=options.marker_editor_sortable,
            follow=options.follow,
            controls=True,
            opengl=options.opengl,
            paths=args,
            cache_dir=options.cache_dir,
            regex=options.regex,
            format=options.format,
            force_cache=options.force_cache,
            store_path=options.store_path,
            store_interval=options.store_interval)

    except deps.MissingPyrockoDependency as e:
        logger.fatal(str(e))
        sys.exit(1)


if __name__ == '__main__':
    snuffler_from_commandline()
