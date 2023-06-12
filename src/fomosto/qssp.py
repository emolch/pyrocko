# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num
import logging
import os
import shutil
import glob
import copy
import signal
import math
import time

from tempfile import mkdtemp
from subprocess import Popen, PIPE
from os.path import join as pjoin

from pyrocko import trace, util, cake, gf
from pyrocko.guts import Object, Float, String, Bool, Tuple, Int, List
from pyrocko.moment_tensor import MomentTensor, symmat6

guts_prefix = 'pf'

logger = logging.getLogger('pyrocko.fomosto.qssp')

# how to call the programs
program_bins = {
    'qssp.2010beta': 'fomosto_qssp2010beta',
    'qssp.2010': 'fomosto_qssp2010',
    'qssp.2017': 'fomosto_qssp2017',
    'qssp.2020': 'fomosto_qssp2020',
    'qssp.ppeg2017': 'fomosto_qsspppeg2017',
}


def have_backend(version=None):
    avail = set()
    for version, exe in program_bins.items():
        try:
            p = Popen([exe], stdout=PIPE, stderr=PIPE, stdin=PIPE)
            (stdout, stderr) = p.communicate()
            avail.add(version)

        except OSError:
            pass

    return avail


qssp_components = {
    1: 'ae an az gr sd te tn ue un uz ve vn vz'.split(),
    2: 'ar at ap gr sd tt tp ur ut up vr vt vp'.split(),
    3: '_disp_e _disp_n _disp_z'.split(),
    4: '_gravitation_e _gravitation_n _gravitation_z '
       '_acce_e _acce_n _acce_z'.split(),
    5: '_rota_e _rota_n _rota_z'.split()
}


def str_float_vals(vals):
    return ' '.join(['%.6e' % val for val in vals])


def cake_model_to_config(mod):
    k = 1000.
    srows = []
    for i, row in enumerate(mod.to_scanlines()):
        depth, vp, vs, rho, qp, qs = row
        row = [depth/k, vp/k, vs/k, rho/k, qp, qs]
        srows.append('%i %s' % (i+1, str_float_vals(row)))

    return '\n'.join(srows), len(srows)


class QSSPSource(Object):
    lat = Float.T(default=0.0)
    lon = Float.T(default=0.0)
    depth = Float.T(default=10.0)
    torigin = Float.T(default=0.0)
    trise = Float.T(default=1.0)

    def string_for_config(self):
        return '%(lat)15e %(lon)15e %(depth)15e %(torigin)15e %(trise)15e' \
            % self.__dict__


class QSSPSourceMT(QSSPSource):
    munit = Float.T(default=1.0)
    mrr = Float.T(default=1.0)
    mtt = Float.T(default=1.0)
    mpp = Float.T(default=1.0)
    mrt = Float.T(default=0.0)
    mrp = Float.T(default=0.0)
    mtp = Float.T(default=0.0)

    def string_for_config(self):
        return '%(munit)15e %(mrr)15e %(mtt)15e %(mpp)15e ' \
               '%(mrt)15e %(mrp)15e %(mtp)15e ' \
            % self.__dict__ + QSSPSource.string_for_config(self)


class QSSPSourceDC(QSSPSource):
    moment = Float.T(default=1.0e9)
    strike = Float.T(default=0.0)
    dip = Float.T(default=90.0)
    rake = Float.T(default=0.0)

    def string_for_config(self):
        return '%(moment)15e %(strike)15e %(dip)15e %(rake)15e ' \
            % self.__dict__ + QSSPSource.string_for_config(self)


class QSSPReceiver(Object):
    lat = Float.T(default=10.0)
    lon = Float.T(default=0.0)
    name = String.T(default='')
    tstart = Float.T(default=0.0)
    distance = Float.T(default=0.0)

    def string_for_config(self):
        return "%(lat)15e %(lon)15e '%(name)s' %(tstart)e" % self.__dict__


class QSSPGreen(Object):
    depth = Float.T(default=10.0)
    filename = String.T(default='GF_10km')
    calculate = Bool.T(default=True)

    def string_for_config(self):
        return "%(depth)15e '%(filename)s' %(calculate)i" % self.__dict__


class QSSPConfig(Object):
    qssp_version = String.T(default='2010beta')
    time_region = Tuple.T(2, gf.Timing.T(), default=(
        gf.Timing('-10'), gf.Timing('+890')))

    frequency_max = Float.T(optional=True)
    slowness_max = Float.T(default=0.4)
    antialiasing_factor = Float.T(default=0.1)

    # only available in 2017:
    switch_turning_point_filter = Int.T(default=0)
    max_pene_d1 = Float.T(default=2891.5)
    max_pene_d2 = Float.T(default=6371.0)
    earth_radius = Float.T(default=6371.0)
    switch_free_surf_reflection = Int.T(default=1)

    lowpass_order = Int.T(default=0, optional=True)
    lowpass_corner = Float.T(default=1.0, optional=True)

    bandpass_order = Int.T(default=0, optional=True)
    bandpass_corner_low = Float.T(default=1.0, optional=True)
    bandpass_corner_high = Float.T(default=1.0, optional=True)

    output_slowness_min = Float.T(default=0.0, optional=True)
    output_slowness_max = Float.T(optional=True)

    spheroidal_modes = Bool.T(default=True)
    toroidal_modes = Bool.T(default=True)

    # only available in 2010beta:
    cutoff_harmonic_degree_sd = Int.T(optional=True, default=0)

    cutoff_harmonic_degree_min = Int.T(default=0)
    cutoff_harmonic_degree_max = Int.T(default=25000)

    crit_frequency_sge = Float.T(default=0.0)
    crit_harmonic_degree_sge = Int.T(default=0)

    include_physical_dispersion = Bool.T(default=False)

    source_patch_radius = Float.T(default=0.0)

    cut = Tuple.T(2, gf.Timing.T(), optional=True)

    fade = Tuple.T(4, gf.Timing.T(), optional=True)
    relevel_with_fade_in = Bool.T(default=False)
    nonzero_fade_in = Bool.T(default=False)
    nonzero_fade_out = Bool.T(default=False)

    def items(self):
        return dict(self.T.inamevals(self))


