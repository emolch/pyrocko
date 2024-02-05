
from pyrocko import gf, trace


comp_azi = {
    'N': 0.0,
    'E': 90.0,
    'D': 0.0}

comp_dip = {
    'N': 0.0,
    'E': 0.0,
    'D': 90.0}


def fd_rot_surface_targets(delta, target):

    assert target.interpolation == 'multilinear'
    assert target.quantity == 'displacement'

    targets = []
    for kn in [-1, 0, 1]:
        for ke in [-1, 0, 1]:
            for comp in 'NED':
                targets.append(gf.Target(
                    codes=target.codes[:3] + (comp,),
                    quantity='displacement',
                    lat=target.lat,
                    lon=target.lon,
                    north_shift=target.north_shift + kn * delta,
                    east_shift=target.east_shift + ke * delta,
                    azimuth=comp_azi[comp],
                    dip=comp_dip[comp],
                    interpolation='multilinear',
                    store_id=target.store_id))

    return targets


def fd_rot_surface_postprocess(delta, traces, rfmax=0.8):

    deltat = traces[0].deltat
    fnyquist = 0.5 / deltat
    fmax = rfmax * fnyquist
    tpad = 2.0 / fmax
    tmin = min(tr.tmin for tr in traces)
    tmax = max(tr.tmax for tr in traces)
    traces_prepared = []

    for tr in traces:
        tr.extend(tmin-tpad, tmax+tpad, fillmethod='repeat')
        tr_filt = tr.transfer(
            tfade=tpad,
            freqlimits=(-1., -1., fmax, fnyquist),
            demean=False)

        traces_prepared.append(tr_filt)

        tr_filt.set_location('filtered')

    # trace.snuffle(traces + traces_prepared)

    d = trace.get_traces_data_as_array(traces_prepared)
    d = d.reshape((3, 3, 3, d.shape[1]))

    kn, ke, kd = 0, 1, 2
    il, ic, ih = 0, 1, 2

    dd_de = (d[ic, ih, kd] - d[ic, il, kd]) / (2.*delta)
    dd_dn = (d[ih, ic, kd] - d[il, ic, kd]) / (2.*delta)
    dn_de = (d[ic, ih, kn] - d[ic, il, kn]) / (2.*delta)
    de_dn = (d[ih, ic, ke] - d[il, ic, ke]) / (2.*delta)

    d_rot = [
        dd_de,
        - dd_dn,
        0.5 * (de_dn - dn_de)]

    traces_rot = []
    for comp, data in zip('NED', d_rot):
        tr = trace.Trace(
            network=traces[0].network,
            station=traces[0].station,
            location=traces[0].location,
            channel='ROT_%s' % comp,
            deltat=deltat,
            tmin=tmin,
            ydata=data)
        # tr.differentiate(1)
        traces_rot.append(tr)

    traces_dis, traces_vel, traces_acc = [], [], []
    for comp, data in zip('NED', d[ic, ic, :]):
        tr_dis = traces[0].copy()
        tr_dis.set_ydata(data)
        tr_dis.set_codes(channel='DIS_%s' % comp)
        tr_vel = tr_dis.differentiate(1, inplace=False)
        tr_vel.set_codes(channel='VEL_%s' % comp)
        tr_acc = tr_dis.differentiate(2, inplace=False)
        tr_acc.set_codes(channel='ACC_%s' % comp)
        traces_dis.append(tr_dis)
        traces_vel.append(tr_vel)
        traces_acc.append(tr_acc)

    return traces_dis, traces_vel, traces_acc, traces_rot
