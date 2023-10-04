# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Observational target generators.
'''

from .base import *  # noqa
from .waveform import *  # noqa
from .insar import *  # noqa
from .gnss_campaign import *  # noqa
from ..station import *  # noqa

AVAILABLE_TARGETS =\
    [WaveformGenerator, InSARGenerator,  # noqa
     GNSSCampaignGenerator]  # noqa
