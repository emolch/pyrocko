# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Fomosto - Green's function database management.
'''

import sys
import re
import os.path as op
import logging
import copy
import shutil
from optparse import OptionParser

from pyrocko import util, trace, gf, cake, io, fomosto
from pyrocko.gui.snuffler import marker
from pyrocko.util import mpl_show

logger = logging.getLogger('pyrocko.apps.fomosto')
km = 1e3


def d2u(d):
    return dict((k.replace('-', '_'), v) for (k, v) in d.items())


subcommand_descriptions = {
    'init':          'create a new empty GF store',
    'build':         'compute GFs and fill into store',
    'stats':         'print information about a GF store',
    'check':         'check for problems in GF store',
    'decimate':      'build decimated variant of a GF store',
    'redeploy':      'copy traces from one GF store into another',
    'view':          'view selected traces',
    'extract':       'extract selected traces',
    'import':        'convert Kiwi GFDB to GF store format',
    'export':        'convert GF store to Kiwi GFDB format',
    'ttt':           'create travel time tables',
    'tttview':       'plot travel time table',
    'tttextract':    'extract selected travel times',
    'tttlsd':        'fix holes in travel time tables',
    'sat':           'create stored ray attribute table',
    'satview':       'plot stored ray attribute table',
    'server':        'run seismosizer server',
    'download':      'download GF store from a server',
    'modelview':     'plot earthmodels',
    'upgrade':       'upgrade store format to latest version',
    'addref':        'import citation references to GF store config',
    'qc':            'quality check',
    'report':        "report for Green's Function databases",
}

subcommand_usages = {
    'init':          ['init <type> <store-dir> [options]',
                      'init redeploy <source> <destination> [options]'],
    'build':         'build [store-dir] [options]',
    'stats':         'stats [store-dir] [options]',
    'check':         'check [store-dir] [options]',
    'decimate':      'decimate [store-dir] <factor> [options]',
    'redeploy':      'redeploy <source> <destination> [options]',
    'view':          'view [store-dir] ... [options]',
    'extract':       'extract [store-dir] <selection>',
    'import':        'import <source> <destination> [options]',
    'export':        'export [store-dir] <destination> [options]',
    'ttt':           'ttt [store-dir] [options]',
    'tttview':       'tttview [store-dir] <phase-ids> [options]',
    'tttextract':    'tttextract [store-dir] <phase> <selection>',
    'tttlsd':        'tttlsd [store-dir] <phase>',
    'sat':           'sat [store-dir] [options]',
    'satview':       'satview [store-dir] <phase-ids> [options]',
    'server':        'server [options] <store-super-dir> ...',
    'download':      'download [options] <site> <store-id>',
    'modelview':     'modelview <selection>',
    'upgrade':       'upgrade [store-dir] ...',
    'addref':        'addref [store-dir] ... <filename> ...',
    'qc':            'qc [store-dir]',
    'report':        'report <subcommand> <arguments>... [options]'
}

subcommands = subcommand_descriptions.keys()

program_name = 'fomosto'

usage = program_name + ''' <subcommand> <arguments> ... [options]

Subcommands:

    init          %(init)s
    build         %(build)s
    stats         %(stats)s
    check         %(check)s
    decimate      %(decimate)s
    redeploy      %(redeploy)s
    view          %(view)s
    extract       %(extract)s
    import        %(import)s
    export        %(export)s
    ttt           %(ttt)s
    tttview       %(tttview)s
    tttextract    %(tttextract)s
    tttlsd        %(tttlsd)s
    sat           %(sat)s
    satview       %(satview)s
    server        %(server)s
    download      %(download)s
    modelview     %(modelview)s
    upgrade       %(upgrade)s
    addref        %(addref)s
    qc            %(qc)s
    report        %(report)s

To get further help and a list of available options for any subcommand run:

    fomosto <subcommand> --help

