##########################################################################
Pseudo Dynamic Rupture - *A stress-based self-similar finite source model*
##########################################################################

************
Introduction
************

Physics-based, dynamic rupture models, which rely on few parameters only, are needed for realistic forward modelling and to reduce the effort and non-uniqueness of the inversion. The :py:class:`~pyrocko.gf.seismosizer.PseudoDynamicRupture` is a simplified, quasi-dynamic, semi-analytical rupture model suited for wavefield and static displacement simulation and earthquake source inversion. The rupture model builds on the class of self-similar crack models. On one hand it is approximative as it neglects inertia and so far the details of frictional effects and treats the rupture front growth in a simplified way.  On the other hand, it is complete as the slip fulfils the boundary condition on the broken plane for every instantaneous rupture front geometry and applied stress.

Additional resources
====================

* `The pseudo dynamic rupture model <https://data.pyrocko.org/presentations/pdr_intro/>`_ (introduction and practical examples)

Theoretical foundation
======================

.. note ::
    
    Dahm, T., Heimann, S., Metz, M., Isken, M. P. (2021). A self-similar dynamic rupture model based on the simplified wave-rupture analogy. Geophysical Journal International. Volume 225, Issue 3, June 2021, Pages 1586–1604, https://doi.org/10.1093/gji/ggab045

.. contents :: Content
  :depth: 4

*****************************
Source implementation details
*****************************


The implementation of the pseudo dynamic rupture model into the Pyrocko and Pyrocko-GF framework is based on [Dahm2021]_. Essential building blocks are the class :py:class:`~pyrocko.gf.seismosizer.PseudoDynamicRupture` and in the :py:class:`~pyrocko.gf.tractions.AbstractTractionField` subclasses. Additionally the model is constrained by the subsurface underground model as provided by the metadata in the Pyrocko GF :py:class:`~pyrocko.gf.store.Store`. See [Dahm2021_] which describes the rupture source model in detail.

.. figure :: /static/pseudo-dynamic-flow-2.svg
    :align: center
    :width: 95%
    :alt: Flowchart calculation of the pseudo dynamic rupture.

    Flowchart illustrating the building blocks and architecture of the :py:class:`~pyrocko.gf.seismosizer.PseudoDynamicRupture` in Pyrocko-GF.

******************************************
Forward modelling a pseudo dynamic rupture
******************************************

The :py:class:`~pyrocko.gf.seismosizer.PseudoDynamicRupture` model is fully integrated into Pyrocko-GF. The model can be used to forward model synthetic waveforms, surface displacements and any quantity that is delivered by the store. Various utility functions are available to analyse and visualize parameters of the rupture model.

In this section we will show the parametrisation, introspection and resulting seismological forward calculations using the :py:class:`~pyrocko.gf.seismosizer.PseudoDynamicRupture`.


Forward calculation of waveforms and static displacement
========================================================

Parametrisation of the source model is straight forward, as for any other Pyrocko-GF source. In the below code example we parametrize a shallow bidirectional strike-slip source.

More details on dynamic and static Green's function databases and other source models are laid out in section :doc:`pyrocko-gf`.


Simple pseudo dynamic rupture forward model
-------------------------------------------
We create a simple forward model and calculate waveforms for one seismic station (:py:class:`~pyrocko.gf.targets.Target`) at about 14 km distance - The tractions will be aligned to force the defined slip rake angle. The modeled waveform is displayed in the :doc:`Snuffler <../apps/snuffler/index>` application.

**Important:** the spatial sampling of the GF store used in the example must be dense enough to prevent aliasing artifacts.

Download :download:`gf_forward_pseudo_rupture_basic.py </../../examples/gf_forward_pseudo_rupture_basic.py>`

.. literalinclude :: /../../examples/gf_forward_pseudo_rupture_basic.py
    :language: python



Traction and stress field parametrisation
=========================================

The rupture plane can be exposed to different stress/traction field models which drive and interact with the rupture process.

A :class:`~pyrocko.gf.tractions.TractionField` defines the absolute stress release on the fault plane:

    * :class:`~pyrocko.gf.tractions.HomogeneousTractions`
    * :class:`~pyrocko.gf.tractions.DirectedTractions`
    * :class:`~pyrocko.gf.tractions.FractalTractions`

An :py:class:`~pyrocko.gf.tractions.AbstractTractionField` can modify an existing :class:`~pyrocko.gf.tractions.TractionField`:

    * :class:`~pyrocko.gf.tractions.RectangularTaper`
    * :class:`~pyrocko.gf.tractions.DepthTaper`

