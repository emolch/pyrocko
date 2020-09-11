import logging
import os

import numpy as num
import matplotlib.pyplot as plt

from pyrocko import trace, util
from pyrocko.gf import PseudoDynamicRupture, LocalEngine, Target, tractions, ws
from pyrocko.plot import dynamic_rupture
from pyrocko.plot import mpl_graph_color


logger = logging.getLogger('pyrocko.examples.gf_forward_pseudo_rupture3')
util.setup_logging(levelname='info')

d2r = num.pi / 180.
km2m = 1000.


# Example of a fractal perturbed traction field used for the Pseudo Dynamic
# Rupture source model.

# The store we are going extract data from:
store_id = 'iceland_reg_v2'

# First, download a Greens Functions store. If you already have one that you
# would like to use, you can skip this step and point the *store_superdirs* in
# the next step to that directory.

if not os.path.exists(store_id):
    ws.download_gf_store(site='kinherd', store_id=store_id)

# We need a pyrocko.gf.Engine object which provides us with the traces
# extracted from the store. In this case we are going to use a local
# engine since we are going to query a local store.
engine = LocalEngine(store_superdirs=['.'], default_store_id=store_id)

# The dynamic parameter used for discretization of the PseudoDynamicRupture are
# extracted from the stores config file.
store = engine.get_store(store_id)

# Length and Width are defined based from Wells and Coppersmith (1994).
mag = 7.5
length = 10**(-2.44 + 0.59 * mag) * km2m
width = 10**(-1.01 + 0.32 * mag) * km2m
nx = int(num.ceil(length / (2. * km2m)))
ny = int(num.ceil(width / (2. * km2m)))

logger.info('nx: %i, ny: %i' % (nx, ny))

# Define fractal traction to directed traction ratios for display of the effect
traction_ratio = num.power(num.ones(5) * 10, num.arange(-2, 3))

# Let's create the PseudoDynamicRupture using combined fractal and directed
# tractions
source = PseudoDynamicRupture(
    lat=0.,
    lon=0.,
    length=length,
    width=width,
    depth=10. * km2m,
    strike=0.,
    dip=0.,
    anchor='top',
    gamma=0.6,
    nucleation_x=0.25,
    nucleation_y=-0.5,
    nx=nx,
    ny=ny,
    pure_shear=True,
    smooth_rupture=True,
    magnitude=mag,
    tractions=tractions.TractionComposition(components=[
        tractions.FractalTractions(
            rake=0, no_rstate=None, traction_max=traction_ratio[0]),
        tractions.DirectedTractions(
            rake=0, traction=1.)]))

# The source needs to be discretized into finite faults (patches) with
# associated elastic parameters taken from the store.
source.discretize_patches(store)

# A key element of the PseudoDynamicRupture is the linkage of the tractions on
# the patches with their dislocations. The linear coefficients describing the
# link are obtained based on Okada (1992) and a boundary element method
source.calc_coef_mat()

synthetic_traces = []
channel_codes = 'ENZ'

for it, t in enumerate(traction_ratio):
    # Display absolut tractions and final absolut dislocations
    logger.info('Modelling for fractal traction for traction ratio %g' % t)

    source.tractions.components[0].traction_max = t

    viewer = dynamic_rupture.RuptureView(source=source)
    viewer.draw_patch_parameter('traction')
    viewer.draw_time_contour(store)
    viewer.show_plot()

    viewer = dynamic_rupture.RuptureView(source=source)
    viewer.draw_dislocation()
    viewer.draw_time_contour(store)
    viewer.show_plot()

    # Define a list of pyrocko.gf.Target objects, representing the recording
    # devices. In this case one station with a three component sensor will
    # serve fine for demonstation.logger.info('Modelling synthetic waveforms')
    targets = [
        Target(
            lat=3.,
            lon=2.,
            store_id=store_id,
            codes=('', 'STA', '%g' % it, channel_code))
        for channel_code in channel_codes]

    # Processing that data will return a pyrocko.gf.Reponse object.
    response = engine.process(source, targets)

    # This will return a list of the requested traces:
    synthetic_traces += response.pyrocko_traces()

# Finally, let's scrutinize these traces.
trace.snuffle(synthetic_traces)

# Plot the component-wise amplitude spectra
fig, axes = plt.subplots(3, 1)
linestyles = ['solid', 'dashed', 'dotted', 'dashdot', (0, (3, 1, 1, 1, 1, 1))]

for c, ax in zip(channel_codes, axes):
    selected_traces = [tr for tr in synthetic_traces if tr.channel == c]

    for i, (tr, linestyle) in enumerate(zip(selected_traces, linestyles)):
        tr.ydata -= tr.ydata.mean()
        freqs, amps = tr.spectrum(tfade=None)
        amps = num.abs(amps)

        ax.loglog(
            freqs,
            amps,
            linestyle=linestyle,
            c=mpl_graph_color(i),
            label='ratio = %g' % traction_ratio[int(tr.location)])

    ax.set_ylim((1e-5, 1.))
    ax.set_title(c)
    ax.set_ylabel('amplitude [counts]')
    ax.legend(loc='best')

axes[-1].set_xlabel('frequency [Hz]')
plt.show()
