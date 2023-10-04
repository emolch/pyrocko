# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Volcanoes of the World dataset from the Smithsonian Institution (`VOTW
<https://volcano.si.edu/gvp_votw.cfm>`_).
'''

import csv
import logging
import numpy as num
from os import path as op
from collections import OrderedDict

from pyrocko import config, util
from .util import get_download_callback

logger = logging.getLogger('volcanoes')

citation = '''
Global Volcanism Program, 2013. Volcanoes of the World,
v. 4.8.5. Venzke, E (ed.). Smithsonian Institution. Downloaded 29 Jan 2020.
https://doi.org/10.5479/si.GVP.VOTW4-2013 '''


__doc__ += '''

.. rubric:: Citation
''' + citation


class Volcano(object):
    age = None

    __fields__ = OrderedDict()
    __slots__ = list(__fields__.keys())

    def __init__(self, *args):
        for (attr, attr_type), value in zip(self.__fields__.items(), args):
            if attr_type in (int, float):
                if not value or value == '?':
                    value = 0.
            try:
                setattr(self, attr, attr_type(value))
            except ValueError as e:
                print(list(zip(self.__fields__.keys(), args)))
                raise e

    def __str__(self):
        d = {attr: getattr(self, attr) for attr in self.__fields__.keys()}
        return '\n'.join(['%s: %s' % (attr, val) for attr, val in d.items()])


class VolcanoHolocene(Volcano):
    age = 'holocene'

    __fields__ = OrderedDict([
        ('fid', str),
        ('volcano_number', int),
        ('volcano_name', str),
        ('primary_volcano_type', str),
        ('last_eruption_year', int),
        ('country', str),
        ('geological_summary', str),
        ('region', str),
        ('subregion', str),
        ('lat', float),
        ('lon', float),
        ('elevation', float),
        ('tectonic_setting', str),
        ('geologic_epoch', str),
        ('evidence_category', str),
        ('primary_photo_link', str),
        ('primary_photo_caption', str),
        ('primary_photo_credit', str),
        ('major_rock_type', str),
        ('geolocation', str),
    ])


class VolcanoPleistocene(Volcano):
    age = 'pleistocene'

    __fields__ = OrderedDict([
        ('fid', str),
        ('volcano_number', int),
        ('volcano_name', str),
        ('primary_volcano_type', str),
        ('country', str),
        ('geological_summary', str),
        ('region', str),
        ('subregion', str),
        ('lat', float),
        ('lon', float),
        ('elevation', float),
        ('geologic_epoch', str),
        ('geolocation', str),
    ])


class Volcanoes(object):
    '''
    Volcanoes of the World.
    '''
    URL_HOLOCENE = 'https://mirror.pyrocko.org/smithsonian/smithsonian-holocene.csv'  # noqa
    URL_PLEISTOCENE = 'https://mirror.pyrocko.org/smithsonian/smithsonian-pleistocene.csv'  # noqa

    def __init__(self):
        self.fname_holocene = op.join(
            config.config().volcanoes_dir, 'smithsonian-holocene.csv')
        self.fname_pleistocene = op.join(
            config.config().volcanoes_dir, 'smithsonian-pleistocene.csv')

        if not op.exists(self.fname_holocene) \
                or not op.exists(self.fname_pleistocene):
            self.download()

        self.volcanoes = []
        self._load_volcanoes(self.fname_holocene, VolcanoHolocene)
        self._load_volcanoes(self.fname_pleistocene, VolcanoPleistocene)

    def _load_volcanoes(self, fname, cls):
        with open(fname, 'r', encoding='utf8') as f:
            next(f)  # skip header
            reader = csv.reader(f, dialect='unix')
            for row in reader:
                volcano = cls(*row)
                self.volcanoes.append(volcano)
        logger.debug('loaded %d volcanoes', self.nvolcanoes)

    def download(self):
        logger.info('Downloading Holocene volcanoes...')
        util.download_file(
            self.URL_HOLOCENE, self.fname_holocene,
            status_callback=get_download_callback(
                'Downloading Holocene volcanoe database...'))

        logger.info('Downloading Pleistocene volcanoes...')
        util.download_file(
            self.URL_PLEISTOCENE, self.fname_pleistocene,
            status_callback=get_download_callback(
                'Downloading Pleistocene volcanoe database...'))

    @property
    def volcanoes_holocene(self):
        return [v for v in self.volcanoes if isinstance(v, VolcanoHolocene)]

    @property
    def volcanoes_pleistocene(self):
        return [v for v in self.volcanoes if isinstance(v, VolcanoPleistocene)]

    @property
    def nvolcanoes(self):
        return len(self.volcanoes)

    @property
    def nvolcanoes_holocene(self):
        return len(self.volcanoes_holocene)

    @property
    def nvolcanoes_pleistocene(self):
        return len(self.volcanoes_pleistocene)

    def get_coords(self):
        return num.array([(v.lat, v.lon) for v in self.volcanoes])

    def get_names(self):
        return [v.volcano_name for v in self.volcanoes]


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    volc = Volcanoes()
    print(volc.volcanoes[0])
