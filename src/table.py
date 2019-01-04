import math
import numpy as num
from pyrocko.guts import Object, String, Unicode, List, Int, SObject, Any
from pyrocko import orthodrome as od
from pyrocko.util import num_full

guts_prefix = 'pf'


def nextpow2(i):
    return 2**int(math.ceil(math.log(i)/math.log(2.)))


def ncols(arr):
    return 1 if arr.ndim == 1 else arr.shape[1]


def nrows(arr):
    return arr.shape[0]


def resize_shape(shape, n):
    return (n, ) if len(shape) == 1 else (n, shape[1])


class DType(SObject):
    dummy_for = num.dtype


class SubHeader(Object):
    name = String.T()
    unit = Unicode.T(optional=True)
    default = Any.T(optional=True)
    label = Unicode.T(optional=True)

    def __init__(self, name, unit=None, default=None, label=None, **kwargs):
        Object.__init__(
            self, name=name, unit=unit, default=default, label=label, **kwargs)

    def get_caption(self):
        s = self.label or self.name
        if self.unit:
            s += ' [%s]' % self.unit

        return s


class Header(SubHeader):
    sub_headers = List.T(SubHeader.T())
    dtype = DType.T(default=num.dtype('float64'), optional=True)

    def __init__(
            self, name,
            unit=None,
            sub_headers=[],
            dtype=None,
            default=None,
            label=None):

        sub_headers = [anything_to_sub_header(sh) for sh in sub_headers]

        kwargs = dict(sub_headers=sub_headers, dtype=dtype)

        SubHeader.__init__(self, name, unit, default, label, **kwargs)

    def get_ncols(self):
        return max(1, len(self.sub_headers))

    def default_array(self, nrows):
        val = self.dtype(self.default)
        if not self.sub_headers:
            return num_full((nrows,), val, dtype=self.dtype)
        else:
            return num_full((nrows, self.get_ncols()), val, dtype=self.dtype)


def anything_to_header(args):
    if isinstance(args, Header):
        return args
    elif isinstance(args, str):
        return Header(name=args)
    elif isinstance(args, tuple):
        return Header(*args)
    else:
        raise ValueError('argument of type Header, str or tuple expected')


def anything_to_sub_header(args):
    if isinstance(args, SubHeader):
        return args
    elif isinstance(args, str):
        return SubHeader(name=args)
    elif isinstance(args, tuple):
        return SubHeader(*args)
    else:
        raise ValueError('argument of type SubHeader, str or tuple expected')


class Description(Object):
    name = String.T(optional=True)
    headers = List.T(Header.T())
    nrows = Int.T()
    ncols = Int.T()

    def __init__(self, table):
        Object.__init__(
            self,
            name=table._name,
            headers=table._headers,
            nrows=table.get_nrows(),
            ncols=table.get_ncols())


class NoSuchRecipe(Exception):
    pass


