Programming Examples
====================

Load, filter, save
------------------

Read a test file `test.mseed <_static/test.mseed>`_, containing a three component seismogram, apply Butterworth lowpass filter to the seismograms and dump the results to a new file.

::

    from pyrocko import io

    traces = io.load('test.mseed')
   
    for tr in traces:
        tr.lowpass(4, 0.02)   # 4th order, 0.02 Hz
    
    io.save(traces, 'filtered.mseed')

Quickly look at a trace
-----------------------

To visualize a single trace, use the :py:meth:`pyrocko.trace.Trace.snuffle` method. To look at a list of traces, use the :py:func:`pyrocko.trace.snuffle` function. If you want to see the contents of a pile, the :py:meth:`pyrocko.pile.Pile.snuffle` method is your friend. Alternatively, you could of course save the traces to file and use the standalone Snuffler to look at them.

::
     
    from pyrocko import io, trace, pile

    traces = io.load('test.mseed')
    traces[0].snuffle() # look at a single trace
    trace.snuffle(traces) # look at a bunch of traces

    # do something with the traces:
    new_traces = []
    for tr in traces:
        new = tr.copy()
        new.whiten()
        # to allow the viewer to distinguish the traces
        new.set_location('whitened') 
        new_traces.append(new)

    trace.snuffle(traces + new_traces)

    # it is also possible to 'snuffle' a pile:
    p = pile.make_pile(['test.mseed'])
    p.snuffle()


Create a trace object from scratch
----------------------------------

::

    from pyrocko import trace, util, io
    import numpy as num

    nsamples = 100
    tmin = util.str_to_time('2010-02-20 15:15:30.100')
    data = num.random.random(nsamples)
    t1 = trace.Trace(station='TEST', channel='Z', deltat=0.5, tmin=tmin, ydata=data)
    t2 = trace.Trace(station='TEST', channel='N', deltat=0.5, tmin=tmin, ydata=data)
    io.save([t1,t2], 'my_precious_traces.mseed')            # all traces in one file
    io.save([t1,t2], 'my_precious_trace_%(channel)s.mseed') # each file one channel

Extracting part of a trace
----------------------------------

::

    from pyrocko import io
    
    traces = list(io.load('test.mseed'))
    t = traces[0]
    print 'original:', t
    
    # extract a copy of a part of t
    extracted = t.chop(t.tmin+10, t.tmax-10, inplace=False)
    print 'extracted:', extracted
    
    # in-place operation modifies t itself
    t.chop(t.tmin+10, t.tmax-10)
    print 'modified:', t

Reorganizing a dataset into hour-files
----------------------------------------


::

    from pyrocko import pile, io, util
    import time, calendar
    
    p = pile.make_pile(['test.mseed'])  # could give directories or thousands of filenames here
    
    # get timestamp for full hour before first data sample in all selected traces
    tmin = calendar.timegm( time.gmtime(p.tmin)[:4] + ( 0, 0 ) )
    
    # iterate over the data, with a window length of one hour
    for traces in p.chopper(tmin=tmin, tinc=3600):
        if traces:    # the list could be empty due to gaps
            window_start = traces[0].wmin
            timestring = util.time_to_str(window_start, format='%Y-%m-%d_%H')
            filepath = 'test_hourfiles/hourfile-%s.mseed' % timestring
            io.save(traces, filepath)

* in each iteration we get all data for the current time window as a list of traces
* the traces emitted by :py:meth:`pyrocko.pile.Pile.chopper()` 'know' the time window to which
  they belong; it is stored in the attributes ``trace.wmin`` and ``trace.wmax``.
  note: ``trace.tmin`` (its onset) does not have to be identical to ``trace.wmin``
* directory parts in the output path will be created as neccessary
* when applying this procedure to a dataset consisting of arbitrarily separated files, it will automatically connect adjacent traces as needed!

Downsampling a whole dataset
----------------------------------

