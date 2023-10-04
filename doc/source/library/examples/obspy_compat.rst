ObsPy compatibility
===================

Pyrocko and `ObsPy <https://obspy.org>`_ use different internal representations
of waveforms, seismic events, and station metadata. To translate between the
different representations, several converter functions are available in the
compatibility module :py:mod:`pyrocko.obspy_compat`. For further convenience,
it can add these converters as Python methods to the respective waveform,
event, and station objects (:py:func:`pyrocko.obspy_compat.base.plant`, see for
list of installed methods).

.. code-block:: python

    import obspy
    from pyrocko import obspy_compat
    obspy_compat.plant()


Using the Snuffler on ``obspy.Stream``
--------------------------------------

This is how you use :py:meth:`~pyrocko.trace.Trace.snuffle` on an
:py:class:`obspy.Stream  <obspy.core.stream.Stream>`.

 .. literalinclude :: /../../examples/obspy_compat_snuffle.py
    :language: python

Download :download:`obspy_compat_snuffle.py </../../examples/obspy_compat_snuffle.py>`
