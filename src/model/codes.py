# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import re
import fnmatch
from collections import namedtuple

from pyrocko.guts import SObject

guts_prefix = 'squirrel'

g_codes_pool = {}


class CodesError(Exception):
    pass


class Codes(SObject):
    pass


def normalize_nslce(*args, **kwargs):
    if args and kwargs:
        raise ValueError('Either *args or **kwargs accepted, not both.')

    if len(args) == 1:
        if isinstance(args[0], str):
            args = tuple(args[0].split('.'))
        elif isinstance(args[0], tuple):
            args = args[0]
        else:
            raise ValueError('Invalid argument type: %s' % type(args[0]))

    nargs = len(args)
    if nargs == 5:
        t = args

    elif nargs == 4:
        t = args + ('',)

    elif nargs == 0:
        d = dict(
            network='',
            station='',
            location='',
            channel='',
            extra='')

        d.update(kwargs)
        t = tuple(kwargs.get(k, '') for k in (
            'network', 'station', 'location', 'channel', 'extra'))

    else:
        raise CodesError(
            'Does not match NSLC or NSLCE codes pattern: %s' % '.'.join(args))

    if '.'.join(t).count('.') != 4:
        raise CodesError(
            'Codes may not contain a ".": "%s", "%s", "%s", "%s", "%s"' % t)

    return t


CodesNSLCEBase = namedtuple(
    'CodesNSLCEBase', [
        'network', 'station', 'location', 'channel', 'extra'])


class CodesNSLCE(CodesNSLCEBase, Codes):
    '''
    Codes denominating a seismic channel (NSLC or NSLCE).

    FDSN/SEED style NET.STA.LOC.CHA is accepted or NET.STA.LOC.CHA.EXTRA, where
    the EXTRA part in the latter form can be used to identify a custom
    processing applied to a channel.
    '''

    __slots__ = ()
    __hash__ = CodesNSLCEBase.__hash__

    as_dict = CodesNSLCEBase._asdict

    def __new__(cls, *args, safe_str=None, **kwargs):
        nargs = len(args)
        if nargs == 1 and isinstance(args[0], CodesNSLCE):
            return args[0]
        elif nargs == 1 and isinstance(args[0], CodesNSL):
            t = (args[0].nsl) + ('*', '*')
        elif nargs == 1 and isinstance(args[0], CodesX):
            t = ('*', '*', '*', '*', '*')
        elif safe_str is not None:
            t = safe_str.split('.')
        else:
            t = normalize_nslce(*args, **kwargs)

        x = CodesNSLCEBase.__new__(cls, *t)
        return g_codes_pool.setdefault(x, x)

    def __init__(self, *args, **kwargs):
        Codes.__init__(self)

    def __str__(self):
        return '.'.join(self)

    def __eq__(self, other):
        if not isinstance(other, CodesNSLCE):
            other = CodesNSLCE(other)

        return CodesNSLCEBase.__eq__(self, other)

    def matches(self, pattern):
        if not isinstance(pattern, CodesNSLCE):
            pattern = CodesNSLCE(pattern)

        return match_codes(pattern, self)

    @property
    def safe_str(self):
        return '.'.join(self)

    @property
    def nslce(self):
        return self[:5]

    @property
    def nslc(self):
        return self[:4]

    @property
    def nsl(self):
        return self[:3]

    @property
    def ns(self):
        return self[:2]

    @property
    def codes_nsl(self):
        return CodesNSL(self)

    @property
    def codes_nsl_star(self):
        return CodesNSL(self.network, self.station, '*')

    def as_tuple(self):
        return tuple(self)

    def replace(self, **kwargs):
        x = CodesNSLCEBase._replace(self, **kwargs)
        return g_codes_pool.setdefault(x, x)


def normalize_nsl(*args, **kwargs):
    if args and kwargs:
        raise ValueError('Either *args or **kwargs accepted, not both.')

    if len(args) == 1:
        if isinstance(args[0], str):
            args = tuple(args[0].split('.'))
        elif isinstance(args[0], tuple):
            args = args[0]
        else:
            raise ValueError('Invalid argument type: %s' % type(args[0]))

    nargs = len(args)
    if nargs == 3:
        t = args

    elif nargs == 0:
        d = dict(
            network='',
            station='',
            location='')

        d.update(kwargs)
        t = tuple(kwargs.get(k, '') for k in (
            'network', 'station', 'location'))

    else:
        raise CodesError(
            'Does not match NSL codes pattern: %s' % '.'.join(args))

    if '.'.join(t).count('.') != 2:
        raise CodesError(
            'Codes may not contain a ".": "%s", "%s", "%s"' % t)

    return t


CodesNSLBase = namedtuple(
    'CodesNSLBase', [
        'network', 'station', 'location'])


