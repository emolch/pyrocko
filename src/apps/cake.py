# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Cake - travel-times and ray paths for 1D layered media.
'''

import sys
import re
import numpy as num
# import logger
from pyrocko import cake, util, orthodrome
from pyrocko.plot import cake_plot as plot
from optparse import OptionParser, OptionGroup
import matplotlib.pyplot as plt
from pyrocko.plot import mpl_init, mpl_papersize, mpl_margins

r2d = cake.r2d


class Anon(dict):

    def __getattr__(self, x):
        return self[x]

    def getn(self, *keys):
        return Anon([(k, self[k]) for k in keys])

    def gett(self, *keys):
        return tuple([self[k] for k in keys])


def process_color(s, phase_colors):
    m = re.match(r'^([^{]+){([^}]*)}$', s)
    if not m:
        return s

    sphase = m.group(1)
    color = m.group(2)
    phase_colors[sphase] = plot.str_to_mpl_color(color)

    return sphase


def optparse(
        required=(),
        optional=(),
        args=sys.argv,
        usage='%prog [options]',
        descr=None):

    want = required + optional

    parser = OptionParser(
        prog='cake',
        usage=usage,
        description=descr.capitalize()+'.',
        add_help_option=False,
        formatter=util.BetterHelpFormatter())

    parser.add_option(
        '-h', '--help', action='help', help='Show help message and exit.')

    if 'phases' in want:
        group = OptionGroup(parser, 'Phases', '''

Seismic phase arrivals may be either specified as traditional phase names (e.g.
P, S, PP, PcP, ...) or in Cake's own syntax which is more powerful.  Use the
--classic option, for traditional phase names. Use the --phase option if you
want to define phases in Cake's syntax.

''')
        group.add_option(
            '--phase', '--phases', dest='phases', action='append',
            default=[], metavar='PHASE1,PHASE2,...',
            help='''Comma separated list of seismic phases in Cake\'s syntax.

The definition of a seismic propagation path in Cake's phase syntax is a string
consisting of an alternating sequence of "legs" and "knees".

A "leg" represents seismic wave propagation without any conversions,
encountering only super-critical reflections. Legs are denoted by "P", "p",
"S", or "s". The capital letters are used when the take-off of the "leg" is
in downward direction, while the lower case letters indicate a take-off in
upward direction.

A "knee" is an interaction with an interface. It can be a mode conversion, a
reflection, or propagation as a headwave or diffracted wave.

   * conversion is simply denoted as: "(INTERFACE)" or "DEPTH"
   * upperside reflection: "v(INTERFACE)" or "vDEPTH"
   * underside reflection: "^(INTERFACE)" or "^DEPTH"
   * normal kind headwave or diffracted wave: "v_(INTERFACE)" or "v_DEPTH"

The interface may be given by name or by depth: INTERFACE is the name of an
interface defined in the model, DEPTH is the depth of an interface in [km] (the
interface closest to that depth is chosen).  If two legs appear consecutively
without an explicit "knee", surface interaction is assumed.

The preferred standard interface names in cake are "conrad", "moho", "cmb"
(core-mantle boundary), and "cb" (inner core boundary).

The phase definition may end with a backslash "\\", to indicate that the ray
should arrive at the receiver from above instead of from below. It is possible
to restrict the maximum and minimum depth of a "leg" by appending
"<(INTERFACE)" or "<DEPTH" or ">(INTERFACE)" or ">DEPTH" after the leg
character, respectively.

When plotting rays or travel-time curves, the color can be set by appending
"{COLOR}" to the phase definition, where COLOR is the name of a color or an RGB
or RGBA color tuple in the format "R/G/B" or "R/G/B/A", respectively. The
values can be normalized to the range [0, 1] or to [0, 255]. The latter is only
assumed when any of the values given exceeds 1.0.
''')

        group.add_option(
            '--classic', dest='classic_phases', action='append',
            default=[], metavar='PHASE1,PHASE2,...',
            help='''Comma separated list of seismic phases in classic
