# Changelog

All notable changes to Pyrocko are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## Unreleased

### Added
- Sparrow:
    - global colorbar handling added to CPTHandler
    - added Elements: Rivers, Borders, Geonames
- datasets:
    - gshhg: added classes Coastlines, Rivers, Borders
    - geonames: added Countries
### Fixed
- Sparrow:
    - GeometryElement: aware to global and focal time windows for animations

## v2024.01.10

### Added
- Support for rotational GFs.
- Seismosizer snuffling: add MT source type
- Date/time parsing now accepts 'today' and 'tomorrow' where
  `str_to_time_fillup` is used.
- Squirrel FDSNSource now supports restriction to concrete list of NSLC codes.
- Squirrel catalog client: add ISC catalog support
- Squirrel: add support for named datasets

### Changed
- Improved progress indicators.
- Release GIL in a few more computation functions.
- Squirrel FDSN clients now store metadata in pickle format rather than
  StationXML for speedup.

### Fixed
- Improved extraction of station information in Pyrocko format from StationXML,
  for situations where the channels of a sensor are split into multiple station
  objects.
- Fixed broken timeout handling in FDSN clients.
- Fixed inconsistencies in StationXML / squirrel unit definitions.
- Various small bug fixes.

## v2023.10.11

### Added
- Pseudo dynamic rupture:
    - Coulomb failure stress modelling.
    - New method to get slip- or moment-scaled tractions.
- GF:
    - New source time function: TremorSTF
- Squirrel:
    - `squirrel jackseis`: support restitution
    - `squirerl jackseis`: new `--dump-config` option

### Removed
- Removed `squirrel jackseis-classic` subcommand. All features are now
  available in `squirrel jackseis`.

### Changed
- Cake: new implementation for LayeredModel.perturb
- Improved library reference manual.

### Fixed
- Fixed various compatibility issues.
- Fixed various bugs.

## v2023.06.29

### Added
- Beachball example: explain syntetic polarity calulation.
- Squirrel: support `now` in command line time arguments.

### Changed
- Disallow automatic downloads in `squirrel snuffler`.
- Allow ignoring some errors when getting pyrocko stations.
- Squirrel: improve behaviour when downloading close to real time data.

### Fixed
- Snuffler: improve robustness against broken snufflings.
- Fix broken beachball.amplitudes which used incorrect units rad instead of
  deg.
- Snufflings rms, spectrogram, stalta: filter ranges now adapt to data sampling
  rates.
- `squirrel snuffler`: fix crash due to incorrect pile emulation.
- Squirrel: Fix crash when chopping over sequence without any waveforms.
- Smartplot: fix tick label placement issues.


## v2023.06.07

### Added
- The Sparrow.
- Squirrel:
    - `squirrel jackseis`: add `--rename-*` options to change nslc codes.
    - `squirrel jackseis`: support more downsamling ratios.
      travel-time.
    - Can now avoid getting redundant waveforms (LH, BH, HH) with channel
      priorities and sample rate ranges. Supported in `squirrel summon` and
      `Squirrel.get_waveforms`, etc.
- `gf.Store.t`: allow getting stored attributes like takeoff-angle along with
- Automap: support custom grd files.
- Reader for Silixa's HDF5 iDAS files.

### Changed
- Squirrel:
    - allow threads
    - more consistent format of outputs from `squirrel nuts`,
      `squirrel response`, etc.
    - `squirrel stationxml`: improved robustness against duplicate entries,
      allow ignoring some errors.

### Fixed
- Squirrel:
    - fixed error leading to overlaps in FDSN waveform downloads.
    - add protection against huge downloads when remote FDSN reports
      incorrect sample rate in meta-data.

## v2023.03.27

### Added
- Squirrel: new subcommand `check` to detect common data/metadata problems.
  Also available as a method on the Squirrel object.
- Squirrel: new subcommand `response` to plot and investigate instrument
  responses
- Improved response plotting and added the ability to combine common responses.
- Added a script `pyrocko` which can print some information about the Pyrocko
  installation and about the availability of its required and optional deps.
- Jackseis: added option to scale seismograms with a common factor.