class CodesNSL(CodesNSLBase, Codes):
    '''
    Codes denominating a seismic station (NSL).

    NET.STA.LOC is accepted, slightly different from SEED/StationXML, where
    LOC is part of the channel. By setting location='*' is possible to get
    compatible behaviour in most cases.
    '''

    __slots__ = ()
    __hash__ = CodesNSLBase.__hash__

    as_dict = CodesNSLBase._asdict

    def __new__(cls, *args, safe_str=None, **kwargs):
        nargs = len(args)
        if nargs == 1 and isinstance(args[0], CodesNSL):
            return args[0]
        elif nargs == 1 and isinstance(args[0], CodesNSLCE):
            t = args[0].nsl
        elif nargs == 1 and isinstance(args[0], CodesX):
            t = ('*', '*', '*')
        elif safe_str is not None:
            t = safe_str.split('.')
        else:
            t = normalize_nsl(*args, **kwargs)

        x = CodesNSLBase.__new__(cls, *t)
        return g_codes_pool.setdefault(x, x)

    def __init__(self, *args, **kwargs):
        Codes.__init__(self)

    def __str__(self):
        return '.'.join(self)

    def __eq__(self, other):
        if not isinstance(other, CodesNSL):
            other = CodesNSL(other)

        return CodesNSLBase.__eq__(self, other)

    def matches(self, pattern):
        if not isinstance(pattern, CodesNSL):
            pattern = CodesNSL(pattern)

        return match_codes(pattern, self)

    @property
    def safe_str(self):
        return '.'.join(self)

    @property
    def ns(self):
        return self[:2]

    @property
    def nsl(self):
        return self[:3]

    def as_tuple(self):
        return tuple(self)

    def replace(self, **kwargs):
        x = CodesNSLBase._replace(self, **kwargs)
        return g_codes_pool.setdefault(x, x)


CodesXBase = namedtuple(
    'CodesXBase', [
        'name'])


class CodesX(CodesXBase, Codes):
    '''
    General purpose codes for anything other than channels or stations.
    '''

    __slots__ = ()
    __hash__ = CodesXBase.__hash__
    __eq__ = CodesXBase.__eq__

    as_dict = CodesXBase._asdict

    def __new__(cls, name='', safe_str=None):
        if isinstance(name, CodesX):
            return name
        elif isinstance(name, (CodesNSLCE, CodesNSL)):
            name = '*'
        elif safe_str is not None:
            name = safe_str
        else:
            if '.' in name:
                raise CodesError('Code may not contain a ".": %s' % name)

        x = CodesXBase.__new__(cls, name)
        return g_codes_pool.setdefault(x, x)

    def __init__(self, *args, **kwargs):
        Codes.__init__(self)

    def __str__(self):
        return '.'.join(self)

    @property
    def safe_str(self):
        return '.'.join(self)

    @property
    def ns(self):
        return self[:2]

    def as_tuple(self):
        return tuple(self)

    def replace(self, **kwargs):
        x = CodesXBase._replace(self, **kwargs)
        return g_codes_pool.setdefault(x, x)


g_codes_patterns = {}


def _is_exact(pat):
    return not ('*' in pat or '?' in pat or ']' in pat or '[' in pat)


def classify_patterns(patterns):
    pats_exact = []
    pats_nonexact = []
    for pat in patterns:
        spat = pat.safe_str
        (pats_exact if _is_exact(spat) else pats_nonexact).append(spat)

    return pats_exact, pats_nonexact


def get_regex_pattern(spattern):
    if spattern not in g_codes_patterns:
        rpattern = re.compile(fnmatch.translate(spattern), re.I)
        g_codes_patterns[spattern] = rpattern

    return g_codes_patterns[spattern]


def match_codes(pattern, codes):
    spattern = pattern.safe_str
    scodes = codes.safe_str
    rpattern = get_regex_pattern(spattern)
    return bool(rpattern.match(scodes))


class CodesMatcher:
    def __init__(self, patterns):
        self._pats_exact, self._pats_nonexact = classify_patterns(patterns)
        self._pats_exact = set(self._pats_exact)
        self._pats_nonexact = [
            get_regex_pattern(spat) for spat in self._pats_nonexact]

    def match(self, codes):
        scodes = codes.safe_str
        if scodes in self._pats_exact:
            return True

        return any(rpat.match(scodes) for rpat in self._pats_nonexact)

    def filter(self, it):
        return filter(self.match, it)


def match_codes_any(patterns, codes):

    pats_exact, pats_nonexact = classify_patterns(patterns)

    if codes.safe_str in pats_exact:
        return True

    return any(match_codes(pattern, codes) for pattern in patterns)
