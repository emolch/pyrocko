# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import logging
import os
import shutil
from tempfile import mkdtemp
from subprocess import Popen, PIPE
from os.path import join as pjoin

import numpy as num

from pyrocko.guts import Object, Float, Int, List, String
from pyrocko.guts_array import Array
from pyrocko import trace, util, gf

guts_prefix = 'pf'

logger = logging.getLogger('pyrocko.fomosto.poel')

# how to call the programs
program_bins = {
    'poel': 'poel',
}


def have_backend():
    for cmd in [[exe] for exe in program_bins.values()]:
        try:
            p = Popen(cmd, stdout=PIPE, stderr=PIPE, stdin=PIPE)
            (stdout, stderr) = p.communicate()

        except OSError:
            return False

    return True


poel_components = 'uz ur ezz err ett ezr tlt pp dvz dvr'.split()


def str_float_vals(vals):
    return ' '.join(['%e' % val for val in vals])


def str_int_vals(vals):
    return ' '.join(['%i' % val for val in vals])


def str_str_vals(vals):
    return ' '.join(["'%s'" % val for val in vals])


def str_complex_vals(vals):
    return ', '.join(['(%e, %e)' % (val.real, val.imag) for val in vals])


class PoelSourceFunction(Object):
    data = Array.T(shape=(None, 2), dtype=float)

    def string_for_config(self):
        return '\n'.join([
            '%i %s' % (i+1, str_float_vals(row))
            for (i, row) in enumerate(self.data)])


class PoelModel(Object):
    data = Array.T(shape=(None, 6), dtype=float)

    def string_for_config(self):
        srows = []
        for i, row in enumerate(self.data):
            srows.append('%i %s' % (i+1, str_float_vals(row)))

        return '\n'.join(srows)

    def get_nlines(self):
        return self.data.shape[0]


class PoelConfig(Object):
    s_radius = Float.T(default=0.0)
    s_type = Int.T(default=0)
    source_function_p = Float.T(default=1.0)
    source_function_i = PoelSourceFunction.T(
        default=PoelSourceFunction.D(
            data=num.array(
                [[0., 0.], [10., 1.]], dtype=float)))

    t_window = Float.T(default=500.)
    accuracy = Float.T(default=0.025)
    isurfcon = Int.T(default=1)
    model = PoelModel.T(
        default=PoelModel.D(
            data=num.array(
                [[0.00, 0.4E+09, 0.2, 0.4, 0.75, 5.00]], dtype=float)))

    def items(self):
        return dict(self.T.inamevals(self))


