Forward modeling synthetic seismograms and displacements
========================================================

Calculate synthetic seismograms from a local GF store
-----------------------------------------------------

.. highlight:: python

It is assumed that a :class:`~pyrocko.gf.store.Store` with store ID *crust2_dd* has been downloaded in advance. A list of currently available stores can be found at https://greens-mill.pyrocko.org as well as how to download such stores.

Further API documentation for the utilized objects can be found at :class:`~pyrocko.gf.targets.Target`, :class:`~pyrocko.gf.seismosizer.LocalEngine` and :class:`~pyrocko.gf.seismosizer.DCSource`.

Download :download:`gf_forward_example1.py </../../examples/gf_forward_example1.py>`

.. literalinclude :: /../../examples/gf_forward_example1.py
    :language: python

.. figure :: /static/gf_synthetic.png
    :align: center
    :width: 90%
    :alt: Synthetic seismograms calculated through pyrocko.gf

    Synthetic seismograms calculated through :class:`pyrocko.gf` displayed in :doc:`/apps/snuffler/index`. The three traces show the east, north and vertical synthetical displacement stimulated by a double-couple source at 155 km distance.


Calculate spatial surface displacement from a local GF store
------------------------------------------------------------
Shear dislocation - Earthquake
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In this example we create a :class:`~pyrocko.gf.seismosizer.RectangularSource` and compute the spatial static displacement invoked by that rupture.

We will utilize :class:`~pyrocko.gf.seismosizer.LocalEngine`, :class:`~pyrocko.gf.targets.StaticTarget` and :class:`~pyrocko.gf.targets.SatelliteTarget`.

.. figure:: /static/gf_static_displacement.png
    :align: center
    :width: 90%
    :alt: Static displacement from a strike-slip fault calculated through Pyrocko

    Synthetic surface displacement from a vertical strike-slip fault, with a N104W azimuth, in the Line-of-sight (LOS), east, north and vertical directions. LOS as for Envisat satellite (Look Angle: 23., Heading:-76). Positive motion toward the satellite.

Download :download:`gf_forward_example2.py </../../examples/gf_forward_example2.py>`

.. literalinclude :: /../../examples/gf_forward_example2.py
    :language: python


Tensile dislocation - Sill/Dike
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

In this example we create a :class:`~pyrocko.gf.seismosizer.RectangularSource` and compute the spatial static displacement invoked by a
magmatic contracting sill. The same model can be used to model a magmatic dike intrusion (changing the "dip" argument).

We will utilize :class:`~pyrocko.gf.seismosizer.LocalEngine`, :class:`~pyrocko.gf.targets.StaticTarget` and :class:`~pyrocko.gf.targets.SatelliteTarget`.

.. figure:: /static/gf_static_displacement_sill.png
    :align: center
    :width: 90%
    :alt: Static displacement from a contracting sill calculated through pyrocko

    Synthetic surface displacement from a contracting sill. The sill has a strike of 104° N. The surface displacements are shown in Line-of-sight (LOS), east, north and vertical directions. Envisat satellite has a look angle of 23° and heading -76°. The motion is positive towards the satellite LOS.

Download :download:`gf_forward_example2_sill.py </../../examples/gf_forward_example2_sill.py>`

.. literalinclude :: /../../examples/gf_forward_example2_sill.py
    :language: python


Calculate spatial surface displacement using subfault dislocations
------------------------------------------------------------------

