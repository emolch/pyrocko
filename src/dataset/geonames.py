# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Access to the cities and population data of
`GeoNames <https://www.geonames.org/>`_.

The GeoNames geographical database covers all countries and contains over
eleven million placenames.

This module provides quick access to a subset of GeoNames containing the cities
with a population size exceeding 1000.
'''

import logging
import os
from collections import namedtuple
import os.path as op

import numpy as num

from pyrocko import util, config
from pyrocko import orthodrome as od
from pyrocko.util import urlopen

logger = logging.getLogger('pyrocko.dataset.geonames')

GeoName = namedtuple('GeoName', '''
geonameid
name
asciiname
alt_names
lat
lon
feature_class
feature_code
country_code
alt_country_code
admin1_code
admin2_code
admin3_code
admin4_code
population
elevation
dem
timezone
modification_date'''.split())

GeoName2 = namedtuple('GeoName2', '''
name
asciiname
lat
lon
population
feature_code
'''.split())

base_url = 'https://mirror.pyrocko.org/download.geonames.org/export/dump/'


def download_file(fn, dirpath):
    url = base_url + '/' + fn
    fpath = op.join(dirpath, fn)
    logger.info('starting download of %s' % url)

    util.ensuredirs(fpath)
    f = urlopen(url)
    fpath_tmp = fpath + '.%i.temp' % os.getpid()
    g = open(fpath_tmp, 'wb')
    while True:
        data = f.read(1024)
        if not data:
            break
        g.write(data)

    g.close()
    f.close()

    os.rename(fpath_tmp, fpath)

    logger.info('finished download of %s' % url)


def positive_region(region):
    west, east, south, north = [float(x) for x in region]

    assert -180. - 360. <= west < 180.
    assert -180. < east <= 180. + 360.
    assert -90. <= south < 90.
    assert -90. < north <= 90.

    if east < west:
        east += 360.

    if west < -180.:
        west += 360.
        east += 360.

    return (west, east, south, north)


def ascii_str(u):
    return u.encode('ascii', 'replace')


def load(zfn, fn, minpop=1000000, region=None):
    geonames_dir = config.config().geonames_dir
    filepath = op.join(geonames_dir, zfn or fn)
    if not os.path.exists(filepath):
        download_file(zfn or fn, geonames_dir)

    if region:
        w, e, s, n = positive_region(region)

    if zfn is not None:
        import zipfile
        z = zipfile.ZipFile(filepath, 'r')
        f = z.open(fn, 'r')
    else:
        z = None
        f = open(filepath, 'rb')

    for line in f:
        t = line.split(b'\t')
        pop = int(t[14])
        if minpop <= pop:
            lat = float(t[4])
            lon = float(t[5])
            feature_code = str(t[7].decode('ascii'))
            if not region or (
                    (w <= lon <= e or w <= lon + 360. <= e)
                    and (s <= lat <= n)):

                yield GeoName2(
                    t[1].decode('utf8'),
                    str(t[2].decode('utf8').encode('ascii', 'replace')
                        .decode('ascii')),
                    lat, lon, pop, feature_code)

    f.close()
    if z is not None:
        z.close()


g_cities = {}


def load_all_keep(zfn, fn, minpop=1000000, region=None, exclude=()):
    if (zfn, fn) not in g_cities:
        g_cities[zfn, fn] = list(load(zfn, fn, minpop=0))

    if region:
        w, e, s, n = positive_region(region)
        return [c for c in g_cities[zfn, fn]
                if (minpop <= c.population and
                    ((w <= c.lon <= e or w <= c.lon + 360. <= e)
                        and (s <= c.lat <= n)) and
                    c.feature_code not in exclude)]

    else:
        return [c for c in g_cities[zfn, fn] if (
            minpop <= c.population and c.feature_code not in exclude)]


def get_cities_region(region=None, minpop=0):
    return load_all_keep(
        'cities1000.zip', 'cities1000.txt',
        region=region,
        minpop=minpop,
        exclude=('PPLX',))


def get_cities_by_name(name):
    '''
    Lookup city by name.

    The comparison is done case-insensitive.

    :param name:
        Name of the city to look for.
    :type name:
        str

    :returns:
        Zero or more matching city entries.
    :rtype:
        :py:class:`list` of :py:class:`GeoName2`
    '''
    cities = get_cities_region()
    candidates = []
    for c in cities:
        if c.asciiname.lower() == name.lower():
            candidates.append(c)

    return candidates


def get_cities(lat, lon, radius, minpop=0):
    '''
    Get cities in a given circular area.

    :param lat:
        Latitude [deg].
    :type lat:
        float

    :param lon:
        Longitude [deg].
    :type lon:
        float

    :param radius:
        Search radius [m].
    :type radius:
        float

    :param minpop:
        Skip entries with population lower than this.
    :type minpop:
        int

    :returns:
        Matching city entries.
    :rtype:
        :py:class:`list` of :py:class:`GeoName2`
    '''
    region = od.radius_to_region(lat, lon, radius)
    cities = get_cities_region(region, minpop=minpop)

    clats = num.array([c.lat for c in cities])
    clons = num.array([c.lon for c in cities])

    dists = od.distance_accurate50m_numpy(lat, lon, clats, clons)
    order = num.argsort(dists)
    cities_sorted = [cities[i] for i in order if dists[i] < radius]
    return cities_sorted
