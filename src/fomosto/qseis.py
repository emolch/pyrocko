# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num
import logging
import os
import shutil
import math
import copy
import signal

from tempfile import mkdtemp
from subprocess import Popen, PIPE
from os.path import join as pjoin

from pyrocko import gf
from pyrocko import trace, util, cake
from pyrocko.moment_tensor import MomentTensor, symmat6
from pyrocko.guts import Float, Int, Tuple, List, Complex, Bool, Object, String

km = 1e3

guts_prefix = 'pf'

Timing = gf.meta.Timing

logger = logging.getLogger('pyrocko.fomosto.qseis')

# how to call the programs
program_bins = {
    'qseis.2006': 'fomosto_qseis2006',
    'qseis.2006a': 'fomosto_qseis2006a',
    'qseis.2006b': 'fomosto_qseis2006b',
}


def have_backend():
    have_any = False
    for cmd in [[exe] for exe in program_bins.values()]:
        try:
            p = Popen(cmd, stdout=PIPE, stderr=PIPE, stdin=PIPE)
            (stdout, stderr) = p.communicate()
            have_any = True

        except OSError:
            pass

    return have_any


qseis_components = 'r t z v'.split()
qseis_greenf_names = ('ex', 'ss', 'ds', 'cl', 'fz', 'fh')


def nextpow2(i):
    return 2**int(math.ceil(math.log(i)/math.log(2.)))


def str_float_vals(vals):
    return ' '.join('%e' % val for val in vals)


def str_int_vals(vals):
    return ' '.join('%i' % val for val in vals)


def str_str_vals(vals):
    return ' '.join("'%s'" % val for val in vals)


def scl(cs):
    if not cs:
        return '\n#'

    return '\n'+' '.join('(%e,%e)' % (c.real, c.imag) for c in cs)


def cake_model_to_config(mod):
    k = 1000.
    srows = []
    ref_depth = 0.
    for i, row in enumerate(mod.to_scanlines()):
        depth, vp, vs, rho, qp, qs = row
        if i == 0:
            ref_depth = depth

        row = [(depth-ref_depth)/k, vp/k, vs/k, rho/k, qp, qs]
        srows.append('%i %s' % (i+1, str_float_vals(row)))

    return '\n'.join(srows), len(srows), ref_depth


class QSeisSourceMech(Object):
    pass


class QSeisSourceMechMT(QSeisSourceMech):
    mnn = Float.T(default=1.0)
    mee = Float.T(default=1.0)
    mdd = Float.T(default=1.0)
    mne = Float.T(default=0.0)
    mnd = Float.T(default=0.0)
    med = Float.T(default=0.0)

    def string_for_config(self):
        return '1 %(mnn)15e %(mee)15e %(mdd)15e ' \
               '%(mne)15e %(med)15e %(mnd)15e ' % self.__dict__


class QSeisSourceMechSDR(QSeisSourceMech):
    m_iso = Float.T(default=0.0)
    m_clvd = Float.T(default=0.0)
    m_dc = Float.T(default=1.0e9)
    strike = Float.T(default=0.0)
    dip = Float.T(default=90.0)
    rake = Float.T(default=0.0)

    def string_for_config(self):
        return '2 %(m_iso)15e %(m_clvd)15e %(m_dc)15e ' \
               '%(strike)15e %(dip)15e %(rake)15e ' % self.__dict__


class QSeisPropagationFilter(Object):
    min_depth = Float.T(default=0.0)
    max_depth = Float.T(default=0.0)
    filtered_phase = Int.T(default=0)

    def string_for_config(self):
        return '%(min_depth)15e %(max_depth)15e ' \
               '%(filtered_phase)i' % self.__dict__


class QSeisPoleZeroFilter(Object):
    constant = Complex.T(default=(1+0j))
    poles = List.T(Complex.T())
    zeros = List.T(Complex.T())

    def string_for_config(self, version=None):
        if version in ('2006a', '2006b'):
            return '(%e,%e)\n%i%s\n%i%s' % (
                self.constant.real, self.constant.imag,
                len(self.zeros), scl(self.zeros),
                len(self.poles), scl(self.poles))
        elif version == '2006':
            return '%e\n%i%s\n%i%s' % (
                abs(self.constant),
                len(self.zeros), scl(self.zeros),
                len(self.poles), scl(self.poles))


class QSeisConfig(Object):

    qseis_version = String.T(default='2006')
    time_region = Tuple.T(2, Timing.T(), default=(
        Timing('-10'), Timing('+890')))

    cut = Tuple.T(2, Timing.T(), optional=True)
    fade = Tuple.T(4, Timing.T(), optional=True)
    relevel_with_fade_in = Bool.T(default=False)

    sw_algorithm = Int.T(default=0)
    slowness_window = Tuple.T(4, Float.T(default=0.0))
    wavenumber_sampling = Float.T(default=2.5)
    aliasing_suppression_factor = Float.T(default=0.1)
    source_disk_radius = Float.T(optional=True)

    filter_surface_effects = Int.T(default=0)
    filter_shallow_paths = Int.T(default=0)
    filter_shallow_paths_depth = Float.T(default=0.0)
    propagation_filters = List.T(QSeisPropagationFilter.T())
    receiver_filter = QSeisPoleZeroFilter.T(optional=True)

    sw_flat_earth_transform = Int.T(default=0)

    gradient_resolution_vp = Float.T(default=0.0)
    gradient_resolution_vs = Float.T(default=0.0)
    gradient_resolution_density = Float.T(default=0.0)

    wavelet_duration_samples = Float.T(default=0.0)
    wavelet_type = Int.T(default=2)
    user_wavelet_samples = List.T(Float.T())

    def items(self):
        return dict(self.T.inamevals(self))