class PoelConfigFull(PoelConfig):
    s_start_depth = Float.T(default=25.0)
    s_end_depth = Float.T(default=25.0)

    sw_equidistant_z = Int.T(default=1)
    no_depths = Int.T(default=10)
    depths = Array.T(
        shape=(None,),
        dtype=float,
        default=num.array([10.0, 100.0], dtype=float))
    sw_equidistant_x = Int.T(default=1)
    no_distances = Int.T(default=10)
    distances = Array.T(
        shape=(None,),
        dtype=float,
        default=num.array([10., 100.]))

    no_t_samples = Int.T(default=51)
    t_files = List.T(String.T(), default=[x+'.t' for x in poel_components])
    sw_t_files = List.T(Int.T(), default=[1 for x in poel_components])

    def get_output_filenames(self, rundir):
        return [pjoin(rundir, fn) for fn in self.t_files]

    def string_for_config(self):

        d = self.__dict__.copy()

        if not self.sw_equidistant_x:
            d['no_distances'] = len(self.distances)
        d['str_distances'] = str_float_vals(self.distances)

        if not self.sw_equidistant_z:
            d['no_depths'] = len(self.depths)
        d['str_depths'] = str_float_vals(self.depths)

        d['sw_t_files_1_2'] = ' '.join(
            ['%i' % i for i in self.sw_t_files[0:2]])
        d['t_files_1_2'] = ' '.join(
            ["'%s'" % s for s in self.t_files[0:2]])
        d['sw_t_files_3_7'] = ' '.join(
            ['%i' % i for i in self.sw_t_files[2:7]])
        d['t_files_3_7'] = ' '.join(
            ["'%s'" % s for s in self.t_files[2:7]])
        d['sw_t_files_8_10'] = ' '.join(
            ['%i' % i for i in self.sw_t_files[7:10]])
        d['t_files_8_10'] = ' '.join(
            ["'%s'" % s for s in self.t_files[7:10]])

        d['no_model_lines'] = self.model.get_nlines()

        if self.s_type == 0:
            d['source_function'] = str(self.source_function_p)
        elif self.s_type == 1:
            d['source_function'] = self.source_function_i.string_for_config()

        d['model'] = self.model.string_for_config()

        template = '''
# This is the input file of FORTRAN77 program "poel06" for modeling
# coupled deformation-diffusion processes based on a multi-layered (half-
# or full-space) poroelastic media induced by an injection (pump) of
# from a borehole or by a (point) reservoir loading.
#
# by R. Wang,
# GeoForschungsZentrum Potsdam
# e-mail: wang@gfz-potsdam.de
# phone 0049 331 2881209
# fax 0049 331 2881204
#
# Last modified: Potsdam, July, 2012
#
##############################################################
##                                                          ##
## Cylindrical coordinates (Z positive downwards!) are used ##
## If not others specified, SI Unit System is used overall! ##
##                                                          ##
## Tilt is positive when the upper end of a borehole tilt-  ##
## meter body moves away from the pumping well.             ##
##                                                          ##
##############################################################
#
###############################################################################
#
#   SOURCE PARAMETERS A: SOURCE GEOMETRY
#   ====================================
# 1. source top and bottom depth [m]
#    Note: top depth < bottom depth for a vertical line source
#          top depth = bottom depth for a vertical point source
#
#        !  whole source screen should be within a homogeneous layer, and  !
#        !  both top and bottom should not coincide with any interface of  !
#        !  the model used (see below)                                     !
#
# 2. source radius (> 0) [m]
#    Note: source radius > 0 for a horizontal disk source
#          source radius = 0 for a horizontal point source
#------------------------------------------------------------------------------
  %(s_start_depth)g %(s_end_depth)g             |dble: s_top_depth, s_bottom_de
  %(s_radius)g                                  |dble: s_radius;
#------------------------------------------------------------------------------
#
#   SOURCE PARAMETERS B: SOURCE TYPE
#   ================================
# 1. selection of source type:
#    0 = initial excess pore pressure within the source volume
#        (initial value problem)
#    1 = injection within the source volume
#        (boundary value problem)
#------------------------------------------------------------------------------
   %(s_type)i                                   |int: sw_source_type;
#------------------------------------------------------------------------------
   %(source_function)s
###############################################################################
#
#   RECEIVER PARAMETERS A: RECEIVER DEPTH SAMPLING
#   ==============================================
# 1. switch for equidistant steping (1/0 = yes/no)
# 2. number of receiver depth samples (<= nzrmax defined in "peglobal.h")
# 3. if equidistant, start depth [m], end depth [m]; else list of depths
#    (all >= 0 and ordered from small to large!)
#------------------------------------------------------------------------------
   %(sw_equidistant_z)i                         |int: sw_receiver_depth_samplin
   %(no_depths)i                                |int: no_depths;
   %(str_depths)s                               |dble: zr_1,zr_n; or zr_1,zr_2,
#------------------------------------------------------------------------------
#
#   RECEIVER PARAMETERS B: RECEIVER DISTANCE SAMPLING
#   =================================================
# 1. switch for equidistant steping (1/0 = yes/no)
# 2. number of receiver distance samples (<= nrmax defined in "peglobal.h")
# 3. if equidistant, start distance [m], end distance [m]; else list of
#    distances (all >= 0 and ordered from small to large!)
#------------------------------------------------------------------------------
   %(sw_equidistant_x)i                         |int: sw_equidistant;
   %(no_distances)i                             |int: no_distances;
   %(str_distances)s                            |dble: d_1,d_n; or d_1,d_2, ...
#------------------------------------------------------------------------------
#
#   RECEIVER PARAMETERS C: Time SAMPLING
#   ====================================
# 1. time window [s]
# 2. number of time samples
#    Note: the caracteristic diffusion time =
#          max_receiver_distance^2 / diffusivity_of_source_layer
#------------------------------------------------------------------------------
   %(t_window)s                                 |dble: time_window;
   %(no_t_samples)i                             |int: no_time_samples;
#------------------------------------------------------------------------------
#
#   WAVENUMBER INTEGRATION PARAMETERS
#   =================================
# 1. relative accuracy (0.01 for 1%% error) for numerical wavenumber integratio
#------------------------------------------------------------------------------
   %(accuracy)s                                 |dble: accuracy;
#------------------------------------------------------------------------------
###############################################################################
#
#   OUTPUTS A: DISPLACEMENT TIME SERIES
#   ===================================
# 1. select the 2 displacement time series (1/0 = yes/no)
#    Note Ut = 0
# 2. file names of these 2 time series
#------------------------------------------------------------------------------
   %(sw_t_files_1_2)s                           |int: sw_t_files(1-2);
   %(t_files_1_2)s                              |char: t_files(1-2);
#------------------------------------------------------------------------------
#
#   OUTPUTS B: STRAIN TENSOR & TILT TIME SERIES
#   ===========================================
# 1. select strain time series (1/0 = yes/no): Ezz, Err, Ett, Ezr (4 tensor
#    components) and Tlt (= -dur/dz, the radial component of the vertical tilt)
#    Note Ezt, Ert and Tlt (tangential tilt) = 0
# 2. file names of these 5 time series
#------------------------------------------------------------------------------
   %(sw_t_files_3_7)s                           |int: sw_t_files(3-7);
   %(t_files_3_7)s                              |char: t_files(3-7);
#------------------------------------------------------------------------------
#
#   OUTPUTS C: PORE PRESSURE & DARCY VELOCITY TIME SERIES
#   =====================================================
# 1. select pore pressure and Darcy velocity time series (1/0 = yes/no):
#    Pp (excess pore pressure), Dvz, Dvr (2 Darcy velocity components)
#    Note Dvt = 0
# 2. file names of these 3 time series
#------------------------------------------------------------------------------
   %(sw_t_files_8_10)s                          |int: sw_t_files(8-10);
   %(t_files_8_10)s                             |char: t_files(8-10);
#------------------------------------------------------------------------------
#
#   OUTPUTS D: SNAPSHOTS OF ALL OBSERVABLES
#   =======================================
# 1. number of snapshots
# 2. time[s] (within the time window, see above) and output filename of
#    the 1. snapshot
# 3. ...
#------------------------------------------------------------------------------
 1                                              |int: no_sn;
   %(t_window)s    'snapshot.dat'               |dable: sn_time(i),sn_file(i)
###############################################################################
#
#   GLOBAL MODEL PARAMETERS
#   =======================
# 1. switch for surface conditions:
#    0 = without free surface (whole space),
#    1 = unconfined free surface (p = 0),
#    2 = confined free surface (dp/dz = 0).
# 2. number of data lines of the layered model (<= lmax as defined in
#    "peglobal.h") (see Note below)
#------------------------------------------------------------------------------
   %(isurfcon)i                                   |int: isurfcon
   %(no_model_lines)i                             |int: no_model_lines;
#------------------------------------------------------------------------------
#
#   MULTILAYERED MODEL PARAMETERS
#   =============================
#
#   Note: mu = shear modulus
#         nu = Poisson ratio under drained condition
#         nu_u = Poisson ratio under undrained condition (nu_u > nu)
#         B = Skempton parameter (the change in pore pressure per unit change
#             in confining pressure under undrained condition)
#         D = hydraulic diffusivity
#
# no depth[m] mu[Pa]    nu    nu_u   B     D[m^2/s]   Explanations
#------------------------------------------------------------------------------
   %(model)s
###########################end of all inputs###################################

Note for the model input format and the step-function approximation for model
parameters varying linearly with depth:

The surface and the upper boundary of the lowest half-space as well as the
interfaces at which the poroelastic parameters are continuous, are all defined
by a single data line; All other interfaces, at which the poroelastic
parameters are discontinuous, are all defined by two data lines (upper-side and
lower-side values). This input format would also be needed for a graphic plot
of the layered model. Layers which have different parameter values at top and
bottom, will be treated as layers with a constant gradient, and will be
discretised to a number of homogeneous sublayers. Errors due to the
discretisation are limited within about 5%% (changeable, see peglobal.h).
'''.lstrip()

        return template % d


