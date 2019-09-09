import numpy as num

from pyrocko.modelling import OkadaSource, DislocationInverter
from pyrocko.plot import dislocation as displt

km = 1000.

# Set Source parameters
ref_north, ref_east, ref_depth = 0. * km, 0. * km, 100. * km

length_total = 50. * km
width_total = 15. * km
nlength, nwidth = 20, 16
npoints = nlength * nwidth

al1 = -length_total / 2.
al2 = length_total / 2.
aw1 = -width_total / 2.
aw2 = width_total / 2.

source = OkadaSource(
    lat=0., lon=0., north_shift=ref_north, east_shift=ref_east,
    depth=ref_depth,
    al1=al1, al2=al2, aw1=aw1, aw2=aw2, strike=45., dip=0., rake=90.,
    slip=1., opening=0., poisson=0.25, shearmod=32.0e9)

# Discretize source and set receiver locations on source plane center points
source_discretized, _ = source.discretize(nlength, nwidth)

receiver_coords = num.array([
    src.source_patch()[:3] for src in source_discretized])

# Create Stress drop (traction) array
dstress = -1.5e6
stress_comp = 1

stress_field = num.zeros((npoints * 3, 1))
for iw in range(nwidth):
    for il in range(nlength):
        idx = (iw * nlength + il) * 3
        if (il > nlength / 2. and il < nlength - 4) and \
                (iw > 2 and iw < nwidth - 4):
            stress_field[idx + stress_comp] = dstress
        elif (il > 2 and il <= nlength / 2.) and \
                (iw > 2 and iw < nwidth - 4):
            stress_field[idx + stress_comp] = dstress / 4.

disloc_est = DislocationInverter.get_disloc_lsq(
    stress_field, source_list=source_discretized)

# Plot
displt.plot(
    disloc_est.reshape(npoints, 3),
    receiver_coords,
    titles=['$u_{strike}$', '$u_{dip}$', '$u_{opening}$', '$u_{total}$'],
    cmap='viridis_r')