class QSSPConfigFull(QSSPConfig):
    time_window = Float.T(default=900.0)

    receiver_depth = Float.T(default=0.0)
    sampling_interval = Float.T(default=5.0)

    stored_quantity = String.T(default='displacement')
    output_filename = String.T(default='receivers')
    output_format = Int.T(default=1)
    output_time_window = Float.T(optional=True)

    gf_directory = String.T(default='qssp_green')
    greens_functions = List.T(QSSPGreen.T())

    sources = List.T(QSSPSource.T())
    receivers = List.T(QSSPReceiver.T())

    earthmodel_1d = gf.meta.Earthmodel1D.T(optional=True)

    @staticmethod
    def example():
        conf = QSSPConfigFull()
        conf.sources.append(QSSPSourceMT())
        lats = [20.]
        conf.receivers.extend(QSSPReceiver(lat=lat) for lat in lats)
        conf.greens_functions.append(QSSPGreen())
        return conf

    @property
    def components(self):
        if self.qssp_version in ('2017', '2020'):
            if self.stored_quantity == 'rotation_displacement':
                fmt = 5
            else:
                fmt = 3
        elif self.qssp_version == 'ppeg2017':
            fmt = 4
        else:
            fmt = self.output_format

        return qssp_components[fmt]

    def get_output_filenames(self, rundir):
        if self.qssp_version in ('2017', '2020', 'ppeg2017'):
            return [
                pjoin(rundir, self.output_filename + c + '.dat')
                for c in self.components]
        else:
            return [
                pjoin(rundir, self.output_filename + '.' + c)
                for c in self.components]

    def ensure_gf_directory(self):
        util.ensuredir(self.gf_directory)

    def string_for_config(self):

        def aggregate(xx):
            return len(xx), '\n'.join(x.string_for_config() for x in xx)

        assert len(self.greens_functions) > 0
        assert len(self.sources) > 0
        assert len(self.receivers) > 0

        d = self.__dict__.copy()

        if self.output_time_window is None:
            d['output_time_window'] = self.time_window

        if self.output_slowness_max is None:
            d['output_slowness_max'] = self.slowness_max

        if self.frequency_max is None:
            d['frequency_max'] = 0.5/self.sampling_interval

        d['gf_directory'] = os.path.abspath(self.gf_directory) + '/'

        d['n_receiver_lines'], d['receiver_lines'] = aggregate(self.receivers)
        d['n_source_lines'], d['source_lines'] = aggregate(self.sources)
        d['n_gf_lines'], d['gf_lines'] = aggregate(self.greens_functions)
        model_str, nlines = cake_model_to_config(self.earthmodel_1d)
        d['n_model_lines'] = nlines
        d['model_lines'] = model_str
        if self.stored_quantity == 'rotation_displacement':
            d['output_rotation'] = 1
            d['output_displacement'] = 0
        else:
            d['output_displacement'] = 1
            d['output_rotation'] = 0

        if len(self.sources) == 0 or isinstance(self.sources[0], QSSPSourceMT):
            d['point_source_type'] = 1
        else:
            d['point_source_type'] = 2

        if self.qssp_version == '2010beta':
            d['scutoff_doc'] = '''
#    (SH waves), and cutoff harmonic degree for static deformation
'''.strip()

            d['scutoff'] = '%i' % self.cutoff_harmonic_degree_sd

            d['sfilter_doc'] = '''
# 3. selection of order of Butterworth low-pass filter (if <= 0, then no
#    filtering), corner frequency (smaller than the cut-off frequency defined
#    above)
'''.strip()

            if self.bandpass_order != 0:
                raise QSSPError(
                    'this version of qssp does not support bandpass '
                    'settings, use lowpass instead')

            d['sfilter'] = '%i %f' % (
                self.lowpass_order,
                self.lowpass_corner)

        elif self.qssp_version in ('2010', '2017', '2020', 'ppeg2017'):
            d['scutoff_doc'] = '''
#    (SH waves), minimum and maximum cutoff harmonic degrees
#    Note: if the near-field static displacement is desired, the minimum
#          cutoff harmonic degree should not be smaller than, e.g., 2000.
'''.strip()

            d['scutoff'] = '%i %i' % (
                self.cutoff_harmonic_degree_min,
                self.cutoff_harmonic_degree_max)

            d['sfilter_doc'] = '''
# 3. selection of order of Butterworth bandpass filter (if <= 0, then no
#    filtering), lower and upper corner frequencies (smaller than the cut-off
#    frequency defined above)
'''.strip()

            if self.lowpass_order != 0:
                raise QSSPError(
                    'this version of qssp does not support lowpass settings, '
                    'use bandpass instead')

            d['sfilter'] = '%i %f %f' % (
                self.bandpass_order,
                self.bandpass_corner_low,
                self.bandpass_corner_high)
        if self.qssp_version in ('2017', '2020', 'ppeg2017'):
            template = '''# autogenerated QSSP input by qssp.py
#
# This is the input file of FORTRAN77 program "qssp2017" for calculating
# synthetic seismograms of a self-gravitating, spherically symmetric,
# isotropic and viscoelastic earth.
#
# by
# Rongjiang Wang <wang@gfz-potsdam.de>
# Helmholtz-Centre Potsdam
# GFZ German Reseach Centre for Geosciences
# Telegrafenberg, D-14473 Potsdam, Germany
#
# Last modified: Potsdam, October 2017
#
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
# If not specified, SI Unit System is used overall!
#
# Coordinate systems:
# spherical (r,t,p) with r = radial,
#                        t = co-latitude,
#                        p = east longitude.
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
#
#	UNIFORM RECEIVER DEPTH
#	======================
# 1. uniform receiver depth [km]
#-------------------------------------------------------------------------------------------
    %(receiver_depth)e
#-------------------------------------------------------------------------------------------
#
#   SPACE-TIME SAMPLING PARAMETERS
#	=========================
# 1. time window [sec], sampling interval [sec]
# 2. max. frequency [Hz] of Green's functions
# 3. max. slowness [s/km] of Green's functions
#    Note: if the near-field static displacement is desired, the maximum slowness should not
#          be smaller than the S wave slowness in the receiver layer
# 4. anti-aliasing factor (> 0 & < 1), if it is <= 0 or >= 1/e (~ 0.4), then
#    default value of 1/e is used (e.g., 0.1 = alias phases will be suppressed
#    to 10%% of their original amplitude)
# 5. switch (1/0 = yes/no) of turning-point filter, the range (d1, d2) of max. penetration
#    depth [km] (d1 is meaningless if it is smaller than the receiver/source depth, and
#    d2 is meaningless if it is equal to or larger than the earth radius)
#
#    Note: The turning-point filter (Line 5) works only for the extended QSSP code (e.g.,
#          qssp2016). if this filter is selected, all phases with the turning point
#          shallower than d1 or deeper than d2 will be filtered.
#
# 6. Earth radius [km], switch of free-surface-reflection filter (1/0 = with/without free
#    surface reflection)
#
#    Note: The free-surface-reflection filter (Line 6) works only for the extended QSSP
#          code (e.g., qssp2016). if this filter is selected, all phases with the turning
#          point shallower than d1 or deeper than d2 will be filtered.
#-------------------------------------------------------------------------------------------
    %(time_window)e   %(sampling_interval)e
    %(frequency_max)e
    %(slowness_max)e
    %(antialiasing_factor)e
    %(switch_turning_point_filter)i   %(max_pene_d1)e   %(max_pene_d2)e
    %(earth_radius)e   %(switch_free_surf_reflection)i
#-------------------------------------------------------------------------------------------
#
#	SELF-GRAVITATING EFFECT
#	=======================
# 1. the critical frequency [Hz] and the critical harmonic degree, below which
#    the self-gravitating effect should be included
#-------------------------------------------------------------------------------------------
    %(crit_frequency_sge)e     %(crit_harmonic_degree_sge)i
#-------------------------------------------------------------------------------------------
#
#	WAVE TYPES
#	==========
# 1. selection (1/0 = yes/no) of speroidal modes (P-SV waves), selection of toroidal modes
%(scutoff_doc)s
#-------------------------------------------------------------------------------------------
    %(spheroidal_modes)i     %(toroidal_modes)i    %(scutoff)s
#-------------------------------------------------------------------------------------------
#	GREEN'S FUNCTION FILES
#	======================
# 1. number of discrete source depths, estimated radius of each source patch [km] and
#    directory for Green's functions
# 2. list of the source depths [km], the respective file names of the Green's
#    functions (spectra) and the switch number (0/1) (0 = do not calculate
#    this Green's function because it exists already, 1 = calculate or update
#    this Green's function. Note: update is required if any of the above
#    parameters is changed)
#-------------------------------------------------------------------------------------------
   %(n_gf_lines)i   %(source_patch_radius)e   '%(gf_directory)s'
   %(gf_lines)s
#--------------------------------------------------------------------------------------------------------
#
#   MULTI-EVENT SOURCE PARAMETERS
#   =============================
# 1. number of discrete point sources and selection of the source data format
#    (1, 2 or 3)
# 2. list of the multi-event sources
#
#    Format 1 (full moment tensor):
#    Unit     Mrr  Mtt  Mpp  Mrt  Mrp  Mtp  Lat   Lon   Depth  T_origin T_rise
#    [Nm]                                   [deg] [deg] [km]   [sec]    [sec]
#
#    Format 2 (double couple):
#    Unit   Strike    Dip       Rake      Lat   Lon   Depth  T_origin T_rise
#    [Nm]   [deg]     [deg]     [deg]     [deg] [deg] [km]   [sec]    [sec]
#
#    Format 3 (single force):
#    Unit      Feast    Fnorth  Fvertical    Lat   Lon   Depth  T_origin T_rise
#    [N]                                     [deg] [deg] [km]   [sec]    [sec]
#
#    Note: for each point source, the default moment (force) rate time function is used, defined by a
#          squared half-period (T_rise) sinusoid starting at T_origin.
#-----------------------------------------------------------------------------------
  %(n_source_lines)i     %(point_source_type)i
%(source_lines)s
#--------------------------------------------------------------------------------------------------------
#
#   RECEIVER PARAMETERS
#   ===================
# 1. select output observables (1/0 = yes/no)
#    Note: the gravity change defined here is space based, i.e., the effect due to free-air
#          gradient and inertial are not included. the vertical component is positve upwards.
# 2. output file name
# 3. output time window [sec] (<= Green's function time window)
%(sfilter_doc)s
# 5. lower and upper slowness cut-off [s/km] (slowness band-pass filter)
# 6. number of receiver
# 7. list of the station parameters
#    Format:
#    Lat     Lon    Name     Time_reduction
#    [deg]   [deg]           [sec]
#    (Note: Time_reduction = start time of the time window)
#---------------------------------------------------------------------------------------------------------------
# disp | velo | acce | strain | strain_rate | stress | stress_rate | rotation | rot_rate | gravitation | gravity
#---------------------------------------------------------------------------------------------------------------
# 1      1      1      1        1             1        1             1          1          1             1
  %(output_displacement)i      0      0      0        0             0        0             %(output_rotation)i          0          0             0

  '%(output_filename)s'
  %(output_time_window)e
  %(sfilter)s
  %(output_slowness_min)e    %(output_slowness_max)e
  %(n_receiver_lines)i
%(receiver_lines)s
#-------------------------------------------------------------------------------------------
#
#	                LAYERED EARTH MODEL (IASP91)
#                   ============================
# 1. number of data lines of the layered model and selection for including
#    the physical dispersion according Kamamori & Anderson (1977)
#-------------------------------------------------------------------------------------------
    %(n_model_lines)i    %(include_physical_dispersion)i
#--------------------------------------------------------------------------------------------------------
#
#   MODEL PARAMETERS
#   ================
# no depth[km] vp[km/s] vs[km/s] ro[g/cm^3]      qp     qs
#-------------------------------------------------------------------------------------------
%(model_lines)s
#---------------------------------end of all inputs-----------------------------------------
'''  # noqa
        else:

            template = '''# autogenerated QSSP input by qssp.py
#
# This is the input file of FORTRAN77 program "qssp2010" for calculating
# synthetic seismograms of a self-gravitating, spherically symmetric,
# isotropic and viscoelastic earth.
#
# by
# Rongjiang  Wang <wang@gfz-potsdam.de>
# Helmholtz-Centre Potsdam
# GFZ German Reseach Centre for Geosciences
# Telegrafenberg, D-14473 Potsdam, Germany
#
# Last modified: Potsdam, July, 2010
#
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
# If not specified, SI Unit System is used overall!
#
# Coordinate systems:
# spherical (r,t,p) with r = radial,
#                        t = co-latitude,
#                        p = east longitude.
# = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = = =
#
#	UNIFORM RECEIVER DEPTH
#	======================
# 1. uniform receiver depth [km]
#-------------------------------------------------------------------------------------------
    %(receiver_depth)e
#-------------------------------------------------------------------------------------------
#
#	TIME (FREQUENCY) SAMPLING
#	=========================
# 1. time window [sec], sampling interval [sec]
# 2. max. frequency [Hz] of Green's functions
# 3. max. slowness [s/km] of Green's functions
#    Note: if the near-field static displacement is desired, the maximum slowness should not
#          be smaller than the S wave slowness in the receiver layer
# 4. anti-aliasing factor (> 0 & < 1), if it is <= 0 or >= 1/e (~ 0.4), then
#    default value of 1/e is used (e.g., 0.1 = alias phases will be suppressed
#    to 10%% of their original amplitude)
#
#    Note: The computation effort increases linearly the time window and
#          quadratically with the cut-off frequency.
#-------------------------------------------------------------------------------------------
    %(time_window)e   %(sampling_interval)e
    %(frequency_max)e
    %(slowness_max)e
    %(antialiasing_factor)e
#-------------------------------------------------------------------------------------------
#
#	SELF-GRAVITATING EFFECT
#	=======================
# 1. the critical frequency [Hz] and the critical harmonic degree, below which
#    the self-gravitating effect should be included
#-------------------------------------------------------------------------------------------
    %(crit_frequency_sge)e     %(crit_harmonic_degree_sge)i
#-------------------------------------------------------------------------------------------
#
#	WAVE TYPES
#	==========
# 1. selection (1/0 = yes/no) of speroidal modes (P-SV waves), selection of toroidal modes
%(scutoff_doc)s
#-------------------------------------------------------------------------------------------
    %(spheroidal_modes)i     %(toroidal_modes)i    %(scutoff)s
#-------------------------------------------------------------------------------------------
#	GREEN'S FUNCTION FILES
#	======================
# 1. number of discrete source depths, estimated radius of each source patch [km] and
#    directory for Green's functions
# 2. list of the source depths [km], the respective file names of the Green's
#    functions (spectra) and the switch number (0/1) (0 = do not calculate
#    this Green's function because it exists already, 1 = calculate or update
#    this Green's function. Note: update is required if any of the above
#    parameters is changed)
#-------------------------------------------------------------------------------------------
   %(n_gf_lines)i   %(source_patch_radius)e   '%(gf_directory)s'
   %(gf_lines)s
#-------------------------------------------------------------------------------------------
#
#	MULTI-EVENT SOURCE PARAMETERS
#	=============================
# 1. number of discrete point sources and selection of the source data format
#    (1 or 2)
# 2. list of the multi-event sources
#    Format 1:
#    M-Unit   Mrr  Mtt  Mpp  Mrt  Mrp  Mtp  Lat   Lon   Depth  T_origin T_rise
#    [Nm]                                   [deg] [deg] [km]   [sec]    [sec]
#    Format 2:
#    Moment   Strike    Dip       Rake      Lat   Lon   Depth  T_origin T_rise
#    [Nm]     [deg]     [deg]     [deg]     [deg] [deg] [km]   [sec]    [sec]
#-------------------------------------------------------------------------------------------
  %(n_source_lines)i     %(point_source_type)i
%(source_lines)s
#-------------------------------------------------------------------------------------------
#
#	RECEIVER PARAMETERS
#	===================
# 1. output file name and and selection of output format:
#       1 = cartesian: vertical(z)/north(n)/east(e);
#       2 = spherical: radial(r)/theta(t)/phi(p)
#      (Note: if output format 2 is selected, the epicenter (T_origin = 0)
# 2. output time window [sec] (<= Green's function time window)
%(sfilter_doc)s
# 4. lower and upper slowness cut-off [s/km] (slowness band-pass filter)
# 5. number of receiver
# 6. list of the station parameters
#    Format:
#    Lat     Lon    Name     Time_reduction
#    [deg]   [deg]           [sec]
#    (Note: Time_reduction = start time of the time window)
#-------------------------------------------------------------------------------------------
  '%(output_filename)s'  %(output_format)i
  %(output_time_window)e
  %(sfilter)s
  %(output_slowness_min)e    %(output_slowness_max)e
  %(n_receiver_lines)i
%(receiver_lines)s
#-------------------------------------------------------------------------------------------
#
#	                LAYERED EARTH MODEL (IASP91)
#                   ============================
# 1. number of data lines of the layered model and selection for including
#    the physical dispersion according Kamamori & Anderson (1977)
#-------------------------------------------------------------------------------------------
    %(n_model_lines)i    %(include_physical_dispersion)i
#-------------------------------------------------------------------------------------------
#
#	MULTILAYERED MODEL PARAMETERS (source site)
#	===========================================
# no depth[km] vp[km/s] vs[km/s] ro[g/cm^3]      qp     qs
#-------------------------------------------------------------------------------------------
%(model_lines)s
#---------------------------------end of all inputs-----------------------------------------
'''  # noqa

        return (template % d).encode('ascii')


