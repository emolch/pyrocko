import os.path as op
from pyrocko import gf

km = 1e3

# Download a Greens Functions store
store_id = 'crust2_ib'

if not op.exists(store_id):
    gf.ws.download_gf_store(site='kinherd', store_id=store_id)


engine = gf.LocalEngine(store_superdirs=['.'], use_config=True)
store = engine.get_store(store_id)

dyn_rupture = gf.PseudoDynamicRupture(
    lat=0.,
    lon=0.,
    north_shift=0*km,
    east_shift=0*km,
    depth=3*km,

    width=12*km,
    length=29*km,

    strike=43.,
    dip=89.,
    rake=88.,

    # Number of discrete patches
    nx=15,
    ny=15,
    # Relation between subsurface model s-wave velocity vs
    # and rupture velocity vr
    gamma=0.7,

    magnitude=7.,
    anchor='top')

waveform_target = gf.Target(
    lat=0.,
    lon=0.,
    east_shift=10*km,
    north_shift=10.*km,
    store_id=store_id)

result = engine.process(dyn_rupture, waveform_target)
result.snuffle()