::

    from pyrocko import pile, io, util
    import time, calendar

    # when pile.make_pile() is called without any arguments, the command line 
    # parameters given to the script are searched for waveform files and directories
    p = pile.make_pile()

    # get timestamp for full hour before first data sample in all selected traces
    tmin = calendar.timegm( time.gmtime(p.tmin)[:4] + ( 0, 0 ) )

    tinc = 3600.
    tpad = 10.
    target_deltat = 0.1

    # iterate over the data, with a window length of one hour and 2x10 seconds of
    # overlap
    for traces in p.chopper(tmin=tmin, tinc=tinc, tpad=tpad):
        
        if traces: # the list could be empty due to gaps
            for tr in traces:
                tr.downsample_to(target_deltat, snap=True, demean=False)
                
                # remove overlapping
                tr.chop(tr.wmin, tr.wmax)
            
            window_start = traces[0].wmin
            timestring = util.time_to_str(window_start, format='%Y-%m-%d_%H')
            filepath = 'downsampled/%(station)s_%(channel)s_%(mytimestring)s.mseed'
            io.save(traces, filepath, additional={'mytimestring': timestring})


    # now look at the result with
    #   > snuffler downsampled/

Convert SAC to MiniSEED
---------------------------

A very basic SAC to MiniSEED converter::

    from pyrocko import io
    import sys

    for filename in sys.argv[1:]:
        traces = io.load(filename, format='sac')
        if filename.lower().endswith('.sac'):
            out_filename = filename[:-4] + '.mseed'
        else:
            out_filename = filename + '.mseed'

        io.save(traces, out_filename)


Convert MiniSEED to ASCII
-----------------------------

An inefficient, non-portable, non-header-preserving, but simple, method to convert some MiniSEED traces to ASCII tables::

    from pyrocko import io
    
    traces = io.load('test.mseed')
    
    for it, t in enumerate(traces):
        f = open('test-%i.txt' % it, 'w')
        
        for tim, val in zip(t.get_xdata(), t.get_ydata()):
            f.write( '%20f %20g\n' % (tim,val) )
        
        f.close()

Restitute traces to displacement using poles and zeros
----------------------------------------------------------

Often we want to deconvolve instrument responses from seismograms. The method
:py:meth:`pyrocko.trace.Trace.transfer` implements a convolution with a
transfer function in the frequency domain. This method takes as argument a
transfer function object which 'knows' how to compute values of the transfer
function at given frequencies. The trace module provides a few different
transfer functions, but it is also possible to write a custom transfer
function. For a transfer function given as poles and zeros, we can use
instances of the class :py:class:`pyrocko.trace.PoleZeroResponse`. There is
also a class :py:class:`InverseEvalrespResponse`, which uses the common ``RESP`` files
through the ``evalresp`` library.

Here is a complete example using a SAC pole-zero file
(`STS2-Generic.polezero.txt <_static/STS2-Generic.polezero.txt>`_) to
deconvolve the transfer function from an example seismogram::

    from pyrocko import pz, io, trace
    
    # read poles and zeros from SAC format pole-zero file
    zeros, poles, constant = pz.read_sac_zpk('STS2-Generic.polezero.txt')
    
    zeros.append(0.0j)  # one more for displacement
    
    # create pole-zero response function object for restitution, so poles and zeros
    # from the response file are swapped here.
    rest_sts2 = trace.PoleZeroResponse(poles, zeros, 1./constant)
    
    traces = io.load('test.mseed')
    out_traces = []
    for trace in traces:
        
        displacement =  trace.transfer(
            1000.,                       # rise and fall of time domain taper in [s]
            (0.001, 0.002, 5., 10.),     # frequency domain taper in [Hz]
            transfer_function=rest_sts2)
        
        # change channel id, so we can distinguish the traces in a trace viewer.
        displacement.set_codes(channel='D'+trace.channel[-1])
        
        out_traces.append(displacement)
            
    io.save(out_traces, 'displacement.mseed')


Distance between two points
-------------------------------

::

    from pyrocko import orthodrome, model

    e = model.Event(lat=10., lon=20.)
    s = model.Station(lat=15., lon=120.)

    # one possibility:
    d = orthodrome.distance_accurate50m(e,s)
    print 'Distance between e and s is %g km' % (d/1000.)

    # another possibility:
    s.set_event_relative_data(e)
    print 'Distance between e and s is %g km' % (s.dist_m/1000.)

Convert a dataset from Mini-SEED to SAC format
--------------------------------------------------

