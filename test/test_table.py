from __future__ import division, print_function, absolute_import
import numpy as num
import unittest

from pyrocko import util, guts

from pyrocko.table import Table


class TableTestCase(unittest.TestCase):

    def test_table(self):

        t = Table()

        npoints = 10
        coords = num.random.random(size=(npoints, 3))
        times = num.random.random(size=npoints)
        names = ['a'*i for i in range(npoints)]

        t.add_col(('coords', u'm', ('x', 'y', 'z')), coords)
        t.add_col(('t', u's'), times)
        t.add_col('name', names)

        t.add_rows([coords, times, names])

        t.add_computed_col('mask', lambda tab: tab.get_col('name') == 'aaa')

        # print(t.get_col('mask'))
        # print(t.get_header('name').dtype)

        for c, i in [('x', 0), ('y', 1), ('z', 2)]:
            assert num.all(t.get_col('coords')[:, i] == t.get_col(c))

    def test_table2(self):

        npoints = 10
        coords = num.random.random(size=(npoints, 3))
        times = num.random.random(size=npoints)

        t = Table()

        t.add_col(('coords', u'm', ('x', 'y', 'z')), coords)
        t.add_col(('t', u's'), times)
        t.add_rows([coords, times])
        print(t)
        t.validate()
        t2 = guts.load(string=str(t))
        print(t2)


if __name__ == '__main__':
    util.setup_logging('test_table', 'warning')
    unittest.main()
