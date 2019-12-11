# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from pyrocko.guts import Object, String, Unicode, List, Int, SObject, Any
from pyrocko.guts_array import Array
from pyrocko.table import Table, LocationRecipe

from .event import Event


class Geometry(Object):

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
    event = Event.T(default=Event.D())
    times = Array.T(
        shape=(None,),
        dtype='float64',
        help='1d vector of times [s] wrt. event time for which '
             'properties have value',
        optional=True)

    @property
    def deltat(self):
        if self.times.size > 2:
            return self.times[1] - self.times[0]
        else:
            return 1.

    def time2idx(self, time, dtype='int'):
        if self.times.size > 2:
            return round((time - self.times.min() - (
                self.deltat / 2.)) / self.deltat).astype(dtype)
        else:
            return 0

    def setup(self, vertices, faces):

        self.vertices = Table()
        self.vertices.add_recipe(LocationRecipe())
        self.vertices.add_col((
            'c5', '',
            ('ref_lat', 'ref_lon', 'north_shift', 'east_shift', 'depth')),
            vertices)

        self.faces = Table()
        ncorners = faces.shape[1]
        sub_headers = tuple(['f{}'.format(i) for i in range(ncorners)])
        self.faces.add_col(('faces', '', sub_headers), faces)

    def add_property(self, name, values):
        self.properties.add_col(name, values)

    def get_property(self, name):
        return self.properties.get_col(name)