### Changed
- Squirrel: format of object summary outputs are now more consistent and more
  shell-pipe-friendly.
- Fomosto: `view` now autoconfigures Snuffler after startup in a useful way.

### Fixed
- Corrected implementation of `Squirrel.get_sensors`.
- Corrected handling of the `view` argument in beachball plotting functions.

## v2023.01.20

### Fixed
- Fix compatibility with newer versions of NumPy and SciPy.
- Fix broken function pyrocko.client.fdsn.event.
- Fix broken YAML-serialization of `Trace` objects.
- Squirrel: fix problems in `get_stations` with `model='pyrocko'`
- Various minor bugs and typos fixed.

## v2022.11.29

### Added
- Squirrel:
  - `squirrel jackseis`: new command line options: `--traversal`, `--tinc`
- Fomosto QSEIS backend: added support for qseis_2006b with adjustable source
  disk radius. Setting this to zero allows calculating of seismograms which are
  correct for low frequencies down to static displacement.
- Snufflings:
  - Seismosizer: add single-force source model.
  - Smartplot integration for improved MPL plot/figure layouting.
  - New built-in Snuffling: Spectrogram
- Docs: add mini-tutorial on how to set up and use remote Snuffler through VNC.
- New function to get a Snuffler-like time axis in MPL plots
  `pyrocko.plot.mpl_time_axis`
- Convenience script for Windows users to download and install MSVC build tools
  15 from the command line.
- Pseudo-dynamic rupture model: add method to get centroid location.

### Changed
- Squirrel: refactored Channel and Sensor classes, improved channel-to-sensor
  logic.
- Snuffler: enlarged default filter ranges.
- Reimplemented TypeC (3D) GF store. To my knowledge this store type has not
  yet been used in the wild, so felt free to improve the design.
- Default antialising FIR filter ``fir-remez`` now uses 45 x q taps instead of
  40 x q.

### Fixed
- *Important:* fixed buffer overflow error in `pyrocko.util.time_to_str`. This
  one-byte buffer overflow occurred for time formats, when the format string
  did *not* request fractional seconds to be appended, e.g. `'%Y-%m-%d
  %H:%M:%S'`. It caused random crashes on macOS and, for longer format strings,
  also on Linux. The error did not occur with the default `format` parameter of
  `time_to_str`.
- Squirrel: various bug fixes and minor improvements.
- Automap: improved GMT6 support.
- Fix crash in `pyrocko.trace.degapper` with `fillmethod='zeros'`.
- Fix output channel naming in `pyrocko.trace.rotate_to_rt`.
- Snuffler:
  - Now always uses locale-independent dates in time axis.
  - Various appearance fixes.
  - Prevent a confusing warning at startup on macOS.
- Snufflings:
  - STA/LTA: fix error where markers were being inserted multiple times.
  - Fix Snuffler crashes when exception is raised in trigger button calls.
- Much improved `pyrocko.plot.smartplot` module.
- Corrected conversion between volume-change and moment for VLVD and explosion
  sources. Before, the approximation for a Poisson solid was used.

## v2022.06.10

### Added
- `squirrel jackseis`: new option: `--codes`
- `squirrel codes`: new options: `--codes`, `--kind`
- Squirrel pile emulation: support `chopper_grouped` method.
- Squirrel: support grouping in `chopper_waveforms` method.
- Running `python -m rdseed` now converts dataless to stationxml.
- Squirrel: new subcommands `remove promises`, `stationxml`.
- New Squirrel CLI tutorial.
- Support GMT6 in gmtpy and automap.

### Fixed
- Fixed installation issues
  - `install.py` called incorrect pip version,
  - Improved platform detection.
  - `install.py` now works on some older linuxes.
- Squirrel: various bugfixes and docs improvements
- Improved robustness of StationXML response handling.

### Changed
- Snuffler: allow confirmation of ctrl-c on command line.
- Drop support for auto-persistent datasets (had confusing consequences).

## v2022.04.28

### Added
- New framework for seismological data access: `pyrocko.squirrel`
- New module `modelling.cracksol` containing different analytical crack
  solutions for displacement and dislocation modelling.
- New extension `modelling.ext.okada_ext` following `Okada, 1992` to calculate
  displacements and spatial derivatives.