class QSSPError(gf.store.StoreError):
    pass


class Interrupted(gf.store.StoreError):
    def __str__(self):
        return 'Interrupted.'


class QSSPRunner(object):

    def __init__(self, tmp=None, keep_tmp=False):

        self.tempdir = mkdtemp(prefix='qssprun-', dir=tmp)
        self.keep_tmp = keep_tmp
        self.config = None

    def run(self, config):
        self.config = config

        input_fn = pjoin(self.tempdir, 'input')

        with open(input_fn, 'wb') as f:
            input_str = config.string_for_config()
            logger.debug('===== begin qssp input =====\n'
                         '%s===== end qssp input =====' % input_str.decode())
            f.write(input_str)

        program = program_bins['qssp.%s' % config.qssp_version]

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
                raise QSSPError(
                    '''could not start qssp executable: "%s"
Available fomosto backends and download links to the modelling codes are listed
on

      https://pyrocko.org/docs/current/apps/fomosto/backends.html

''' % program)

            (output_str, error_str) = proc.communicate(b'input\n')

        finally:
            signal.signal(signal.SIGINT, original)

        if interrupted:
            raise KeyboardInterrupt()

        logger.debug('===== begin qssp output =====\n'
                     '%s===== end qssp output =====' % output_str.decode())

        errmess = []
        if proc.returncode != 0:
            errmess.append(
                'qssp had a non-zero exit state: %i' % proc.returncode)
        if error_str:

            logger.warning(
                'qssp emitted something via stderr: \n\n%s'
                % error_str.decode())

            # errmess.append('qssp emitted something via stderr')
        if output_str.lower().find(b'error') != -1:
            errmess.append("the string 'error' appeared in qssp output")

        if errmess:
            os.chdir(old_wd)
            raise QSSPError('''
===== begin qssp input =====
%s===== end qssp input =====
===== begin qssp output =====
%s===== end qssp output =====
===== begin qssp error =====
%s===== end qssp error =====
%s
qssp has been invoked as "%s"'''.lstrip() % (
                input_str.decode(),
                output_str.decode(),
                error_str.decode(),
                '\n'.join(errmess),
                program))

        self.qssp_output = output_str
        self.qssp_error = error_str

        os.chdir(old_wd)

    def get_traces(self):

        fns = self.config.get_output_filenames(self.tempdir)
        traces = {}
        for comp, fn in zip(self.config.components, fns):
            data = num.loadtxt(fn, skiprows=1, dtype=float)
            nsamples, ntraces = data.shape
            ntraces -= 1
            deltat = (data[-1, 0] - data[0, 0])/(nsamples-1)
            toffset = data[0, 0]
            for itrace in range(ntraces):
                rec = self.config.receivers[itrace]
                tmin = rec.tstart + toffset
                tr = trace.Trace(
                    '', '%04i' % itrace, '', comp,
                    tmin=tmin, deltat=deltat, ydata=data[:, itrace+1],
                    meta=dict(distance=rec.distance))

                traces[itrace, comp] = tr

        if self.config.qssp_version == 'ppeg2017':
            for itrace in range(ntraces):
                for c in 'nez':
                    tr_accel = traces[itrace, '_acce_' + c]
                    tr_gravi = traces[itrace, '_gravitation_' + c]
                    tr_ag = tr_accel.copy()
                    tr_ag.ydata -= tr_gravi.ydata
                    tr_ag.set_codes(channel='ag_' + c)
                    tr_ag.meta = tr_accel.meta
                    traces[itrace, 'ag_' + c] = tr_ag

        traces = list(traces.values())
        traces.sort(key=lambda tr: tr.nslc_id)
        return traces

    def __del__(self):
        if self.tempdir:
            if not self.keep_tmp:
                shutil.rmtree(self.tempdir)
                self.tempdir = None
            else:
                logger.warning(
                    'not removing temporary directory: %s' % self.tempdir)


