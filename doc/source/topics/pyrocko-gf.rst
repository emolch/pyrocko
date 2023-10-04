**********************************************************************************
Pyrocko-GF - *Geophysical forward modelling with pre-calculated Green’s functions*
**********************************************************************************

Introduction
============

Many seismological methods make use of numerically calculated Green’s
functions (GFs). Often these are required for a vast number of combinations of source
and receiver coordinates, e.g. when computing synthetic seismograms in seismic
source inversions. Calculation of the GFs is a computationally
expensive operation and it can be of advantage to calculate them in advance.
The same GF traces can then be reused many times as required in a
typical application.

To efficiently reuse GFs across different applications, they must be stored in
a common format. In such a form, they can also be passed to fellow researchers.

Furthermore, it is useful to store associated meta information, like e.g. 
travel time tables for seismic phases and the earth model used, together with
the GF in order to have a complete and consistent framework to play with.

.. figure :: /static/software_architecture.svg
    :align: center
    :alt: Overview of the components and interaction for Pyrocko-GF


Pyrocko contains a flexible framework to store and work with pre-calculated
GFs. It is implemented in the :mod:`pyrocko.gf` sub-package. Also
included, is a powerful front end tool to create, inspect, and manipulate
GF stores: the :program:`fomosto` tool ("forward model storage
tool").

.. contents :: Content
  :depth: 2

Media models
============

Where Pyrocko uses layered 1D earth models in the calculation of GFs it uses the `TauP <https://www.seis.sc.edu/downloads/TauP/taup.pdf>`_ :file:`.nd` (named discontinuity) format. These files are ascii tables with the following columns:

.. code-block :: text
    :caption: Structure of a named discontinuities file (:file:`.nd`).

    depth [km]    Vp[km/s]    Vs[km/s]    density[g/cm^3]    qp    qs

The :doc:`fomosto <../apps/fomosto/index>` application description holds an exemplary earth model configuration. Users can define own input models before calculation. Also a number of predefined common variations of AK135 and PREM models are available. They can be listed and inspected using the :doc:`cake <../apps/cake/index>` command line tool.

Green’s function stores
=======================

GF pre-calculation
------------------

Calculating and managing Pyrocko-GF stores is accomplished by Pyrocko’s :program:`fomosto` application. More details how GF stores are set-up and calculated can be found in the :doc:`fomosto tutorial <../apps/fomosto/tutorial>`.

Downloading GF stores
---------------------

Calculating and quality checking GF stores is a time consuming task. Many pre-calculated stores can be downloaded from our online repository, the `Green's mill (greens-mill.pyrocko.org) <https://greens-mill.pyrocko.org>`_.

The available stores include dynamic stores for simulating waveforms at global and regional extents, as well as static stores for the modelling of step-like surface displacements.


.. code-block:: sh
    :caption: Downloading a store with :program:`fomosto`

    fomosto download kinherd global_2s_25km 

Using GF Stores
---------------

GF stores are accessed for forward modelling by the Pyrocko-GF :py:class:`~pyrocko.gf.seismosizer.Engine`. Here is how we can start-up the engine for modelling:

.. code-block :: python
   :caption: Import and initialise the forward modelling engine.

   from pyrocko.gf import LocalEngine

   engine = LocalEngine(store_dirs=['gf_stores/global_2s/'])

A complete list of arguments can be found in the library reference, :class:`~pyrocko.gf.seismosizer.LocalEngine`.

Source models
=============

Pyrocko-GF supports the simulation of various dislocation sources, focused on
earthquake and volcano studies.


.. note ::

    Multiple sources can be combined through the :class:`~pyrocko.gf.seismosizer.CombiSource` object.

Point sources
-------------

For convenience, different parameterizations of seismological moment tensor
point sources are available.

+---------------------------------------------------------+------------------------------------------------------------------------+
|Source                                                   | Short description                                                      |
+=========================================================+========================================================================+
|:class:`~pyrocko.gf.seismosizer.ExplosionSource`         | An isotrope moment tensor for explosions or volume changes.            |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.DCSource`                | Double force couple, for pure-shear earthquake ruptures.               |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.MTSource`                | Full moment tensor representation of force excitation.                 |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.CLVDSource`              | A pure compensated linear vector dipole source.                        |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.VLVDSource`              | Volumetric linear vector dipole, a rotational symmetric volume source. |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.SFSource`                | A 3-component single force point source.                               |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.PorePressurePointSource` | Excess pore pressure point source.                                     |
+---------------------------------------------------------+------------------------------------------------------------------------+

Finite sources
--------------

+---------------------------------------------------------+------------------------------------------------------------------------+
| Source                                                  | Short description                                                      |
+=========================================================+========================================================================+
|:class:`~pyrocko.gf.seismosizer.RectangularSource`       | Rectangular fault plane.                                               |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.RingfaultSource`         | Ring fault for volcanic processes, e.g. caldera collapses.             |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.DoubleDCSource`          | Relative parameterization of a twin double couple source.              |
+---------------------------------------------------------+------------------------------------------------------------------------+
|:class:`~pyrocko.gf.seismosizer.PorePressureLineSource`  | Excess pore pressure line source                                       |
+---------------------------------------------------------+------------------------------------------------------------------------+





First import the Pyrocko-GF framework with

.. code-block :: python
    :caption: Import all object from ``pyrocko.gf``.

    from pyrocko import gf


Explosion source
----------------

.. figure :: /static/source-explosion.svg
  :width: 20%
  :figwidth: 50%
  :align: center
  :alt: explosion source

An isotropic explosion point source, which can also be used for dislocations due to volume changes.

.. code-block :: python
    :caption: Initialise a simple explosion source with a volume

    explosion = gf.ExplosionSource(lat=42., lon=22., depth=8e3, volume_change=5e8)

Double couple
-------------

.. figure :: /static/source-doublecouple.svg
  :width: 20%
  :figwidth: 50%
  :align: center
  :alt: double couple source

A double-couple point source, describing shear ruptures.

.. code-block :: python
    :caption: Initialise a double-couple source.

    dc_source = gf.DCSource(lat=54., lon=7., depth=5e3, strike=33., dip=20., rake=80.)

Moment tensor
-------------

.. figure :: /static/source-mt.svg
  :width: 20%
  :figwidth: 50%
  :align: center
  :alt: moment tensor source

A moment tensor point source. This is the most complete form of describing an ensemble of buried forces to first order.

.. code-block :: python
    :caption: Initialise a full moment tensor.

    mt_source = gf.MTSource(
       lat=20., lon=58., depth=8.3e3,
       mnn=.5, mee=.1, mdd=.7,
       mne=.6, mnd=.2, med=.1,)

    # Or use an event
    mt_source = MTSource.from_pyrocko_event(event)

CLVD source
-----------

.. figure :: /static/source-clvd.svg
  :width: 20%
  :figwidth: 50%
  :align: center
  :alt: clvd source

A compensated linear vector dipole (CLVD) point source.

.. code-block :: python
    :caption: Initialise a CLVD source.

    clvd_source = gf.CLVDSource(
        lat=48., lon=17., depth=5e3, dip=31., depth=5e3, azimuth=83.)

VLVD source
-----------

A volumetric linear vector dipole, a uniaxial rotational symmetric moment tensor source. This source can be used to constrain sill or dyke like volume dislocation.

.. code-block :: python
    :caption: Initialise a VLVD source.

    vlvd_source = gf.VLVDSource(
       lat=-30., lon=184., depth=5e3, 
       volume_change=1e9, clvd_moment=20e9, dip=10., azimuth=110.)

Rectangular fault
-----------------

.. figure :: /static/source-rectangular.svg
  :width: 40%
  :figwidth: 50%
  :align: center
  :alt: moment tensor source

Classical Haskell finite source model, modified for bilateral rupture.

.. code-block :: python
    :caption: Initialise a rectangular fault with a width of 3 km, a length of 8 km and slip of 2.3 m.

    km = 1e3

    rectangular_source = gf.RectangularSource(
        lat=20., lon=44., depth=5*km,
        dip=30., strike=120., rake=50.,
        width=3*km, length=8*km, slip=2.3)

Ring fault
----------

A ring fault with vertical double couples. Ring faults can describe volcanic processes, e.g. caldera collapses.

.. code-block :: python
    :caption: Initialise a dipping ring fault.

    ring_fault = gf.RingFault(
        lat=31., lon=12., depth=2e3,
        diameter=5e3, sign=1.,
        dip=10., strike=30.,
        npointsources=50)


Source Time Functions
=====================

Source time functions describe the normalized moment rate of a source point as a function of time. A number of source time functions (STF) are available and can be applied in pre- or post-processing. If no specific STF is defined a unit pulse response is assumed.

+--------------------------------------------------+------------------------------------+
| STF                                              | Short description                  |
+==================================================+====================================+
| :class:`~pyrocko.gf.seismosizer.BoxcarSTF`       | Boxcar shape source time function. |
+--------------------------------------------------+------------------------------------+
| :class:`~pyrocko.gf.seismosizer.TriangularSTF`   | Triangular shape source time       |
|                                                  | function.                          |
+--------------------------------------------------+------------------------------------+
| :class:`~pyrocko.gf.seismosizer.HalfSinusoidSTF` | Half sinusoid type source time     |
|                                                  | function.                          |
+--------------------------------------------------+------------------------------------+
| :class:`~pyrocko.gf.seismosizer.ResonatorSTF`    | A simple resonator like source     |
|                                                  | time function.                     |
+--------------------------------------------------+------------------------------------+

Boxcar STF
----------

.. figure :: /static/stf-BoxcarSTF.svg
  :align: center
  :alt: boxcar source time function

A boxcar source time function. In the plot, each point is representative of the
STF's integral in the time interval :math:`[-\Delta t/2, +\Delta t/2]`
surrounding it (:math:`\Delta t` is the sampling interval).


.. code-block :: python
    :caption: Initialise an boxcar STF with duration of 5 s and centred at the centroid time.

    stf = gf.BoxcarSTF(5., center=0.)

Triangular STF
--------------

.. figure :: /static/stf-TriangularSTF.svg
  :align: center
  :alt: triangular source time function

A triangular shaped source time function. It can be made asymmetric.

.. code-block :: python
    :caption: Initialise a symmetric triangular STF with duration 5 s, which reaches its maximum amplitude after half the duration and centred at the centroid time.

    stf = gf.TriangularSTF(5., peak_ratio=0.5, center=0.)

Half sinusoid STF
-----------------

.. figure :: /static/stf-HalfSinusoidSTF.svg
  :align: center
  :alt: half-sinusouid source time function

A half-sinusoid source time function.

.. code-block :: python
    :caption: Initialise a half sinusoid type STF with a duration of 5 s and centred around the centroid time.

    stf = gf.HalfSinusoidSTF(5., center=0.)

Resonator STF
-------------

.. figure :: /static/stf-ResonatorSTF.svg
  :align: center
  :alt: smooth ramp source time function

.. code-block :: python
    :caption: Initialise a resonator STF with duration of 5 s and a resonance frequency of 1 Hz. 

    stf = gf.ResonatorSTF(5., frequency=1.0)

Modelling targets
=================

Pyrocko-GF :py:class:`Targets <pyrocko.gf.targets.Target>` are data structures
holding observer properties to tell the framework what we want to model, e.g.
whether we want to model a waveform or spectrum at a specific receiver site or
displacement values at a set of locations. Each target has properties
(location, depth, physical quantity) and essentially is associated to a GF
store, used for modelling. The target also defines the method used to
interpolate the discrete, gridded GF components. Please also see the
:doc:`Pyrocko GF modelling example <../library/examples/gf_forward>`.

.. note ::
    
    In Pyrocko locations are given with five coordinates: ``lat``, ``lon``, ``east_shift``, ``north_shift`` and ``depth``.

    Latitude and longitude are the origin of an optional local Cartesian coordinate system for which an ``east_shift`` and a ``north_shift`` [m] can be defined. A target has a depth below the surface. However, the surface can have topography and the target can also have an ``elevation``.


Waveforms
---------

Objects of the class :class:`~pyrocko.gf.targets.Target` are used to calculate
seismic waveforms. They define the geographical location (e.g. the station),
component orientation (e.g. vertical or radial), physical
quantity, and optionally a time interval

.. code:: python

    # Define a list of pyrocko.gf.Target objects, representing the recording
    # devices. In this case one three-component seismometer is represented with
    # three distinct target objects. The channel orientations are guessed from 
    # the channel codes here.
    waveform_targets = [
        gf.Target(
           quantity='displacement',
           lat=10., lon=10.,
           store_id='global_2s_25km',
           codes=('NET', 'STA', 'LOC', channel_code))
        for channel_code in ['E', 'N', 'Z']

See the :doc:`forward modelling example <../library/examples/gf_forward>` for
a complete Python script and further explanation.

Static surface displacements
----------------------------

Modelling of step-like surface displacements is configured with
:class:`~pyrocko.gf.targets.StaticTarget` objects. The resulting displacements
have no time dependence, but can hold many locations. Special forms derive from
the :class:`~pyrocko.gf.targets.StaticTarget` class:

* the :class:`~pyrocko.gf.targets.SatelliteTarget`, for the forward modelling of InSAR data, and
* the :class:`~pyrocko.gf.targets.GNSSCampaignTarget` for e.g. step-like GPS displacements.

.. code-block :: python
   :caption: Initialising a StaticTarget.

   # east and north are numpy.ndarrays in meters
   import numpy as num

   km = 1.0e3
   norths = num.linspace(-20*km, 20*km, 100)
   easts = num.linspace(-20*km, 20*km, 100)
   north_shifts, east_shifts = num.meshgrid(norths, easts)

   static_target = gf.StaticTarget(
       lats=43., lons=20.,
       north_shifts=north_shifts,
       east_shifts=east_shifts,
       interpolation='nearest_neighbor',
       store_id='ak135_static')

The :class:`~pyrocko.gf.targets.SatelliteTarget` defines the locations of displacement measurements and the direction of the measurement, which is the so-called line-of-sight of the radar. See the :doc:`forward modelling examples <../library/examples/gf_forward>` for detailed instructions of usage.

.. code-block :: python
   :caption: Initialising a SatelliteTarget.

   # east/north shifts as numpy.ndarrays in [m]
   # line-of-sight angles are NumPy arrays,
   # - phi is _towards_ the satellite clockwise from east in [rad]
   # - theta is the elevation angle from the horizon

   satellite_target = gf.SatelliteTarget(
       lats=43., lons=20.,
       north_shifts=north_shifts,
       east_shifts=east_shifts,
       interpolation='nearest_neighbor',
       phi=phi,
       theta=theta,
       store_id='ak135_static')

The :class:`~pyrocko.gf.targets.GNSSCampaignTarget` defines station locations
and the three components: east, north and up.

Forward modelling with Pyrocko-GF
=================================

Forward modelling, given a source and target description, is handled in the
so-called :class:`~pyrocko.gf.seismosizer.Engine` using the 
:meth:`~pyrocko.gf.seismosizer.LocalEngine.process` method.

Initialisation of the engine requires setting the folder, where it should look
for  GF stores. This can be configured globally by setting the
``store_superdirs`` entry in file :file:`~/.pyrocko/config.pf` or locally using
the initialization arguments of the
:py:class:`~pyrocko.gf.seismosizer.LocalEngine`.

Note, that modelling of dynamic targets (displacement waveforms) requires GFs
that have many samples in time and modelling of static targets (for step-like
displacements) usually only one. It is therefore meaningful to use dynamic GF
stores for dynamic targets and static stores for static targets.


Forward modelling dynamic waveforms
-----------------------------------

For waveform targets, Pyrocko :py:class:`~pyrocko.trace.Trace` objects
representing the resulting waveforms can be obtained from the engine's
response.

.. code-block :: python
    :caption: forward model wave forms of a DoubleCouple point.

    # Setup the LocalEngine and point it to the GF store you want to use.
    # `store_superdirs` is a list of directories where to look for GF Stores.
    engine = gf.LocalEngine(store_superdirs=['/data/gf_stores'])

    # The computation is performed by calling process on the engine
    response = engine.process(dc_source, waveform_targets)

    # convert results in response to Pyrocko traces
    synthetic_traces = response.pyrocko_traces()

    # visualise the response with the snuffler
    synthetic_traces.snuffle()


Forward modelling static surface displacements
----------------------------------------------

For static targets, the results are retrieved in the following way:

.. code-block :: python
    :caption: forward model static surface displacements of a rectangular fault

    # Get a default engine (will look into directories configured in 
    # ~/.pyrocko/config.pf to find GF stores)
    engine = gf.get_engine()

    response = engine.process(rectangular_source, satellite_target)

    # Retrieve a list of static results:
    synth_disp = response.static_results()


For regularly gridded satellite targets, the engine's response
can be converted to a synthetic `Kite
<https://pyrocko.org/kite/docs/current/>`_ scene:

.. code-block :: python
    :caption: forward modelling from an existing kite scene.

    from pyrocko import gf
    from kite import Scene

    km = 1e3
    engine = gf.LocalEngine(use_config=True)

    scene = Scene.load('sentinel_scene.npz')

    src_lat = 37.08194 + .045
    src_lon = 28.45194 + .2

    source = gf.RectangularSource(
        lat=src_lat,
        lon=src_lon,
        depth=2*km,
        length=4*km, width=2*km,
        strike=45., dip=60.,
        slip=.5, rake=0.,
        anchor='top')

    target = gf.KiteSceneTarget(scene, store_id='ak135_static')

    result = engine.process(source, target, nthreads=0)

    mod_scene = result.kite_scenes()[0]
    mod_scene.spool()