class QSeisConfigFull(QSeisConfig):

    time_start = Float.T(default=0.0)
    time_reduction_velocity = Float.T(default=0.0)
    time_window = Float.T(default=900.0)

    source_depth = Float.T(default=10.0)
    source_mech = QSeisSourceMech.T(
        optional=True,
        default=QSeisSourceMechMT.D())

    receiver_depth = Float.T(default=0.0)
    receiver_distances = List.T(Float.T())
    nsamples = Int.T(default=256)

    gf_sw_source_types = Tuple.T(6, Int.T(), default=(1, 1, 1, 1, 0, 0))

    gf_filenames = Tuple.T(6, String.T(), default=qseis_greenf_names)

    seismogram_filename = String.T(default='seis')

    receiver_azimuths = List.T(Float.T())

    earthmodel_1d = gf.meta.Earthmodel1D.T(optional=True)
    earthmodel_receiver_1d = gf.meta.Earthmodel1D.T(optional=True)

    @staticmethod
    def example():
        conf = QSeisConfigFull()
        conf.receiver_distances = [2000.]
        conf.receiver_azimuths = [0.]
        conf.time_start = -10.0
        conf.time_reduction_velocity = 15.0
        conf.earthmodel_1d = cake.load_model().extract(depth_max='cmb')
        conf.earthmodel_receiver_1d = None
        conf.sw_flat_earth_transform = 1
        return conf

    def get_output_filenames(self, rundir):
        return [pjoin(rundir, self.seismogram_filename+'.t'+c)
                for c in qseis_components]

    def get_output_filenames_gf(self, rundir):
        return [pjoin(rundir, fn+'.t'+c)
                for fn in self.gf_filenames for c in qseis_components]

    def string_for_config(self):

        def aggregate(xx):
            return len(xx), '\n'.join(
                [''] + [x.string_for_config() for x in xx])

        assert len(self.receiver_distances) > 0
        assert len(self.receiver_distances) == len(self.receiver_azimuths)
        assert self.earthmodel_1d is not None

        d = self.__dict__.copy()

        # fixing these switches here to reduce the amount of wrapper code
        d['sw_distance_unit'] = 1    # always give distances in [km]
        d['sw_t_reduce'] = 1         # time reduction always as velocity [km/s]
        d['sw_equidistant'] = 0      # always give all distances and azimuths
        d['sw_irregular_azimuths'] = 1

        d['n_distances'] = len(self.receiver_distances)
        d['str_distances'] = str_float_vals(self.receiver_distances)
        d['str_azimuths'] = str_float_vals(self.receiver_azimuths)

        model_str, nlines, ref_depth = cake_model_to_config(self.earthmodel_1d)
        d['n_model_lines'] = nlines
        d['model_lines'] = model_str

        if self.earthmodel_receiver_1d:
            model_str, nlines, ref_depth2 = cake_model_to_config(
                self.earthmodel_receiver_1d)
            assert ref_depth == ref_depth2
        else:
            model_str = '# no receiver side model'
            nlines = 0

        d['n_model_receiver_lines'] = nlines
        d['model_receiver_lines'] = model_str

        d['str_slowness_window'] = str_float_vals(self.slowness_window)

        if self.qseis_version == '2006b':
            sdr = self.source_disk_radius
            d['str_source_disk_radius'] \
                = '\n %e |dble: source_radius;' % (
                    sdr if sdr is not None else -1.0)
        else:
            if self.source_disk_radius is not None:
                raise QSeisError(
                    'This version of QSEIS does not support the '
                    '`source_disk_radius` parameter.')

            d['str_source_disk_radius'] = ''

        if self.propagation_filters and ref_depth != 0.0:
            raise QSeisError(
                'Earth model must start with zero depth if '
                'propagation_filters are set.')

        d['n_depth_ranges'], d['str_depth_ranges'] = \
            aggregate(self.propagation_filters)

        if self.wavelet_type == 0:  # user wavelet
            d['str_w_samples'] = '\n' \
                + '%i\n' % len(self.user_wavelet_samples) \
                + str_float_vals(self.user_wavelet_samples)
        else:
            d['str_w_samples'] = ''

        if self.receiver_filter:
            d['str_receiver_filter'] = self.receiver_filter.string_for_config(
                self.qseis_version)
        else:
            if self.qseis_version in ('2006a', '2006b'):
                d['str_receiver_filter'] = '(1.0,0.0)\n0\n#\n0'
            else:
                d['str_receiver_filter'] = '1.0\n0\n#\n0'

        d['str_gf_sw_source_types'] = str_int_vals(self.gf_sw_source_types)
        d['str_gf_filenames'] = str_str_vals(self.gf_filenames)

        if self.source_mech:
            d['str_source'] = "%s '%s'" % (
                self.source_mech.string_for_config(),
                self.seismogram_filename)
        else:
            d['str_source'] = '0'

        d['source_depth_rel'] = d['source_depth'] - ref_depth / km
        d['receiver_depth_rel'] = d['receiver_depth'] - ref_depth / km

        template = '''# autogenerated QSEIS input by qseis.py
#
# This is the input file of FORTRAN77 program "qseis06" for calculation of
# synthetic seismograms based on a layered halfspace earth model.
#
# by
# Rongjiang  Wang <wang@gfz-potsdam.de>
# GeoForschungsZentrum Potsdam
# Telegrafenberg, D-14473 Potsdam, Germany
#
# Last modified: Potsdam, Nov., 2006
#
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
# If not specified, SI Unit System is used overall!
#
# Coordinate systems:
# cylindrical (z,r,t) with z = downward,
#                          r = from source outward,
#                          t = azmuth angle from north to east;
# cartesian (x,y,z) with   x = north,
#                          y = east,
#                          z = downward;
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
#
#	SOURCE PARAMETERS
#	=================
# 1. source depth [km]
#------------------------------------------------------------------------------
 %(source_depth_rel)e                    |dble: source_depth;
#------------------------------------------------------------------------------
#
#	RECEIVER PARAMETERS
#	===================
# 1. receiver depth [km]
# 2. switch for distance sampling role (1/0 = equidistant/irregular); switch
#    for unit used (1/0 = km/deg)
# 3. number of distance samples
# 4. if equidistant, then start and end trace distance (> 0); else distance
#    list (please order the receiver distances from small to large)
# 5. (reduced) time begin [sec] & length of time window [sec], number of time
#    samples (<= 2*nfmax in qsglobal.h)
# 6. switch for unit of the following time reduction parameter: 1 = velocity
#    [km/sec], 0 = slowness [sec/deg]; time reduction parameter
#------------------------------------------------------------------------------
 %(receiver_depth_rel)e                         |dble: receiver_depth;
 %(sw_equidistant)i  %(sw_distance_unit)i   |int: sw_equidistant, sw_d_unit;
 %(n_distances)i                            |int: no_distances;
 %(str_distances)s                          |dble: d_1,d_n; or d_1,d_2, ...(no comments in between!);
 %(time_start)e %(time_window)e %(nsamples)i  |dble: t_start,t_window; int: no_t_samples;
 %(sw_t_reduce)i %(time_reduction_velocity)e  |int: sw_t_reduce; dble: t_reduce;
#------------------------------------------------------------------------------
#
#	WAVENUMBER INTEGRATION PARAMETERS
#	=================================
# 1. select slowness integration algorithm (0 = suggested for full wave-field
#    modelling; 1 or 2 = suggested when using a slowness window with narrow
#    taper range - a technique for suppressing space-domain aliasing);
# 2. 4 parameters for low and high slowness (Note 1) cut-offs [s/km] with
#    tapering: 0 < slw1 < slw2 defining cosine taper at the lower end, and 0 <
#    slw3 < slw4 defining the cosine taper at the higher end. default values
#    will be used in case of inconsistent input of the cut-offs (possibly with
#    much more computational effort);
# 3. parameter for sampling rate of the wavenumber integration (1 = sampled
#    with the spatial Nyquist frequency, 2 = sampled with twice higher than
#    the Nyquist, and so on: the larger this parameter, the smaller the space-
#    domain aliasing effect, but also the more computation effort);
# 4. the factor for suppressing time domain aliasing (> 0 and <= 1) (Note 2).
#------------------------------------------------------------------------------
 %(sw_algorithm)i                    |int: sw_algorithm;
 %(str_slowness_window)s             |dble: slw(1-4);
 %(wavenumber_sampling)e             |dble: sample_rate;
 %(aliasing_suppression_factor)e     |dble: supp_factor;%(str_source_disk_radius)s
#------------------------------------------------------------------------------
#
#	        OPTIONS FOR PARTIAL SOLUTIONS
#       (only applied to the source-site structure)
#	    ===========================================
#
# 1. switch for filtering free surface effects (0 = with free surface, i.e.,
#    do not select this filter; 1 = without free surface; 2 = without free
#    surface but with correction on amplitude and wave form. Note switch 2
#    can only be used for receivers at the surface)
# 2. switch for filtering waves with a shallow penetration depth (concerning
#    their whole trace from source to receiver), penetration depth limit [km]
#
#    if this option is selected, waves whose travel path never exceeds the
#    given depth limit will be filtered ("seismic nuting"). the condition for
#    selecting this filter is that the given shallow path depth limit should
#    be larger than both source and receiver depth.
#
# 3. number of depth ranges where the following selected up/down-sp2oing P or
#    SV waves should be filtered
# 4. the 1. depth range: upper and lower depth [km], switch for filtering P
#    or SV wave in this depth range:
#
#    switch no:              1      2        3       4         other
#    filtered phase:         P(up)  P(down)  SV(up)  SV(down)  Error
#
# 5. the 2. ...
#
#    The partial solution options are useful tools to increase the numerical
#    significance of desired wave phases. Especially when the desired phases
#    are smaller than the undesired phases, these options should be selected
#    and carefully combined.
#------------------------------------------------------------------------------
 %(filter_surface_effects)i                  |int: isurf;
 %(filter_shallow_paths)i %(filter_shallow_paths_depth)e  |int: sw_path_filter; dble:shallow_depth_limit;
 %(n_depth_ranges)i %(str_depth_ranges)s
#------------------------------------------------------------------------------
#
#	SOURCE TIME FUNCTION (WAVELET) PARAMETERS (Note 3)
#	==================================================
# 1. wavelet duration [unit = time sample rather than sec!], that is about
#    equal to the half-amplitude cut-off period of the wavelet (> 0. if <= 0,
#    then default value = 2 time samples will be used), and switch for the
#    wavelet form (0 = user's own wavelet; 1 = default wavelet: normalized
#    square half-sinusoid for simulating a physical delta impulse; 2 = tapered
#    Heaviside wavelet, i.e. integral of wavelet 1)
# 2. IF user's own wavelet is selected, then number of the wavelet time samples
#    (<= 1024), and followed by
# 3. equidistant wavelet time samples
# 4  ...(continue) (! no comment lines allowed between the time sample list!)
#    IF default, delete line 2, 3, 4 ... or comment them out!
#------------------------------------------------------------------------------
 %(wavelet_duration_samples)e %(wavelet_type)i%(str_w_samples)s
#------------------------------------------------------------------------------
#
#	 FILTER PARAMETERS OF RECEIVERS (SEISMOMETERS OR HYDROPHONES)
#	 ============================================================
# 1. constant coefficient (normalization factor)
# 2. number of roots (<= nrootmax in qsglobal.h)
# 3. list of the root positions in the complex format (Re,Im). If no roots,
#    comment out this line
# 4. number of poles (<= npolemax in qsglobal.h)
# 5. list of the pole positions in the complex format (Re,Im). If no poles,
#    comment out this line
#------------------------------------------------------------------------------
 %(str_receiver_filter)s
#------------------------------------------------------------------------------
#
#	OUTPUT FILES FOR GREEN'S FUNCTIONS (Note 4)
#	===========================================
# 1. selections of source types (yes/no = 1/0)
# 2. file names of Green's functions (please give the names without extensions,
#    which will be appended by the program automatically: *.tz, *.tr, *.tt
#    and *.tv are for the vertical, radial, tangential, and volume change (for
#    hydrophones) components, respectively)
#------------------------------------------------------------------------------
#  explosion   strike-slip dip-slip   clvd       single_f_v  single_f_h
#------------------------------------------------------------------------------
 %(str_gf_sw_source_types)s
 %(str_gf_filenames)s
#------------------------------------------------------------------------------
#	OUTPUT FILES FOR AN ARBITRARY POINT DISLOCATION SOURCE
#               (for applications to earthquakes)
#	======================================================
# 1. selection (0 = not selected; 1 or 2 = selected), if (selection = 1), then
#    the 6 moment tensor elements [N*m]: Mxx, Myy, Mzz, Mxy, Myz, Mzx (x is
#    northward, y is eastward and z is downard); else if (selection = 2), then
#    Mis [N*m] = isotropic moment part = (MT+MN+MP)/3, Mcl = CLVD moment part
#    = (2/3)(MT+MP-2*MN), Mdc = double-couple moment part = MT-MN, Strike [deg],
#    Dip [deg] and Rake [deg].
#
#    Note: to use this option, the Green's functions above should be computed
#          (selection = 1) if they do not exist already.
#
#                 north(x)
#                  /
#                 /\ strike
#                *----------------------->  east(y)
#                |\                       \
#                |-\                       \
#                |  \     fault plane       \
#                |90 \                       \
#                |-dip\                       \
#                |     \                       \
#                |      \                       \
#           downward(z)  \-----------------------\\
#
# 2. switch for azimuth distribution of the stations (0 = uniform azimuth,
#    else = irregular azimuth angles)
# 3. list of the azimuth angles [deg] for all stations given above (if the
#    uniform azimuth is selected, then only one azimuth angle is required)
#
#------------------------------------------------------------------------------
#     Mis        Mcl        Mdc        Strike     Dip        Rake      File
#------------------------------------------------------------------------------
#  2   0.00       1.00       6.0E+19    120.0      30.0       25.0      'seis'
#------------------------------------------------------------------------------
#     Mxx        Myy        Mzz        Mxy        Myz        Mzx       File
#------------------------------------------------------------------------------
%(str_source)s
%(sw_irregular_azimuths)i
%(str_azimuths)s
#------------------------------------------------------------------------------
#
#	GLOBAL MODEL PARAMETERS (Note 5)
#	================================
# 1. switch for flat-earth-transform
# 2. gradient resolution [%%] of vp, vs, and ro (density), if <= 0, then default
#    values (depending on wave length at cut-off frequency) will be used
#------------------------------------------------------------------------------
 %(sw_flat_earth_transform)i     |int: sw_flat_earth_transform;
 %(gradient_resolution_vp)e %(gradient_resolution_vs)e %(gradient_resolution_density)e   |dble: vp_res, vs_res, ro_res;
#------------------------------------------------------------------------------
#
#	                LAYERED EARTH MODEL
#       (SHALLOW SOURCE + UNIFORM DEEP SOURCE/RECEIVER STRUCTURE)
#	=========================================================
# 1. number of data lines of the layered model (source site)
#------------------------------------------------------------------------------
 %(n_model_lines)i                   |int: no_model_lines;
#------------------------------------------------------------------------------
#
#	MULTILAYERED MODEL PARAMETERS (source site)
#	===========================================
# no  depth[km]  vp[km/s]  vs[km/s]  ro[g/cm^3] qp      qs
#------------------------------------------------------------------------------
%(model_lines)s
#------------------------------------------------------------------------------
#
#	          LAYERED EARTH MODEL
#       (ONLY THE SHALLOW RECEIVER STRUCTURE)
#       =====================================
# 1. number of data lines of the layered model
#
#    Note: if the number = 0, then the receiver site is the same as the
#          source site, else different receiver-site structure is considered.
#          please be sure that the lowest interface of the receiver-site
#          structure given given below can be found within the source-site
#          structure, too.
#
#------------------------------------------------------------------------------
 %(n_model_receiver_lines)i                               |int: no_model_lines;
#------------------------------------------------------------------------------
#
#	MULTILAYERED MODEL PARAMETERS (shallow receiver-site structure)
#	===============================================================
# no  depth[km]    vp[km/s]    vs[km/s]   ro[g/cm^3]   qp      qs
#------------------------------------------------------------------------------
%(model_receiver_lines)s
#---------------------------------end of all inputs----------------------------


Note 1:

The slowness is defined by inverse value of apparent wave velocity = sin(i)/v
with i = incident angle and v = true wave velocity.

Note 2:

The suppression of the time domain aliasing is achieved by using the complex
frequency technique. The suppression factor should be a value between 0 and 1.
If this factor is set to 0.1, for example, the aliasing phase at the reduced
time begin is suppressed to 10%%.

Note 3:

The default basic wavelet function (option 1) is (2/tau)*sin^2(pi*t/tau),
for 0 < t < tau, simulating physical delta impuls. Its half-amplitude cut-off
frequency is 1/tau. To avoid high-frequency noise, tau should not be smaller
than 4-5 time samples.

Note 4:

  Double-Couple   m11/ m22/ m33/ m12/ m23/ m31  Azimuth_Factor_(tz,tr,tv)/(tt)
  ============================================================================
  explosion       1.0/ 1.0/ 1.0/ -- / -- / --       1.0         /   0.0
  strike-slip     -- / -- / -- / 1.0/ -- / --       sin(2*azi)  /   cos(2*azi)
                  1.0/-1.0/ -- / -- / -- / --       cos(2*azi)  /  -sin(2*azi)
  dip-slip        -- / -- / -- / -- / -- / 1.0      cos(azi)    /   sin(azi)
                  -- / -- / -- / -- / 1.0/ --       sin(azi)    /  -cos(azi)
  clvd           -0.5/-0.5/ 1.0/ -- / -- / --       1.0         /   0.0
  ============================================================================
  Single-Force    fx / fy / fz                  Azimuth_Factor_(tz,tr,tv)/(tt)
  ============================================================================
  fz              -- / -- / 1.0                        1.0      /   0.0
  fx              1.0/ -- / --                         cos(azi) /   sin(azi)
  fy              -- / 1.0/ --                         sin(azi) /  -cos(azi)
  ============================================================================

Note 5:

Layers with a constant gradient will be discretized with a number of homogeneous
sublayers. The gradient resolutions are then used to determine the maximum
allowed thickness of the sublayers. If the resolutions of Vp, Vs and Rho
(density) require different thicknesses, the smallest is first chosen. If this
is even smaller than 1%% of the characteristic wavelength, then the latter is
taken finally for the sublayer thickness.
'''  # noqa

        return (template % d).encode('ascii')