class QSSPGFBuilder(gf.builder.Builder):
    nsteps = 2

    def __init__(self, store_dir, step, shared, block_size=None, tmp=None,
                 force=False):

        self.store = gf.store.Store(store_dir, 'w')
        baseconf = self.store.get_extra('qssp')
        if baseconf.qssp_version in ('2017', '2020'):
            if self.store.config.component_scheme == 'rotational8':
                self.gfmapping = [
                    (MomentTensor(m=symmat6(1, 0, 0, 1, 0, 0)),
                     {'_rota_n': (0, -1), '_rota_e': (2, -1),
                      '_rota_z': (5, -1)}),
                    (MomentTensor(m=symmat6(0, 0, 0, 0, 1, 1)),
                     {'_rota_n': (1, -1), '_rota_e': (3, -1),
                      '_rota_z': (6, -1)}),
                    (MomentTensor(m=symmat6(0, 0, 1, 0, 0, 0)),
                     {'_rota_e': (4, -1)}),
                    (MomentTensor(m=symmat6(0, 1, 0, 0, 0, 0)),
                     {'_rota_e': (7, -1)}),
                ]
            elif self.store.config.component_scheme == 'elastic10':
                self.gfmapping = [
                    (MomentTensor(m=symmat6(1, 0, 0, 1, 0, 0)),
                     {'_disp_n': (0, -1), '_disp_e': (3, -1),
                      '_disp_z': (5, -1)}),
                    (MomentTensor(m=symmat6(0, 0, 0, 0, 1, 1)),
                     {'_disp_n': (1, -1), '_disp_e': (4, -1),
                      '_disp_z': (6, -1)}),
                    (MomentTensor(m=symmat6(0, 0, 1, 0, 0, 0)),
                     {'_disp_n': (2, -1), '_disp_z': (7, -1)}),
                    (MomentTensor(m=symmat6(0, 1, 0, 0, 0, 0)),
                     {'_disp_n': (8, -1), '_disp_z': (9, -1)}),
                ]
            elif self.store.config.component_scheme == 'elastic8':
                self.gfmapping = [
                    (MomentTensor(m=symmat6(1, 0, 0, 1, 0, 0)),
                     {'_disp_n': (0, -1), '_disp_e': (3, -1),
                      '_disp_z': (5, -1)}),
                    (MomentTensor(m=symmat6(0, 0, 0, 0, 1, 1)),
                     {'_disp_n': (1, -1), '_disp_e': (4, -1),
                      '_disp_z': (6, -1)}),
                    (MomentTensor(m=symmat6(0, 0, 1, 0, 0, 0)),
                     {'_disp_n': (2, -1), '_disp_z': (7, -1)}),
                ]

        elif baseconf.qssp_version == 'ppeg2017':
            self.gfmapping = [
                (MomentTensor(m=symmat6(1, 0, 0, 1, 0, 0)),
                 {'ag_n': (0, -1), 'ag_e': (3, -1), 'ag_z': (5, -1)}),
                (MomentTensor(m=symmat6(0, 0, 0, 0, 1, 1)),
                 {'ag_n': (1, -1), 'ag_e': (4, -1), 'ag_z': (6, -1)}),
                (MomentTensor(m=symmat6(0, 0, 1, 0, 0, 0)),
                 {'ag_n': (2, -1), 'ag_z': (7, -1)}),
                (MomentTensor(m=symmat6(0, 1, 0, 0, 0, 0)),
                 {'ag_n': (8, -1), 'ag_z': (9, -1)}),
            ]
        else:
            self.gfmapping = [
                (MomentTensor(m=symmat6(1, 0, 0, 1, 0, 0)),
                 {'un': (0, -1), 'ue': (3, -1), 'uz': (5, -1)}),
                (MomentTensor(m=symmat6(0, 0, 0, 0, 1, 1)),
                 {'un': (1, -1), 'ue': (4, -1), 'uz': (6, -1)}),
                (MomentTensor(m=symmat6(0, 0, 1, 0, 0, 0)),
                 {'un': (2, -1), 'uz': (7, -1)}),
                (MomentTensor(m=symmat6(0, 1, 0, 0, 0, 0)),
                 {'un': (8, -1), 'uz': (9, -1)}),
            ]

        if step == 0:
            block_size = (1, 1, self.store.config.ndistances)
        else:
            if block_size is None:
                block_size = (1, 1, 51)

        if len(self.store.config.ns) == 2:
            block_size = block_size[1:]

        gf.builder.Builder.__init__(
            self, self.store.config, step, block_size=block_size, force=force)

        conf = QSSPConfigFull(**baseconf.items())
        conf.gf_directory = pjoin(store_dir, 'qssp_green')
        conf.earthmodel_1d = self.store.config.earthmodel_1d
        deltat = self.store.config.deltat
        if 'time_window' not in shared:
            d = self.store.make_timing_params(
                conf.time_region[0], conf.time_region[1],
                force=force)

            tmax = math.ceil(d['tmax'] / deltat) * deltat
            tmin = math.floor(d['tmin'] / deltat) * deltat

            shared['time_window'] = tmax - tmin
            shared['tstart'] = tmin

        self.tstart = shared['tstart']
        conf.time_window = shared['time_window']

        self.tmp = tmp
        if self.tmp is not None:
            util.ensuredir(self.tmp)

        util.ensuredir(conf.gf_directory)

        self.qssp_config = conf

    def cleanup(self):
        self.store.close()

    def work_block(self, iblock):
        if len(self.store.config.ns) == 2:
            (sz, firstx), (sz, lastx), (ns, nx) = \
                self.get_block_extents(iblock)

            rz = self.store.config.receiver_depth
        else:
            (rz, sz, firstx), (rz, sz, lastx), (nr, ns, nx) = \
                self.get_block_extents(iblock)

        gf_filename = 'GF_%gkm_%gkm' % (sz/km, rz/km)

        conf = copy.deepcopy(self.qssp_config)

        gf_path = os.path.join(conf.gf_directory, '?_' + gf_filename)

        if self.step == 0 and len(glob.glob(gf_path)) > 0:
            logger.info(
                'Skipping step %i / %i, block %i / %i (GF already exists)'
                % (self.step+1, self.nsteps, iblock+1, self.nblocks))

            return

        logger.info(
            'Starting step %i / %i, block %i / %i' %
            (self.step+1, self.nsteps, iblock+1, self.nblocks))

        tbeg = time.time()

        runner = QSSPRunner(tmp=self.tmp)

        conf.receiver_depth = rz/km

        component_scheme = self.store.config.component_scheme
        stored_quantity = self.store.config.effective_stored_quantity

        if (component_scheme, stored_quantity) not in [
                ('rotational8', 'rotation_displacement'),
                ('elastic10', 'displacement'),
                ('elastic8', 'displacement')]:

            raise QSSPError(
                'componentent_scheme "%s" is inconsistent with '
                'stored_quantity "%s"' % (component_scheme, stored_quantity))

        conf.stored_quantity = stored_quantity
        conf.sampling_interval = 1.0 / self.gf_config.sample_rate
        dx = self.gf_config.distance_delta

        if self.step == 0:
            distances = [firstx]
        else:
            distances = num.linspace(firstx, firstx + (nx-1)*dx, nx)

        conf.receivers = [
            QSSPReceiver(
                lat=90-d*cake.m2d,
                lon=180.,
                tstart=self.tstart,
                distance=d)

            for d in distances]

        if self.step == 0:
            gf_filename = 'TEMP' + gf_filename[2:]

        gfs = [QSSPGreen(
            filename=gf_filename,
            depth=sz/km,
            calculate=(self.step == 0))]

        conf.greens_functions = gfs

        trise = 0.001*conf.sampling_interval  # make it short (delta impulse)

        if self.step == 0:
            conf.sources = [QSSPSourceMT(
                lat=90-0.001*dx*cake.m2d,
                lon=0.0,
                trise=trise,
                torigin=0.0)]

            runner.run(conf)
            gf_path = os.path.join(conf.gf_directory, '?_' + gf_filename)
            for s in glob.glob(gf_path):
                d = s.replace('TEMP_', 'GF_')
                os.rename(s, d)

        else:
            for mt, gfmap in self.gfmapping:
                m = mt.m_up_south_east()

                conf.sources = [QSSPSourceMT(
                    lat=90-0.001*dx*cake.m2d,
                    lon=0.0,
                    mrr=m[0, 0], mtt=m[1, 1], mpp=m[2, 2],
                    mrt=m[0, 1], mrp=m[0, 2], mtp=m[1, 2],
                    trise=trise,
                    torigin=0.0)]

                runner.run(conf)

                rawtraces = runner.get_traces()

                interrupted = []

                def signal_handler(signum, frame):
                    interrupted.append(True)

                original = signal.signal(signal.SIGINT, signal_handler)
                self.store.lock()
                duplicate_inserts = 0
                try:
                    for itr, tr in enumerate(rawtraces):
                        if tr.channel in gfmap:

                            x = tr.meta['distance']
                            ig, factor = gfmap[tr.channel]

                            if len(self.store.config.ns) == 2:
                                args = (sz, x, ig)
                            else:
                                args = (rz, sz, x, ig)

                            if conf.cut:
                                tmin = self.store.t(conf.cut[0], args[:-1])
                                tmax = self.store.t(conf.cut[1], args[:-1])
                                if None in (tmin, tmax):
                                    continue

                                tr.chop(tmin, tmax)

                            tmin = tr.tmin
                            tmax = tr.tmax

                            if conf.fade:
                                ta, tb, tc, td = [
                                    self.store.t(v, args[:-1])
                                    for v in conf.fade]

                                if None in (ta, tb, tc, td):
                                    continue

                                if not (ta <= tb and tb <= tc and tc <= td):
                                    raise QSSPError(
                                        'invalid fade configuration')

                                t = tr.get_xdata()
                                fin = num.interp(t, [ta, tb], [0., 1.])
                                fout = num.interp(t, [tc, td], [1., 0.])
                                anti_fin = 1. - fin
                                anti_fout = 1. - fout

                                y = tr.ydata

                                sum_anti_fin = num.sum(anti_fin)
                                sum_anti_fout = num.sum(anti_fout)

                                if conf.nonzero_fade_in \
                                        and sum_anti_fin != 0.0:
                                    yin = num.sum(anti_fin*y) / sum_anti_fin
                                else:
                                    yin = 0.0

                                if conf.nonzero_fade_out \
                                        and sum_anti_fout != 0.0:
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
                                duplicate_inserts += 1

                finally:
                    if duplicate_inserts:
                        logger.warning(
                            '%i insertions skipped (duplicates)'
                            % duplicate_inserts)

                    self.store.unlock()
                    signal.signal(signal.SIGINT, original)

                if interrupted:
                    raise KeyboardInterrupt()

        tend = time.time()
        logger.info(
            'Done with step %i / %i, block %i / %i, wallclock time: %.0f s' % (
                self.step+1, self.nsteps, iblock+1, self.nblocks, tend-tbeg))