class PoelError(Exception):
    pass


class PoelRunner(object):

    def __init__(self, tmp=None):

        self.tempdir = mkdtemp(prefix='poelrun', dir=tmp)
        self.program = program_bins['poel']
        self.config = None

    def run(self, config):
        self.config = config

        input_fn = pjoin(self.tempdir, 'input')

        f = open(input_fn, 'w')
        poel_input = config.string_for_config()

        logger.debug(
            '===== begin poel input =====\n%s===== end poel input ====='
            % poel_input)

        f.write(poel_input)
        f.close()
        program = self.program

        old_wd = os.getcwd()

        os.chdir(self.tempdir)

        try:
            proc = Popen(program, stdin=PIPE, stdout=PIPE, stderr=PIPE)
        except OSError:
            os.chdir(old_wd)
            raise PoelError(
                '''could not start poel executable: "%s"
Available fomosto backends and download links to the modelling codes are listed
on

      https://pyrocko.org/docs/current/apps/fomosto/backends.html

''' % program)

        (poel_output, poel_error) = proc.communicate('input\n')

        logger.debug(
            '===== begin poel output =====\n%s===== end poel output ====='
            % poel_output)
        if poel_error:
            logger.error(
                '===== begin poel error =====\n%s===== end poel error ====='
                % poel_error)

        errmess = []
        if proc.returncode != 0:
            errmess.append(
                'poel had a non-zero exit state: %i' % proc.returncode)
        if poel_error:
            errmess.append('poel emitted something via stderr')
        if poel_output.lower().find('error') != -1:
            errmess.append("the string 'error' appeared in poel output")

        if errmess:
            os.chdir(old_wd)
            raise PoelError(
                '''===== begin poel input =====\n%s===== end poel input =====
===== begin poel output =====\n%s===== end poel output =====
===== begin poel error =====\n%s===== end poel error =====
%s
poel has been invoked as "%s"''' % (
                    poel_input,
                    poel_output,
                    poel_error,
                    '\n'.join(errmess),
                    program))

        self.poel_output = poel_output
        self.poel_error = poel_error

        os.chdir(old_wd)

    def get_traces(self):

        if self.config.sw_equidistant_x == 1:
            nx = self.config.no_distances
            xmin, xmax = self.config.distances
            if nx > 1:
                dx = (xmax-xmin)/(nx-1)
            else:
                dx = 1.0
            distances = [xmin + ix*dx for ix in range(nx)]
        else:
            distances = self.config.distances

        if self.config.sw_equidistant_z == 1:
            nrz = self.config.no_depths
            rzmin, rzmax = self.config.depths
            if nrz > 1:
                drz = (rzmax-rzmin)/(nrz-1)
            else:
                drz = 1.0
            rdepths = [rzmin + irz*drz for irz in range(nrz)]
        else:
            rdepths = self.config.depths

        sz = self.config.s_start_depth

        fns = self.config.get_output_filenames(self.tempdir)
        traces = []
        for comp, fn in zip(poel_components, fns):
            data = num.loadtxt(fn, skiprows=1, dtype=float)
            nsamples, ntraces = data.shape
            ntraces -= 1
            tmin = data[0, 0]
            deltat = (data[-1, 0] - data[0, 0])/(nsamples-1)
            for itrace in range(ntraces):
                x = distances[itrace % len(distances)]
                rz = rdepths[itrace // len(distances)]
                tr = trace.Trace(
                    '', '%i' % itrace, 'c', comp,
                    tmin=tmin, deltat=deltat, ydata=data[:, itrace+1],
                    meta={'itrace': itrace, 'x': x, 'rz': rz, 'sz': sz})

                traces.append(tr)

        return traces

    def __del__(self):
        shutil.rmtree(self.tempdir)


class PoelGFBuilder(gf.builder.Builder):
    def __init__(self, store_dir, step, shared, block_size=None, tmp=None,
                 force=False):

        if block_size is None:
            block_size = (51, 1, 51)

        self.store = gf.store.Store(store_dir, 'w')

        gf.builder.Builder.__init__(
            self, self.store.config, step, block_size=block_size, force=force)

        self.poel_config = self.store.get_extra('poel')

        self.tmp = tmp
        if self.tmp is not None:
            util.ensuredir(self.tmp)

    def cleanup(self):
        self.store.close()

    def work_block(self, index):
        logger.info('Starting block %i / %i' % (index+1, self.nblocks))

        runner = PoelRunner(tmp=self.tmp)

        conf = PoelConfigFull(**self.poel_config.items())

        (firstrz, sz, firstx), (lastrz, sz, lastx), (nrz, _, nx) = \
            self.get_block_extents(index)

        conf.s_start_depth = sz
        conf.s_end_depth = sz
        conf.sw_equidistant_x = 1
        conf.distances = [firstx, lastx]
        conf.sw_equidistant_z = 1
        conf.no_distances = nx
        conf.depths = [firstrz, lastrz]
        conf.no_depths = nrz
        conf.no_t_samples = int(
            round(conf.t_window * self.gf_config.sample_rate)) + 1

        runner.run(conf)

        comp2ig = dict([(c, ig) for (ig, c) in enumerate(poel_components)])

        rawtraces = runner.get_traces()

        self.store.lock()

        for tr in rawtraces:

            x = tr.meta['x']
            rz = tr.meta['rz']
            sz = tr.meta['sz']

            ig = comp2ig[tr.channel]

            gf_tr = gf.store.GFTrace(
                tr.get_ydata(),
                int(round(tr.tmin / tr.deltat)),
                tr.deltat)

            self.store.put((rz, sz, x, ig), gf_tr)

        self.store.unlock()

        logger.info('Done with block %i / %i' % (index+1, self.nblocks))


def init(store_dir, variant):
    if variant is not None:
        raise gf.store.StoreError('unsupported variant: %s' % variant)

    poel = PoelConfig()

    store_id = os.path.basename(os.path.realpath(store_dir))

    config = gf.meta.ConfigTypeB(
        modelling_code_id='poel',
        id=store_id,
        ncomponents=10,
        component_scheme='poroelastic10',
        sample_rate=0.1,
        distance_min=10.0,
        distance_max=20.0,
        distance_delta=5.0,
        source_depth_min=10.0,
        source_depth_max=20.0,
        source_depth_delta=5.0,
        receiver_depth_min=10.0,
        receiver_depth_max=10.0,
        receiver_depth_delta=5.0)

    return gf.store.Store.create_editables(
        store_dir,
        config=config,
        extra={'poel': poel})


def build(
        store_dir,
        force=False,
        nworkers=None,
        continue_=False,
        step=None,
        iblock=None):

    return PoelGFBuilder.build(
        store_dir,
        force=force,
        nworkers=nworkers,
        continue_=continue_,
        step=step,
        iblock=iblock)
