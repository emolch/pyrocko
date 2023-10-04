# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Snuffling infrastructure

This module provides the base class :py:class:`Snuffling` for user-defined
snufflings and some utilities for their handling.
'''

import os
import sys
import time
import logging
import traceback
import tempfile

from ..qt_compat import qc, qw, getSaveFileName

from pyrocko import pile, config
from pyrocko.util import quote

from ..util import (
    ValControl, LinValControl, FigureFrame, SmartplotFrame, WebKitFrame,
    VTKFrame, PixmapFrame, Marker, EventMarker, PhaseMarker, load_markers,
    save_markers)

from importlib import reload

Marker, load_markers, save_markers  # noqa

logger = logging.getLogger('pyrocko.gui.snuffler.snuffling')


class MyFrame(qw.QFrame):
    widgetVisibilityChanged = qc.pyqtSignal(bool)

    def showEvent(self, ev):
        ''
        self.widgetVisibilityChanged.emit(True)

    def hideEvent(self, ev):
        ''
        self.widgetVisibilityChanged.emit(False)


class Param(object):
    '''
    Definition of an adjustable floating point parameter for the
    snuffling. The snuffling may display controls for user input for
    such parameters.

    :param name: labels the parameter on the snuffling's control panel
    :param ident: identifier of the parameter
    :param default: default value
    :param minimum: minimum value for the parameter
    :param maximum: maximum value for the parameter
    :param low_is_none: if ``True``: parameter is set to None at lowest value
        of parameter range (optional)
    :param high_is_none: if ``True``: parameter is set to None at highest value
        of parameter range (optional)
    :param low_is_zero: if ``True``: parameter is set to value 0 at lowest
        value of parameter range (optional)
    '''

    def __init__(
            self, name, ident, default, minimum, maximum,
            low_is_none=None,
            high_is_none=None,
            low_is_zero=False,
            tracking=True,
            type=float):

        if low_is_none and default == minimum:
            default = None
        if high_is_none and default == maximum:
            default = None

        self.name = name
        self.ident = ident
        self.default = default
        self.minimum = minimum
        self.maximum = maximum
        self.low_is_none = low_is_none
        self.high_is_none = high_is_none
        self.low_is_zero = low_is_zero
        self.tracking = tracking
        self.type = type

        self._control = None


class Switch(object):
    '''
    Definition of a boolean switch for the snuffling. The snuffling
    may display a checkbox for such a switch.

    :param name:    labels the switch on the snuffling's control panel
    :param ident:   identifier of the parameter
    :param default: default value
    '''

    def __init__(self, name, ident, default):
        self.name = name
        self.ident = ident
        self.default = default


class Choice(object):
    '''
    Definition of a string choice for the snuffling. The snuffling
    may display a menu for such a choice.

    :param name:    labels the menu on the snuffling's control panel
    :param ident:   identifier of the parameter
    :param default: default value
    :param choices: tuple of other options
    '''

    def __init__(self, name, ident, default, choices):
        self.name = name
        self.ident = ident
        self.default = default
        self.choices = choices


class Snuffling(object):
    '''
    Base class for user snufflings.

    Snufflings are plugins for snuffler (and other applications using the
    :py:class:`~pyrocko.gui.snuffler.pile_viewer.PileViewer` class defined in
    ``pile_viewer.py``). They can be added, removed and reloaded at runtime and
    should provide a simple way of extending the functionality of snuffler.

    A snuffling has access to all data available in a pile viewer, can process
    this data and can create and add new traces and markers to the viewer.
    '''

    def __init__(self):
        self._path = None

        self._name = 'Untitled Snuffling'
        self._viewer = None
        self._tickets = []
        self._markers = []

        self._delete_panel = None
        self._delete_menuitem = None

        self._panel_parent = None
        self._menu_parent = None

        self._panel = None
        self._menuitem = None
        self._helpmenuitem = None
        self._parameters = []
        self._param_controls = {}

        self._triggers = []

        self._live_update = True
        self._previous_output_filename = None
        self._previous_input_filename = None
        self._previous_input_directory = None

        self._tempdir = None
        self._iplot = 0

        self._have_pre_process_hook = False
        self._have_post_process_hook = False
        self._pre_process_hook_enabled = False
        self._post_process_hook_enabled = False

        self._no_viewer_pile = None
        self._cli_params = {}
        self._filename = None
        self._force_panel = False
        self._call_in_progress = {}

    def setup(self):
        '''
        Setup the snuffling.

        This method should be implemented in subclass and contain e.g. calls to
        :py:meth:`set_name` and :py:meth:`add_parameter`.
        '''

        pass

    def module_dir(self):
        '''
        Returns the path of the directory where snufflings are stored.

        The default path is ``$HOME/.snufflings``.
        '''

        return self._path

    def init_gui(self, viewer, panel_parent, menu_parent, reloaded=False):
        '''
        Set parent viewer and hooks to add panel and menu entry.

        This method is called from the
        :py:class:`~pyrocko.gui.snuffler.pile_viewer.PileViewer` object. Calls
        :py:meth:`setup_gui`.
        '''

        self._viewer = viewer
        self._panel_parent = panel_parent
        self._menu_parent = menu_parent

        self.setup_gui(reloaded=reloaded)

    def setup_gui(self, reloaded=False):
        '''
        Create and add gui elements to the viewer.

        This method is initially called from :py:meth:`init_gui`. It is also
        called, e.g. when new parameters have been added or if the name of the
        snuffling has been changed.
        '''

        if self._panel_parent is not None:
            self._panel = self.make_panel(self._panel_parent)
            if self._panel:
                self._panel_parent.add_panel(
                    self.get_name(), self._panel, reloaded)

        if self._menu_parent is not None:
            self._menuitem = self.make_menuitem(self._menu_parent)
            self._helpmenuitem = self.make_helpmenuitem(self._menu_parent)
            if self._menuitem:
                self._menu_parent.add_snuffling_menuitem(self._menuitem)

            if self._helpmenuitem:
                self._menu_parent.add_snuffling_help_menuitem(
                    self._helpmenuitem)

    def set_force_panel(self, bool=True):
        '''
        Force to create a panel.

        :param bool: if ``True`` will create a panel with Help, Clear and Run
            button.
        '''

        self._force_panel = bool

    def make_cli_parser1(self):
        import optparse

        class MyOptionParser(optparse.OptionParser):
            def error(self, msg):
                logger.error(msg)
                self.exit(1)

        parser = MyOptionParser()

        parser.add_option(
            '--format',
            dest='format',
            default='from_extension',
            choices=(
                'mseed', 'sac', 'kan', 'segy', 'seisan', 'seisan.l',
                'seisan.b', 'gse1', 'gcf', 'yaff', 'datacube',
                'from_extension', 'detect'),
            help="assume files are of given FORMAT [default: '%default']")

        parser.add_option(
            '--pattern',
            dest='regex',
            metavar='REGEX',
            help='only include files whose paths match REGEX')

        self.add_params_to_cli_parser(parser)
        self.configure_cli_parser(parser)
        return parser

    def configure_cli_parser(self, parser):
        pass

    def cli_usage(self):
        return None

    def add_params_to_cli_parser(self, parser):

        for param in self._parameters:
            if isinstance(param, Param):
                parser.add_option(
                    '--' + param.ident,
                    dest=param.ident,
                    default=param.default,
                    type={float: 'float', int: 'int'}[param.type],
                    help=param.name)

    def setup_cli(self):
        self.setup()
        parser = self.make_cli_parser1()
        (options, args) = parser.parse_args()

        for param in self._parameters:
            if isinstance(param, Param):
                setattr(self, param.ident, getattr(options, param.ident))

        self._cli_params['regex'] = options.regex
        self._cli_params['format'] = options.format
        self._cli_params['sources'] = args

        return options, args, parser

    def delete_gui(self):
        '''
        Remove the gui elements of the snuffling.

        This removes the panel and menu entry of the widget from the viewer and
        also removes all traces and markers added with the
        :py:meth:`add_traces` and :py:meth:`add_markers` methods.
        '''

        self.cleanup()

        if self._panel is not None:
            self._panel_parent.remove_panel(self._panel)
            self._panel = None

        if self._menuitem is not None:
            self._menu_parent.remove_snuffling_menuitem(self._menuitem)
            self._menuitem = None

        if self._helpmenuitem is not None:
            self._menu_parent.remove_snuffling_help_menuitem(
                self._helpmenuitem)

    def set_name(self, name):
        '''
        Set the snuffling's name.

        The snuffling's name is shown as a menu entry and in the panel header.
        '''

        self._name = name
        self.reset_gui()

    def get_name(self):
        '''
        Get the snuffling's name.
        '''

        return self._name

    def set_have_pre_process_hook(self, bool):
        self._have_pre_process_hook = bool
        self._live_update = False
        self._pre_process_hook_enabled = False
        self.reset_gui()

    def set_have_post_process_hook(self, bool):
        self._have_post_process_hook = bool
        self._live_update = False
        self._post_process_hook_enabled = False
        self.reset_gui()

    def set_have_pile_changed_hook(self, bool):
        self._pile_ = False

    def enable_pile_changed_notifications(self):
        '''
        Get informed when pile changed.

        When activated, the :py:meth:`pile_changed` method is called on every
        update in the viewer's pile.
        '''

        viewer = self.get_viewer()
        viewer.pile_has_changed_signal.connect(
            self.pile_changed)

    def disable_pile_changed_notifications(self):
        '''
        Stop getting informed about changes in viewer's pile.
        '''

        viewer = self.get_viewer()
        viewer.pile_has_changed_signal.disconnect(
            self.pile_changed)

    def pile_changed(self):
        '''
        Called when the connected viewer's pile has changed.

        Must be activated with a call to
        :py:meth:`enable_pile_changed_notifications`.
        '''

        pass

    def reset_gui(self, reloaded=False):
        '''
        Delete and recreate the snuffling's panel.
        '''

        if self._panel or self._menuitem:
            sett = self.get_settings()
            self.delete_gui()
            self.setup_gui(reloaded=reloaded)
            self.set_settings(sett)

    def show_message(self, kind, message):
        '''
        Display a message box.

        :param kind: string defining kind of message
        :param message: the message to be displayed
        '''

        try:
            box = qw.QMessageBox(self.get_viewer())
            box.setText('%s: %s' % (kind.capitalize(), message))
            box.exec_()
        except NoViewerSet:
            pass

    def error(self, message):
        '''
        Show an error message box.

        :param message: specifying the error
        '''

        logger.error('%s: %s' % (self._name, message))
        self.show_message('error', message)

    def warn(self, message):
        '''
        Display a warning message.

        :param message: specifying the warning
        '''

        logger.warning('%s: %s' % (self._name, message))
        self.show_message('warning', message)

    def fail(self, message):
        '''
        Show an error message box and raise :py:exc:`SnufflingCallFailed`
        exception.

        :param message: specifying the error
        '''

        self.error(message)
        raise SnufflingCallFailed(message)

    def pylab(self, name=None, get='axes', figure_cls=None):
        '''
        Create a :py:class:`pyrocko.gui.util.FigureFrame` and return either the
        frame, a :py:class:`matplotlib.figure.Figure` instance or a
        :py:class:`matplotlib.axes.Axes` instance.

        :param name: labels the figure frame's tab
        :param get: 'axes'|'figure'|'frame' (optional)
        '''

        if name is None:
            self._iplot += 1
            name = 'Plot %i (%s)' % (self._iplot, self.get_name())

        fframe = FigureFrame(figure_cls=figure_cls)
        self._panel_parent.add_tab(name, fframe)
        if get == 'axes':
            return fframe.gca()
        elif get == 'figure':
            return fframe.gcf()
        elif get == 'figure_frame':
            return fframe

    def figure(self, name=None):
        '''
        Returns a :py:class:`matplotlib.figure.Figure` instance.

        Force drawing of the figure by calling `fig.canvas.draw()` on the
        returned object ``fig``.

        :param name: labels the tab of the figure
        '''

        return self.pylab(name=name, get='figure')

    def axes(self, name=None):
        '''
        Returns a :py:class:`matplotlib.axes.Axes` instance.

        :param name: labels the tab of axes
        '''

        return self.pylab(name=name, get='axes')

    def figure_frame(self, name=None, figure_cls=None):
        '''
        Create a :py:class:`pyrocko.gui.util.FigureFrame`.

        :param name: labels the tab figure frame
        '''

        return self.pylab(name=name, get='figure_frame', figure_cls=figure_cls)

    def smartplot_frame(self, name, *args, plot_cls=None, **kwargs):
        '''
        Create a :py:class:`pyrocko.gui.util.SmartplotFrame`.

        :param name: labels the tab
        :param \\*args:
            passed to :py:class:`pyrocko.plot.smartplot.Plot`
        :param \\*kwargs:
            passed to :py:class:`pyrocko.plot.smartplot.Plot`
        :param plot_cls:
            if given, subclass to be used instead of
            :py:class:`pyrocko.plot.smartplot.Plot`
        '''
        frame = SmartplotFrame(
            plot_args=args,
            plot_cls=plot_cls,
            plot_kwargs=kwargs)

        self._panel_parent.add_tab(name, frame)
        return frame

    def pixmap_frame(self, filename=None, name=None):
        '''
        Create a :py:class:`pyrocko.gui.util.PixmapFrame`.

        :param name: labels the tab
        :param filename: name of file to be displayed
        '''

        f = PixmapFrame(filename)

        scroll_area = qw.QScrollArea()
        scroll_area.setWidget(f)
        scroll_area.setWidgetResizable(True)

        self._panel_parent.add_tab(name or 'Pixmap', scroll_area)
        return f

    def web_frame(self, url=None, name=None):
        '''
        Creates a :py:class:`~pyrocko.gui.util.WebKitFrame` which can be
        used as a browser within Snuffler.

        :param url: url to open
        :param name: labels the tab
        '''

        if name is None:
            self._iplot += 1
            name = 'Web browser %i (%s)' % (self._iplot, self.get_name())

        f = WebKitFrame(url)
        self._panel_parent.add_tab(name, f)
        return f

    def vtk_frame(self, name=None, actors=None):
        '''
        Create a :py:class:`pyrocko.gui.util.VTKFrame` to render interactive 3D
        graphics.

        :param actors: list of VTKActors
        :param name: labels the tab

        Initialize the interactive rendering by calling the frames'
        :py:meth`initialize` method after having added all actors to the frames
        renderer.

        Requires installation of vtk including python wrapper.
        '''
        if name is None:
            self._iplot += 1
            name = 'VTK %i (%s)' % (self._iplot, self.get_name())

        try:
            f = VTKFrame(actors=actors)
        except ImportError as e:
            self.fail(e)

        self._panel_parent.add_tab(name, f)
        return f

    def tempdir(self):
        '''
        Create a temporary directory and return its absolute path.

        The directory and all its contents are removed when the Snuffling
        instance is deleted.
        '''

        if self._tempdir is None:
            self._tempdir = tempfile.mkdtemp('', 'snuffling-tmp-')

        return self._tempdir

    def set_live_update(self, live_update):
        '''
        Enable/disable live updating.

        When live updates are enabled, the :py:meth:`call` method is called
        whenever the user changes a parameter. If it is disabled, the user has
        to initiate such a call manually by triggering the snuffling's menu
        item or pressing the call button.
        '''

        self._live_update = live_update
        if self._have_pre_process_hook:
            self._pre_process_hook_enabled = live_update
        if self._have_post_process_hook:
            self._post_process_hook_enabled = live_update

        try:
            self.get_viewer().clean_update()
        except NoViewerSet:
            pass

    def add_parameter(self, param):
        '''
        Add an adjustable parameter to the snuffling.

        :param param: object of type :py:class:`Param`, :py:class:`Switch`, or
            :py:class:`Choice`.

        For each parameter added, controls are added to the snuffling's panel,
        so that the parameter can be adjusted from the gui.
        '''

        self._parameters.append(param)
        self._set_parameter_value(param.ident, param.default)

        if self._panel is not None:
            self.delete_gui()
            self.setup_gui()

    def add_trigger(self, name, method):
        '''
        Add a button to the snuffling's panel.

        :param name:    string that labels the button
        :param method:  method associated with the button
        '''

        self._triggers.append((name, method))

        if self._panel is not None:
            self.delete_gui()
            self.setup_gui()

    def get_parameters(self):
        '''
        Get the snuffling's adjustable parameter definitions.

        Returns a list of objects of type :py:class:`Param`.
        '''

        return self._parameters

    def get_parameter(self, ident):
        '''
        Get one of the snuffling's adjustable parameter definitions.

        :param ident: identifier of the parameter

        Returns an object of type :py:class:`Param` or ``None``.
        '''

        for param in self._parameters:
            if param.ident == ident:
                return param
        return None

    def set_parameter(self, ident, value):
        '''
        Set one of the snuffling's adjustable parameters.

        :param ident: identifier of the parameter
        :param value: new value of the parameter

        Adjusts the control of a parameter without calling :py:meth:`call`.
        '''

        self._set_parameter_value(ident, value)

        control = self._param_controls.get(ident, None)
        if control:
            control.set_value(value)

    def set_parameter_range(self, ident, vmin, vmax):
        '''
        Set the range of one of the snuffling's adjustable parameters.

        :param ident: identifier of the parameter
        :param vmin,vmax: new minimum and maximum value for the parameter

        Adjusts the control of a parameter without calling :py:meth:`call`.
        '''

        control = self._param_controls.get(ident, None)
        if control:
            control.set_range(vmin, vmax)

    def set_parameter_choices(self, ident, choices):
        '''
        Update the choices of a Choice parameter.

        :param ident: identifier of the parameter
        :param choices: list of strings
        '''

        control = self._param_controls.get(ident, None)
        if control:
            selected_choice = control.set_choices(choices)
            self._set_parameter_value(ident, selected_choice)

    def _set_parameter_value(self, ident, value):
        setattr(self, ident, value)

    def get_parameter_value(self, ident):
        '''
        Get the current value of a parameter.

        :param ident: identifier of the parameter
        '''
        return getattr(self, ident)

    def get_settings(self):
        '''
        Returns a dictionary with identifiers of all parameters as keys and
        their values as the dictionaries values.
        '''

        params = self.get_parameters()
        settings = {}
        for param in params:
            settings[param.ident] = self.get_parameter_value(param.ident)

        return settings

    def set_settings(self, settings):
        params = self.get_parameters()
        dparams = dict([(param.ident, param) for param in params])
        for k, v in settings.items():
            if k in dparams:
                self._set_parameter_value(k, v)
                if k in self._param_controls:
                    control = self._param_controls[k]
                    control.set_value(v)

    def get_viewer(self):
        '''
        Get the parent viewer.

        Returns a reference to an object of type
        :py:class:`~pyrocko.gui.snuffler.pile_viewer.PileViewer`, which is the
        main viewer widget.

        If no gui has been initialized for the snuffling, a
        :py:exc:`NoViewerSet` exception is raised.
        '''

        if self._viewer is None:
            raise NoViewerSet()
        return self._viewer

    def get_pile(self):
        '''
        Get the pile.

        If a gui has been initialized, a reference to the viewer's internal
        pile is returned. If not, the :py:meth:`make_pile` method (which may be
        overloaded in subclass) is called to create a pile. This can be
        utilized to make hybrid snufflings, which may work also in a standalone
        mode.
        '''

        try:
            p = self.get_viewer().get_pile()
        except NoViewerSet:
            if self._no_viewer_pile is None:
                self._no_viewer_pile = self.make_pile()

            p = self._no_viewer_pile

        return p

    def get_active_event_and_stations(
            self, trange=(-3600., 3600.), missing='warn'):

        '''
        Get event and stations with available data for active event.

        :param trange: (begin, end), time range around event origin time to
            query for available data
        :param missing: string, what to do in case of missing station
            information: ``'warn'``, ``'raise'`` or ``'ignore'``.

        :returns: ``(event, stations)``
        '''

        p = self.get_pile()
        v = self.get_viewer()

        event = v.get_active_event()
        if event is None:
            self.fail(
                'No active event set. Select an event and press "e" to make '
                'it the "active event"')

        stations = {}
        for traces in p.chopper(
                event.time+trange[0],
                event.time+trange[1],
                load_data=False,
                degap=False):

            for tr in traces:
                try:
                    for skey in v.station_keys(tr):
                        if skey in stations:
                            continue

                        station = v.get_station(skey)
                        stations[skey] = station

                except KeyError:
                    s = 'No station information for station key "%s".' \
                        % '.'.join(skey)

                    if missing == 'warn':
                        logger.warning(s)
                    elif missing == 'raise':
                        raise MissingStationInformation(s)
                    elif missing == 'ignore':
                        pass
                    else:
                        assert False, 'invalid argument to "missing"'

                    stations[skey] = None

        return event, list(set(
            st for st in stations.values() if st is not None))

    def get_stations(self):
        '''
        Get all stations known to the viewer.
        '''

        v = self.get_viewer()
        stations = list(v.stations.values())
        return stations

    def get_markers(self):
        '''
        Get all markers from the viewer.
        '''

        return self.get_viewer().get_markers()

    def get_event_markers(self):
        '''
        Get all event markers from the viewer.
        '''

        return [m for m in self.get_viewer().get_markers()
                if isinstance(m, EventMarker)]

    def get_selected_markers(self):
        '''
        Get all selected markers from the viewer.
        '''

        return self.get_viewer().selected_markers()

    def get_selected_event_markers(self):
        '''
        Get all selected event markers from the viewer.
        '''

        return [m for m in self.get_viewer().selected_markers()
                if isinstance(m, EventMarker)]

    def get_active_event_and_phase_markers(self):
        '''
        Get the marker of the active event and any associated phase markers
        '''

        viewer = self.get_viewer()
        markers = viewer.get_markers()
        event_marker = viewer.get_active_event_marker()
        if event_marker is None:
            self.fail(
                'No active event set. '
                'Select an event and press "e" to make it the "active event"')

        event = event_marker.get_event()

        selection = []
        for m in markers:
            if isinstance(m, PhaseMarker):
                if m.get_event() is event:
                    selection.append(m)

        return (
            event_marker,
            [m for m in markers if isinstance(m, PhaseMarker) and
             m.get_event() == event])

    def get_viewer_trace_selector(self, mode='inview'):
        '''
        Get currently active trace selector from viewer.

        :param mode: set to ``'inview'`` (default) to only include selections
            currently shown in the viewer, ``'visible' to include all traces
            not currenly hidden by hide or quick-select commands, or ``'all'``
            to disable any restrictions.
        '''

        viewer = self.get_viewer()

        def rtrue(tr):
            return True

        if mode == 'inview':
            return viewer.trace_selector or rtrue
        elif mode == 'visible':
            return viewer.trace_filter or rtrue
        elif mode == 'all':
            return rtrue
        else:
            raise Exception('invalid mode argument')

    def chopper_selected_traces(self, fallback=False, marker_selector=None,
                                mode='inview', main_bandpass=False,
                                progress=None, responsive=False,
                                *args, **kwargs):
        '''
        Iterate over selected traces.

        Shortcut to get all trace data contained in the selected markers in the
        running snuffler. For each selected marker,
        :py:meth:`pyrocko.pile.Pile.chopper` is called with the arguments
        *tmin*, *tmax*, and *trace_selector* set to values according to the
        marker. Additional arguments to the chopper are handed over from
        *\\*args* and *\\*\\*kwargs*.

        :param fallback:
            If ``True``, if no selection has been marked, use the content
            currently visible in the viewer.

        :param marker_selector:
            If not ``None`` a callback to filter markers.

        :param mode:
            Set to ``'inview'`` (default) to only include selections currently
            shown in the viewer (excluding traces accessible through vertical
            scrolling), ``'visible'`` to include all traces not currently
            hidden by hide or quick-select commands (including traces
            accessible through vertical scrolling), or ``'all'`` to disable any
            restrictions.

        :param main_bandpass:
            If ``True``, apply main control high- and lowpass filters to
            traces. Note: use with caution. Processing is fixed to use 4th
            order Butterworth highpass and lowpass and the signal is always
            demeaned before filtering. FFT filtering, rotation, demean and
            bandpass settings from the graphical interface are not respected
            here. Padding is not automatically adjusted so results may include
            artifacts.

        :param progress:
            If given a string a progress bar is shown to the user. The string
            is used as the label for the progress bar.

        :param responsive:
            If set to ``True``, occasionally allow UI events to be processed.
            If used in combination with ``progress``, this allows the iterator
            to be aborted by the user.
        '''

        try:
            viewer = self.get_viewer()
            markers = [
                m for m in viewer.selected_markers()
                if not isinstance(m, EventMarker)]

            if marker_selector is not None:
                markers = [
                    marker for marker in markers if marker_selector(marker)]

            pile = self.get_pile()

            def rtrue(tr):
                return True

            trace_selector_arg = kwargs.pop('trace_selector', rtrue)
            trace_selector_viewer = self.get_viewer_trace_selector(mode)

            style_arg = kwargs.pop('style', None)

            if main_bandpass:
                def apply_filters(traces):
                    for tr in traces:
                        if viewer.highpass is not None:
                            tr.highpass(4, viewer.highpass)
                        if viewer.lowpass is not None:
                            tr.lowpass(4, viewer.lowpass)
                    return traces
            else:
                def apply_filters(traces):
                    return traces

            pb = viewer.parent().get_progressbars()

            time_last = [time.time()]

            def update_progress(label, batch):
                time_now = time.time()
                if responsive:
                    # start processing events with one second delay, so that
                    # e.g. cleanup actions at startup do not cause track number
                    # changes etc.
                    if time_last[0] + 1. < time_now:
                        qw.qApp.processEvents()
                else:
                    # redraw about once a second
                    if time_last[0] + 1. < time_now:
                        viewer.repaint()

                    time_last[0] = time.time()  # use time after drawing

                abort = pb.set_status(
                    label, batch.i*100./batch.n, responsive)
                abort |= viewer.window().is_closing()

                return abort

            if markers:
                for imarker, marker in enumerate(markers):
                    try:
                        if progress:
                            label = '%s: %i/%i' % (
                                progress, imarker+1, len(markers))

                            pb.set_status(label, 0, responsive)

                        if not marker.nslc_ids:
                            trace_selector_marker = rtrue
                        else:
                            def trace_selector_marker(tr):
                                return marker.match_nslc(tr.nslc_id)

                        def trace_selector(tr):
                            return trace_selector_arg(tr) \
                                and trace_selector_viewer(tr) \
                                and trace_selector_marker(tr)

                        for batch in pile.chopper(
                                tmin=marker.tmin,
                                tmax=marker.tmax,
                                trace_selector=trace_selector,
                                style='batch',
                                *args,
                                **kwargs):

                            if progress:
                                abort = update_progress(label, batch)
                                if abort:
                                    return

                            batch.traces = apply_filters(batch.traces)
                            if style_arg == 'batch':
                                yield batch
                            else:
                                yield batch.traces

                    finally:
                        if progress:
                            pb.set_status(label, 100., responsive)

            elif fallback:
                def trace_selector(tr):
                    return trace_selector_arg(tr) \
                        and trace_selector_viewer(tr)

                tmin, tmax = viewer.get_time_range()

                if not pile.is_empty():
                    ptmin = pile.get_tmin()
                    tpad = kwargs.get('tpad', 0.0)
                    if ptmin > tmin:
                        tmin = ptmin + tpad
                    ptmax = pile.get_tmax()
                    if ptmax < tmax:
                        tmax = ptmax - tpad

                try:
                    if progress:
                        label = progress
                        pb.set_status(label, 0, responsive)

                    for batch in pile.chopper(
                            tmin=tmin,
                            tmax=tmax,
                            trace_selector=trace_selector,
                            style='batch',
                            *args,
                            **kwargs):

                        if progress:
                            abort = update_progress(label, batch)

                            if abort:
                                return

                        batch.traces = apply_filters(batch.traces)

                        if style_arg == 'batch':
                            yield batch
                        else:
                            yield batch.traces

                finally:
                    if progress:
                        pb.set_status(label, 100., responsive)

            else:
                raise NoTracesSelected()

        except NoViewerSet:
            pile = self.get_pile()
            return pile.chopper(*args, **kwargs)

    def get_selected_time_range(self, fallback=False):
        '''
        Get the time range spanning all selected markers.

        :param fallback: if ``True`` and no marker is selected return begin and
            end of visible time range
        '''

        viewer = self.get_viewer()
        markers = viewer.selected_markers()
        mins = [marker.tmin for marker in markers]
        maxs = [marker.tmax for marker in markers]

        if mins and maxs:
            tmin = min(mins)
            tmax = max(maxs)

        elif fallback:
            tmin, tmax = viewer.get_time_range()

        else:
            raise NoTracesSelected()

        return tmin, tmax

    def panel_visibility_changed(self, bool):
        '''
        Called when the snuffling's panel becomes visible or is hidden.

        Can be overloaded in subclass, e.g. to perform additional setup actions
        when the panel is activated the first time.
        '''

        pass

    def make_pile(self):
        '''
        Create a pile.

        To be overloaded in subclass. The default implementation just calls
        :py:func:`pyrocko.pile.make_pile` to create a pile from command line
        arguments.
        '''

        cachedirname = config.config().cache_dir
        sources = self._cli_params.get('sources', sys.argv[1:])
        return pile.make_pile(
            sources,
            cachedirname=cachedirname,
            regex=self._cli_params['regex'],
            fileformat=self._cli_params['format'])

    def make_panel(self, parent):
        '''
        Create a widget for the snuffling's control panel.

        Normally called from the :py:meth:`setup_gui` method. Returns ``None``
        if no panel is needed (e.g. if the snuffling has no adjustable
        parameters).
        '''

        params = self.get_parameters()
        self._param_controls = {}
        if params or self._force_panel:
            sarea = MyScrollArea(parent.get_panel_parent_widget())
            sarea.setFrameStyle(qw.QFrame.NoFrame)
            sarea.setSizePolicy(qw.QSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Expanding))
            frame = MyFrame(sarea)
            frame.widgetVisibilityChanged.connect(
                self.panel_visibility_changed)

            frame.setSizePolicy(qw.QSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Minimum))
            frame.setFrameStyle(qw.QFrame.NoFrame)
            sarea.setWidget(frame)
            sarea.setWidgetResizable(True)
            layout = qw.QGridLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(0)
            frame.setLayout(layout)

            parlayout = qw.QGridLayout()

            irow = 0
            ipar = 0
            have_switches = False
            have_params = False
            for iparam, param in enumerate(params):
                if isinstance(param, Param):
                    if param.minimum <= 0.0:
                        param_control = LinValControl(
                            high_is_none=param.high_is_none,
                            low_is_none=param.low_is_none,
                            type=param.type)
                    else:
                        param_control = ValControl(
                            high_is_none=param.high_is_none,
                            low_is_none=param.low_is_none,
                            low_is_zero=param.low_is_zero,
                            type=param.type)

                    param_control.setup(
                        param.name,
                        param.minimum,
                        param.maximum,
                        param.default,
                        iparam)

                    param_control.set_tracking(param.tracking)
                    param_control.valchange.connect(
                        self.modified_snuffling_panel)

                    self._param_controls[param.ident] = param_control
                    for iw, w in enumerate(param_control.widgets()):
                        parlayout.addWidget(w, ipar, iw)

                    ipar += 1
                    have_params = True

                elif isinstance(param, Choice):
                    param_widget = ChoiceControl(
                        param.ident, param.default, param.choices, param.name)
                    param_widget.choosen.connect(
                        self.choose_on_snuffling_panel)

                    self._param_controls[param.ident] = param_widget
                    parlayout.addWidget(param_widget, ipar, 0, 1, 3)
                    ipar += 1
                    have_params = True

                elif isinstance(param, Switch):
                    have_switches = True

            if have_params:
                parframe = qw.QFrame(sarea)
                parframe.setSizePolicy(qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Minimum))
                parframe.setLayout(parlayout)
                layout.addWidget(parframe, irow, 0)
                irow += 1

            if have_switches:
                swlayout = qw.QGridLayout()
                isw = 0
                for iparam, param in enumerate(params):
                    if isinstance(param, Switch):
                        param_widget = SwitchControl(
                            param.ident, param.default, param.name)
                        param_widget.sw_toggled.connect(
                            self.switch_on_snuffling_panel)

                        self._param_controls[param.ident] = param_widget
                        swlayout.addWidget(param_widget, isw//10, isw % 10)
                        isw += 1

                swframe = qw.QFrame(sarea)
                swframe.setSizePolicy(qw.QSizePolicy(
                    qw.QSizePolicy.Expanding, qw.QSizePolicy.Minimum))
                swframe.setLayout(swlayout)
                layout.addWidget(swframe, irow, 0)
                irow += 1

            butframe = qw.QFrame(sarea)
            butframe.setSizePolicy(qw.QSizePolicy(
                qw.QSizePolicy.Expanding, qw.QSizePolicy.Minimum))
            butlayout = qw.QHBoxLayout()
            butframe.setLayout(butlayout)

            live_update_checkbox = qw.QCheckBox('Auto-Run')
            if self._live_update:
                live_update_checkbox.setCheckState(qc.Qt.Checked)

            butlayout.addWidget(live_update_checkbox)
            live_update_checkbox.toggled.connect(
                self.live_update_toggled)

            help_button = qw.QPushButton('Help')
            butlayout.addWidget(help_button)
            help_button.clicked.connect(
                self.help_button_triggered)

            clear_button = qw.QPushButton('Clear')
            butlayout.addWidget(clear_button)
            clear_button.clicked.connect(
                self.clear_button_triggered)

            call_button = qw.QPushButton('Run')
            butlayout.addWidget(call_button)
            call_button.clicked.connect(
                self.call_button_triggered)

            for name, method in self._triggers:
                but = qw.QPushButton(name)

                def call_and_update(method):
                    def f():
                        self.check_call(method)
                        self.get_viewer().update()
                    return f

                but.clicked.connect(
                    call_and_update(method))

                butlayout.addWidget(but)

            layout.addWidget(butframe, irow, 0)

            irow += 1
            spacer = qw.QSpacerItem(
                0, 0, qw.QSizePolicy.Expanding, qw.QSizePolicy.Expanding)

            layout.addItem(spacer, irow, 0)

            return sarea

        else:
            return None

    def make_helpmenuitem(self, parent):
        '''
        Create the help menu item for the snuffling.
        '''

        item = qw.QAction(self.get_name(), None)

        item.triggered.connect(
            self.help_button_triggered)

        return item

    def make_menuitem(self, parent):
        '''
        Create the menu item for the snuffling.

        This method may be overloaded in subclass and return ``None``, if no
        menu entry is wanted.
        '''

        item = qw.QAction(self.get_name(), None)
        item.setCheckable(
            self._have_pre_process_hook or self._have_post_process_hook)

        item.triggered.connect(
            self.menuitem_triggered)

        return item

    def output_filename(
            self,
            caption='Save File',
            dir='',
            filter='',
            selected_filter=None):

        '''
        Query user for an output filename.

        This is currently a wrapper to ``QFileDialog.getSaveFileName``.
        :py:exc:`UserCancelled` exception is raised if the user cancels the
        dialog.
        '''

        if not dir and self._previous_output_filename:
            dir = self._previous_output_filename

        fn = getSaveFileName(
            self.get_viewer(), caption, dir, filter, selected_filter)
        if not fn:
            raise UserCancelled()

        self._previous_output_filename = fn
        return str(fn)

    def input_directory(self, caption='Open Directory', dir=''):
        '''
        Query user for an input directory.

        This is a wrapper to ``QFileDialog.getExistingDirectory``. A
        :py:exc:`UserCancelled` exception is raised if the user cancels the
        dialog.
        '''

        if not dir and self._previous_input_directory:
            dir = self._previous_input_directory

        dn = qw.QFileDialog.getExistingDirectory(
            None, caption, dir, qw.QFileDialog.ShowDirsOnly)

        if not dn:
            raise UserCancelled()

        self._previous_input_directory = dn
        return str(dn)

    def input_filename(self, caption='Open File', dir='', filter='',
                       selected_filter=None):
        '''
        Query user for an input filename.

        This is currently a wrapper to ``QFileDialog.getOpenFileName``. A
        :py:exc:`UserCancelled` exception is raised if the user cancels the
        dialog.
        '''

        if not dir and self._previous_input_filename:
            dir = self._previous_input_filename

        fn, _ = qw.QFileDialog.getOpenFileName(
            self.get_viewer(),
            caption,
            dir,
            filter)

        if not fn:
            raise UserCancelled()

        self._previous_input_filename = fn
        return str(fn)

    def input_dialog(self, caption='', request='', directory=False):
        '''
        Query user for a text input.

        This is currently a wrapper to ``QInputDialog.getText``.
        A :py:exc:`UserCancelled` exception is raised if the user cancels the
        dialog.
        '''

        inp, ok = qw.QInputDialog.getText(self.get_viewer(), 'Input', caption)

        if not ok:
            raise UserCancelled()

        return inp

    def modified_snuffling_panel(self, value, iparam):
        '''
        Called when the user has played with an adjustable parameter.

        The default implementation sets the parameter, calls the snuffling's
        :py:meth:`call` method and finally triggers an update on the viewer
        widget.
        '''

        param = self.get_parameters()[iparam]
        self._set_parameter_value(param.ident, value)
        if self._live_update:
            self.check_call(self.call)
            self.get_viewer().update()

    def switch_on_snuffling_panel(self, ident, state):
        '''
        Called when the user has toggled a switchable parameter.
        '''

        self._set_parameter_value(ident, state)
        if self._live_update:
            self.check_call(self.call)
            self.get_viewer().update()

    def choose_on_snuffling_panel(self, ident, state):
        '''
        Called when the user has made a choice about a choosable parameter.
        '''

        self._set_parameter_value(ident, state)
        if self._live_update:
            self.check_call(self.call)
            self.get_viewer().update()

    def menuitem_triggered(self, arg):
        '''
        Called when the user has triggered the snuffling's menu.

        The default implementation calls the snuffling's :py:meth:`call` method
        and triggers an update on the viewer widget.
        '''

        self.check_call(self.call)

        if self._have_pre_process_hook:
            self._pre_process_hook_enabled = arg

        if self._have_post_process_hook:
            self._post_process_hook_enabled = arg

        if self._have_pre_process_hook or self._have_post_process_hook:
            self.get_viewer().clean_update()
        else:
            self.get_viewer().update()

    def call_button_triggered(self):
        '''
        Called when the user has clicked the snuffling's call button.

        The default implementation calls the snuffling's :py:meth:`call` method
        and triggers an update on the viewer widget.
        '''

        self.check_call(self.call)
        self.get_viewer().update()

    def clear_button_triggered(self):
        '''
        Called when the user has clicked the snuffling's clear button.

        This calls the :py:meth:`cleanup` method and triggers an update on the
        viewer widget.
        '''

        self.cleanup()
        self.get_viewer().update()

    def help(self):
        '''
        Get help text in html/markdown.
        '''

        # Older snuffling used to provide this through __doc__, newer code
        # should overload .help()
        return self.__doc__ or ''

    def help_button_triggered(self):
        '''
        Creates a :py:class:`QLabel` which contains the documentation as
        given in the snufflings :py:meth:`help`.
        '''

        s = self.help().strip()

        if s:
            if s.startswith('<html>'):
                doc = qw.QLabel(s)
            else:
                try:
                    import markdown
                    doc = qw.QLabel(markdown.markdown(s))

                except ImportError:
                    logger.error(
                        'Install Python module "markdown" for pretty help '
                        'formatting.')

                    doc = qw.QLabel(s)
        else:
            doc = qw.QLabel('This snuffling does not provide any online help.')

        labels = [doc]

        if self._filename:
            from html import escape

            code = open(self._filename, 'r').read()

            doc_src = qw.QLabel(
                '''<html><body>
