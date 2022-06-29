# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
This module provides basic compatibility between ObsPy and Pyrocko.

The functions defined here can be used to translate back and forth some of the
basic objects in Pyrocko and ObsPy. It also provides shortcuts to quickly look
at ObsPy waveforms with the Pyrocko's :doc:`Snuffler </apps/snuffler/index>`
application (:py:func:`snuffle`, :py:func:`fiddle`).

With :func:`pyrocko.obspy_compat.plant` several new methods are attached to
Pyrocko and ObsPy classes.

**Example, visualize ObsPy stream object with Snuffler:**

.. code-block:: python

    import obspy
    from pyrocko import obspy_compat
    obspy_compat.plant()

    stream = obspy.read()  # returns some example data
    stream.snuffle()

-- *With best wishes to the ObsPy Team from the Pyrocko Developers!*

.. note::

    This is an experimental module, the interface may still be changed.
    Feedback and discussion welcome!

'''

from __future__ import absolute_import, print_function, division


def to_pyrocko_trace(trace):
    '''
    Convert ObsPy trace object to Pyrocko trace object.

    :param trace:
        :py:class:`obspy.Trace <obspy.core.trace.Trace>` object
    :returns:
        :py:class:`pyrocko.trace.Trace` object
    '''
    obspy_trace = trace
    from pyrocko import trace

    return trace.Trace(
        str(obspy_trace.stats.network),
        str(obspy_trace.stats.station),
        str(obspy_trace.stats.location),
        str(obspy_trace.stats.channel),
        tmin=obspy_trace.stats.starttime.timestamp,
        tmax=obspy_trace.stats.endtime.timestamp,
        ydata=obspy_trace.data,
        deltat=obspy_trace.stats.delta)


def to_pyrocko_traces(stream):
    '''
    Convert ObsPy stream object to list of Pyrocko trace objects.

    :param stream:
        :py:class:`obspy.Stream <obspy.core.stream.Stream>` object
    :returns:
        list of :py:class:`pyrocko.trace.Trace` objects
    '''

    obspy_stream = stream

    return [to_pyrocko_trace(obspy_trace) for obspy_trace in obspy_stream]


def to_pyrocko_events(catalog):
    '''
    Convert ObsPy catalog object to list of Pyrocko event objects.

    :param catalog:
        :py:class:`obspy.Catalog <obspy.core.event.Catalog>` object
    :returns:
        list of :py:class:`pyrocko.model.Event` objects or ``None`` if catalog
        is ``None``
    '''

    obspy_catalog = catalog

    if obspy_catalog is None:
        return None

    from pyrocko import model

    events = []
    for obspy_event in obspy_catalog:
        for origin in obspy_event.origins:

            events.append(model.Event(
                name='%s-%s' % (obspy_event.resource_id, origin.resource_id),
                time=origin.time.timestamp,
                lat=origin.latitude,
                lon=origin.longitude,
                depth=origin.depth,
                region=origin.region))

    return events


def to_pyrocko_stations(inventory):
    '''
    Convert ObsPy inventory to list of Pyrocko traces.

    :param inventory:
        :py:class:`obspy.Inventory <obspy.core.inventory.inventory.Inventory>`
        object
    :returns:
        list of :py:class:`pyrocko.model.Station` objects or ``None`` if
        inventory is ``None``
    '''

    obspy_inventory = inventory

    if obspy_inventory is None:
        return None

    from pyrocko import model
    stations = []
    for net in obspy_inventory.networks:
        for sta in net.stations:
            stations.append(
                model.Station(
                    lat=sta.latitude,
                    lon=sta.longitude,
                    elevation=sta.elevation,
                    network=net.code,
                    station=sta.code,
                    location='',
                    channels=[
                        model.station.Channel(
                            name=cha.code,
                            azimuth=cha.azimuth,
                            dip=cha.dip) for cha in sta.channels]
                    ))

    return stations


def to_obspy_stream(pile):
    '''
    Convert Pyrocko pile to ObsPy stream.

    :param pile:
        :py:class:`pyrocko.pile.Pile` object
    :returns:
        :py:class:`obspy.Stream <obspy.core.stream.Stream>` object
    '''

    pyrocko_pile = pile

    import obspy
    stream = obspy.Stream()
    stream.extend([to_obspy_trace(tr) for tr in pyrocko_pile.iter_all()])
    return stream


def to_obspy_trace(trace):
    '''
    Convert Pyrocko trace to ObsPy trace.

    :param trace:
        :py:class:`pyrocko.trace.Trace`
    '''
    import obspy

    pyrocko_trace = trace

    obspy_trace = obspy.Trace(
        data=pyrocko_trace.ydata,
        header=obspy.core.trace.Stats(
            dict(
                npts=len(pyrocko_trace.ydata),
                network=pyrocko_trace.network,
                station=pyrocko_trace.station,
                location=pyrocko_trace.location,
                channel=pyrocko_trace.channel,
                delta=pyrocko_trace.deltat,
                starttime=pyrocko_trace.tmin,
                endtime=pyrocko_trace.tmax)
            ))

    return obspy_trace


def snuffle(stream_or_trace, inventory=None, catalog=None, **kwargs):
    '''
    Explore ObsPy data with Snuffler.

    :param stream_or_trace:
        :py:class:`obspy.Stream <obspy.core.stream.Stream>` or
        :py:class:`obspy.Trace <obspy.core.trace.Trace>` object
    :param inventory:
        :py:class:`obspy.Inventory <obspy.core.inventory.inventory.Inventory>`
        object
    :param catalog:
        :py:class:`obspy.Catalog <obspy.core.event.Catalog>` object
    :param kwargs:
        extra arguments passed to :meth:`pyrocko.trace.Trace.snuffle`.

    :returns:
        ``(return_tag, markers)``, where ``return_tag`` is the a string to flag
        how the Snuffler window has been closed and ``markers`` is a list of
        :py:class:`pyrocko.gui.snuffler.marker.Marker` objects.

    This function displays an ObsPy stream object in Snuffler. It returns to
    the caller once the window has been closed. The ``return_tag`` returned by
    the function can be used as a primitive way to communicate a user decision
    to the calling script. By default it returns the key pressed to close the
    window (if any), either ``'q'`` or ``'x'``, but the value could be
    customized when the exit is triggered from within a Snuffling.

    See also :py:func:`fiddle` for a variant of this function returning
    an interactively modified ObsPy stream object.
    '''

    from pyrocko import trace
    import obspy

    obspy_inventory = inventory
    obspy_catalog = catalog

    if isinstance(stream_or_trace, obspy.Trace):
        obspy_stream = obspy.core.stream.Stream(traces=[stream_or_trace])
    else:
        obspy_stream = stream_or_trace

    events = to_pyrocko_events(obspy_catalog)
    stations = to_pyrocko_stations(obspy_inventory)

    return trace.snuffle(
        to_pyrocko_traces(obspy_stream),
        events=events,
        stations=stations,
        want_markers=True,
        **kwargs)


class ObsPyStreamSnufflingLoader(object):

    def __init__(self, obspy_stream):
        self.obspy_stream = obspy_stream

    def __call__(self, win):
        from .snuffling import ObsPyStreamSnuffling
        self.snuffling = ObsPyStreamSnuffling(obspy_stream=self.obspy_stream)
        self.snuffling.setup()
        win.pile_viewer.viewer.add_snuffling(self.snuffling, reloaded=True)

    def get_snuffling(self):
        return self.snuffling


def fiddle(stream_or_trace, inventory=None, catalog=None, **kwargs):
    '''
    Manipulate ObsPy stream object interactively.

    :param stream_or_trace:
        :py:class:`obspy.Stream <obspy.core.stream.Stream>` or
        :py:class:`obspy.Trace <obspy.core.trace.Trace>` object
    :param inventory:
        :py:class:`obspy.Inventory <obspy.core.inventory.inventory.Inventory>`
        object
    :param catalog:
        :py:class:`obspy.Catalog <obspy.core.event.Catalog>` object
    :param kwargs:
        extra arguments passed to :meth:`pyrocko.trace.Trace.snuffle`.

    :returns: :py:class:`obspy.Stream <obspy.core.stream.Stream>` object with
        changes applied interactively (or :py:class:`obspy.Trace
        <obspy.core.trace.Trace>` if called with a trace as first argument).

    This function displays an ObsPy stream object in Snuffler like
    :py:func:`snuffle`, but additionally adds a Snuffling panel to apply some
    basic ObsPy signal processing to the contained traces. The applied changes
    are handed back to the caller as a modified copy of the stream object.

    .. code::

        import obspy
        from pyrocko import obspy_compat

        obspy_compat.plant()

        stream = obspy.read()
        stream_filtered = stream.fiddle()  # returns once window has been
                                           # closed
    '''

    from pyrocko import trace
    import obspy

    obspy_inventory = inventory
    obspy_catalog = catalog

    if isinstance(stream_or_trace, obspy.Trace):
        obspy_stream = obspy.core.stream.Stream(traces=[stream_or_trace])
    else:
        obspy_stream = stream_or_trace

    events = to_pyrocko_events(obspy_catalog)
    stations = to_pyrocko_stations(obspy_inventory)

    snuffling_loader = ObsPyStreamSnufflingLoader(obspy_stream)
    launch_hook = kwargs.pop('launch_hook', [])
    if not isinstance(launch_hook, list):
        launch_hook = [launch_hook]
    launch_hook.append(snuffling_loader)

    trace.snuffle(
        [],
        events=events,
        stations=stations,
        controls=False,
        launch_hook=launch_hook,
        **kwargs)

    new_obspy_stream = snuffling_loader.get_snuffling().get_obspy_stream()

    if isinstance(obspy_stream, obspy.Trace):
        return new_obspy_stream[0]
    else:
        return new_obspy_stream


def plant():
    '''
    Add conversion functions as methods to ObsPy and Pyrocko classes.

    Methods added to ObsPy classes are:

    +--------------------------------------+---------------------------------+
    | class                                | methods                         |
    +======================================+=================================+
    | :py:class:`obspy.Trace`              | :py:func:`to_pyrocko_trace`     |
    |                                      +---------------------------------+
    |                                      | :py:func:`snuffle`              |
    |                                      +---------------------------------+
    |                                      | :py:func:`fiddle`               |
    +--------------------------------------+---------------------------------+
    | :py:class:`obspy.Stream`             | :py:func:`to_pyrocko_traces`    |
    |                                      +---------------------------------+
    |                                      | :py:func:`snuffle`              |
    |                                      +---------------------------------+
    |                                      | :py:func:`fiddle`               |
    +--------------------------------------+---------------------------------+
    | :py:class:`obspy.Catalog`            | :py:func:`to_pyrocko_events`    |
    +--------------------------------------+---------------------------------+
    | :py:class:`obspy.Inventory`          | :py:func:`to_pyrocko_stations`  |
    +--------------------------------------+---------------------------------+

    Methods added to Pyrocko classes are:

    +--------------------------------------+---------------------------------+
    | class                                | methods                         |
    +======================================+=================================+
    | :py:class:`pyrocko.trace.Trace`      | :py:func:`to_obspy_trace`       |
    +--------------------------------------+---------------------------------+
    | :py:class:`pyrocko.pile.Pile`        | :py:func:`to_obspy_stream`      |
    +--------------------------------------+---------------------------------+
    '''

    import obspy
    obspy.Trace.to_pyrocko_trace = to_pyrocko_trace
    obspy.Trace.snuffle = snuffle
    obspy.Trace.fiddle = fiddle

    obspy.Stream.to_pyrocko_traces = to_pyrocko_traces
    obspy.Stream.snuffle = snuffle
    obspy.Stream.fiddle = fiddle

    obspy.core.event.Catalog.to_pyrocko_events = to_pyrocko_events
    obspy.core.inventory.inventory.Inventory.to_pyrocko_stations =\
        to_pyrocko_stations

    import pyrocko.trace
    import pyrocko.pile
    pyrocko.trace.Trace.to_obspy_trace = to_obspy_trace
    pyrocko.pile.Pile.to_obspy_stream = to_obspy_stream


__all__ = [
    'to_pyrocko_trace',
    'to_pyrocko_traces',
    'to_pyrocko_events',
    'to_pyrocko_stations',
    'to_obspy_stream',
    'to_obspy_trace',
    'snuffle',
    'fiddle',
    'plant']
