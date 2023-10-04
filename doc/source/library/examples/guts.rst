Working with the ``guts`` package
=================================

Introduction to ``guts``
------------------------

Guts is a `Lightweight declarative YAML and XML data binding for Python
<https://github.com/emolch/guts>`_ (the link provides a basic introduction
and usage tutorial).


``guts`` and ``pyrocko``
------------------------

When building add-on functionality to pyrocko, objects that will be
in/ex-ported can use the guts wrapping to conform easily to pyrocko standards.
There is some overhead, so only certain items implement the guts package in the
base pyrocko project.  One add-on functionality that implement it is the
``fomosto report`` command.  Within it, the base class
:py:class:`~pyrocko.fomosto.report.report_main.GreensFunctionTest` and a small
utility class :py:class:`~pyrocko.fomosto.report.report_main.SensorArray` are
implemented with guts.  We shall look at
:py:class:`~pyrocko.fomosto.report.report_main.SensorArray` below.

Implementing ``guts``
---------------------

When creating a class that implements :py:mod:`pyrocko.guts`, first determine
which attribute are important to the class.  In the case of
:py:class:`~pyrocko.fomosto.report.report_main.SensorArray` those attributes
are: ``distance_min``, ``distance_max``, ``strike``, and ``sensor_count``.  Now
create the class and attributes, where the attributes are defined as guts types
(good practice is to define a ``guts_prefix`` to the module, as it helps with
in/ex-porting).

Download :download:`guts_sensor_array.py </../../examples/guts_sensor_array.py>`

.. literalinclude :: /../../examples/guts_sensor_array.py
    :language: python


As you can see only one type has a default value, so when initializing the
object if values do not get passed in for the attributes without default
values, then the ``guts`` initializer will throw an error.

Other attributes whose values are desired to be keep through in/ex-porting,
but do not need to be initialized by default can have the ``optional``
parameter set to ``True``.  This will allow them to be exported with when the
attribute has been assigned a value.

Usage examples
--------------

Now that a class has been defined (and imported) we can see how to use it.


Download :download:`guts_usage.py </../../examples/guts_usage.py>`

.. literalinclude :: /../../examples/guts_usage.py
    :language: python


Example guts YAML File:
-----------------------

This is a minimal example of a guts YAML file.

Download :download:`guts_usage.py </../../examples/guts_example.yaml>`

.. literalinclude :: /../../examples/guts_example.yaml
    :language: yaml
