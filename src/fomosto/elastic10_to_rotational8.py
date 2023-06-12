import os
import logging
import shutil
from pyrocko import gf, guts, util
import numpy as num


logger = logging.getLogger('main')


def a(*args):
    return num.array(args, dtype=float)


def ai(*args):
    return num.array(args, dtype=int)


def almost_equal(a, b, eps):
    return abs(a - b < eps)


def configure_diff(x, xmin, xmax, dx):
    if almost_equal(x, xmin, 1e-6*dx):
        return dx, 0.
    elif almost_equal(x, xmax, 1e-6*dx):
        return 0., dx
    else:
        return dx, dx


def sindex(args):
    return '(%s)' % ', '.join('%g' % x for x in args)


def elastic10_to_rotational8(
        source_store_dir,
        dest_store_dir,
        show_progress=True):

    def _raise(message):
        raise gf.StoreError('elastic10_to_rotational8: %s' % message)

    source = gf.Store(source_store_dir)

    if source.config.component_scheme not in ('elastic10', 'elastic10_fd'):
        _raise(
            'Only `elastic10` and `elastic10_fd` component schemes supported '
            'for input store.')

    have_fd_components = source.config.component_scheme == 'elastic10_fd'

    if source.config.effective_stored_quantity != 'displacement':
        _raise('Stored quantity of input store must be displacement.')

    if not os.path.exists(dest_store_dir):
        config = guts.clone(source.config)
        config.id += '_rotfd'
        config.__dict__['ncomponents'] = 8
        config.__dict__['component_scheme'] = 'rotational8'
        config.stored_quantity = 'rotation_displacement'
        config.fd_distance_delta = None
        if config.short_type == 'B':
            config.fd_receiver_depth_delta = None

        util.ensuredirs(dest_store_dir)
        gf.Store.create(dest_store_dir, config=config)
        shutil.copytree(
            os.path.join(source_store_dir, 'phases'),
            os.path.join(dest_store_dir, 'phases'))

    try:
        gf.store.Store.create_dependants(dest_store_dir)
    except gf.StoreError:
        pass

    dest = gf.Store(dest_store_dir, 'w')

    ta = source.config.short_type
    tb = dest.config.short_type

    if have_fd_components and not (ta, tb) == ('A', 'A'):
        _raise(
            'For input stores with component scheme `elastic10_fd`, only '
            'conversion from store type A to A is currently supported.')

    if (ta, tb) not in (('A', 'A'), ('B', 'B'), ('B', 'A')):
        _raise('Cannot convert type %s to type %s.' % (ta, tb))

    if source.config.distance_delta > dest.config.distance_delta:
        _raise(
            'Distance spacing of output store must be equal to or larger '
            'distance spacing of input store.')

    if (ta, tb) == ('B', 'B'):
        if source.config.receiver_depth_delta \
                > dest.config.receiver_depth_delta:
            _raise(
                'Depth spacing of output store must be equal to or larger '
                'depth spacing of input store.')

    if ta == 'A':
        if source.config.receiver_depth \
                != source.config.earthmodel_1d.discontinuity('surface').z:
            _raise(
                'When input store is of type A, receivers must be at the '
                'surface.')

    if have_fd_components:
        dx = source.config.fd_distance_delta
    else:
        dx = source.config.distance_delta

    if ta == 'B':
        dz = source.config.receiver_depth_delta
    else:
        dz = None

    if show_progress:
        pbar = util.progressbar(
            'elastic10_to_rotational8',
            source.config.nrecords/source.config.ncomponents)

    try:
        for i, args in enumerate(dest.config.iter_nodes(level=-1)):
            if ta == 'A':
                sz, x = args

                if have_fd_components:
                    dx1 = dx2 = dx
                else:
                    dx1, dx2 = configure_diff(
                        x,
                        source.config.distance_min,
                        source.config.distance_max,
                        dx)

                odx = dx1+dx2

                for ig, (sum_args, weights) in enumerate(zip(
                        [
                            (a(), a(), ai()),
                            (a(), a(), ai()),
                            (a(sz, sz), a(x, x), ai(25, 5)),
                            (a(sz, sz), a(x, x), ai(26, 6)),
                            (a(sz, sz), a(x, x), ai(27, 7)),
                            (a(sz, sz), a(x, x), ai(23, 3)),
                            (a(sz, sz), a(x, x), ai(24, 4)),
                            (a(sz, sz), a(x, x), ai(29, 9)),
                        ] if have_fd_components else [
                            (a(), a(), ai()),
                            (a(), a(), ai()),
                            (a(sz, sz), a(x+dx1, x-dx2), ai(5, 5)),
                            (a(sz, sz), a(x+dx1, x-dx2), ai(6, 6)),
                            (a(sz, sz), a(x+dx1, x-dx2), ai(7, 7)),
                            (a(sz, sz), a(x+dx1, x-dx2), ai(3, 3)),
                            (a(sz, sz), a(x+dx1, x-dx2), ai(4, 4)),
                            (a(sz, sz), a(x+dx1, x-dx2), ai(9, 9)),
                        ],
                        [
                            a(),
                            a(),
                            1.0 / a(-odx, odx),
                            1.0 / a(-odx, odx),
                            1.0 / a(-odx, odx),
                            0.5 / a(odx, -odx),
                            0.5 / a(odx, -odx),
                            1.0 / a(-odx, odx),
                        ])):

                    if weights.size == 0:
                        h = gf.GFTrace(is_zero=True, itmin=0)
                    else:
                        h = source.sum(
                            sum_args,
                            num.zeros_like(weights),
                            weights,
                            optimization='disable')

                    dest.put(args + (ig,), h)
            else:
                rz, sz, x = args

                dx1, dx2 = configure_diff(
                    x,
                    source.config.distance_min,
                    source.config.distance_max,
                    dx)

                dz1, dz2 = configure_diff(
                    rz,
                    source.config.receiver_depth_min,
                    source.config.receiver_depth_max,
                    dz)

                odx = dx1+dx2
                odz = dz1+dz2

                for ig, (sum_args, weights) in enumerate(zip(
                        [
                            (a(rz+dz1, rz-dz2), a(sz, sz), a(x, x), ai(3, 3)),
                            (a(rz+dz1, rz-dz2), a(sz, sz), a(x, x), ai(4, 4)),
                            (a(rz+dz1, rz-dz2, rz, rz), a(sz, sz, sz, sz), a(x, x, x+dx1, x-dx2), ai(0, 0, 5, 5)),  # noqa
                            (a(rz+dz1, rz-dz2, rz, rz), a(sz, sz, sz, sz), a(x, x, x+dx1, x-dx2), ai(1, 1, 6, 6)),  # noqa
                            (a(rz+dz1, rz-dz2, rz, rz), a(sz, sz, sz, sz), a(x, x, x+dx1, x-dx2), ai(2, 2, 7, 7)),  # noqa
                            (a(rz, rz), a(sz, sz), a(x+dx1, x-dx2), ai(3, 3)),
                            (a(rz, rz), a(sz, sz), a(x+dx1, x-dx2), ai(4, 4)),
                            (a(rz+dz1, rz-dz2, rz, rz), a(sz, sz, sz, sz), a(x, x, x+dx1, x-dx2), ai(8, 8, 9, 9)),  # noqa
                        ],
                        [
                            0.5 / a(-odz, odz),
                            0.5 / a(-odz, odz),
                            0.5 / a(odz, -odz, -odx, odx),
                            0.5 / a(odz, -odz, -odx, odx),
                            0.5 / a(odz, -odz, -odx, odx),
                            0.5 / a(odx, -odx),
                            0.5 / a(odx, -odx),
                            0.5 / a(odz, -odz, -odx, odx),
                        ])):

                    h = source.sum(
                        sum_args,
                        num.zeros_like(weights),
                        weights,
                        optimization='disable')

                    dest.put(args + (ig,), h)

            if show_progress:
                pbar.update(i+1)

    finally:
        if show_progress:
            pbar.finish()
