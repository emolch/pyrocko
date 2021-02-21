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

# Initialize the source model
dyn_rupture = gf.PseudoDynamicRupture(
    depth=3*km,

    strike=43.,
    dip=89.,

    length=26*km,
    width=12*km,
    nucleation_x=-.6,
    nucleation_y=.3,
    # Relation between subsurface model s-wave velocity vs
    # and rupture velocity vr
    gamma=0.7,

    magnitude=7.,
    anchor='top',
    nthreads=5,

    nx=30,
    ny=20,

    # Tractions are in [Pa]. However here we are using relative tractions,
    # Resulting waveforms will be scaled to magnitude [Mw]
    # or a maximumslip [m]
    #
    # slip=3.,
    tractions=gf.tractions.TractionComposition(
        components=[
            gf.tractions.DirectedTractions(rake=56., traction=1.e6),
            gf.tractions.FractalTractions(rake=56., traction_max=.4e6),
            gf.tractions.RectangularTaper()
        ])
)

dyn_rupture.discretize_patches(store)

# Plot the absolute tractions from strike, dip, normal
plot = RuptureView(dyn_rupture, figsize=(8, 4))
plot.draw_patch_parameter('traction')
plot.draw_nucleation_point()
plot.save('dynamic_complex_tractions.png')

# Plot the modelled dislocations
plot = RuptureView(dyn_rupture, figsize=(8, 4))
plot.draw_dislocation()
# We can also define a time for the snapshot:
# plot.draw_dislocation(time=1.5)
plot.draw_time_contour(store)
plot.draw_nucleation_point()
plot.save('dynamic_complex_dislocations.png')

# Forward model waveforms for one station
engine = gf.LocalEngine(store_superdirs=['.'], use_config=True)
store = engine.get_store(store_id)

waveform_target = gf.Target(
    lat=0.,
    lon=0.,
    east_shift=10*km,
    north_shift=30.*km,
    store_id=store_id)

result = engine.process(dyn_rupture, waveform_target)
result.snuffle()
