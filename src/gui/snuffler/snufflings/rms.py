# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import

import time
import logging
from collections import defaultdict

import numpy as num

from pyrocko.gui.snuffler.snuffling import Snuffling, Param, Switch
from pyrocko.trace import Trace, NoData
from pyrocko import util

logger = logging.getLogger('pyrocko.gui.snuffling.rms')


class RootMeanSquareSnuffling(Snuffling):

    '''
    Create traces with blockwise root mean square values.
    '''

    def setup(self):
        '''
        Customization of the snuffling.
        '''

        self.set_name('RMS')

        self.add_parameter(Param(
            'Highpass [Hz]', 'highpass', None, 0.001, 1000.,
            low_is_none=True))

        self.add_parameter(Param(
            'Lowpass [Hz]', 'lowpass', None, 0.001, 1000.,
            high_is_none=True))

        self.add_parameter(Param(
            'Block Length [s]', 'block_length', 100., 0.1, 3600.))

        self.add_parameter(Switch(
            'Group channels', 'group_channels', True))

        self.add_parameter(Switch(
            'Log RMS', 'log', False))

        self.add_trigger(
            'Copy passband from Main', self.copy_passband)

        self.set_live_update(False)

    def copy_passband(self):
        viewer = self.get_viewer()
        self.set_parameter('lowpass', viewer.lowpass)
        self.set_parameter('highpass', viewer.highpass)

    def call(self):
        '''
        Main work routine of the snuffling.
        '''

        self.cleanup()

        tinc = self.block_length

        tpad = 0.0
        for freq in (self.highpass, self.lowpass):
            if freq is not None:
                tpad = max(tpad, 1./freq)

        targets = {}
        tlast = time.time()
        for batch in self.chopper_selected_traces(
                tinc=tinc,
                tpad=tpad,
                want_incomplete=False,
                style='batch',
                mode='visible',
                progress='Calculating RMS',
                responsive=True,
                fallback=True):

            tcur = batch.tmin + 0.5 * tinc

            if self.group_channels:
                def grouping(nslc):
                    return nslc[:3] + (nslc[3][:-1],)

            else:
                def grouping(nslc):
                    return nslc

            rms = defaultdict(list)
            for tr in batch.traces:

                # don't work traces produced by this (and other) snuffling
                if tr.meta and 'tabu' in tr.meta and tr.meta['tabu']:
                    continue

                if self.lowpass is not None:
                    tr.lowpass(4, self.lowpass, nyquist_exception=True)

                if self.highpass is not None:
                    tr.highpass(4, self.highpass, nyquist_exception=True)

                try:
                    tr.chop(batch.tmin, batch.tmax)
                    val = 0.0
                    if tr.ydata.size != 0:
                        y = tr.ydata.astype(float)
                        if num.any(num.isnan(y)):
                            logger.error(
                                'NaN value in trace %s (%s - %s)' % (
                                    '.'.join(tr.nslc_id),
                                    util.time_to_str(tr.tmin),
                                    util.time_to_str(tr.tmax)))

                        val = num.sqrt(num.sum(y**2)/tr.ydata.size)

                    rms[grouping(tr.nslc_id)].append(val)

                except NoData:
                    continue

            tnow = time.time()

            insert_now = False
            if tnow > tlast + 0.8:
                insert_now = True
                tlast = tnow

            to_add = []
            for key, values in rms.items():
                target = targets.get(key, None)

                if not target \
                        or abs((target.tmax + tinc) - tcur) > 0.01 * tinc \
                        or insert_now:

                    if target:
                        to_add.append(target)

                    target = targets[key] = Trace(
                        network=key[0],
                        station=key[1],
                        location=key[2],
                        channel=key[3] + '-RMS',
                        tmin=tcur,
                        deltat=tinc,
                        ydata=num.zeros(0, dtype=float),
                        meta={'tabu': True})

                value = num.atleast_1d(
                    num.sqrt(num.sum(num.array(values, dtype=float)**2)))

                if self.log and value != 0.0:
                    value = num.log(value)

                targets[key].append(value)

            if to_add:
                self.add_traces(to_add)

        # add the newly created traces to the viewer
        if targets.values():
            self.add_traces(list(targets.values()))


def __snufflings__():
    '''
    Returns a list of snufflings to be exported by this module.
    '''

    return [RootMeanSquareSnuffling()]