class QSeisError(gf.store.StoreError):
    pass


class Interrupted(gf.store.StoreError):
    def __str__(self):
        return 'Interrupted.'


class QSeisRunner(object):

    def __init__(self, tmp=None, keep_tmp=False):
        self.tempdir = mkdtemp(prefix='qseisrun-', dir=tmp)
        self.keep_tmp = keep_tmp
        self.config = None

    def run(self, config):
        self.config = config

        input_fn = pjoin(self.tempdir, 'input')

        with open(input_fn, 'wb') as f:
            input_str = config.string_for_config()
            logger.debug('===== begin qseis input =====\n'
                         '%s===== end qseis input =====' % input_str.decode())
            f.write(input_str)

        program = program_bins['qseis.%s' % config.qseis_version]

        old_wd = os.getcwd()

        os.chdir(self.tempdir)

        interrupted = []

        def signal_handler(signum, frame):
            os.kill(proc.pid, signal.SIGTERM)
            interrupted.append(True)

        original = signal.signal(signal.SIGINT, signal_handler)
        try:
            try:
                proc = Popen(program, stdin=PIPE, stdout=PIPE, stderr=PIPE)

            except OSError:
                os.chdir(old_wd)
                raise QSeisError(
                    '''could not start qseis executable: "%s"
Available fomosto backends and download links to the modelling codes are listed
on

      https://pyrocko.org/docs/current/apps/fomosto/backends.html

''' % program)

            (output_str, error_str) = proc.communicate(b'input\n')

        finally:
            signal.signal(signal.SIGINT, original)

        if interrupted:
            raise KeyboardInterrupt()

        logger.debug('===== begin qseis output =====\n'
                     '%s===== end qseis output =====' % output_str.decode())

        errmess = []
        if proc.returncode != 0:
            errmess.append(
                'qseis had a non-zero exit state: %i' % proc.returncode)

        if error_str:
            logger.warning(
                'qseis emitted something via stderr:\n\n%s'
                % error_str.decode())

            # errmess.append('qseis emitted something via stderr')

        if output_str.lower().find(b'error') != -1:
            errmess.append("the string 'error' appeared in qseis output")

        if errmess:
            self.keep_tmp = True

            os.chdir(old_wd)
            raise QSeisError('''
===== begin qseis input =====
%s===== end qseis input =====
===== begin qseis output =====
%s===== end qseis output =====
===== begin qseis error =====
%s===== end qseis error =====
%s
qseis has been invoked as "%s"
in the directory %s'''.lstrip() % (
                input_str.decode(), output_str.decode(), error_str.decode(),
                '\n'.join(errmess), program, self.tempdir))

        self.qseis_output = output_str
        self.qseis_error = error_str

        os.chdir(old_wd)

    def get_traces(self, which='seis'):

        if which == 'seis':
            fns = self.config.get_output_filenames(self.tempdir)
            components = qseis_components

        elif which == 'gf':
            fns = self.config.get_output_filenames_gf(self.tempdir)
            components = [
                fn+'.t'+c
                for fn in self.config.gf_filenames for c in qseis_components]
        else:
            raise Exception(
                'get_traces: which argument should be "seis" or "gf"')

        traces = []
        distances = self.config.receiver_distances
        azimuths = self.config.receiver_azimuths
        for comp, fn in zip(components, fns):
            if not os.path.exists(fn):
                continue

            data = num.loadtxt(fn, skiprows=1, dtype=float)
            nsamples, ntraces = data.shape
            ntraces -= 1
            vred = self.config.time_reduction_velocity
            deltat = (data[-1, 0] - data[0, 0])/(nsamples-1)

            for ireceiver, distance, azimuth in zip(
                    range(ntraces), distances, azimuths):

                tmin = self.config.time_start
                if vred != 0.0:
                    tmin += distance / vred

                tmin += deltat
                tr = trace.Trace(
                    '', '%04i' % ireceiver, '', comp,
                    tmin=tmin, deltat=deltat, ydata=data[:, ireceiver+1],
                    meta=dict(
                        ireceiver=ireceiver,
                        distance=distance*km,
                        azimuth=azimuth))

                traces.append(tr)

        return traces

    def __del__(self):
        if self.tempdir:
            if not self.keep_tmp:
                shutil.rmtree(self.tempdir)
                self.tempdir = None
            else:
                logger.warning(
                    'not removing temporary directory: %s' % self.tempdir)


