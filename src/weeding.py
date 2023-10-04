# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
An algorithm to select station subsets with good coverage in azimuth and
distance.
'''

import numpy as num


def neighborhood_density(dists, neighborhood=1):
    sdists = dists.copy()
    sdists.sort(axis=1)
    meandists = num.mean(sdists[:, 1:1+neighborhood], axis=1)
    return meandists


def _weed(dists, badnesses, neighborhood=1, interaction_radius=3.,
          del_frac=4, max_del=100, max_depth=100, depth=0):

    if depth > max_depth:
        assert False, 'max recursion depth reached'

    meandists = neighborhood_density(dists, neighborhood)

    order = meandists.argsort()
    candidates = order[:order.size//del_frac+1]
    badness_candidates = badnesses[candidates]
    order_badness = (-badness_candidates).argsort()

    order[:order.size//del_frac+1] = \
        order[:order.size//del_frac+1][order_badness]

    deleted = num.zeros(order.size, dtype=bool)
    ndeleted = 0
    for i, ind in enumerate(order):
        if (i < order.size // del_frac // 2 + 1
                and ndeleted < max_del
                and num.all(
                    dists[ind, deleted] > interaction_radius*meandists[ind])):

            deleted[ind] = True
            ndeleted += 1

    if ndeleted == 0:
        return deleted

    kept = num.logical_not(deleted)
    xdists = dists[kept][:, kept]
    xbadnesses = badnesses[kept]
    xdeleted = _weed(xdists, xbadnesses, neighborhood, interaction_radius,
                     del_frac, max_del-ndeleted, max_depth, depth+1)

    deleted[kept] = xdeleted
    return deleted


def weed(x, y, badnesses, neighborhood=1, nwanted=None, interaction_radius=3.):
    assert x.size == y.size
    n = x.size
    NEW = num.newaxis
    ax = x[NEW, :]
    ay = y[NEW, :]
    bx = x[:, NEW]
    by = y[:, NEW]

    if nwanted is None:
        nwanted = n // 2

    dx = num.abs(ax-bx)
    dx = num.where(dx > 180., 360.-dx, dx)

    dists = num.sqrt(dx**2 + (ay-by)**2)
    deleted = _weed(
        dists, badnesses, neighborhood, interaction_radius, del_frac=4,
        max_del=n-nwanted, max_depth=500, depth=0)

    kept = num.logical_not(deleted)
    dists_kept = dists[kept][:, kept]
    meandists_kept = neighborhood_density(dists_kept, neighborhood)
    return deleted, meandists_kept


def badnesses_c_mean(badnesses_nslc):
    # convert stream badnesses to station badnesses by averaging
    badnesses_nsl = {}
    for nslc, b in badnesses_nslc.items():
        nsl = nslc[:3]
        badnesses_nsl.setdefault(nsl, []).append(b)

    for nsl in list(badnesses_nsl.keys()):
        this_station_badness = badnesses_nsl[nsl]
        badnesses_nsl[nsl] = sum(this_station_badness) \
            / len(this_station_badness)

    return badnesses_nsl


def weed_stations(stations, nwanted, neighborhood=3, default_badness=1.0,
                  badnesses=None,
                  badnesses_ns={}, badnesses_nsl={}, badnesses_nslc={}):

    azimuths = num.zeros(len(stations), dtype=float)
    dists = num.zeros(len(stations), dtype=float)
    for ista, sta in enumerate(stations):
        azimuths[ista] = sta.azimuth
        dists[ista] = sta.dist_deg

    badnesses_nslc_mean_c = badnesses_c_mean(badnesses_nslc)
    badnesses2 = num.ones(len(stations), dtype=float)
    for ista, sta in enumerate(stations):
        nsl = sta.network, sta.station, sta.location
        if badnesses is not None:
            b = badnesses[ista]
        else:
            b = 1.0
        b *= badnesses_ns.get(nsl, 1.0)
        b *= badnesses_nsl.get(nsl, 1.0)
        b *= badnesses_nslc_mean_c.get(nsl, 1.0)
        badnesses2[ista] = b

    deleted, meandists_kept = weed(
        azimuths, dists, badnesses2,
        nwanted=nwanted,
        neighborhood=neighborhood)

    stations_weeded = [station for (delete, station) in zip(deleted, stations)
                       if not delete]

    return stations_weeded, meandists_kept, deleted