::

    from pyrocko import pile, io, util, model
    
    dinput = 'data/mseed'
    doutput = 'data/sac/%(dirhz)s/%(station)s/%(station)s_%(channel)s_%(tmin)s.sac'
    fn_stations = 'meta/stations.txt'
    
    stations_list = model.load_stations(fn_stations)
    
    stations = {}
    for s in stations_list:
        stations[s.network, s.station, s.location] = s
        s.set_channels_by_name(*'BHN BHE BHZ BLN BLE BLZ'.split())

    p = pile.make_pile(dinput, cachedirname='/tmp/snuffle_cache_u254023')
    h = 3600.
    tinc = 1*h
    tmin = util.day_start(p.tmin)
    for traces in p.chopper_grouped(tmin=tmin, tinc=tinc, gather=lambda tr: tr.nslc_id):
        for tr in traces:
            dirhz = '%ihz' % int(round(1./tr.deltat))
            io.save([tr], doutput, format='sac', additional={'dirhz': dirhz}, stations=stations)

Misfit of one trace against two other traces
------------------------------------------------

Three traces will be created. One of these traces will be assumed to be the reference trace (rt) that we want to know the misfit of in comparison to two other traces (tt1 and tt2). The traces rt and tt1 will be provided with the same random y-data. Hence, their misfit will be zero, in the end.

::

    from pyrocko import trace
    from math import sqrt
    import numpy as num
    
    # Let's create three traces: One trace as the reference (rt) and two as test 
    # traces (tt1 and tt2):
    ydata1 = num.random.random(1000)
    ydata2 = num.random.random(1000)
    rt = trace.Trace(station='REF', ydata=ydata1)
    candidate1 = trace.Trace(station='TT1', ydata=ydata1)
    candidate2 = trace.Trace(station='TT2', ydata=ydata2)
    
    # Define a fader to apply before fft.
    taper = trace.CosFader(xfade=5)
    
    # Define a frequency response to apply before performing the inverse fft.
    # This can be basically any funtion, as long as it contains a function called
    # *evaluate*, which evaluates the frequency response function at a given list
    # of frequencies.
    # Please refer to the :py:class:`FrequencyResponse` class or its subclasses for
    # examples.
    # However, we are going to use a butterworth low-pass filter in this example.
    bw_filter = trace.ButterworthResponse(corner=2,
                                          order=4,
                                          type='low')
    
    # Combine all information in one misfit setup:
    setup = trace.MisfitSetup(description='An Example Setup',
                              norm=2,
                              taper=taper,
                              filter=bw_filter,
                              domain='time_domain')
    
    # Calculate misfits of each candidate against the reference trace:
    for candidate in [candidate1, candidate2]:
        misfit = rt.misfit(candidate=candidate, setup=setup)
        print 'misfit: %s, normalization: %s' % misfit
    
    # Finally, dump the misfit setup that has been used as a yaml file for later
    # re-use:
    setup.dump(filename='my_misfit_setup.txt')
    
If we wanted to reload our misfit setup, guts provides the iload_all() method for 
that purpose:

::

    from pyrocko.guts import load
    from pyrocko.trace import MisfitSetup 
    
    setup = load(filename='my_misfit_setup.txt')
    
    # now, we can change for example only the domain:
    setup.domain = 'frequency_domain'
    
    print setup


Travel time table interpolation
-------------------------------
This example demonstrates how to interpolate and query travel time tables.

Classes covered in this example:
 * :py:class:`pyrocko.spit.SPTree` (interpolation of travel time tables)
 * :py:class:`pyrocko.gf.meta.TPDef` (phase definitions)
 * :py:class:`pyrocko.gf.meta.Timing` (onset definition to query the travel
   time tables)