nomenclature. Run "cake list-phase-map" for a list of available
phase names. When plotting, color can be specified in the same way
as in --phases.''')

        parser.add_option_group(group)

    if 'model' in want:
        group = OptionGroup(parser, 'Model')
        group.add_option(
            '--model', dest='model_filename', metavar='(NAME or FILENAME)',
            help='Use builtin model named NAME or user model from file '
                 'FILENAME. By default, the "ak135-f-continental.m" model is '
                 'used. Run "cake list-models" for a list of builtin models.')

        group.add_option(
            '--format', dest='model_format', metavar='FORMAT',
            choices=['nd', 'hyposat'], default='nd',
            help='Set model file format (available: nd, hyposat; default: '
                 'nd).')
        group.add_option(
            '--crust2loc', dest='crust2loc', metavar='LAT,LON',
            help='Set model from CRUST2.0 profile at location (LAT,LON).')
        group.add_option(
            '--crust2profile', dest='crust2profile', metavar='KEY',
            help='Set model from CRUST2.0 profile with given KEY.')

        parser.add_option_group(group)

    if any(x in want for x in (
            'zstart', 'zstop', 'distances', 'sloc', 'rloc')):

        group = OptionGroup(parser, 'Source-receiver geometry')
        if 'zstart' in want:
            group.add_option(
                '--sdepth', dest='sdepth', type='float', default=0.0,
                metavar='FLOAT',
                help='Source depth [km] (default: 0)')
        if 'zstop' in want:
            group.add_option(
                '--rdepth', dest='rdepth', type='float', default=0.0,
                metavar='FLOAT',
                help='Receiver depth [km] (default: 0)')
        if 'distances' in want:
            group.add_option(
                '--distances', dest='sdist', metavar='DISTANCES',
                help='Surface distances as "start:stop:n" or '
                     '"dist1,dist2,..." [km]')
            group.add_option(
                '--sloc', dest='sloc', metavar='LAT,LON',
                help='Source location (LAT,LON).')
            group.add_option(
                '--rloc', dest='rloc', metavar='LAT,LON',
                help='Receiver location (LAT,LON).')
        parser.add_option_group(group)

    if 'material' in want:
        group = OptionGroup(
            parser, 'Material',
            'An isotropic elastic material may be specified by giving '
            'a combination of some of the following options. ')
        group.add_option(
            '--vp', dest='vp', default=None, type='float', metavar='FLOAT',
            help='P-wave velocity [km/s]')
        group.add_option(
            '--vs', dest='vs', default=None, type='float', metavar='FLOAT',
            help='S-wave velocity [km/s]')
        group.add_option(
            '--rho', dest='rho', default=None, type='float', metavar='FLOAT',
            help='density [g/cm**3]')
        group.add_option(
            '--qp', dest='qp', default=None, type='float', metavar='FLOAT',
            help='P-wave attenuation Qp (default: 1456)')
        group.add_option(
            '--qs', dest='qs', default=None, type='float', metavar='FLOAT',
            help='S-wave attenuation Qs (default: 600)')
        group.add_option(
            '--poisson', dest='poisson', default=None, type='float',
            metavar='FLOAT',
            help='Poisson ratio')
        group.add_option(
            '--lambda', dest='lame_lambda', default=None, type='float',
            metavar='FLOAT',
            help='Lame parameter lambda [GPa]')
        group.add_option(
            '--mu', dest='lame_mu', default=None, type='float',
            metavar='FLOAT',
            help='Shear modulus [GPa]')
        group.add_option(
            '--qk', dest='qk', default=None, type='float', metavar='FLOAT',
            help='Bulk attenuation Qk')
        group.add_option(
            '--qmu', dest='qmu', default=None, type='float', metavar='FLOAT',
            help='Shear attenuation Qmu')
        parser.add_option_group(group)

    if any(x in want for x in (
            'vred', 'as_degrees', 'accuracy', 'slowness', 'interface',
            'aspect', 'shade_model')):

        group = OptionGroup(parser, 'General')
        if 'vred' in want:
            group.add_option(
                '--vred', dest='vred', type='float', metavar='FLOAT',
                help='Velocity for time reduction in plot [km/s]')

        if 'as_degrees' in want:
            group.add_option(
                '--degrees', dest='as_degrees', action='store_true',
                default=False,
                help='Distances are in [deg] instead of [km], velocities in '
                     '[deg/s] instead of [km/s], slownesses in [s/deg] '
                     'instead of [s/km].')

        if 'accuracy' in want:
            group.add_option(
                '--accuracy', dest='accuracy', type='float',
                metavar='MAXIMUM_RELATIVE_RMS', default=0.002,
                help='Set accuracy for model simplification.')

        if 'slowness' in want:
            group.add_option(
                '--slowness', dest='slowness', type='float', metavar='FLOAT',
                default=0.0,
                help='Select surface slowness [s/km] (default: 0)')

        if 'interface' in want:
            group.add_option(
                '--interface', dest='interface', metavar='(NAME or DEPTH)',
                help='Name or depth [km] of interface to select')

        if 'aspect' in want:
            group.add_option(
                '--aspect', dest='aspect', type='float', metavar='FLOAT',
                help='Aspect ratio for plot')

        if 'shade_model' in want:
            group.add_option(
                '--no-shade-model', dest='shade_model', action='store_false',
                default=True,
                help='Suppress shading of earth model layers')

        parser.add_option_group(group)

    if any(x in want for x in ('output_format', 'save', 'size', 'show')):
        group = OptionGroup(parser, 'Output', 'Output specifications')
        if 'output_format' in want:
            group.add_option(
                '--output-format', dest='output_format', metavar='FORMAT',
                default='textual',
                choices=('textual', 'nd'),
                help='Set model output format (available: textual, nd, '
                     'default: textual)')
        if 'save' in want:
            group.add_option(
                '-s', '--save', dest='save', metavar='PATH',
                help='saves plot to .png (default) or other py-supported\
                 endings without showing, use --show or -u for showing',
                default='')
        if 'size' in want:
            group.add_option(
                '--size', dest='size', type='string',
                default='a4',
                help="gives size of returned plot, use 'a5' or 'a4'")
        if 'show' in want:
            group.add_option(
                '-u', '--show', dest='show', action='store_true',
                help='shows plot when saving (-u for unhide)')

        parser.add_option_group(group)

    if usage == 'cake help-options':
        parser.print_help()

    (options, args) = parser.parse_args(args)

    if len(args) != 2:
        parser.error(
            'Cake arguments should look like "--option" or "--option=...".')

    d = {}
    as_degrees = False
    if 'as_degrees' in want:
        as_degrees = options.as_degrees
        d['as_degrees'] = as_degrees

    if 'accuracy' in want:
        d['accuracy'] = options.accuracy

    if 'output_format' in want:
        d['output_format'] = options.output_format

    if 'save' in want:
        d['save'] = options.save

    if 'size' in want:
        d['size'] = options.size

    if 'show' in want:
        d['show'] = options.show

    if 'aspect' in want:
        d['aspect'] = options.aspect

    if 'shade_model' in want:
        d['shade_model'] = options.shade_model

    if 'phases' in want:
        phases = []
        phase_colors = {}
        try:
            for ss in options.phases:
                for s in ss.split(','):
                    s = process_color(s, phase_colors)
                    phases.append(cake.PhaseDef(s))

            for pp in options.classic_phases:
                for p in pp.split(','):
                    p = process_color(p, phase_colors)
                    phases.extend(cake.PhaseDef.classic(p))

        except (cake.PhaseDefParseError, cake.UnknownClassicPhase) as e:
            parser.error(e)

        if not phases and 'phases' in required:
            s = process_color('P', phase_colors)
            phases.append(cake.PhaseDef(s))

        if phases:
            d['phase_colors'] = phase_colors
            d['phases'] = phases

    if 'model' in want:
        if options.model_filename:
            d['model'] = cake.load_model(
                options.model_filename, options.model_format)

        if options.crust2loc or options.crust2profile:
            if options.crust2loc:
                try:
                    args = tuple(
                        [float(x) for x in options.crust2loc.split(',')])
                except Exception:
                    parser.error(
                        'format for --crust2loc option is '
                        '"LATITUDE,LONGITUDE"')
            elif options.crust2profile:
                args = (options.crust2profile.upper(),)
            else:
                assert False

            if 'model' in d:
                d['model'] = d['model'].replaced_crust(args)
            else:
                from pyrocko import crust2x2
                profile = crust2x2.get_profile(*args)
                d['model'] = cake.LayeredModel.from_scanlines(
                    cake.from_crust2x2_profile(profile))

    if 'vred' in want:
        d['vred'] = options.vred
        if d['vred'] is not None:
            if not as_degrees:
                d['vred'] *= r2d * cake.km / cake.earthradius

    if 'distances' in want:
        distances = None
        if options.sdist:
            if options.sdist.find(':') != -1:
                ssn = options.sdist.split(':')
                if len(ssn) != 3:
                    parser.error(
                        'format for distances is '
                        '"min_distance:max_distance:n_distances"')

                distances = num.linspace(
                    float(ssn[0]), float(ssn[1]), int(ssn[2]))
            else:
                distances = num.array(
                    list(map(
                        float, options.sdist.split(','))), dtype=float)

            if not as_degrees:
                distances *= r2d * cake.km / cake.earthradius

        if options.sloc and options.rloc:
            try:
                slat, slon = tuple([float(x) for x in options.sloc.split(',')])
                rlat, rlon = tuple([float(x) for x in options.rloc.split(',')])
            except Exception:
                parser.error(
                    'format for --sloc and --rloc options is '
                    '"LATITUDE,LONGITUDE"')

            distance_sr = orthodrome.distance_accurate50m_numpy(
                slat, slon, rlat, rlon)

            distance_sr *= r2d / cake.earthradius
            if distances is not None:
                distances = num.concatenate((distances, [distance_sr]))
            else:
                distances = num.array([distance_sr], dtype=float)

        if distances is not None:
            d['distances'] = distances
        else:
            if 'distances' not in required:
                d['distances'] = None

    if 'slowness' in want:
        d['slowness'] = options.slowness/cake.d2r
        if not as_degrees:
            d['slowness'] /= cake.km*cake.m2d

    if 'interface' in want:
        if options.interface:
            try:
                d['interface'] = float(options.interface)*cake.km
            except ValueError:
                d['interface'] = options.interface

        else:
            d['interface'] = None

    if 'zstart' in want:
        d['zstart'] = options.sdepth*cake.km

    if 'zstop' in want:
        d['zstop'] = options.rdepth*cake.km

    if 'material' in want:
        md = {}
        userfactor = dict(
            vp=1000., vs=1000., rho=1000., qp=1., qs=1., qmu=1., qk=1.,
            lame_lambda=1.0e9, lame_mu=1.0e9, poisson=1.)

        for k in userfactor.keys():
            if getattr(options, k) is not None:
                md[k] = getattr(options, k) * userfactor[k]

        if not (bool('lame_lambda' in md) == bool('lame_mu' in md)):
            parser.error('lambda and mu must be specified both.')
        if 'lame_lambda' in md and 'lame_mu' in md:
            md['lame'] = md.pop('lame_lambda'), md.pop('lame_mu')

        if md:
            try:
                d['material'] = cake.Material(**md)
            except cake.InvalidArguments as e:
                parser.error(str(e))

    for k in list(d.keys()):
        if k not in want:
            del d[k]

    for k in required:
        if k not in d:
            if k == 'model':
                d['model'] = cake.load_model('ak135-f-continental.m')

            elif k == 'distances':
                d['distances'] = num.linspace(10*cake.km, 100*cake.km, 10) \
                    / cake.earthradius * r2d

            elif k == 'phases':
                d['phases'] = list(map(cake.PhaseDef, 'Pp'))

            else:
                parser.error('missing %s' % k)

    return Anon(d)


def my_simplify_model(mod, accuracy):
    mod_simple = mod.simplify(max_rel_error=accuracy)
    cake.write_nd_model_fh(mod_simple, sys.stdout)


def d2u(d):
    return dict((k.replace('-', '_'), v) for (k, v) in d.items())


def mini_fmt(v, d=5, try_fmts='fe'):
    for fmt in try_fmts:
        for i in range(d, -1, -1):
            s = ('%%%i.%i%s' % (d, i, fmt)) % v
            if len(s) <= d and (v == 0.0 or float(s) != 0.0):
                return s

    return s


def scatter_out_fmt(d, m, v):
    if v < 1e-8:
        return '  ', '     '
    else:
        return '%s%s' % ('\\/'[d == cake.UP], 'SP'[m == cake.P]), \
            mini_fmt(v*100, 5)


def scatter_in_fmt(d, m, dwant):
    if d == dwant:
        return '%s%s' % ('\\/'[d == cake.UP], 'SP'[m == cake.P])
    else:
        return '  '


def print_scatter(model, p=0.0, interface=None):
    if interface is not None:
        discontinuities = [model.discontinuity(interface)]
    else:
        discontinuities = model.discontinuities()

    for discontinuity in discontinuities:
        print('%s (%g km)' % (discontinuity, discontinuity.z/cake.km))
        print()
        cols = []
        for in_direction in (cake.DOWN, cake.UP):
            for in_mode in (cake.P, cake.S):
                p_critical = discontinuity.critical_ps(in_mode)[
                    in_direction == cake.UP]

                if p_critical is None or p >= p_critical:
                    continue

                vals = []
                for out_direction in (cake.UP, cake.DOWN):
                    for out_mode in (cake.S, cake.P):
                        vals.append(
                            (out_direction, out_mode, discontinuity.efficiency(
                                in_direction, out_direction,
                                in_mode, out_mode, p)))

                if all(x[-1] == 0.0 for x in vals):
                    continue

                sout = [scatter_out_fmt(d, m, v) for (d, m, v) in vals]

                sin1 = scatter_in_fmt(in_direction, in_mode, cake.DOWN)
                sin2 = scatter_in_fmt(in_direction, in_mode, cake.UP)
                line1 = '%s  %5s  %5s' % (
                    ' '*len(sin1), sout[0][1], sout[1][1])
                line2 = '%s  %-5s  %-5s' % (
                    sin1, sout[0][0], sout[1][0])
                line4 = '%s  %-5s  %-5s' % (
                    sin2, sout[2][0], sout[3][0])
                line5 = '%s  %5s  %5s' % (
                    ' '*len(sin2), sout[2][1], sout[3][1])
                line3 = '-' * len(line1)
                cols.append((line1, line2, line3, line4, line5))

        for cols in zip(*cols):
            print('  ' + '   '.join(cols))

        print()
        print()


def print_arrivals(
        model, distances=[], phases=cake.PhaseDef('P'), zstart=0.0, zstop=0.0,
        as_degrees=False):

    headers = 'slow dist time take inci effi spre phase used'.split()
    space = (7, 5, 6, 4, 4, 4, 4, 17, 17)

    if as_degrees:
        units = 's/deg deg s deg deg % %'.split()
    else:
        units = 's/km km s deg deg % %'.split()

    hline = ' '.join(x.ljust(s) for (x, s) in zip(headers, space))
    uline = ' '.join(('%s' % x).ljust(s) for (x, s) in zip(units, space))

    print(hline)
    print(uline)
    print('-' * len(hline))

    for ray in model.arrivals(
            distances=distances, phases=phases, zstart=zstart, zstop=zstop):

        if as_degrees:
            sd = ray.x
            slow = ray.p/cake.r2d
        else:
            sd = ray.x*(cake.d2r*cake.earthradius/cake.km)
            slow = ray.p/(r2d*cake.d2m/cake.km)

        su = '(%s)' % ray.path.used_phase(p=ray.p, eps=1.0).used_repr()

        print(' '.join(tuple(mini_fmt(x, s).rjust(s) for (x, s) in zip(
            (slow, sd, ray.t, ray.takeoff_angle(), ray.incidence_angle(),
             100*ray.efficiency(), 100*ray.spreading()*ray.surface_sphere()),
            space)) + tuple(
            x.ljust(17) for x in (ray.path.phase.definition(), su))))


def plot_init(size, save, show):
    fontsize = 9
    mpl_init()
    fig = plt.figure(figsize=mpl_papersize(size, 'landscape'))

    labelpos = mpl_margins(fig, w=7., h=5., units=fontsize)
    axes = fig.add_subplot(1, 1, 1)
    labelpos(axes, 2., 1.5)

    showplt = bool(show or not save)

    return fig, axes, showplt


class CakeError(Exception):
    pass


def plot_end(save, fig, show=True):
    if save:
        try:
            fig.savefig(save)
            if show:
                plt.show()
        except OSError as e:
            raise CakeError(str(e))
        except ValueError as e:
            raise CakeError(str(e))


def main(args=None):
    '''
    CLI entry point for Pyrocko's ``cake`` app.
    '''

    if args is None:
        args = sys.argv[1:]

    subcommand_descriptions = {
        'print':          'get information on model/phase/material properties',
        'arrivals':       'print list of phase arrivals',
        'paths':          'print ray path details',
        'plot-xt':        'plot traveltime vs distance curves',
        'plot-xp':        'plot ray parameter vs distance curves',
        'plot-rays':      'plot ray propagation paths',
        'plot':           'plot combination of ray and traveltime curves',
        'plot-model':     'plot velocity model',
        'list-models':    'list builtin velocity models',
        'list-phase-map': 'show translation table for classic phase names',
        'simplify-model': 'create a simplified version of a layered model',
        'scatter':        'show details about scattering at model interfaces'}

    usage = '''cake <subcommand> [options]

