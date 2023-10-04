# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Reader for `Silixia iDAS
<https://silixa.com/technology/idas-intelligent-distributed-acoustic-sensor/>`_
HDF5 files.
'''

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterator

from pyrocko import trace

META_KEYS = {
    'measure_length': 'MeasureLength',
    'start_position': 'StartPosition',
    'spatial_resolution': 'SpatialResolution',
    'fibre_index': 'FibreIndex',
    'fibre_length_multiplier': 'FibreLengthMultiplier',
    # 'unit_calibration': 'Unit Calibration (nm)',
    'start_distance': 'StartDistance',
    'stop_distance': 'StopDistance',
    'normalization': 'Normalization',
    'decimation_filter': 'DecimationFilter',
    'gauge_length': 'GaugeLength',
    'norm_offset': 'NormOffset',
    'source_mode': 'SourceMode',
    'time_decimation': 'TimeDecimation',
    'zero_offset': 'ZeroOffset',
    'p_parameter': 'P',
    'p_coefficients': 'P_Coefficients',
    'idas_version': 'Version',
    'precice_sampling_freq': 'PreciseSamplingFrequency',
    'receiver_gain': 'ReceiverGain',
    # 'continuous_mode': 'Continuous Mode',
    'geo_lat': 'Latitude',
    'geo_lon': 'Longitude',
    'geo_elevation': 'Altitude',

    'unit': 'RawDataUnit'
}


def get_meta(h5file) -> dict[str, Any]:
    '''
    Get metadata from HDF5 file using the same fields as for the TDMS files.

    :param h5file:
         The file to extract metadata from.
    :type h5file:
        `HDF5 file object <https://docs.h5py.org/en/stable/high/file.html>`_

    :returns:
        Dictionary containing the metadata.
    :rtype:
        dict

    '''

    key_list = list(META_KEYS.keys())
    val_list = list(META_KEYS.values())

    meta = dict()
    # the following is based on the PRODML format
    for field in ['Acquisition',
                  'Acquisition/Custom/AdvancedUserSettings',
                  'Acquisition/Custom/SystemSettings',
                  'Acquisition/Custom/SystemInformation/GPS',
                  'Acquisition/Custom/SystemInformation/OSVersion',
                  'Acquisition/Custom/UserSettings',
                  'Acquisition/Raw[0]']:
        try:
            field_keys = h5file[field].attrs.keys()
            for val in val_list:
                if val not in field_keys:
                    continue
                meta[key_list[val_list.index(val)]] = h5file[field].attrs[val]
        except KeyError:
            raise KeyError(f"Key '{val}' not found in PRODML H5 file.")

    # some type conversions
    for val in (
            'p_coefficients',
            'receiver_gain',
            'source_mode',
            'unit',
            'idas_version'):
        meta[val] = meta[val].decode('utf-8')
    for val in ['decimation_filter', 'normalization']:
        meta[val] = bool(meta[val])
    for val in ['receiver_gain']:
        meta[val] = tuple([float(item) for item in meta[val].split(';')])

    return meta


def iload(filename, load_data=True) -> Iterator[trace.Trace]:

    # prevent hard dependency on h5py
    try:
        import h5py
    except ImportError as exc:
        raise ImportError(
            "Please install 'h5py' to proceed,"
            "e.g. by running 'pip install h5py'") from exc

    with h5py.File(filename, 'r') as file:
        # get the meta data
        meta = get_meta(file)
        # get the actual time series if load_data
        data = file['Acquisition/Raw[0]/RawData'][:] if load_data else None
        # get the sampling rate, starttime, number of samples in space and time
        deltat = 1.0 / file['Acquisition/Raw[0]'].attrs['OutputDataRate']
        tmin = datetime.fromisoformat(
            file['Acquisition/Raw[0]/RawData'].attrs['PartStartTime']
            .decode('ascii')).timestamp()
        nchannels = int(file['Acquisition/Raw[0]'].attrs['NumberOfLoci'])
        nsamples = int(file['Acquisition/Raw[0]/RawDataTime'].attrs['Count'])

    for icha in range(nchannels):
        station = '%05i' % icha
        meta_icha = meta.copy()
        meta_icha['channel'] = icha

        tr = trace.Trace(
            network='DA',
            station=station,
            ydata=None,
            deltat=deltat,
            tmin=tmin,
            tmax=tmin + (nsamples - 1) * deltat,
            meta=meta_icha)

        if data:
            tr.set_ydata(data[:, icha])

        yield tr


def detect(first512) -> bool:
    return first512.startswith(b'\x89HDF')