::

    import numpy as num
    import matplotlib.pyplot as plt
    from pyrocko import spit, cake
    from pyrocko.gf import meta


    # Define a list of phases.
    phase_defs = [meta.TPDef(id='p', definition='p'),
                  meta.TPDef(id='P', definition='P')]

    # Load a velocity model. In this example use the default AK135.
    mod = cake.load_model()

    # Time and space tolerance thresholds defining the accuracy of the
    # :py:class:`pyrocko.spit.SPTree`.
    t_tolerance = 0.1                           # in seconds
    x_tolerance = num.array((100., 100.))       # in meters

    # Boundaries of the grid.
    xmin = 0.
    xmax = 20000
    zmin = 0.
    zmax = 11000
    x_bounds = num.array(((xmin, xmax), (zmin, zmax)))

    # In this example the receiver is located at the surface.
    receiver_depth = 0.

    interpolated_tts = {}
    for phase_def in phase_defs:
        v_horizontal = phase_def.horizontal_velocities

        def evaluate(args):
            '''Calculate arrival using source and receiver location
            defined by *args*. To be evaluated by the SPTree instance.'''
            source_depth, x = args

            t = []

            # Calculate arrivals
            rays = mod.arrivals(
                phases=phase_def.phases,
                distances=[x*cake.m2d],
                zstart=source_depth,
                zstop=receiver_depth)

            for ray in rays:
                t.append(ray.t)

            for v in v_horizontal:
                t.append(x/(v*1000.))
            if t:
                return min(t)
            else:
                return None

        # Creat a :py:class:`pyrocko.spit.SPTree` interpolator.
        sptree = spit.SPTree(
            f=evaluate,
            ftol=t_tolerance,
            xbounds=x_bounds,
            xtols=x_tolerance)

        # Store the result in a dictionary which is later used to retrieve an
        # SPTree (value) for each phase_id (key).
        interpolated_tts[phase_def.id] = sptree

        # Dump the sptree for later reuse:
        sptree.dump(filename='sptree_%s.yaml' % phase_def.id)

    # Define a :py:class:`pyrocko.gf.meta.Timing` instance.
    timing = meta.Timing('first(p|P)')


    # If only one interpolated onset is need at a time you can retrieve
    # that value as follows:
    # First argument has to be a function which takes a requested *phase_id*
    # and returns the associated :py:class:`pyrocko.spit.SPTree` instance.
    # Second argument is a tuple of distance and source depth.
    z_want = 5000.
    x_want = 2000.
    one_onset = timing.evaluate(lambda x: interpolated_tts[x],
                                (z_want, x_want))
    print 'a single arrival: ', one_onset


    # But if you have many locations for which you would like to calculate the
    # onset time the following is the preferred way as it is much faster
    # on large coordinate arrays.
    # x_want is now an array of 10000 distances
    x_want = num.linspace(0, xmax, 10000)

    # Coords is set up of distances-depth-pairs
    coords = num.array((x_want, num.tile(z_want, x_want.shape))).T

    # *interpolate_many* then interpolates onset times for each of these
    # pairs.
    tts = interpolated_tts["p"].interpolate_many(coords)

    # Plot distance vs. onset time
    plt.plot(x_want, tts, '.')
    plt.show()


Retrieve synthetic seismograms from a local store
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. highlight:: python

It is assumed that a :class:`~pyrocko.gf.store.Store` with store ID
*crust2_dd* has been downloaded in advance. A list of currently available
stores can be found at http://kinherd.org/gfs.html as well as how to download
such stores.

Further API documentation for the utilized objects can be found at :class:`~pyrocko.gf.targets.Target`,
:class:`~pyrocko.gf.seismosizer.LocalEngine` and :class:`~pyrocko.gf.seismosizer.DCSource`.

