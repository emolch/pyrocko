Geographical datasets
======================

Pyrocko offers access to commonly used geographical datasets, such as 

Topography
----------

The :py:mod:`pyrocko.dataset.topo` subpackage offers quick access to some
popular global topography datasets.

The following example draws gridded topography for Mount Vesuvius from SRTMGL3
([#ft1]_, [#ft2]_, [#ft3]_, [#ft4]_) in local cartesian coordinates.

.. literalinclude :: /../../examples/topo_example.py
   :caption: :download:`topo_example.py </../../examples/topo_example.py>`
   :language: python

.. figure:: /static/topo_example.png
    :align: center

.. rubric:: Footnotes

.. [#ft1] Farr, T. G., and M. Kobrick, 2000, Shuttle Radar Topography Mission
    produces a wealth of data. Eos Trans. AGU, 81:583-585.

.. [#ft2] Farr, T. G. et al., 2007, The Shuttle Radar Topography Mission, Rev.
    Geophys., 45, RG2004, doi:10.1029/2005RG000183. (Also available online at
    http://www2.jpl.nasa.gov/srtm/SRTM_paper.pdf)

.. [#ft3] Kobrick, M., 2006, On the toes of giants-How SRTM was born, Photogramm. Eng.
    Remote Sens., 72:206-210.

.. [#ft4] Rosen, P. A. et al., 2000, Synthetic aperture radar interferometry, Proc. IEEE,
    88:333-382.

GSHHG coastal database
----------------------
The `GSHHG database <https://www.ngdc.noaa.gov/mgg/shorelines/gshhs.html>`_ is a high-resolution geography data set. We implement functions to extract coordinates of landmasks.

Classes covered in this example:
 * :py:class:`pyrocko.dataset.gshhg.GSHHG`

 .. literalinclude :: /../../examples/gshhg_example.py
    :language: python

Download :download:`gshhg_example.py </../../examples/gshhg_example.py>`

.. rubric:: Footnotes

.. [#f1] Wessel, P., and W. H. F. Smith, A Global Self-consistent, Hierarchical, High-resolution Shoreline Database, J. Geophys. Res., 101, #B4, pp. 8741-8743, 1996.


Tectonic plates and boundaries (PB2003)
---------------------------------------

*An updated digital model of plate boundaries* [#f2]_ offers a global set of present plate boundaries on the Earth. This database used in :mod:`pyrocko.plot.automap`.

Classes covered in this example:
 * :py:class:`pyrocko.dataset.tectonics.PeterBird2003`

 .. literalinclude :: /../../examples/tectonics_example.py
    :language: python

Download :download:`tectonics_example.py </../../examples/tectonics_example.py>`

.. rubric:: Footnotes

.. [#f2] Bird, Peter. "An updated digital model of plate boundaries." Geochemistry, Geophysics, Geosystems 4.3 (2003).


Global strain rate (GSRM1)
--------------------------

Access to the global strain rate data set from Kreemer et al. (2003) [#f3]_.

Classes to be covered in this example:
 * :py:class:`pyrocko.dataset.tectonics.GSRM1`

.. warning :: To be documented by example!

.. rubric:: Footnotes

.. [#f3] Kreemer, C., W.E. Holt, and A.J. Haines, "An integrated global model of present-day plate motions and plate boundary deformation", Geophys. J. Int., 154, 8-34, 2003.
