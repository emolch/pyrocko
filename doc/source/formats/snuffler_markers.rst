
.. _marker-files:

Marker files
------------

The marker file format is used to store markers and pick information from
:doc:`/apps/snuffler/index` in a simple way.

Example:

.. code-block:: none
    :caption: example.markers

    # Snuffler Markers File Version 0.2
    event: 2015-04-16 06:38:08.8350  0 4342fb5oj726   51.4177088165 12.1322880252  29344.72658 3.22029 None  gfz2015hkiy None
    event: 2017-04-29 00:56:23.3900  0 sbqqrmbj03ce   51.3385103357 12.2131631055  27253.08273 2.88913 None  gfz2017ihrf None
    phase: 2015-04-16 06:38:16.2762  0 SX.NEUB..BHZ    4342fb5oj726   2015-04-16   06:38:08.8350 P        None False
    phase: 2015-04-16 06:38:21.3077  0 SX.NEUB..BHN    4342fb5oj726   2015-04-16   06:38:08.8350 S        None False
    phase: 2015-04-16 06:38:17.6081  0 SX.WIMM..BHZ    4342fb5oj726   2015-04-16   06:38:08.8350 P        None False
    phase: 2015-04-16 06:38:27.2764 2015-04-16 06:38:28.2630 0.986566066742  0 TH.ABG1..BHZ    4342fb5oj726   2015-04-16   06:38:08.8350 S        None False
    2015-04-16 06:38:13.9964  0 TH.CHRS..BHE
    2015-04-16 06:38:15.0121 2015-04-16 06:38:19.1703 4.1582171917  0 TH.GRZ1..BHE
    2015-04-16 06:38:11.9014 2015-04-16 06:38:34.4383 22.5369031429  0 None
    phase: 2017-04-29 00:56:32.9685  0 SX.WIMM..BHZ    sbqqrmbj03ce   2017-04-29   00:56:23.3900 P        None False

Each line in the marker file represents a visual marker. There are three kinds
of markers: event markers, phase markers, and basic markers.

* basic and phase markers can be associated with a certain NET.STA.LOC.CHA name
* basic and phase markers can either match a time instant or a time span
* phase markers can be associated to an event marker

The rules how to parse these files are somewhat cumbersome. Use the library
functions :py:func:`~pyrocko.gui.snuffler.marker.load_markers`
and :py:func:`~pyrocko.gui.snuffler.marker.save_markers`. The marker file
format is subject to be replaced by a YAML based variant.
