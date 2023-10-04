Earthquake catalog
==================

Pyrocko provides access to some online earthquake catalogs via the
:mod:`pyrocko.client.catalog` module.


QuakeML import
--------------

This example shows how to read `QuakeML <https://quake.ethz.ch/quakeml/docs/REC?action=AttachFile&do=get&target=QuakeML-BED-20130214b.pdf>` event catalogs using :func:`~pyrocko.io.quakeml.QuakeML.load_xml`.
The function :meth:`~pyrocko.io.quakeml.QuakeML.get_pyrocko_events()` is used to obtain events in pyrocko format.
If a moment tensor is provided as [``Mrr, Mtt, Mpp, Mrt, Mrp, Mtp``], this is converted to [``mnn, mee, mdd, mne, mnd, med``]. The strike, dip and rake values appearing in the pyrocko event are calculated from the moment tensor.

.. literalinclude :: /../../examples/readnwrite_quakml.py
    :language: python


Creating QuakeML from scratch
-----------------------------

.. literalinclude :: /../../examples/make_quakeml.py
    :language: python


Searching the GlobalCMT catalog
--------------------------------

This example demonstrates how to query the `GlobalCMT
<http://www.globalcmt.org/>`_ [#f1]_ database for events which occurred in 2011
in northern Chile.

.. literalinclude :: /../../examples/catalog_search_globalcmt.py
    :language: python

Download :download:`catalog_search_globalcmt.py </../../examples/catalog_search_globalcmt.py>`


We expect to see the following output:

::

    Downloaded 53 events
    The last one is
    --- !pf.Event
    lat: -28.03
    lon: -71.55
    time: 2011-12-07 22:23:14.250000
    name: 201112072223A
    depth: 22800.0
    magnitude: 6.106838394015895
    region: NEAR COAST OF NORTHERN C
    catalog: gCMT
    moment_tensor: !pf.MomentTensor
      mnn: 1.16e+17
      mee: -1.24e+18
      mdd: 1.1200000000000001e+18
      mne: 1.29e+17
      mnd: 1.61e+17
      med: 1.0900000000000001e+18
      strike1: 16.540029329929244
      dip1: 24.774772153067424
      rake1: 109.14904335232158
      strike2: 175.61123518070136
      dip2: 66.6800337700307
      rake2: 81.39111828783355
      moment: 1.622772319211786e+18
      magnitude: 6.106838394015895
    duration: 5.4


Search for an event in GEOFON catalog
--------------------------------------------------

Search for an event name only in the `GEOFON <http://geofon.gfz-potsdam.de>`_
catalog [#f2]_ using :meth:`~pyrocko.client.geofon.Geofon`, with a given magnitude
range and timeframe.

.. literalinclude :: /../../examples/catalog_search_geofon.py
    :language: python

Download :download:`catalog_search_geofon.py </../../examples/catalog_search_geofon.py>`


We expect to see the following output (in YAML format):

::

    --- !pf.Event
    lat: 18.37
    lon: -72.55
    time: 2010-01-12 21:53:11
    name: gfz2010avtm
    depth: 17000.0
    magnitude: 7.2
    region: Haiti Region
    catalog: GEOFON


.. rubric:: Footnotes

.. [#f1] Dziewonski, A. M., T.-A. Chou and J. H. Woodhouse, Determination of earthquake source parameters from waveform data for studies of global and regional seismicity, J. Geophys. Res., 86, 2825-2852, 1981. doi:10.1029/JB086iB04p02825

.. [#f2] GEOFON Data Centre (1993): GEOFON Seismic Network. Deutsches GeoForschungsZentrum GFZ. Other/Seismic Network. doi:10.14470/TR560404. 