class Table(object):

    def __init__(self, name=None, nrows_capacity=None, nrows_capacity_min=0):
        self._name = name
        self._buffers = []
        self._arrays = []
        self._headers = []
        self._cols = {}
        self.recipes = []
        self.nrows_capacity_min = nrows_capacity_min
        self._nrows_capacity = 0
        if nrows_capacity is not None:
            self.set_nrows_capacity(max(nrows_capacity, nrows_capacity_min))

    def add_recipe(self, recipe):
        self.recipes.append(recipe)
        recipe._add_required_cols(self)

    def get_nrows(self):
        if not self._arrays:
            return 0
        else:
            return nrows(self._arrays[0])

    def get_nrows_capacity(self):
        return self._nrows_capacity

    def set_nrows_capacity(self, nrows_capacity_new):
        if self.get_nrows_capacity() != nrows_capacity_new:
            if self.get_nrows() > nrows_capacity_new:
                raise ValueError('new capacity too small to hold current data')

            new_buffers = []
            for buf in self._buffers:
                shape = resize_shape(buf.shape, nrows_capacity_new)
                new_buffers.append(num.zeros(shape, dtype=buf.dtype))

            ncopy = min(self.get_nrows(), nrows_capacity_new)

            new_arrays = []
            for arr, buf in zip(self._arrays, new_buffers):
                buf[:ncopy, ...] = arr[:ncopy, ...]
                new_arrays.append(buf[:ncopy, ...])

            self._buffers = new_buffers
            self._arrays = new_arrays
            self._nrows_capacity = nrows_capacity_new

    def get_ncols(self):
        return len(self._arrays)

    def add_col(self, header, array=None):
        header = anything_to_header(header)

        nrows_current = self.get_nrows()
        if array is None:
            array = header.default_array(nrows_current)

        array = num.asarray(array)
        print(header.get_ncols(), ncols(array))

        assert header.get_ncols() == ncols(array)
        assert array.ndim in (1, 2)
        if self._arrays:
            assert nrows(array) == nrows_current

        if nrows_current == 0:
            nrows_current = nrows(array)
            self.set_nrows_capacity(
                max(nrows_current, self.nrows_capacity_min))

        iarr = len(self._arrays)

        shape = resize_shape(array.shape, self.get_nrows_capacity())
        if shape != array.shape:
            buf = num.zeros(shape, dtype=array.dtype)
            buf[:nrows_current, ...] = array[:, ...]
        else:
            buf = array

        self._buffers.append(buf)
        self._arrays.append(buf[:nrows_current, ...])
        self._headers.append(header)

        self._cols[header.name] = iarr, None

        for icol, sub_header in enumerate(header.sub_headers):
            self._cols[sub_header.name] = iarr, icol

    def add_cols(self, headers, arrays=None):
        if arrays is None:
            arrays = [None] * len(headers)

        for header, array in zip(headers, arrays):
            self.add_col(header, array)

    def add_rows(self, arrays):
        assert self.get_ncols() == len(arrays)
        arrays = [num.asarray(arr) for arr in arrays]

        nrows_add = nrows(arrays[0])
        nrows_current = self.get_nrows()
        nrows_new = nrows_current + nrows_add
        if self.get_nrows_capacity() < nrows_new:
            self.set_nrows_capacity(max(
                self.nrows_capacity_min, nextpow2(nrows_new)))

        new_arrays = []
        for buf, arr in zip(self._buffers, arrays):
            assert ncols(arr) == ncols(buf)
            assert nrows(arr) == nrows_add
            buf[nrows_current:nrows_new, ...] = arr[:, ...]
            new_arrays.append(buf[:nrows_new, ...])

        self._arrays = new_arrays

        for recipe in self.recipes:
            recipe._add_rows_handler(self, nrows_add)

    def get_col(self, name, mask=slice(None)):
        if name in self._cols:
            if isinstance(mask, str):
                mask = self.get_col(mask)

            iarr, icol = self._cols[name]
            if icol is None:
                return self._arrays[iarr][mask]
            else:
                return self._arrays[iarr][mask, icol]
        else:
            recipe = self.get_recipe_for_col(name)
            recipe._update_col(self, name)

            print('mm', mask)
            return recipe.get_table().get_col(name, mask)

    def get_header(self, name):
        if name in self._cols:
            iarr, icol = self._cols[name]
            if icol is None:
                return self._headers[iarr]
            else:
                return self._headers[iarr].sub_headers[icol]
        else:
            recipe = self.get_recipe_for_col(name)
            return recipe.get_header(name)

    def has_col(self, name):
        return name in self._cols or \
            any(rec.has_col(name) for rec in self.recipes)

    def get_col_names(self, sub_headers=True):
        names = []
        for h in self._headers:
            names.append(h.name)
            if sub_headers:
                for sh in h.sub_headers:
                    names.append(sh.name)

        for recipe in self.recipes:
            names.extend(recipe.get_col_names())

        return names

    def get_recipe_for_col(self, name):
        for recipe in self.recipes:
            print(recipe, recipe.has_col(name), name)
            if recipe.has_col(name):
                print('xx')
                return recipe
                print('yyy')

        print('yy')
        raise NoSuchRecipe(name)

    def get_description(self):
        d = Description(self)
        d.validate()
        return str(Description(self))

    def __str__(self):
        scols = []
        formats = {
            num.dtype('float64'): '%e'}

        for name in self.get_col_names(sub_headers=False):
            array = self.get_col(name)
            header = self.get_header(name)
            fmt = formats.get(array.dtype, '%s')
            if array.ndim == 1:
                scol = [header.get_caption(), '']
                for val in array:
                    scol.append(fmt % val)

                scols.append(scol)
            else:
                for icol in range(ncols(array)):
                    sub_header = header.sub_headers[icol]
                    scol = [header.get_caption(), sub_header.get_caption()]
                    for val in array[:, icol]:
                        scol.append(fmt % val)

                    scols.append(scol)

        for scol in scols:
            width = max(len(s) for s in scol)
            for i in range(len(scol)):
                scol[i] = scol[i].rjust(width)

        return '\n'.join(' '.join(s for s in srow) for srow in zip(*scols))

    def add_computed_col(self, header, func):
        header = anything_to_header(header)
        self.add_recipe(SimpleRecipe(header, func))


