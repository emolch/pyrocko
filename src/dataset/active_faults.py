# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import

import re
import logging
import numpy as num
from os import path as op
from collections import OrderedDict
import json

from pyrocko import config, util


def parse_3tup(s):
    m = re.match(r'^\(?([^,]+),([^,]*),([^,]*)\)$', s)
    if m:
        return [float(m.group(1)) if m.group(1) else None for i in range(3)]
    else:
        return [None, None, None]


logger = logging.getLogger('ActiveFaults')


class Fault(object):
    __fields__ = OrderedDict()
    __slots__ = list(__fields__.keys())

    def get_property(self, fault_obj, attr):
        try:
            values = float(fault_obj['properties'][attr][1:3])
        except KeyError:
            if attr == 'lower_seis_depth' or attr == 'upper_seis_depth':
                values = 0
            else:
                values = -999
        return values

    def __init__(self, f):
        nodes = f['geometry']['coordinates']
        props = f['properties']
        lons = [p[0] for p in nodes]
        lats = [p[1] for p in nodes]
        self.lon = lons
        self.lat = lats
        self.slip_type = props.get('slip_type', 'Unknown')

        for attr, attr_type in self.__fields__.items():
            if attr in props:
                if props[attr] is None or props[attr] == '':
                    continue

                if isinstance(props[attr], attr_type):
                    v = props[attr]

                elif attr_type is float:
                    try:
                        v = parse_3tup(props[attr])[0]
                    except TypeError:
                        v = float(props[attr])

                elif attr_type is int:
                    v = int(props[attr])

                else:
                    v = None

                setattr(self, attr, v)

    def get_surface_line(self):
        arr = num.empty((len(self.lat), 2))
        for i in range(len(self.lat)):
            arr[i, 0] = self.lat[i]
            arr[i, 1] = self.lon[i]

        return arr

    def __str__(self):
        d = {attr: getattr(self, attr) for attr in self.__fields__.keys()}
        return '\n'.join(['%s: %s' % (attr, val) for attr, val in d.items()])


class ActiveFault(Fault):
    __fields__ = OrderedDict([

        ('lat', list),
        ('lon', list),
        ('average_dip', float),
        ('average_rake', float),
        ('lower_seis_depth', float),
        ('upper_seis_depth', float),
        ('slip_type', str),
    ])


class ActiveFaults(object):
    URL_GEM_ACTIVE_FAULTS = 'https://raw.githubusercontent.com/cossatot/gem-global-active-faults/master/geojson/gem_active_faults.geojson'  # noqa

    def __init__(self):
        self.fname_active_faults = op.join(
            config.config().fault_lines_dir, 'gem_active_faults.geojson')

        if not op.exists(self.fname_active_faults):
            self.download()

        self.active_faults = []
        self._load_faults(self.fname_active_faults, ActiveFault)

    def _load_faults(self, fname, cls):
        with open(fname, 'r') as f:
            gj = json.load(f)
            faults = gj['features']
            for f in faults:
                fault = cls(f)
                self.active_faults.append(fault)
        logger.debug('loaded %d fault', self.nactive_faults)

    def download(self):
        logger.info('Downloading GEM active faults database...')
        util.download_file(self.URL_GEM_ACTIVE_FAULTS,
                           self.fname_active_faults)

    @property
    def nactive_faults(self):
        return len(self.active_faults)

    def nactive_faults_nodes(self):
        return int(sum(len(f.lat) for f in self.active_faults))

    def get_coords(self):
        return num.array([f['coordinates'] for f in self.active_faults])


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    activefaults = ActiveFaults()