km = 1000.


def init(store_dir, variant, config_params=None):
    if variant is None:
        variant = '2010beta'

    if ('qssp.' + variant) not in program_bins:
        raise gf.store.StoreError('unsupported qssp variant: %s' % variant)

    qssp = QSSPConfig(qssp_version=variant)
    if variant != 'ppeg2017':
        qssp.time_region = (
            gf.Timing('begin-50'),
            gf.Timing('end+100'))

        qssp.cut = (
            gf.Timing('begin-50'),
            gf.Timing('end+100'))

    else:  # variant == 'ppeg2017':
        qssp.frequency_max = 0.5
        qssp.time_region = [
            gf.Timing('-100'), gf.Timing('{stored:begin}+100')]
        qssp.cut = [
            gf.Timing('-100'), gf.Timing('{stored:begin}+100')]
        qssp.antialiasing_factor = 1.0e-10
        qssp.toroidal_modes = False
        qssp.cutoff_harmonic_degree_min = 2500
        qssp.cutoff_harmonic_degree_max = 2500
        qssp.crit_frequency_sge = 5.0
        qssp.crit_harmonic_degree_sge = 50000
        qssp.source_patch_radius = 10.0
        qssp.bandpass_order = 6
        qssp.bandpass_corner_low = 0.0
        qssp.bandpass_corner_high = 0.125

    store_id = os.path.basename(os.path.realpath(store_dir))
    if variant == 'ppeg2017':
        quantity = 'acceleration'
    else:
        quantity = None

    if variant == 'ppeg2017':
        sample_rate = 4.0
    else:
        sample_rate = 0.2

    d = dict(
        id=store_id,
        ncomponents=10,
        component_scheme='elastic10',
        stored_quantity=quantity,
        sample_rate=sample_rate,
        receiver_depth=0*km,
        source_depth_min=10*km,
        source_depth_max=20*km,
        source_depth_delta=10*km,
        distance_min=100*km,
        distance_max=1000*km,
        distance_delta=10*km,
        earthmodel_1d=cake.load_model(),
        modelling_code_id='qssp',
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
        store_dir,
        config=config,
        extra={'qssp': qssp})


def build(
        store_dir,
        force=False,
        nworkers=None,
        continue_=False,
        step=None,
        iblock=None):

    return QSSPGFBuilder.build(
        store_dir, force=force, nworkers=nworkers, continue_=continue_,
        step=step, iblock=iblock)


def get_conf(
        store_dir,
        force=False,
        nworkers=None,
        continue_=False,
        step=None,
        iblock=None):

    return QSSPGFBuilder.get_conf()