In this example we create a :class:`~pyrocko.modelling.OkadaSource` and compute the spatial static displacement at the surface invoked by that rupture [#f1]_.

Download :download:`okada_forward_example.py </../../examples/okada_forward_example.py>`

.. literalinclude :: /../../examples/okada_forward_example.py
    :language: python

.. rubric:: Footnotes

.. [#f1] Okada, Y., Gravity and potential changes due to shear and tensile faults in a half-space. In: Journal of Geophysical Research 82.2, 1018–1040. doi:10.1029/92JB00178, 1992.
>>>>>>> 89252887... add okada modelling and pseudo-dynamic rupture model (chapter 1)


Calculate spatial surface displacement and export Kite scenes
-------------------------------------------------------------

We derive InSAR surface deformation targets from `Kite <https://pyrocko.org/docs/kite>`_ scenes. This way we can easily inspect the data and use Kite's quadtree data sub-sampling and data error variance-covariance estimation calculation.

Download :download:`gf_forward_example2_kite.py </../../examples/gf_forward_example2_kite.py>`

.. literalinclude :: /../../examples/gf_forward_example2_kite.py
    :language: python


Calculate forward model of thrust faulting and display wrapped phase
--------------------------------------------------------------------

In this example we compare the synthetic unwappred and wrapped LOS displacements caused by a thrust rupture.

.. figure:: /static/gf_static_wrapper.png
    :align: center
    :width: 90%
    :alt: Static displacement from a thrust fault calculated through Pyrocko

    Synthetic LOS displacements from a south-dipping thrust fault. LOS as for Sentinel-1 satellite (Look Angle: 36., Heading:-76). Positive motion toward the satellite. Left: unwrapped phase. Right: Wrapped phase.


Download :download:`gf_forward_example3.py </../../examples/gf_forward_example3.py>`

.. literalinclude :: /../../examples/gf_forward_example3.py
    :language: python


Combining dislocation sources 
-----------------------------

In this example we combine two rectangular sources and plot the forward model in profile.

.. figure:: /static/gf_static_several.png
    :align: center
    :width: 90%

    Synthetic LOS displacements from a flower-structure made of one strike-slip fault and one thrust fault. LOS as for Sentinel-1 satellite (Look Angle: 36°, Heading: -76°). Positive motion toward the satellite.

Download :download:`gf_forward_example4.py </../../examples/gf_forward_example4.py>`

.. literalinclude :: /../../examples/gf_forward_example4.py
    :language: python


Modelling viscoelastic static displacement
------------------------------------------

In this advanced example we leverage the viscoelastic forward modelling capabilities of the `psgrn_pscmp` backend.

.. raw:: html

    <video style="width: 80%; margin: auto" controls>
        <source src="https://pyrocko.org/media/gf-viscoelastic-response.mp4" type="video/mp4">
        Your browser does not support the video tag.
    </video>

Viscoelastic static GF store forward-modeling the transient effects of a deep dislocation source, mimicking a transform plate boundary. Together with a shallow seismic source. The cross denotes the tracked pixel location. (Top) Displacement of the tracked pixel in time.

The static store has to be setup with Burger material describing the viscoelastic properties of the medium, see this ``config`` for the fomosto store:

.. note ::

    Static stores define the sampling rate in Hz.
    ``sampling_rate: 1.157e-06 Hz`` is a sampling rate of 10 days!

.. code-block:: yaml

    --- !pf.ConfigTypeA
    id: static_t
    modelling_code_id: psgrn_pscmp.2008a
    regions: []
    references: []
    earthmodel_1d: |2
          0.             2.5            1.2            2.1           50.            50.
          1.             2.5            1.2            2.1           50.            50.
          1.             6.2            3.6            2.8          600.           400.
         17.             6.2            3.6            2.8          600.           400.
         17.             6.6            3.7            2.9         1432.           600.
         32.             6.6            3.7            2.9         1432.           600.
         32.             7.3            4.             3.1         1499.           600.            1e30            1e20           1.
         41.             7.3            4.             3.1         1499.           600.            1e30            1e20           1.
      mantle
         41.             8.2            4.7            3.4         1370.           600.            1e19            5e17           1.
         91.             8.2            4.7            3.4         1370.           600.            1e19            5e17           1.
    sample_rate: 1.1574074074074074e-06
    component_scheme: elastic10
    tabulated_phases: []
    ncomponents: 10
    receiver_depth: 0.0
    source_depth_min: 0.0
    source_depth_max: 40000.0
    source_depth_delta: 500.0
    distance_min: 0.0
    distance_max: 150000.0
    distance_delta: 1000.0


In the ``extra/psgrn_pscmp`` configruation file we have to define the timespan from `tmin_days` to `tmax_days`, covered by the `sampling_rate` (see above)

.. code-block:: yaml

    --- !pf.PsGrnPsCmpConfig
    tmin_days: 0.0
    tmax_days: 600.0
    gf_outdir: psgrn_functions
    psgrn_config: !pf.PsGrnConfig
      version: 2008a
      sampling_interval: 1.0
      gf_depth_spacing: -1.0
      gf_distance_spacing: -1.0
      observation_depth: 0.0
    pscmp_config: !pf.PsCmpConfig
      version: 2008a
      observation: !pf.PsCmpScatter {}
      rectangular_fault_size_factor: 1.0
      rectangular_source_patches: []


Download :download:`gf_forward_viscoelastic.py </../../examples/gf_forward_viscoelastic.py>`

.. literalinclude :: /../../examples/gf_forward_viscoelastic.py
    :language: python

Creating a custom Source Time Function (STF)
--------------------------------------------

Basic example how to create a custom STF class, creating a linearly decreasing ramp excitation.

Download :download:`gf_custom_stf.py </../../examples/gf_custom_stf.py>`

.. literalinclude :: /../../examples/gf_custom_stf.py
    :language: python
