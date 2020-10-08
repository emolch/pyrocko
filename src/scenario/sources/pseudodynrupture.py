# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, division, print_function

import numpy as num

from pyrocko.guts import Float, Int
from pyrocko import gf

from .base import SourceGenerator

km = 1e3
guts_prefix = 'pf.scenario'


class PseudoDynamicRuptureGenerator(SourceGenerator):
    depth_min = Float.T(
        default=0.0)
    depth_max = Float.T(
        default=5*km)
    decimation_factor = Int.T(
        default=4)

    slip_min = Float.T(
        optional=True)
    slip_max = Float.T(
        optional=True)

    strike = Float.T(
        optional=True)
    dip = Float.T(
        optional=True)
    rake = Float.T(
        optional=True)
    depth = Float.T(
        optional=True)
    nx = Int.T(
        default=5,
        optional=True)
    ny = Int.T(
        default=5,
        optional=True)
    nucleation_x = Float.T(
        optional=True)
    nucleation_y = Float.T(
        optional=True)

    width = Float.T(
        optional=True)
    length = Float.T(
        optional=True)

    gamma = Float.T(
        optional=True)

    def get_source(self, ievent):
        rstate = self.get_rstate(ievent)
        time = rstate.uniform(self.time_min, self.time_max)
        lat, lon = self.get_latlon(ievent)
        depth = rstate.uniform(self.depth_min, self.depth_max)
        nucleation_x = self.nucleation_x if self.nucleation_x is not None \
            else rstate.uniform(-1., 1.)
        nucleation_y = self.nucleation_y if self.nucleation_y is not None \
            else rstate.uniform(-1., 1.)

        magnitude = self.draw_magnitude(rstate)
        slip = None

        # After K. Thingbaijam et al. (2017) - Tab. 1, Normal faulting
        def scale_from_mag(magnitude, a, b):
            return 10**(a + b*magnitude)

        def scale_from_slip(slip, a, b):
            return 10**((num.log10(slip) - a) / b)

        length = scale_from_mag(magnitude, a=-1.722, b=0.485)
        width = scale_from_mag(magnitude, a=-0.829, b=0.323)

        if self.slip_min is not None and self.slip_max is not None:
            slip = rstate.uniform(self.slip_min, self.slip_max)
            # After K. Thingbaijam et al. (2017) - Tab. 2, Normal faulting
            length = scale_from_slip(slip, a=-2.302, b=1.302)
            width = scale_from_slip(slip, a=-3.698, b=2.512)
            magnitude = None

        length = length if not self.length else self.length
        width = width if not self.width else self.width
        depth = depth if not self.depth else self.depth

        if self.strike is None and self.dip is None and self.rake is None:
            strike, rake = rstate.uniform(-180., 180., 2)
            dip = rstate.uniform(0., 90.)
        else:
            if None in (self.strike, self.dip, self.rake):
                raise ValueError(
                    'PseudoDynamicRuptureGenerator: '
                    'strike, dip, rake must be used in combination.')

            strike = self.strike
            dip = self.dip
            rake = self.rake

        source = gf.PseudoDynamicRupture(
            time=float(time),
            lat=float(lat),
            lon=float(lon),
            anchor='top',
            depth=float(depth),
            length=float(length),
            width=float(width),
            strike=float(strike),
            dip=float(dip),
            rake=float(rake),
            magnitude=magnitude,
            slip=slip,
            nucleation_x=float(nucleation_x),
            nucleation_y=float(nucleation_y),
            nx=self.nx,
            ny=self.ny,
            decimation_factor=self.decimation_factor,
            smooth_rupture=True,
            gamma=self.gamma if self.gamma else None)

        return source

    def add_map_artists(self, automap):
        for source in self.get_sources():
            automap.gmt.psxy(
                in_rows=source.outline(cs='lonlat'),
                L='+p2p,black',
                W='1p,black',
                G='black',
                t=50,
                *automap.jxyr)
