Plotting functions
========================================

Generating topographic maps with ``automap``
--------------------------------------------

The :mod:`pyrocko.plot.automap` module provides a painless and clean interface
for the `Generic Mapping Tool (GMT) <http://gmt.soest.hawaii.edu/>`_ [#f1]_.

Classes covered in these examples:
 * :class:`pyrocko.plot.automap.Map`

For details on our approach in calling GMT from Python:
 * :doc:`gmtpy/index`

 .. note ::

    To retain PDF transparency in :mod:`~pyrocko.plot.gmtpy` use :meth:`save(psconvert=True) <pyrocko.plot.gmtpy.GMT.save>`.


Topographic map of Dead Sea basin
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This example demonstrates how to create a map of the Dead Sea area with largest
cities, topography and gives a hint on how to access genuine GMT methods.

Download :download:`automap_example.py </../../examples/automap_example.py>`

Station file used in the example: :download:`stations_deadsea.pf </static/stations_deadsea.pf>`

.. literalinclude :: /../../examples/automap_example.py
    :language: python

.. figure :: /static/automap_deadsea.jpg
    :align: center
    :alt: Map created using automap


Map with gridded data
^^^^^^^^^^^^^^^^^^^^^

This example demonstrates how to create a map using GMT methods and plotting spatial gridded data on it.

Download :download:`automap_example2.py </../../examples/automap_example2.py>`

.. literalinclude :: /../../examples/automap_example2.py
    :language: python

.. figure :: /static/automap_chile.png
    :align: center
    :alt: Map with interpolated gridded data created using automap

.. rubric:: Footnotes

.. [#f1] Wessel, P., W. H. F. Smith, R. Scharroo, J. F. Luis, and F. Wobbe, Generic Mapping Tools: Improved version released, EOS Trans. AGU, 94, 409-410, 2013.


Plotting beachballs (focal mechanisms)
--------------------------------------

Classes covered in these examples:
 * :class:`pyrocko.plot.beachball` (visual representation of a focal mechanism)
 * :mod:`pyrocko.moment_tensor` (a 3x3 matrix representation of an
   earthquake source)
 * :class:`pyrocko.gf.seismosizer.DCSource` (a representation of a double
   couple source object),
 * :class:`pyrocko.gf.seismosizer.RectangularExplosionSource` (a
   representation of a rectangular explostion source), 
 * :class:`pyrocko.gf.seismosizer.CLVDSource` (a representation of a
   compensated linear vector diploe source object)
 * :class:`pyrocko.gf.seismosizer.DoubleDCSource` (a representation of a
   double double-couple source object).


Beachballs from moment tensors
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Here we create random moment tensors and plot their beachballs.

Download :download:`beachball_example01.py </../../examples/beachball_example01.py>`

.. literalinclude :: /../../examples/beachball_example01.py
    :language: python

.. figure :: /static/beachball-example01.png
    :align: center
    :alt: Beachballs (focal mechanisms) created by moment tensors.

    An artistic display of focal mechanisms drawn by classes
    :class:`pyrocko.plot.beachball` and :mod:`pyrocko.moment_tensor`.


This example shows how to plot a full, a deviatoric and a double-couple beachball
for a moment tensor.

Download :download:`beachball_example03.py </../../examples/beachball_example03.py>`

.. literalinclude :: /../../examples/beachball_example03.py
    :language: python

.. figure :: /static/beachball-example03.png
    :align: center
    :alt: Beachballs (focal mechanisms) options created from moment tensor

    The three types of beachballs that can be plotted through pyrocko.


Beachballs from source objects
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This example shows how to add beachballs of various sizes to the corners of a
plot by obtaining the moment tensor from four different source object types:
:class:`pyrocko.gf.seismosizer.DCSource` (upper left),
:class:`pyrocko.gf.seismosizer.RectangularExplosionSource` (upper right), 
:class:`pyrocko.gf.seismosizer.CLVDSource` (lower left) and
:class:`pyrocko.gf.seismosizer.DoubleDCSource` (lower right).

Creating the beachball this ways allows for finer control over their location
based on their size (in display units) which allows for a round beachball even
if the axis are not 1:1.

Download :download:`beachball_example02.py </../../examples/beachball_example02.py>`

.. literalinclude :: /../../examples/beachball_example02.py
    :language: python


.. figure :: /static/beachball-example02.png
    :align: center
    :alt: Beachballs (focal mechanisms) created in corners of graph.

    Four different source object types plotted with different beachball sizes.


Fuzzy beachballs with uncertainty
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

If we want to express moment tensor uncertainties we can plot fuzzy beachballs from an ensemble of many solutions.

This example will generate random solution around a best moment tensor (red lines). The perturbed solutions are the uncertainty which can be illustrated in a fuzzy beachball.

Download :download:`beachball_example05.py </../../examples/beachball_example05.py>`

.. literalinclude :: /../../examples/beachball_example05.py
    :language: python


.. figure :: /static/beachball-example05.png
    :align: center
    :alt: Fuzzy beachball with uncertainty.

    Fuzzy beachball illustrating the solutions uncertainty.


Beachballs views for cross-sections:
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

It is useful to show beachballs from other view angles, as in cross-sections. For that, we can define a ``view`` for all beachball plotting functions as shown here:

Download :download:`beachball_example06.py </../../examples/beachball_example06.py>`

.. literalinclude :: /../../examples/beachball_example06.py
    :language: python



Add station symbols to focal sphere diagram
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This example shows how to add station symbols at the positions where P wave
rays pierce the focal sphere.

The function to plot focal spheres
(:func:`pyrocko.plot.beachball.plot_beachball_mpl`) uses the function
:func:`pyrocko.plot.beachball.project` in the final projection from 3D to 2D
coordinates. Here we use this function to place additional symbols on the plot.
The take-off angles needed can be computed with some help of the
:mod:`pyrocko.cake` module. Azimuth and distance computations are done with
functions from :mod:`pyrocko.orthodrome`.

Download :download:`beachball_example04.py </../../examples/beachball_example04.py>`

.. literalinclude :: /../../examples/beachball_example04.py
    :language: python

.. figure :: /static/beachball-example04.png
    :align: center
    :alt: Focal sphere diagram with station symbols

    Focal sphere diagram with markers at positions of P wave ray piercing points.


Hudson's source type plot
-------------------------

Hudson's source type plot [Hudson, 1989] is a way to visually represent the
widely used "standard" decomposition of a moment tensor into its isotropic,
its compensated linear vector dipole (CLVD), and its double-couple (DC)
components.

The function :py:func:`pyrocko.plot.hudson.project` may be used to get the
*(u,v)* coordinates for a given (full) moment tensor used for positioning the
symbol in the plot. The function :py:func:`pyrocko.plot.hudson.draw_axes` can
be used to conveniently draw the axes and annotions. Note, that we follow the
original convention introduced by Hudson, to place the negative CLVD on the
right hand side.

Download :download:`hudson_diagram.py </../../examples/hudson_diagram.py>`

.. literalinclude :: /../../examples/hudson_diagram.py
    :language: python

.. figure :: /static/hudson_diagram.png
    :align: center
    :alt: Hudson's source type plot for 200 random moment tensors.

    Hudson's source type plot for 200 random moment tensors.


Source radiation plot
---------------------

The directivity and radiation characteristics of any point or finite 
:py:class:`~pyrocko.gf.seismosizer.Source` model can be illustrated with
:py:func:`~pyrocko.plot.directivity.plot_directivity`.

Synthetic seismic traces (R, T or Z) are forward-modelled at a defined radius,
covering the full or partial azimuthal range and projected on a polar plot.
Difference in the amplitude are enhanced by hillshading the data.

Download :download:`plot_directivity.py </../../examples/plot_directivity.py>`

.. literalinclude :: /../../examples/plot_directivity.py
    :language: python


.. figure :: /static/directivity_rectangular.png
    :align: center
    :alt: Source radiation pattern of a RectangularSource

    Source radiation pattern at 300 km distance of the Mw 6.8 2020
    Elazig-Sevrice earthquake. The dominantly
    unilateral strike-slip rupture is reconstructed by a finite
    :py:mod:`~pyrocko.gf.seismosizer.RectangularSource` model.

.. figure :: /static/directivity_envelope_rectangular.png
    :align: center
    :alt: Source radiation pattern of a RectangularSource

    Here we see the envelope of the synthetic seismic traces,
    emphasizing the directivity effects of the source (``envelope=True``).
    Same source model: Mw 6.8 2020 Elazig-Sevrice earthquake.

