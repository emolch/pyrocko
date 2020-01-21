# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from pyrocko.guts import Object, String, Unicode, List, Int, SObject, Any
from pyrocko.guts_array import Array
from pyrocko.table import Table, LocationRecipe

from .event import Event

from logging import getLogger


logger = getLogger('model.geometry')


def reduce_array_dims(array):
    '''
    Support function to reduce output array ndims from table
    '''

    if array.shape[0] == 1 and array.ndim > 1:
        return num.squeeze(array, axis=0)
    else:
        return array


class Geometry(Object):
    '''
    Spatial (and temporal) distributed properties of an event

    The Geometry object allows to store properties of an event in a spatial
    (and temporal) distributed manner. For a set of planes ("faces"),
    characterized by their corner points ("vertices"), properties are stored.
    Also information on the outline of the source are stored.
    '''

    properties = Table.T(
        default=Table.D(),
        help='Properties that should be displayable on the surface of the'
             ' geometry. If 2d time dependency in column directions.',
        optional=True)

    vertices = Table.T(
        default=Table.D(),
        help='Vertices of the mesh of the geometry. '
             'Expected to be (lat,lon,north,east,depth) for each vertex.',
        optional=True)

    faces = Table.T(
        default=Table.D(),
        help='Face integer indexes to the respective vertices. '
             'Indexes belonging to one polygon have to be given row-wise.',
        optional=True)

    outlines = List.T(Table.T(),
        default=[],
        help='List of vertices of the mesh of the outlines of the geometry. '
             'Expected to be (lat,lon,north,east,depth) for each vertex'
             '(outline).',
        optional=True)

    event = Event.T(default=Event.D())

    times = Array.T(
        shape=(None,),
        dtype='float64',
        help='1d vector of times [s] wrt. event time for which '
             'properties have value. Must have constant delta t',
        optional=True)

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self._ntimes = None

    @property
    def deltat(self):
        '''
        Sampling rate of properties (time difference) [s]
        '''

        if self.times.size > 2:
            return self.times[1] - self.times[0]
        else:
            return 1.

    @property
    def ntimes(self):
        if self._ntimes is None:
            if self.times is not None:
                self._ntimes = len(self.times)
            else:
                return 0

        return self._ntimes

    def time2idx(self, time):
        if self.times.size > 2:
            idx = int(round((time - self.times.min() - (
                    self.deltat / 2.)) / self.deltat))

            if idx < 0:
                return 0
            elif idx > self.ntimes:
                return self.ntimes
            else:
                return idx
        else:
            return 0

    def set_vertices(self, vertices):
        self.vertices.add_recipe(LocationRecipe())
        self.vertices.add_col((
            'c5', '',
            ('ref_lat', 'ref_lon', 'north_shift', 'east_shift', 'depth')),
            vertices)

    def get_vertices(self, col='c5'):
        if self.vertices:
            return reduce_array_dims(self.vertices.get_col(col))

    def set_faces(self, faces):
        ncorners = faces.shape[1]
        sub_headers = tuple(['f{}'.format(i) for i in range(ncorners)])
        self.faces.add_col(('faces', '', sub_headers), faces)

    def get_faces(self, col='faces'):
        if self.faces:
            return reduce_array_dims(self.faces.get_col(col))

    def no_faces(self):
        return self.faces.get_nrows()

    def setup(self, vertices, faces, outlines=None):
        self.set_vertices(vertices)
        self.set_faces(faces)

        if outlines is not None:
            self.set_outlines(outlines)

    def set_outlines(self, outlines):
        if outlines is not None:
            self.outlines = []
            for outline in outlines:
                outl = Table()
                outl.add_recipe(LocationRecipe())
                outl.add_col((
                    'c5', '',
                    ('ref_lat', 'ref_lon', 'north_shift', 'east_shift',
                     'depth')),
                    outline)
                self.outlines.append(outl)

    def get_outlines(self):
        if self.outlines:
            return self.outlines
        else:
            logger.warning('No outlines set!')

    def add_property(self, name, values):
        if values.ndim == 1 or values.shape[1] == 1:
            self.properties.add_col(name, values.reshape(-1,))
        elif (values.ndim == 2) and (self.times is not None):
            assert values.shape[1] == self.times.shape[0]
            sub_headers = tuple(['{}'.format(i) for i in self.times])
            self.properties.add_col((name, '', sub_headers), values)
        else:
            raise AttributeError(
                'Please give either 1D array or the associated times first.')

    def get_property(self, name):
        return reduce_array_dims(self.properties.get_col(name))

    def has_property(self, name):
        return self.properties.has_col(name)
