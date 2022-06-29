# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import
from . import (
    minmax, rms, stalta, geofon, ampspec, catalogs, download, cake_phase,
    seismosizer, map, polarization, spectrogram)

modules = [
    minmax, rms, download, stalta, geofon, ampspec, catalogs, map, cake_phase,
    seismosizer, polarization, spectrogram]


def __snufflings__():
    snufflings = []
    for mod in modules:
        snufflings.extend(mod.__snufflings__())

    for snuffling in snufflings:
        snuffling.setup()
        snuffling.set_name(snuffling.get_name() + ' (builtin)')

    return snufflings
