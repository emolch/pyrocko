import os
from pyrocko.plot.directivity import plot_directivity
from pyrocko.gf import LocalEngine, RectangularSource, ws

km = 1e3
# The store we are going extract data from:
store_id = 'iceland_reg_v2'

# First, download a Greens Functions store. If you already have one that you
# would like to use, you can skip this step and point the *store_superdirs* in
# the next step to that directory.

if not os.path.exists(store_id):
    ws.download_gf_store(site='kinherd', store_id=store_id)

# We need a pyrocko.gf.Engine object which provides us with the traces
# extracted from the store.
engine = LocalEngine(store_superdirs=['.'])

# Create a RectangularSource with uniform fit.
rect_source = RectangularSource(
    depth=1.6*km,
    strike=240.,
    dip=76.6,
    rake=-.4,
    anchor='top',

    nucleation_x=-.57,
    nucleation_y=-.59,
    velocity=2070.,

    length=27*km,
    width=9.4*km,
    slip=1.4)


resp = plot_directivity(
    engine, rect_source, store_id,
    distance=300*km, dazi=5., component='R',
    plot_mt='full', show_phases=True,
<<<<<<< HEAD
    phases={
        'First': 'first{stored:begin}-10%',
        'Last': 'last{stored:end}+20'
    },
    quantity='displacement', envelope=True)
=======
    phase_begin='first{stored:begin}-10%',
    phase_end='last{stored:end}+20',
>>>>>>> add okada modelling and pseudo-dynamic rupture model (chapter 18)
