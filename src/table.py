import numpy as num
from pyrocko.guts import Object, String, Unicode, List, Int

guts_prefix = 'pf'


def ncols(arr):
    return 1 if arr.ndim == 1 else arr.shape[1]


def nrows(arr):
    return arr.shape[0]


class Header(Object):
    name = String.T()
    label = Unicode.T(optional=True)
    unit = Unicode.T(optional=True)


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


class Table(object):

    def __init__(self, name=None):
        self._name = name
        self._arrays = []
        self._headers = []
        self._group_headers = []
        self._cols = {}
        self._col_groups = {}

    def is_empty(self):
        return not self._arrays

    def get_nrows(self):
        if self.is_empty():
            return 0
        else:
            return nrows(self._arrays[0])

    def get_ncols(self):
        if self.is_empty():
            return 0
        else:
            return sum(ncols(arr) for arr in self._arrays)

    def add_cols(self, headers, arrays, group_headers=None):
        assert sum(ncols(arr) for arr in arrays) == len(headers)
        if group_headers:
            assert len(group_headers) == len(arrays)
        else:
            group_headers = [None]*len(arrays)

        for gheader, arr in zip(group_headers, arrays):
            assert isinstance(arr, num.ndarray)
            assert arr.ndim in (1, 2)
            if not self.is_empty():
                assert nrows(arr) == self.get_nrows()

            iarr = len(self._arrays)

            self._arrays.append(arr)
            self._group_headers.append(gheader)

            if gheader:
                self._col_groups[gheader.name] = iarr

            for icol in range(ncols(arr)):
                header = headers.pop(0)
                self._cols[header.name] = iarr, icol
                self._headers.append(header)

    def get_col(self, name):
        iarr, icol = self._cols[name]
        return self._arrays[iarr][:, icol]

    def get_col_group(self, name):
        iarr = self._col_groups[name]
        return self._arrays[iarr]

    def __str__(self):
        return str(Description(self))
