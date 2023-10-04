
Extending Snuffler with plugins: Snufflings
===========================================

Snufflings are small Python scripts which extend the functionality of Snuffler.
Snuffler looks into the directory ``$HOME/.snufflings`` for snufflings.
Snufflings can be reloaded at run-time using the menu entry 'Reload Snufflings'
in the main menu of Snuffler - no need to restart Snuffler when a snuffling is
modified or added.

Already existing snufflings can be downloaded from the  `snuffling repository <https://git.pyrocko.org/pyrocko/contrib-snufflings>`_

Example Snuffling to show earthquake catalog information within Snuffler
------------------------------------------------------------------------

Put the following code into ``$HOME/.snufflings/geofon.py``. It will add four
items into the *Snufflings* sub-menu of Snuffler (*Get GEOFON events*, *Get
GEOFON events (> M6)*, ...). When one of these is selected by the user, the
`GEOFON catalog <http://geofon.gfz-potsdam.de/eqinfo/form.php>`_ is queried for
earthquake information for the time range visible in Snuffler. For each
earthquake found, a marker is shown in the viewer.

::

    from pyrocko.gui.snuffler.snuffling import Snuffling, Param
    from pyrocko.gui.snuffler.pile_viewer import Marker, EventMarker
    from pyrocko.client import catalog

    class GeofonEvents(Snuffling):
        
        '''
        Get events from GEOFON catalog.
        '''

        def __init__(self, magmin=None):
            self._magmin = magmin
            Snuffling.__init__(self)

        def setup(self):
            '''Customization of the snuffling.'''
            
            if self._magmin is None:
                self.set_name('Get GEOFON Events')
            else:
                self.set_name('Get GEOFON Events (> M %g)' % self._magmin)
            
        def call(self):
            '''Main work routine of the snuffling.'''
            
            # get time range visible in viewer
            viewer = self.get_viewer()
            tmin, tmax = viewer.get_time_range()
            
            # download event information from GEOFON web page
            # 1) get list of event names
            geofon = catalog.Geofon()
            event_names = geofon.get_event_names(
                time_range=(tmin,tmax), 
                magmin=self._magmin)
                
            # 2) get event information and add a marker in the snuffler window
            for event_name in event_names:
                event = geofon.get_event(event_name)
                marker = EventMarker(event)
                self.add_markers([marker])
                    
    def __snufflings__():
        '''Returns a list of snufflings to be exported by this module.'''
        
        return [ GeofonEvents(), 
                 GeofonEvents(magmin=6), 
                 GeofonEvents(magmin=7), 
                 GeofonEvents(magmin=8) ]

How it works
^^^^^^^^^^^^

Snuffler looks into the directory ``HOME/.snufflings`` for python scripts
(``*.py``). Within each of these it tries to query the function
``__snufflings__()`` which should return a list of snuffling objects, which are
instances of a snuffling class. A custom snuffling class is created by
subclassing :py:class:`~pyrocko.gui.snuffler.snuffling.Snuffling`. Within the derived class implement
the methods ``setup()`` and ``call()``. ``setup()`` is called during
initialization of the snuffling object, ``call()`` is called when the user
selects the menu entry. You may define several snuffling classes within one
snuffling source file. You may also return several instances of a single
snuffling class from the ``__snufflings__()`` function.

The :py:class:`~pyrocko.gui.snuffler.snuffling.Snuffling` base class documentation can also
be accessed with the command ``pydoc pyrocko.gui.snuffler.snuffling.Snuffling`` from the
shell. Example snufflings can be found in `src/gui/snuffler/snufflings/ <https://git.pyrocko.org/pyrocko/pyrocko/src/master/src/gui/snuffler/snufflings>`_
in the pyrocko source code. More examples may be found in the 
`contrib-snufflings repository <https://git.pyrocko.org/pyrocko/contrib-snufflings>`_ repository.

More examples
-------------

Print minimum, maximum, and peak-to-peak amplitudes to the terminal
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This is a built-in snuffling of Snuffler. It serves here as a demonstration of
how selected trace data can be accessed from within the snuffling.

::

    from pyrocko.gui.snuffler.snuffling import Snuffling, Param
    from pyrocko import trace

    class MinMaxSnuffling(Snuffling):
        
        '''Reports minimum, maximum, and peak-to-peak values of selected data.
    To use it, use the picker tool to mark a region or select existing regions
    and call this snuffling. The values are printed via standard output to the
    termimal.'''

        def setup(self):
            '''Customization of the snuffling.'''
            
            self.set_name('Minimum Maximum Peak-To-Peak')
            self.tinc = None

        def call(self):
            '''Main work routine of the snuffling.'''
                    
            # to select a reasonable increment for the chopping, the smallest
            # sampling interval in the pile is looked at. this is only done,
            # the first time the snuffling is called.
            if self.tinc is None:
                self.tinc = self.get_pile().get_deltats()[0] * 10000.
            
            # the chopper yields lists of traces but for minmax() below, an iterator
            # yielding single traces is needed; using a converter:
            def iter_single_traces():
                for traces in self.chopper_selected_traces(tinc=self.tinc, 
                                                           degap=False, 
                                                           fallback=True):
                    for tr in traces:
                        yield tr
            
            # the function minmax() in the trace module can get minima and maxima
            # grouped by (network,station,location,channel):
            mima = trace.minmax(iter_single_traces())
            
            for nslc in sorted(mima.keys()):
                p2p = mima[nslc][1] - mima[nslc][0]
                print '%s.%s.%s.%s: %12.5g %12.5g %12.5g' % (nslc + mima[nslc] + (p2p,))
                                                
    def __snufflings__():
        '''Returns a list of snufflings to be exported by this module.'''
        
        return [ MinMaxSnuffling() ]


How to add simple markers to the viewer
---------------------------------------

::

    from pyrocko.gui.snuffler.snuffling import Snuffling
    from pyrocko.gui.snuffler.pile_viewer import Marker

    class Example1(Snuffling):
        
        '''Example Snuffling to demonstrate how to add markers to the viewer.

    It looks at all selected traces and puts a Marker at the peak amplitude of the
    raw traces. If no traces are selected all traces in view are used.  It is not
    affected by filter settings of the viewer.

    This works well for short continuous traces, but if longer or gappy traces are
    in the viewer, there may be some problems which are not 
    '''

        def setup(self):
            # this sets the name for the menu entry:
            self.set_name('Example 1: mark peak amplitudes')

        def call(self):
            
            # remove all markers which have been previously added by this snuffling
            self.cleanup()

            # this is a shortcut to get selected traces or all traces in view
            for traces in self.chopper_selected_traces(fallback=True):

                for tr in traces:
                    net, sta, loc, cha = tr.nslc_id

                    # using a trace method to get time and amplitude
                    time, amplitude = tr.absmax()

                    # the marker kind sets the color of the marker
                    kind = 3 

                    # create the marker object
                    m = Marker([ (net, sta, loc, cha) ], time, time, kind )

                    # add it to the viewer
                    self.add_marker(m)

    def __snufflings__():
        return [ Example1() ]
