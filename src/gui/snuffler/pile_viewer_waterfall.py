import logging
import hashlib
import time
import numpy as num
from scipy import signal

from matplotlib.cm import get_cmap
from matplotlib.colors import Normalize

from pyrocko.trace import t2ind
from ..qt_compat import qg

logger = logging.getLogger(__name__)


DEFAULT_CMAP = 'viridis'


class TraceWaterfall:

    def __init__(self):
        self.tmin = 0.
        self.tmax = 0.
        self.traces = []

        self._current_cmap = None
        self.cmap = None
        self.norm = Normalize()

        self._data_cache = None

        self._show_absolute = False
        self._integrate = False
        self._clip_min = 0.
        self._clip_max = 1.
        self._common_scale = True

        self.set_cmap(DEFAULT_CMAP)

    def set_traces(self, traces):
        self.traces = traces

    def set_time_range(self, tmin, tmax):
        self.tmin = tmin
        self.tmax = tmax

    def set_clip(self, clip_min, clip_max):
        assert 0. <= clip_min < clip_max <= 1.
        self._clip_min = clip_min
        self._clip_max = clip_max

    def set_integrate(self, integrate):
        self._integrate = integrate

    def show_absolute_values(self, show_absolute):
        self._show_absolute = show_absolute

    def set_cmap(self, cmap):
        if cmap == self._current_cmap:
            return
        logger.debug('setting colormap to %s', cmap)
        self.cmap = get_cmap(cmap)
        self._current_cmap = cmap

    def set_common_scale(self, _common_scale):
        self._common_scale = _common_scale

    def get_state_hash(self):
        sha1 = hashlib.sha1()
        sha1.update(self.tmin.hex().encode())
        sha1.update(self.tmax.hex().encode())
        sha1.update(self._clip_min.hex().encode())
        sha1.update(self._clip_max.hex().encode())
        sha1.update(self.cmap.name.encode())
        sha1.update(bytes(self._show_absolute))
        sha1.update(bytes(self._integrate))
        sha1.update(bytes(len(self.traces)))
        for tr in self.traces:
            sha1.update(tr.hash(unsafe=True).encode())

        return sha1

    def get_image(self, px_x, px_y):
        hash = self.get_state_hash()
        hash.update(bytes(px_x))
        hash.update(bytes(px_y))

        data_hash = hash.hexdigest()

        if self._data_cache and self._data_cache[-1] == data_hash:
            logger.debug('using cached image')
            return self._data_cache

        # Undersample in space
        traces_step = int(len(self.traces) // px_y) + 1
        traces = self.traces[::traces_step]
        img_rows = len(traces)

        # Undersample in time
        raw_deltat = min(tr.deltat for tr in traces)
        raw_nsamples = int(round((self.tmax - self.tmin) / raw_deltat)) + 1

        img_undersample = max(1, int(raw_nsamples // (2*px_x)))
        img_deltat = raw_deltat * img_undersample
        img_nsamples = int(round((self.tmax - self.tmin) / img_deltat)) + 1

        dtypes = set(tr.ydata.dtype for tr in traces)
        dtype = num.float64 if num.float64 in dtypes else num.float32

        data = num.zeros((img_rows, img_nsamples), dtype=dtype)
        empty_data = num.ones_like(data, dtype=bool)

        deltats = num.zeros(img_rows) if self._integrate else None

        logger.debug(
            'image render: using [::%d] traces at %d time undersampling'
            ' - rect (%d, %d), data: (%d, %d)',
            traces_step, img_undersample, px_y, px_x, *data.shape)

        for itr, tr in enumerate(traces):
            tr_data = tr.ydata

            if tr.deltat != img_deltat:
                time_vec = tr.tmin \
                    + num.arange((tr.tmax - tr.tmin) // img_deltat) \
                    * img_deltat
                tr_data = num.interp(time_vec, tr.get_xdata(), tr.ydata)

            ibeg = max(0, t2ind(self.tmin - tr.tmin, img_deltat, round))
            iend = min(
                tr_data.size,
                t2ind(self.tmax - tr.tmin, img_deltat, round))
            tr_tmin = tr.tmin + ibeg * img_deltat

            img_ibeg = max(0, t2ind(tr_tmin - self.tmin, img_deltat, round))
            img_iend = img_ibeg + (iend - ibeg)

            data[itr, img_ibeg:img_iend] = tr_data[ibeg:iend]
            empty_data[itr, img_ibeg:img_iend] = False

            if self._integrate:
                deltats[itr] = tr.deltat

        if self._integrate:
            data = num.cumsum(data, axis=1) * deltats[:, num.newaxis]
            # data -= data.mean(axis=1)[:, num.newaxis]

        if self._common_scale:
            data /= num.abs(data).max(axis=1)[:, num.newaxis]

        if self._show_absolute:
            data = num.abs(signal.hilbert(data, axis=1))
            vmax = data.max()
            vmin = data.min()
        else:
            vmax = num.abs(data).max()
            vmin = -vmax

        vrange = vmax - vmin

        self.norm.vmin = vmin + self._clip_min*vrange
        self.norm.vmax = vmax - (1. - self._clip_max)*vrange

        tstart = time.time()
        img_data = self.norm(data)
        t_norm = time.time() - tstart
        tstart = time.time()
        img_data = self.cmap(img_data, alpha=None, bytes=True)
        t_cmap = time.time() - tstart
        logger.debug('normalizing: %.3f cmap: %.3f', t_norm, t_cmap)

        # Mask out empty data
        img_data[empty_data, 3] = 0

        px_x, px_y = data.shape
        img = qg.QImage(
            img_data,
            px_y, px_x, qg.QImage.Format_RGBA8888)

        self._data_cache = (data, img, data_hash)
        return self._data_cache

    def draw_waterfall(self, p, rect=None):
        if not self.traces:
            raise AttributeError('No traces to paint.')

        rect = rect or p.window()
        trace_data, img, *_ = self.get_image(
            int(rect.width()), int(rect.height()))
        p.drawImage(rect, img)
