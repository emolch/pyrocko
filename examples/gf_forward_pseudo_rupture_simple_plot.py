import os.path as op
from pyrocko import gf
from pyrocko.plot.dynamic_rupture import RuptureView

km = 1e3

# Download a Greens Functions store
store_id = 'crust2_ib'
if not op.exists(store_id):
    gf.ws.download_gf_store(site='kinherd', store_id=store_id)


engine = gf.LocalEngine(store_superdirs=['.'], use_config=True)
store = engine.get_store(store_id)

dyn_rupture = gf.PseudoDynamicRupture(
    # At lat 0. and lon 0. (default)
    north_shift=2*km,
    east_shift=2*km,
    depth=3*km,
    strike=43.,
    dip=89.,
    rake=88.,

    width=12*km,
    length=26*km,

    nx=20,
    ny=30,

    # Relative nucleation between -1. and 1.
    nucleation_x=-.6,
    nucleation_y=.3,
    magnitude=7.,
    anchor='top',

    # Threads used for modelling
    nthreads=0)

dyn_rupture.discretize_patches(store)

plot = RuptureView(dyn_rupture, figsize=(8, 4))
plot.draw_patch_parameter('traction')
plot.draw_time_contour(store)
plot.draw_nucleation_point()
plot.save('dynamic_simple_tractions.png')
# Alternatively plot on screen
# plot.show_plot()
