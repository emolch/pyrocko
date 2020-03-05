import numpy as num

from pyrocko.modelling import OkadaSource, okada_ext
from pyrocko.plot import dislocation as displt

d2r = num.pi / 180.
km = 1000.

# Set source parameter
src_north, src_east, src_depth = 0. * km, 0. * km, 100. * km

length_total = 50. * km
width_total = 15. * km
nlength = 50
nwidth = 15

al1 = -length_total / 2.
al2 = length_total / 2.
aw1 = -width_total / 2.
aw2 = width_total / 2.

# Define rupture plane and discretize it depending on nlength, nwidth
source = OkadaSource(
    lat=0., lon=0., north_shift=src_north, east_shift=src_east,
    depth=src_depth,
    al1=al1, al2=al2, aw1=aw1, aw2=aw2,
    strike=45., dip=90., rake=90.,
    slip=1., opening=0., poisson=0.25, shearmod=32.0e9)

source_discretized, _ = source.discretize(nlength, nwidth)

# Set receiver at the surface
receiver_coords = num.zeros((10000, 3))
margin = length_total * 3
receiver_coords[:, 0] = \
    num.tile(num.linspace(-margin, margin, 100), 100) + src_north
receiver_coords[:, 1] = \
    num.repeat(num.linspace(-margin, margin, 100), 100) + src_east

# Calculation of displacements due to source at receiver_coords points
source_patch = num.array([
    patch.source_patch() for patch in source_discretized])
source_disl = num.array([
    patch.source_disloc() for patch in source_discretized])
result = okada_ext.okada(
    source_patch, source_disl, receiver_coords,
    source.lamb, source.shearmod, 0)

# Plot
displt.plot(result, receiver_coords, cmap='coolwarm', zero_center=True)