- New module `modelling.okada` with `OkadaSource` object as wrapper of C
  extension and inverter to estimate dislocation based on stress drop on a
  rectangular rupture plane.
- New `gf.seismosizer.PseudoDynamicRupture` wrapping boundary element method
  based on `modelling.okada.OkadaSource` combined with the Eikonal solver to
  perform quasi-dynamic slip modelling.
- New plotting module for the `PseudoDynamicRupture` in `plot.dynamic_rupture`.
- New scenario `scenario.sources.pseudodynrupture` for usage of the
  `PseudoDynamicRupture` as `colosseo` input.
- New `aggressive_oversampling` attribute for both `gf.RectangularSource` and
  `gf.PseudoDynamicRupture` allowing for hard oversampling of the basesources.
- RMS Snuffling: Option to show log RMS.
- New example on how to create QuakeML files from scratch.
- automap: add flags to customize plate plotting and axes ticks
- Snuffler: live seismograms from DataCube.
- Improved responses module, more supported transfer functions, converters.
- Improved error handling and diagnostics when extracting responses from
  StationXML.
- Functions to instantiate moment tensor from P and T axes.
- Examples for eikonal solver.
- Support for take-off angle and other precomputed tables in GF stores.
- Snuffler: add waterfall style for dense recordings like DAS.
- Snuffler: `goto today`, `goto yesterday` commands.
- Support reading of TDMS IDAS files.

### Fixed
- Fix Snuffler crashes on reading invalid files and other IO related errors.
- Fixed `Trace.envelope`.
- Fixed `evalresp` platform detection.
- Fixed `MomentTensor.both_slip_vectors`, this function was broken completely.

### Changed
- Drop support for Python < 3.5.
- Drop support for Qt4.
- Improvements to directivity plot.
- Renamed Snuffling "Block RMS" to "RMS".
- Fomosto QSEIS backend can now handle non-zero (negative) top layer depth,
  e.g. for models including the atmosphere.
- Removed support for initial marker file format from before August 2011.
- New installation recommendations.
- Snuffler: two more marker kinds/colors (6, 7).
- Snuffler: migrated from right-click menu to regular menubar.

## v2021.09.14

### Changed
- Improved RMS and STA/LTA Snufflings (keep responsive while processing, abort
  button, more options).

### Added
- Reading of GNSS location information from datacube files.
- Jackseis: added possibility to restitute data to displacement, velocity, or
  acceleration.

### Fixed
- Fix problems with Station-XML files containing 1900-01-01 dummy dates
  (macOS).
- Correct 'pyrocko-python' symlink on Linux which was broken in v2021.06.29
  (affects grondown scripts).

## v2021.06.29

### Added
- Windows support (experimental).
- Jackseis: can now use 3-digit Julian day in output filename templates.

### Changed
- Snuffler: improved fidelity when working with many markers. It should now be
  possible to smoothly handle 100.000 markers. The option
  `--disable-marker-sorting` can be supplied to disable sorting in the marker
  side-panel for an additional speedup.
- Improved high precision (HP) time handling. Pyrocko now has two distinct
  modes for time handling. Timestamps are now handled either as 64-bit floats
  or as 96/128-bit floats. The mode can be selected by environment variable,
  config setting or by a call to `util.use_high_precicion_time` at program
  startup. HP time mode is only available on platforms where NumPy's HP floats
  are available. HP time mode is necessary when handling data with sampling
  rates above 100 kHz.
- Dropping support for Python 2 binary distribution packages (Anaconda and
  PIP).
- Python 2 support will be removed from Pyrocko in the near future in order to
  reduce our maintenance and testing workload. Sorry.

### Fixed
- Fixed an error in Double-DC source which caused incorrect placement of the
  sub-sources.

## v2021.04.02

### Added
- RectangularSource: added opening_fraction to model tensile dislocations
- New command line option for jackseis: `--record-length`
- Timing definition offsets can now take `%` as suffix to scale phase
  traveltimes relatively.
- New plot function to show radiation pattern / azimuthal distribution of
  directivity effects for synthetics.
