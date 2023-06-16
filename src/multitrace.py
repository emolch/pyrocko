import numpy as num

from . import trace
from .guts import Object, Float, Timestamp, List
from .guts_array import Array
from .squirrel.model import CodesNSLCE


class MultiTrace(Object):
    codes = List.T(CodesNSLCE.T())
    data = Array.T(shape=(None, None))
    tmin = Timestamp.T(default=Timestamp.D('1970-01-01 00:00:00'))
    deltat = Float.T(default=1.0)

    def __init__(
            self,
            traces=None,
            codes=None,
            data=None,
            tmin=None,
            deltat=None):

        if traces is not None:

            if len(traces) == 0:
                data = num.zeros((0, 0))
            else:
                data = trace.get_traces_data_as_array(traces)
                deltat = traces[0].deltat
                tmin = traces[0].tmin
                codes = [tr.codes for tr in traces]

        self.ntraces, self.nsamples = data.shape

        if codes is None:
            codes = [CodesNSLCE()] * self.ntraces

        if len(codes) != self.ntraces:
            raise ValueError(
                'MultiTrace construction: mismatch between number of traces '
                'and number of codes given.')

        if deltat is None:
            deltat = self.T.deltat.default()

        if tmin is None:
            tmin = self.T.tmin.default()

        Object.__init__(self, codes=codes, data=data, tmin=tmin, deltat=deltat)

    def __len__(self):
        return self.ntraces

    def __getitem__(self, i):
        return self.get_trace(i)

    @property
    def tmax(self):
        return self.tmin + (self.nsamples - 1) * self.deltat

    def get_trace(self, i):
        network, station, location, channel, extra = self.codes[i]
        return trace.Trace(
            network=network,
            station=station,
            location=location,
            channel=channel,
            extra=extra,
            tmin=self.tmin,
            deltat=self.deltat,
            ydata=self.data[i, :])

    def snuffle(self):
        trace.snuffle(list(self))
