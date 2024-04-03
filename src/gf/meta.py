# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Data model for Green's function store meta-data.
'''

import math
import re
import fnmatch
import logging

import numpy as num
from scipy.interpolate import interp1d

from pyrocko.guts import (Object, SObject, String, StringChoice,
                          StringPattern, Unicode, Float, Bool, Int, TBase,
                          List, ValidationError, Timestamp, Tuple, Dict)
from pyrocko.guts import dump, load  # noqa
from pyrocko.guts_array import literal, Array
from pyrocko.model import Location, gnss

from pyrocko import cake, orthodrome, spit, moment_tensor, trace

from .error import StoreError

try:
    new_str = unicode
except NameError:
    new_str = str

guts_prefix = 'pf'

d2r = math.pi / 180.
r2d = 1.0 / d2r
km = 1000.
vicinity_eps = 1e-5

logger = logging.getLogger('pyrocko.gf.meta')


def fmt_choices(cls):
    return 'choices: %s' % ', '.join(
        "``'%s'``" % choice for choice in cls.choices)


class InterpolationMethod(StringChoice):
    choices = ['nearest_neighbor', 'multilinear']


class SeismosizerTrace(Object):

    codes = Tuple.T(
        4, String.T(),
        default=('', 'STA', '', 'Z'),
        help='network, station, location and channel codes')

    data = Array.T(
        shape=(None,),
        dtype=num.float32,
        serialize_as='base64',
        serialize_dtype=num.dtype('<f4'),
        help='numpy array with data samples')

    deltat = Float.T(
        default=1.0,
        help='sampling interval [s]')

    tmin = Timestamp.T(
        default=Timestamp.D('1970-01-01 00:00:00'),
        help='time of first sample as a system timestamp [s]')

    def pyrocko_trace(self):
        c = self.codes
        return trace.Trace(c[0], c[1], c[2], c[3],
                           ydata=self.data,
                           deltat=self.deltat,
                           tmin=self.tmin)

    @classmethod
    def from_pyrocko_trace(cls, tr, **kwargs):
        d = dict(
            codes=tr.nslc_id,
            tmin=tr.tmin,
            deltat=tr.deltat,
            data=num.asarray(tr.get_ydata(), dtype=num.float32))
        d.update(kwargs)
        return cls(**d)


class SeismosizerResult(Object):
    n_records_stacked = Int.T(optional=True, default=1)
    t_stack = Float.T(optional=True, default=0.)


class Result(SeismosizerResult):
    trace = SeismosizerTrace.T(optional=True)
    n_shared_stacking = Int.T(optional=True, default=1)
    t_optimize = Float.T(optional=True, default=0.)


class StaticResult(SeismosizerResult):
    result = Dict.T(
        String.T(),
        Array.T(shape=(None,), dtype=float, serialize_as='base64'))


class GNSSCampaignResult(StaticResult):
    campaign = gnss.GNSSCampaign.T(
        optional=True)


class SatelliteResult(StaticResult):

    theta = Array.T(
        optional=True,
        shape=(None,), dtype=float, serialize_as='base64')

    phi = Array.T(
        optional=True,
        shape=(None,), dtype=float, serialize_as='base64')


class KiteSceneResult(SatelliteResult):

    shape = Tuple.T()

    def get_scene(self, component='displacement.los'):
        try:
            from kite import Scene
        except ImportError:
            raise ImportError('Kite not installed')

        def reshape(arr):
            return arr.reshape(self.shape)

        displacement = self.result[component]

        displacement, theta, phi = map(
            reshape, (displacement, self.theta, self.phi))

        sc = Scene(
            displacement=displacement,
            theta=theta, phi=phi,
            config=self.config)

        return sc


class ComponentSchemeDescription(Object):
    name = String.T()
    source_terms = List.T(String.T())
    ncomponents = Int.T()
    default_stored_quantity = String.T(optional=True)
    provided_components = List.T(String.T())


component_scheme_descriptions = [
    ComponentSchemeDescription(
        name='elastic2',
        source_terms=['m0'],
        ncomponents=2,
        default_stored_quantity='displacement',
        provided_components=[
            'n', 'e', 'd']),
    ComponentSchemeDescription(
        name='elastic8',
        source_terms=['mnn', 'mee', 'mdd', 'mne', 'mnd', 'med'],
        ncomponents=8,
        default_stored_quantity='displacement',
        provided_components=[
            'n', 'e', 'd']),
    ComponentSchemeDescription(
        name='elastic10',
        source_terms=['mnn', 'mee', 'mdd', 'mne', 'mnd', 'med'],
        ncomponents=10,
        default_stored_quantity='displacement',
        provided_components=[
            'n', 'e', 'd']),
    ComponentSchemeDescription(
        name='elastic10_fd',
        source_terms=['mnn', 'mee', 'mdd', 'mne', 'mnd', 'med'],
        ncomponents=30,
        default_stored_quantity='displacement',
        provided_components=[
            'n', 'e', 'd']),
    ComponentSchemeDescription(
        name='elastic18',
        source_terms=['mnn', 'mee', 'mdd', 'mne', 'mnd', 'med'],
        ncomponents=18,
        default_stored_quantity='displacement',
        provided_components=[
            'n', 'e', 'd']),
    ComponentSchemeDescription(
        name='elastic5',
        source_terms=['fn', 'fe', 'fd'],
        ncomponents=5,
        default_stored_quantity='displacement',
        provided_components=[
            'n', 'e', 'd']),
    ComponentSchemeDescription(
        name='rotational8',
        source_terms=['mnn', 'mee', 'mdd', 'mne', 'mnd', 'med'],
        ncomponents=8,
        default_stored_quantity='rotation_displacement',
        provided_components=[
            'n', 'e', 'd']),
    ComponentSchemeDescription(
        name='poroelastic10',
        source_terms=['pore_pressure'],
        ncomponents=10,
        default_stored_quantity=None,
        provided_components=[
            'displacement.n', 'displacement.e', 'displacement.d',
            'vertical_tilt.n', 'vertical_tilt.e',
            'pore_pressure',
            'darcy_velocity.n', 'darcy_velocity.e', 'darcy_velocity.d'])]


# new names?
# 'mt_to_displacement_1d'
# 'mt_to_displacement_1d_ff_only'
# 'mt_to_gravity_1d'
# 'mt_to_stress_1d'
# 'explosion_to_displacement_1d'
# 'sf_to_displacement_1d'
# 'mt_to_displacement_3d'
# 'mt_to_gravity_3d'
# 'mt_to_stress_3d'
# 'pore_pressure_to_displacement_1d'
# 'pore_pressure_to_vertical_tilt_1d'
# 'pore_pressure_to_pore_pressure_1d'
# 'pore_pressure_to_darcy_velocity_1d'


component_schemes = [c.name for c in component_scheme_descriptions]
component_scheme_to_description = dict(
    (c.name, c) for c in component_scheme_descriptions)


class ComponentScheme(StringChoice):
    '''
    Different Green's Function component schemes are available:

    ================= =========================================================
    Name              Description
    ================= =========================================================
    ``elastic10``     Elastodynamic for
                      :py:class:`~pyrocko.gf.meta.ConfigTypeA` and
                      :py:class:`~pyrocko.gf.meta.ConfigTypeB` stores, MT
                      sources only
    ``elastic8``      Elastodynamic for far-field only
                      :py:class:`~pyrocko.gf.meta.ConfigTypeA` and
                      :py:class:`~pyrocko.gf.meta.ConfigTypeB` stores,
                      MT sources only
    ``elastic2``      Elastodynamic for
                      :py:class:`~pyrocko.gf.meta.ConfigTypeA` and
                      :py:class:`~pyrocko.gf.meta.ConfigTypeB` stores, purely
                      isotropic sources only
    ``elastic5``      Elastodynamic for
                      :py:class:`~pyrocko.gf.meta.ConfigTypeA`
                      and :py:class:`~pyrocko.gf.meta.ConfigTypeB` stores, SF
                      sources only
    ``elastic18``     Elastodynamic for
                      :py:class:`~pyrocko.gf.meta.ConfigTypeC` stores, MT
                      sources only
    ``poroelastic10`` Poroelastic for :py:class:`~pyrocko.gf.meta.ConfigTypeA`
                      and :py:class:`~pyrocko.gf.meta.ConfigTypeB` stores
    ``rotational8``   Elastodynamic rotational motions for
                      :py:class:`~pyrocko.gf.meta.ConfigTypeA` and
                      :py:class:`~pyrocko.gf.meta.ConfigTypeB` stores, MT
                      sources only
    ================= =========================================================
    '''

    choices = component_schemes


class Earthmodel1D(Object):
    dummy_for = cake.LayeredModel
    dummy_for_description = 'pyrocko.cake.LayeredModel'

    class __T(TBase):
        def regularize_extra(self, val):
            if isinstance(val, str):
                val = cake.LayeredModel.from_scanlines(
                    cake.read_nd_model_str(val))

            return val

        def to_save(self, val):
            return literal(cake.write_nd_model_str(val))


class StringID(StringPattern):
    pattern = r'^[A-Za-z][A-Za-z0-9._]{0,64}$'


class ScopeType(StringChoice):
    choices = [
        'global',
        'regional',
        'local',
    ]


class WaveType(StringChoice):
    choices = [
        'full waveform',
        'bodywave',
        'P wave',
        'S wave',
        'surface wave',
    ]


class NearfieldTermsType(StringChoice):
    choices = [
        'complete',
        'incomplete',
        'missing',
    ]


class QuantityType(StringChoice):
    choices = [
        'displacement',
        'velocity',
        'acceleration',
        'rotation_displacement',
        'rotation_velocity',
        'rotation_acceleration',
        'pressure',
        'tilt',
        'pore_pressure',
        'darcy_velocity',
        'vertical_tilt']


class Reference(Object):
    id = StringID.T()
    type = String.T()
    title = Unicode.T()
    journal = Unicode.T(optional=True)
    volume = Unicode.T(optional=True)
    number = Unicode.T(optional=True)
    pages = Unicode.T(optional=True)
    year = String.T()
    note = Unicode.T(optional=True)
    issn = String.T(optional=True)
    doi = String.T(optional=True)
    url = String.T(optional=True)
    eprint = String.T(optional=True)
    authors = List.T(Unicode.T())
    publisher = Unicode.T(optional=True)
    keywords = Unicode.T(optional=True)
    note = Unicode.T(optional=True)
    abstract = Unicode.T(optional=True)

    @classmethod
    def from_bibtex(cls, filename=None, stream=None):

        from pybtex.database.input import bibtex

        parser = bibtex.Parser()

        if filename is not None:
            bib_data = parser.parse_file(filename)
        elif stream is not None:
            bib_data = parser.parse_stream(stream)

        references = []

        for id_, entry in bib_data.entries.items():
            d = {}
            avail = entry.fields.keys()
            for prop in cls.T.properties:
                if prop.name == 'authors' or prop.name not in avail:
                    continue

                d[prop.name] = entry.fields[prop.name]

            if 'author' in entry.persons:
                d['authors'] = []
                for person in entry.persons['author']:
                    d['authors'].append(new_str(person))

            c = Reference(id=id_, type=entry.type, **d)
            references.append(c)

        return references


_fpat = r'[+-]?(\d+(\.\d*)?|\.\d+)([eE][-+]?\d+)?'
_spat = StringID.pattern[1:-1]
_cake_pat = cake.PhaseDef.allowed_characters_pattern
_iaspei_pat = cake.PhaseDef.allowed_characters_pattern_classic

_ppat = r'(' \
    r'cake:' + _cake_pat + \
    r'|iaspei:' + _iaspei_pat + \
    r'|vel_surface:' + _fpat + \
    r'|vel:' + _fpat + \
    r'|stored:' + _spat + \
    r')'


timing_regex_old = re.compile(
    r'^((first|last)?\((' + _spat + r'(\|' + _spat + r')*)\)|(' +
    _spat + r'))?(' + _fpat + ')?$')


timing_regex = re.compile(
    r'^((first|last)?\{(' + _ppat + r'(\|' + _ppat + r')*)\}|(' +
    _ppat + r'))?(' + _fpat + '(S|%)?)?$')


class PhaseSelect(StringChoice):
    choices = ['', 'first', 'last']


class InvalidTimingSpecification(ValidationError):
    pass


class TimingAttributeError(Exception):
    pass


class Timing(SObject):
    '''
    Definition of a time instant relative to one or more named phase arrivals.

    Instances of this class can be used e.g. in cutting and tapering
    operations. They can hold an absolute time or an offset to a named phase
    arrival or group of such arrivals.

    Timings can be instantiated from a simple string defintion i.e. with
    ``Timing(str)`` where ``str`` is something like
    ``'SELECT{PHASE_DEFS}[+-]OFFSET[S|%]'`` where ``'SELECT'`` is ``'first'``,
    ``'last'`` or empty, ``'PHASE_DEFS'`` is a ``'|'``-separated list of phase
    definitions, and ``'OFFSET'`` is the time offset in seconds. If a ``'%'``
    is appended, it is interpreted as percent. If the an ``'S'`` is appended
    to ``'OFFSET'``, it is interpreted as a surface slowness in [s/km].

    Phase definitions can be specified in either of the following ways:

    * ``'stored:PHASE_ID'`` - retrieves value from stored travel time table
    * ``'cake:CAKE_PHASE_DEF'`` - evaluates first arrival of phase with cake
      (see :py:class:`pyrocko.cake.PhaseDef`)
    * ``'vel_surface:VELOCITY'`` - arrival according to surface distance /
      velocity [km/s]
    * ``'vel:VELOCITY'`` - arrival according to 3D-distance / velocity [km/s]

    **Examples:**

    * ``'100'`` : absolute time; 100 s
    * ``'{stored:P}-100'`` : 100 s before arrival of P phase according to
      stored travel time table named ``'P'``
    * ``'{stored:P}-5.1S'`` : 10% before arrival of P phase according to
      stored travel time table named ``'P'``
    * ``'{stored:P}-10%'`` : 10% before arrival of P phase according to
      stored travel time table named ``'P'``
    * ``'{stored:A|stored:B}'`` : time instant of phase arrival A, or B if A is
      undefined for a given geometry
    * ``'first{stored:A|stored:B}'`` : as above, but the earlier arrival of A
      and B is chosen, if both phases are defined for a given geometry
    * ``'last{stored:A|stored:B}'`` : as above but the later arrival is chosen
    * ``'first{stored:A|stored:B|stored:C}-100'`` : 100 s before first out of
      arrivals A, B, and C
    '''

    def __init__(self, s=None, **kwargs):

        if s is not None:
            offset_is = None
            s = re.sub(r'\s+', '', s)
            try:
                offset = float(s.rstrip('S'))

                if s.endswith('S'):
                    offset_is = 'slowness'

                phase_defs = []
                select = ''

            except ValueError:
                matched = False
                m = timing_regex.match(s)
                if m:
                    if m.group(3):
                        phase_defs = m.group(3).split('|')
                    elif m.group(19):
                        phase_defs = [m.group(19)]
                    else:
                        phase_defs = []

                    select = m.group(2) or ''

                    offset = 0.0
                    soff = m.group(27)
                    if soff:
                        offset = float(soff.rstrip('S%'))
                        if soff.endswith('S'):
                            offset_is = 'slowness'
                        elif soff.endswith('%'):
                            offset_is = 'percent'

                    matched = True

                else:
                    m = timing_regex_old.match(s)
                    if m:
                        if m.group(3):
                            phase_defs = m.group(3).split('|')
                        elif m.group(5):
                            phase_defs = [m.group(5)]
                        else:
                            phase_defs = []

                        select = m.group(2) or ''

                        offset = 0.0
                        if m.group(6):
                            offset = float(m.group(6))

                        phase_defs = [
                            'stored:' + phase_def for phase_def in phase_defs]

                        matched = True

                if not matched:
                    raise InvalidTimingSpecification(s)

            kwargs = dict(
                phase_defs=phase_defs,
                select=select,
                offset=offset,
                offset_is=offset_is)

        SObject.__init__(self, **kwargs)

    def __str__(self):
        s = []
        if self.phase_defs:
            sphases = '|'.join(self.phase_defs)
            # if len(self.phase_defs) > 1 or self.select:
            sphases = '{%s}' % sphases

            if self.select:
                sphases = self.select + sphases

            s.append(sphases)

        if self.offset != 0.0 or not self.phase_defs:
            s.append('%+g' % self.offset)
            if self.offset_is == 'slowness':
                s.append('S')
            elif self.offset_is == 'percent':
                s.append('%')

        return ''.join(s)

    def evaluate(self, get_phase, args, attributes=None):
        try:
            if self.offset_is == 'slowness' and self.offset != 0.0:
                phase_offset = get_phase(
                    'vel_surface:%g' % (1.0/self.offset))
                offset = phase_offset(args)
            else:
                offset = self.offset

            if self.phase_defs:
                extra_args = ()
                if attributes:
                    extra_args = (attributes,)

                phases = [
                    get_phase(phase_def, *extra_args)
                    for phase_def in self.phase_defs]

                results = [phase(args) for phase in phases]
                results = [
                    result if isinstance(result, tuple) else (result,)
                    for result in results]

                results = [
                    result for result in results
                    if result[0] is not None]

                if self.select == 'first':
                    results.sort(key=lambda result: result[0])
                elif self.select == 'last':
                    results.sort(key=lambda result: -result[0])

                if not results:
                    if attributes is not None:
                        return (None,) * (len(attributes) + 1)
                    else:
                        return None

                else:
                    t, values = results[0][0], results[0][1:]
                    if self.offset_is == 'percent':
                        t = t*(1.+offset/100.)
                    else:
                        t = t + offset

                    if attributes is not None:
                        return (t, ) + values
                    else:
                        return t

            else:
                if attributes is not None:
                    raise TimingAttributeError(
                        'Cannot get phase attributes from offset-only '
                        'definition.')
                return offset

        except spit.OutOfBounds:
            raise OutOfBounds(args)

    phase_defs = List.T(String.T())
    offset = Float.T(default=0.0)
    offset_is = String.T(optional=True)
    select = PhaseSelect.T(
        default='',
        help=("Can be either ``'%s'``, ``'%s'``, or ``'%s'``. " %
              tuple(PhaseSelect.choices)))


def mkdefs(s):
    defs = []
    for x in s.split(','):
        try:
            defs.append(float(x))
        except ValueError:
            if x.startswith('!'):
                defs.extend(cake.PhaseDef.classic(x[1:]))
            else:
                defs.append(cake.PhaseDef(x))

    return defs


class TPDef(Object):
    '''
    Maps an arrival phase identifier to an arrival phase definition.
    '''

    id = StringID.T(
        help='name used to identify the phase')
    definition = String.T(
        help='definition of the phase in either cake syntax as defined in '
             ':py:class:`pyrocko.cake.PhaseDef`, or, if prepended with an '
             '``!``, as a *classic phase name*, or, if it is a simple '
             'number, as a constant horizontal velocity.')

    @property
    def phases(self):
        return [x for x in mkdefs(self.definition)
                if isinstance(x, cake.PhaseDef)]

    @property
    def horizontal_velocities(self):
        return [x for x in mkdefs(self.definition) if isinstance(x, float)]


class OutOfBounds(Exception):
    def __init__(self, values=None, reason=None):
        Exception.__init__(self)
        self.values = values
        self.reason = reason
        self.context = None

    def __str__(self):
        scontext = ''
        if self.context:
            scontext = '\n%s' % str(self.context)

        if self.reason:
            scontext += '\n%s' % self.reason

        if self.values:
            return 'out of bounds: (%s)%s' % (
                ', '.join('%g' % x for x in self.values), scontext)
        else:
            return 'out of bounds%s' % scontext


class MultiLocation(Object):
    '''
    Unstructured grid of point coordinates.
    '''

    lats = Array.T(
        optional=True, shape=(None,), dtype=float,
        help='Latitudes of targets.')
    lons = Array.T(
        optional=True, shape=(None,), dtype=float,
        help='Longitude of targets.')
    north_shifts = Array.T(
        optional=True, shape=(None,), dtype=float,
        help='North shifts of targets.')
    east_shifts = Array.T(
        optional=True, shape=(None,), dtype=float,
        help='East shifts of targets.')
    elevation = Array.T(
        optional=True, shape=(None,), dtype=float,
        help='Elevations of targets.')

    def __init__(self, *args, **kwargs):
        self._coords5 = None
        Object.__init__(self, *args, **kwargs)

    @property
    def coords5(self):
        if self._coords5 is not None:
            return self._coords5
        props = [self.lats, self.lons, self.north_shifts, self.east_shifts,
                 self.elevation]
        sizes = [p.size for p in props if p is not None]
        if not sizes:
            raise AttributeError('Empty StaticTarget')
        if num.unique(sizes).size != 1:
            raise AttributeError('Inconsistent coordinate sizes.')

        self._coords5 = num.zeros((sizes[0], 5))
        for idx, p in enumerate(props):
            if p is not None:
                self._coords5[:, idx] = p.flatten()

        return self._coords5

    @property
    def ncoords(self):
        if self.coords5.shape[0] is None:
            return 0
        return int(self.coords5.shape[0])

    def get_latlon(self):
        '''
        Get all coordinates as lat/lon.

        :returns: Coordinates in Latitude, Longitude
        :rtype: :class:`numpy.ndarray`, (N, 2)
        '''
        latlons = num.empty((self.ncoords, 2))
        for i in range(self.ncoords):
            latlons[i, :] = orthodrome.ne_to_latlon(*self.coords5[i, :4])
        return latlons

    def get_corner_coords(self):
        '''
        Returns the corner coordinates of the multi-location object.

        :returns: In lat/lon: lower left, upper left, upper right, lower right
        :rtype: tuple
        '''
        latlon = self.get_latlon()
        ll = (latlon[:, 0].min(), latlon[:, 1].min())
        ur = (latlon[:, 0].max(), latlon[:, 1].max())
        return (ll, (ll[0], ur[1]), ur, (ur[0], ll[1]))


class Receiver(Location):
    codes = Tuple.T(
        3, String.T(),
        optional=True,
        help='network, station, and location codes')

    def pyrocko_station(self):
        from pyrocko import model

        lat, lon = self.effective_latlon

        return model.Station(
            network=self.codes[0],
            station=self.codes[1],
            location=self.codes[2],
            lat=lat,
            lon=lon,
            depth=self.depth)


def g(x, d):
    if x is None:
        return d
    else:
        return x


class UnavailableScheme(Exception):
    '''
    Raised when it is not possible to use the requested component scheme.
    '''
    pass


class InvalidNComponents(Exception):
    '''
    Raised when ``ncomponents`` is incompatible with ``component_scheme``.
    '''
    pass


class DiscretizedSource(Object):
    '''
    Base class for discretized sources.

    To compute synthetic seismograms, the parameterized source models (see of
    :py:class:`~pyrocko.gf.seismosizer.Source` derived classes) are first
    discretized into a number of point sources. These spacio-temporal point
    source distributions are represented by subclasses of the
    :py:class:`DiscretizedSource`. For elastodynamic problems there is the
    :py:class:`DiscretizedMTSource` for moment tensor point source
    distributions and the :py:class:`DiscretizedExplosionSource` for pure
    explosion/implosion type source distributions. The geometry calculations
    are implemented in the base class. How Green's function components have to
    be weighted and sumed is defined in the derived classes.

    Like in the :py:class:`pyrocko.model.location.Location` class, the
    positions of the point sources contained in the discretized source are
    defined by a common reference point (:py:attr:`lat`, :py:attr:`lon`) and
    cartesian offsets to this (:py:attr:`north_shifts`, :py:attr:`east_shifts`,
    :py:attr:`depths`). Alternatively latitude and longitude of each contained
    point source can be specified directly (:py:attr:`lats`, :py:attr:`lons`).
    '''

    times = Array.T(shape=(None,), dtype=float)
    lats = Array.T(shape=(None,), dtype=float, optional=True)
    lons = Array.T(shape=(None,), dtype=float, optional=True)
    lat = Float.T(optional=True)
    lon = Float.T(optional=True)
    north_shifts = Array.T(shape=(None,), dtype=num.float64, optional=True)
    east_shifts = Array.T(shape=(None,), dtype=num.float64, optional=True)
    depths = Array.T(shape=(None,), dtype=num.float64)
    dl = Float.T(optional=True)
    dw = Float.T(optional=True)
    nl = Float.T(optional=True)
    nw = Float.T(optional=True)

    @classmethod
    def check_scheme(cls, scheme):
        '''
        Check if given GF component scheme is supported by the class.

        Raises :py:class:`UnavailableScheme` if the given scheme is not
        supported by this discretized source class.
        '''

        if scheme not in cls.provided_schemes:
            raise UnavailableScheme(
                'source type "%s" does not support GF component scheme "%s"' %
                (cls.__name__, scheme))

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self._latlons = None

    def __setattr__(self, name, value):
        if name in ('lat', 'lon', 'north_shifts', 'east_shifts',
                    'lats', 'lons'):
            self.__dict__['_latlons'] = None

        Object.__setattr__(self, name, value)

    def get_source_terms(self, scheme):
        raise NotImplementedError()

    def make_weights(self, receiver, scheme):
        raise NotImplementedError()

    @property
    def effective_latlons(self):
        '''
        Property holding the offest-corrected lats and lons of all points.
        '''

        if self._latlons is None:
            if self.lats is not None and self.lons is not None:
                if (self.north_shifts is not None and
                        self.east_shifts is not None):
                    self._latlons = orthodrome.ne_to_latlon(
                        self.lats, self.lons,
                        self.north_shifts, self.east_shifts)
                else:
                    self._latlons = self.lats, self.lons
            else:
                lat = g(self.lat, 0.0)
                lon = g(self.lon, 0.0)
                self._latlons = orthodrome.ne_to_latlon(
                    lat, lon, self.north_shifts, self.east_shifts)

        return self._latlons

    @property
    def effective_north_shifts(self):
        if self.north_shifts is not None:
            return self.north_shifts
        else:
            return num.zeros(self.times.size)

    @property
    def effective_east_shifts(self):
        if self.east_shifts is not None:
            return self.east_shifts
        else:
            return num.zeros(self.times.size)

    def same_origin(self, receiver):
        '''
        Check if receiver has same reference point.
        '''

        return (g(self.lat, 0.0) == receiver.lat and
                g(self.lon, 0.0) == receiver.lon and
                self.lats is None and self.lons is None)

    def azibazis_to(self, receiver):
        '''
        Compute azimuths and backaziumuths to/from receiver, for all contained
        points.
        '''

        if self.same_origin(receiver):
            azis = r2d * num.arctan2(receiver.east_shift - self.east_shifts,
                                     receiver.north_shift - self.north_shifts)
            bazis = azis + 180.
        else:
            slats, slons = self.effective_latlons
            rlat, rlon = receiver.effective_latlon
            azis = orthodrome.azimuth_numpy(slats, slons, rlat, rlon)
            bazis = orthodrome.azimuth_numpy(rlat, rlon, slats, slons)

        return azis, bazis

    def distances_to(self, receiver):
        '''
        Compute distances to receiver for all contained points.
        '''
        if self.same_origin(receiver):
            return num.sqrt((self.north_shifts - receiver.north_shift)**2 +
                            (self.east_shifts - receiver.east_shift)**2)

        else:
            slats, slons = self.effective_latlons
            rlat, rlon = receiver.effective_latlon
            return orthodrome.distance_accurate50m_numpy(slats, slons,
                                                         rlat, rlon)

    def element_coords(self, i):
        if self.lats is not None and self.lons is not None:
            lat = float(self.lats[i])
            lon = float(self.lons[i])
        else:
            lat = self.lat
            lon = self.lon

        if self.north_shifts is not None and self.east_shifts is not None:
            north_shift = float(self.north_shifts[i])
            east_shift = float(self.east_shifts[i])

        else:
            north_shift = east_shift = 0.0

        return lat, lon, north_shift, east_shift

    def coords5(self):
        xs = num.zeros((self.nelements, 5))

        if self.lats is not None and self.lons is not None:
            xs[:, 0] = self.lats
            xs[:, 1] = self.lons
        else:
            xs[:, 0] = g(self.lat, 0.0)
            xs[:, 1] = g(self.lon, 0.0)

        if self.north_shifts is not None and self.east_shifts is not None:
            xs[:, 2] = self.north_shifts
            xs[:, 3] = self.east_shifts

        xs[:, 4] = self.depths

        return xs

    @property
    def nelements(self):
        return self.times.size

    @classmethod
    def combine(cls, sources, **kwargs):
        '''
        Combine several discretized source models.

        Concatenenates all point sources in the given discretized ``sources``.
        Care must be taken when using this function that the external amplitude
        factors and reference times of the parameterized (undiscretized)
        sources match or are accounted for.
        '''

        first = sources[0]

        if not all(type(s) is type(first) for s in sources):
            raise Exception('DiscretizedSource.combine must be called with '
                            'sources of same type.')

        latlons = []
        for s in sources:
            latlons.append(s.effective_latlons)

        lats, lons = num.hstack(latlons)

        if all((s.lats is None and s.lons is None) for s in sources):
            rlats = num.array([s.lat for s in sources], dtype=float)
            rlons = num.array([s.lon for s in sources], dtype=float)
            same_ref = num.all(
                rlats == rlats[0]) and num.all(rlons == rlons[0])
        else:
            same_ref = False

        cat = num.concatenate
        times = cat([s.times for s in sources])
        depths = cat([s.depths for s in sources])

        if same_ref:
            lat = first.lat
            lon = first.lon
            north_shifts = cat([s.effective_north_shifts for s in sources])
            east_shifts = cat([s.effective_east_shifts for s in sources])
            lats = None
            lons = None
        else:
            lat = None
            lon = None
            north_shifts = None
            east_shifts = None

        return cls(
            times=times, lat=lat, lon=lon, lats=lats, lons=lons,
            north_shifts=north_shifts, east_shifts=east_shifts,
            depths=depths, **kwargs)

    def centroid_position(self):
        moments = self.moments()
        norm = num.sum(moments)
        if norm != 0.0:
            w = moments / num.sum(moments)
        else:
            w = num.ones(moments.size)

        if self.lats is not None and self.lons is not None:
            lats, lons = self.effective_latlons
            rlat, rlon = num.mean(lats), num.mean(lons)
            n, e = orthodrome.latlon_to_ne_numpy(rlat, rlon, lats, lons)
        else:
            rlat, rlon = g(self.lat, 0.0), g(self.lon, 0.0)
            n, e = self.north_shifts, self.east_shifts

        cn = num.sum(n*w)
        ce = num.sum(e*w)
        clat, clon = orthodrome.ne_to_latlon(rlat, rlon, cn, ce)

        if self.lats is not None and self.lons is not None:
            lat = clat
            lon = clon
            north_shift = 0.
            east_shift = 0.
        else:
            lat = g(self.lat, 0.0)
            lon = g(self.lon, 0.0)
            north_shift = cn
            east_shift = ce

        depth = num.sum(self.depths*w)
        time = num.sum(self.times*w)
        return tuple(float(x) for x in
                     (time, lat, lon, north_shift, east_shift, depth))


class DiscretizedExplosionSource(DiscretizedSource):
    m0s = Array.T(shape=(None,), dtype=float)

    provided_schemes = (
        'elastic2',
        'elastic8',
        'elastic10',
        'rotational8',
    )

    def get_source_terms(self, scheme):
        self.check_scheme(scheme)

        if scheme == 'elastic2':
            return self.m0s[:, num.newaxis].copy()

        elif scheme in ('elastic8', 'elastic10', 'rotational8'):
            m6s = num.zeros((self.m0s.size, 6))
            m6s[:, 0:3] = self.m0s[:, num.newaxis]
            return m6s
        else:
            assert False

    def make_weights(self, receiver, scheme):
        self.check_scheme(scheme)

        azis, bazis = self.azibazis_to(receiver)

        sb = num.sin(bazis*d2r-num.pi)
        cb = num.cos(bazis*d2r-num.pi)

        m0s = self.m0s
        n = azis.size

        cat = num.concatenate
        rep = num.repeat

        if scheme == 'elastic2':
            w_n = cb*m0s
            g_n = filledi(0, n)
            w_e = sb*m0s
            g_e = filledi(0, n)
            w_d = m0s
            g_d = filledi(1, n)

        elif scheme == 'elastic8':
            w_n = cat((cb*m0s, cb*m0s))
            g_n = rep((0, 2), n)
            w_e = cat((sb*m0s, sb*m0s))
            g_e = rep((0, 2), n)
            w_d = cat((m0s, m0s))
            g_d = rep((5, 7), n)

        elif scheme == 'elastic10':
            w_n = cat((cb*m0s, cb*m0s, cb*m0s))
            g_n = rep((0, 2, 8), n)
            w_e = cat((sb*m0s, sb*m0s, sb*m0s))
            g_e = rep((0, 2, 8), n)
            w_d = cat((m0s, m0s, m0s))
            g_d = rep((5, 7, 9), n)

        elif scheme == 'rotational8':
            w_n = cat((sb*m0s, sb*m0s, sb*m0s))
            g_n = rep((2, 4, 7), n)
            w_e = cat((sb*m0s, sb*m0s, sb*m0s))
            g_e = rep((2, 4, 7), n)
            w_d = num.zeros(0)
            g_d = num.zeros(0, dtype=int)
            logger.warning('untested code executed, check for sign errors')

        else:
            assert False

        return (
            ('displacement.n', w_n, g_n),
            ('displacement.e', w_e, g_e),
            ('displacement.d', w_d, g_d),
        )

    def split(self):
        from pyrocko.gf.seismosizer import ExplosionSource
        sources = []
        for i in range(self.nelements):
            lat, lon, north_shift, east_shift = self.element_coords(i)
            sources.append(ExplosionSource(
                time=float(self.times[i]),
                lat=lat,
                lon=lon,
                north_shift=north_shift,
                east_shift=east_shift,
                depth=float(self.depths[i]),
                moment=float(self.m0s[i])))

        return sources

    def moments(self):
        return self.m0s

    def centroid(self):
        from pyrocko.gf.seismosizer import ExplosionSource
        time, lat, lon, north_shift, east_shift, depth = \
            self.centroid_position()

        return ExplosionSource(
            time=time,
            lat=lat,
            lon=lon,
            north_shift=north_shift,
            east_shift=east_shift,
            depth=depth,
            moment=float(num.sum(self.m0s)))

    @classmethod
    def combine(cls, sources, **kwargs):
        '''
        Combine several discretized source models.

        Concatenenates all point sources in the given discretized ``sources``.
        Care must be taken when using this function that the external amplitude
        factors and reference times of the parameterized (undiscretized)
        sources match or are accounted for.
        '''

        if 'm0s' not in kwargs:
            kwargs['m0s'] = num.concatenate([s.m0s for s in sources])

        return super(DiscretizedExplosionSource, cls).combine(sources,
                                                              **kwargs)


class DiscretizedSFSource(DiscretizedSource):
    forces = Array.T(shape=(None, 3), dtype=float)

    provided_schemes = (
        'elastic5',
    )

    def get_source_terms(self, scheme):
        self.check_scheme(scheme)

        return self.forces

    def make_weights(self, receiver, scheme):
        self.check_scheme(scheme)

        azis, bazis = self.azibazis_to(receiver)

        sa = num.sin(azis*d2r)
        ca = num.cos(azis*d2r)
        sb = num.sin(bazis*d2r-num.pi)
        cb = num.cos(bazis*d2r-num.pi)

        forces = self.forces
        fn = forces[:, 0]
        fe = forces[:, 1]
        fd = forces[:, 2]

        f0 = fd
        f1 = ca * fn + sa * fe
        f2 = ca * fe - sa * fn

        n = azis.size

        if scheme == 'elastic5':
            ioff = 0

        cat = num.concatenate
        rep = num.repeat

        w_n = cat((cb*f0, cb*f1, -sb*f2))
        g_n = ioff + rep((0, 1, 2), n)
        w_e = cat((sb*f0, sb*f1, cb*f2))
        g_e = ioff + rep((0, 1, 2), n)
        w_d = cat((f0, f1))
        g_d = ioff + rep((3, 4), n)

        return (
            ('displacement.n', w_n, g_n),
            ('displacement.e', w_e, g_e),
            ('displacement.d', w_d, g_d),
        )

    @classmethod
    def combine(cls, sources, **kwargs):
        '''
        Combine several discretized source models.

        Concatenenates all point sources in the given discretized ``sources``.
        Care must be taken when using this function that the external amplitude
        factors and reference times of the parameterized (undiscretized)
        sources match or are accounted for.
        '''

        if 'forces' not in kwargs:
            kwargs['forces'] = num.vstack([s.forces for s in sources])

        return super(DiscretizedSFSource, cls).combine(sources, **kwargs)

    def moments(self):
        return num.sum(self.forces**2, axis=1)

    def centroid(self):
        from pyrocko.gf.seismosizer import SFSource
        time, lat, lon, north_shift, east_shift, depth = \
            self.centroid_position()

        fn, fe, fd = map(float, num.sum(self.forces, axis=0))
        return SFSource(
            time=time,
            lat=lat,
            lon=lon,
            north_shift=north_shift,
            east_shift=east_shift,
            depth=depth,
            fn=fn,
            fe=fe,
            fd=fd)


class DiscretizedMTSource(DiscretizedSource):
    m6s = Array.T(
        shape=(None, 6), dtype=float,
        help='rows with (m_nn, m_ee, m_dd, m_ne, m_nd, m_ed)')

    provided_schemes = (
        'elastic8',
        'elastic10',
        'elastic18',
        'rotational8',
    )

    def get_source_terms(self, scheme):
        self.check_scheme(scheme)
        return self.m6s

    def make_weights(self, receiver, scheme):
        self.check_scheme(scheme)

        m6s = self.m6s
        n = m6s.shape[0]
        rep = num.repeat

        if scheme == 'elastic18':
            w_n = m6s.flatten()
            g_n = num.tile(num.arange(0, 6), n)
            w_e = m6s.flatten()
            g_e = num.tile(num.arange(6, 12), n)
            w_d = m6s.flatten()
            g_d = num.tile(num.arange(12, 18), n)

        else:
            azis, bazis = self.azibazis_to(receiver)

            sa = num.sin(azis*d2r)
            ca = num.cos(azis*d2r)
            s2a = num.sin(2.*azis*d2r)
            c2a = num.cos(2.*azis*d2r)
            sb = num.sin(bazis*d2r-num.pi)
            cb = num.cos(bazis*d2r-num.pi)

            f0 = m6s[:, 0]*ca**2 + m6s[:, 1]*sa**2 + m6s[:, 3]*s2a
            f1 = m6s[:, 4]*ca + m6s[:, 5]*sa
            f2 = m6s[:, 2]
            f3 = 0.5*(m6s[:, 1]-m6s[:, 0])*s2a + m6s[:, 3]*c2a
            f4 = m6s[:, 5]*ca - m6s[:, 4]*sa
            f5 = m6s[:, 0]*sa**2 + m6s[:, 1]*ca**2 - m6s[:, 3]*s2a

            cat = num.concatenate

            if scheme == 'elastic8':
                w_n = cat((cb*f0, cb*f1, cb*f2, -sb*f3, -sb*f4))
                g_n = rep((0, 1, 2, 3, 4), n)
                w_e = cat((sb*f0, sb*f1, sb*f2, cb*f3, cb*f4))
                g_e = rep((0, 1, 2, 3, 4), n)
                w_d = cat((f0, f1, f2))
                g_d = rep((5, 6, 7), n)

            elif scheme == 'elastic10':
                w_n = cat((cb*f0, cb*f1, cb*f2, cb*f5, -sb*f3, -sb*f4))
                g_n = rep((0, 1, 2, 8, 3, 4), n)
                w_e = cat((sb*f0, sb*f1, sb*f2, sb*f5, cb*f3, cb*f4))
                g_e = rep((0, 1, 2, 8, 3, 4), n)
                w_d = cat((f0, f1, f2, f5))
                g_d = rep((5, 6, 7, 9), n)

            elif scheme == 'rotational18':
                w_n = cat((cb*f3, cb*f4, -sb*f0, -sb*f1, -sb*f2, -sb*f5))
                g_n = rep((0, 1, 2, 3, 4, 7), n)
                w_n = cat((sb*f3, sb*f4, cb*f0, cb*f1, cb*f2, cb*f5))
                g_e = rep((0, 1, 2, 3, 4, 7), n)
                w_d = cat((f3, f4))
                g_d = rep((5, 6), n)

            else:
                assert False

        return (
            ('displacement.n', w_n, g_n),
            ('displacement.e', w_e, g_e),
            ('displacement.d', w_d, g_d),
        )

    def split(self):
        from pyrocko.gf.seismosizer import MTSource
        sources = []
        for i in range(self.nelements):
            lat, lon, north_shift, east_shift = self.element_coords(i)
            sources.append(MTSource(
                time=float(self.times[i]),
                lat=lat,
                lon=lon,
                north_shift=north_shift,
                east_shift=east_shift,
                depth=float(self.depths[i]),
                m6=self.m6s[i]))

        return sources

    def moments(self):
        moments = num.array(
            [num.linalg.eigvalsh(moment_tensor.symmat6(*m6))
             for m6 in self.m6s])
        return num.linalg.norm(moments, axis=1) / num.sqrt(2.)

    def get_moment_rate(self, deltat=None):
        moments = self.moments()
        times = self.times
        times -= times.min()

        t_max = times.max()
        mom_times = num.arange(0, t_max + 2 * deltat, deltat) - deltat
        mom_times[mom_times > t_max] = t_max

        # Right open histrogram bins
        mom, _ = num.histogram(
            times,
            bins=mom_times,
            weights=moments)

        deltat = num.diff(mom_times)
        mom_rate = mom / deltat

        return mom_rate, mom_times[1:]

    def centroid(self):
        from pyrocko.gf.seismosizer import MTSource
        time, lat, lon, north_shift, east_shift, depth = \
            self.centroid_position()

        return MTSource(
            time=time,
            lat=lat,
            lon=lon,
            north_shift=north_shift,
            east_shift=east_shift,
            depth=depth,
            m6=num.sum(self.m6s, axis=0))

    @classmethod
    def combine(cls, sources, **kwargs):
        '''
        Combine several discretized source models.

        Concatenenates all point sources in the given discretized ``sources``.
        Care must be taken when using this function that the external amplitude
        factors and reference times of the parameterized (undiscretized)
        sources match or are accounted for.
        '''

        if 'm6s' not in kwargs:
            kwargs['m6s'] = num.vstack([s.m6s for s in sources])

        return super(DiscretizedMTSource, cls).combine(sources, **kwargs)


class DiscretizedPorePressureSource(DiscretizedSource):
    pp = Array.T(shape=(None,), dtype=float)

    provided_schemes = (
        'poroelastic10',
    )

    def get_source_terms(self, scheme):
        self.check_scheme(scheme)
        return self.pp[:, num.newaxis].copy()

    def make_weights(self, receiver, scheme):
        self.check_scheme(scheme)

        azis, bazis = self.azibazis_to(receiver)

        sb = num.sin(bazis*d2r-num.pi)
        cb = num.cos(bazis*d2r-num.pi)

        pp = self.pp
        n = bazis.size

        w_un = cb*pp
        g_un = filledi(1, n)
        w_ue = sb*pp
        g_ue = filledi(1, n)
        w_ud = pp
        g_ud = filledi(0, n)

        w_tn = cb*pp
        g_tn = filledi(6, n)
        w_te = sb*pp
        g_te = filledi(6, n)

        w_pp = pp
        g_pp = filledi(7, n)

        w_dvn = cb*pp
        g_dvn = filledi(9, n)
        w_dve = sb*pp
        g_dve = filledi(9, n)
        w_dvd = pp
        g_dvd = filledi(8, n)

        return (
            ('displacement.n', w_un, g_un),
            ('displacement.e', w_ue, g_ue),
            ('displacement.d', w_ud, g_ud),
            ('vertical_tilt.n', w_tn, g_tn),
            ('vertical_tilt.e', w_te, g_te),
            ('pore_pressure', w_pp, g_pp),
            ('darcy_velocity.n', w_dvn, g_dvn),
            ('darcy_velocity.e', w_dve, g_dve),
            ('darcy_velocity.d', w_dvd, g_dvd),
        )

    def moments(self):
        return self.pp

    def centroid(self):
        from pyrocko.gf.seismosizer import PorePressurePointSource
        time, lat, lon, north_shift, east_shift, depth = \
            self.centroid_position()

        return PorePressurePointSource(
            time=time,
            lat=lat,
            lon=lon,
            north_shift=north_shift,
            east_shift=east_shift,
            depth=depth,
            pp=float(num.sum(self.pp)))

    @classmethod
    def combine(cls, sources, **kwargs):
        '''
        Combine several discretized source models.

        Concatenenates all point sources in the given discretized ``sources``.
        Care must be taken when using this function that the external amplitude
        factors and reference times of the parameterized (undiscretized)
        sources match or are accounted for.
        '''

        if 'pp' not in kwargs:
            kwargs['pp'] = num.concatenate([s.pp for s in sources])

        return super(DiscretizedPorePressureSource, cls).combine(sources,
                                                                 **kwargs)


class Region(Object):
    name = String.T(optional=True)


class RectangularRegion(Region):
    lat_min = Float.T()
    lat_max = Float.T()
    lon_min = Float.T()
    lon_max = Float.T()


class CircularRegion(Region):
    lat = Float.T()
    lon = Float.T()
    radius = Float.T()


class Config(Object):
    '''
    Green's function store meta information.

    Currently implemented :py:class:`~pyrocko.gf.store.Store`
    configuration types are:

    * :py:class:`~pyrocko.gf.meta.ConfigTypeA` - cylindrical or
      spherical symmetry, 1D earth model, single receiver depth

      * Problem is invariant to horizontal translations and rotations around
        vertical axis.
      * All receivers must be at the same depth (e.g. at the surface)
      * High level index variables: ``(source_depth, receiver_distance,
        component)``

    * :py:class:`~pyrocko.gf.meta.ConfigTypeB` - cylindrical or
      spherical symmetry, 1D earth model, variable receiver depth

      * Symmetries like in Type A but has additional index for receiver depth
      * High level index variables: ``(source_depth, receiver_distance,
        receiver_depth, component)``

    * :py:class:`~pyrocko.gf.meta.ConfigTypeC` - no symmetrical
      constraints but fixed receiver positions

      * Cartesian source volume around a reference point
      * High level index variables: ``(ireceiver, source_depth,
        source_east_shift, source_north_shift, component)``
    '''

    id = StringID.T(
        help='Name of the store. May consist of upper and lower-case letters, '
             'digits, dots and underscores. The name must start with a '
             'letter.')

    derived_from_id = StringID.T(
        optional=True,
        help='Name of the original store, if this store has been derived from '
             'another one (e.g. extracted subset).')

    version = String.T(
        default='1.0',
        optional=True,
        help='User-defined version string. Use <major>.<minor> format.')

    modelling_code_id = StringID.T(
        optional=True,
        help='Identifier of the backend used to compute the store.')

    author = Unicode.T(
        optional=True,
        help='Comma-separated list of author names.')

    author_email = String.T(
        optional=True,
        help="Author's contact email address.")

    created_time = Timestamp.T(
        optional=True,
        help='Time of creation of the store.')

    regions = List.T(
        Region.T(),
        help='Geographical regions for which the store is representative.')

    scope_type = ScopeType.T(
        optional=True,
        help='Distance range scope of the store '
             '(%s).' % fmt_choices(ScopeType))

    waveform_type = WaveType.T(
        optional=True,
        help='Wave type stored (%s).' % fmt_choices(WaveType))

    nearfield_terms = NearfieldTermsType.T(
        optional=True,
        help='Information about the inclusion of near-field terms in the '
             'modelling (%s).' % fmt_choices(NearfieldTermsType))

    description = String.T(
        optional=True,
        help='Free form textual description of the GF store.')

    references = List.T(
        Reference.T(),
        help='Reference list to cite the modelling code, earth model or '
             'related work.')

    earthmodel_1d = Earthmodel1D.T(
        optional=True,
        help='Layered earth model in ND (named discontinuity) format.')

    earthmodel_receiver_1d = Earthmodel1D.T(
        optional=True,
        help='Receiver-side layered earth model in ND format.')

    can_interpolate_source = Bool.T(
        optional=True,
        help='Hint to indicate if the spatial sampling of the store is dense '
             'enough for multi-linear interpolation at the source.')

    can_interpolate_receiver = Bool.T(
        optional=True,
        help='Hint to indicate if the spatial sampling of the store is dense '
             'enough for multi-linear interpolation at the receiver.')

    frequency_min = Float.T(
        optional=True,
        help='Hint to indicate the lower bound of valid frequencies [Hz].')

    frequency_max = Float.T(
        optional=True,
        help='Hint to indicate the upper bound of valid frequencies [Hz].')

    sample_rate = Float.T(
        optional=True,
        help='Sample rate of the GF store [Hz].')

    factor = Float.T(
        default=1.0,
        help='Gain value, factored out of the stored GF samples. '
             '(may not work properly, keep at 1.0).',
        optional=True)

    component_scheme = ComponentScheme.T(
        default='elastic10',
        help='GF component scheme (%s).' % fmt_choices(ComponentScheme))

    stored_quantity = QuantityType.T(
        optional=True,
        help='Physical quantity of stored values (%s). If not given, a '
             'default is used based on the GF component scheme. The default '
             'for the ``"elastic*"`` family of component schemes is '
             '``"displacement"``.' % fmt_choices(QuantityType))

    tabulated_phases = List.T(
        TPDef.T(),
        help='Mapping of phase names to phase definitions, for which travel '
             'time tables are available in the GF store.')

    ncomponents = Int.T(
        optional=True,
        help='Number of GF components. Use :gattr:`component_scheme` instead.')

    uuid = String.T(
        optional=True,
        help='Heuristic hash value which can be used to uniquely identify the '
             'GF store for practical purposes.')

    reference = String.T(
        optional=True,
        help="Store reference name composed of the store's :gattr:`id` and "
             'the first six letters of its :gattr:`uuid`.')

    def __init__(self, **kwargs):
        self._do_auto_updates = False
        Object.__init__(self, **kwargs)
        self._index_function = None
        self._indices_function = None
        self._vicinity_function = None
        self.validate(regularize=True, depth=1)
        self._do_auto_updates = True
        self.update()

    def check_ncomponents(self):
        ncomponents = component_scheme_to_description[
            self.component_scheme].ncomponents

        if self.ncomponents is None:
            self.ncomponents = ncomponents
        elif ncomponents != self.ncomponents:
            raise InvalidNComponents(
                'ncomponents=%i incompatible with component_scheme="%s"' % (
                    self.ncomponents, self.component_scheme))

    def __setattr__(self, name, value):
        Object.__setattr__(self, name, value)
        try:
            self.T.get_property(name)
            if self._do_auto_updates:
                self.update()

        except ValueError:
            pass

    def update(self):
        self.check_ncomponents()
        self._update()
        self._make_index_functions()

    def irecord(self, *args):
        return self._index_function(*args)

    def irecords(self, *args):
        return self._indices_function(*args)

    def vicinity(self, *args):
        return self._vicinity_function(*args)

    def vicinities(self, *args):
        return self._vicinities_function(*args)

    def grid_interpolation_coefficients(self, *args):
        return self._grid_interpolation_coefficients(*args)

    def nodes(self, level=None, minlevel=None):
        return nodes(self.coords[minlevel:level])

    def iter_nodes(self, level=None, minlevel=None):
        return nditer_outer(self.coords[minlevel:level])

    def iter_extraction(self, gdef, level=None):
        i = 0
        arrs = []
        ntotal = 1
        for mi, ma, inc in zip(self.mins, self.effective_maxs, self.deltas):
            if gdef and len(gdef) > i:
                sssn = gdef[i]
            else:
                sssn = (None,)*4

            arr = num.linspace(*start_stop_num(*(sssn + (mi, ma, inc))))
            ntotal *= len(arr)

            arrs.append(arr)
            i += 1

        arrs.append(self.coords[-1])
        return nditer_outer(arrs[:level])

    def make_sum_params(self, source, receiver, implementation='c',
                        nthreads=0):
        assert implementation in ['c', 'python']

        out = []
        delays = source.times
        for comp, weights, icomponents in source.make_weights(
                receiver,
                self.component_scheme):

            weights *= self.factor

            args = self.make_indexing_args(source, receiver, icomponents)
            delays_expanded = num.tile(delays, icomponents.size//delays.size)
            out.append((comp, args, delays_expanded, weights))

        return out

    def short_info(self):
        raise NotImplementedError('should be implemented in subclass')

    def get_shear_moduli(self, lat, lon, points,
                         interpolation=None):
        '''
        Get shear moduli at given points from contained velocity model.

        :param lat: surface origin for coordinate system of ``points``
        :param points: NumPy array of shape ``(N, 3)``, where each row is
            a point ``(north, east, depth)``, relative to origin at
            ``(lat, lon)``
        :param interpolation: interpolation method. Choose from
            ``('nearest_neighbor', 'multilinear')``
        :returns: NumPy array of length N with extracted shear moduli at each
            point

        The default implementation retrieves and interpolates the shear moduli
        from the contained 1D velocity profile.
        '''
        return self.get_material_property(lat, lon, points,
                                          parameter='shear_moduli',
                                          interpolation=interpolation)

    def get_lambda_moduli(self, lat, lon, points,
                          interpolation=None):
        '''
        Get lambda moduli at given points from contained velocity model.

        :param lat: surface origin for coordinate system of ``points``
        :param points: NumPy array of shape ``(N, 3)``, where each row is
            a point ``(north, east, depth)``, relative to origin at
            ``(lat, lon)``
        :param interpolation: interpolation method. Choose from
            ``('nearest_neighbor', 'multilinear')``
        :returns: NumPy array of length N with extracted shear moduli at each
            point

        The default implementation retrieves and interpolates the lambda moduli
        from the contained 1D velocity profile.
        '''
        return self.get_material_property(lat, lon, points,
                                          parameter='lambda_moduli',
                                          interpolation=interpolation)

    def get_bulk_moduli(self, lat, lon, points,
                        interpolation=None):
        '''
        Get bulk moduli at given points from contained velocity model.

        :param lat: surface origin for coordinate system of ``points``
        :param points: NumPy array of shape ``(N, 3)``, where each row is
            a point ``(north, east, depth)``, relative to origin at
            ``(lat, lon)``
        :param interpolation: interpolation method. Choose from
            ``('nearest_neighbor', 'multilinear')``
        :returns: NumPy array of length N with extracted shear moduli at each
            point

        The default implementation retrieves and interpolates the lambda moduli
        from the contained 1D velocity profile.
        '''
        lambda_moduli = self.get_material_property(
            lat, lon, points, parameter='lambda_moduli',
            interpolation=interpolation)
        shear_moduli = self.get_material_property(
            lat, lon, points, parameter='shear_moduli',
            interpolation=interpolation)
        return lambda_moduli + (2 / 3) * shear_moduli

    def get_vs(self, lat, lon, points, interpolation=None):
        '''
        Get Vs at given points from contained velocity model.

        :param lat: surface origin for coordinate system of ``points``
        :param points: NumPy array of shape ``(N, 3)``, where each row is
            a point ``(north, east, depth)``, relative to origin at
            ``(lat, lon)``
        :param interpolation: interpolation method. Choose from
            ``('nearest_neighbor', 'multilinear')``
        :returns: NumPy array of length N with extracted shear moduli at each
            point

        The default implementation retrieves and interpolates Vs
        from the contained 1D velocity profile.
        '''
        return self.get_material_property(lat, lon, points,
                                          parameter='vs',
                                          interpolation=interpolation)

    def get_vp(self, lat, lon, points, interpolation=None):
        '''
        Get Vp at given points from contained velocity model.

        :param lat: surface origin for coordinate system of ``points``
        :param points: NumPy array of shape ``(N, 3)``, where each row is
            a point ``(north, east, depth)``, relative to origin at
            ``(lat, lon)``
        :param interpolation: interpolation method. Choose from
            ``('nearest_neighbor', 'multilinear')``
        :returns: NumPy array of length N with extracted shear moduli at each
            point

        The default implementation retrieves and interpolates Vp
        from the contained 1D velocity profile.
        '''
        return self.get_material_property(lat, lon, points,
                                          parameter='vp',
                                          interpolation=interpolation)

    def get_rho(self, lat, lon, points, interpolation=None):
        '''
        Get rho at given points from contained velocity model.

        :param lat: surface origin for coordinate system of ``points``
        :param points: NumPy array of shape ``(N, 3)``, where each row is
            a point ``(north, east, depth)``, relative to origin at
            ``(lat, lon)``
        :param interpolation: interpolation method. Choose from
            ``('nearest_neighbor', 'multilinear')``
        :returns: NumPy array of length N with extracted shear moduli at each
            point

        The default implementation retrieves and interpolates rho
        from the contained 1D velocity profile.
        '''
        return self.get_material_property(lat, lon, points,
                                          parameter='rho',
                                          interpolation=interpolation)

    def get_material_property(self, lat, lon, points, parameter='vs',
                              interpolation=None):

        if interpolation is None:
            raise TypeError('Interpolation method not defined! available: '
                            'multilinear', 'nearest_neighbor')

        earthmod = self.earthmodel_1d
        store_depth_profile = self.get_source_depths()
        z_profile = earthmod.profile('z')

        if parameter == 'vs':
            vs_profile = earthmod.profile('vs')
            profile = num.interp(
                store_depth_profile, z_profile, vs_profile)

        elif parameter == 'vp':
            vp_profile = earthmod.profile('vp')
            profile = num.interp(
                store_depth_profile, z_profile, vp_profile)

        elif parameter == 'rho':
            rho_profile = earthmod.profile('rho')

            profile = num.interp(
                store_depth_profile, z_profile, rho_profile)

        elif parameter == 'shear_moduli':
            vs_profile = earthmod.profile('vs')
            rho_profile = earthmod.profile('rho')

            store_vs_profile = num.interp(
                store_depth_profile, z_profile, vs_profile)
            store_rho_profile = num.interp(
                store_depth_profile, z_profile, rho_profile)

            profile = num.power(store_vs_profile, 2) * store_rho_profile

        elif parameter == 'lambda_moduli':
            vs_profile = earthmod.profile('vs')
            vp_profile = earthmod.profile('vp')
            rho_profile = earthmod.profile('rho')

            store_vs_profile = num.interp(
                store_depth_profile, z_profile, vs_profile)
            store_vp_profile = num.interp(
                store_depth_profile, z_profile, vp_profile)
            store_rho_profile = num.interp(
                store_depth_profile, z_profile, rho_profile)

            profile = store_rho_profile * (
                num.power(store_vp_profile, 2) -
                num.power(store_vs_profile, 2) * 2)
        else:
            raise TypeError(
                'parameter %s not available' % parameter)

        if interpolation == 'multilinear':
            kind = 'linear'
        elif interpolation == 'nearest_neighbor':
            kind = 'nearest'
        else:
            raise TypeError(
                'Interpolation method %s not available' % interpolation)

        interpolator = interp1d(store_depth_profile, profile, kind=kind)

        try:
            return interpolator(points[:, 2])
        except ValueError:
            raise OutOfBounds()

    def is_static(self):
        for code in ('psgrn_pscmp', 'poel'):
            if self.modelling_code_id.startswith(code):
                return True
        return False

    def is_dynamic(self):
        return not self.is_static()

    def get_source_depths(self):
        raise NotImplementedError('must be implemented in subclass')

    def get_tabulated_phase(self, phase_id):
        '''
        Get tabulated phase definition.
        '''

        for pdef in self.tabulated_phases:
            if pdef.id == phase_id:
                return pdef

        raise StoreError('No such phase: %s' % phase_id)

    def fix_ttt_holes(self, sptree, mode):
        raise StoreError(
            'Cannot fix travel time table holes in GF stores of type %s.'
            % self.short_type)

    @property
    def effective_stored_quantity(self):
        return self.stored_quantity if self.stored_quantity is not None else \
            component_scheme_to_description[self.component_scheme] \
            .default_stored_quantity


class ConfigTypeA(Config):
    '''
    Cylindrical symmetry, 1D earth model, single receiver depth

    * Problem is invariant to horizontal translations and rotations around
      vertical axis.

    * All receivers must be at the same depth (e.g. at the surface)
      High level index variables: ``(source_depth, distance,
      component)``

    * The ``distance`` is the surface distance between source and receiver
      points.
    '''

    receiver_depth = Float.T(
        default=0.0,
        help='Fixed receiver depth [m].')

    source_depth_min = Float.T(
        help='Minimum source depth [m].')

    source_depth_max = Float.T(
        help='Maximum source depth [m].')

    source_depth_delta = Float.T(
        help='Grid spacing of source depths [m]')

    distance_min = Float.T(
        help='Minimum source-receiver surface distance [m].')

    distance_max = Float.T(
        help='Maximum source-receiver surface distance [m].')

    distance_delta = Float.T(
        help='Grid spacing of source-receiver surface distance [m].')

    fd_distance_delta = Float.T(
        optional=True,
        help='Finite differences interval for FD stores [m].')

    short_type = 'A'

    provided_schemes = [
        'elastic2', 'elastic5', 'elastic8', 'elastic10', 'poroelastic10',
        'rotational8']

    def get_surface_distance(self, args):
        return args[1]

    def get_distance(self, args):
        return math.sqrt(args[0]**2 + args[1]**2)

    def get_source_depth(self, args):
        return args[0]

    def get_source_depths(self):
        return self.coords[0]

    def get_receiver_depth(self, args):
        return self.receiver_depth

    def _update(self):
        self.mins = num.array(
            [self.source_depth_min, self.distance_min], dtype=float)
        self.maxs = num.array(
            [self.source_depth_max, self.distance_max], dtype=float)
        self.deltas = num.array(
            [self.source_depth_delta, self.distance_delta],
            dtype=float)
        self.ns = num.floor((self.maxs - self.mins) / self.deltas +
                            vicinity_eps).astype(int) + 1
        self.effective_maxs = self.mins + self.deltas * (self.ns - 1)
        self.deltat = 1.0/self.sample_rate
        self.nrecords = num.prod(self.ns) * self.ncomponents
        self.coords = tuple(num.linspace(mi, ma, n) for
                            (mi, ma, n) in
                            zip(self.mins, self.effective_maxs, self.ns)) + \
            (num.arange(self.ncomponents),)

        self.nsource_depths, self.ndistances = self.ns

    def _make_index_functions(self):

        amin, bmin = self.mins
        da, db = self.deltas
        na, nb = self.ns

        ng = self.ncomponents

        def index_function(a, b, ig):
            ia = int(round((a - amin) / da))
            ib = int(round((b - bmin) / db))
            try:
                return num.ravel_multi_index((ia, ib, ig), (na, nb, ng))
            except ValueError:
                raise OutOfBounds()

        def indices_function(a, b, ig):
            ia = num.round((a - amin) / da).astype(int)
            ib = num.round((b - bmin) / db).astype(int)
            try:
                return num.ravel_multi_index((ia, ib, ig), (na, nb, ng))
            except ValueError:
                for ia_, ib_, ig_ in zip(ia, ib, ig):
                    try:
                        num.ravel_multi_index((ia_, ib_, ig_), (na, nb, ng))
                    except ValueError:
                        raise OutOfBounds()

        def grid_interpolation_coefficients(a, b):
            ias = indi12((a - amin) / da, na)
            ibs = indi12((b - bmin) / db, nb)
            return ias, ibs

        def vicinity_function(a, b, ig):
            ias, ibs = grid_interpolation_coefficients(a, b)

            if not (0 <= ig < ng):
                raise OutOfBounds()

            indis = []
            weights = []
            for ia, va in ias:
                iia = ia*nb*ng
                for ib, vb in ibs:
                    indis.append(iia + ib*ng + ig)
                    weights.append(va*vb)

            return num.array(indis), num.array(weights)

        def vicinities_function(a, b, ig):

            xa = (a - amin) / da
            xb = (b - bmin) / db

            xa_fl = num.floor(xa)
            xa_ce = num.ceil(xa)
            xb_fl = num.floor(xb)
            xb_ce = num.ceil(xb)
            va_fl = 1.0 - (xa - xa_fl)
            va_ce = (1.0 - (xa_ce - xa)) * (xa_ce - xa_fl)
            vb_fl = 1.0 - (xb - xb_fl)
            vb_ce = (1.0 - (xb_ce - xb)) * (xb_ce - xb_fl)

            ia_fl = xa_fl.astype(int)
            ia_ce = xa_ce.astype(int)
            ib_fl = xb_fl.astype(int)
            ib_ce = xb_ce.astype(int)

            if num.any(ia_fl < 0) or num.any(ia_fl >= na):
                raise OutOfBounds()

            if num.any(ia_ce < 0) or num.any(ia_ce >= na):
                raise OutOfBounds()

            if num.any(ib_fl < 0) or num.any(ib_fl >= nb):
                raise OutOfBounds()

            if num.any(ib_ce < 0) or num.any(ib_ce >= nb):
                raise OutOfBounds()

            irecords = num.empty(a.size*4, dtype=int)
            irecords[0::4] = ia_fl*nb*ng + ib_fl*ng + ig
            irecords[1::4] = ia_ce*nb*ng + ib_fl*ng + ig
            irecords[2::4] = ia_fl*nb*ng + ib_ce*ng + ig
            irecords[3::4] = ia_ce*nb*ng + ib_ce*ng + ig

            weights = num.empty(a.size*4, dtype=float)
            weights[0::4] = va_fl * vb_fl
            weights[1::4] = va_ce * vb_fl
            weights[2::4] = va_fl * vb_ce
            weights[3::4] = va_ce * vb_ce

            return irecords, weights

        self._index_function = index_function
        self._indices_function = indices_function
        self._grid_interpolation_coefficients = grid_interpolation_coefficients
        self._vicinity_function = vicinity_function
        self._vicinities_function = vicinities_function

    def make_indexing_args(self, source, receiver, icomponents):
        nc = icomponents.size
        dists = source.distances_to(receiver)
        n = dists.size
        return (num.tile(source.depths, nc//n),
                num.tile(dists, nc//n),
                icomponents)

    def make_indexing_args1(self, source, receiver):
        return (source.depth, source.distance_to(receiver))

    @property
    def short_extent(self):
        return '%g:%g:%g x %g:%g:%g' % (
            self.source_depth_min/km,
            self.source_depth_max/km,
            self.source_depth_delta/km,
            self.distance_min/km,
            self.distance_max/km,
            self.distance_delta/km)

    def fix_ttt_holes(self, sptree, mode):
        from pyrocko import eikonal_ext, spit

        nodes = self.nodes(level=-1)

        delta = self.deltas[-1]
        assert num.all(delta == self.deltas)

        nsources, ndistances = self.ns

        points = num.zeros((nodes.shape[0], 3))
        points[:, 0] = nodes[:, 1]
        points[:, 2] = nodes[:, 0]

        speeds = self.get_material_property(
            0., 0., points,
            parameter='vp' if mode == cake.P else 'vs',
            interpolation='multilinear')

        speeds = speeds.reshape((nsources, ndistances))

        times = sptree.interpolate_many(nodes)

        times[num.isnan(times)] = -1.
        times = times.reshape(speeds.shape)

        try:
            eikonal_ext.eikonal_solver_fmm_cartesian(
                speeds, times, delta)
        except eikonal_ext.EikonalExtError as e:
            if str(e).endswith('please check results'):
                logger.debug(
                    'Got a warning from eikonal solver '
                    '- may be ok...')
            else:
                raise

        def func(x):
            ibs, ics = \
                self.grid_interpolation_coefficients(*x)

            t = 0
            for ib, vb in ibs:
                for ic, vc in ics:
                    t += times[ib, ic] * vb * vc

            return t

        return spit.SPTree(
            f=func,
            ftol=sptree.ftol,
            xbounds=sptree.xbounds,
            xtols=sptree.xtols)


class ConfigTypeB(Config):
    '''
    Cylindrical symmetry, 1D earth model, variable receiver depth

    * Symmetries like in :py:class:`ConfigTypeA` but has additional index for
      receiver depth

    * High level index variables: ``(receiver_depth, source_depth,
      receiver_distance, component)``
    '''

    receiver_depth_min = Float.T(
        help='Minimum receiver depth [m].')

    receiver_depth_max = Float.T(
        help='Maximum receiver depth [m].')

    receiver_depth_delta = Float.T(
        help='Grid spacing of receiver depths [m]')

    source_depth_min = Float.T(
        help='Minimum source depth [m].')

    source_depth_max = Float.T(
        help='Maximum source depth [m].')

    source_depth_delta = Float.T(
        help='Grid spacing of source depths [m]')

    distance_min = Float.T(
        help='Minimum source-receiver surface distance [m].')

    distance_max = Float.T(
        help='Maximum source-receiver surface distance [m].')

    distance_delta = Float.T(
        help='Grid spacing of source-receiver surface distances [m].')

    fd_distance_delta = Float.T(
        optional=True,
        help='Finite differences interval for FD stores [m].')

    fd_receiver_depth_delta = Float.T(
        optional=True,
        help='Finite differences interval for FD stores [m].')

    short_type = 'B'

    provided_schemes = [
        'elastic2', 'elastic5', 'elastic8', 'elastic10', 'poroelastic10',
        'rotational8']

    def get_distance(self, args):
        return math.sqrt((args[1] - args[0])**2 + args[2]**2)

    def get_surface_distance(self, args):
        return args[2]

    def get_source_depth(self, args):
        return args[1]

    def get_receiver_depth(self, args):
        return args[0]

    def get_source_depths(self):
        return self.coords[1]

    def _update(self):
        self.mins = num.array([
            self.receiver_depth_min,
            self.source_depth_min,
            self.distance_min],
            dtype=float)

        self.maxs = num.array([
            self.receiver_depth_max,
            self.source_depth_max,
            self.distance_max],
            dtype=float)

        self.deltas = num.array([
            self.receiver_depth_delta,
            self.source_depth_delta,
            self.distance_delta],
            dtype=float)

        self.ns = num.floor((self.maxs - self.mins) / self.deltas +
                            vicinity_eps).astype(int) + 1
        self.effective_maxs = self.mins + self.deltas * (self.ns - 1)
        self.deltat = 1.0/self.sample_rate
        self.nrecords = num.prod(self.ns) * self.ncomponents
        self.coords = tuple(num.linspace(mi, ma, n) for
                            (mi, ma, n) in
                            zip(self.mins, self.effective_maxs, self.ns)) + \
            (num.arange(self.ncomponents),)
        self.nreceiver_depths, self.nsource_depths, self.ndistances = self.ns

    def _make_index_functions(self):

        amin, bmin, cmin = self.mins
        da, db, dc = self.deltas
        na, nb, nc = self.ns
        ng = self.ncomponents

        def index_function(a, b, c, ig):
            ia = int(round((a - amin) / da))
            ib = int(round((b - bmin) / db))
            ic = int(round((c - cmin) / dc))
            try:
                return num.ravel_multi_index((ia, ib, ic, ig),
                                             (na, nb, nc, ng))
            except ValueError:
                raise OutOfBounds()

        def indices_function(a, b, c, ig):
            ia = num.round((a - amin) / da).astype(int)
            ib = num.round((b - bmin) / db).astype(int)
            ic = num.round((c - cmin) / dc).astype(int)
            try:
                return num.ravel_multi_index((ia, ib, ic, ig),
                                             (na, nb, nc, ng))
            except ValueError:
                raise OutOfBounds()

        def grid_interpolation_coefficients(a, b, c):
            ias = indi12((a - amin) / da, na)
            ibs = indi12((b - bmin) / db, nb)
            ics = indi12((c - cmin) / dc, nc)
            return ias, ibs, ics

        def vicinity_function(a, b, c, ig):
            ias, ibs, ics = grid_interpolation_coefficients(a, b, c)

            if not (0 <= ig < ng):
                raise OutOfBounds()

            indis = []
            weights = []
            for ia, va in ias:
                iia = ia*nb*nc*ng
                for ib, vb in ibs:
                    iib = ib*nc*ng
                    for ic, vc in ics:
                        indis.append(iia + iib + ic*ng + ig)
                        weights.append(va*vb*vc)

            return num.array(indis), num.array(weights)

        def vicinities_function(a, b, c, ig):

            xa = (a - amin) / da
            xb = (b - bmin) / db
            xc = (c - cmin) / dc

            xa_fl = num.floor(xa)
            xa_ce = num.ceil(xa)
            xb_fl = num.floor(xb)
            xb_ce = num.ceil(xb)
            xc_fl = num.floor(xc)
            xc_ce = num.ceil(xc)
            va_fl = 1.0 - (xa - xa_fl)
            va_ce = (1.0 - (xa_ce - xa)) * (xa_ce - xa_fl)
            vb_fl = 1.0 - (xb - xb_fl)
            vb_ce = (1.0 - (xb_ce - xb)) * (xb_ce - xb_fl)
            vc_fl = 1.0 - (xc - xc_fl)
            vc_ce = (1.0 - (xc_ce - xc)) * (xc_ce - xc_fl)

            ia_fl = xa_fl.astype(int)
            ia_ce = xa_ce.astype(int)
            ib_fl = xb_fl.astype(int)
            ib_ce = xb_ce.astype(int)
            ic_fl = xc_fl.astype(int)
            ic_ce = xc_ce.astype(int)

            if num.any(ia_fl < 0) or num.any(ia_fl >= na):
                raise OutOfBounds()

            if num.any(ia_ce < 0) or num.any(ia_ce >= na):
                raise OutOfBounds()

            if num.any(ib_fl < 0) or num.any(ib_fl >= nb):
                raise OutOfBounds()

            if num.any(ib_ce < 0) or num.any(ib_ce >= nb):
                raise OutOfBounds()

            if num.any(ic_fl < 0) or num.any(ic_fl >= nc):
                raise OutOfBounds()

            if num.any(ic_ce < 0) or num.any(ic_ce >= nc):
                raise OutOfBounds()

            irecords = num.empty(a.size*8, dtype=int)
            irecords[0::8] = ia_fl*nb*nc*ng + ib_fl*nc*ng + ic_fl*ng + ig
            irecords[1::8] = ia_ce*nb*nc*ng + ib_fl*nc*ng + ic_fl*ng + ig
            irecords[2::8] = ia_fl*nb*nc*ng + ib_ce*nc*ng + ic_fl*ng + ig
            irecords[3::8] = ia_ce*nb*nc*ng + ib_ce*nc*ng + ic_fl*ng + ig
            irecords[4::8] = ia_fl*nb*nc*ng + ib_fl*nc*ng + ic_ce*ng + ig
            irecords[5::8] = ia_ce*nb*nc*ng + ib_fl*nc*ng + ic_ce*ng + ig
            irecords[6::8] = ia_fl*nb*nc*ng + ib_ce*nc*ng + ic_ce*ng + ig
            irecords[7::8] = ia_ce*nb*nc*ng + ib_ce*nc*ng + ic_ce*ng + ig

            weights = num.empty(a.size*8, dtype=float)
            weights[0::8] = va_fl * vb_fl * vc_fl
            weights[1::8] = va_ce * vb_fl * vc_fl
            weights[2::8] = va_fl * vb_ce * vc_fl
            weights[3::8] = va_ce * vb_ce * vc_fl
            weights[4::8] = va_fl * vb_fl * vc_ce
            weights[5::8] = va_ce * vb_fl * vc_ce
            weights[6::8] = va_fl * vb_ce * vc_ce
            weights[7::8] = va_ce * vb_ce * vc_ce

            return irecords, weights

        self._index_function = index_function
        self._indices_function = indices_function
        self._grid_interpolation_coefficients = grid_interpolation_coefficients
        self._vicinity_function = vicinity_function
        self._vicinities_function = vicinities_function

    def make_indexing_args(self, source, receiver, icomponents):
        nc = icomponents.size
        dists = source.distances_to(receiver)
        n = dists.size
        receiver_depths = num.empty(nc)
        receiver_depths.fill(receiver.depth)
        return (receiver_depths,
                num.tile(source.depths, nc//n),
                num.tile(dists, nc//n),
                icomponents)

    def make_indexing_args1(self, source, receiver):
        return (receiver.depth,
                source.depth,
                source.distance_to(receiver))

    @property
    def short_extent(self):
        return '%g:%g:%g x %g:%g:%g x %g:%g:%g' % (
            self.receiver_depth_min/km,
            self.receiver_depth_max/km,
            self.receiver_depth_delta/km,
            self.source_depth_min/km,
            self.source_depth_max/km,
            self.source_depth_delta/km,
            self.distance_min/km,
            self.distance_max/km,
            self.distance_delta/km)

    def fix_ttt_holes(self, sptree, mode):
        from pyrocko import eikonal_ext, spit

        nodes_sr = self.nodes(minlevel=1, level=-1)

        delta = self.deltas[-1]
        assert num.all(delta == self.deltas[1:])

        nreceivers, nsources, ndistances = self.ns

        points = num.zeros((nodes_sr.shape[0], 3))
        points[:, 0] = nodes_sr[:, 1]
        points[:, 2] = nodes_sr[:, 0]

        speeds = self.get_material_property(
            0., 0., points,
            parameter='vp' if mode == cake.P else 'vs',
            interpolation='multilinear')

        speeds = speeds.reshape((nsources, ndistances))

        receiver_times = []
        for ireceiver in range(nreceivers):
            nodes = num.hstack([
                num.full(
                    (nodes_sr.shape[0], 1),
                    self.coords[0][ireceiver]),
                nodes_sr])

            times = sptree.interpolate_many(nodes)

            times[num.isnan(times)] = -1.

            times = times.reshape(speeds.shape)

            try:
                eikonal_ext.eikonal_solver_fmm_cartesian(
                    speeds, times, delta)
            except eikonal_ext.EikonalExtError as e:
                if str(e).endswith('please check results'):
                    logger.debug(
                        'Got a warning from eikonal solver '
                        '- may be ok...')
                else:
                    raise

            receiver_times.append(times)

        def func(x):
            ias, ibs, ics = \
                self.grid_interpolation_coefficients(*x)

            t = 0
            for ia, va in ias:
                times = receiver_times[ia]
                for ib, vb in ibs:
                    for ic, vc in ics:
                        t += times[ib, ic] * va * vb * vc

            return t

        return spit.SPTree(
            f=func,
            ftol=sptree.ftol,
            xbounds=sptree.xbounds,
            xtols=sptree.xtols)


class ConfigTypeC(Config):
    '''
    No symmetrical constraints, one fixed receiver position.

    * Cartesian 3D source volume around a reference point

    * High level index variables: ``(source_depth,
      source_east_shift, source_north_shift, component)``
    '''

    receiver = Receiver.T(
        help='Receiver location')

    source_origin = Location.T(
        help='Origin of the source volume grid.')

    source_depth_min = Float.T(
        help='Minimum source depth [m].')

    source_depth_max = Float.T(
        help='Maximum source depth [m].')

    source_depth_delta = Float.T(
        help='Source depth grid spacing [m].')

    source_east_shift_min = Float.T(
        help='Minimum easting of source grid [m].')

    source_east_shift_max = Float.T(
        help='Maximum easting of source grid [m].')

    source_east_shift_delta = Float.T(
        help='Source volume grid spacing in east direction [m].')

    source_north_shift_min = Float.T(
        help='Minimum northing of source grid [m].')

    source_north_shift_max = Float.T(
        help='Maximum northing of source grid [m].')

    source_north_shift_delta = Float.T(
        help='Source volume grid spacing in north direction [m].')

    short_type = 'C'

    provided_schemes = ['elastic18']

    def get_surface_distance(self, args):
        _, source_east_shift, source_north_shift, _ = args
        sorig = self.source_origin
        sloc = Location(
            lat=sorig.lat,
            lon=sorig.lon,
            north_shift=sorig.north_shift + source_north_shift,
            east_shift=sorig.east_shift + source_east_shift)

        return self.receiver.distance_to(sloc)

    def get_distance(self, args):
        sdepth, source_east_shift, source_north_shift, _ = args
        sorig = self.source_origin
        sloc = Location(
            lat=sorig.lat,
            lon=sorig.lon,
            north_shift=sorig.north_shift + source_north_shift,
            east_shift=sorig.east_shift + source_east_shift)

        return self.receiver.distance_3d_to(sloc)

    def get_source_depth(self, args):
        return args[0]

    def get_receiver_depth(self, args):
        return self.receiver.depth

    def get_source_depths(self):
        return self.coords[0]

    def _update(self):
        self.mins = num.array([
            self.source_depth_min,
            self.source_east_shift_min,
            self.source_north_shift_min],
            dtype=float)

        self.maxs = num.array([
            self.source_depth_max,
            self.source_east_shift_max,
            self.source_north_shift_max],
            dtype=float)

        self.deltas = num.array([
            self.source_depth_delta,
            self.source_east_shift_delta,
            self.source_north_shift_delta],
            dtype=float)

        self.ns = num.floor((self.maxs - self.mins) / self.deltas +
                            vicinity_eps).astype(int) + 1
        self.effective_maxs = self.mins + self.deltas * (self.ns - 1)
        self.deltat = 1.0/self.sample_rate
        self.nrecords = num.prod(self.ns) * self.ncomponents

        self.coords = tuple(
            num.linspace(mi, ma, n) for (mi, ma, n) in
            zip(self.mins, self.effective_maxs, self.ns)) + \
            (num.arange(self.ncomponents),)

    def _make_index_functions(self):

        amin, bmin, cmin = self.mins
        da, db, dc = self.deltas
        na, nb, nc = self.ns
        ng = self.ncomponents

        def index_function(a, b, c, ig):
            ia = int(round((a - amin) / da))
            ib = int(round((b - bmin) / db))
            ic = int(round((c - cmin) / dc))
            try:
                return num.ravel_multi_index((ia, ib, ic, ig),
                                             (na, nb, nc, ng))
            except ValueError:
                raise OutOfBounds(values=(a, b, c, ig))

        def indices_function(a, b, c, ig):
            ia = num.round((a - amin) / da).astype(int)
            ib = num.round((b - bmin) / db).astype(int)
            ic = num.round((c - cmin) / dc).astype(int)

            try:
                return num.ravel_multi_index((ia, ib, ic, ig),
                                             (na, nb, nc, ng))
            except ValueError:
                raise OutOfBounds()

        def vicinity_function(a, b, c, ig):
            ias = indi12((a - amin) / da, na)
            ibs = indi12((b - bmin) / db, nb)
            ics = indi12((c - cmin) / dc, nc)

            if not (0 <= ig < ng):
                raise OutOfBounds()

            indis = []
            weights = []
            for ia, va in ias:
                iia = ia*nb*nc*ng
                for ib, vb in ibs:
                    iib = ib*nc*ng
                    for ic, vc in ics:
                        indis.append(iia + iib + ic*ng + ig)
                        weights.append(va*vb*vc)

            return num.array(indis), num.array(weights)

        def vicinities_function(a, b, c, ig):

            xa = (a-amin) / da
            xb = (b-bmin) / db
            xc = (c-cmin) / dc

            xa_fl = num.floor(xa)
            xa_ce = num.ceil(xa)
            xb_fl = num.floor(xb)
            xb_ce = num.ceil(xb)
            xc_fl = num.floor(xc)
            xc_ce = num.ceil(xc)
            va_fl = 1.0 - (xa - xa_fl)
            va_ce = (1.0 - (xa_ce - xa)) * (xa_ce - xa_fl)
            vb_fl = 1.0 - (xb - xb_fl)
            vb_ce = (1.0 - (xb_ce - xb)) * (xb_ce - xb_fl)
            vc_fl = 1.0 - (xc - xc_fl)
            vc_ce = (1.0 - (xc_ce - xc)) * (xc_ce - xc_fl)

            ia_fl = xa_fl.astype(int)
            ia_ce = xa_ce.astype(int)
            ib_fl = xb_fl.astype(int)
            ib_ce = xb_ce.astype(int)
            ic_fl = xc_fl.astype(int)
            ic_ce = xc_ce.astype(int)

            if num.any(ia_fl < 0) or num.any(ia_fl >= na):
                raise OutOfBounds()

            if num.any(ia_ce < 0) or num.any(ia_ce >= na):
                raise OutOfBounds()

            if num.any(ib_fl < 0) or num.any(ib_fl >= nb):
                raise OutOfBounds()

            if num.any(ib_ce < 0) or num.any(ib_ce >= nb):
                raise OutOfBounds()

            if num.any(ic_fl < 0) or num.any(ic_fl >= nc):
                raise OutOfBounds()

            if num.any(ic_ce < 0) or num.any(ic_ce >= nc):
                raise OutOfBounds()

            irecords = num.empty(a.size*8, dtype=int)
            irecords[0::8] = ia_fl*nb*nc*ng + ib_fl*nc*ng + ic_fl*ng + ig
            irecords[1::8] = ia_ce*nb*nc*ng + ib_fl*nc*ng + ic_fl*ng + ig
            irecords[2::8] = ia_fl*nb*nc*ng + ib_ce*nc*ng + ic_fl*ng + ig
            irecords[3::8] = ia_ce*nb*nc*ng + ib_ce*nc*ng + ic_fl*ng + ig
            irecords[4::8] = ia_fl*nb*nc*ng + ib_fl*nc*ng + ic_ce*ng + ig
            irecords[5::8] = ia_ce*nb*nc*ng + ib_fl*nc*ng + ic_ce*ng + ig
            irecords[6::8] = ia_fl*nb*nc*ng + ib_ce*nc*ng + ic_ce*ng + ig
            irecords[7::8] = ia_ce*nb*nc*ng + ib_ce*nc*ng + ic_ce*ng + ig

            weights = num.empty(a.size*8, dtype=float)
            weights[0::8] = va_fl * vb_fl * vc_fl
            weights[1::8] = va_ce * vb_fl * vc_fl
            weights[2::8] = va_fl * vb_ce * vc_fl
            weights[3::8] = va_ce * vb_ce * vc_fl
            weights[4::8] = va_fl * vb_fl * vc_ce
            weights[5::8] = va_ce * vb_fl * vc_ce
            weights[6::8] = va_fl * vb_ce * vc_ce
            weights[7::8] = va_ce * vb_ce * vc_ce

            return irecords, weights

        self._index_function = index_function
        self._indices_function = indices_function
        self._vicinity_function = vicinity_function
        self._vicinities_function = vicinities_function

    def make_indexing_args(self, source, receiver, icomponents):
        nc = icomponents.size

        dists = source.distances_to(self.source_origin)
        azis, _ = source.azibazis_to(self.source_origin)

        source_north_shifts = - num.cos(d2r*azis) * dists
        source_east_shifts = - num.sin(d2r*azis) * dists
        source_depths = source.depths - self.source_origin.depth

        n = dists.size

        return (num.tile(source_depths, nc//n),
                num.tile(source_east_shifts, nc//n),
                num.tile(source_north_shifts, nc//n),
                icomponents)

    def make_indexing_args1(self, source, receiver):
        dist = source.distance_to(self.source_origin)
        azi, _ = source.azibazi_to(self.source_origin)

        source_north_shift = - num.cos(d2r*azi) * dist
        source_east_shift = - num.sin(d2r*azi) * dist
        source_depth = source.depth - self.source_origin.depth

        return (source_depth,
                source_east_shift,
                source_north_shift)

    @property
    def short_extent(self):
        return '%g:%g:%g x %g:%g:%g x %g:%g:%g' % (
            self.source_depth_min/km,
            self.source_depth_max/km,
            self.source_depth_delta/km,
            self.source_east_shift_min/km,
            self.source_east_shift_max/km,
            self.source_east_shift_delta/km,
            self.source_north_shift_min/km,
            self.source_north_shift_max/km,
            self.source_north_shift_delta/km)


class Weighting(Object):
    factor = Float.T(default=1.0)


class Taper(Object):
    tmin = Timing.T()
    tmax = Timing.T()
    tfade = Float.T(default=0.0)
    shape = StringChoice.T(
        choices=['cos', 'linear'],
        default='cos',
        optional=True)


class SimplePattern(SObject):

    _pool = {}

    def __init__(self, pattern):
        self._pattern = pattern
        SObject.__init__(self)

    def __str__(self):
        return self._pattern

    @property
    def regex(self):
        pool = SimplePattern._pool
        if self.pattern not in pool:
            rpat = '|'.join(fnmatch.translate(x) for
                            x in self.pattern.split('|'))
            pool[self.pattern] = re.compile(rpat, re.I)

        return pool[self.pattern]

    def match(self, s):
        return self.regex.match(s)


class WaveformType(StringChoice):
    choices = ['dis', 'vel', 'acc',
               'amp_spec_dis', 'amp_spec_vel', 'amp_spec_acc',
               'envelope_dis', 'envelope_vel', 'envelope_acc']


class ChannelSelection(Object):
    pattern = SimplePattern.T(optional=True)
    min_sample_rate = Float.T(optional=True)
    max_sample_rate = Float.T(optional=True)


class StationSelection(Object):
    includes = SimplePattern.T()
    excludes = SimplePattern.T()
    distance_min = Float.T(optional=True)
    distance_max = Float.T(optional=True)
    azimuth_min = Float.T(optional=True)
    azimuth_max = Float.T(optional=True)


class WaveformSelection(Object):
    channel_selection = ChannelSelection.T(optional=True)
    station_selection = StationSelection.T(optional=True)
    taper = Taper.T()
    # filter = FrequencyResponse.T()
    waveform_type = WaveformType.T(default='dis')
    weighting = Weighting.T(optional=True)
    sample_rate = Float.T(optional=True)
    gf_store_id = StringID.T(optional=True)


def indi12(x, n):
    '''
    Get linear interpolation index and weight.
    '''

    r = round(x)
    if abs(r - x) < vicinity_eps:
        i = int(r)
        if not (0 <= i < n):
            raise OutOfBounds()

        return ((int(r), 1.),)
    else:
        f = math.floor(x)
        i = int(f)
        if not (0 <= i < n-1):
            raise OutOfBounds()

        v = x-f
        return ((i, 1.-v), (i + 1, v))


def float_or_none(s):
    units = {
        'k': 1e3,
        'M': 1e6,
    }

    factor = 1.0
    if s and s[-1] in units:
        factor = units[s[-1]]
        s = s[:-1]
        if not s:
            raise ValueError("unit without a number: '%s'" % s)

    if s:
        return float(s) * factor
    else:
        return None


class GridSpecError(Exception):
    def __init__(self, s):
        Exception.__init__(self, 'invalid grid specification: %s' % s)


def parse_grid_spec(spec):
    try:
        result = []
        for dspec in spec.split(','):
            t = dspec.split('@')
            num = start = stop = step = None
            if len(t) == 2:
                num = int(t[1])
                if num <= 0:
                    raise GridSpecError(spec)

            elif len(t) > 2:
                raise GridSpecError(spec)

            s = t[0]
            v = [float_or_none(x) for x in s.split(':')]
            if len(v) == 1:
                start = stop = v[0]
            if len(v) >= 2:
                start, stop = v[0:2]
            if len(v) == 3:
                step = v[2]

            if len(v) > 3 or (len(v) > 2 and num is not None):
                raise GridSpecError(spec)

            if step == 0.0:
                raise GridSpecError(spec)

            result.append((start, stop, step, num))

    except ValueError:
        raise GridSpecError(spec)

    return result


def start_stop_num(start, stop, step, num, mi, ma, inc, eps=1e-5):
    swap = step is not None and step < 0.
    if start is None:
        start = ma if swap else mi
    if stop is None:
        stop = mi if swap else ma
    if step is None:
        step = -inc if ma < mi else inc
    if num is None:
        if (step < 0) != (stop-start < 0):
            raise GridSpecError()

        num = int(round((stop-start)/step))+1
        stop2 = start + (num-1)*step
        if abs(stop-stop2) > eps:
            num = int(math.floor((stop-start)/step))+1
            stop = start + (num-1)*step
        else:
            stop = stop2

    if start == stop:
        num = 1

    return start, stop, num


def nditer_outer(x):
    return num.nditer(
        x, op_axes=(num.identity(len(x), dtype=int)-1).tolist())


def nodes(xs):
    ns = [x.size for x in xs]
    nnodes = num.prod(ns)
    ndim = len(xs)
    nodes = num.empty((nnodes, ndim), dtype=xs[0].dtype)
    for idim in range(ndim-1, -1, -1):
        x = xs[idim]
        nrepeat = num.prod(ns[idim+1:], dtype=int)
        ntile = num.prod(ns[:idim], dtype=int)
        nodes[:, idim] = num.repeat(num.tile(x, ntile), nrepeat)

    return nodes


def filledi(x, n):
    a = num.empty(n, dtype=int)
    a.fill(x)
    return a


config_type_classes = [ConfigTypeA, ConfigTypeB, ConfigTypeC]

discretized_source_classes = [
    DiscretizedExplosionSource,
    DiscretizedSFSource,
    DiscretizedMTSource,
    DiscretizedPorePressureSource]


__all__ = '''
Earthmodel1D
StringID
ScopeType
WaveformType
QuantityType
NearfieldTermsType
Reference
Region
CircularRegion
RectangularRegion
PhaseSelect
InvalidTimingSpecification
Timing
TPDef
OutOfBounds
Location
Receiver
'''.split() + [
    S.__name__ for S in discretized_source_classes + config_type_classes] + '''
ComponentScheme
component_scheme_to_description
component_schemes
Config
GridSpecError
Weighting
Taper
SimplePattern
WaveformType
ChannelSelection
StationSelection
WaveformSelection
nditer_outer
dump
load
discretized_source_classes
config_type_classes
UnavailableScheme
InterpolationMethod
SeismosizerTrace
SeismosizerResult
Result
StaticResult
TimingAttributeError
'''.split()