- Snuffler: load StationXML via menu.
- `io.mseed`: Adding option for STEIM2 compression.
- Jackseis: Adding `--output-steim` option to control compression. Default
  compression changed to STEIM2.
- YAML files can now include other YAML files, when loaded through guts.
- Moment tensor objects can now also be initialized from east-north-up
  coordinates.

### Fixed
- Fix plotting issues in cake.
- Update Geofon catalog to handle MTs correctly after Geofon web page update.
- Fix typos in STA/LTA documentation.
- Fomosto PSGRN/PSCMP backend: improved control of modelling parameters,
  fixes some accuracy issues, regarding the spacial sampling interval.
- Fomosto PSGRN/PSCMP backend: fixed scaling of isotropic GF components
- Improved handling of differing sampling rates and interpolation settings
  when modelling multiple targets in `gf.Engine.process`.
- PyQt compat issues with MacOS Big Sur.
- Fix of `gf.SFSource.discretize_basesource`.

### Changed
- GmtPy now forces PDF version 1.5 when producing PDFs (newer PDFs caused
  problems when included in XeLaTeX).
- QuakeML: Not strictly requiring preferred origin to be set anymore when
  extracting Pyrocko event objects.
- Snuffler now asks for confirmation when the user attempts to close the
  window.

## v2020.10.26

### Fixed
- Fix errors with corrupt WADL returned by GEONET FDSN web service.
- Fix cake crashes related to the `--distances` argument on newer
  NumPy/Python3.8.

### Changed
- Changed default of `demean` argument to `Trace.transfer` from `False` to
  `True`, to be consistent with the behaviour before the introduction of that
  flag.

## v2020.10.08

### Added
- Support for rotational seismograms in GF stores and Fomosto QSSP2017 backend.
- Trace objects now support serialization to YAML and inclusion into Guts based
  objects.

### Fixed
- Fix incorrect conversion from displacement to velocity and acceleration in
  seismogram synthesis in `pyrocko.gf`. The problem occured when
  `quantity='velocity'` was selected in a `pyrocko.gf.Target` with a GF store
  with `stored_quantity='displacement'`. The returned amplitudes were incorrect
  except for the case of 1 Hz GFs.

### Changed
- Installation of prerequisites is now possible with a separate script
  `install_prerequisites.py` rather than through `setup.py
  install_prerequisites`.

## v2020.08.18

### Added
- Respect sensor azimuth and dip when converting RESP to StationXML.
- Scenario-generator (Colosseo) now supports user-specified lists of stations.

### Changed
- FDSN client now checks arguments against service description (WADL) by
  default.
- Improved FDSN client and documentation.

### Fixed
- Fix Py2/Py3 related crashes of `fomosto server`.
- Fix installation dependency issues.
- Fix error in EPS export of GmtPy (GMT5).
- Fix broken CSV export in CrustDB.
- Fix broken help panel in some snufflings.
- Fix buggy marker removal in Snuffler
- Various small bug fixes and documentation improvements.

## v2020.03.30

### Fixed
- Fix Python 2 issue affecting `fomosto server`

## v2020.03.13

### Added
- Event objects now have an `extras` dict to hold user defined attributes.

### Changed
- Removed dependency on 'future' package.
- On installation with pip we now allow automatic dependency resolution.
- We now additionally provide binary 'manylinux1' pip wheels for Python 2.7,
  3.5, 3.6, 3.7, and 3.8.
- Improved testing, CI, deployment.

### Fixed
- Fix a bug in static modelling time handling.

## v2020.03.03

### Added
- `fomosto`:
  - Support QSSP 2017
  - Support QSSP PPEG variant
  - Add subcommand `tttlsd` to fill holes in travel time tables. Uses eikonal
    solver to fill the holes.
  - Allow setting receiver depth for `tttview`.
- `gf`:
  - Support ``velocity`` and ``acceleration`` as stored GF quantities.
  - Support squared half-sinusoid source time function.
- Allow specifying record length when saving MiniSEED files.
- New command line options to save cake plots.

### Changed
- In `trace.transfer`, bypass FFTs for flat responses.
- `fdsn` adding event query
- `snuffling.catalog` adding FDSN event query
- Snuffler adding `trace_scale` to configuration
- Added Burger elasticity parameters to cake and `gf.psgrn_pscmp`
- Added Smithsonian Volcano database to `pyrocko.dataset`
- Added Tile export to 3D printable formats