class Recipe(object):

    def __init__(self):
        self._table = None
        self._table = Table()

        self._required_headers = []
        self._headers = []
        self._col_update_map = {}
        self._name_to_header = {}

    def has_col(self, name):
        return name in self._name_to_header

    def get_col_names(self):
        names = []
        for h in self._headers:
            names.append(h.name)
            for sh in h.sub_headers:
                names.append(sh.name)

        return names

    def get_table(self):
        return self._table

    def get_header(self, name):
        return self._name_to_header[name]

    def _add_required_cols(self, table):
        for h in self._headers:
            if not table.has_col(h.name):
                table.add_col(h)

    def _update_col(self, table, name):
        if not self._table.has_col(name):
            print('aufruf')
            self._col_update_map[name](table)

    def _add_rows_handler(self, table, nrows_added):
        pass

    def _register_required_col(self, header):
        self._required_headers.append(header)

    def _register_computed_col(self, header, updater):
        self._headers.append(header)
        self._name_to_header[header.name] = header
        self._col_update_map[header.name] = updater
        for sh in header.sub_headers:
            self._col_update_map[sh.name] = updater
            self._name_to_header[sh.name] = sh


class SimpleRecipe(Recipe):

    def __init__(self, header, func):
        Recipe.__init__(self)
        self._col_name = header.name

        def call_func(tab):
            self._table.add_col(header, func(tab))

        self._register_computed_col(header, call_func)

    def _add_rows_handler(self, table, nrows_added):
        Recipe._add_rows_handler(self, table, nrows_added)
        if self._table.has_col(self._col_name):
            self._table.remove_col(self._col_name)


class LocationRecipe(Recipe):

    def __init__(self):
        Recipe.__init__(self)

        self._register_required_col(
            Header(name='c5', sub_headers=[
                SubHeader(name='ref_lat', unit='degrees'),
                SubHeader(name='ref_lon', unit='degrees'),
                SubHeader(name='north_shift', unit='m'),
                SubHeader(name='east_shift', unit='m'),
                SubHeader(name='depth', unit='m')]))

        self._latlon_header = Header(name='latlon', sub_headers=[
            SubHeader(name='lat', unit='degrees'),
            SubHeader(name='lon', unit='degrees')])

        self._register_computed_col(self._latlon_header, self._update_latlon)

    def _add_rows_handler(self, table, nrows_added):
        Recipe._add_rows_handler(self, table, nrows_added)
        if self._table.has_col('latlon'):
            self._table.remove_col('latlon')

    def _update_latlon(self, table):
        lats, lons = od.ne_to_latlon(
            table.get_col('ref_lat'),
            table.get_col('ref_lon'),
            table.get_col('north_shift'),
            table.get_col('east_shift'))

        latlons = num.zeros((lats.size, 2))
        latlons[:, 0] = lats
        latlons[:, 1] = lons

        self._table.add_col(self._latlon_header, latlons)


class EventRecipe(LocationRecipe):

    def __init__(self):
        LocationRecipe.__init__(self)
        self._register_required_col(Header(name='time', unit='s'))
        self._register_required_col(Header(name='magnitude'))
