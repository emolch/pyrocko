import os.path as op

from pyrocko import gf
from pyrocko.plot.dynamic_rupture import RuptureView, rupture_movie

km = 1e3

# Download a Greens Functions store
store_id = 'crust2_ib'
if not op.exists(store_id):
    gf.ws.download_gf_store(site='kinherd', store_id=store_id)


engine = gf.LocalEngine(store_superdirs=['.'], use_config=True)
store = engine.get_store(store_id)

dyn_rupture = gf.PseudoDynamicRupture(
    nx=30, ny=40,
    north_shift=2*km, east_shift=2*km, depth=5*km,
    strike=43., dip=90., rake=88.,
    width=12*km, length=26*km,
    nucleation_x=-.6, nucleation_y=.3,
    gamma=0.7, slip=2., anchor='top', smooth_rupture=True,
    nthreads=0)

dyn_rupture.discretize_patches(store)

plot = RuptureView(dyn_rupture, figsize=(8, 4))
plot.draw_patch_parameter('traction')
plot.draw_time_contour(store)
plot.draw_nucleation_point()
plot.save('dynamic_simple_tractions.png')
# Alternatively plot on screen
# plot.show_plot()

plot = RuptureView(dyn_rupture, figsize=(8, 4))
plot.draw_dislocation()
plot.draw_time_contour(store)
plot.draw_nucleation_point()
plot.save('dynamic_simple_dislocations.png')

plot = RuptureView(dyn_rupture, figsize=(8, 4))
plot.draw_patch_parameter('vr')
plot.draw_time_contour(store)
plot.draw_nucleation_point()
plot.save('dynamic_simple_vr.png')

rupture_movie(
    dyn_rupture, store, 'dislocation',
    plot_type='view', figsize=(8, 4))
