# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Strain rate (`GSRM1 <https://gsrm.unavco.org/>`_) and plate boundaries
(`PeterBird2003
<http://peterbird.name/publications/2003_PB2002/2003_PB2002.htm>`_).
'''

import os.path as op
import math
from collections import defaultdict

import numpy as num

from pyrocko import util, config
from pyrocko import orthodrome as od
from pyrocko.guts_array import Array
from pyrocko.guts import Object, String
from .util import get_download_callback


PI = math.pi


class Plate(Object):

    name = String.T(
        help='Name of the tectonic plate.')
    points = Array.T(
        dtype=float, shape=(None, 2),
        help='Points on the plate.')

    def max_interpoint_distance(self):
        p = od.latlon_to_xyz(self.points)
        return math.sqrt(num.max(num.sum(
            (p[num.newaxis, :, :] - p[:, num.newaxis, :])**2, axis=2)))

    def contains_point(self, point):
        return od.contains_point(self.points, point)

    def contains_points(self, points):
        return od.contains_points(self.points, points)


class Boundary(Object):

    plate_name1 = String.T()
    plate_name2 = String.T()
    kind = String.T()
    points = Array.T(dtype=float, shape=(None, 2))
    cpoints = Array.T(dtype=float, shape=(None, 2))
    itypes = Array.T(dtype=int, shape=(None))

    def split_types(self, groups=None):
        xyz = od.latlon_to_xyz(self.points)
        xyzmid = (xyz[1:] + xyz[:-1, :]) * 0.5
        cxyz = od.latlon_to_xyz(self.cpoints)
        d = od.distances3d(xyzmid[num.newaxis, :, :], cxyz[:, num.newaxis, :])
        idmin = num.argmin(d, axis=0)
        itypes = self.itypes[idmin]

        if groups is None:
            groupmap = num.arange(len(self._index_to_type))
        else:
            d = {}
            for igroup, group in enumerate(groups):
                for name in group:
                    d[name] = igroup

            groupmap = num.array(
                [d[name] for name in self._index_to_type],
                dtype=int)

        iswitch = num.concatenate(
            ([0],
             num.where(groupmap[itypes[1:]] != groupmap[itypes[:-1]])[0]+1,
             [itypes.size]))

        results = []
        for ii in range(iswitch.size-1):
            if groups is not None:
                tt = [self._index_to_type[ityp] for ityp in num.unique(
                    itypes[iswitch[ii]:iswitch[ii+1]])]
            else:
                tt = self._index_to_type[itypes[iswitch[ii]]]

            results.append((tt, self.points[iswitch[ii]:iswitch[ii+1]+1]))

        return results


class TectonicsDataset(object):
    '''
    Base class for datasets in :py:mod:`pyrocko.dataset.tectonics`.
    '''

    def __init__(self, name, data_dir, citation):
        self.name = name
        self.citation = citation
        self.data_dir = data_dir

    def fpath(self, filename):
        return op.join(self.data_dir, filename)

    def download_file(
            self, url, fpath, username=None, password=None,
            status_callback=None):

        util.download_file(
            url, fpath, username, password, status_callback=status_callback)


class PlatesDataset(TectonicsDataset):
    '''
    Base class for datasets describing plate boundaries.
    '''


class PeterBird2003(PlatesDataset):
    '''
    An updated digital model of plate boundaries.
    '''

    __citation = \
        'Bird, Peter. "An updated digital model of plate boundaries." ' \
        'Geochemistry, Geophysics, Geosystems 4.3 (2003).'

    def __init__(
            self,
            name='PeterBird2003',
            data_dir=None,
            raw_data_url=('https://mirror.pyrocko.org/peterbird.name/oldFTP/PB2002/%s')):  # noqa

        if data_dir is None:
            data_dir = op.join(config.config().tectonics_dir, name)

        PlatesDataset.__init__(
            self,
            name,
            data_dir=data_dir,
            citation=self.__citation)

        self.raw_data_url = raw_data_url

        self.filenames = [
            '2001GC000252_readme.txt',
            'PB2002_boundaries.dig.txt',
            'PB2002_orogens.dig.txt',
            'PB2002_plates.dig.txt',
            'PB2002_poles.dat.txt',
            'PB2002_steps.dat.txt']

        self._full_names = None

    def full_name(self, name):
        if not self._full_names:
            fn = util.data_file(op.join('tectonics', 'bird2003_plates.txt'))

            with open(fn, 'r') as f:
                self._full_names = dict(
                    line.strip().split(None, 1) for line in f)

        return self._full_names[name]

    def download_if_needed(self):
        for fn in self.filenames:
            fpath = self.fpath(fn)
            if not op.exists(fpath):
                self.download_file(
                    self.raw_data_url % fn, fpath,
                    status_callback=get_download_callback(
                        'Downloading Bird 2003 plate database...'))

    def get_boundaries(self):
        self.download_if_needed()
        fpath = self.fpath('PB2002_steps.dat.txt')

        d = defaultdict(list)
        ntyp = 0
        type_to_index = {}
        index_to_type = []
        with open(fpath, 'rb') as f:
            data = []
            for line in f:
                lsplit = line.split()
                name = lsplit[1].lstrip(b':').decode('ascii')
                plate_name1 = str(name[0:2])
                plate_name2 = str(name[3:5])
                kind = name[2]

                alon, alat, blon, blat = list(map(float, lsplit[2:6]))
                mlat = (alat + blat) * 0.5
                dlon = ((blon - alon) + 180.) % 360. - 180.
                mlon = alon + dlon * 0.5
                typ = str(lsplit[14].strip(b':*').decode('ascii'))

                if typ not in type_to_index:
                    ntyp += 1
                    type_to_index[typ] = ntyp - 1
                    index_to_type.append(typ)

                ityp = type_to_index[typ]
                d[plate_name1, kind, plate_name2].append((mlat, mlon, ityp))

        d2 = {}
        for k in d:
            d2[k] = (
                num.array([x[:2] for x in d[k]], dtype=float),
                num.array([x[2] for x in d[k]], dtype=int))

        fpath = self.fpath('PB2002_boundaries.dig.txt')
        boundaries = []
        plate_name1 = ''
        plate_name2 = ''
        kind = '-'
        with open(fpath, 'rb') as f:
            data = []
            for line in f:
                if line.startswith(b'***'):
                    cpoints, itypes = d2[plate_name1, kind, plate_name2]
                    boundaries.append(Boundary(
                        plate_name1=plate_name1,
                        plate_name2=plate_name2,
                        kind=kind,
                        points=num.array(data, dtype=float),
                        cpoints=cpoints,
                        itypes=itypes))

                    boundaries[-1]._type_to_index = type_to_index
                    boundaries[-1]._index_to_type = index_to_type

                    data = []
                elif line.startswith(b' '):
                    data.append(list(map(float, line.split(b',')))[::-1])
                else:
                    s = line.strip().decode('ascii')
                    plate_name1 = str(s[0:2])
                    plate_name2 = str(s[3:5])
                    kind = s[2]

        return boundaries

    def get_plates(self):
        self.download_if_needed()
        fpath = self.fpath('PB2002_plates.dig.txt')
        plates = []
        name = ''
        with open(fpath, 'rb') as f:
            data = []
            for line in f:
                if line.startswith(b'***'):
                    plates.append(Plate(
                        name=name,
                        points=num.array(data, dtype=float)))

                    data = []
                elif line.startswith(b' '):
                    data.append(list(map(float, line.split(b',')))[::-1])
                else:
                    name = str(line.strip().decode('ascii'))

        return plates


class StrainRateDataset(TectonicsDataset):
    '''
    Base class for strain rate datasets.
    '''


class GSRM1(StrainRateDataset):
    '''
    Global Strain Rate Map. An integrated global model of present-day
    plate motions and plate boundary deformation.
    '''

    __citation = \
        'Kreemer, C., W.E. Holt, and A.J. Haines, "An integrated global ' \
        'model of present-day plate motions and plate boundary ' \
        'deformation", Geophys. J. Int., 154, 8-34, 2003.'

    def __init__(
            self,
            name='GSRM1.2',
            data_dir=None,
            raw_data_url=('https://mirror.pyrocko.org/gsrm.unavco.org/model'
                          '/files/1.2/%s')):

        if data_dir is None:
            data_dir = op.join(config.config().tectonics_dir, name)

        StrainRateDataset.__init__(
            self,
            name,
            data_dir=data_dir,
            citation=self.__citation)

        self.raw_data_url = raw_data_url
        self._full_names = None
        self._names = None

    def full_names(self):
        if not self._full_names:
            fn = util.data_file(op.join('tectonics', 'gsrm1_plates.txt'))

            with open(fn, 'r') as f:
                self._full_names = dict(
                    line.strip().split(None, 1) for line in f)

        return self._full_names

    def full_name(self, name):
        name = self.plate_alt_names().get(name, name)
        return self.full_names()[name]

    def plate_names(self):
        if self._names is None:
            self._names = sorted(self.full_names().keys())

        return self._names

    def plate_alt_names(self):
        # 'African Plate' is named 'Nubian Plate' in GSRM1
        return {'AF': 'NU'}

    def download_if_needed(self, fn):
        fpath = self.fpath(fn)
        if not op.exists(fpath):
            self.download_file(
                self.raw_data_url % fn, fpath,
                status_callback=get_download_callback(
                    'Downloading global strain rate map...'))

    def get_velocities(self, reference_name=None, region=None):
        reference_name = self.plate_alt_names().get(
            reference_name, reference_name)

        if reference_name is None:
            reference_name = 'NNR'

        fn = 'velocity_%s.dat' % reference_name

        self.download_if_needed(fn)
        fpath = self.fpath(fn)
        data = []
        with open(fpath, 'rb') as f:
            for line in f:
                if line.strip().startswith(b'#'):
                    continue
                t = line.split()
                data.append(list(map(float, t)))

        arr = num.array(data, dtype=float)

        if region is not None:
            points = arr[:, 1::-1]
            mask = od.points_in_region(points, region)
            arr = arr[mask, :]

        lons, lats, veast, vnorth, veast_err, vnorth_err, corr = arr.T
        return lats, lons, vnorth, veast, vnorth_err, veast_err, corr


for cls in PeterBird2003, GSRM1:
    cls.__doc__ += '\n\n    .. note::\n        Please cite: %s\n' \
        % getattr(cls, '_%s__citation' % cls.__name__)


__all__ = '''
GSRM1
PeterBird2003
Plate'''.split()