''' % d2u(subcommand_descriptions)


def add_common_options(parser):
    parser.add_option(
        '--loglevel',
        action='store',
        dest='loglevel',
        type='choice',
        choices=('critical', 'error', 'warning', 'info', 'debug'),
        default='info',
        help='set logger level to '
             '"critical", "error", "warning", "info", or "debug". '
             'Default is "%default".')


def process_common_options(options):
    util.setup_logging(program_name, options.loglevel)


def cl_parse(command, args, setup=None, details=None):
    usage = subcommand_usages[command]
    descr = subcommand_descriptions[command]

    if isinstance(usage, str):
        usage = [usage]

    susage = '%s %s' % (program_name, usage[0])
    for s in usage[1:]:
        susage += '\n%s%s %s' % (' '*7, program_name, s)

    description = descr[0].upper() + descr[1:] + '.'

    if details:
        description = description + ' %s' % details

    parser = OptionParser(usage=susage, description=description)
    parser.format_description = lambda formatter: description

    if setup:
        setup(parser)

    add_common_options(parser)
    (options, args) = parser.parse_args(args)
    process_common_options(options)
    return parser, options, args


def die(message, err=''):
    sys.exit('%s: error: %s \n %s' % (program_name, message, err))


def fomo_wrapper_module(name):
    try:
        if not re.match(gf.meta.StringID.pattern, name):
            raise ValueError('invalid name')

        words = name.split('.', 1)
        if len(words) == 2:
            name, variant = words
        else:
            name = words[0]
            variant = None

        name_clean = re.sub(r'[.-]', '_', name)
        modname = '.'.join(['pyrocko', 'fomosto', name_clean])
        mod = __import__(modname, level=0)
        return getattr(mod.fomosto, name_clean), variant

    except ValueError:
        die('invalid modelling code wrapper name')

    except ImportError:
        die('''modelling code wrapper "%s" not available or not installed
                (module probed: "%s")''' % (name, modname))


def command_init(args):

    details = '''

Available modelling backends:
%s

  More information at
    https://pyrocko.org/docs/current/apps/fomosto/backends.html
