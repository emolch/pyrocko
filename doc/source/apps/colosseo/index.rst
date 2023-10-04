Colosseo - *earthquake scenario generator*
==========================================

.. highlight:: sh

Use :mod:`pyrocko.gf` Green's Function databases to generate earthquake data from picture-book scenarios.

``colosseo`` is a CLI for :mod:`pyrocko.scenario` that orchestrates
different generators to randomly (yet seeded) create synthetic data of
randomised sources, as well as constrained sources and fixed network
geometries. Point sources or finite sources are generated with the
:class:`~pyrocko.scenario.sources.base.SourceGenerator`.

Stations are created by the
:class:`~pyrocko.scenario.station.StationGenerator`, dynamic or static
synthetic data use the
:class:`~pyrocko.scenario.targets.waveform.WaveformGenerator` and the
:class:`~pyrocko.scenario.targets.gnss_campaign.GNSSCampaignGenerator`. Also
InSAR data scenarios using `kite <https://pyrocko.org/docs/kite/>`_ are
possible with the :class:`~pyrocko.scenario.targets.insar.InSARGenerator`.
Network geometries can be import by
:class:`~pyrocko.scenario.station.ImportStationGenerator`.

Creating a scenario with ``colosseo`` is straight forward, but in any case you get help with subcommands using:

.. code-block :: sh

    $ colosseo --help

    Usage: colosseo <subcommand> [options] [--] <arguments> ...

    Subcommands:

        init      initialize a new, blank scenario
        fill      fill the scenario with modelled data
        snuffle   open Snuffler to inspect the waveform data
        map       map the scenario arena

    To get further help and a list of available options for any subcommand run:

        colosseo <subcommand> --help


Initialize a new scenario
--------------------------

Create a new scenario in a folder :file:`my_scenario`:

.. code-block :: sh

    colosseo init my_scenario


What you need is a **pre-calculated Green's function store**, for more information see :doc:`../fomosto/index`.
The database to utilize for forward modelling is defined in variable ``store_id`` at the respective :class:`~pyrocko.scenario.targets.base.TargetGenerator`.

The you can either copy the database into folder :file:`gf_stores` or have them in your ``gf_store_superdirs`` config variable (see :file:`~/.pyrocko/config.pf`).

The scenario is built from a YAML configuration file, which can look like this:

.. code-block:: yaml
    :caption: Example scenario configuration file

    --- !pf.scenario.ScenarioGenerator
    avoid_water: true
    center_lat: 52
    center_lon: 5.4
    radius: 90000.0
    ntries: 500
    target_generators:
    - !pf.scenario.RandomStationGenerator
      avoid_water: true
      ntries: 500
      nstations: 8
    - !pf.scenario.WaveformGenerator
      avoid_water: true
      ntries: 500
      station_generator: !pf.scenario.RandomStationGenerator
        avoid_water: true
        ntries: 500
        nstations: 10
      noise_generator: !pf.scenario.WhiteNoiseGenerator
        scale: 1.0e-06
      store_id: crust2_m5_hardtop_8Hz_fine
      seismogram_quantity: displacement
      vmin_cut: 2000.0
      vmax_cut: 8000.0
      fmin: 0.01
    - !pf.scenario.InSARGenerator
      avoid_water: true
      ntries: 500
      store_id: ak135_static
      inclination: 98.2
      apogee: 693000.0
      swath_width: 20000.0
      track_length: 15000.0
      incident_angle: 29.1
      resolution: [250, 250]
      mask_water: true
      noise_generator: !pf.scenario.AtmosphericNoiseGenerator
        amplitude: 1.0
    - !pf.scenario.GNSSCampaignGenerator
      avoid_water: true
      ntries: 500
      station_generator: !pf.scenario.RandomStationGenerator
        avoid_water: true
        ntries: 500
        nstations: 10
      noise_generator: !pf.scenario.GPSNoiseGenerator
        measurement_duarion_days: 2.0
      store_id: ak135_static
    source_generator: !pf.scenario.DCSourceGenerator
      ntries: 500
      avoid_water: false
      nevents: 2
      radius: 1000
      time_min: 2017-01-01 00:00:00
      time_max: 2017-01-03 00:00:00
      magnitude_min: 4.0
      magnitude_max: 7.0
      depth_min: 5000.0
      depth_max: 10000.0



Start the forward model
-----------------------

Start filling the scenario with forward modelled data:

.. code-block:: sh

    colosseo fill my_scenario


Seismic source models
---------------------


Double-couple source
********************

See also :class:`~pyrocko.gf.seismosizer.DCSource`.

.. code-block :: yaml

  --- !pf.scenario.DCSourceGenerator
  # How often the are we rolling the dice for this model
  ntries: 10
  # Number of DCSources to generate
  nevents: 2
  avoid_water: false
  time_min: 2017-01-01 00:00:00
  time_max: 2017-01-03 00:00:00
  magnitude_min: 4.0
  magnitude_max: 6.0
  depth_min: 0.0
  depth_max: 30000.0
  # b-value for Gutenberg-Richter magnitude distribution.
  b_value: 1.

Rectangular fault plane
***********************

See also :class:`~pyrocko.gf.seismosizer.RectangularSource`.

.. code-block :: yaml

  --- !pf.scenario.RectangularSourceGenerator
  # How often the are we rolling the dice for this model
  ntries: 10
  # Number of events to generate
  nevents: 2
  avoid_water: false
  time_min: 2017-01-01 00:00:00
  time_max: 2017-01-03 00:00:00
  magnitude_min: 4.0
  depth_min: 0.0
  depth_max: 5000.0
  # Dimensions of the fault, if not given random dimensions after Mai and Berozza (2000)
  # are assumed
  length: 4000.
  width: 2000.
  # Orientation of the plane, optional
  strike: 90.
  dip: 34.
  rake: 150.
  # Decimation of sub-sources
  decimation_factor: 4

Pseudo dynamic rupture
**********************

See also :class:`~pyrocko.gf.seismosizer.PseudoDynamicRupture`.

.. code-block :: yaml

  --- !pf.scenario.PseudoDynamicRuptureGenerator
  # How often the are we rolling the dice for this model
  ntries: 10
  # Number of events to generate
  nevents: 2
  avoid_water: false
  time_min: 2017-01-01 00:00:00
  time_max: 2017-01-03 00:00:00
  magnitude_min: 4.0
  depth_min: 0.0
  depth_max: 5000.0
  decimation_factor: 4
  # Dimensions of the fault, if not given random dimensions after Mai and Berozza (2000)
  # are assumed
  length: 4000.
  width: 2000.
  # Orientation of the plane, optional
  strike: 90.
  dip: 34.
  rake: 150.
  # Decimation of sub-sources
  decimation_factor: 4


The final scenario
-------------------

The directory structure is divided into subfolders holding the forward-modelled data as well as individual folders and files for plots and meta data of stations and events (e.g. StationXML responses).

.. code-block :: text
    :caption: Colosseo directory structure

    my_scenario/         # this directory hosts the scenario
    |-- scenario.yml     # general settings
    |-- waveforms/       # generated waveforms
    |-- insar/           # Kite InSAR scenes
    |-- gf_stores/       # Your GF stores live here
    |-- map.pdf          # GMT map of the scenario


Along with the output of synthetic data the scenario's map is plotted

.. figure :: /static/scenario_map.png
  :scale: 80%
  :align: center
  :alt: Synthetic scenario map

  Example of an earthquake scenario located in the Netherland's part of the Lower Rhine Plain.
