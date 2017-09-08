import unittest
import pyrocko
from pyrocko import util


class BackwardCompatTest(unittest.TestCase):
    pass


compat_modules = [
    'automap',
    'css',
    'datacube',
    'gcf',
    'gse1',
    'gse2_io_wrap',
    'ims',
    'io_common',
    'kan',
    'mseed',
    'rdseed',
    'sacio',
    'segy',
    'seisan_response',
    'seisan_waveform',
    'suds',
    'yaff',
    'catalog',
    'iris_ws',
    'crust2x2',
    'crustdb',
    'geonames',
    'tectonics',
    'topo',
    'automap',
    'beachball',
    'cake_plot',
    'gmtpy',
    'hudson',
    'response_plot',
    'fdsn.__init__',
    'fdsn.enhanced_sacpz',
    'fdsn.station',
    'fdsn.resp',
    'fdsn.ws',
    'marker',
]


def _make_function(module):
    def f(self):
        grumpy = pyrocko.grumpy
        pyrocko.grumpy = 0
        __import__('pyrocko.' + module)
        pyrocko.grumpy = grumpy

    f.__name__ = 'test_import_%s' % module

    return f


for mod in compat_modules:
    setattr(
        BackwardCompatTest,
        'test_import_' + mod,
        _make_function(mod))


if __name__ == '__main__':
    util.setup_logging('test_tutorials', 'warning')
    unittest.main()
