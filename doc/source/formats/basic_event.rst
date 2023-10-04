
.. _basic-event-files:

Basic event files
-----------------

This simple text file format can be used to hold most basic earthquake catalog
information.

Example:

.. code-block:: none
    :caption: events.txt

    name = ev_1 (cluster 0)
    time = 2014-11-16 22:27:00.105
    latitude = 64.622
    longitude = -17.4295
    magnitude = 4.27346
    catalog = bardarbunga_reloc
    --------------------------------------------
    name = ev_2 (cluster 0)
    time = 2014-11-18 03:18:41.398
    latitude = 64.6203
    longitude = -17.4075
    depth = 5000
    magnitude = 4.34692
    moment = 3.7186e+15
    catalog = bardarbunga_reloc
    --------------------------------------------
    name = ev_3 (cluster 0)
    time = 2014-11-23 09:22:48.570
    latitude = 64.6091
    longitude = -17.3617
    magnitude = 4.9103
    moment = 2.60286e+16
    depth = 3000
    mnn = 2.52903e+16
    mee = 1.68639e+15
    mdd = -1.03187e+16
    mne = 9.8335e+15
    mnd = -7.63905e+15
    med = 1.9335e+16
    strike1 = 77.1265
    dip1 = 57.9522
    rake1 = -138.246
    strike2 = 321.781
    dip2 = 55.6358
    rake2 = -40.0024
    catalog = bardarbunga_mti
    --------------------------------------------

* depth must be given in [m]
* moment tensor entries must be given in [Nm], in north-east-down coordinate
  system

Use the library functions :py:func:`~pyrocko.model.event.load_events` and
:py:func:`~pyrocko.model.event.dump_events` to read and write basic event files.

.. note::

    The basic event file format is a relic from pre-YAML Pyrocko. Consider
    using YAML format to read/write event objects in newer applications.