### Fixed
- Fix problems with corrupt channel info text tables from FDSN.
- Correct reading of SEGY files with IEEE floating point values.
- Correct query parameters for ISC catalog, previous versions where querying
  for HH:HH:SS instead of HH:MM:SS.
- Fix scenario generator crashes.
- Fix incorrect error handling in GF waveform synthesis
  (`store_calc_timeseries`).
- Fix failing maps snuffling when running multiple Snuffler instances.

## v2020.02.10

### Added
- Support querying all stations with `GLOBAL` from ISC.
- Support event queries in `client.fdsn`.
- Catalog snuffling: support FDSN event queries.
- Add `trace_scale` setting in Snuffler configuration file.
- Support 1-2-3 as a valid channel triplet.
- Support `elastic2` component scheme in Fomosto QSEIS backend (pure explosion
  sources).
- Support Burger's elasticity parameters in `cake` and `gf.psgrn_pscmp`.
- Include updated old GmtPy tutorial it documentation.
- Snuffler: can now use `<tab>` and `<shift>-<tab>` to iterate through phase
  markers of active event.
- New dataset: Pleistocene and Holocene volcano database from Smithsonian
  Institution.

### Changed
- All location-based objects like events and stations should now fully support
  Cartesian offset coordinates.
- Scenario: interface, behaviour and defaults improved.
- Snuffler: trace to station lookup now supports both: `(net, sta)` and `(net,
  sta, loc)`. The latter more specific one has precedence.
- Automap: changed appearance of GNSS velocities.

### Fixed
- Fix a bug affecting origin time and STF of `gf.RectangularSource`.
- Fix conversion of QuakeML phase lacking phase hint to Pyrocko marker.
- Fix ignored `timeout` argument in `client.fdsn.dataselect`.
- Fix error in polygon-on-sphere cutting (`beachball` module).
- Fix errors in point in polygon-on-sphere checks.
- Fix various errors in GSHHG data dry/wet area masking.
- Fix crashes with bad StationXML files, improve robustness.
- Fix problems with crazy GPS infos in Datacube recordings. Time interpolation
  is now much more robust.
- Fix crashes in recursive STA/LTA.
- Fix a numerical bug in recursive STA/LTA.
- Improved SeedLink acquisition.

## v2019.06.06

### Added
- Shortcut to get Kite `Scene` from `SatelliteResult` and direct
  `KiteSceneTarget`.
- Improve documentation of `pyrocko.gf` with a special topic chapter.
- Combined volume change plus CLVD parameterized source: `gf.VLVDSource`.
- Method to perturb `cake` earth models.
- Support cross-section views in beachball plotting.

### Changed
- Automap now defaults to not show any scale.

## v2019.05.03

### Fixed
- Improved compatibility with Anaconda.

## v2019.05.02

### Added
- `gf`:
  - CombiSource, which can handle a set of different sources as a single source
    object
  - resonator stf
- `guts`:
  - Function to get Guts attributes.
  - `ypath` functions to set Guts attributes via pattern.
- Snuffler: `clip_traces` configurable in configuration file.
- New client: ISC catalog interface.
- Add a function to create phase markers from QuakeML.
- Can now use Gutenberg Richter magnitude distribution when creating synthetic
  scenario events.
- Support for handling of sparse gnss components.

### Changed
- gf:
  - Now the discretised point sources have their true time set, time shifting
    is done only before and after c function calls.
  - Source times are handled in double precision.
  - Static store requests fallback to zero time to handle absolute source
    times.
  - Store ext gives individual index for out of bounds error for targets.
- Geofon catalog web format changed, now parsing GeoJSON instead of HTML.
- Instrument response deconvolution gives more explicit warnings about
  inconsistencies.
- Changed default of `model.gnss` correlation factor to 0.0.
- Add flag to dump progressbar instead of showing the progressbar.
- Can now handle and plot GNSS stations lacking complete set of component
  orientations.
- Event depth is now optional (model).