::

    from pyrocko.gf import LocalEngine, Target, DCSource
    from pyrocko import trace
    from pyrocko.gui_util import PhaseMarker

    # We need a pyrocko.gf.Engine object which provides us with the traces
    # extracted from the store. In this case we are going to use a local
    # engine since we are going to query a local store.
    engine = LocalEngine(store_superdirs=['/media/usb/stores'])

    # The store we are going extract data from:
    store_id = 'crust2_dd'

    # Define a list of pyrocko.gf.Target objects, representing the recording
    # devices. In this case one station with a three component sensor will
    # serve fine for demonstation.
    channel_codes = 'ENZ'
    targets = [
        Target(
            lat=10.,
            lon=10.,
            store_id=store_id,
            codes=('', 'STA', '', channel_code))
        for channel_code in channel_codes]

    # Let's use a double couple source representation.
    source_dc = DCSource(
        lat=11.,
        lon=11.,
        depth=10000.,
        strike=20.,
        dip=40.,
        rake=60.,
        magnitude=4.)

    # Processing that data will return a pyrocko.gf.Reponse object.
    response = engine.process(source_dc, targets)

    # This will return a list of the requested traces:
    synthetic_traces = response.pyrocko_traces()

    # In addition to that it is also possible to extract interpolated travel times
    # of phases which have been defined in the store's config file.
    store = engine.get_store(store_id)

    markers = []
    for t in targets:
        dist = t.distance_to(source_dc)
        depth = source_dc.depth
        arrival_time = store.t('p', (depth, dist))
        m = PhaseMarker(tmin=arrival_time,
                        tmax=arrival_time,
                        phasename='p',
                        nslc_ids=(t.codes,))
        markers.append(m)

    # Processing that data will return a pyrocko.gf.Response object.
    response = engine.process(source_dc, targets)

    # This will return a list of the requested traces:
    synthetic_traces = response.pyrocko_traces()

    # Finally, let's scrutinize these traces.
    trace.snuffle(synthetic_traces, markers=markers)

Retrieve spatial displacement from a local store
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In this example we create a :class:`~pyrocko.gf.RectangularSource` and compute
the spatial static/geodetic displacement caused by that rupture.

We will utilize :class:`~pyrocko.gf.seismosizer.LocalEngine`, :class:`~pyrocko.gf.targets.StaticTarget` and :class:`~pyrocko.gf.targets.SatelliteTarget` in this example.

::

	from pyrocko.gf import LocalEngine, StaticTarget, SatelliteTarget,\
		RectangularSource
	import numpy as num

	km = 1e3

	# Ignite the LocalEngine and point it to fomosto stores stored on a
	# USB stick, for this example we use a static store with id 'static_store'
	engine = LocalEngine(store_superdirs=['/media/usb/stores'])
	store_id = 'static_store'

	# We define an extended source, in this case a rectangular geometry
	# Centroid UTM position is defined relatively to geographical lat, lon position
	rect_source = RectangularSource(
		lat=0., lon=0.,
		north_shift=0., east_shift=0., depth=6.5*km,
		width=5*km, length=8*km,
		dip=90., rake=90., strike=90.,
		slip=1.)

	# We will define 1000 randomly distributed targets.
	ntargets = 1000

	# We initialize the satellite target and set the line of sight vectors direction
	phi = num.empty(ntargets)    # Horizontal LOS from E
	theta = num.empty(ntargets)  # Vertical LOS from vertical
	phi.fill(num.deg2rad(192.))
	theta.fill(num.deg2rad(90.-23.))

	satellite_target = SatelliteTarget(
		north_shifts=(num.random.rand(ntargets)-.5) * 25. * km,
		east_shifts=(num.random.rand(ntargets)-.5) * 25. * km,
		tsnapshot=60,
		interpolation='nearest_neighbor',
		phi=phi,
		theta=theta)

	# The computation is performed by calling process on the engine
	result = engine.process(rect_source, [satellite_target])

	# Helper function for plotting the displacement
	def plot_static_los_result(result, target=0):
		import matplotlib.pyplot as plt
		fig, _ = plt.subplots(1, 4,figsize=(8,4))
		fig.subplots_adjust(wspace=0.5)

		N = result.request.targets[target].coords5[:, 2]
		E = result.request.targets[target].coords5[:, 3]
		result = result.results_list[0][target].result

		vranges = [(result['displacement.%s' % c].max(),
					result['displacement.%s' % c].min()) for c in list('ned') +
				['los']]

		lmax = num.abs([num.min(vranges), num.max(vranges)]).max()
		levels = num.linspace(-lmax, lmax, 50)

		for dspl, ax in zip(list('ned') + ['los'], fig.axes):
			cmap = ax.tricontourf(E, N, result['displacement.%s' % dspl],
								cmap='seismic', levels=levels)
			ax.set_title('displacement.%s' % dspl)
			ax.set_aspect('equal')

			n, e = rect_source.outline(cs='xy').T
			ax.fill(e, n, color=(0.5, 0.5, 0.5), alpha=0.5)

		fig.colorbar(cmap, aspect=5)
		plt.show()

	plot_static_los_result(result)


.. figure:: _static/rect_source.png
	:align: center
