Seismic traces
==============

Pyrocko can be used to handle and process seismic waveform data. The following
examples describe usage of the :mod:`pyrocko.io` module to read and write
seismological waveform data and the :mod:`pyrocko.trace` module which offers
basic signal processing functionality.

Supported seismological waveform formats are:

============ =========================== ========= ======== ======
format       format identifier           load      save     note
============ =========================== ========= ======== ======
MiniSEED     mseed                       yes       yes
SAC          sac                         yes       yes      [#f1]_
SEG Y rev1   segy                        some
SEISAN       seisan, seisan.l, seisan.b  yes                [#f2]_
KAN          kan                         yes                [#f3]_
YAFF         yaff                        yes       yes      [#f4]_
ASCII Table  text                                  yes      [#f5]_
GSE1         gse1                        some
GSE2         gse2                        yes       yes
DATACUBE     datacube                    yes
SUDS         suds                        some
============ =========================== ========= ======== ======

.. rubric:: Notes

.. [#f1] For SAC files, the endianness is guessed. Additional header
    information is stored in the :class:`~pyrocko.trace.Trace`'s ``meta`` attribute.
.. [#f2] Seisan waveform files can be in little (``seisan.l``) or big endian
    (``seisan.b``) format. ``seisan`` currently is an alias for ``seisan.l``.
.. [#f3] The KAN file format has only been seen once by the author, and support
    for it may be removed again.
.. [#f4] YAFF is an in-house, experimental file format, which should not be
    released into the wild.
.. [#f5] ASCII tables with two columns (time and amplitude) are output - meta
    information will be lost.

Load, filter and save
---------------------

Read a test file :download:`test.mseed </static/test.mseed>` with
:func:`pyrocko.io.load`, containing a three component seismogram, apply
Butterworth lowpass filter to the seismograms and dump the results to a new
file with :meth:`pyrocko.io.save`.

::

    from pyrocko import io

    traces = io.load('test.mseed')

    for tr in traces:
        tr.lowpass(4, 0.02)   # 4th order, 0.02 Hz

    io.save(traces, 'filtered.mseed')

Other filtering methods are :meth:`pyrocko.trace.Trace.highpass` and
:meth:`pyrocko.trace.Trace.bandpass`.

If more than a single file should be read, it is much more convenient to use
Pyrocko's :mod:`pyrocko.pile` module instead of :func:`pyrocko.io.load`. See
section :doc:`/library/examples/dataset_management` for examples on how to use
it.

Visual inspection of traces
---------------------------

To visualize a single :class:`~pyrocko.trace.Trace` object, use its
:meth:`~pyrocko.trace.Trace.snuffle` method. To look at a list of traces, use
the :func:`pyrocko.trace.snuffle` function. If you want to see the contents of
a pile, the :meth:`pyrocko.pile.Pile.snuffle` method is your friend.
Alternatively, you could of course save the traces to file and use the
standalone :doc:`/apps/snuffler/index` to look at them.

::

    from pyrocko import io, trace, pile

    traces = io.load('test.mseed')
    traces[0].snuffle() # look at a single trace
    trace.snuffle(traces) # look at a bunch of traces

    # do something with the traces:
    new_traces = []
    for tr in traces:
        new = tr.copy()
        new.whiten()
        # to allow the viewer to distinguish the traces
        new.set_location('whitened')
        new_traces.append(new)

    trace.snuffle(traces + new_traces)

    # it is also possible to 'snuffle' a pile:
    p = pile.make_pile(['test.mseed'])
    p.snuffle()

If needed, station meta-information, event information, and marker objects can
be passed into any of the ``snuffle()`` methods and  functions using keyword
arguments.


Creating a trace object from scratch
------------------------------------

Creates two :class:`~pyrocko.trace.Trace` objects, fills them with noise (using
:func:`numpy.random.random`) and saves them with :func:`~pyrocko.io.save` to a
single or to split files. For each :class:`~pyrocko.trace.Trace` object the
station name is defined, the channel name, the sampling interval (0.5 s) and
the time onset (``tmin``).

Download :download:`trace_scratch.py </../../examples/trace_scratch.py>`

.. literalinclude :: /../../examples/trace_scratch.py
    :language: python

Extracting part of a trace (trimming)
-------------------------------------

Trimming is achieved with the :meth:`~pyrocko.trace.Trace.chop` method. Here we
cut 10 s from the beginning and the end of the example trace
(:download:`test.mseed </static/test.mseed>`).

Download :download:`trace_extract.py </../../examples/trace_extract.py>`

.. literalinclude :: /../../examples/trace_extract.py
    :language: python

Time shifting a trace
---------------------

This example demonstrates how to time shift a trace by a given relative time or
to a given absolute onset time with :meth:`pyrocko.trace.Trace.shift`.

::

    from pyrocko import io, util

    traces = io.load('test.mseed')
    tr = traces[0]

    # shift by 10 seconds backward in time
    tr.shift(-10.0)
    print(tr)

    # shift to a new absolute onset time
    tmin_new = util.str_to_time('2009-04-06 01:32:42.000')
    tr.shift(tmin_new - tr.tmin)
    print(tr)


Resampling a trace
------------------

Example for downsampling a trace in a file to a sampling rate with
:meth:`pyrocko.trace.Trace.downsample_to`.

::

    from pyrocko import io, trace

    tr1 = io.load('test.mseed')[0]

    tr2 = tr1.copy()
    tr2.downsample_to(2.0)

    # make them distinguishable
    tr1.set_location('1')
    tr2.set_location('2')

    # visualize with Snuffler
    trace.snuffle([tr1, tr2])



To overlay the traces in Snuffler, right-click the mouse button and

* check '*Subsort ... (Grouped by Location)*'
* uncheck '*Show Boxes*'
* check '*Common Scale*'


Convert SAC to MiniSEED
-----------------------

A very basic SAC to MiniSEED converter:

Download :download:`convert_sac_mseed </../../examples/convert_sac_mseed>`

.. literalinclude :: /../../examples/convert_sac_mseed
    :language: python


Convert MiniSEED to ASCII
-------------------------

An inefficient, non-portable, non-header-preserving, but simple, method to
convert some MiniSEED traces to ASCII tables:

.. literalinclude :: /../../examples/convert_mseed_ascii.py
    :language: python

Download :download:`convert_mseed_ascii.py </../../examples/convert_mseed_ascii.py>`


Finding the comparative misfits of mulitple traces
--------------------------------------------------

Three traces will be created, where one will be the used as a reference trace
(``rt``).  Using :meth:`pyrocko.trace.Trace.misfit`, we can find the misfits
of the other two traces (``tt1`` and ``tt2``) in comparision to ``rt``.
Traces ``rt`` and ``tt1`` will have the same y-data, so the misfit between
them will be zero.


Download :download:`trace_misfit.py </../../examples/trace_misfit.py>`

.. literalinclude :: /../../examples/trace_misfit.py
    :language: python

If we wanted to reload our misfit setup, :mod:`pyrocko.guts` provides the
``iload_all()`` method for that purpose:

::

    from pyrocko.guts import load
    from pyrocko.trace import MisfitSetup

    setup = load(filename='my_misfit_setup.txt')

    # now we can change, for example, the domain:
    setup.domain = 'frequency_domain'

    print(setup)


Restitute to displacement using poles and zeros
-----------------------------------------------

Often we want to deconvolve instrument responses from seismograms. The method
:meth:`pyrocko.trace.Trace.transfer` implements a convolution with a transfer
function in the frequency domain. This method takes as argument a transfer
function object which 'knows' how to compute values of the transfer function at
given frequencies. The trace module provides a few different transfer
functions, but it is also possible to write a custom transfer function. For a
transfer function given as poles and zeros, we can use instances of the class
:class:`pyrocko.response.PoleZeroResponse`. There is also a class
:class:`pyrocko.response.InverseEvalresp`, which uses the common ``RESP``
files through the ``evalresp`` library.

Here is a complete example using a SAC pole-zero file
(:download:`STS2-Generic.polezero.txt </static/STS2-Generic.polezero.txt>`) to
deconvolve the transfer function from an example seismogram:

Download :download:`trace_restitution_pz.py </../../examples/trace_restitution_pz.py>`

.. literalinclude :: /../../examples/trace_restitution_pz.py
    :language: python


Restitute to displacement using SEED RESP response
-------------------------------------------------------

In this examples we 

Download :download:`trace_restitution_resp.py </../../examples/trace_restitution_resp.py>`

.. literalinclude :: /../../examples/trace_restitution_resp.py
    :language: python
