import os.path
import numpy as num
import matplotlib.pyplot as plt
from pyrocko import gf

km = 1e3

# Download a Greens Functions store, programmatically.
store_id = 'gf_abruzzo_nearfield_vmod_Ameri'
if not os.path.exists(store_id):
    gf.ws.download_gf_store(site='kinherd', store_id=store_id)

# Ignite the LocalEngine and point it to your fomosto store at '.'
engine = gf.LocalEngine(store_superdirs=['.'])

# RectangularSource parameters
strike = 90.
dip = 40.
dep = 10.5*km
leng = 10.*km
wid = 10.*km
rake = 90.
slip = .5

# Magnitude of the event
potency = leng * wid * slip
rigidity = 31.5e9
m0 = potency*rigidity
mw = (2./3) * num.log10(m0) - 6.07

# Define an extended RectangularSource
thrust = gf.RectangularSource(
    north_shift=0., east_shift=0.,
    depth=dep, width=wid, length=leng,
    dip=dip, rake=rake, strike=strike,
    slip=slip)

# Define a grid of targets
# number in east and north directions, and total
ngrid = 40
# ngrid = 90  # for better resolution

# extension from origin in all directions
obs_size = 20.*km
ntargets = ngrid**2

norths = num.linspace(-obs_size, obs_size, ngrid)
easts = num.linspace(-obs_size, obs_size, ngrid)

# make regular grid
norths2d = num.repeat(norths, len(easts))
easts2d = num.tile(easts, len(norths))

# Initialize the SatelliteTarget and set the line of site vectors
# Case example of the Sentinel-1 satellite:
#
# Heading: -166 (anti-clockwise rotation from east)
# Average Look Angle: 36 (from vertical)
heading = -76.
look = 36.
phi = num.empty(ntargets)  # Horizontal LOS from E in anti-clockwise rotation
theta = num.empty(ntargets)  # Vertical LOS from horizontal
phi.fill(num.deg2rad(-90-heading))
theta.fill(num.deg2rad(90.-look))

satellite_target = gf.SatelliteTarget(
    north_shifts=norths2d,
    east_shifts=easts2d,
    tsnapshot=24.*3600.,    # one day
    interpolation='nearest_neighbor',
    phi=phi,
    theta=theta,
    store_id=store_id)

# Forward-modell is performed by calling 'process' on the engine
result = engine.process(thrust, [satellite_target])

# Retrieve synthetic displacements and coordinates from engine's result
# of the first target (it=0)
it = 0
N = result.request.targets[it].coords5[:, 2]
E = result.request.targets[it].coords5[:, 3]
synth_disp = result.results_list[0][it].result

# Fault projection to the surface for plotting
n, e = thrust.outline(cs='xy').T

fig, _ = plt.subplots(1, 2, figsize=(8, 4))
fig.suptitle(
    "fault: dep={:0.2f}, l={}, w={:0.2f},str={},"
    "rake={}, dip={}, slip={}, Mw={:0.3f}\n"
    "satellite: heading={}, look angle={}"
    .format(dep/km, leng/km, wid/km,
            strike, rake, dip, slip, heading, look, mw),
    fontsize=14,
    fontweight='bold')

# Shift the relative LOS displacements
los = synth_disp['displacement.los']
losmax = num.abs(los).max()

# Plot unwrapped LOS displacements
ax = fig.axes[0]
cmap = ax.scatter(
    E, N, c=los,
    s=10., marker='s',
    edgecolor='face',
    cmap=plt.get_cmap('seismic'),
    vmin=-1.*losmax, vmax=1.*losmax)

ax.set_title('line-of-sight displacement [m]')
ax.set_aspect('equal')
ax.set_xlim(-obs_size, obs_size)
ax.set_ylim(-obs_size, obs_size)
# Fault outline
ax.fill(e, n, color=(0.5, 0.5, 0.5), alpha=0.5)
# Underline the tip of the thrust
ax.plot(e[:2], n[:2], linewidth=2., color='black', alpha=0.5)

fig.colorbar(cmap, ax=ax, orientation='vertical', aspect=5, shrink=0.5)

# Simulate a C-band interferogram for this source
c_lambda = 0.056
insar_phase = -num.mod(los, c_lambda/2.)/(c_lambda/2.)*2.*num.pi - num.pi

# Plot wrapped phase
ax = fig.axes[1]
cmap = ax.scatter(
    E, N, c=insar_phase,
    s=10., marker='s',
    edgecolor='face',
    cmap=plt.get_cmap('gist_rainbow'))

ax.set_xlim(-obs_size, obs_size)
ax.set_ylim(-obs_size, obs_size)
ax.set_title('simulated interferogram')
ax.set_aspect('equal')

# plot fault outline
ax.fill(e, n, color=(0.5, 0.5, 0.5), alpha=0.5)
# We outline the top edge of the fault with a thick line
ax.plot(e[:2], n[:2], linewidth=2., color='black', alpha=0.5)

fig.colorbar(cmap, orientation='vertical', shrink=0.5, aspect=5)
plt.show()
