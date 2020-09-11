import logging
import os

import numpy as num
import matplotlib.pyplot as plt

from pyrocko import trace, util
from pyrocko.gf import PseudoDynamicRupture, LocalEngine, Target, tractions, ws
from pyrocko.plot import dynamic_rupture
from pyrocko.plot import mpl_graph_color


logger = logging.getLogger('pyrocko.examples.gf_forward_pseudo_rupture2')
util.setup_logging(levelname='info')

d2r = num.pi / 180.
km2m = 1000.

# Example of a self-similar traction field with increasing complexity used for
# the Pseudo Dynamic Rupture source model.

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
nx, ny = int(num.ceil(length / 2000.)), int(num.ceil(width / 2000.))
nyq = int(num.floor(num.min((nx, ny))/2.))

logger.info('nx: %i, ny: %i' % (nx, ny))
logger.info('ranks <= %i for no aliasing' % nyq)

# Define the ranks (maximum wavenumber) and phases for the cosine functions
# in the SelfSimiliarTractions
ranks = num.array([1, 2, 5, 10])
phases = num.array([
    -0.9120799, 1.40519485, -0.80165805, 1.65676832, 1.04067916, -2.58736667,
    1.27630965, -2.55843096, 2.13857185, 1.01601178])

# Let's create the PseudoDynamicRupture using self similar tractions
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
    tractions=tractions.SelfSimilarTractions(
        rank=ranks[0], rake=0, phases=phases[:1]))

# The source needs to be discretized into finite faults (patches) with
# associated elastic parameters taken from the store.
source.discretize_patches(store)

# A key element of the PseudoDynamicRupture is the linkage of the tractions on
# the patches with their dislocations. The linear coefficients describing the
# link are obtained based on Okada (1992) and a boundary element method
source.calc_coef_mat()

synthetic_traces = []
channel_codes = 'ENZ'

for rank in ranks:
    logger.info('Modelling for rank %i' % rank)

    # Update source traction rank and phases for increasing number of summed
    # cosines
    source.tractions.rank = rank
    source.tractions.phases = phases[:rank]

    # Display absolut tractions and final absolut dislocations
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
            codes=('', 'STA', '%02d' % rank, channel_code))
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
            label='ratio = %g' % int(tr.location))

    ax.set_ylim((1e-5, 1.))
    ax.set_title(c)
    ax.set_ylabel('amplitude [counts]')
    ax.legend(loc='best')

axes[-1].set_xlabel('frequency [Hz]')
plt.show()
