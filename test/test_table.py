from __future__ import division, print_function, absolute_import
import numpy as num
import unittest

from pyrocko import table, util

from pyrocko.table import Table, Header, SubHeader


class TableTestCase(unittest.TestCase):

    def test_table(self):

        t = Table()

        npoints = 10
        coords = num.random.random(size=(npoints, 3))
        times = num.random.random(size=npoints)
        names = ['a'*i for i in range(npoints)]

        t.add_col(('coords', 'm', ('x', 'y', 'z')), coords)
        t.add_col(('t', 's'), times)
        t.add_col('name', names)

        t.add_rows([coords, times, names])

        t.add_computed_col('mask', lambda tab: tab.get_col('name') == 'aaa')

        print(t.get_col('mask'))
        print(t.get_header('name').dtype)

        print(t)
        for c, i in [('x', 0), ('y', 1), ('z', 2)]:
            assert num.all(t.get_col('coords')[:, i] == t.get_col(c))


if __name__ == '__main__':
    util.setup_logging('test_table', 'warning')
    unittest.main()
