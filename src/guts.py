# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Lightweight declarative YAML and XML data binding for Python.
'''

import datetime
import calendar
import re
import sys
import os
import types
import copy
import logging
import os.path as op
from collections import defaultdict
from base64 import b64decode, b64encode

from io import BytesIO

try:
    import numpy as num
except ImportError:
    num = None

import yaml
try:
    from yaml import CSafeLoader as SafeLoader, CSafeDumper as SafeDumper
except ImportError:
    from yaml import SafeLoader, SafeDumper

from .util import time_to_str, str_to_time, TimeStrError, hpfloat, \
    get_time_float


logger = logging.getLogger('pyrocko.guts')

ALLOW_INCLUDE = False


class GutsSafeDumper(SafeDumper):
    pass


class GutsSafeLoader(SafeLoader):
    pass


g_iprop = 0

g_deferred = {}
g_deferred_content = {}

g_tagname_to_class = {}
g_xmltagname_to_class = {}
g_guessable_xmlns = {}

guts_types = [
    'Object', 'SObject', 'String', 'Unicode', 'Int', 'Float',
    'Complex', 'Bool', 'Timestamp', 'DateTimestamp', 'StringPattern',
    'UnicodePattern', 'StringChoice', 'IntChoice', 'List', 'Dict', 'Tuple',
    'StringUnion', 'Choice', 'Any']

us_to_cc_regex = re.compile(r'([a-z])_([a-z])')


class literal(str):
    pass


class folded(str):
    pass


class singlequoted(str):
    pass


class doublequoted(str):
    pass


def make_str_presenter(style):
    def presenter(dumper, data):
        return dumper.represent_scalar(
            'tag:yaml.org,2002:str', str(data), style=style)

    return presenter


str_style_map = {
    None: lambda x: x,
    '|': literal,
    '>': folded,
    "'": singlequoted,
    '"': doublequoted}

for (style, cls) in str_style_map.items():
    if style:
        GutsSafeDumper.add_representer(cls, make_str_presenter(style))


class uliteral(str):
    pass


class ufolded(str):
    pass


class usinglequoted(str):
    pass


class udoublequoted(str):
    pass


def make_unicode_presenter(style):
    def presenter(dumper, data):
        return dumper.represent_scalar(
            'tag:yaml.org,2002:str', str(data), style=style)

    return presenter


unicode_style_map = {
    None: lambda x: x,
    '|': literal,
    '>': folded,
    "'": singlequoted,
    '"': doublequoted}

for (style, cls) in unicode_style_map.items():
    if style:
        GutsSafeDumper.add_representer(cls, make_unicode_presenter(style))


class blist(list):
    pass


class flist(list):
    pass


list_style_map = {
    None: list,
    'block': blist,
    'flow': flist}


def make_list_presenter(flow_style):
    def presenter(dumper, data):
        return dumper.represent_sequence(
            'tag:yaml.org,2002:seq', data, flow_style=flow_style)

    return presenter


GutsSafeDumper.add_representer(blist, make_list_presenter(False))
GutsSafeDumper.add_representer(flist, make_list_presenter(True))

if num:
    def numpy_float_presenter(dumper, data):
        return dumper.represent_float(float(data))

    def numpy_int_presenter(dumper, data):
        return dumper.represent_int(int(data))

    for dtype in (num.float64, num.float32):
        GutsSafeDumper.add_representer(dtype, numpy_float_presenter)

    for dtype in (num.int32, num.int64):
        GutsSafeDumper.add_representer(dtype, numpy_int_presenter)


def us_to_cc(s):
    return us_to_cc_regex.sub(lambda pat: pat.group(1)+pat.group(2).upper(), s)


cc_to_us_regex1 = re.compile(r'([a-z])([A-Z]+)([a-z]|$)')
cc_to_us_regex2 = re.compile(r'([A-Z])([A-Z][a-z])')


def cc_to_us(s):
    return cc_to_us_regex2.sub('\\1_\\2', cc_to_us_regex1.sub(
        '\\1_\\2\\3', s)).lower()


re_frac = re.compile(r'\.[1-9]FRAC')
frac_formats = dict([('.%sFRAC' % x, '%.'+x+'f') for x in '123456789'])


def encode_utf8(s):
    return s.encode('utf-8')


def no_encode(s):
    return s


def make_xmltagname_from_name(name):
    return us_to_cc(name)


def make_name_from_xmltagname(xmltagname):
    return cc_to_us(xmltagname)


def make_content_name(name):
    if name.endswith('_list'):
        return name[:-5]
    elif name.endswith('s'):
        return name[:-1]
    else:
        return name


def classnames(cls):
    if isinstance(cls, tuple):
        return '(%s)' % ', '.join(x.__name__ for x in cls)
    else:
        return cls.__name__


def expand_stream_args(mode):
    def wrap(f):
        '''
        Decorator to enhance functions taking stream objects.

        Wraps a function f(..., stream, ...) so that it can also be called as
        f(..., filename='myfilename', ...) or as f(..., string='mydata', ...).
        '''

        def g(*args, **kwargs):
            stream = kwargs.pop('stream', None)
            filename = kwargs.get('filename', None)
            if mode != 'r':
                filename = kwargs.pop('filename', None)
            string = kwargs.pop('string', None)

            assert sum(x is not None for x in (stream, filename, string)) <= 1

            if stream is not None:
                kwargs['stream'] = stream
                return f(*args, **kwargs)

            elif filename is not None:
                stream = open(filename, mode+'b')
                kwargs['stream'] = stream
                retval = f(*args, **kwargs)
                if isinstance(retval, types.GeneratorType):
                    def wrap_generator(gen):
                        try:
                            for x in gen:
                                yield x

                        except GeneratorExit:
                            pass

                        stream.close()

                    return wrap_generator(retval)

                else:
                    stream.close()
                    return retval

            elif string is not None:
                assert mode == 'r', \
                    'Keyword argument string=... cannot be used in dumper ' \
                    'function.'

                kwargs['stream'] = BytesIO(string.encode('utf-8'))
                return f(*args, **kwargs)

            else:
                assert mode == 'w', \
                    'Use keyword argument stream=... or filename=... in ' \
                    'loader function.'

                sout = BytesIO()
                f(stream=sout, *args, **kwargs)
                return sout.getvalue().decode('utf-8')

        g.__doc__ = f.__doc__
        return g

    return wrap


class Defer(object):
    def __init__(self, classname, *args, **kwargs):
        global g_iprop
        if kwargs.get('position', None) is None:
            kwargs['position'] = g_iprop

        g_iprop += 1

        self.classname = classname
        self.args = args
        self.kwargs = kwargs


class TBase(object):
    '''
    Base class for Guts type definitions.

    :param default:
        Default value or :py:class:`DefaultMaker` object (see
        :py:meth:`Object.D`) to be used to generate a default.

    :param optional:
        If ``True``, the attribute is optional and may be set to ``None``.
    :type optional:
        bool

    :param xmlstyle:
        Controls how the attribute is serialized in XML. :Choices:
        ``'element'``, ``'attribute'``, ``'content'``. Only scalar and
        :py:class:`SObject` values may be serialized as ``'attribute'``. Only
        one attribute in a class may be serialized as ``'content'``.
    :type xmlstyle:
        str

    :param xmltagname:
        XML tag name to be used. By default, the attribute name converted to
        camel-case is used.
    :type xmltagname:
         str

    :param xmlns:
        XML namespace to be used for this attribute.
    :type xmlns:
        str

    :param help:
        Description of the attribute used in documentation and online help.
    :type help:
        rst formatted :py:class:`str`

    :param position:
        Position index to be used when the attribute should be output in
        non-default order.
    :type position:
        int
    '''

    strict = False
    multivalued = None
    force_regularize = False
    propnames = []
    _dummy_cls = None
    _cls = None
    _sphinx_doc_skip = False

    @classmethod
    def init_propertystuff(cls):
        cls.properties = []
        cls.xmltagname_to_name = {}
        cls.xmltagname_to_name_multivalued = {}
        cls.xmltagname_to_class = {}
        cls.content_property = None

    def __init__(
            self,
            default=None,
            optional=False,
            xmlstyle='element',
            xmltagname=None,
            xmlns=None,
            help=None,
            position=None):

        global g_iprop
        if position is not None:
            self.position = position
        else:
            self.position = g_iprop

        g_iprop += 1
        self._default = default

        self.optional = optional
        self.name = None
        self._xmltagname = xmltagname
        self._xmlns = xmlns
        self.parent = None
        self.xmlstyle = xmlstyle
        self.help = help
        self._sphinx_doc_skip = True

    def default(self):
        return make_default(self._default)

    def is_default(self, val):
        if self._default is None:
            return val is None
        else:
            return self._default == val

    def has_default(self):
        return self._default is not None

    def xname(self):
        if self.name is not None:
            return self.name
        elif self.parent is not None:
            return 'element of %s' % self.parent.xname()
        else:
            return '?'

    def set_xmlns(self, xmlns):
        if self._xmlns is None and not self.xmlns:
            self._xmlns = xmlns

        if self.multivalued:
            self.content_t.set_xmlns(xmlns)

    def get_xmlns(self):
        return self._xmlns or self.xmlns

    def get_xmltagname(self):
        if self._xmltagname is not None:
            return self.get_xmlns() + ' ' + self._xmltagname
        elif self.name:
            return self.get_xmlns() + ' ' \
                + make_xmltagname_from_name(self.name)
        elif self.xmltagname:
            return self.get_xmlns() + ' ' + self.xmltagname
        else:
            assert False

    @classmethod
    def get_property(cls, name):
        for prop in cls.properties:
            if prop.name == name:
                return prop

        raise ValueError()

    @classmethod
    def remove_property(cls, name):

        prop = cls.get_property(name)

        if not prop.multivalued:
            del cls.xmltagname_to_class[prop.effective_xmltagname]
            del cls.xmltagname_to_name[prop.effective_xmltagname]
        else:
            del cls.xmltagname_to_class[prop.content_t.effective_xmltagname]
            del cls.xmltagname_to_name_multivalued[
                prop.content_t.effective_xmltagname]

        if cls.content_property is prop:
            cls.content_property = None

        cls.properties.remove(prop)
        cls.propnames.remove(name)

        return prop

    @classmethod
    def add_property(cls, name, prop):

        prop.instance = prop
        prop.name = name
        prop.set_xmlns(cls.xmlns)

        if isinstance(prop, Choice.T):
            for tc in prop.choices:
                tc.effective_xmltagname = tc.get_xmltagname()
                cls.xmltagname_to_class[tc.effective_xmltagname] = tc._cls
                cls.xmltagname_to_name[tc.effective_xmltagname] = prop.name
        elif not prop.multivalued:
            prop.effective_xmltagname = prop.get_xmltagname()
            cls.xmltagname_to_class[prop.effective_xmltagname] = prop._cls
            cls.xmltagname_to_name[prop.effective_xmltagname] = prop.name
        else:
            prop.content_t.name = make_content_name(prop.name)
            prop.content_t.effective_xmltagname = \
                prop.content_t.get_xmltagname()
            cls.xmltagname_to_class[
                prop.content_t.effective_xmltagname] = prop.content_t._cls
            cls.xmltagname_to_name_multivalued[
                prop.content_t.effective_xmltagname] = prop.name

        cls.properties.append(prop)

        cls.properties.sort(key=lambda x: x.position)

        cls.propnames = [p.name for p in cls.properties]

        if prop.xmlstyle == 'content':
            cls.content_property = prop

    @classmethod
    def ivals(cls, val):
        for prop in cls.properties:
            yield getattr(val, prop.name)

    @classmethod
    def ipropvals(cls, val):
        for prop in cls.properties:
            yield prop, getattr(val, prop.name)

    @classmethod
    def inamevals(cls, val):
        for prop in cls.properties:
            yield prop.name, getattr(val, prop.name)

    @classmethod
    def ipropvals_to_save(cls, val, xmlmode=False):
        for prop in cls.properties:
            v = getattr(val, prop.name)
            if v is not None and (
                    not (prop.optional or (prop.multivalued and not v))
                    or (not prop.is_default(v))):

                if xmlmode:
                    yield prop, prop.to_save_xml(v)
                else:
                    yield prop, prop.to_save(v)

    @classmethod
    def inamevals_to_save(cls, val, xmlmode=False):
        for prop, v in cls.ipropvals_to_save(val, xmlmode):
            yield prop.name, v

    @classmethod
    def translate_from_xml(cls, list_of_pairs, strict):
        d = {}
        for k, v in list_of_pairs:
            if k in cls.xmltagname_to_name_multivalued:
                k2 = cls.xmltagname_to_name_multivalued[k]
                if k2 not in d:
                    d[k2] = []

                d[k2].append(v)
            elif k in cls.xmltagname_to_name:
                k2 = cls.xmltagname_to_name[k]
                if k2 in d:
                    raise ArgumentError(
                        'Unexpectedly found more than one child element "%s" '
                        'within "%s".' % (k, cls.tagname))

                d[k2] = v
            elif k is None:
                if cls.content_property:
                    k2 = cls.content_property.name
                    d[k2] = v
            else:
                if strict:
                    raise ArgumentError(
                        'Unexpected child element "%s" found within "%s".' % (
                            k, cls.tagname))

        return d

    def validate(self, val, regularize=False, depth=-1):
        if self.optional and val is None:
            return val

        is_derived = isinstance(val, self._cls)
        is_exact = type(val) is self._cls

        not_ok = not self.strict and not is_derived or \
            self.strict and not is_exact

        if not_ok or self.force_regularize:
            if regularize:
                try:
                    val = self.regularize_extra(val)
                except ValueError:
                    raise ValidationError(
                        '%s: could not convert "%s" to type %s' % (
                            self.xname(), val, classnames(self._cls)))
            else:
                raise ValidationError(
                    '%s: "%s" (type: %s) is not of type %s' % (
                        self.xname(), val, type(val), classnames(self._cls)))

        validator = self
        if isinstance(self._cls, tuple):
            clss = self._cls
        else:
            clss = (self._cls,)

        for cls in clss:
            try:
                if type(val) is not cls and isinstance(val, cls):
                    validator = val.T.instance

            except AttributeError:
                pass

        validator.validate_extra(val)

        if depth != 0:
            val = validator.validate_children(val, regularize, depth)

        return val

    def regularize_extra(self, val):
        return self._cls(val)

    def validate_extra(self, val):
        pass

    def validate_children(self, val, regularize, depth):
        for prop, propval in self.ipropvals(val):
            newpropval = prop.validate(propval, regularize, depth-1)
            if regularize and (newpropval is not propval):
                setattr(val, prop.name, newpropval)

        return val

    def to_save(self, val):
        return val

    def to_save_xml(self, val):
        return self.to_save(val)

    def extend_xmlelements(self, elems, v):
        if self.multivalued:
            for x in v:
                elems.append((self.content_t.effective_xmltagname, x))
        else:
            elems.append((self.effective_xmltagname, v))

    def deferred(self):
        return []

    def classname_for_help(self, strip_module=''):

        if self._dummy_cls is not self._cls:
            if self._dummy_cls.__module__ == strip_module:
                sadd = ' (:py:class:`%s`)' % (
                    self._dummy_cls.__name__)
            else:
                sadd = ' (:py:class:`%s.%s`)' % (
                    self._dummy_cls.__module__, self._dummy_cls.__name__)
        else:
            sadd = ''

        if self._dummy_cls in guts_plain_dummy_types:
            return '``%s``' % self._cls.__name__

        elif self._dummy_cls.dummy_for_description:
            return '%s%s' % (self._dummy_cls.dummy_for_description, sadd)

        else:
            def sclass(cls):
                mod = cls.__module__
                clsn = cls.__name__
                if mod == '__builtin__' or mod == 'builtins':
                    return '``%s``' % clsn

                elif mod == strip_module:
                    return ':py:class:`%s`' % clsn

                else:
                    return ':py:class:`%s.%s`' % (mod, clsn)

            if isinstance(self._cls, tuple):
                return '(%s)%s' % (
                    ' | '.join(sclass(cls) for cls in self._cls), sadd)
            else:
                return '%s%s' % (sclass(self._cls), sadd)

    @classmethod
    def props_help_string(cls):
        baseprops = []
        for base in cls._dummy_cls.__bases__:
            if hasattr(base, 'T'):
                baseprops.extend(base.T.properties)

        hlp = []
        hlp.append('')
        for prop in cls.properties:
            if prop in baseprops:
                continue

            descr = [
                prop.classname_for_help(
                    strip_module=cls._dummy_cls.__module__)]

            if prop.optional:
                descr.append('*optional*')

            if isinstance(prop._default, DefaultMaker):
                descr.append('*default:* ``%s``' % repr(prop._default))
            else:
                d = prop.default()
                if d is not None:
                    descr.append('*default:* ``%s``' % repr(d))

            hlp.append('    .. py:gattribute:: %s' % prop.name)
            hlp.append('')
            hlp.append('      %s' % ', '.join(descr))
            hlp.append('      ')
            if prop.help is not None:
                hlp.append('      %s' % prop.help)
                hlp.append('')

        return '\n'.join(hlp)

    @classmethod
    def class_help_string(cls):
        return cls._dummy_cls.__doc_template__

    @classmethod
    def class_signature(cls):
        r = []
        for prop in cls.properties:
            d = prop.default()
            if d is not None:
                arg = repr(d)

            elif prop.optional:
                arg = 'None'

            else:
                arg = '...'

            r.append('%s=%s' % (prop.name, arg))

        return '(%s)' % ', '.join(r)

    @classmethod
    def help(cls):
        return cls.props_help_string()


class ObjectMetaClass(type):
    def __new__(meta, classname, bases, class_dict):
        classname = class_dict.get('class_name', classname)
        cls = type.__new__(meta, classname, bases, class_dict)
        if classname != 'Object':
            t_class_attr_name = '_%s__T' % classname
            if not hasattr(cls, t_class_attr_name):
                if hasattr(cls, 'T'):
                    class T(cls.T):
                        _sphinx_doc_skip = True

                    T.__doc__ = cls.T.__doc__
                else:
                    class T(TBase):
                        _sphinx_doc_skip = True

                    T.__doc__ = TBase.__doc__

                setattr(cls, t_class_attr_name, T)

            T = getattr(cls, t_class_attr_name)
            T.__name__ = 'T'
            T.__qualname__ = T.__qualname__.replace('__T', 'T')

            if cls.dummy_for is not None:
                T._cls = cls.dummy_for
            else:
                T._cls = cls

            T._dummy_cls = cls

            if hasattr(cls, 'xmltagname'):
                T.xmltagname = cls.xmltagname
            else:
                T.xmltagname = classname

            mod = sys.modules[cls.__module__]

            if hasattr(cls, 'xmlns'):
                T.xmlns = cls.xmlns
            elif hasattr(mod, 'guts_xmlns'):
                T.xmlns = mod.guts_xmlns
            else:
                T.xmlns = ''

            if T.xmlns and hasattr(cls, 'guessable_xmlns'):
                g_guessable_xmlns[T.xmltagname] = cls.guessable_xmlns

            if hasattr(mod, 'guts_prefix'):
                if mod.guts_prefix:
                    T.tagname = mod.guts_prefix + '.' + classname
                else:
                    T.tagname = classname
            else:
                if cls.__module__ != '__main__':
                    T.tagname = cls.__module__ + '.' + classname
                else:
                    T.tagname = classname

            T.classname = classname

            T.init_propertystuff()

            for k in dir(cls):
                prop = getattr(cls, k)

                if k.endswith('__'):
                    k = k[:-2]

                if isinstance(prop, TBase):
                    if prop.deferred():
                        for defer in prop.deferred():
                            g_deferred_content.setdefault(
                                defer.classname[:-2], []).append((prop, defer))
                            g_deferred.setdefault(
                                defer.classname[:-2], []).append((T, k, prop))

                    else:
                        T.add_property(k, prop)

                elif isinstance(prop, Defer):
                    g_deferred.setdefault(prop.classname[:-2], []).append(
                        (T, k, prop))

            if classname in g_deferred_content:
                for prop, defer in g_deferred_content[classname]:
                    prop.process_deferred(
                        defer, T(*defer.args, **defer.kwargs))

                del g_deferred_content[classname]

            if classname in g_deferred:
                for (T_, k_, prop_) in g_deferred.get(classname, []):
                    if isinstance(prop_, Defer):
                        prop_ = T(*prop_.args, **prop_.kwargs)

                    if not prop_.deferred():
                        T_.add_property(k_, prop_)

                del g_deferred[classname]

            g_tagname_to_class[T.tagname] = cls
            if hasattr(cls, 'xmltagname'):
                g_xmltagname_to_class[T.xmlns + ' ' + T.xmltagname] = cls

            cls.T = T
            T.instance = T()

            cls.__doc_template__ = cls.__doc__
            cls.__doc__ = T.class_help_string()

            if cls.__doc__ is None:
                cls.__doc__ = 'Undocumented.'

            cls.__doc__ += '\n' + T.props_help_string()

        return cls


class ValidationError(ValueError):
    '''
    Raised when an object is invalid according to its definition.
    '''
    pass


class ArgumentError(ValueError):
    '''
    Raised when invalid arguments would be used in an object's initialization.
    '''
    pass


def make_default(x):
    if isinstance(x, DefaultMaker):
        return x.make()
    elif isinstance(x, Object):
        return clone(x)
    else:
        return x


class DefaultMaker(object):
    '''
    Base class for default value factories.
    '''
    def make(self):
        '''
        Create a new object.
        '''
        raise NotImplementedError


class ObjectDefaultMaker(DefaultMaker):
    '''
    Default value factory for :py:class:`Object` derived classes.
    '''
    def __init__(self, cls, args, kwargs):
        DefaultMaker.__init__(self)
        self._cls = cls
        self.args = args
        self.kwargs = kwargs
        self.instance = None

    def make(self):
        return self._cls(
            *[make_default(x) for x in self.args],
            **dict((k, make_default(v)) for (k, v) in self.kwargs.items()))

    def __eq__(self, other):
        if self.instance is None:
            self.instance = self.make()

        return self.instance == other

    def __repr__(self):
        sargs = []
        for arg in self.args:
            sargs.append(repr(arg))

        for k, v in self.kwargs.items():
            sargs.append(
                '%s=%s' % (
                    k,
                    ' '.join(line.strip() for line in repr(v).splitlines())))

        return '%s(%s)' % (self._cls.__name__, ', '.join(sargs))


class TimestampDefaultMaker(DefaultMaker):
    def __init__(self, s, format='%Y-%m-%d %H:%M:%S.OPTFRAC'):
        DefaultMaker.__init__(self)
        self._stime = s
        self._format = format

    def make(self):
        return str_to_time(self._stime, self._format)

    def __repr__(self):
        return 'str_to_time(%s)' % repr(self._stime)


def with_metaclass(meta, *bases):
    # inlined py2/py3 compat solution from python-future
    class metaclass(meta):
        __call__ = type.__call__
        __init__ = type.__init__

        def __new__(cls, name, this_bases, d):
            if this_bases is None:
                return type.__new__(cls, name, (), d)
            return meta(name, bases, d)

    return metaclass('temp', None, {})


class Object(with_metaclass(ObjectMetaClass, object)):
    '''
    Base class for Guts objects.

    :cvar dummy_for:
        (class variable) If set, this indicates that the containing class is a
        dummy for another type. This can be used to hold native Python objects
        and non-Guts based objects as children of a Guts object.
    :cvar dummy_for_description:
        (class variable) Overrides the name shown in the "dummy for ..."
        documentation strings.
    '''

    dummy_for = None
    dummy_for_description = None

    def __init__(self, **kwargs):
        if not kwargs.get('init_props', True):
            return

        for prop in self.T.properties:
            k = prop.name
            if k in kwargs:
                setattr(self, k, kwargs.pop(k))
            else:
                if not prop.optional and not prop.has_default():
                    raise ArgumentError('Missing argument to %s: %s' % (
                        self.T.tagname, prop.name))
                else:
                    setattr(self, k, prop.default())

        if kwargs:
            raise ArgumentError('Invalid argument to %s: %s' % (
                self.T.tagname, ', '.join(list(kwargs.keys()))))

        self.post_init()

    def post_init(self):
        pass

    @classmethod
    def D(cls, *args, **kwargs):
        '''
        Get a default value factory for this class, configured with
        specified arguments.

        :returns:
            Factory for default values.
        :rtype:
            :py:class:`ObjectDefaultMaker` object
        '''
        return ObjectDefaultMaker(cls, args, kwargs)

    def validate(self, regularize=False, depth=-1):
        '''
        Validate this object.

        Raises :py:class:`ValidationError` when the object is invalid.

        :param depth:
            Maximum depth to descend into child objects.
        :type depth:
            int
        '''
        self.T.instance.validate(self, regularize, depth)

    def regularize(self, depth=-1):
        '''
        Regularize this object.

        Regularization tries to convert child objects of invalid types to the
        expected types.

        Raises :py:class:`ValidationError` when the object is invalid and
        cannot be regularized.

        :param depth:
            Maximum depth to descend into child objects.
        :type depth:
            int
        '''
        self.validate(regularize=True, depth=depth)

    def dump(self, stream=None, filename=None, header=False):
        '''
        Serialize to YAML.

        If neither ``stream`` nor ``filename`` is set, a string containing the
        serialized data is returned.

        :param stream:
            Output to stream.

        :param filename:
            Output to file of given name.
        :type filename:
            str

        :param header:
            File header to prepend to the output.
        :type header:
            str
        '''
        return dump(self, stream=stream, filename=filename, header=header)

    def dump_xml(
            self, stream=None, filename=None, header=False, ns_ignore=False):
        '''
        Serialize to XML.

        If neither ``stream`` nor ``filename`` is set, a string containing the
        serialized data is returned.

        :param stream:
            Output to stream.

        :param filename:
            Output to file of given name.
        :type filename:
            str

        :param header:
            File header to prepend to the output.
        :type header:
            str

        :param ns_ignore:
            Whether to ignore the XML namespace.
        :type ns_ignore:
            bool
        '''
        return dump_xml(
            self, stream=stream, filename=filename, header=header,
            ns_ignore=ns_ignore)

    @classmethod
    def load(cls, stream=None, filename=None, string=None):
        '''
        Deserialize from YAML.

        :param stream:
            Read input from stream.

        :param filename:
            Read input from file of given name.
        :type filename:
            str

        :param string:
            Read input from string.
        :type string:
            str
        '''
        return load(stream=stream, filename=filename, string=string)

    @classmethod
    def load_xml(cls, stream=None, filename=None, string=None, ns_hints=None,
                 ns_ignore=False):
        '''
        Deserialize from XML.

        :param stream:
            Read input from stream.

        :param filename:
            Read input from file of given name.
        :type filename:
            str

        :param string:
            Read input from string.
        :type string:
            str
        '''

        if ns_hints is None:
            ns_hints = [cls.T.instance.get_xmlns()]

        return load_xml(
            stream=stream,
            filename=filename,
            string=string,
            ns_hints=ns_hints,
            ns_ignore=ns_ignore)

    def __str__(self):
        return self.dump()


def to_dict(obj):
    '''
    Get dict of guts object attributes.

    :param obj: :py:class`Object` object
    '''

    return dict(obj.T.inamevals(obj))


class SObject(Object):
    '''
    Base class for simple str-serializable Guts objects.

    Derived classes must support (de)serialization as in ``X(str(x))``.
    '''

    class __T(TBase):
        def regularize_extra(self, val):
            if isinstance(val, str):
                return self._cls(val)

            return val

        def to_save(self, val):
            return str(val)

        def to_save_xml(self, val):
            return str(val)


class Any(Object):
    '''
    Placeholder for any object.
    '''

    class __T(TBase):
        def validate(self, val, regularize=False, depth=-1):
            if isinstance(val, Object):
                val.validate(regularize, depth)

            return val


class Int(Object):
    '''
    Placeholder for :py:class:`int`.
    '''
    dummy_for = int

    class __T(TBase):
        strict = True

        def to_save_xml(self, value):
            return repr(value)


class Float(Object):
    '''
    Placeholder for :py:class:`float`.
    '''
    dummy_for = float

    class __T(TBase):
        strict = True

        def to_save_xml(self, value):
            return repr(value)


class Complex(Object):
    '''
    Placeholder for :py:class:`complex`.
    '''
    dummy_for = complex

    class __T(TBase):
        strict = True

        def regularize_extra(self, val):

            if isinstance(val, list) or isinstance(val, tuple):
                assert len(val) == 2
                val = complex(*val)

            elif not isinstance(val, complex):
                val = complex(val)

            return val

        def to_save(self, value):
            return repr(value)

        def to_save_xml(self, value):
            return repr(value)


class Bool(Object):
    '''
    Placeholder for :py:class:`bool`.
    '''
    dummy_for = bool

    class __T(TBase):
        strict = True

        def regularize_extra(self, val):
            if isinstance(val, str):
                if val.lower().strip() in ('0', 'false'):
                    return False

            return bool(val)

        def to_save_xml(self, value):
            return repr(bool(value)).lower()


class String(Object):
    '''
    Placeholder for :py:class:`str`.
    '''
    dummy_for = str

    class __T(TBase):
        def __init__(self, *args, yamlstyle=None, **kwargs):
            TBase.__init__(self, *args, **kwargs)
            self.style_cls = str_style_map[yamlstyle]

        def to_save(self, val):
            return self.style_cls(val)


class Bytes(Object):
    '''
    Placeholder for :py:class:`bytes`.
    '''
    dummy_for = bytes

    class __T(TBase):

        def regularize_extra(self, val):
            if isinstance(val, str):
                val = b64decode(val)

            return val

        def to_save(self, val):
            return literal(b64encode(val).decode('utf-8'))


class Unicode(Object):
    '''
    Placeholder for :py:class:`str`.
    '''
    dummy_for = str

    class __T(TBase):
        def __init__(self, *args, yamlstyle=None, **kwargs):
            TBase.__init__(self, *args, **kwargs)
            self.style_cls = unicode_style_map[yamlstyle]

        def to_save(self, val):
            return self.style_cls(val)


guts_plain_dummy_types = (String, Unicode, Int, Float, Complex, Bool)


class Dict(Object):
    '''
    Placeholder for :py:class:`dict`.
    '''
    dummy_for = dict

    class __T(TBase):
        multivalued = dict

        def __init__(self, key_t=Any.T(), content_t=Any.T(), *args, **kwargs):
            TBase.__init__(self, *args, **kwargs)
            assert isinstance(key_t, TBase)
            assert isinstance(content_t, TBase)
            self.key_t = key_t
            self.content_t = content_t
            self.content_t.parent = self

        def default(self):
            if self._default is not None:
                return dict(
                    (make_default(k), make_default(v))
                    for (k, v) in self._default.items())

            if self.optional:
                return None
            else:
                return {}

        def has_default(self):
            return True

        def validate(self, val, regularize, depth):
            return TBase.validate(self, val, regularize, depth+1)

        def validate_children(self, val, regularize, depth):
            for key, ele in list(val.items()):
                newkey = self.key_t.validate(key, regularize, depth-1)
                newele = self.content_t.validate(ele, regularize, depth-1)
                if regularize:
                    if newkey is not key or newele is not ele:
                        del val[key]
                        val[newkey] = newele

            return val

        def to_save(self, val):
            return dict((self.key_t.to_save(k), self.content_t.to_save(v))
                        for (k, v) in val.items())

        def to_save_xml(self, val):
            raise NotImplementedError

        def classname_for_help(self, strip_module=''):
            return '``dict`` of %s objects' % \
                self.content_t.classname_for_help(strip_module=strip_module)


class List(Object):
    '''
    Placeholder for :py:class:`list`.
    '''
    dummy_for = list

    class __T(TBase):
        multivalued = list

        def __init__(self, content_t=Any.T(), *args, yamlstyle=None, **kwargs):
            TBase.__init__(self, *args, **kwargs)
            assert isinstance(content_t, TBase) or isinstance(content_t, Defer)
            self.content_t = content_t
            self.content_t.parent = self
            self.style_cls = list_style_map[yamlstyle]

        def default(self):
            if self._default is not None:
                return [make_default(x) for x in self._default]
            if self.optional:
                return None
            else:
                return []

        def has_default(self):
            return True

        def validate(self, val, regularize, depth):
            return TBase.validate(self, val, regularize, depth+1)

        def validate_children(self, val, regularize, depth):
            for i, ele in enumerate(val):
                newele = self.content_t.validate(ele, regularize, depth-1)
                if regularize and newele is not ele:
                    val[i] = newele

            return val

        def to_save(self, val):
            return self.style_cls(self.content_t.to_save(v) for v in val)

        def to_save_xml(self, val):
            return [self.content_t.to_save_xml(v) for v in val]

        def deferred(self):
            if isinstance(self.content_t, Defer):
                return [self.content_t]

            return []

        def process_deferred(self, defer, t_inst):
            if defer is self.content_t:
                self.content_t = t_inst

        def classname_for_help(self, strip_module=''):
            return '``list`` of %s objects' % \
                self.content_t.classname_for_help(strip_module=strip_module)


def make_typed_list_class(t):
    class TL(List):
        class __T(List.T):
            def __init__(self, *args, **kwargs):
                List.T.__init__(self, content_t=t.T(), *args, **kwargs)

    return TL


class Tuple(Object):
    '''
    Placeholder for :py:class:`tuple`.
    '''
    dummy_for = tuple

    class __T(TBase):
        multivalued = tuple

        def __init__(self, n=None, content_t=Any.T(), *args, **kwargs):
            TBase.__init__(self, *args, **kwargs)
            assert isinstance(content_t, TBase)
            self.content_t = content_t
            self.content_t.parent = self
            self.n = n

        def default(self):
            if self._default is not None:
                return tuple(
                    make_default(x) for x in self._default)

            elif self.optional:
                return None
            else:
                if self.n is not None:
                    return tuple(
                        self.content_t.default() for x in range(self.n))
                else:
                    return tuple()

        def has_default(self):
            return True

        def validate(self, val, regularize, depth):
            return TBase.validate(self, val, regularize, depth+1)

        def validate_extra(self, val):
            if self.n is not None and len(val) != self.n:
                raise ValidationError(
                    '%s should have length %i' % (self.xname(), self.n))

        def validate_children(self, val, regularize, depth):
            if not regularize:
                for ele in val:
                    self.content_t.validate(ele, regularize, depth-1)

                return val
            else:
                newval = []
                isnew = False
                for ele in val:
                    newele = self.content_t.validate(ele, regularize, depth-1)
                    newval.append(newele)
                    if newele is not ele:
                        isnew = True

                if isnew:
                    return tuple(newval)
                else:
                    return val

        def to_save(self, val):
            return tuple(self.content_t.to_save(v) for v in val)

        def to_save_xml(self, val):
            return [self.content_t.to_save_xml(v) for v in val]

        def classname_for_help(self, strip_module=''):
            if self.n is not None:
                return '``tuple`` of %i %s objects' % (
                    self.n, self.content_t.classname_for_help(
                        strip_module=strip_module))
            else:
                return '``tuple`` of %s objects' % (
                    self.content_t.classname_for_help(
                        strip_module=strip_module))


duration_unit_factors = dict(
    s=1.0,
    m=60.0,
    h=3600.0,
    d=24*3600.0,
    y=365*24*3600.0)


def parse_duration(s):
    unit = s[-1]
    if unit in duration_unit_factors:
        return float(s[:-1]) * duration_unit_factors[unit]
    else:
        return float(s)


def str_duration(d):
    for k in 'ydhms':
        if abs(d) >= duration_unit_factors[k]:
            return '%g' % (d / duration_unit_factors[k]) + k

    return '%g' % d


class Duration(Object):
    '''
    Placeholder for :py:class:`float` time duration [s] with human-readable
    (de)serialization.

    Examples:

    - ``'1s'`` -> 1 second
    - ``'1m'`` -> 1 minute
    - ``'1h'`` -> 1 hour
    - ``'1d'`` -> 1 day
    - ``'1y'`` -> about 1 year = 365*24*3600 seconds
    '''
    dummy_for = float

    class __T(TBase):
        def regularize_extra(self, val):
            if isinstance(val, str):
                return parse_duration(val)

            return val

        def to_save(self, val):
            return str_duration(val)

        def to_save_xml(self, val):
            return str_duration(val)


re_tz = re.compile(r'(Z|([+-][0-2][0-9])(:?([0-5][0-9]))?)$')


class Timestamp(Object):
    '''
    Placeholder for a UTC timestamp.
    '''
    dummy_for = (hpfloat, float)
    dummy_for_description = 'pyrocko.util.get_time_float'

    class __T(TBase):

        def regularize_extra(self, val):

            time_float = get_time_float()

            if isinstance(val, datetime.datetime):
                tt = val.utctimetuple()
                val = time_float(calendar.timegm(tt)) + val.microsecond * 1e-6

            elif isinstance(val, datetime.date):
                tt = val.timetuple()
                val = time_float(calendar.timegm(tt))

            elif isinstance(val, str):
                val = val.strip()
                tz_offset = 0

                m = re_tz.search(val)
                if m:
                    sh = m.group(2)
                    sm = m.group(4)
                    tz_offset = (int(sh)*3600 if sh else 0) \
                        + (int(sm)*60 if sm else 0)

                    val = re_tz.sub('', val)

                if len(val) > 10 and val[10] == 'T':
                    val = val.replace('T', ' ', 1)

                try:
                    val = str_to_time(val) - tz_offset
                except TimeStrError:
                    raise ValidationError(
                        '%s: cannot parse time/date: %s' % (self.xname(), val))

            elif isinstance(val, (int, float)):
                val = time_float(val)

            else:
                raise ValidationError(
                    '%s: cannot convert "%s" to type %s' % (
                        self.xname(), val, time_float))

            return val

        def to_save(self, val):
            return time_to_str(val, format='%Y-%m-%d %H:%M:%S.9FRAC')\
                .rstrip('0').rstrip('.')

        def to_save_xml(self, val):
            return time_to_str(val, format='%Y-%m-%dT%H:%M:%S.9FRAC')\
                .rstrip('0').rstrip('.') + 'Z'

    @classmethod
    def D(self, s):
        return TimestampDefaultMaker(s)


class DateTimestamp(Object):
    '''
    Placeholder for a UTC timestamp which (de)serializes as a date string.
    '''
    dummy_for = (hpfloat, float)
    dummy_for_description = 'pyrocko.util.get_time_float'

    class __T(TBase):

        def regularize_extra(self, val):

            time_float = get_time_float()

            if isinstance(val, datetime.datetime):
                tt = val.utctimetuple()
                val = time_float(calendar.timegm(tt)) + val.microsecond * 1e-6

            elif isinstance(val, datetime.date):
                tt = val.timetuple()
                val = time_float(calendar.timegm(tt))

            elif isinstance(val, str):
                val = str_to_time(val, format='%Y-%m-%d')

            elif isinstance(val, int):
                val = time_float(val)

            return val

        def to_save(self, val):
            return time_to_str(val, format='%Y-%m-%d')

        def to_save_xml(self, val):
            return time_to_str(val, format='%Y-%m-%d')

    @classmethod
    def D(self, s):
        return TimestampDefaultMaker(s, format='%Y-%m-%d')


class StringPattern(String):

    '''
    Any :py:class:`str` matching pattern ``%(pattern)s``.
    '''

    dummy_for = str
    pattern = '.*'

    class __T(String.T):
        def __init__(self, pattern=None, *args, **kwargs):
            String.T.__init__(self, *args, **kwargs)

            if pattern is not None:
                self.pattern = pattern
            else:
                self.pattern = self._dummy_cls.pattern

        def validate_extra(self, val):
            pat = self.pattern
            if not re.search(pat, val):
                raise ValidationError('%s: "%s" does not match pattern %s' % (
                    self.xname(), val, repr(pat)))

        @classmethod
        def class_help_string(cls):
            dcls = cls._dummy_cls
            doc = dcls.__doc_template__ or StringPattern.__doc_template__
            return doc % {'pattern': repr(dcls.pattern)}


class UnicodePattern(Unicode):

    '''
    Any :py:class:`str` matching pattern ``%(pattern)s``.
    '''

    dummy_for = str
    pattern = '.*'

    class __T(TBase):
        def __init__(self, pattern=None, *args, **kwargs):
            TBase.__init__(self, *args, **kwargs)

            if pattern is not None:
                self.pattern = pattern
            else:
                self.pattern = self._dummy_cls.pattern

        def validate_extra(self, val):
            pat = self.pattern
            if not re.search(pat, val, flags=re.UNICODE):
                raise ValidationError('%s: "%s" does not match pattern %s' % (
                    self.xname(), val, repr(pat)))

        @classmethod
        def class_help_string(cls):
            dcls = cls._dummy_cls
            doc = dcls.__doc_template__ or UnicodePattern.__doc_template__
            return doc % {'pattern': repr(dcls.pattern)}


class StringChoice(String):

    '''
    Any :py:class:`str` out of ``%(choices)s``.

    :cvar choices:
        Allowed choices (:py:class:`list` of :py:class:`str`).
    :cvar ignore_case:
        Whether to behave case-insensitive (:py:class:`bool`, default:
        ``False``).
    '''

    dummy_for = str
    choices = []
    ignore_case = False

    class __T(String.T):
        def __init__(self, choices=None, ignore_case=None, *args, **kwargs):
            String.T.__init__(self, *args, **kwargs)

            if choices is not None:
                self.choices = choices
            else:
                self.choices = self._dummy_cls.choices

            if ignore_case is not None:
                self.ignore_case = ignore_case
            else:
                self.ignore_case = self._dummy_cls.ignore_case

            if self.ignore_case:
                self.choices = [x.upper() for x in self.choices]

        def validate_extra(self, val):
            if self.ignore_case:
                val = val.upper()

            if val not in self.choices:
                raise ValidationError(
                    '%s: "%s" is not a valid choice out of %s' % (
                        self.xname(), val, repr(self.choices)))

        @classmethod
        def class_help_string(cls):
            dcls = cls._dummy_cls
            doc = dcls.__doc_template__ or StringChoice.__doc_template__
            return doc % {'choices': repr(dcls.choices)}


class IntChoice(Int):

    '''
    Any :py:class:`int` out of ``%(choices)s``.
    '''

    dummy_for = int
    choices = []

    class __T(Int.T):
        def __init__(self, choices=None, *args, **kwargs):
            Int.T.__init__(self, *args, **kwargs)

            if choices is not None:
                self.choices = choices
            else:
                self.choices = self._dummy_cls.choices

        def validate_extra(self, val):
            if val not in self.choices:
                raise ValidationError(
                    '%s: %i is not a valid choice out of %s' % (
                        self.xname(), val, repr(self.choices)))

        @classmethod
        def class_help_string(cls):
            dcls = cls._dummy_cls
            doc = dcls.__doc_template__ or IntChoice.__doc_template__
            return doc % {'choices': repr(dcls.choices)}


# this will not always work...
class StringUnion(Object):
    '''
    Any :py:class:`str` matching any of a set of constraints.

    :cvar members:
        List of constraints, e.g. :py:class:`StringChoice`,
        :py:class:`StringPattern`, ... (:py:class:`list` of :py:class:`TBase`
        derived objects).

    '''

    members = []

    dummy_for = str

    class __T(TBase):
        def __init__(self, members=None, *args, **kwargs):
            TBase.__init__(self, *args, **kwargs)
            if members is not None:
                self.members = members
            else:
                self.members = self._dummy_cls.members

        def validate(self, val, regularize=False, depth=-1):
            assert self.members
            e2 = None
            for member in self.members:
                try:
                    return member.validate(val, regularize, depth=depth)
                except ValidationError as e:
                    e2 = e

            raise e2


class Choice(Object):
    '''
    Any out of a set of different types.

    :cvar choices:
        Allowed types (:py:class:`list` of :py:class:`TBase` derived objects).

    '''
    choices = []

    class __T(TBase):
        def __init__(self, choices=None, *args, **kwargs):
            TBase.__init__(self, *args, **kwargs)
            if choices is not None:
                self.choices = choices
            else:
                self.choices = self._dummy_cls.choices

            self.cls_to_xmltagname = dict(
                (t._cls, t.get_xmltagname()) for t in self.choices)

        def validate(self, val, regularize=False, depth=-1):
            if self.optional and val is None:
                return val

            t = None
            for tc in self.choices:
                is_derived = isinstance(val, tc._cls)
                is_exact = type(val) is tc._cls
                if not (not tc.strict and not is_derived or
                        tc.strict and not is_exact):

                    t = tc
                    break

            if t is None:
                if regularize:
                    ok = False
                    for tc in self.choices:
                        try:
                            val = tc.regularize_extra(val)
                            ok = True
                            t = tc
                            break
                        except (ValidationError, ValueError):
                            pass

                    if not ok:
                        raise ValidationError(
                            '%s: could not convert "%s" to any type out of '
                            '(%s)' % (self.xname(), val, ','.join(
                                classnames(x._cls) for x in self.choices)))
                else:
                    raise ValidationError(
                        '%s: "%s" (type: %s) is not of any type out of '
                        '(%s)' % (self.xname(), val, type(val), ','.join(
                            classnames(x._cls) for x in self.choices)))

            validator = t

            if isinstance(t._cls, tuple):
                clss = t._cls
            else:
                clss = (t._cls,)

            for cls in clss:
                try:
                    if type(val) is not cls and isinstance(val, cls):
                        validator = val.T.instance

                except AttributeError:
                    pass

            validator.validate_extra(val)

            if depth != 0:
                val = validator.validate_children(val, regularize, depth)

            return val

        def extend_xmlelements(self, elems, v):
            elems.append((
                self.cls_to_xmltagname[type(v)].split(' ', 1)[-1], v))


def _dump(
        object, stream,
        header=False,
        Dumper=GutsSafeDumper,
        _dump_function=yaml.dump):

    if not getattr(stream, 'encoding', None):
        enc = encode_utf8
    else:
        enc = no_encode

    if header:
        stream.write(enc(u'%YAML 1.1\n'))
        if isinstance(header, str):
            banner = u'\n'.join('# ' + x for x in header.splitlines()) + '\n'
            stream.write(enc(banner))

    _dump_function(
        object,
        stream=stream,
        encoding='utf-8',
        explicit_start=True,
        Dumper=Dumper)


def _dump_all(object, stream, header=True, Dumper=GutsSafeDumper):
    _dump(object, stream=stream, header=header, _dump_function=yaml.dump_all)


def _load(stream,
          Loader=GutsSafeLoader, allow_include=None, filename=None,
          included_files=None):

    class _Loader(Loader):
        _filename = filename
        _allow_include = allow_include
        _included_files = included_files or []

    return yaml.load(stream=stream, Loader=_Loader)


def _load_all(stream,
              Loader=GutsSafeLoader, allow_include=None, filename=None):

    class _Loader(Loader):
        _filename = filename
        _allow_include = allow_include

    return list(yaml.load_all(stream=stream, Loader=_Loader))


def _iload_all(stream,
               Loader=GutsSafeLoader, allow_include=None, filename=None):

    class _Loader(Loader):
        _filename = filename
        _allow_include = allow_include

    return yaml.load_all(stream=stream, Loader=_Loader)


def multi_representer(dumper, data):
    node = dumper.represent_mapping(
        '!'+data.T.tagname, data.T.inamevals_to_save(data), flow_style=False)

    return node


# hack for compatibility with early GF Store versions
re_compatibility = re.compile(
    r'^pyrocko\.(trace|gf\.(meta|seismosizer)|fomosto\.'
    r'(dummy|poel|qseis|qssp))\.'
)


def multi_constructor(loader, tag_suffix, node):
    tagname = str(tag_suffix)

    tagname = re_compatibility.sub('pf.', tagname)

    cls = g_tagname_to_class[tagname]
    kwargs = dict(iter(loader.construct_pairs(node, deep=True)))
    o = cls(**kwargs)
    o.validate(regularize=True, depth=1)
    return o


def include_constructor(loader, node):
    allow_include = loader._allow_include \
        if loader._allow_include is not None \
        else ALLOW_INCLUDE

    if not allow_include:
        raise EnvironmentError(
            'Not allowed to include YAML. Load with allow_include=True')

    if isinstance(node, yaml.nodes.ScalarNode):
        inc_file = loader.construct_scalar(node)
    else:
        raise TypeError('Unsupported YAML node %s' % repr(node))

    if loader._filename is not None and not op.isabs(inc_file):
        inc_file = op.join(op.dirname(loader._filename), inc_file)

    if not op.isfile(inc_file):
        raise FileNotFoundError(inc_file)

    included_files = list(loader._included_files)
    if loader._filename is not None:
        included_files.append(op.abspath(loader._filename))

    for included_file in loader._included_files:
        if op.samefile(inc_file, included_file):
            raise ImportError(
                'Circular import of file "%s". Include path: %s' % (
                    op.abspath(inc_file),
                    ' -> '.join('"%s"' % s for s in included_files)))

    with open(inc_file, 'rb') as f:
        return _load(
            f,
            Loader=loader.__class__, filename=inc_file,
            allow_include=True,
            included_files=included_files)


def dict_noflow_representer(dumper, data):
    return dumper.represent_mapping(
        'tag:yaml.org,2002:map', data, flow_style=False)


yaml.add_multi_representer(Object, multi_representer, Dumper=GutsSafeDumper)
yaml.add_constructor('!include', include_constructor, Loader=GutsSafeLoader)
yaml.add_multi_constructor('!', multi_constructor, Loader=GutsSafeLoader)
yaml.add_representer(dict, dict_noflow_representer, Dumper=GutsSafeDumper)


def str_representer(dumper, data):
    return dumper.represent_scalar(
        'tag:yaml.org,2002:str', str(data))


yaml.add_representer(str, str_representer, Dumper=GutsSafeDumper)


class Constructor(object):
    def __init__(self, add_namespace_maps=False, strict=False, ns_hints=None,
                 ns_ignore=False):

        self.stack = []
        self.queue = []
        self.namespaces = defaultdict(list)
        self.add_namespace_maps = add_namespace_maps
        self.strict = strict
        self.ns_hints = ns_hints
        self.ns_ignore = ns_ignore

    def start_element(self, ns_name, attrs):
        if self.ns_ignore:
            ns_name = ns_name.split(' ')[-1]

        if -1 == ns_name.find(' '):
            if self.ns_hints is None and ns_name in g_guessable_xmlns:
                self.ns_hints = g_guessable_xmlns[ns_name]

            if self.ns_hints:
                ns_names = [
                    ns_hint + ' ' + ns_name for ns_hint in self.ns_hints]

            elif self.ns_hints is None:
                ns_names = [' ' + ns_name]

        else:
            ns_names = [ns_name]

        for ns_name in ns_names:
            if self.stack and self.stack[-1][1] is not None:
                cls = self.stack[-1][1].T.xmltagname_to_class.get(
                    ns_name, None)

                if isinstance(cls, tuple):
                    cls = None
                else:
                    if cls is not None and (
                            not issubclass(cls, Object)
                            or issubclass(cls, SObject)):
                        cls = None
            else:
                cls = g_xmltagname_to_class.get(ns_name, None)

            if cls:
                break

        self.stack.append((ns_name, cls, attrs, [], []))

    def end_element(self, _):
        ns_name, cls, attrs, content2, content1 = self.stack.pop()

        ns = ns_name.split(' ', 1)[0]

        if cls is not None:
            content2.extend(
                (ns + ' ' + k if -1 == k.find(' ') else k, v)
                for (k, v) in attrs.items())
            content2.append((None, ''.join(content1)))
            o = cls(**cls.T.translate_from_xml(content2, self.strict))
            o.validate(regularize=True, depth=1)
            if self.add_namespace_maps:
                o.namespace_map = self.get_current_namespace_map()

            if self.stack and not all(x[1] is None for x in self.stack):
                self.stack[-1][-2].append((ns_name, o))
            else:
                self.queue.append(o)
        else:
            content = [''.join(content1)]
            if self.stack:
                for c in content:
                    self.stack[-1][-2].append((ns_name, c))

    def characters(self, char_content):
        if self.stack:
            self.stack[-1][-1].append(char_content)

    def start_namespace(self, ns, uri):
        self.namespaces[ns].append(uri)

    def end_namespace(self, ns):
        self.namespaces[ns].pop()

    def get_current_namespace_map(self):
        return dict((k, v[-1]) for (k, v) in self.namespaces.items() if v)

    def get_queued_elements(self):
        queue = self.queue
        self.queue = []
        return queue


def _iload_all_xml(
        stream,
        bufsize=100000,
        add_namespace_maps=False,
        strict=False,
        ns_hints=None,
        ns_ignore=False):

    from xml.parsers.expat import ParserCreate
    from pyrocko import progress

    parser = ParserCreate('UTF-8', namespace_separator=' ')

    handler = Constructor(
        add_namespace_maps=add_namespace_maps,
        strict=strict,
        ns_hints=ns_hints,
        ns_ignore=ns_ignore)

    parser.StartElementHandler = handler.start_element
    parser.EndElementHandler = handler.end_element
    parser.CharacterDataHandler = handler.characters
    parser.StartNamespaceDeclHandler = handler.start_namespace
    parser.EndNamespaceDeclHandler = handler.end_namespace

    try:
        nbytes = os.fstat(stream.fileno()).st_size - stream.tell()
    except Exception:
        nbytes = None

    ibytes = 0
    task = progress.task('Parsing XML', nbytes, logger=logger)
    try:
        while True:
            data = stream.read(bufsize)
            ibytes += len(data)
            parser.Parse(data, bool(not data))
            for element in handler.get_queued_elements():
                yield element

            task.update(ibytes)

            if not data:
                break

    except Exception:
        task.fail()
        raise

    finally:
        task.done()


def _load_all_xml(*args, **kwargs):
    return list(_iload_all_xml(*args, **kwargs))


def _load_xml(*args, **kwargs):
    g = _iload_all_xml(*args, **kwargs)
    return next(g)


def _dump_all_xml(objects, stream, root_element_name='root', header=True):

    if not getattr(stream, 'encoding', None):
        enc = encode_utf8
    else:
        enc = no_encode

    _dump_xml_header(stream, header)

    beg = u'<%s>\n' % root_element_name
    end = u'</%s>\n' % root_element_name

    stream.write(enc(beg))

    for ob in objects:
        _dump_xml(ob, stream=stream)

    stream.write(enc(end))


def _dump_xml_header(stream, banner=None):

    if not getattr(stream, 'encoding', None):
        enc = encode_utf8
    else:
        enc = no_encode

    stream.write(enc(u'<?xml version="1.0" encoding="UTF-8" ?>\n'))
    if isinstance(banner, str):
        stream.write(enc(u'<!-- %s -->\n' % banner))


def _dump_xml(
        obj, stream, depth=0, ns_name=None, header=False, ns_map=[],
        ns_ignore=False):

    from xml.sax.saxutils import escape, quoteattr

    if not getattr(stream, 'encoding', None):
        enc = encode_utf8
    else:
        enc = no_encode

    if depth == 0 and header:
        _dump_xml_header(stream, header)

    indent = ' '*depth*2
    if ns_name is None:
        ns_name = obj.T.instance.get_xmltagname()

    if -1 != ns_name.find(' '):
        ns, name = ns_name.split(' ')
    else:
        ns, name = '', ns_name

    if isinstance(obj, Object):
        obj.validate(depth=1)
        attrs = []
        elems = []

        added_ns = False
        if not ns_ignore and ns and (not ns_map or ns_map[-1] != ns):
            attrs.append(('xmlns', ns))
            ns_map.append(ns)
            added_ns = True

        for prop, v in obj.T.ipropvals_to_save(obj, xmlmode=True):
            if prop.xmlstyle == 'attribute':
                assert not prop.multivalued
                assert not isinstance(v, Object)
                attrs.append((prop.effective_xmltagname, v))

            elif prop.xmlstyle == 'content':
                assert not prop.multivalued
                assert not isinstance(v, Object)
                elems.append((None, v))

            else:
                prop.extend_xmlelements(elems, v)

        attr_str = ''
        if attrs:
            attr_str = ' ' + ' '.join(
                '%s=%s' % (k.split(' ')[-1], quoteattr(str(v)))
                for (k, v) in attrs)

        if not elems:
            stream.write(enc(u'%s<%s%s />\n' % (indent, name, attr_str)))
        else:
            oneline = len(elems) == 1 and elems[0][0] is None
            stream.write(enc(u'%s<%s%s>%s' % (
                indent,
                name,
                attr_str,
                '' if oneline else '\n')))

            for (k, v) in elems:
                if k is None:
                    stream.write(enc(escape(str(v), {'\0': '&#00;'})))
                else:
                    _dump_xml(v, stream,  depth+1, k, False, ns_map, ns_ignore)

            stream.write(enc(u'%s</%s>\n' % (
                '' if oneline else indent, name)))

        if added_ns:
            ns_map.pop()

    else:
        stream.write(enc(u'%s<%s>%s</%s>\n' % (
            indent,
            name,
            escape(str(obj), {'\0': '&#00;'}),
            name)))


def walk(x, typ=None, path=()):
    if typ is None or isinstance(x, typ):
        yield path, x

    if isinstance(x, Object):
        for (prop, val) in x.T.ipropvals(x):
            if prop.multivalued:
                if val is not None:
                    for iele, ele in enumerate(val):
                        for y in walk(ele, typ,
                                      path=path + ((prop.name, iele),)):
                            yield y
            else:
                for y in walk(val, typ, path=path+(prop.name,)):
                    yield y


def clone(x, pool=None):
    '''
    Clone guts object tree.

    Traverses guts object tree and recursively clones all guts attributes,
    falling back to :py:func:`copy.deepcopy` for non-guts objects. Objects
    deriving from :py:class:`Object` are instantiated using their respective
    init function. Multiply referenced objects in the source tree are multiply
    referenced also in the destination tree.

    This function can be used to clone guts objects ignoring any contained
    run-time state, i.e. any of their attributes not defined as a guts
    property.
    '''

    if pool is None:
        pool = {}

    if id(x) in pool:
        x_copy = pool[id(x)][1]

    else:
        if isinstance(x, SObject):
            x_copy = x.__class__(str(x))
        elif isinstance(x, Object):
            d = {}
            for (prop, y) in x.T.ipropvals(x):
                if y is not None:
                    if not prop.multivalued:
                        y_copy = clone(y, pool)
                    elif prop.multivalued is dict:
                        y_copy = dict(
                            (clone(zk, pool), clone(zv, pool))
                            for (zk, zv) in y.items())
                    else:
                        y_copy = type(y)(clone(z, pool) for z in y)
                else:
                    y_copy = y

                d[prop.name] = y_copy

            x_copy = x.__class__(**d)

        else:
            x_copy = copy.deepcopy(x)

    pool[id(x)] = (x, x_copy)
    return x_copy


class YPathError(Exception):
    '''
    This exception is raised for invalid ypath specifications.
    '''
    pass


def _parse_yname(yname):
    ident = r'[a-zA-Z][a-zA-Z0-9_]*'
    rint = r'-?[0-9]+'
    m = re.match(
        r'^(%s)(\[((%s)?(:)(%s)?|(%s))\])?$'
        % (ident, rint, rint, rint), yname)

    if not m:
        raise YPathError('Syntax error in component: "%s"' % yname)

    d = dict(
        name=m.group(1))

    if m.group(2):
        if m.group(5):
            istart = iend = None
            if m.group(4):
                istart = int(m.group(4))
            if m.group(6):
                iend = int(m.group(6))

            d['slice'] = (istart, iend)
        else:
            d['index'] = int(m.group(7))

    return d


def _decend(obj, ynames):
    if ynames:
        for sobj in iter_elements(obj, ynames):
            yield sobj
    else:
        yield obj


def iter_elements(obj, ypath):
    '''
    Generator yielding elements matching a given ypath specification.

    :param obj: guts :py:class:`Object` instance
    :param ypath: Dot-separated object path (e.g. 'root.child.child').
        To access list objects use slice notatation (e.g.
        'root.child[:].child[1:3].child[1]').

    Raises :py:exc:`YPathError` on failure.
    '''

    try:
        if isinstance(ypath, str):
            ynames = ypath.split('.')
        else:
            ynames = ypath

        yname = ynames[0]
        ynames = ynames[1:]
        d = _parse_yname(yname)
        if d['name'] not in obj.T.propnames:
            raise AttributeError(d['name'])

        obj = getattr(obj, d['name'])

        if 'index' in d:
            sobj = obj[d['index']]
            for ssobj in _decend(sobj, ynames):
                yield ssobj

        elif 'slice' in d:
            for i in range(*slice(*d['slice']).indices(len(obj))):
                sobj = obj[i]
                for ssobj in _decend(sobj, ynames):
                    yield ssobj
        else:
            for sobj in _decend(obj, ynames):
                yield sobj

    except (AttributeError, IndexError) as e:
        raise YPathError('Invalid ypath: "%s" (%s)' % (ypath, str(e)))


def get_elements(obj, ypath):
    '''
    Get all elements matching a given ypath specification.

    :param obj: guts :py:class:`Object` instance
    :param ypath: Dot-separated object path (e.g. 'root.child.child').
        To access list objects use slice notatation (e.g.
        'root.child[:].child[1:3].child[1]').

    Raises :py:exc:`YPathError` on failure.
    '''
    return list(iter_elements(obj, ypath))


def set_elements(obj, ypath, value, validate=False, regularize=False):
    '''
    Set elements matching a given ypath specification.

    :param obj: guts :py:class:`Object` instance
    :param ypath: Dot-separated object path (e.g. 'root.child.child').
        To access list objects use slice notatation (e.g.
        'root.child[:].child[1:3].child[1]').
    :param value: All matching elements will be set to `value`.
    :param validate: Whether to validate affected subtrees.
    :param regularize: Whether to regularize affected subtrees.

    Raises :py:exc:`YPathError` on failure.
    '''

    ynames = ypath.split('.')
    try:
        d = _parse_yname(ynames[-1])
        if ynames[:-1]:
            it = iter_elements(obj, ynames[:-1])
        else:
            it = [obj]

        for sobj in it:
            if d['name'] not in sobj.T.propnames:
                raise AttributeError(d['name'])

            if 'index' in d:
                ssobj = getattr(sobj, d['name'])
                ssobj[d['index']] = value
            elif 'slice' in d:
                ssobj = getattr(sobj, d['name'])
                for i in range(*slice(*d['slice']).indices(len(ssobj))):
                    ssobj[i] = value
            else:
                setattr(sobj, d['name'], value)
                if regularize:
                    sobj.regularize()
                if validate:
                    sobj.validate()

    except (AttributeError, IndexError, YPathError) as e:
        raise YPathError('Invalid ypath: "%s" (%s)' % (ypath, str(e)))


def zip_walk(x, typ=None, path=(), stack=()):
    if typ is None or isinstance(x, typ):
        yield path, stack + (x,)

    if isinstance(x, Object):
        for (prop, val) in x.T.ipropvals(x):
            if prop.multivalued:
                if val is not None:
                    for iele, ele in enumerate(val):
                        for y in zip_walk(
                                ele, typ,
                                path=path + ((prop.name, iele),),
                                stack=stack + (x,)):

                            yield y
            else:
                for y in zip_walk(val, typ,
                                  path=path+(prop.name,),
                                  stack=stack + (x,)):
                    yield y


def path_element(x):
    if isinstance(x, tuple):
        if len(x) == 2:
            return '%s[%i]' % x
        elif len(x) == 3:
            return '%s[%i:%i]' % x

    else:
        return x


def path_to_str(path):
    return '.'.join(path_element(x) for x in path)


@expand_stream_args('w')
def dump(obj, stream, **kwargs):
    '''
    Serialize to YAML.

    If neither ``stream`` nor ``filename`` is set, a string containing the
    serialized data is returned.

    :param obj:
        Object to be serialized.
    :type obj:
        :py:class:`Object`

    :param stream:
        Output to stream.

    :param filename:
        Output to file of given name.
    :type filename:
        str

    :param header:
        File header to prepend to the output.
    :type header:
        str
    '''
    return _dump(obj, stream, **kwargs)


@expand_stream_args('r')
def load(stream, **kwargs):
    return _load(stream, **kwargs)


def load_string(s, **kwargs):
    return load(string=s, **kwargs)


@expand_stream_args('w')
def dump_all(obj, stream, **kwargs):
    return _dump_all(obj, stream, **kwargs)


@expand_stream_args('r')
def load_all(stream, **kwargs):
    return _load_all(stream, **kwargs)


@expand_stream_args('r')
def iload_all(stream, **kwargs):
    return _iload_all(stream, **kwargs)


@expand_stream_args('w')
def dump_xml(obj, stream, **kwargs):
    '''
    Serialize to XML.

    If neither ``stream`` nor ``filename`` is set, a string containing the
    serialized data is returned.

    :param obj:
        Object to be serialized.
    :type obj:
        :py:class:`Object`

    :param stream:
        Output to stream.

    :param filename:
        Output to file of given name.
    :type filename:
        str

    :param header:
        File header to prepend to the output.
    :type header:
        str

    :param ns_ignore:
        Whether to ignore the XML namespace.
    :type ns_ignore:
        bool
    '''
    return _dump_xml(obj, stream, **kwargs)


@expand_stream_args('r')
def load_xml(stream, **kwargs):
    kwargs.pop('filename', None)
    return _load_xml(stream, **kwargs)


def load_xml_string(s, **kwargs):
    return load_xml(string=s, **kwargs)


@expand_stream_args('w')
def dump_all_xml(obj, stream, **kwargs):
    return _dump_all_xml(obj, stream, **kwargs)


@expand_stream_args('r')
def load_all_xml(stream, **kwargs):
    kwargs.pop('filename', None)
    return _load_all_xml(stream, **kwargs)


@expand_stream_args('r')
def iload_all_xml(stream, **kwargs):
    kwargs.pop('filename', None)
    return _iload_all_xml(stream, **kwargs)


def _dump_all_spickle(objects, stream):
    import pickle
    header = b'SPICKLE'.ljust(512)
    stream.write(header, )
    for obj in objects:
        pickle.dump(obj, stream)


def _iload_all_spickle(stream):
    for obj, _ in _iload_all_spickle_internal(stream):
        yield obj


def _load_one_spickle_internal(stream):
    import pickle
    fpos = stream.tell()
    return pickle.load(stream), fpos


def _iload_all_spickle_internal(stream, offset=None):
    if offset is not None:
        stream.seek(offset, 0)
    else:
        header = stream.read(512)
        if not header.startswith(b'SPICKLE'):
            raise ValueError('Not a SPICKLE file.')

    while True:
        try:
            yield _load_one_spickle_internal(stream)
        except EOFError:
            break


def _load_all_spickle(stream):
    return list(_iload_all_spickle(stream))


@expand_stream_args('w')
def dump_all_spickle(objects, stream, **kwargs):
    return _dump_all_spickle(objects, stream)


@expand_stream_args('r')
def iload_all_spickle(stream, **kwargs):
    _iload_all_spickle(stream)


@expand_stream_args('r')
def load_all_spickle(stream, **kwargs):
    kwargs.pop('filename', None)
    return _load_all_spickle(stream, **kwargs)


__all__ = guts_types + [
    'guts_types', 'TBase', 'ValidationError',
    'ArgumentError', 'Defer',
    'DefaultMaker', 'ObjectDefaultMaker',
    'clone',
    'dump', 'load',
    'dump_all', 'load_all', 'iload_all',
    'dump_xml', 'load_xml',
    'dump_all_xml', 'load_all_xml', 'iload_all_xml',
    'load_string',
    'load_xml_string',
    'make_typed_list_class', 'walk', 'zip_walk', 'path_to_str'
]
