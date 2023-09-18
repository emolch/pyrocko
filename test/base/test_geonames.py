
import unittest
from pyrocko.dataset import geonames
from pyrocko import util


class GeonamesTestCase(unittest.TestCase):

    def test_geonames(self):

        cities = geonames.get_cities(53.6, 10.0, 100e3, 200000)
        self.assertEqual(
            sorted(c.asciiname for c in cities),
            ['Bremen', 'Hamburg', 'Kiel', 'Luebeck'])

    def test_geonames_countries(self):

        countries = geonames.load_all_countries()
        for country in countries:
            print(country)


if __name__ == '__main__':
    util.setup_logging('test_geonames', 'warning')
    unittest.main()
