import os

import numpy as num
from scipy.interpolate import RegularGridInterpolator as scrgi

from pyrocko.plot.automap import Map
from pyrocko import gmtpy
import pyrocko.orthodrome as otd

gmtpy.check_have_gmt()
gmt = gmtpy.GMT()

km = 1000.

# Generate the basic map
lat = -31.
lon = -72.
m = Map(
    lat=lat,
    lon=lon,
    radius=250000.,
    width=30., height=30.,
    show_grid=False,
    show_topo=True,
    color_dry=(238, 236, 230),
    topo_cpt_wet='light_sea_uniform',
    topo_cpt_dry='light_land_uniform',
    illuminate=True,
    illuminate_factor_ocean=0.15,
    show_rivers=False,
    show_plates=True)

# Draw some larger cities covered by the map area
m.draw_cities()

# Create grid and data
x = num.linspace(-100., 100., 200) * km
y = num.linspace(-50., 50., 100) * km
yy, xx = num.meshgrid(y, x)

data = num.log10(xx**2 + yy**2)


def extend_1d_coordinate_array(array):
    '''
    Extend 1D coordinate array for gridded data, that grid corners are plotted
    right
    '''
    dx = array[1] - array[0]

    out = num.zeros(array.shape[0] + 2)
    out[1:-1] = array.copy()
    out[0] = array[0] - dx / 2.
    out[-1] = array[-1] + dx / 2.

    return out

def extend_2d_data_array(array):
    '''
    Extend 2D data array for gridded data, that grid corners are plotted
    right
    '''
    out = num.zeros((array.shape[0] + 2, array.shape[1] + 2))
    out[1:-1, 1:-1] = array
    out[1:-1, 0] = array[:, 0]
    out[1:-1, -1] = array[:, -1]
    out[0, 1:-1] = array[0, :]
    out[-1, 1:-1] = array[-1, :]

    for i, j in zip([-1, -1, 0, 0], [-1, 0, -1, 0]):
        out[i, j] = array[i, j]

    return out

def tile_to_length_width(m, ref_lat, ref_lon):
    '''
    Transform grid tile (lat, lon) to easting, northing for data interpolation
    '''
    t, _ = m._get_topo_tile('land')
    grid_lats = t.y()
    grid_lons = t.x()

    meshgrid_lons, meshgrid_lats = num.meshgrid(grid_lons, grid_lats)

    grid_northing, grid_easting = otd.latlon_to_ne_numpy(
        ref_lat, ref_lon, meshgrid_lats.flatten(), meshgrid_lons.flatten())

    return num.hstack((
        grid_easting.reshape(-1, 1), grid_northing.reshape(-1, 1)))

def data_to_grid(m, x, y, data):
    '''
    Create data grid from data and coordinate arrays
    '''
    assert data.shape == (x.shape[0], y.shape[0])

    # Extend grid coordinate and data arrays to plot grid corners right
    x_ext = extend_1d_coordinate_array(x)
    y_ext = extend_1d_coordinate_array(y)
    data_ext = extend_2d_data_array(data)

    # Create grid interpolator based on given coordinates and data
    interpolator = scrgi(
        (x_ext, y_ext),
        data_ext,
        bounds_error=False,
        method='nearest')

    # Interpolate on topography grid from the map
    points_out = tile_to_length_width(m=m, ref_lat=lat, ref_lon=lon)

    t, _ = m._get_topo_tile('land')
    t.data = num.zeros_like(t.data, dtype=num.float)
    t.data[:] = num.nan

    t.data = interpolator(points_out).reshape(t.data.shape)

    # Save grid as grd-file
    gmtpy.savegrd(t.x(), t.y(), t.data, filename='temp.grd', naming='lonlat')


# Create data grid file
data_to_grid(m, x, y, data)

# Create appropiate colormap
increment = (num.max(data) - num.min(data)) / 20.
gmt.makecpt(
    C='0/127.6/102,255/255/102',
    T='%g/%g/%g' % (num.min(data), num.max(data), increment),
    Z=True,
    out_filename='my_cpt.cpt',
    suppress_defaults=True)

# Plot grid image
m.gmt.grdimage(
    'temp.grd',
    C='my_cpt.cpt',
    E='200',
    I='0.1',
    Q=True,
    n='+t0.15',
    *m.jxyr)

# Plot corresponding contour
m.gmt.grdcontour(
    'temp.grd',
    A='0.5',
    C='0.1',
    S='10',
    W='a1.0p',
    *m.jxyr)

# Plot color scake
m.gmt.psscale(
    B='af+lScale [m]',
    C='my_cpt.cpt',
    D='jTR+o1.05c/0.2c+w10c/1c+h',
    F='+g238/236/230',
    *m.jxyr)

# Save plot
m.save('automap_chile.png', resolution=150)

# Clear temporary files
os.remove('temp.grd')
os.remove('my_cpt.cpt')