### Fixed
- gf:
  - low level errors in time handling
  - ExplosionSource for non-volume sources
- `obspy_compat` event conversion
- Problem with numpy scalars in source and target objects
- Conversion of quakeml piks to pyrocko phasepiks use phase polarities strings
- snuffling broken load dialogs (QT5)
- trace: deltat rounding error function
- segy functions
- model.gnss covar
- scenario: perfomance improvement
- geofon catalog: problem with multiple solutions for some events
- setup: UnicodeDecodeError
- fuzzy beachball plotting bugs

## v2019.05.02

### Added

- Anaconda builds for python 3.6 and 3.7
- Green's Mill
- gf: rectangular source check for point source discretisation
- stationxml: using a flat response function is enabled
- guts: support for time stamps in local time
- datasets/geonames: get city by name
- gf: Eikonal solver
- plot: fuzzy beachballs
- trace: has a function to fix rounding errord

### Changed
- gf: improved summation of static gf components
- FDSN: configurable time out for requests

### Fixed
- rdseed get_station fix
- gf: quantity velocity from displacement through `num.diff`


## v2018.09.13

### Added
- Snuffler map added
  - Bing aerial images
  - Distance and area measure
  - Toggle lines and cities
- GF: Server added JSON API
- Snuffler: and Jackseis now accept YAML event files
- Snuffler: polarity picking in
- fomosto: ttt now checks for holes in travel-time tables
- Guts:
  - can now specify output yaml style for strings
  - improved XML namespace support
  - add utility module to help with guts structure updaters
- model: GNSS displacement components can have covariances


### Changed
- gf:
  - improved handling of derived magnitude sources
  - slip-driven rectangular source, explosion

### Fixed
- Fixed Bug in `ExplosionSource` (incorrect moment conversion)
- Fixed bug in polygon coordinates
- Fixed SSL issues
- Fixed SRTM tile download
- Fixed `fomosto tttextract --output`
- Various minor bugfixes
- Various compatibility fixes
- Updated web service URLs and online catalog parsers


## v2018.01.29

### Added
- `pyrocko.obspy_compat` compatibility with basic ObsPy classes (see https://pyrocko.org/docs/)
- Added examples for ObsPy compatability, StationXML and QuakeML
- Added `Source.outline`

### Changed


### Fixed
- `geofon` updated page parser
- old `requests` compatibility
- various bugfixes

## v2018.01.16

### Added
- improvements to `colosseo` / `scenario`
- `model.load_events()` now accepts `yaml` based event files

### Changed
- changes on geofon event web pages require an update in `catalog.geofon`
- better handling of defaults in `guts`, guts-derived default objects are now automatically cloned
- follow changed SRTM url

### Fixed
- error in string/time conversion (affecting date formats with more than one '.')
- py2/3 related bugs in `cake` and `guts`
- incorrect handling of moment/magnitude in `moment_tensor.MomentTensor.randam_mt()`

## v2017.12.13

### Added
- new `pyrocko.model`: `GNSSCampaign` model
- new `pyrocko.gf`:  `GNSSCampaignTarget`
- New module `pyrocko.scenario`: Create earthquake data scenarios on the fly, outputs are
  - Waveforms model
  - InSAR deformation model (with `kite`)
  - GNSS data
 Use `colosseo` CLI tool to initialize and calculate your earthquake scenarios.

### Changed
- `pyrocko.pile`: caching
- `snuffler`: improved OpenStreetmap visual appearance and logging
- `snuffler`: marker table print menu
- `snuffler.maps`: upgrade to OpenLayers4

## v2017.11.22

### Added
- QuakeML - Include moment tensor to `pyrocko.model.event`

### Changed
- deployment polishing to `pip` and Anaconda
- documentation

### Fixed
- `pyrocko.pile` caching
- automap SRTM download authentication

## v2017.11.16

### Added
- Python 2/3 support
- Community support chat
- new deployment for Anaconda and `pip`
- Installation through python pip and Anaconda
- Built-in Snufflings added: Maps, Seismosizer and Cake

### Changed
- Version naming has changed to rolling release style  (e.g. v2017.11.16)
- Reorganized module hierarchy (backwards-compatible)
- documentation and examples
