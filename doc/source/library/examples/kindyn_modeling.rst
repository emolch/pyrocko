Kinematic/Dynamic source parameter modeling/inversion 
=====================================================

Calculate subfault dislocations from tractions with Okada half-space equation
-----------------------------------------------------------------------------

.. highlight:: python

In this example we create a :class:`~pyrocko.modelling.okada.OkadaSource` and compute the spatial quasi-static dislocation field caused by a traction field. The linear relation between traction and dislocation is calculated based on Okada (1992) [#f1]_.

Download :download:`okada_inversion_example.py </../../examples/okada_inversion_example.py>`

.. literalinclude :: /../../examples/okada_inversion_example.py
    :language: python

.. rubric:: Footnotes

.. [#f1] Okada, Y., Gravity and potential changes due to shear and tensile faults in a half-space. In: Journal of Geophysical Research 82.2, 1018–1040. doi:10.1029/92JB00178, 1992.