These fields can be used independently or be combined into a :py:class:`~pyrocko.gf.tractions.TractionComposition`, where :py:class:`~pyrocko.gf.tractions.TractionField` are stacked and :py:class:`~pyrocko.gf.tractions.AbstractTractionField` are multiplied with the stack. See the reference and code for implementation details.

Pure tractions can be visualised using the utility function :py:func:`~pyrocko.gf.tractions.plot_tractions`.



Plotting and rupture model insights
===================================

Convenience functions for plotting and introspection of the dynamic rupture model are offered by the :py:mod:`pyrocko.plot.dynamic_rupture` module.

Traction and rupture evolution
------------------------------

Initialize a simple dynamic rupture with uniform rake tractions and visualize the tractions and rupture propagation.

Download :download:`gf_forward_pseudo_rupture_basic_plot.py </../../examples/gf_forward_pseudo_rupture_basic_plot.py>`

.. literalinclude :: /../../examples/gf_forward_pseudo_rupture_basic_plot.py
    :language: python

.. figure :: /static/dynamic_basic_tractions.png
    :align: center
    :width: 70%
    :alt: Rupture propagation and tractions of a simple dynamic rupture source
        with uniform rake tractions

    Absolute tractions of a simple dynamic source model with a uniform rake. Contour lines are isochrones of the rupture front.


Rupture propagation
-------------------

We can investigate the rupture propagation speed :math:`v_r` with :py:meth:`~pyrocko.plot.dynamic_rupture.RuptureView.draw_patch_parameter`.
Rupture speed is proportional to the S-wave velocity in the Earth model and scaled with the attribute :py:gattr:`~pyrocko.gf.seismosizer.PseudoDynamicRupture.gamma`.

.. code-block :: python

    # rupture is a PseudoDynamicRupture object
    plot = RuptureView(rupture)

    plot.draw_patch_parameter('vr')
    plot.draw_time_contour(store)
    plot.draw_nucleation_point()
    plot.show_plot()


.. figure :: /static/dynamic_basic_vr.png
    :align: center
    :width: 70%
    :alt: Rupture propagation and tractions of a simple dynamic rupture source
        with uniform rake tractions

    Rupture propagation speed of a simple dynamic source model. Contour lines are isochrones of the rupture front.


Slip distribution
-----------------

Dislocations of the dynamic rupture source can be plotted with :py:meth:`~pyrocko.plot.dynamic_rupture.RuptureView.draw_dislocation`:

.. code-block :: python

    # rupture is a PseudoDynamicRupture object
    plot = RuptureView(rupture)

    plot.draw_dislocation()
    plot.draw_time_contour(store)
    plot.draw_nucleation_point()
    plot.show_plot()


.. figure :: /static/dynamic_basic_dislocations.png
    :align: center
    :width: 70%
    :alt: Rupture propagation and dislocation of a simple dynamic rupture source
        with uniform rake tractions

    Absolute dislocation of a simple dynamic rupture source model with uniform rake tractions. Contour lines are isochrones of the rupture front.


Rupture evolution
-----------------

We can animate the rupture evolution using the :py:func:`~pyrocko.plot.dynamic_rupture.rupture_movie` function.

.. code-block :: python

    from pyrocko.plot.dynamic_rupture import rupture_movie

    rupture_movie(
        rupture, store, 'dislocation',
        plot_type='view')


.. raw:: html

    <center>
        <video width="70%" controls>
            <source src="https://data.pyrocko.org/media/dislocation_view_movie.mp4" type="video/mp4">
            Your browser does not support the video tag.
        </video>
    </center>


Combined complex traction fields
--------------------------------

In this example we will combine different traction fields: :py:class:`~pyrocko.gf.tractions.DirectedTractions`, :py:class:`~pyrocko.gf.tractions.FractalTractions` and taper them using :py:class:`~pyrocko.gf.tractions.RectangularTaper`.

After plotting the tractions and final dislocations, we will forward model the waveforms.

Download :download:`gf_forward_pseudo_rupture_complex.py </../../examples/gf_forward_pseudo_rupture_complex.py>`

.. literalinclude :: /../../examples/gf_forward_pseudo_rupture_complex.py
    :language: python


.. figure :: /static/dynamic_complex_tractions.png
    :align: center
    :width: 70%
    :alt: Rupture propagation and tractions of a complex dynamic rupture source with uniform rake
        tractions and random fractal perturbations.

    Absolute tractions of a complex dynamic rupture source model with uniform rake and superimposed random fractal perturbations.



.. figure :: /static/dynamic_complex_dislocations.png
    :align: center
    :width: 70%
    :alt: Rupture propagation and dislocation of a complex dynamic rupture source
        with uniform rake tractions and random fractal perturbations.

    Absolute dislocation of a complex dynamic rupture source with uniform rake and superimposed random fractal perturbations. Contour lines are isochrones of the rupture front.


