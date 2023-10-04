# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Green's function store builders interfacing with the external modelling codes.

This subpackage contains the GF builders which are used by :py:app:`fomosto` to
interface with the various supported numerical forward modelling tools
(:doc:`/apps/fomosto/backends`). '''

import os
import re

op = os.path


modules = [m for m in os.listdir(op.dirname(__file__))
           if re.search(r'[^_(dummy)].py', m)]
AVAILABLE_BACKENDS = set([op.splitext(m)[0] for m in modules])