Subcommands:

    print          %(print)s
    arrivals       %(arrivals)s
    paths          %(paths)s
    plot-xt        %(plot_xt)s
    plot-xp        %(plot_xp)s
    plot-rays      %(plot_rays)s
    plot           %(plot)s
    plot-model     %(plot_model)s
    list-models    %(list_models)s
    list-phase-map %(list_phase_map)s
    simplify-model %(simplify_model)s
    scatter        %(scatter)s

To get further help and a list of available options for any subcommand run:

    cake <subcommand> --help

'''.strip() % d2u(subcommand_descriptions)

    usage_sub = 'cake %s [options]'
    if len(args) < 1:
        sys.exit('Usage: %s' % usage)

    command = args[0]

    args[0:0] = ['cake']
    descr = subcommand_descriptions.get(command, None)
    subusage = usage_sub % command

    if command == 'print':
        c = optparse(
            (), ('model', 'phases', 'material', 'output_format'),
            usage=subusage, descr=descr, args=args)

        if 'model' in c:
            if c.output_format == 'textual':
                print(c.model)
                print()
            elif c.output_format == 'nd':
                cake.write_nd_model_fh(c.model, sys.stdout)

        if 'phases' in c:
            for phase in c.phases:
                print(phase)
            print()

        if 'material' in c:
            print(c.material.describe())
            print()

    elif command == 'arrivals':
        c = optparse(
            ('model', 'phases', 'distances'),
            ('zstart', 'zstop', 'as_degrees'),
            usage=subusage, descr=descr, args=args)

        print_arrivals(
            c.model,
            **c.getn('zstart', 'zstop', 'phases', 'distances', 'as_degrees'))

    elif command == 'paths':
        c = optparse(
            ('model', 'phases'),
            ('zstart', 'zstop', 'as_degrees'),
            usage=subusage, descr=descr, args=args)

        mod = c.model
        for path in mod.gather_paths(**c.getn('phases', 'zstart', 'zstop')):
            print(path.describe(path.endgaps(c.zstart, c.zstop), c.as_degrees))

    elif command in ('plot-xt', 'plot-xp', 'plot-rays', 'plot'):
        if command in ('plot-xt', 'plot'):
            c = optparse(
                ('model', 'phases',),
                ('zstart', 'zstop', 'distances', 'as_degrees', 'vred',
                 'phase_colors', 'save', 'size', 'show'),
                usage=subusage, descr=descr, args=args)
        else:
            c = optparse(
                ('model', 'phases'),
                ('zstart', 'zstop', 'distances', 'as_degrees', 'aspect',
                 'shade_model', 'phase_colors', 'save', 'size', 'show'),
                usage=subusage, descr=descr, args=args)

        mod = c.model
        paths = mod.gather_paths(**c.getn('phases', 'zstart', 'zstop'))

        if c.distances is not None:
            arrivals = mod.arrivals(
                **c.getn('phases', 'zstart', 'zstop', 'distances'))
        else:
            arrivals = None

        fig, axes, showplt = plot_init(c.size, c.save, c.show)

        if command == 'plot-xp':
            plot.my_xp_plot(
                paths, c.zstart, c.zstop, c.distances,
                c.as_degrees, show=showplt, phase_colors=c.phase_colors)

        elif command == 'plot-xt':
            plot.my_xt_plot(
                paths, c.zstart, c.zstop, c.distances, c.as_degrees,
                vred=c.vred, show=showplt,
                phase_colors=c.phase_colors)

        elif command == 'plot-rays':
            if c.as_degrees:
                plot.my_rays_plot_gcs(
                    mod, paths, arrivals, c.zstart, c.zstop, c.distances,
                    show=showplt, phase_colors=c.phase_colors)

            else:
                plot.my_rays_plot(
                    mod, paths, arrivals, c.zstart, c.zstop, c.distances,
                    show=showplt, aspect=c.aspect, shade_model=c.shade_model,
                    phase_colors=c.phase_colors)

        elif command == 'plot':
            plot.my_combi_plot(
                mod, paths, arrivals, c.zstart, c.zstop, c.distances,
                c.as_degrees, show=showplt, vred=c.vred,
                phase_colors=c.phase_colors)

        try:
            plot_end(save=c.save, fig=fig, show=c.show)
        except CakeError as e:
            exit('cake.py: %s' % str(e))

    elif command in ('plot-model',):
        c = optparse(
            ('model',), ('save', 'size', 'show'),
            usage=subusage, descr=descr, args=args)
        mod = c.model
        fig, axes, showplt = plot_init(c.size, c.save, c.show)
        plot.my_model_plot(mod, show=showplt)
        try:
            plot_end(save=c.save, fig=fig, show=c.show)
        except CakeError as e:
            exit('cake.py: %s' % str(e))

    elif command in ('simplify-model',):
        c = optparse(('model',), ('accuracy',),
                     usage=subusage, descr=descr, args=args)
        my_simplify_model(c.model, c.accuracy)

    elif command in ('list-models',):
        c = optparse((), (), usage=subusage, descr=descr, args=args)
        for x in cake.builtin_models():
            print(x)

    elif command in ('list-phase-map',):
        c = optparse((), (), usage=subusage, descr=descr, args=args)
        defs = cake.PhaseDef.classic_definitions()
        for k in sorted(defs.keys()):
            print('%-15s: %s' % (k, ', '.join(defs[k])))

    elif command in ('scatter',):
        c = optparse(
            ('model',),
            ('slowness', 'interface', 'as_degrees'),
            usage=subusage, descr=descr, args=args)

        print_scatter(c.model, p=c.slowness, interface=c.interface)

    elif command in ('help-options',):
        optparse(
            (),
            ('model', 'accuracy', 'slowness', 'interface', 'phases',
             'distances', 'zstart', 'zstop', 'distances', 'as_degrees',
             'material', 'vred', 'save'),
            usage='cake help-options', descr='list all available options',
            args=args)

    elif command in ('--help', '-h', 'help'):
        sys.exit('Usage: %s' % usage)

    else:
        sys.exit('cake: no such subcommand: %s' % command)


if __name__ == '__main__':
    main()
