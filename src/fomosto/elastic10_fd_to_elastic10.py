import os
import logging
import shutil
from pyrocko import gf, guts, util


logger = logging.getLogger('main')


def elastic10_fd_to_elastic10(
        source_store_dir,
        dest_store_dir,
        show_progress=True):

    def _raise(message):
        raise gf.StoreError('elastic10_fd_to_elastic10: %s' % message)

    source = gf.Store(source_store_dir)

    if source.config.component_scheme != 'elastic10_fd':
        _raise(
            'Only `elastic10_fd` component scheme supported for input store.')

    if source.config.short_type != 'A':
        _raise(
            'Only type A stores supported for input store.')

    if not os.path.exists(dest_store_dir):
        config = guts.clone(source.config)
        config.id += '_from_fd'
        config.__dict__['ncomponents'] = 10
        config.__dict__['component_scheme'] = 'elastic10'
        config.fd_distance_delta = None

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

    if show_progress:
        pbar = util.progressbar(
            'elastic10_to_rotational8',
            source.config.nrecords/source.config.ncomponents)

    try:
        for i, args in enumerate(dest.config.iter_nodes(level=-1)):
            for ig in range(10):
                tr = source.get(args + (ig+10,))
                dest.put(args + (ig,), tr)

            if show_progress:
                pbar.update(i+1)

    finally:
        if show_progress:
            pbar.finish()