def in_array_almost_equal(x, arr, eps):
    return num.any(num.abs(x - arr) < eps)


class QSeisGFBuilder(gf.builder.Builder):
    def __init__(self, store_dir, step, shared, block_size=None, tmp=None,
                 force=False):

        self.store = gf.store.Store(store_dir, 'w')

        ndistances = 100
        if self.store.config.component_scheme == 'elastic10_fd':
            ndistances = 33

        if block_size is None:
            block_size = (1, 1, ndistances)

        if len(self.store.config.ns) == 2:
            block_size = block_size[1:]

        gf.builder.Builder.__init__(
            self, self.store.config, step, block_size=block_size, force=force)

        baseconf = self.store.get_extra('qseis')

        conf = QSeisConfigFull(**baseconf.items())
        conf.earthmodel_1d = self.store.config.earthmodel_1d
        conf.earthmodel_receiver_1d = self.store.config.earthmodel_receiver_1d

        deltat = 1.0/self.gf_config.sample_rate

        if 'time_window_min' not in shared:
            d = self.store.make_timing_params(
                conf.time_region[0], conf.time_region[1],
                force=force)

            if self.store.config.component_scheme == 'elastic10_fd':
                # using reduction velocity is not possible here
                tmax = math.ceil(d['tmax'] / deltat) * deltat
                tmin = math.floor(d['tmin'] / deltat) * deltat
                shared['time_window_min'] = tmax - tmin
                shared['time_start'] = tmin
                shared['time_reduction_velocity'] = 0.0
            else:
                shared['time_window_min'] = d['tlenmax_vred']
                shared['time_start'] = d['tmin_vred']
                shared['time_reduction_velocity'] = d['vred'] / km

        time_window_min = shared['time_window_min']
        conf.time_start = shared['time_start']

        conf.time_reduction_velocity = shared['time_reduction_velocity']

        conf.nsamples = nextpow2(int(round(time_window_min / deltat)) + 1)
        conf.time_window = (conf.nsamples-1)*deltat

        self.qseis_config = conf

        self.tmp = tmp
        if self.tmp is not None:
            util.ensuredir(self.tmp)

    def cleanup(self):
        self.store.close()

    def work_block(self, index):
        if len(self.store.config.ns) == 2:
            (sz, firstx), (sz, lastx), (ns, nx) = \
                self.get_block_extents(index)

            rz = self.store.config.receiver_depth
        else:
            (rz, sz, firstx), (rz, sz, lastx), (nr, ns, nx) = \
                self.get_block_extents(index)

        conf = copy.deepcopy(self.qseis_config)

        logger.info('Starting block %i / %i' %
                    (index+1, self.nblocks))

        conf.source_depth = float(sz/km)
        conf.receiver_depth = float(rz/km)

        component_scheme = self.store.config.component_scheme

        runner = QSeisRunner(tmp=self.tmp)

        dx = self.gf_config.distance_delta

        distances = num.linspace(firstx, firstx + (nx-1)*dx, nx)
        if component_scheme == 'elastic10_fd':

            fd_distances = [
                distances - self.gf_config.fd_distance_delta,
                distances,
                distances + self.gf_config.fd_distance_delta]

            n_fd_distances = distances.size

            distances = num.concatenate(fd_distances)

        distances = distances.tolist()

        # add global max distance, because qseis does some adjustments with
        # this value
        distances.append(self.gf_config.distance_max)

        nreceivers = len(distances)

        mex = (MomentTensor(m=symmat6(1, 1, 1, 0, 0, 0)),
               {'r': (0, +1), 'z': (1, +1)})

        mmt1 = (MomentTensor(m=symmat6(1, 0, 0, 1, 0, 0)),
                {'r': (0, +1), 't': (3, +1), 'z': (5, +1)})
        mmt2 = (MomentTensor(m=symmat6(0, 0, 0, 0, 1, 1)),
                {'r': (1, +1), 't': (4, +1), 'z': (6, +1)})
        mmt3 = (MomentTensor(m=symmat6(0, 0, 1, 0, 0, 0)),
                {'r': (2, +1), 'z': (7, +1)})
        mmt4 = (MomentTensor(m=symmat6(0, 1, 0, 0, 0, 0)),
                {'r': (8, +1), 'z': (9, +1)})

        off = 0
        if component_scheme == 'elastic8':
            off = 8
        elif component_scheme == 'elastic10':
            off = 10

        msf = (None, {
            'fz.tr': (off+0, +1),
            'fh.tr': (off+1, +1),
            'fh.tt': (off+2, -1),
            'fz.tz': (off+3, +1),
            'fh.tz': (off+4, +1)})
        if component_scheme == 'elastic2':
            gfsneeded = (1, 0, 0, 0, 0, 0)
            gfmapping = [mex]

        if component_scheme == 'elastic5':
            gfsneeded = (0, 0, 0, 0, 1, 1)
            gfmapping = [msf]

        elif component_scheme == 'elastic8':
            gfsneeded = (1, 1, 1, 1, 0, 0)
            gfmapping = [mmt1, mmt2, mmt3]

        elif component_scheme in ('elastic10', 'elastic10_fd'):
            gfsneeded = (1, 1, 1, 1, 0, 0)
            gfmapping = [mmt1, mmt2, mmt3, mmt4]

        elif component_scheme == 'elastic13':
            gfsneeded = (1, 1, 1, 1, 1, 1)
            gfmapping = [mmt1, mmt2, mmt3, msf]

        elif component_scheme == 'elastic15':
            gfsneeded = (1, 1, 1, 1, 1, 1)
            gfmapping = [mmt1, mmt2, mmt3, mmt4, msf]

        conf.gf_sw_source_types = gfsneeded
        conf.receiver_distances = [d/km for d in distances]
        conf.receiver_azimuths = [0.0] * nreceivers

        for mt, gfmap in gfmapping:
            if mt:
                m = mt.m()
                f = float
                conf.source_mech = QSeisSourceMechMT(
                    mnn=f(m[0, 0]), mee=f(m[1, 1]), mdd=f(m[2, 2]),
                    mne=f(m[0, 1]), mnd=f(m[0, 2]), med=f(m[1, 2]))
            else:
                conf.source_mech = None

            if any(conf.gf_sw_source_types) or conf.source_mech is not None:
                runner.run(conf)

            if any(c in gfmap for c in qseis_components):
                rawtraces = runner.get_traces('seis')
            else:
                rawtraces = runner.get_traces('gf')

            interrupted = []

            def signal_handler(signum, frame):
                interrupted.append(True)

            original = signal.signal(signal.SIGINT, signal_handler)
            self.store.lock()
            try:
                for tr in rawtraces:
                    if tr.channel not in gfmap:
                        continue

                    ireceiver = tr.meta['ireceiver']
                    if ireceiver == nreceivers - 1:
                        continue

                    if component_scheme != 'elastic10_fd':
                        x = distances[ireceiver]

                    else:
                        x = distances[
                            n_fd_distances + ireceiver % n_fd_distances]
                        ifd = ireceiver // n_fd_distances

                    ig, factor = gfmap[tr.channel]
                    if component_scheme == 'elastic10_fd':
                        ig += ifd*10

                    if len(self.store.config.ns) == 2:
                        args = (sz, x, ig)
                    else:
                        args = (rz, sz, x, ig)

                    if conf.cut:
                        tmin = self.store.t(conf.cut[0], args[:-1])
                        tmax = self.store.t(conf.cut[1], args[:-1])

                        if None in (tmin, tmax):
                            self.warn(
                                'Failed cutting {} traces. ' +
                                'Failed to determine time window')
                            continue

                        tr.chop(tmin, tmax)

                    tmin = tr.tmin
                    tmax = tr.tmax

                    if conf.fade:
                        ta, tb, tc, td = [
                            self.store.t(v, args[:-1]) for v in conf.fade]

                        if None in (ta, tb, tc, td):
                            continue

                        if not (ta <= tb and tb <= tc and tc <= td):
                            raise QSeisError(
                                'invalid fade configuration '
                                '(it should be (ta <= tb <= tc <= td) but '
                                'ta=%g, tb=%g, tc=%g, td=%g)' % (
                                    ta, tb, tc, td))

                        t = tr.get_xdata()
                        fin = num.interp(t, [ta, tb], [0., 1.])
                        fout = num.interp(t, [tc, td], [1., 0.])
                        anti_fin = 1. - fin
                        anti_fout = 1. - fout

                        y = tr.ydata

                        sum_anti_fin = num.sum(anti_fin)
                        sum_anti_fout = num.sum(anti_fout)

                        if sum_anti_fin != 0.0:
                            yin = num.sum(anti_fin*y) / sum_anti_fin
                        else:
                            yin = 0.0

                        if sum_anti_fout != 0.0:
                            yout = num.sum(anti_fout*y) / sum_anti_fout
                        else:
                            yout = 0.0

                        y2 = anti_fin*yin + fin*fout*y + anti_fout*yout

                        if conf.relevel_with_fade_in:
                            y2 -= yin

                        tr.set_ydata(y2)

                    gf_tr = gf.store.GFTrace.from_trace(tr)
                    gf_tr.data *= factor

                    try:
                        self.store.put(args, gf_tr)
                    except gf.store.DuplicateInsert:
                        self.warn('{} insertions_skipped (duplicates)')

            finally:
                self.log_warnings(index+1, logger)
                self.store.unlock()
                signal.signal(signal.SIGINT, original)

            if interrupted:
                raise KeyboardInterrupt()

            conf.gf_sw_source_types = (0, 0, 0, 0, 0, 0)

        logger.info('Done with block %i / %i' %
                    (index+1, self.nblocks))


