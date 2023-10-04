Downloading seismic data (FDSN)
================================

Waveforms and meta data can be retrieved from online `FDSN services <http://www.fdsn.org>`_ using the :py:mod:`pyrocko.client.fdsn` modules.


Seismic data from GEOFON
-------------------------

The following demo explains how to download waveform data and instrument
response information. Latter is used to deconvolve the transfer function from
the waveform traces in a second step.


 .. literalinclude :: /../../examples/fdsn_request_geofon.py
    :language: python

Download :download:`fdsn_request_geofon.py </../../examples/fdsn_request_geofon.py>`


StationXML data manipulation
----------------------------

To manipulate `StationXML <http://www.fdsn.org/xml/station/>`_ data through
Pyrocko use the :py:mod:`pyrocko.io.stationxml` module.  This example will
change the azimuth and dip values for channels whose codes are X, Y and Z, and
set all channel instrument's input units to meters.


 .. literalinclude :: /../../examples/fdsn_stationxml_modify.py
    :language: python

Download :download:`fdsn_stationxml_modify.py </../../examples/fdsn_stationxml_modify.py>`
