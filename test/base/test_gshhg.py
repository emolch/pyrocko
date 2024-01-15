
import os
import unittest
import numpy as num
from numpy.testing import assert_array_less

from pyrocko.dataset import gshhg
from pyrocko import util

plot = int(os.environ.get('MPL_SHOW', 0))


class BB(object):
    west = -10.
    east = 20.
    south = 35.
    north = 55.

    tpl = (west, east, south, north)


class BBLakes(object):
    west = 4.41
    east = 13.14
    south = 42.15
    north = 49.32

    tpl = (west, east, south, north)


class BBPonds(object):
    west, east, south, north = (
        304.229444, 306.335556, -3.228889, -1.1358329999999999)

    tpl = (west, east, south, north)


class BBOtherSide(object):
    west = -5.
    east = 5.
    south = 30.
    north = 50.

    tpl = (west, east, south, north)


class GSHHGTest(unittest.TestCase):
    def setUp(self):
        self.gshhg = gshhg.GSHHG.intermediate()
        self.gshhg_preloaded = gshhg.GSHHG.intermediate()
        self.gshhg_preloaded.load_all()

    def test_polygon_loading_points(self):
        for ipoly in range(100):
            assert num.all(
                self.gshhg.polygons[ipoly].points
                == self.gshhg_preloaded.polygons[ipoly].points)

    def test_bb_ranges(self):
        for gs in [
                gshhg.GSHHG.crude(),
                gshhg.GSHHG.low(),
                gshhg.GSHHG.intermediate()]:
            # gshhg.GSHHG.high(), gshhg.GSHHG.full()]:

            gs.load_all()

            for ipoly, poly in enumerate(gs.polygons):

                assert gshhg.is_valid_polygon(poly.points)
                assert gshhg.is_valid_bounding_box(poly.get_bounding_box())

                assert gshhg.is_polygon_in_bounding_box(
                    poly.points, poly.get_bounding_box())

    def test_levels(self):
        for resolution in ['intermediate']:
            for gs in [
                    getattr(cls, resolution)() for cls in [
                        gshhg.Coastlines, gshhg.Rivers, gshhg.Borders]]:

                nlevels = len(gshhg.LEVELS[gs.data_type])
                avail = set()
                for poly in gs.polygons:
                    avail.add(poly.level_no)
                    assert 0 <= poly.level_no < nlevels

    def test_polygon_contains_point(self):
        poly = self.gshhg.polygons[-1]
        p_within = num.array(
            [poly.south + (poly.north - poly.south) / 2,
             poly.west + (poly.east - poly.west) / 2])

        p_outside = num.array(
            [poly.north + (poly.north - poly.south) / 2,
             poly.east + (poly.east - poly.west) / 2])

        if plot:
            import matplotlib.pyplot as plt

            ax = plt.axes()

            self.plot_polygons([poly], ax)
            ax.scatter(p_within[1], p_within[0], s=10.)
            ax.scatter(p_outside[1], p_outside[0], s=10.)

            plt.show()

        assert poly.contains_point(p_within) is True
        assert poly.contains_point(p_outside) is False

    def test_latlon(self):
        p = self.gshhg.polygons[0]

        assert_array_less(num.zeros_like(p.lons) - 0.001, p.lons)
        assert_array_less(p.lats, num.ones_like(p.lats) * 90 + 0.001)

    def test_polygon_level_selection(self):
        for p in self.gshhg.polygons:
            p.is_land()
            p.is_island_in_lake()
            p.is_pond_in_island_in_lake()
            p.is_antarctic_icefront()
            p.is_antarctic_grounding_line()

    def test_polygon_contains_points(self):
        poly = self.gshhg.polygons[0]

        points = num.array(
                [num.random.uniform(BB.south, BB.north, size=100),
                 num.random.uniform(BB.east, BB.west, size=100)]).T
        pts = poly.contains_points(points)

        if plot:
            import matplotlib.pyplot as plt

            points = points[pts]

            colors = num.ones(points.shape[0]) * pts[pts]
            ax = plt.axes()

            self.plot_polygons([poly], ax)
            ax.scatter(points[:, 1], points[:, 0], c=colors, s=.5)

            plt.show()

    def test_bounding_box_select(self):
        p = self.gshhg.get_polygons_within(*BB.tpl)

        if plot:
            import matplotlib.pyplot as plt

            from matplotlib.patches import Rectangle

            ax = plt.axes()
            self.plot_polygons(p, ax)

            ax.add_patch(
                Rectangle([BB.west, BB.south],
                          width=BB.east-BB.west, height=BB.north-BB.south,
                          alpha=.2))
            plt.show()

    def test_mask_land(self):
        poly = self.gshhg.get_polygons_within(*BBPonds.tpl)

        points = num.array(
                [num.random.uniform(BBPonds.south, BBPonds.north, size=10000),
                 num.random.uniform(BBPonds.east, BBPonds.west, size=10000)]).T

        pts = self.gshhg.get_land_mask(points)

        if plot:
            import matplotlib.pyplot as plt

            points = points
            colors = num.ones(points.shape[0]) * pts

            # colors = num.ones(points.shape[0]) * pts
            ax = plt.axes()

            self.plot_polygons(poly, ax)
            ax.scatter(points[:, 1], points[:, 0], c=colors, s=.5, zorder=2)
            plt.show()

        for is_land, point in zip(pts[:20], points[:20]):
            is_land2 = self.gshhg.is_point_on_land(*point)
            assert is_land == is_land2

    def test_is_point_on_land(self):

        point = (46.455289, 6.494283)
        p = self.gshhg.get_polygons_at(*point)
        assert self.gshhg.is_point_on_land(*point) is False

        if plot:
            import matplotlib.pyplot as plt

            ax = plt.axes()
            self.plot_polygons(p, ax)
            ax.scatter(point[1], point[0])

            plt.show()

    @staticmethod
    def plot_polygons(polygons, ax, **kwargs):
        # from matplotlib.patches import Polygon
        from pyrocko.plot import mpl_color

        args = {
            'edgecolor': 'red',
        }
        args.update(kwargs)

        colormap = [
            mpl_color('aluminium2'),
            mpl_color('skyblue1'),
            mpl_color('aluminium4'),
            mpl_color('skyblue2'),
            mpl_color('white'),
            mpl_color('aluminium1')]

        for p in polygons:
            ax.plot(
                p.points[:, 1], p.points[:, 0],
                color=colormap[p.level_no-1])

        # map(ax.add_patch, [Polygon(num.fliplr(p.points),
        #                            facecolor=colormap[p.level_no-1],
        #                            **args)
        #                    for p in polygons])

    def test_pond(self):
        for poly in self.gshhg.polygons:
            if poly.is_pond_in_island_in_lake():
                (w, e, s, n) = poly.get_bounding_box()
                # print (w-1., e+1, s-1., n+1)
                polys2 = self.gshhg.get_polygons_within(w-1., e+1, s-1., n+1)

                if plot:
                    import matplotlib.pyplot as plt

                    ax = plt.axes()
                    self.plot_polygons(polys2, ax)

                    ax.autoscale_view()

                    plt.show()

    def test_other_side(self):
        bb = BBOtherSide
        poly = self.gshhg.get_polygons_within(*bb.tpl)

        points = num.array(
                [num.random.uniform(bb.south, bb.north, size=1000),
                 num.random.uniform(bb.east, bb.west, size=1000)]).T
        pts = self.gshhg.get_land_mask(points)

        if plot:
            import matplotlib.pyplot as plt

            points = points
            colors = num.ones(points.shape[0]) * pts

            # colors = num.ones(points.shape[0]) * pts
            ax = plt.axes()

            self.plot_polygons(poly, ax)
            ax.scatter(points[:, 1], points[:, 0], c=colors, s=.5, zorder=2)
            plt.show()


if __name__ == '__main__':
    plot = False
    util.setup_logging('test_gshhg', 'debug')
    unittest.main(exit=False)