''' % '\n'.join(['  * %s' % b for b in fomosto.AVAILABLE_BACKENDS])

    parser, options, args = cl_parse(
        'init', args,
        details=details)

    if len(args) == 0:
        sys.exit(parser.format_help())

    if args[0] == 'redeploy':
        if len(args) != 3:
            parser.error('incorrect number of arguments')

        source_dir, dest_dir = args[1:]

        try:
            source = gf.Store(source_dir)
        except gf.StoreError as e:
            die(e)

        config = copy.deepcopy(source.config)
        config.derived_from_id = source.config.id
        try:
            config_filenames = gf.store.Store.create_editables(
                dest_dir, config=config)

        except gf.StoreError as e:
            die(e)

        try:
            dest = gf.Store(dest_dir)
        except gf.StoreError as e:
            die(e)

        for k in source.extra_keys():
            source_fn = source.get_extra_path(k)
            dest_fn = dest.get_extra_path(k)
            shutil.copyfile(source_fn, dest_fn)

        logger.info(
            '(1) configure settings in files:\n  %s'
            % '\n  '.join(config_filenames))

        logger.info(
            '(2) run "fomosto redeploy <source> <dest>", as needed')

    else:
        if len(args) != 2:
            parser.error('incorrect number of arguments')

        (modelling_code_id, store_dir) = args

        module, variant = fomo_wrapper_module(modelling_code_id)
        try:
            config_filenames = module.init(store_dir, variant)
        except gf.StoreError as e:
            die(e)

        logger.info('(1) configure settings in files:\n  %s'
                    % '\n  '.join(config_filenames))
        logger.info('(2) run "fomosto ttt" in directory "%s"' % store_dir)
        logger.info('(3) run "fomosto build" in directory "%s"' % store_dir)


def get_store_dir(args):
    if len(args) == 1:
        store_dir = op.abspath(args.pop(0))
    else:
        store_dir = op.abspath(op.curdir)

    if not op.isdir(store_dir):
        die('not a directory: %s' % store_dir)

    return store_dir


def get_store_dirs(args):
    if len(args) == 0:
        store_dirs = [op.abspath(op.curdir)]
    else:
        store_dirs = [op.abspath(x) for x in args]

    for store_dir in store_dirs:
        if not op.isdir(store_dir):
            die('not a directory: %s' % store_dir)

    return store_dirs


def command_build(args):

    def setup(parser):
        parser.add_option(
            '--force', dest='force', action='store_true',
            help='overwrite existing files')

        parser.add_option(
            '--nworkers', dest='nworkers', type='int', metavar='N',
            help='run N worker processes in parallel')

        parser.add_option(
            '--continue', dest='continue_', action='store_true',
            help='continue suspended build')

        parser.add_option(
            '--step', dest='step', type='int', metavar='I',
            help='process block number IBLOCK')

        parser.add_option(
            '--block', dest='iblock', type='int', metavar='I',
            help='process block number IBLOCK')

    parser, options, args = cl_parse('build', args, setup=setup)

    store_dir = get_store_dir(args)
    try:
        if options.step is not None:
            step = options.step - 1
        else:
            step = None

        if options.iblock is not None:
            iblock = options.iblock - 1
        else:
            iblock = None

        store = gf.Store(store_dir)
        module, _ = fomo_wrapper_module(store.config.modelling_code_id)
        module.build(
            store_dir,
            force=options.force,
            nworkers=options.nworkers, continue_=options.continue_,
            step=step,
            iblock=iblock)

    except gf.StoreError as e:
        die(e)


def command_stats(args):

    parser, options, args = cl_parse('stats', args)
    store_dir = get_store_dir(args)

    try:
        store = gf.Store(store_dir)
        s = store.stats()

    except gf.StoreError as e:
        die(e)

    for k in store.stats_keys:
        print('%s: %s' % (k, s[k]))


def command_check(args):

    parser, options, args = cl_parse('check', args)
    store_dir = get_store_dir(args)

    try:
        store = gf.Store(store_dir)
        problems = store.check(show_progress=True)
        if problems:
            die('problems detected with gf store: %s' % store_dir)

    except gf.StoreError as e:
        die(e)


def load_config(fn):
    try:
        config = gf.meta.load(filename=fn)
        assert isinstance(config, gf.Config)

    except Exception:
        die('cannot load gf config from file: %s' % fn)

    return config


def command_decimate(args):

    def setup(parser):
        parser.add_option(
            '--config', dest='config_fn', metavar='FILE',
            help='use modified spacial sampling given in FILE')

        parser.add_option(
            '--force', dest='force', action='store_true',
            help='overwrite existing files')

    parser, options, args = cl_parse('decimate', args, setup=setup)
    try:
        decimate = int(args.pop())
    except Exception:
        parser.error('cannot get <factor> argument')

    store_dir = get_store_dir(args)

    config = None
    if options.config_fn:
        config = load_config(options.config_fn)

    try:
        store = gf.Store(store_dir)
        store.make_decimated(decimate, config=config, force=options.force,
                             show_progress=True)

    except gf.StoreError as e:
        die(e)


def sindex(args):
    return '(%s)' % ', '.join('%g' % x for x in args)


def command_redeploy(args):

    parser, options, args = cl_parse('redeploy', args)

    if not len(args) == 2:
        sys.exit(parser.format_help())

    source_store_dir, dest_store_dir = args

    try:
        source = gf.Store(source_store_dir)
    except gf.StoreError as e:
        die(e)

    try:
        gf.store.Store.create_dependants(dest_store_dir)
    except gf.StoreError:
        pass

    try:
        dest = gf.Store(dest_store_dir, 'w')

    except gf.StoreError as e:
        die(e)

    show_progress = True

    try:
        if show_progress:
            pbar = util.progressbar('redeploying', dest.config.nrecords)

        for i, args in enumerate(dest.config.iter_nodes()):
            try:
                tr = source.get(args, interpolation='off')
                dest.put(args, tr)

            except (gf.meta.OutOfBounds, gf.store.NotAllowedToInterpolate) as e:  # noqa
                logger.debug('skipping %s, (%s)' % (sindex(args), e))

            except gf.store.StoreError as e:
                logger.warning('cannot insert %s, (%s)' % (sindex(args), e))

            if show_progress:
                pbar.update(i+1)

    finally:
        if show_progress:
            pbar.finish()


def command_view(args):
    def setup(parser):
        parser.add_option(
            '--extract',
            dest='extract',
            metavar='start:stop[:step|@num],...',
            help='specify which traces to show')

        parser.add_option(
            '--show-phases',
            dest='showphases',
            default=None,
            metavar='[phase_id1,phase_id2,...|all]',
            help='add phase markers from ttt')

        parser.add_option(
            '--opengl',
            dest='opengl',
            action='store_true',
            default=None,
            help='use OpenGL for drawing')

        parser.add_option(
            '--no-opengl',
            dest='opengl',
            action='store_false',
            default=None,
            help='do not use OpenGL for drawing')

    parser, options, args = cl_parse('view', args, setup=setup)

    gdef = None
    if options.extract:
        try:
            gdef = gf.meta.parse_grid_spec(options.extract)
        except gf.meta.GridSpecError as e:
            die(e)

    store_dirs = get_store_dirs(args)

    alpha = 'abcdefghijklmnopqrstxyz'.upper()

    markers = []
    traces = []

    try:
        for istore, store_dir in enumerate(store_dirs):
            store = gf.Store(store_dir)
            if options.showphases == 'all':
                phasenames = [pn.id for pn in store.config.tabulated_phases]
            elif options.showphases is not None:
                phasenames = options.showphases.split(',')

            ii = 0
            for args in store.config.iter_extraction(gdef):
                gtr = store.get(args)

                loc_code = ''
                if len(store_dirs) > 1:
                    loc_code = alpha[istore % len(alpha)]

                if gtr:

                    sta_code = '%04i (%s)' % (
                        ii, ','.join('%gk' % (x/1000.) for x in args[:-1]))
                    tmin = gtr.deltat * gtr.itmin

                    tr = trace.Trace(
                        '',
                        sta_code,
                        loc_code,
                        '%02i' % args[-1],
                        ydata=gtr.data,
                        deltat=gtr.deltat,
                        tmin=tmin)

                    if options.showphases:
                        for phasename in phasenames:
                            phase_tmin = store.t(phasename, args[:-1])
                            if phase_tmin:
                                m = marker.PhaseMarker(
                                    [('',
                                      sta_code,
                                      loc_code,
                                      '%02i' % args[-1])],
                                    phase_tmin,
                                    phase_tmin,
                                    0,
                                    phasename=phasename)
                                markers.append(m)

                    traces.append(tr)

                ii += 1

    except (gf.meta.GridSpecError, gf.StoreError, gf.meta.OutOfBounds) as e:
        die(e)

    def setup(win):
        viewer = win.get_view()
        viewer.menuitem_showboxes.setChecked(False)
        viewer.menuitem_colortraces.setChecked(True)
        viewer.menuitem_demean.setChecked(False)
        viewer.menuitems_sorting[5][0].setChecked(True)
        viewer.menuitems_scaling[2][0].setChecked(True)
        viewer.sortingmode_change()
        viewer.scalingmode_change()

    trace.snuffle(
        traces, markers=markers, opengl=options.opengl, launch_hook=setup)


def command_extract(args):
    def setup(parser):
        parser.add_option(
            '--format', dest='format', default='mseed',
            choices=['mseed', 'sac', 'text', 'yaff'],
            help='export to format "mseed", "sac", "text", or "yaff". '
                 'Default is "mseed".')

        fndfl = 'extracted/%(irecord)s_%(args)s.%(extension)s'
        parser.add_option(
            '--output', dest='output_fn', default=fndfl, metavar='TEMPLATE',
            help='output path template [default: "%s"]' % fndfl)

    parser, options, args = cl_parse('extract', args, setup=setup)
    try:
        sdef = args.pop()
    except Exception:
        parser.error('cannot get <selection> argument')

    try:
        gdef = gf.meta.parse_grid_spec(sdef)
    except gf.meta.GridSpecError as e:
        die(e)

    store_dir = get_store_dir(args)

    extensions = {
        'mseed': 'mseed',
        'sac': 'sac',
        'text': 'txt',
        'yaff': 'yaff'}

    try:
        store = gf.Store(store_dir)
        for args in store.config.iter_extraction(gdef):
            gtr = store.get(args)
            if gtr:
                tr = trace.Trace(
                    '', '', '', util.zfmt(store.config.ncomponents) % args[-1],
                    ydata=gtr.data,
                    deltat=gtr.deltat,
                    tmin=gtr.deltat * gtr.itmin)

                additional = dict(
                    args='_'.join('%g' % x for x in args),
                    irecord=store.str_irecord(args),
                    extension=extensions[options.format])

                io.save(
                    tr,
                    options.output_fn,
                    format=options.format,
                    additional=additional)

    except (gf.meta.GridSpecError, gf.StoreError, gf.meta.OutOfBounds) as e:
        die(e)


def command_import(args):
    try:
        from tunguska import gfdb
    except ImportError:
        die('the kiwi tools must be installed to use this feature')

    parser, options, args = cl_parse('import', args)

    show_progress = True

    if not len(args) == 2:
        sys.exit(parser.format_help())

    source_path, dest_store_dir = args

    if op.isdir(source_path):
        source_path = op.join(source_path, 'db')

    source_path = re.sub(r'(\.\d+\.chunk|\.index)$', '', source_path)

    db = gfdb.Gfdb(source_path)

    config = gf.meta.ConfigTypeA(
        id='imported_gfs',
        distance_min=db.firstx,
        distance_max=db.firstx + (db.nx-1) * db.dx,
        distance_delta=db.dx,
        source_depth_min=db.firstz,
        source_depth_max=db.firstz + (db.nz-1) * db.dz,
        source_depth_delta=db.dz,
        sample_rate=1.0/db.dt,
        ncomponents=db.ng
    )

    try:
        gf.store.Store.create(dest_store_dir, config=config)
        dest = gf.Store(dest_store_dir, 'w')
        try:
            if show_progress:
                pbar = util.progressbar(
                    'importing', dest.config.nrecords/dest.config.ncomponents)

            for i, args in enumerate(dest.config.iter_nodes(level=-1)):
                source_depth, distance = [float(x) for x in args]
                traces = db.get_traces_pyrocko(distance, source_depth)
                ig_to_trace = dict((tr.meta['ig']-1, tr) for tr in traces)
                for ig in range(db.ng):
                    if ig in ig_to_trace:
                        tr = ig_to_trace[ig]
                        gf_tr = gf.store.GFTrace(
                            tr.get_ydata(),
                            int(round(tr.tmin / tr.deltat)),
                            tr.deltat)

                    else:
                        gf_tr = gf.store.Zero

                    dest.put((source_depth, distance, ig), gf_tr)

                if show_progress:
                    pbar.update(i+1)

        finally:
            if show_progress:
                pbar.finish()

        dest.close()

    except gf.StoreError as e:
        die(e)


def command_export(args):
    from subprocess import Popen, PIPE

    try:
        from tunguska import gfdb
    except ImportError as err:
        die('the kiwi tools must be installed to use this feature', err)

    def setup(parser):
        parser.add_option(
            '--nchunks', dest='nchunks', type='int', default=1, metavar='N',
            help='split output gfdb into N chunks')

    parser, options, args = cl_parse('export', args, setup=setup)

    show_progress = True

    if len(args) not in (1, 2):
        sys.exit(parser.format_help())

    target_path = args.pop()
    if op.isdir(target_path):
        target_path = op.join(target_path, 'kiwi_gfdb')
        logger.warning('exported gfdb will be named as "%s.*"' % target_path)

    source_store_dir = get_store_dir(args)

    source = gf.Store(source_store_dir, 'r')
    config = source.config

    if not isinstance(config, gf.meta.ConfigTypeA):
        die('only stores of type A can be exported to Kiwi format')

    if op.isfile(target_path + '.index'):
        die('destation already exists')

    cmd = [str(x) for x in [
        'gfdb_build',
        target_path,
        options.nchunks,
        config.ndistances,
        config.nsource_depths,
        config.ncomponents,
        config.deltat,
        config.distance_delta,
        config.source_depth_delta,
        config.distance_min,
        config.source_depth_min]]

    p = Popen(cmd, stdin=PIPE)
    p.communicate()

    out_db = gfdb.Gfdb(target_path)

    try:
        if show_progress:
            pbar = util.progressbar(
                'exporting', config.nrecords/config.ncomponents)

        for i, (z, x) in enumerate(config.iter_nodes(level=-1)):

            data_out = []
            for ig in range(config.ncomponents):
                try:
                    tr = source.get((z, x, ig), interpolation='off')
                    data_out.append((tr.t, tr.data * config.factor))

                except gf.store.StoreError as e:
                    logger.warning(
                        'cannot get %s, (%s)' % (sindex((z, x, ig)), e))
                    data_out.append(None)

            # put a zero valued sample to no-data zero-traces at a compatible
            # time
            tmins = [
                entry[0][0]
                for entry in data_out
                if entry is not None and entry[0].size != 0]

            if tmins:
                tmin = min(tmins)
                for entry in data_out:
                    if entry is not None and entry[0].size == 0:
                        entry[0].resize(1)
                        entry[1].resize(1)
                        entry[0][0] = tmin
                        entry[1][0] = 0.0

            out_db.put_traces_slow(x, z, data_out)

            if show_progress:
                pbar.update(i+1)

        source.close()

    finally:
        if show_progress:
            pbar.finish()


def phasedef_or_horvel(x):
    try:
        return float(x)
    except ValueError:
        return cake.PhaseDef(x)


def mkp(s):
    return [phasedef_or_horvel(ps) for ps in s.split(',')]


def stored_attribute_table_plots(phase_ids, options, args, attribute):
    import numpy as num
    from pyrocko.plot.cake_plot import labelspace, xscaled, yscaled, mpl_init

    plt = mpl_init()

    np = 1
    store_dir = get_store_dir(args)
    for phase_id in phase_ids:
        try:
            store = gf.Store(store_dir)

            if options.receiver_depth is not None:
                receiver_depth = options.receiver_depth * 1000.0
            else:
                if isinstance(store.config, (gf.ConfigTypeA, gf.ConfigTypeC)):
                    receiver_depth = store.config.receiver_depth

                elif isinstance(store.config, gf.ConfigTypeB):
                    receiver_depth = store.config.receiver_depth_min

                else:
                    receiver_depth = 0.0

            phase = store.get_stored_phase(phase_id, attribute)
            axes = plt.subplot(2, len(phase_ids), np)
            labelspace(axes)
            xscaled(1. / km, axes)
            yscaled(1. / km, axes)
            x = None
            if isinstance(store.config, gf.ConfigTypeB):
                x = (receiver_depth, None, None)

            phase.plot_2d(axes, x=x)
            axes.set_title(phase_id)
            np += 1
        except gf.StoreError as e:
            die(e)

    axes = plt.subplot(2, 1, 2)
    num_d = 100
    distances = num.linspace(store.config.distance_min,
                             store.config.distance_max,
                             num_d)

    if options.source_depth is not None:
        source_depth = options.source_depth * km
    else:
        source_depth = store.config.source_depth_min + (
            store.config.source_depth_max - store.config.source_depth_min) / 2.

    if isinstance(store.config, gf.ConfigTypeA):
        attribute_vals = num.empty(num_d)
        for phase_id in phase_ids:
            attribute_vals[:] = num.NAN
            for i, d in enumerate(distances):
                if attribute == 'phase':
                    attribute_vals[i] = store.t(phase_id, (source_depth, d))
                    ylabel = 'TT [s]'
                else:
                    attribute_vals[i] = store.get_stored_attribute(
                        phase_id, options.attribute, (source_depth, d))
                    ylabel = '%s [deg]' % options.attribute

            axes.plot(distances / km, attribute_vals, label=phase_id)

        axes.set_title('source source_depth %s km' % (source_depth / km))
        axes.set_xlabel('distance [km]')
        axes.set_ylabel(ylabel)
        axes.legend()

    plt.tight_layout()
    mpl_show(plt)


def command_ttt(args):
    def setup(parser):
        parser.add_option(
            '--force', dest='force', action='store_true',
            help='overwrite existing files')

    parser, options, args = cl_parse('ttt', args, setup=setup)

    store_dir = get_store_dir(args)
    try:
        store = gf.Store(store_dir)
        store.make_travel_time_tables(force=options.force)

    except gf.StoreError as e:
        die(e)


def command_tttview(args):

    def setup(parser):
        parser.add_option(
            '--source-depth', dest='source_depth', type=float,
            help='Source depth in km')

        parser.add_option(
            '--receiver-depth', dest='receiver_depth', type=float,
            help='Receiver depth in km')

    parser, options, args = cl_parse(
        'tttview', args, setup=setup,
        details="Comma seperated <phase-ids>, eg. 'fomosto tttview Pdiff,S'.")

    try:
        phase_ids = args.pop().split(',')
    except Exception:
        parser.error('cannot get <phase-ids> argument')

    stored_attribute_table_plots(phase_ids, options, args, attribute='phase')


def command_sat(args):
    def setup(parser):
        parser.add_option(
            '--force', dest='force', action='store_true',
            help='overwrite existing files')

        parser.add_option(
            '--attribute',
            action='store',
            dest='attribute',
            type='choice',
            choices=gf.store.available_stored_tables[1::],
            default='takeoff_angle',
            help='calculate interpolation table for selected ray attributes.')

    parser, options, args = cl_parse('sat', args, setup=setup)

    store_dir = get_store_dir(args)
    try:
        store = gf.Store(store_dir)
        store.make_stored_table(options.attribute, force=options.force)

    except gf.StoreError as e:
        die(e)


def command_satview(args):

    def setup(parser):
        parser.add_option(
            '--source-depth', dest='source_depth', type=float,
            help='Source depth in km')

        parser.add_option(
            '--receiver-depth', dest='receiver_depth', type=float,
            help='Receiver depth in km')

        parser.add_option(
            '--attribute',
            action='store',
            dest='attribute',
            type='choice',
            choices=gf.store.available_stored_tables[1::],
            default='takeoff_angle',
            help='view selected ray attribute.')

    parser, options, args = cl_parse(
        'satview', args, setup=setup,
        details="Comma seperated <phase-ids>, eg. 'fomosto satview Pdiff,S'.")

    try:
        phase_ids = args.pop().split(',')
    except Exception:
        parser.error('cannot get <phase-ids> argument')

    logger.info('Plotting stored attribute %s' % options.attribute)

    stored_attribute_table_plots(
        phase_ids, options, args, attribute=options.attribute)


def command_tttextract(args):
    def setup(parser):
        parser.add_option(
            '--output', dest='output_fn', metavar='TEMPLATE',
            help='output to text files instead of stdout '
                 '(example TEMPLATE: "extracted/%(args)s.txt")')

    parser, options, args = cl_parse('tttextract', args, setup=setup)
    try:
        sdef = args.pop()
    except Exception:
        parser.error('cannot get <selection> argument')

    try:
        sphase = args.pop()
    except Exception:
        parser.error('cannot get <phase> argument')

    try:
        phases = [gf.meta.Timing(x.strip()) for x in sphase.split(',')]
    except gf.meta.InvalidTimingSpecification:
        parser.error('invalid phase specification: "%s"' % sphase)

    try:
        gdef = gf.meta.parse_grid_spec(sdef)
    except gf.meta.GridSpecError as e:
        die(e)

    store_dir = get_store_dir(args)

    try:
        store = gf.Store(store_dir)
        for args in store.config.iter_extraction(gdef, level=-1):
            s = ['%e' % x for x in args]
            for phase in phases:
                t = store.t(phase, args)
                if t is not None:
                    s.append('%e' % t)
                else:
                    s.append('nan')

            if options.output_fn:
                d = dict(
                    args='_'.join('%e' % x for x in args),
                    extension='txt')

                fn = options.output_fn % d
                util.ensuredirs(fn)
                with open(fn, 'a') as f:
                    f.write(' '.join(s))
                    f.write('\n')
            else:
                print(' '.join(s))

    except (gf.meta.GridSpecError, gf.StoreError, gf.meta.OutOfBounds) as e:
        die(e)


def command_tttlsd(args):

    def setup(parser):
        pass

    parser, options, args = cl_parse('tttlsd', args, setup=setup)

    try:
        sphase_ids = args.pop()
    except Exception:
        parser.error('cannot get <phase> argument')

    try:
        phase_ids = [x.strip() for x in sphase_ids.split(',')]
    except gf.meta.InvalidTimingSpecification:
        parser.error('invalid phase specification: "%s"' % sphase_ids)

    store_dir = get_store_dir(args)

    try:
        store = gf.Store(store_dir)
        for phase_id in phase_ids:
            store.fix_ttt_holes(phase_id)

    except gf.StoreError as e:
        die(e)


def command_server(args):
    from pyrocko.gf import server

    def setup(parser):
        parser.add_option(
            '--port', dest='port', metavar='PORT', type='int', default=8080,
            help='serve on port PORT')

        parser.add_option(
            '--ip', dest='ip', metavar='IP', default='',
            help='serve on ip address IP')

    parser, options, args = cl_parse('server', args, setup=setup)

    engine = gf.LocalEngine(store_superdirs=args)
    server.run(options.ip, options.port, engine)


def command_download(args):
    from pyrocko.gf import ws

    details = '''