<hr />
<center><em>May the source be with you, young Skywalker!</em><br /><br />
<a href="file://%s"><code>%s</code></a></center>
<br />
<p style="margin-left: 2em; margin-right: 2em; background-color:#eed;">
<pre style="white-space: pre-wrap"><code>%s
</code></pre></p></body></html>'''
                % (
                    quote(self._filename),
                    escape(self._filename),
                    escape(code)))

            labels.append(doc_src)

        for h in labels:
            h.setAlignment(qc.Qt.AlignTop | qc.Qt.AlignLeft)
            h.setWordWrap(True)

        self._viewer.show_doc('Help: %s' % self._name, labels, target='panel')

    def live_update_toggled(self, on):
        '''
        Called when the checkbox for live-updates has been toggled.
        '''

        self.set_live_update(on)

    def add_traces(self, traces):
        '''
        Add traces to the viewer.

        :param traces: list of objects of type :py:class:`pyrocko.trace.Trace`

        The traces are put into a :py:class:`pyrocko.pile.MemTracesFile` and
        added to the viewer's internal pile for display. Note, that unlike with
        the traces from the files given on the command line, these traces are
        kept in memory and so may quickly occupy a lot of ram if a lot of
        traces are added.

        This method should be preferred over modifying the viewer's internal
        pile directly, because this way, the snuffling has a chance to
        automatically remove its private traces again (see :py:meth:`cleanup`
        method).
        '''

        ticket = self.get_viewer().add_traces(traces)
        self._tickets.append(ticket)
        return ticket

    def add_trace(self, tr):
        '''
        Add a trace to the viewer.

        See :py:meth:`add_traces`.
        '''

        self.add_traces([tr])

    def add_markers(self, markers):
        '''
        Add some markers to the display.

        Takes a list of objects of type
        :py:class:`pyrocko.gui.snuffler.marker.Marker` and adds these to the
        viewer.
        '''

        self.get_viewer().add_markers(markers)
        self._markers.extend(markers)

    def add_marker(self, marker):
        '''
        Add a marker to the display.

        See :py:meth:`add_markers`.
        '''

        self.add_markers([marker])

    def cleanup(self):
        '''
        Remove all traces and markers which have been added so far by the
        snuffling.
        '''

        try:
            viewer = self.get_viewer()
            viewer.release_data(self._tickets)
            viewer.remove_markers(self._markers)

        except NoViewerSet:
            pass

        self._tickets = []
        self._markers = []

    def check_call(self, method):

        if method in self._call_in_progress:
            self.show_message('error', 'Previous action still in progress.')
            return

        try:
            self._call_in_progress[method] = True
            method()
            return 0

        except SnufflingError as e:
            if not isinstance(e, SnufflingCallFailed):
                # those have logged within error()
                logger.error('%s: %s' % (self._name, e))
            logger.error('%s: Snuffling action failed' % self._name)
            return 1

        except Exception as e:
            message = '%s: Snuffling action raised an exception: %s' % (
                self._name, str(e))

            logger.exception(message)
            self.show_message('error', message)

        finally:
            del self._call_in_progress[method]

    def call(self):
        '''
        Main work routine of the snuffling.

        This method is called when the snuffling's menu item has been triggered
        or when the user has played with the panel controls. To be overloaded
        in subclass. The default implementation does nothing useful.
        '''

        pass

    def pre_process_hook(self, traces):
        return traces

    def post_process_hook(self, traces):
        return traces

    def get_tpad(self):
        '''
        Return current amount of extra padding needed by live processing hooks.
        '''

        return 0.0

    def pre_destroy(self):
        '''
        Called when the snuffling instance is about to be deleted.

        Can be overloaded to do user-defined cleanup actions.  The
        default implementation calls :py:meth:`cleanup` and deletes
        the snuffling`s tempory directory, if needed.
        '''

        self.cleanup()
        if self._tempdir is not None:
            import shutil
            shutil.rmtree(self._tempdir)


class SnufflingError(Exception):
    '''
    Base exception for Snuffling errors.
    '''
    pass


class NoViewerSet(SnufflingError):
    '''
    This exception is raised, when no viewer has been set on a Snuffling.
    '''

    def __str__(self):
        return 'No GUI available. ' \
               'Maybe this Snuffling cannot be run in command line mode?'


class MissingStationInformation(SnufflingError):
    '''
    Raised when station information is missing.
    '''


class NoTracesSelected(SnufflingError):
    '''
    This exception is raised, when no traces have been selected in the viewer
    and we cannot fallback to using the current view.
    '''

    def __str__(self):
        return 'No traces have been selected / are available.'


class UserCancelled(SnufflingError):
    '''
    This exception is raised, when the user has cancelled a snuffling dialog.
    '''

    def __str__(self):
        return 'The user has cancelled a dialog.'


class SnufflingCallFailed(SnufflingError):
    '''
    This exception is raised, when :py:meth:`Snuffling.fail` is called from
    :py:meth:`Snuffling.call`.
    '''


class InvalidSnufflingFilename(Exception):
    pass


class SnufflingModule(object):
    '''
    Utility class to load/reload snufflings from a file.

    The snufflings are created by user modules which have the special function
    ``__snufflings__`` which return the snuffling instances to be
    exported. The snuffling module is attached to a handler class, which makes
    use of the snufflings (e.g.
    :py:class:`~pyrocko.gui.snuffler.pile_viewer.PileViewer` from
    ``pile_viewer.py``). The handler class must implement the methods
    ``add_snuffling()`` and ``remove_snuffling()`` which are used as callbacks.
    The callbacks are utilized from the methods :py:meth:`load_if_needed` and
    :py:meth:`remove_snufflings` which may be called from the handler class,
    when needed.
    '''

    mtimes = {}

    def __init__(self, path, name, handler):
        self._path = path
        self._name = name
        self._mtime = None
        self._module = None
        self._snufflings = []
        self._handler = handler

    def load_if_needed(self):
        '''
        Called by Snuffler to check whether it has to reload the module.
        '''
        filename = os.path.join(self._path, self._name+'.py')

        try:
            mtime = os.stat(filename)[8]
        except OSError as e:
            if e.errno == 2:
                logger.error(e)
                raise BrokenSnufflingModule(filename)

        if self._module is None:
            sys.path[0:0] = [self._path]
            try:
                logger.debug('Loading snuffling module %s' % filename)
                if self._name in sys.modules:
                    raise InvalidSnufflingFilename(self._name)

                self._module = __import__(self._name)
                del sys.modules[self._name]

                for snuffling in self._module.__snufflings__():
                    snuffling._filename = filename
                    self.add_snuffling(snuffling)

            except (Exception, SystemExit):
                logger.error(traceback.format_exc())
                raise BrokenSnufflingModule(filename)

            finally:
                sys.path[0:1] = []

        elif self._mtime != mtime:
            logger.warning('Reloading snuffling module %s' % filename)
            settings = self.remove_snufflings()
            sys.path[0:0] = [self._path]
            try:

                sys.modules[self._name] = self._module

                reload(self._module)
                del sys.modules[self._name]

                for snuffling in self._module.__snufflings__():
                    snuffling._filename = filename
                    self.add_snuffling(snuffling, reloaded=True)

                if len(self._snufflings) == len(settings):
                    for sett, snuf in zip(settings, self._snufflings):
                        snuf.set_settings(sett)

            except (Exception, SystemExit):
                logger.error(traceback.format_exc())
                raise BrokenSnufflingModule(filename)

            finally:
                sys.path[0:1] = []

        self._mtime = mtime

    def add_snuffling(self, snuffling, reloaded=False):
        '''
        Called by :py:meth:`load_if_needed` to add a snuffling.
        '''
        snuffling._path = self._path
        snuffling.setup()
        self._snufflings.append(snuffling)
        self._handler.add_snuffling(snuffling, reloaded=reloaded)

    def remove_snufflings(self):
        '''
        Called by :py:meth:`load_if_needed` to remove all snufflings.
        '''
        settings = []
        for snuffling in self._snufflings:
            settings.append(snuffling.get_settings())
            self._handler.remove_snuffling(snuffling)

        self._snufflings = []
        return settings


class BrokenSnufflingModule(Exception):
    pass


class MyScrollArea(qw.QScrollArea):

    def sizeHint(self):
        '''
        '''

        s = qc.QSize()
        s.setWidth(self.widget().sizeHint().width())
        s.setHeight(self.widget().sizeHint().height())
        return s


class SwitchControl(qw.QCheckBox):
    sw_toggled = qc.pyqtSignal(object, bool)

    def __init__(self, ident, default, *args):
        qw.QCheckBox.__init__(self, *args)
        self.ident = ident
        self.setChecked(default)
        self.toggled.connect(self._sw_toggled)

    def _sw_toggled(self, state):
        self.sw_toggled.emit(self.ident, state)

    def set_value(self, state):
        self.blockSignals(True)
        self.setChecked(state)
        self.blockSignals(False)


class ChoiceControl(qw.QFrame):
    choosen = qc.pyqtSignal(object, object)

    def __init__(self, ident, default, choices, name, *args):
        qw.QFrame.__init__(self, *args)
        self.label = qw.QLabel(name, self)
        self.label.setMinimumWidth(120)
        self.cbox = qw.QComboBox(self)
        self.layout = qw.QHBoxLayout(self)
        self.layout.addWidget(self.label)
        self.layout.addWidget(self.cbox)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.ident = ident
        self.choices = choices
        for ichoice, choice in enumerate(choices):
            self.cbox.addItem(choice)

        self.set_value(default)
        self.cbox.activated.connect(self.emit_choosen)

    def set_choices(self, choices):
        icur = self.cbox.currentIndex()
        if icur != -1:
            selected_choice = choices[icur]
        else:
            selected_choice = None

        self.choices = choices
        self.cbox.clear()
        for ichoice, choice in enumerate(choices):
            self.cbox.addItem(qc.QString(choice))

        if selected_choice is not None and selected_choice in choices:
            self.set_value(selected_choice)
            return selected_choice
        else:
            self.set_value(choices[0])
            return choices[0]

    def emit_choosen(self, i):
        self.choosen.emit(
            self.ident,
            self.choices[i])

    def set_value(self, v):
        self.cbox.blockSignals(True)
        for i, choice in enumerate(self.choices):
            if choice == v:
                self.cbox.setCurrentIndex(i)
        self.cbox.blockSignals(False)
