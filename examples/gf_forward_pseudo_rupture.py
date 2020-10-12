import numpy as num
import os.path as op

import matplotlib.pyplot as plt

from pyrocko import gf


km = 1e3
d2r = 180./num.pi

# Download a Greens Functions store, programmatically.
store_id = 'gf_abruzzo_nearfield_vmod_Ameri'
store_id_dynamic = 'iceland_reg_v2'

if not op.exists(store_id):
    gf.ws.download_gf_store(site='kinherd', store_id=store_id)

if not op.exists(store_id_dynamic):
    gf.ws.download_gf_store(site='kinherd', store_id=store_id_dynamic)


engine = gf.LocalEngine(store_superdirs=['.'])
store = engine.get_store(store_id)

strike = 0.
dip = 90.
dep = 3*km
leng = 2*km
wid = 2*km

source_params = dict(
    north_shift=2*km,
    east_shift=2*km,
    depth=dep,
    width=wid,
    length=leng,
    dip=dip,
    strike=strike,
    magnitude=6.,
    anchor='top',
    decimation_factor=4)

dyn_rupture = gf.PseudoDynamicRupture(
    nx=5, ny=5,
    tractions=gf.tractions.HomogeneousTractions(
        strike=1.e4,
        dip=0.e4,
        normal=0.),
    **source_params)

dyn_rupture.discretize_patches(store)
slip = dyn_rupture.get_okada_slip()
rake = num.arctan2(slip[:, 1].mean(), slip[:, 0].mean())
print('rake', float(rake*d2r))


depths = dyn_rupture.get_patch_attribute('depth')
rect_rupture = gf.RectangularSource(
    rake=float(rake*d2r),
    **source_params)

# Define a grid of targets
# number in east and north directions
# ngrid = 40
ngrid = 90  # for better resolution

# extension from origin in all directions
obs_size = 10.*km
ntargets = ngrid**2

norths = num.linspace(-obs_size, obs_size, ngrid)
easts = num.linspace(-obs_size, obs_size, ngrid)

norths2d = num.repeat(norths, len(easts))
easts2d = num.tile(easts, len(norths))


waveform_target = gf.Target(
    lat=0., lon=0.,
    east_shift=10*km, north_shift=0.*km,
    store_id=store_id_dynamic)


static_target = gf.StaticTarget(
    lats=num.zeros(norths2d.size), lons=num.zeros(norths2d.size),
    north_shifts=norths2d.ravel(),
    east_shifts=easts2d.ravel(),
    interpolation='nearest_neighbor',
    store_id=store_id)

result = engine.process(rect_rupture, static_target)

targets_static = result.request.targets_static
N = targets_static[0].coords5[:, 2]
E = targets_static[0].coords5[:, 3]
synth_disp_rect = result.results_list[0][0].result

result = engine.process(dyn_rupture, static_target)

targets_static = result.request.targets_static
N = targets_static[0].coords5[:, 2]
E = targets_static[0].coords5[:, 3]
synth_disp_dyn = result.results_list[0][0].result


down_rect = synth_disp_rect['displacement.d']
down_dyn = synth_disp_dyn['displacement.d']
down_diff = down_rect - down_dyn

print('rect', down_rect.max())
print('dyn', down_dyn.max())

fig, axes = plt.subplots(3, 1)

for ax, down in zip(axes, (down_rect, down_dyn, down_diff)):
    cmap = ax.scatter(
        E, N, c=down,
        s=10., marker='s',
        edgecolor='face',
        cmap=plt.get_cmap('seismic'))

    fig.colorbar(cmap, ax=ax, orientation='vertical', aspect=5, shrink=0.5)

plt.show()