.. figure :: /static/dynamic_complex_waveforms_snuffler.png
    :align: center
    :width: 80%
    :alt: Synthetic waveforms modelled from the pseudo dynamic rupture source model.

    Synthetic waveforms generated by :doc:`Pyrocko-GF <pyrocko-gf>` from the pseudo dynamic rupture model at 31 km distance.



Moment rate function / source time function
-------------------------------------------

With this example we demonstrate, how the moment rate :math:`\dot{M}(t)` or source time function (STF) of a rupture can be simulated using the slip rate on each subfault :math:`\dot{u_i}(t)`, the average shear modulus :math:`\mu` and the subfault areas :math:`A_i`:

.. math::  \dot{M}(t) = \sum_{i=1}^{n_{sf}} \dot{u_i}(t) \mu A_i

Use the method :py:meth:`~pyrocko.plot.dynamic_rupture.RuptureView.draw_source_dynamics`:


.. code-block :: python

    plot = RuptureView(rupture)

    # variable can be:
    #    - 'stf', 'moment_rate':            moment rate function
    #    - 'cumulative_moment', 'moment':   cumulative seismic moment function
    # of the rupture
    plot.draw_source_dynamics(variable='stf', store=store)
    plot.show_plot()


.. figure :: /static/dynamic_source_time_function.png
    :align: center
    :width: 70%
    :alt: Source time function of a complex dynamic rupture source with uniform rake
        tractions and random fractal perturbations.

    Source time function (moment rate function) of the complex dynamic rupture source model with uniform rake and superimposed random fractal perturbations.



Individual time-dependent subfault characteristics
--------------------------------------------------

Sometimes it might be also interesting to check the time-dependent behaviour of an individual subfault.

Use the method :py:meth:`~pyrocko.plot.dynamic_rupture.RuptureView.draw_patch_dynamics`:

.. code-block :: python

    plot = RuptureView(rupture)

    # nx and ny are the indices of the subfault along strike (nx) and down dip (ny)
    # variable can be:
    #    - 'dislocation':                   length of subfault dislocation vector [m]
    #    - 'dislocation_<x, y, z>':         subfault dislocation vector component
    #                                       in strike, updip or normal direction in [m]
    #    - 'slip_rate':                     subfault slip rate in [m/s]
    #    - 'moment_rate':                   subfault moment rate function
    #    - 'cumulative_moment', 'moment':   subfault summed moment function
    # of the rupture
    plot.draw_patch_dynamics(variable='slip_rate', nx=6, ny=3, store=store)
    plot.show_plot()


.. figure :: /static/dynamic_complex_patch_slip_rate.png
    :align: center
    :width: 70%
    :alt: Slip rate function of a single subfault of the complex dynamic rupture source with uniform rake tractions and random fractal perturbations.

    Slip rate function of a single subfault (:math:`n_x=6, n_y=3`) of the complex dynamic rupture source with uniform rake tractions and random fractal perturbations.


Radiated seismic energy
-----------------------

For rather complex ruptures also directivity effects in the waveforms are of interest. Using the function :py:func:`~pyrocko.plot.directivity.plot_directivity` allows to plot synthetic waveforms or its envelopes at a certain distance from the source in a circular plot. It provides an easy way of visual directivity effect imaging.

.. code-block :: python

    from pyrocko.plot.directivity import plot_directivity

    # many more possible arguments are provided in the help of plot_directivity
    resp = plot_directivity(
        engine,
        rupture,
        store_id,
        phases={
            'P': '{cake:p|cake:P}-10%',
            'S': '{cake:s|cake:S}+50'},

        # distance and azimuthal density of modelled waveforms
        distance=300*km,
        dazi=5.,

        # waveform settings
        component='R',
        quantity='displacement',
        envelope=True,

        plot_mt='full')


.. figure :: /static/dynamic_complex_directivity.png
    :align: center
    :width: 70%
    :alt: Directivity plot at 300 km distance for the complex dynamic rupture source with uniform rake tractions and random fractal perturbations.

    Directivity plot at 300 km distance for the complex dynamic rupture source with uniform rake tractions and random fractal perturbations.


**********
References
**********
.. [Dahm2021] Dahm, T., Heimann, S., Metz, M., Isken, M. P. (2021). A self-similar dynamic rupture model based on the simplified wave-rupture analogy. Geophysical Journal International. Volume 225, Issue 3, June 2021, Pages 1586–1604, https://doi.org/10.1093/gji/ggab045
