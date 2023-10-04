# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
User configuration file handling.
'''

import os
import os.path as op
from copy import deepcopy
import logging

from . import util
from .guts import Object, Float, String, load, dump, List, Dict, TBase, \
    Tuple, StringChoice, Bool


logger = logging.getLogger('pyrocko.config')

guts_prefix = 'pf'

pyrocko_dir_tmpl = os.environ.get(
    'PYROCKO_DIR',
    os.path.join('~', '.pyrocko'))


def make_conf_path_tmpl(name='config'):
    return op.join(pyrocko_dir_tmpl, '%s.pf' % name)


default_phase_key_mapping = {
    'F1': 'P', 'F2': 'S', 'F3': 'R', 'F4': 'Q', 'F5': '?'}


class BadConfig(Exception):
    pass


class PathWithPlaceholders(String):
    '''
    Path, possibly containing placeholders.
    '''
    pass


class VisibleLengthSetting(Object):
    class __T(TBase):
        def regularize_extra(self, val):
            if isinstance(val, list):
                return self._cls(key=val[0], value=val[1])

            return val

        def to_save(self, val):
            return (val.key, val.value)

        def to_save_xml(self, val):
            raise NotImplementedError()

    key = String.T()
    value = Float.T()


class ConfigBase(Object):
    @classmethod
    def default(cls):
        return cls()


class SnufflerConfig(ConfigBase):
    visible_length_setting = List.T(
        VisibleLengthSetting.T(),
        default=[VisibleLengthSetting(key='Short', value=20000.),
                 VisibleLengthSetting(key='Medium', value=60000.),
                 VisibleLengthSetting(key='Long', value=120000.),
                 VisibleLengthSetting(key='Extra Long', value=600000.)])
    phase_key_mapping = Dict.T(
        String.T(), String.T(), default=default_phase_key_mapping)
    demean = Bool.T(default=True)
    show_scale_ranges = Bool.T(default=False)
    show_scale_axes = Bool.T(default=False)
    trace_scale = String.T(default='individual_scale')
    show_boxes = Bool.T(default=True)
    clip_traces = Bool.T(default=True)
    first_start = Bool.T(default=True)

    def get_phase_name(self, key):
        return self.phase_key_mapping.get('F%s' % key, 'Undefined')


class PyrockoConfig(ConfigBase):
    cache_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'cache'))
    earthradius = Float.T(default=6371.*1000.)
    fdsn_timeout = Float.T(default=None, optional=True)
    gf_store_dirs = List.T(PathWithPlaceholders.T())
    gf_store_superdirs = List.T(PathWithPlaceholders.T())
    topo_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'topo'))
    tectonics_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'tectonics'))
    geonames_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'geonames'))
    crustdb_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'crustdb'))
    gshhg_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'gshhg'))
    volcanoes_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'volcanoes'))
    fault_lines_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'fault_lines'))
    colortables_dir = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'colortables'))
    leapseconds_path = PathWithPlaceholders.T(
        default=os.path.join(pyrocko_dir_tmpl, 'leap-seconds.list'))
    leapseconds_url = String.T(
        default='https://hpiers.obspm.fr/iers/bul/bulc/ntp/leap-seconds.list')
    earthdata_credentials = Tuple.T(
        2, String.T(),
        optional=True)
    gui_toolkit = StringChoice.T(
        choices=['auto', 'qt4', 'qt5'],
        default='auto')
    use_high_precision_time = Bool.T(default=False)


config_cls = {
    'config': PyrockoConfig,
    'snuffler': SnufflerConfig
}


def fill_template(tmpl, config_type):
    tmpl = tmpl .format(
        module=('.' + config_type) if config_type != 'pyrocko' else '')
    return tmpl


def expand(x):
    x = op.expanduser(op.expandvars(x))
    return x


def rec_expand(x):
    for prop, val in x.T.ipropvals(x):
        if prop.multivalued:
            if val is not None:
                for i, ele in enumerate(val):
                    if isinstance(prop.content_t, PathWithPlaceholders.T):
                        newele = expand(ele)
                        if newele != ele:
                            val[i] = newele

                    elif isinstance(ele, Object):
                        rec_expand(ele)
        else:
            if isinstance(prop, PathWithPlaceholders.T):
                newval = expand(val)
                if newval != val:
                    setattr(x, prop.name, newval)

            elif isinstance(val, Object):
                rec_expand(val)


def processed(config):
    config = deepcopy(config)
    rec_expand(config)
    return config


def mtime(p):
    return os.stat(p).st_mtime


g_conf_mtime = {}
g_conf = {}


def raw_config(config_name='config'):

    conf_path = expand(make_conf_path_tmpl(config_name))

    if not op.exists(conf_path):
        g_conf[config_name] = config_cls[config_name].default()
        write_config(g_conf[config_name], config_name)

    conf_mtime_now = mtime(conf_path)
    if conf_mtime_now != g_conf_mtime.get(config_name, None):
        g_conf[config_name] = load(filename=conf_path)
        if not isinstance(g_conf[config_name], config_cls[config_name]):
            with open(conf_path, 'r') as fconf:
                logger.warning('Config file content:')
                for line in fconf:
                    logger.warning('   ' + line)

            raise BadConfig('config file does not contain a '
                            'valid "%s" section. Found: %s' % (
                                config_cls[config_name].__name__,
                                type(g_conf[config_name])))

        g_conf_mtime[config_name] = conf_mtime_now

    return g_conf[config_name]


def config(config_name='config'):
    return processed(raw_config(config_name))


def write_config(conf, config_name='config'):
    conf_path = expand(make_conf_path_tmpl(config_name))
    util.ensuredirs(conf_path)
    dump(conf, filename=conf_path)


override_gui_toolkit = None


def effective_gui_toolkit():
    return override_gui_toolkit or config().gui_toolkit


if __name__ == '__main__':
    print(config())
