from __future__ import annotations

from typing import Any, Generator

from pyrocko.trace import Trace

try:
    import simpledas
except ImportError:
    simpledas = None



def iload(filename: str, load_data: bool=True) -> Generator[Trace, Any, None]:
    if simpledas is None:
        raise ImportError(
            'simpledas is not available. '
            'Install ASN SimpleDAS to load ASN OptoDAS HDF5 data.')

    trace_data = simpledas.load_DAS_files(
        filename, samples=None if load_data else 0, integrate=False)
    if not load_data:
        time_data = simpledas.load_DAS_files(filename, chIndex=[0])
    else:
        time_data = trace_data


    deltat = (time_data.index[1] - time_data.index[0]).total_seconds()
    tmin = time_data.index[0].timestamp()
    nsamples = time_data.index.size

    for channel in trace_data:

        trace = Trace(
            network='OD',
            station='%05d' % channel,
            ydata=None,
            deltat=deltat,
            tmin=tmin,
            tmax=tmin + (nsamples - 1) * deltat,
        )
        if load_data:
            data = trace_data[channel].values
            trace.ydata = data
        yield trace


def detect(first512: bytes) -> bool:
    if simpledas is None:
        return False
    ret = first512.startswith(b'\x89HDF') and b'TREE' in first512
    return ret
