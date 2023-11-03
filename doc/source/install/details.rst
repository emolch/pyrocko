Detailed installation instructions
==================================

Pyrocko can be installed under any operating system where its prerequisites are
available. This document describes details about its requirements which are
needed when a standard install is not possible or conflicts arise.

**For standard install instructions, head on over to**

* :doc:`system/index`
* :doc:`packages/index`

Prerequisites
-------------

The following software packages must be installed before Pyrocko can be
installed from source:

* Build requirements
   * C compiler (tested with gcc, clang and MSVC)
   * ``patch`` utility
   * `NumPy <http://numpy.scipy.org/>`_ (>= 1.16, with development headers)
   * `wheel <https://pypi.org/project/wheel/>`_

* Try to use normal system packages for these Python modules:
   * `Python <http://www.python.org/>`_ (>= 3.8, with development headers)
   * `NumPy <http://numpy.scipy.org/>`_ (>= 1.16, with development headers)
   * `SciPy <http://scipy.org/>`_ (>= 1.0)
   * `matplotlib <http://matplotlib.sourceforge.net/>`_ (with Qt5 backend)
   * `pyyaml <https://bitbucket.org/xi/pyyaml>`_
   * `PyQt5 <http://www.riverbankcomputing.co.uk/software/pyqt/intro>`_ (only needed for the GUI apps)
   * `requests <http://docs.python-requests.org/en/master/>`_
   * `pyproj <https://pyproj4.github.io/pyproj/stable/>`_

* Optional Python modules:
   * `VTK <https://vtk.org>`_ (with Python bindings, required for the :program:`Sparrow` app)
   * `Jinja2 <http://jinja.pocoo.org/>`_ (required for the :ref:`fomosto report <fomosto_report>` subcommand)
   * `pytest <https://pytest.org>`_ (to run the unittests)
   * `coverage <https://pypi.python.org/pypi/coverage>`_ (unittest coverage report)

* Manually install these optional software tools:
   * `GMT <http://gmt.soest.hawaii.edu/>`_ (4 or 5, only required for the :py:mod:`pyrocko.plot.automap` module)
   * `slinktool <http://www.iris.edu/data/dmc-seedlink.htm>`_ (optionally, if you want to use the :py:mod:`pyrocko.streaming.slink` module)
   * `rdseed <http://www.iris.edu/software/downloads/rdseed_request.htm>`_ (optionally, if you want to use the :py:mod:`pyrocko.io.rdseed` module)
   * `QSEIS <https://git.pyrocko.org/pyrocko/fomosto-qseis>`_ (optional, needed for the Fomosto ``qseis.2006a`` backend)
   * `QSSP <https://git.pyrocko.org/pyrocko/fomosto-qssp>`_ (optional, needed for the Fomosto ``qssp.2010`` backend)
   * `PSGRN/PSCMP <https://git.pyrocko.org/pyrocko/fomosto-psgrn-pscmp>`_ (optional, needed for the Fomosto ``psgrn.pscmp`` backend)

Download, build and install from source
---------------------------------------

The following examples will install Pyrocko from source, on Linux or MacOS.
For Windows "from source" installs, please refer to :ref:`Installation on
Windows: From source <windows-install-from-source>`.

Because of the many different and conflicting ways how you can manage your
Python installations, be sure to understand the basics of Python package
management before proceeding.

For convenience, we are using Pyrocko's "from source" installation helper
``install.py`` here. Run ``python install.py --help`` for more information. The
native commands to be run are printed before execution, and have to be
confirmed by you.

.. highlight:: sh

**(A1)** Download (clone) the Pyrocko project directory with *git*::

    cd ~/src/   # or wherever you keep your source packages
    git clone https://git.pyrocko.org/pyrocko/pyrocko.git pyrocko

**(A2)** Change to the Pyrocko project directory::

    cd ~/src/pyrocko/

**(A3)** Install prerequisites using your method of choice::

    # (a) If you manage the prerequisites with the system's native package manager:
    python3 install.py deps system

    # or (b), if you manage the prerequisites with pip:
    python3 install.py deps pip

    # or (c), if you manage your installation with conda:
    python3 install.py deps conda

**(A4)** Build and install Pyrocko::

    # If you want to install for single user (pip, venv, conda):
    python3 install.py user

    # or, if you want to install system wide:
    python3 install.py system

**Note:** With *pip*, if you do not specify ``--no-deps``, it will automatically
download and install missing dependencies. Unless you manage your installations
exclusively with *pip*, omitting this flag can lead to conflicts.

**Note:** The intention of using ``--no-build-isolation`` is to compile exactly
against the already installed prerequisites. If you omit the flag, *pip* will
compile against possibly newer versions which it downloads and installs into a
temporary, isolated environment.

**Note:** If you have previously installed Pyrocko using other tools like e.g.
*pip*, or *conda*, you should first remove the old installation. Otherwise you
will end up with two parallel installations which will cause trouble.

Updating a "from source" install
--------------------------------

If you later would like to update Pyrocko, run the following commands (this
assumes that you have used *git* to download Pyrocko).

**(B1)** **Change to the Pyrocko project directory (A2).**

**(B2)** Update the project directory tree with *git*::

    git pull origin master --ff-only

**(B3)** **Build and reinstall Pyrocko (A4).**

Uninstalling
------------

You can use *pip* to uninstall Pyrocko::

    # (a) To remove a single user "from source" install (pip, venv, conda):
    pip uninstall pyrocko

    # (b) To remove a system-wide "from source" install:
    sudo pip uninstall pyrocko
