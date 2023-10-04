
YAML based file formats in Pyrocko
----------------------------------

The default IO format for many of Pyrocko's internal structures and its
configuration files is the `YAML <http://yaml.org/>`_ format. A generic
mechanism is provided to allow users to define arbitrary new types with YAML IO
support. These can nest or extend Pyrocko's predefined types. The functionality
for this is provided via the :py:mod:`pyrocko.guts` module, usage examples can
be found in section :doc:`/library/examples/guts`.

For example, here is how a :py:class:`~pyrocko.model.station.Station` object is
represented in YAML format:

.. code-block:: yaml
    :caption: station.yaml

    --- !pf.Station
    network: DK
    station: BSD
    location: ''
    lat: 55.1139
    lon: 14.9147
    elevation: 88.0
    depth: 0.0
    name: Bornholm Skovbrynet, Denmark
    channels:
    - !pf.Channel
      name: BHE
      azimuth: 90.0
      dip: 0.0
      gain: 1.0
    - !pf.Channel
      name: BHN
      azimuth: 0.0
      dip: 0.0
      gain: 1.0
    - !pf.Channel
      name: BHZ
      azimuth: 0.0
      dip: -90.0
      gain: 1.0

Though YAML or standard file formats can be used to hold station or event
information, for the sake of simplicity, two basic text file formats are
supported for stations and events. One other simple file format has been
defined to store markers from the :doc:`Snuffler </apps/snuffler/index>` application.
These file formats are briefly described in the following sections.