def init(store_dir, variant, config_params=None):
    if variant is None:
        variant = '2006'

    if variant not in ('2006', '2006a', '2006b'):
        raise gf.store.StoreError('unsupported variant: %s' % variant)

    modelling_code_id = 'qseis.%s' % variant

    qseis = QSeisConfig(qseis_version=variant)
    qseis.time_region = (
        gf.meta.Timing('begin-50'),
        gf.meta.Timing('end+100'))

    qseis.cut = (
        gf.meta.Timing('begin-50'),
        gf.meta.Timing('end+100'))

    qseis.wavelet_duration_samples = 0.001
    qseis.sw_flat_earth_transform = 1

    store_id = os.path.basename(os.path.realpath(store_dir))

    d = dict(
        id=store_id,
        ncomponents=10,
        sample_rate=0.2,
        receiver_depth=0*km,
        source_depth_min=10*km,
        source_depth_max=20*km,
        source_depth_delta=10*km,
        distance_min=100*km,
        distance_max=1000*km,
        distance_delta=10*km,
        earthmodel_1d=cake.load_model().extract(depth_max='cmb'),
        modelling_code_id=modelling_code_id,
        tabulated_phases=[
            gf.meta.TPDef(
                id='begin',
                definition='p,P,p\\,P\\,Pv_(cmb)p'),
            gf.meta.TPDef(
                id='end',
                definition='2.5'),
            gf.meta.TPDef(
                id='P',
                definition='!P'),
            gf.meta.TPDef(
                id='S',
                definition='!S'),
            gf.meta.TPDef(
                id='p',
                definition='!p'),
            gf.meta.TPDef(
                id='s',
                definition='!s')])

    if config_params is not None:
        d.update(config_params)

    config = gf.meta.ConfigTypeA(**d)

    config.validate()
    return gf.store.Store.create_editables(
        store_dir, config=config, extra={'qseis': qseis})


def build(store_dir, force=False, nworkers=None, continue_=False, step=None,
          iblock=None):

    return QSeisGFBuilder.build(
        store_dir, force=force, nworkers=nworkers, continue_=continue_,
        step=step, iblock=iblock)
