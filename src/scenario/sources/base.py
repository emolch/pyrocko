# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------
from __future__ import absolute_import, division, print_function

import os.path as op

from pyrocko import moment_tensor
from pyrocko.guts import Timestamp, Float, Int, Bool

from ..base import LocationGenerator
from ..error import ScenarioError

km = 1e3
guts_prefix = 'pf.scenario'


class SourceGenerator(LocationGenerator):

    nevents = Int.T(default=2)
    avoid_water = Bool.T(
        default=False,
        help='Avoid sources offshore under the ocean / lakes.')

    time_min = Timestamp.T(default=Timestamp.D('2017-01-01 00:00:00'))
    time_max = Timestamp.T(default=Timestamp.D('2017-01-03 00:00:00'))

    magnitude_min = Float.T(
        default=4.0,
        help='minimum moment magnitude')
    magnitude_max = Float.T(
        optional=True,
        help='if set, maximum moment magnitude for a uniform distribution. '
             'If set to ``None``, magnitudes are drawn using a '
             'Gutenberg-Richter distribution, see :gattr:`b_value`.')
    b_value = Float.T(
        optional=True,
        help='b-value for Gutenberg-Richter magnitude distribution. If unset, '
             'a value of 1 is assumed.')

    def __init__(self, *args, **kwargs):
        super(SourceGenerator, self).__init__(*args, **kwargs)
        if self.b_value is not None and self.magnitude_max is not None:
            raise ScenarioError(
                '%s: b_value and magnitude_max are mutually exclusive.'
                % self.__class__.__name__)

    def draw_magnitude(self, rstate):
        if self.b_value is None and self.magnitude_max is None:
            b_value = 1.0
        else:
            b_value = self.b_value

        if b_value is None:
            return rstate.uniform(self.magnitude_min, self.magnitude_max)
        else:
            return moment_tensor.rand_to_gutenberg_richter(
                rstate.rand(), b_value, magnitude_min=self.magnitude_min)

    def get_sources(self):
        sources = []
        for ievent in range(self.nevents):
            src = self.get_source(ievent)
            src.name = 'scenario_ev%03d' % (ievent + 1)
            sources.append(src)

        return sources

    def ensure_data(self, path):
        fn_sources = op.join(path, 'sources.yml')
        if not op.exists(fn_sources):
            with open(fn_sources, 'w') as f:
                for src in self.get_sources():
                    f.write(src.dump())

        fn_events = op.join(path, 'events.txt')
        if not op.exists(fn_events):
            with open(fn_events, 'w') as f:
                for isrc, src in enumerate(self.get_sources()):
                    f.write(src.pyrocko_event().dump())

    def add_map_artists(self, automap):
        pass