Browse pre-calculated Green's function stores online:

  https://greens-mill.pyrocko.org
'''

    def setup(parser):
        parser.add_option(
            '--force', dest='force', action='store_true',
            help='overwrite existing files')

    parser, options, args = cl_parse(
        'download', args, setup=setup, details=details)
    if len(args) not in (1, 2):
        sys.exit(parser.format_help())

    if len(args) == 2:
        site, store_id = args
        if not re.match(gf.meta.StringID.pattern, store_id):
            die('invalid store ID')
    else:
        site, store_id = args[0], None

    if site not in gf.ws.g_site_abbr:
        if -1 == site.find('://'):
            site = 'http://' + site

    try:
        ws.download_gf_store(site=site, store_id=store_id, force=options.force)
    except ws.DownloadError as e:
        die(str(e))


def command_modelview(args):

    import matplotlib.pyplot as plt
    import numpy as num
    from pyrocko.plot.cake_plot import mpl_init, labelspace, xscaled, yscaled
    mpl_init()

    neat_labels = {
        'vp': '$v_p$',
        'vs': '$v_s$',
        'qp': '$Q_p$',
        'qs': '$Q_s$',
        'rho': '$\\rho$'}

    def setup(parser):
        parser.add_option(
            '--parameters', dest='parameters',
            default='vp,vs', metavar='vp,vs,....',
            help='select one or several of vp, vs, rho, qp, qs, vp/vs, qp/qs')

    units = {'vp': '[km/s]', 'vs': '[km/s]', 'rho': '[g/cm^3]'}

    parser, options, args = cl_parse('modelview', args, setup=setup)

    store_dirs = get_store_dirs(args)

    parameters = options.parameters.split(',')

    fig, axes = plt.subplots(1,
                             len(parameters),
                             sharey=True,
                             figsize=(len(parameters)*3, 5))

    if not isinstance(axes, num.ndarray):
        axes = [axes]

    axes = dict(zip(parameters, axes))

    for store_id in store_dirs:
        try:
            store = gf.Store(store_id)
            mod = store.config.earthmodel_1d
            z = mod.profile('z')

            for p in parameters:
                ax = axes[p]
                labelspace(ax)
                if '/' in p:
                    p1, p2 = p.split('/')
                    profile = mod.profile(p1)/mod.profile(p2)
                else:
                    profile = mod.profile(p)

                ax.plot(profile, -z, label=store_id.split('/')[-1])
                if p in ['vs', 'vp', 'rho']:
                    xscaled(1./1000., ax)

                yscaled(1./km, ax)

        except gf.StoreError as e:
            die(e)

    for p, ax in axes.items():
        ax.grid()
        if p in neat_labels:
            lab = neat_labels[p]
        elif all(x in neat_labels for x in p.split('/')):
            lab = '/'.join(neat_labels[x] for x in p.split('/'))
        else:
            lab = p

        ax.set_title(lab, y=1.02)

        if p in units:
            lab += ' ' + units[p]

        ax.autoscale()
        ax.set_xlabel(lab)

    axes[parameters[0]].set_ylabel('Depth [km]')

    handles, labels = ax.get_legend_handles_labels()

    if len(store_dirs) > 1:
        ax.legend(
            handles,
            labels,
            bbox_to_anchor=(0.5, 0.12),
            bbox_transform=fig.transFigure,
            ncol=3,
            loc='upper center',
            fancybox=True)

    plt.subplots_adjust(bottom=0.22,
                        wspace=0.05)

    mpl_show(plt)


def command_upgrade(args):
    parser, options, args = cl_parse('upgrade', args)
    store_dirs = get_store_dirs(args)
    try:
        for store_dir in store_dirs:
            store = gf.Store(store_dir)
            nup = store.upgrade()
            if nup == 0:
                print('%s: already up-to-date.' % store_dir)
            else:
                print('%s: %i file%s upgraded.' % (
                    store_dir, nup, ['s', ''][nup == 1]))

    except gf.StoreError as e:
        die(e)


def command_addref(args):
    parser, options, args = cl_parse('addref', args)

    store_dirs = []
    filenames = []
    for arg in args:
        if op.isdir(arg):
            store_dirs.append(arg)
        elif op.isfile(arg):
            filenames.append(arg)
        else:
            die('invalid argument: %s' % arg)

    if not store_dirs:
        store_dirs.append('.')

    references = []
    try:
        for filename in args:
            references.extend(gf.meta.Reference.from_bibtex(filename=filename))
    except ImportError:
        die('pybtex module must be installed to use this function')

    if not references:
        die('no references found')

    for store_dir in store_dirs:
        try:
            store = gf.Store(store_dir)
            ids = [ref.id for ref in store.config.references]
            for ref in references:
                if ref.id in ids:
                    die('duplicate reference id: %s' % ref.id)

                ids.append(ref.id)
                store.config.references.append(ref)

            store.save_config(make_backup=True)

        except gf.StoreError as e:
            die(e)


def command_qc(args):
    parser, options, args = cl_parse('qc', args)

    store_dir = get_store_dir(args)

    try:
        store = gf.Store(store_dir)
        s = store.stats()
        if s['empty'] != 0:
            print('has empty records')

        for aname in ['author', 'author_email', 'description', 'references']:

            if not getattr(store.config, aname):
                print('%s empty' % aname)

    except gf.StoreError as e:
        die(e)


def command_report(args):
    from pyrocko.fomosto.report import report_call
    report_call.run_program(args)


def main(args=None):
    '''
    CLI entry point for Pyrocko's ``fomosto`` app.
    '''
    if args is None:
        args = sys.argv[1:]

    if len(args) < 1:
        sys.exit('Usage: %s' % usage)

    command = args.pop(0)

    if command in subcommands:
        globals()['command_' + command](args)

    elif command in ('--help', '-h', 'help'):
        if command == 'help' and args:
            acommand = args[0]
            if acommand in subcommands:
                globals()['command_' + acommand](['--help'])

        sys.exit('Usage: %s' % usage)

    else:
        sys.exit('fomosto: error: no such subcommand: %s' % command)


if __name__ == '__main__':
    main()
