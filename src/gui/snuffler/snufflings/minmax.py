# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

from ..snuffling import Snuffling
from pyrocko import trace


class MinMaxSnuffling(Snuffling):

    '''
    Reports minimum, maximum, and peak-to-peak values of selected data.

    To use it, use the picker tool to mark a region or select existing regions
    and call this snuffling. The values are printed via standard output to the
    termimal.
    '''

    def setup(self):
        '''
        Customization of the snuffling.
        '''

        self.set_name('Minimum Maximum Peak-To-Peak')
        self.tinc = None

    def call(self):
        '''
        Main work routine of the snuffling.
        '''

        # to select a reasonable increment for the chopping, the smallest
        # sampling interval in the pile is looked at. this is only done,
        # the first time the snuffling is called.
        if self.tinc is None:
            self.tinc = self.get_pile().get_deltats()[0] * 10000.

        # the chopper yields lists of traces but for minmax() below, an
        # iterator yielding single traces is needed; using a converter:
        def iter_single_traces():
            for traces in self.chopper_selected_traces(
                    tinc=self.tinc, degap=False, fallback=True):

                for tr in traces:
                    yield tr

        # the function minmax() in the trace module can get minima and maxima
        # grouped by (network,station,location,channel):
        mima = trace.minmax(iter_single_traces())

        for nslc in sorted(mima.keys()):
            p2p = mima[nslc][1] - mima[nslc][0]
            print('%s.%s.%s.%s: %12.5g %12.5g %12.5g' % (
                nslc + mima[nslc] + (p2p,)))


def __snufflings__():
    '''
    Returns a list of snufflings to be exported by this module.
    '''

    return [MinMaxSnuffling()]
