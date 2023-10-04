# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for `DiGOS DATA-CUBE³ <https://digos.eu/the-seismic-data-recorder/>`_
raw data.
'''


import os
import math
import logging

import numpy as num

from pyrocko import trace, util, plot
from pyrocko.guts import Object, Int, String, Timestamp

from . import io_common

logger = logging.getLogger(__name__)

N_GPS_TAGS_WANTED = 200  # must match definition in datacube_ext.c

APPLY_SUBSAMPLE_SHIFT_CORRECTION = True


def color(c):
    c = plot.color(c)
    return tuple(x/255. for x in c)


class DataCubeError(io_common.FileLoadError):
    pass


class ControlPointError(Exception):
    pass


def make_control_point(ipos_block, t_block, tref, deltat):

    # reduce time (no drift would mean straight line)
    tred = (t_block - tref) - ipos_block*deltat

    # first round, remove outliers
    q25, q75 = num.percentile(tred, (25., 75.))
    iok = num.logical_and(q25 <= tred, tred <= q75)

    # detrend
    slope, offset = num.polyfit(ipos_block[iok], tred[iok], 1)
    tred2 = tred - (offset + slope * ipos_block)

    # second round, remove outliers based on detrended tred, refit
    q25, q75 = num.percentile(tred2, (25., 75.))
    iok = num.logical_and(q25 <= tred2, tred2 <= q75)
    x = ipos_block[iok].copy()
    ipos0 = x[0]
    x -= ipos0
    y = tred[iok].copy()
    if x.size < 2:
        raise ControlPointError('Insufficient number control points after QC.')

    elif x.size < 5:  # needed for older numpy versions
        (slope, offset) = num.polyfit(x, y, 1)
    else:
        (slope, offset), cov = num.polyfit(x, y, 1, cov=True)

        slope_err, offset_err = num.sqrt(num.diag(cov))

        slope_err_limit = 1.0e-10
        if ipos_block.size < N_GPS_TAGS_WANTED // 2:
            slope_err_limit *= (200. / ipos_block.size)

        offset_err_limit = 5.0e-3

        if slope_err > slope_err_limit:
            raise ControlPointError(
                'Slope error too large: %g (limit: %g' % (
                    slope_err, slope_err_limit))

        if offset_err > offset_err_limit:
            raise ControlPointError(
                'Offset error too large: %g (limit: %g' % (
                    offset_err, offset_err_limit))

    ic = ipos_block[ipos_block.size//2]
    tc = offset + slope * (ic - ipos0)

    return ic, tc + ic * deltat + tref


def analyse_gps_tags(header, gps_tags, offset, nsamples):

    ipos, t, fix, nsvs = gps_tags
    deltat = 1.0 / int(header['S_RATE'])

    tquartz = offset + ipos * deltat

    toff = t - tquartz
    toff_median = num.median(toff)

    n = t.size

    dtdt = (t[1:n] - t[0:n-1]) / (tquartz[1:n] - tquartz[0:n-1])

    ok = abs(toff_median - toff) < 10.

    xok = num.abs(dtdt - 1.0) < 0.00001

    if ok.size >= 1:

        ok[0] = False
        ok[1:n] &= xok
        ok[0:n-1] &= xok
        ok[n-1] = False

    ipos = ipos[ok]
    t = t[ok]
    fix = fix[ok]
    nsvs = nsvs[ok]

    blocksize = N_GPS_TAGS_WANTED // 2
    if ipos.size < blocksize:
        blocksize = max(10, ipos.size // 4)
        logger.warning(
            'Small number of GPS tags found. '
            'Reducing analysis block size to %i tags. '
            'Time correction may be unreliable.' % blocksize)

    try:
        if ipos.size < blocksize:
            raise ControlPointError(
                'Cannot determine GPS time correction: '
                'Too few GPS tags found: %i' % ipos.size)

        j = 0
        control_points = []
        tref = num.median(t - ipos*deltat)
        while j < ipos.size - blocksize:
            ipos_block = ipos[j:j+blocksize]
            t_block = t[j:j+blocksize]
            try:
                ic, tc = make_control_point(ipos_block, t_block, tref, deltat)
                control_points.append((ic, tc))
            except ControlPointError as e:
                logger.debug(str(e))

            j += blocksize

        ipos_last = ipos[-blocksize:]
        t_last = t[-blocksize:]
        try:
            ic, tc = make_control_point(ipos_last, t_last, tref, deltat)
            control_points.append((ic, tc))
        except ControlPointError as e:
            logger.debug(str(e))

        if len(control_points) < 2:
            raise ControlPointError(
                'Could not safely determine time corrections from GPS: '
                'unable to construct two or more control points')

        i0, t0 = control_points[0]
        i1, t1 = control_points[1]
        i2, t2 = control_points[-2]
        i3, t3 = control_points[-1]
        if len(control_points) == 2:
            tmin = t0 - i0 * deltat - offset * deltat
            tmax = t3 + (nsamples - i3 - 1) * deltat
        else:
            icontrol = num.array(
                [x[0] for x in control_points], dtype=num.int64)
            tcontrol = num.array(
                [x[1] for x in control_points], dtype=float)
            # robust against steps:
            slope = num.median(
                (tcontrol[1:] - tcontrol[:-1])
                / (icontrol[1:] - icontrol[:-1]))

            tmin = t0 + (offset - i0) * slope
            tmax = t2 + (offset + nsamples - 1 - i2) * slope

        if offset < i0:
            control_points[0:0] = [(offset, tmin)]

        if offset + nsamples - 1 > i3:
            control_points.append((offset + nsamples - 1, tmax))

        icontrol = num.array([x[0] for x in control_points], dtype=num.int64)
        tcontrol = num.array([x[1] for x in control_points], dtype=float)

        # corrected 2021-10-26: This sub-sample time shift introduced by the
        # Cube's ADC was previously not recognized.
        if APPLY_SUBSAMPLE_SHIFT_CORRECTION:
            tcontrol -= 0.199 * deltat + 0.0003

        return tmin, tmax, icontrol, tcontrol, ok

    except ControlPointError as e:
        logger.error(str(e))

        tmin = util.str_to_time(header['S_DATE'] + header['S_TIME'],
                                format='%y/%m/%d%H:%M:%S')

        idat = int(header['DAT_NO'])
        if idat == 0:
            tmin = tmin + util.gps_utc_offset(tmin)
        else:
            tmin = util.day_start(tmin + idat * 24.*3600.) \
                + util.gps_utc_offset(tmin)

        tmax = tmin + (nsamples - 1) * deltat
        icontrol = num.array([offset, offset+nsamples - 1], dtype=num.int64)
        tcontrol = num.array([tmin, tmax])
        return tmin, tmax, icontrol, tcontrol, ok


def plot_gnss_location_timeline(fns):
    from matplotlib import pyplot as plt
    from pyrocko.orthodrome import latlon_to_ne_numpy
    not_ = num.logical_not
    h = 3600.

    fig = plt.figure()

    axes = []
    for i in range(4):
        axes.append(
            fig.add_subplot(4, 1, i+1, sharex=axes[-1] if axes else None))

    background_colors = [
        color('aluminium1'),
        color('aluminium2')]

    tref = None
    for ifn, fn in enumerate(fns):
        header, gps_tags, nsamples = get_time_infos(fn)
        _, t, fix, nsvs, lats, lons, elevations, _ = gps_tags

        fix = fix.astype(bool)

        if t.size < 2:
            logger.warning('Need at least 2 gps tags for plotting: %s' % fn)

        if tref is None:
            tref = util.day_start(t[0])
            lat, lon, elevation = coordinates_from_gps(gps_tags)

        norths, easts = latlon_to_ne_numpy(lat, lon, lats, lons)

        for ax, data in zip(axes, (norths, easts, elevations, nsvs)):

            tspan = t[num.array([0, -1])]

            ax.axvspan(*((tspan - tref) / h), color=background_colors[ifn % 2])
            med = num.median(data)
            ax.plot(
                (tspan - tref) / h,
                [med, med],
                ls='--',
                c='k',
                lw=3,
                alpha=0.5)

            ax.plot(
                (t[not_(fix)] - tref) / h, data[not_(fix)], 'o',
                ms=1.5,
                mew=0,
                color=color('scarletred2'))

            ax.plot(
                (t[fix] - tref) / h, data[fix], 'o',
                ms=1.5,
                mew=0,
                color=color('aluminium6'))

    for ax in axes:
        ax.grid(alpha=.3)

    ax_lat, ax_lon, ax_elev, ax_nsv = axes

    ax_lat.set_ylabel('Northing [m]')
    ax_lon.set_ylabel('Easting [m]')
    ax_elev.set_ylabel('Elevation [m]')
    ax_nsv.set_ylabel('Number of Satellites')

    ax_lat.get_xaxis().set_tick_params(labelbottom=False)
    ax_lon.get_xaxis().set_tick_params(labelbottom=False)
    ax_nsv.set_xlabel(
        'Hours after %s' % util.time_to_str(tref, format='%Y-%m-%d'))

    fig.suptitle(
        u'Lat: %.5f\u00b0 Lon: %.5f\u00b0 Elevation: %g m' % (
            lat, lon, elevation))

    plt.show()


def coordinates_from_gps(gps_tags):
    ipos, t, fix, nsvs, lats, lons, elevations, temps = gps_tags
    return tuple(num.median(x) for x in (lats, lons, elevations))


def extract_stations(fns):
    import io
    import sys
    from pyrocko.model import Station
    from pyrocko.guts import dump_all

    stations = {}

    for fn in fns:
        sta_name = os.path.splitext(fn)[1].lstrip('.')
        if sta_name in stations:
            logger.warning('Cube %s already in list!', sta_name)
            continue

        header, gps_tags, nsamples = get_time_infos(fn)

        lat, lon, elevation = coordinates_from_gps(gps_tags)

        sta = Station(
            network='',
            station=sta_name,
            name=sta_name,
            location='',
            lat=lat,
            lon=lon,
            elevation=elevation)

        stations[sta_name] = sta

    f = io.BytesIO()
    dump_all(stations.values(), stream=f)
    sys.stdout.write(f.getvalue().decode())


def plot_timeline(fns):
    from matplotlib import pyplot as plt

    fig = plt.figure()
    axes = fig.gca()

    h = 3600.

    if isinstance(fns, str):
        fn = fns
        if os.path.isdir(fn):
            fns = [
                os.path.join(fn, entry) for entry in sorted(os.listdir(fn))]

            ipos, t, fix, nsvs, header, offset, nsamples = \
                get_timing_context(fns)

        else:
            ipos, t, fix, nsvs, header, offset, nsamples = \
                get_extended_timing_context(fn)

    else:
        ipos, t, fix, nsvs, header, offset, nsamples = \
            get_timing_context(fns)

    deltat = 1.0 / int(header['S_RATE'])

    tref = num.median(t - ipos * deltat)
    tref = round(tref / deltat) * deltat

    if APPLY_SUBSAMPLE_SHIFT_CORRECTION:
        tcorr = 0.199 * deltat + 0.0003
    else:
        tcorr = 0.0

    x = ipos*deltat
    y = (t - tref) - ipos*deltat - tcorr

    bfix = fix != 0
    bnofix = fix == 0

    tmin, tmax, icontrol, tcontrol, ok = analyse_gps_tags(
        header, (ipos, t, fix, nsvs), offset, nsamples)

    la = num.logical_and
    nok = num.logical_not(ok)

    axes.plot(
        x[la(bfix, ok)]/h, y[la(bfix, ok)], '+',
        ms=5, color=color('chameleon3'))
    axes.plot(
        x[la(bfix, nok)]/h, y[la(bfix, nok)], '+',
        ms=5, color=color('aluminium4'))

    axes.plot(
        x[la(bnofix, ok)]/h, y[la(bnofix, ok)], 'x',
        ms=5, color=color('chocolate3'))
    axes.plot(
        x[la(bnofix, nok)]/h, y[la(bnofix, nok)], 'x',
        ms=5, color=color('aluminium4'))

    tred = tcontrol - icontrol*deltat - tref
    axes.plot(icontrol*deltat/h, tred, color=color('aluminium6'))
    axes.plot(icontrol*deltat/h, tred, 'o', ms=5, color=color('aluminium6'))

    ymin = (math.floor(tred.min() / deltat)-1) * deltat
    ymax = (math.ceil(tred.max() / deltat)+1) * deltat
    # ymin = min(ymin, num.min(y))
    # ymax = max(ymax, num.max(y))

    if ymax - ymin < 1000 * deltat:
        ygrid = math.floor(tred.min() / deltat) * deltat
        while ygrid < ymax:
            axes.axhline(ygrid, color=color('aluminium4'), alpha=0.3)
            ygrid += deltat

    xmin = icontrol[0]*deltat/h
    xmax = icontrol[-1]*deltat/h
    xsize = xmax - xmin
    xmin -= xsize * 0.1
    xmax += xsize * 0.1
    axes.set_xlim(xmin, xmax)

    axes.set_ylim(ymin, ymax)

    axes.set_xlabel('Uncorrected (quartz) time [h]')
    axes.set_ylabel('Relative time correction [s]')

    plt.show()


g_dir_contexts = {}


class DirContextEntry(Object):
    path = String.T()
    tstart = Timestamp.T()
    ifile = Int.T()


class DirContext(Object):
    path = String.T()
    mtime = Timestamp.T()
    entries = DirContextEntry.T()

    def get_entry(self, fn):
        path = os.path.abspath(fn)
        for entry in self.entries:
            if entry.path == path:
                return entry

        raise Exception('entry not found')

    def iter_entries(self, fn, step=1):
        current = self.get_entry(fn)
        by_ifile = dict(
            (entry.ifile, entry) for entry in self.entries
            if entry.tstart == current.tstart)

        icurrent = current.ifile
        while True:
            icurrent += step
            try:
                yield by_ifile[icurrent]

            except KeyError:
                break


def context(fn):
    from pyrocko import datacube_ext

    dpath = os.path.dirname(os.path.abspath(fn))
    mtimes = [os.stat(dpath)[8]]

    dentries = sorted([os.path.join(dpath, f) for f in os.listdir(dpath)
                       if os.path.isfile(os.path.join(dpath, f))])
    for dentry in dentries:
        fn2 = os.path.join(dpath, dentry)
        mtimes.append(os.stat(fn2)[8])

    mtime = float(max(mtimes))

    if dpath in g_dir_contexts:
        dir_context = g_dir_contexts[dpath]
        if dir_context.mtime == mtime:
            return dir_context

        del g_dir_contexts[dpath]

    entries = []
    for dentry in dentries:
        fn2 = os.path.join(dpath, dentry)
        if not os.path.isfile(fn2):
            continue

        with open(fn2, 'rb') as f:
            first512 = f.read(512)
            if not detect(first512):
                continue

        with open(fn2, 'rb') as f:
            try:
                header, data_arrays, gps_tags, nsamples, _ = \
                        datacube_ext.load(f.fileno(), 3, 0, -1, None)

            except datacube_ext.DataCubeError as e:
                e = DataCubeError(str(e))
                e.set_context('filename', fn)
                raise e

        header = dict(header)
        entries.append(DirContextEntry(
            path=os.path.abspath(fn2),
            tstart=util.str_to_time(
                '20' + header['S_DATE'] + ' ' + header['S_TIME'],
                format='%Y/%m/%d %H:%M:%S'),
            ifile=int(header['DAT_NO'])))

    dir_context = DirContext(mtime=mtime, path=dpath, entries=entries)

    return dir_context


def get_time_infos(fn):
    from pyrocko import datacube_ext

    with open(fn, 'rb') as f:
        try:
            header, _, gps_tags, nsamples, _ = datacube_ext.load(
                f.fileno(), 1, 0, -1, None)

        except datacube_ext.DataCubeError as e:
            e = DataCubeError(str(e))
            e.set_context('filename', fn)
            raise e

    return dict(header), gps_tags, nsamples


def get_timing_context(fns):
    joined = [[], [], [], []]
    ioff = 0
    for fn in fns:
        header, gps_tags, nsamples = get_time_infos(fn)

        ipos = gps_tags[0]
        ipos += ioff

        for i in range(4):
            joined[i].append(gps_tags[i])

        ioff += nsamples

    ipos, t, fix, nsvs = [num.concatenate(x) for x in joined]

    nsamples = ioff
    return ipos, t, fix, nsvs, header, 0, nsamples


def get_extended_timing_context(fn):
    c = context(fn)

    header, gps_tags, nsamples_base = get_time_infos(fn)

    ioff = 0
    aggregated = [gps_tags]

    nsamples_total = nsamples_base

    if num.sum(gps_tags[2]) == 0:

        ioff = nsamples_base
        for entry in c.iter_entries(fn, 1):

            _, gps_tags, nsamples = get_time_infos(entry.path)

            ipos = gps_tags[0]
            ipos += ioff

            aggregated.append(gps_tags)
            nsamples_total += nsamples

            if num.sum(gps_tags[2]) > 0:
                break

            ioff += nsamples

        ioff = 0
        for entry in c.iter_entries(fn, -1):

            _, gps_tags, nsamples = get_time_infos(entry.path)

            ioff -= nsamples

            ipos = gps_tags[0]
            ipos += ioff

            aggregated[0:0] = [gps_tags]

            nsamples_total += nsamples

            if num.sum(gps_tags[2]) > 0:
                break

    ipos, t, fix, nsvs = [num.concatenate(x) for x in zip(*aggregated)][:4]

#    return ipos, t, fix, nsvs, header, ioff, nsamples_total
    return ipos, t, fix, nsvs, header, 0, nsamples_base


def iload(fn, load_data=True, interpolation='sinc'):
    from pyrocko import datacube_ext
    from pyrocko import signal_ext

    if interpolation not in ('sinc', 'off'):
        raise NotImplementedError(
            'no such interpolation method: %s' % interpolation)

    with open(fn, 'rb') as f:
        if load_data:
            loadflag = 2
        else:
            loadflag = 1

        try:
            header, data_arrays, gps_tags, nsamples, _ = datacube_ext.load(
                f.fileno(), loadflag, 0, -1, None)

        except datacube_ext.DataCubeError as e:
            e = DataCubeError(str(e))
            e.set_context('filename', fn)
            raise e

    header = dict(header)
    deltat = 1.0 / int(header['S_RATE'])
    nchannels = int(header['CH_NUM'])

    ipos, t, fix, nsvs, header_, offset_, nsamples_ = \
        get_extended_timing_context(fn)

    tmin, tmax, icontrol, tcontrol, _ = analyse_gps_tags(
        header_, (ipos, t, fix, nsvs), offset_, nsamples_)

    if icontrol is None:
        logger.warning(
            'No usable GPS timestamps found. Using datacube header '
            'information to guess time. (file: "%s")' % fn)

    tmin_ip = round(tmin / deltat) * deltat
    if interpolation != 'off':
        tmax_ip = round(tmax / deltat) * deltat
    else:
        tmax_ip = tmin_ip + (nsamples-1) * deltat

    nsamples_ip = int(round((tmax_ip - tmin_ip)/deltat)) + 1
    # to prevent problems with rounding errors:
    tmax_ip = tmin_ip + (nsamples_ip-1) * deltat

    leaps = num.array(
        [x[0] + util.gps_utc_offset(x[0]) for x in util.read_leap_seconds2()],
        dtype=float)

    if load_data and icontrol is not None:
        ncontrol_this = num.sum(
            num.logical_and(0 <= icontrol, icontrol < nsamples))

        if ncontrol_this <= 1:
            logger.warning(
                'Extrapolating GPS time information from directory context '
                '(insufficient number of GPS timestamps in file: "%s").' % fn)

    for i in range(nchannels):
        if load_data:
            arr = data_arrays[i]
            assert arr.size == nsamples

            if interpolation == 'sinc' and icontrol is not None:

                ydata = num.empty(nsamples_ip, dtype=float)
                try:
                    signal_ext.antidrift(
                        icontrol, tcontrol,
                        arr.astype(float), tmin_ip, deltat, ydata)

                except signal_ext.Error as e:
                    e = DataCubeError(str(e))
                    e.set_context('filename', fn)
                    e.set_context('n_control_points', icontrol.size)
                    e.set_context('n_samples_raw', arr.size)
                    e.set_context('n_samples_ip', ydata.size)
                    e.set_context('tmin_ip', util.time_to_str(tmin_ip))
                    raise e

                ydata = num.round(ydata).astype(arr.dtype)
            else:
                ydata = arr

            tr_tmin = tmin_ip
            tr_tmax = None
        else:
            ydata = None
            tr_tmin = tmin_ip
            tr_tmax = tmax_ip

        tr = trace.Trace('', header['DEV_NO'], '', 'p%i' % i, deltat=deltat,
                         ydata=ydata, tmin=tr_tmin, tmax=tr_tmax, meta=header)

        bleaps = num.logical_and(tmin_ip <= leaps, leaps < tmax_ip)

        if num.any(bleaps):
            assert num.sum(bleaps) == 1
            tcut = leaps[bleaps][0]

            for tmin_cut, tmax_cut in [
                    (tr.tmin, tcut), (tcut, tr.tmax+tr.deltat)]:

                try:
                    tr_cut = tr.chop(tmin_cut, tmax_cut, inplace=False)
                    tr_cut.shift(
                        util.utc_gps_offset(0.5*(tr_cut.tmin+tr_cut.tmax)))
                    yield tr_cut

                except trace.NoData:
                    pass

        else:
            tr.shift(util.utc_gps_offset(0.5*(tr.tmin+tr.tmax)))
            yield tr


header_keys = {
    str: b'GIPP_V DEV_NO E_NAME GPS_PO S_TIME S_DATE DAT_NO'.split(),
    int: b'''P_AMPL CH_NUM S_RATE D_FILT C_MODE A_CHOP F_TIME GPS_TI GPS_OF
            A_FILT A_PHAS GPS_ON ACQ_ON V_TCXO D_VOLT E_VOLT'''.split()}

all_header_keys = header_keys[str] + header_keys[int]


def detect(first512):
    s = first512

    if len(s) < 512:
        return False

    if ord(s[0:1]) >> 4 != 15:
        return False

    n = s.find(b'\x80')
    if n == -1:
        n = len(s)

    s = s[1:n]
    s = s.replace(b'\xf0', b'')
    s = s.replace(b';', b' ')
    s = s.replace(b'=', b' ')
    kvs = s.split(b' ')

    if len([k for k in all_header_keys if k in kvs]) == 0:
        return False
    return True


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Datacube reader')

    parser.add_argument(
        'action', choices=['timeline', 'gnss', 'stations'],
        help='Action')
    parser.add_argument(
        'files', nargs='+')

    parser.add_argument(
        '--loglevel', '-l',
        choices=['critical', 'error', 'warning', 'info', 'debug'],
        default='info',
        help='Set logger level. Default: %(default)s')

    args = parser.parse_args()

    util.setup_logging('pyrocko.io.datacube', args.loglevel)
    logging.getLogger('matplotlib.font_manager').disabled = True

    if args.action == 'timeline':
        plot_timeline(args.files)

    elif args.action == 'gnss':
        plot_gnss_location_timeline(args.files)

    elif args.action == 'stations':
        extract_stations(args.files)
