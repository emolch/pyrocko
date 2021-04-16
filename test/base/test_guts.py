from __future__ import division, print_function, absolute_import

import unittest
import calendar
import math
import re
import sys
import datetime
import os.path as op
import time
from contextlib import contextmanager

import numpy as num

from pyrocko.guts import StringPattern, Object, Bool, Int, Float, String, \
    SObject, Unicode, Complex, Timestamp, DateTimestamp, StringChoice, Defer, \
    ArgumentError, ValidationError, Any, List, Tuple, Union, Choice, Dict, \
    load, load_string, load_xml_string, load_xml, load_all, iload_all, \
    load_all_xml, iload_all_xml, dump, dump_xml, dump_all, dump_all_xml, \
    make_typed_list_class, walk, zip_walk, path_to_str, clone, set_elements, \
    get_elements, YPathError, FileNotFoundError

import pyrocko.guts


try:
    unicode
except NameError:
    unicode = str

from pyrocko.util import get_time_float, to_time_float


guts_prefix = 'guts_test'


class SamplePat(StringPattern):
    pattern = r'[a-z]{3}'


class SampleChoice(StringChoice):
    choices = ['a', 'bcd', 'efg']


basic_types = (
    Bool, Int, Float, String, Unicode, Complex, Timestamp, SamplePat,
    SampleChoice)


def tstamp(*args):
    time_float = get_time_float()
    return time_float(calendar.timegm(args))


samples = {}
samples[Bool] = [True, False]
samples[Int] = [2**n for n in [1, 30]]  # ,31,65] ]
samples[Float] = [0., 1., math.pi, float('inf'), float('-inf'), float('nan')]
samples[String] = [
    '', 'test', 'abc def', '<', '\n', '"', '\'',
    ''.join(chr(x) for x in range(32, 128))]
# chr(0) and other special chars don't work with xml...

samples[Unicode] = [u'aoeu \u00e4 \u0100']
samples[Complex] = [1.0+5J, 0.0J, complex(math.pi, 1.0)]
samples[Timestamp] = [
    0.0,
    tstamp(2030, 1, 1, 0, 0, 0),
    tstamp(1960, 1, 1, 0, 0, 0),
    tstamp(2010, 10, 10, 10, 10, 10) + 0.000001]

samples[SamplePat] = ['aaa', 'zzz']
samples[SampleChoice] = ['a', 'bcd', 'efg']

regularize = {}
regularize[Bool] = [(1, True), (0, False), ('0', False), ('False', False)]
regularize[Int] = [('1', 1), (1.0, 1), (1.1, 1)]
regularize[Float] = [
    ('1.0', 1.0),
    (1, 1.0),
    ('inf', float('inf')),
    ('nan', float('nan'))]
regularize[String] = [(1, '1')]
regularize[Unicode] = [(1, u'1')]
regularize[Timestamp] = [
    ('2010-01-01 10:20:01',  tstamp(2010, 1, 1, 10, 20, 1)),
    ('2010-01-01T10:20:01',  tstamp(2010, 1, 1, 10, 20, 1)),
    ('2010-01-01T10:20:01.11Z',  tstamp(2010, 1, 1, 10, 20, 1)+0.11),
    ('2030-12-12 00:00:10.11111',  tstamp(2030, 12, 12, 0, 0, 10)+0.11111),
    (datetime.date(2010, 12, 12),  tstamp(2010, 12, 12, 0, 0, 0)),
    (10,  to_time_float(10.))
]
regularize[DateTimestamp] = [
    ('2010-01-01',  tstamp(2010, 1, 1, 0, 0, 0)),
    (datetime.datetime(2010, 12, 12),  tstamp(2010, 12, 12, 0, 0, 0)),
    (datetime.date(2010, 12, 12),  tstamp(2010, 12, 12, 0, 0, 0)),
    (86400, to_time_float(86400.))
]

regularize[Complex] = [
    ([1., 2.], 1.0+2.0J),
    ((1., 2.), 1.0+2.0J)
]


class GutsTestCase(unittest.TestCase):

    if sys.version_info < (2, 7):

        @contextmanager
        def assertRaises(self, exc):

            gotit = False
            try:
                yield None
            except exc:
                gotit = True

            assert gotit, 'expected to get a %s exception' % exc

        def assertIsNone(self, value):
            assert value is None, 'expected None but got %s' % value

    def assertEqualNanAware(self, a, b):
        if isinstance(a, float) \
                and isinstance(b, float) \
                and math.isnan(a) and math.isnan(b):
            return

        if isinstance(a, float) and isinstance(b, float):
            self.assertEqual('%.14g' % a, '%.14g' % b)
        else:
            self.assertEqual(a, b)

    def testStringChoice(self):
        class X(Object):
            m = StringChoice.T(['a', 'b'])

        x = X(m='a')
        x.validate()
        x = X(m='c')
        with self.assertRaises(ValidationError):
            x.validate()

    def testStringChoiceIgnoreCase(self):
        class X(Object):
            m = StringChoice.T(['a', 'b'], ignore_case=True)

        x = X(m='A')
        x.validate()
        x = X(m='C')
        with self.assertRaises(ValidationError):
            x.validate()

    def testDefaultMaker(self):
        class X(Object):
            a = Int.T(default=1)

        class Y(Object):
            x = X.T(default=X.D(a=2))

        class Yb(Object):
            x = X.T(default=X(a=2))

        class Z(Object):
            y = Y.T(default=Y.D(x=X.D(a=3)))

        class Zb(Object):
            y = Y.T(default=Yb(x=X(a=3)))

        class Zl(Object):
            y = Y.T(default=Y.D(x=X.D(a=3)))

        class Zbl(Object):
            y = Y.T(default=Yb(x=X(a=3)))

        y = Y()
        self.assertEqual(y.x.a, 2)

        z = Z()
        z2 = Z()

        z2.y.x.a = 5
        self.assertEqual(z.y.x.a, 3)
        self.assertEqual(z2.y.x.a, 5)

        y = Yb()
        self.assertEqual(y.x.a, 2)

        z = Zb()
        z2 = Zb()

        z2.y.x.a = 5
        self.assertEqual(z.y.x.a, 3)
        self.assertEqual(z2.y.x.a, 5)

    def testDefaultList(self):
        class X(Object):
            a = Int.T(default=1)

        class Y(Object):
            xs = List.T(X.T(), default=[X(a=2)])

        y = Y()
        y.xs[0].a = 3
        y2 = Y()
        self.assertEqual(y2.xs[0].a, 2)
        self.assertEqual(y.xs[0].a, 3)

    def testDefaultTuple(self):
        class X(Object):
            a = Int.T(default=1)

        class Y(Object):
            xs = Tuple.T(1, X.T(), default=(X(a=2),))

        y = Y()
        y.xs[0].a = 3
        y2 = Y()
        self.assertEqual(y2.xs[0].a, 2)
        self.assertEqual(y.xs[0].a, 3)

    def testDefaultDict(self):
        class X(Object):
            a = Int.T(default=1)

        class Y(Object):
            xs = Dict.T(X.T(), X.T(), default={
                X(a=2): X(a=3)})

        def fi(d):
            return list(d.values())[0]

        y = Y()
        fi(y.xs).a = 4
        y2 = Y()
        self.assertEqual(fi(y2.xs).a, 3)
        self.assertEqual(fi(y.xs).a, 4)

    def testRemove(self):
        class X(Object):
            y = Int.T(default=1, xmlstyle='attribute')
            z = List.T(Int.T())
            a = Int.T(xmlstyle='content')

        x = X(a=11, z=[1, 2, 3])
        del x

        X.T.remove_property('y')
        X.T.remove_property('z')
        X.T.remove_property('a')

        assert len(X.T.propnames) == 0
        assert len(X.T.xmltagname_to_name) == 0
        assert len(X.T.xmltagname_to_name_multivalued) == 0
        assert len(X.T.xmltagname_to_name_multivalued) == 0

    def testAny(self):
        class X(Object):
            y = Int.T(default=1)

        class A(Object):
            x = Any.T()
            lst = List.T(Any.T())

        a1 = A(x=X(y=33))
        a1.validate()
        a1c = load_string(a1.dump())
        self.assertEqual(a1c.x.y, 33)

        a2 = A(x=22, lst=['a', 44, X(y=22)])
        a2.validate()
        a2c = load_string(a2.dump())
        self.assertEqual(a2c.x, 22)
        self.assertEqual(a2c.lst[:2], ['a', 44])
        self.assertEqual(a2c.lst[2].y, 22)

        a3 = A(x=X(y='10'))
        with self.assertRaises(ValidationError):
            a3.validate()

        a3.regularize()
        assert a3.x.y == 10

    def testAnyObject(self):
        class Base(Object):
            pass

        class A(Base):
            y = Int.T(default=1)

        class B(Base):
            x = Float.T(default=1.0)

        class C(Object):
            c = Base.T(optional=True)

        ca = C(c=A())
        cb = C(c=B())
        c_err = C(c='abc')
        cc_err = C(c=C())
        ca_err = C(c=A(y='1'))

        for c in (ca, cb):
            c.validate()

        for c in (c_err, cc_err, ca_err):
            with self.assertRaises(ValidationError):
                c.validate()

        ca_err.regularize()
        assert ca_err.c.y == 1

    def testUnion(self):

        class X1(Object):
            xmltagname = 'root'
            m = Union.T(members=[Int.T(), StringChoice.T(['small', 'large'])])

        class U(Union):
            members = [Int.T(), StringChoice.T(['small', 'large'])]

        class X2(Object):
            xmltagname = 'root'
            m = U.T()

        for X in [X1, X2]:
            X = X1
            x1 = X(m='1')
            with self.assertRaises(ValidationError):
                x1.validate()

            x1.validate(regularize=True)
            self.assertEqual(x1.m, 1)

            x2 = X(m='small')
            x2.validate()
            x3 = X(m='fail!')
            with self.assertRaises(ValidationError):
                x3.validate()
            with self.assertRaises(ValidationError):
                x3.validate(regularize=True)

            for x in [x1, x2]:
                y = load_string(x.dump())
                self.assertEqual(x.m, y.m)

            for x in [x1, x2]:
                y = load_xml_string(x.dump_xml())
                self.assertEqual(x.m, y.m)

    def testChoice(self):
        class A(Object):
            x = Int.T(default=1)

        class B(Object):
            y = Int.T(default=2)

        class OhOh(Object):
            z = Float.T(default=4.0)

        class AB(Choice):
            choices = [A.T(xmltagname='a'), B.T(xmltagname='b')]

        class C1(Object):
            xmltagname = 'root1'
            ab = Choice.T(choices=[A.T(xmltagname='a'), B.T(xmltagname='b')])

        class C2(Object):
            xmltagname = 'root2'
            ab = AB.T()

        for C in (C1, C2):
            for good in (A(), B()):
                c = C(ab=good)
                c.validate()
                for dumpx, loadx in (
                        (dump, load_string),
                        (dump_xml, load_xml_string)):
                    c2 = loadx(dumpx(c))
                    self.assertEqual(type(c2), C)
                    self.assertEqual(type(c2.ab), type(good))

            for bad in (OhOh(), 5.0):
                c = C(ab=bad)
                with self.assertRaises(ValidationError):
                    c.validate()

        c = C1(ab=A(x='5'))
        c.regularize()
        assert c.ab.x == 5
        c = C1(ab=B(y='6'))
        c.regularize()
        assert c.ab.y == 6

    def testRegularizeChoice(self):

        class A(Object):
            x = Choice.T(optional=True, choices=[Timestamp.T(), Int.T()])

        a = A()
        a.regularize()

        a = A(x='2015-01-01 00:00:00')
        a.regularize()

        a = A(x='5')
        a.regularize()

        a = A(x='abc')
        with self.assertRaises(ValidationError):
            a.regularize()

    def testTooMany(self):

        class A(Object):
            m = List.T(Int.T())
            xmltagname = 'a'

        a = A(m=[1, 2, 3])

        class A(Object):
            m = Int.T()
            xmltagname = 'a'

        with self.assertRaises(ArgumentError):
            load_xml_string(a.dump_xml())

    def testDeferred(self):
        class A(Object):
            p = Defer('B.T', optional=True)

        class B(Object):
            p = A.T()

        a = A(p=B(p=A()))
        del a

    def testListDeferred(self):
        class A(Object):
            p = List.T(Defer('B.T'))
            q = List.T(Defer('B.T'))

        class B(Object):
            p = List.T(A.T())

        a = A(p=[B(p=[A()])], q=[B(), B()])
        del a

    def testOptionalList(self):
        class A(Object):
            l1 = List.T(Int.T())
            l2 = List.T(Int.T(), optional=True)
            l3 = List.T(Int.T(), default=[1, 2, 3])

        a = A()
        a.validate()
        self.assertEqual(a.l1, [])
        self.assertIsNone(a.l2)
        self.assertEqual(a.l3, [1, 2, 3])

    def testSelfDeferred(self):
        class A(Object):
            a = Defer('A.T', optional=True)

        a = A(a=A(a=A()))
        del a

    def testOrder(self):
        class A(Object):
            a = Int.T(default=1)
            b = Int.T(default=2)

        class B(A):
            a = Int.T(default=3, position=A.a.position)
            c = Int.T(default=4)

        b = B()
        names = [k for (k, v) in b.T.inamevals(b)]
        assert names == ['a', 'b', 'c']

    def testOrderDeferred(self):
        class A(Object):
            a = Defer('B.T')
            b = Int.T(default=0)

        class B(Object):
            x = Int.T(default=1)

        a = A(a=B())
        names = [k for (k, v) in a.T.inamevals(a)]

        assert names == ['a', 'b']

    def testDocs(self):
        class A(Object):
            '''A description'''

            a = Int.T(default=0, help='the a property')

        class B(A):
            '''B description'''

            b = Float.T(default=0, help='the b property')
            c = List.T(Int.T(), help='the c')

        self.assertEqual(B.__doc__, '''B description

    .. py:gattribute:: b

      ``float``, *default:* ``0``
      
      the b property

    .. py:gattribute:: c

      ``list`` of ``int`` objects, *default:* ``[]``
      
      the c
''')  # noqa

    def testContentStyleXML(self):

        class Duration(Object):
            unit = String.T(optional=True, xmlstyle='attribute')
            uncertainty = Float.T(optional=True)
            value = Float.T(optional=True, xmlstyle='content')

            xmltagname = 'duration'

        s = '<duration unit="s"><uncertainty>1.0</uncertainty>10.5</duration>'
        dur = load_xml_string(s)
        self.assertEqual(dur.value, float('10.5'))
        self.assertEqual(dur.unit, 's')
        self.assertEqual(dur.uncertainty, float('1.0'))
        self.assertEqual(re.sub(r'\n\s*', '', dur.dump_xml()), s)

    def testSObject(self):

        class DotName(SObject):
            network = String.T()
            station = String.T()

            def __init__(self, s=None, **kwargs):
                if s is not None:
                    network, station = s.split('.')
                    kwargs = dict(network=network, station=station)

                SObject.__init__(self, **kwargs)

            def __str__(self):
                return '.'.join((self.network, self.station))

        class X(Object):
            xmltagname = 'root'
            dn = DotName.T()

        x = X(dn=DotName(network='abc', station='def'))
        self.assertEqual(x.dn.network, 'abc')
        self.assertEqual(x.dn.station, 'def')
        x = load_string(dump(x))
        self.assertEqual(x.dn.network, 'abc')
        self.assertEqual(x.dn.station, 'def')
        x = load_xml_string(dump_xml(x))
        self.assertEqual(x.dn.network, 'abc')
        self.assertEqual(x.dn.station, 'def')

    def testDict(self):
        class A(Object):
            d = Dict.T(Int.T(), Float.T())

        a = A(d={1: 2.0})

        with self.assertRaises(NotImplementedError):
            a.dump_xml()

        a2 = load_string(a.dump())
        self.assertEqual(a2.dump(), a.dump())

        for (k1, v1), (k2, v2) in [
                [('1', 2.0), (1, 2.0)],
                [(1, '2.0'), (1, 2.0)],
                [('1', '2.0'), (1, 2.0)]]:

            a = A(d={k1: v1})
            with self.assertRaises(ValidationError):
                a.validate()

            a.regularize()
            self.assertEqual(a.d[k2], v2)

    def testOptionalDefault(self):

        from pyrocko.guts_array import Array, array_equal
        import numpy as num
        assert_ae = num.testing.assert_almost_equal

        def array_equal_noneaware(a, b):
            if a is None:
                return b is None
            elif b is None:
                return a is None
            else:
                return array_equal(a, b)

        data = [
            ('a', Int.T(),
                [None, 0, 1, 2],
                ['aerr', 0, 1, 2]),
            ('b', Int.T(optional=True),
                [None, 0, 1, 2],
                [None, 0, 1, 2]),
            ('c', Int.T(default=1),
                [None, 0, 1, 2],
                [1, 0, 1, 2]),
            ('d', Int.T(default=1, optional=True),
                [None, 0, 1, 2],
                [1, 0, 1, 2]),
            ('e', List.T(Int.T()),
                [None, [], [1], [2]],
                [[], [], [1], [2]]),
            ('f', List.T(Int.T(), optional=True),
                [None, [], [1], [2]],
                [None, [], [1], [2]]),
            ('g', List.T(Int.T(), default=[1]), [
                None, [], [1], [2]],
                [[1], [], [1], [2]]),
            ('h', List.T(Int.T(), default=[1], optional=True),
                [None, [], [1], [2]],
                [[1], [], [1], [2]]),
            ('i', Tuple.T(2, Int.T()),
                [None, (1, 2)],
                ['err', (1, 2)]),
            ('j', Tuple.T(2, Int.T(), optional=True),
                [None, (1, 2)],
                [None, (1, 2)]),
            ('k', Tuple.T(2, Int.T(), default=(1, 2)),
                [None, (1, 2), (3, 4)],
                [(1, 2), (1, 2), (3, 4)]),
            ('l', Tuple.T(2, Int.T(), default=(1, 2), optional=True),
                [None, (1, 2), (3, 4)],
                [(1, 2), (1, 2), (3, 4)]),
            ('i2', Tuple.T(None, Int.T()),
                [None, (1, 2)],
                [(), (1, 2)]),
            ('j2', Tuple.T(None, Int.T(), optional=True),
                [None, (), (3, 4)],
                [None, (), (3, 4)]),
            ('k2', Tuple.T(None, Int.T(), default=(1,)),
                [None, (), (3, 4)],
                [(1,), (), (3, 4)]),
            ('l2', Tuple.T(None, Int.T(), default=(1,), optional=True),
                [None, (), (3, 4)],
                [(1,), (), (3, 4)]),
            ('m', Array.T(shape=(None,), dtype=num.int, serialize_as='list'),
                [num.arange(0), num.arange(2)],
                [num.arange(0), num.arange(2)]),
            ('n', Array.T(shape=(None,), dtype=num.int, serialize_as='list',
                          optional=True),
                [None, num.arange(0), num.arange(2)],
                [None, num.arange(0), num.arange(2)]),
            ('o', Array.T(shape=(None,), dtype=num.int, serialize_as='list',
                          default=num.arange(2)),
                [None, num.arange(0), num.arange(2), num.arange(3)],
                [num.arange(2), num.arange(0), num.arange(2), num.arange(3)]),
            ('p', Array.T(shape=(None,), dtype=num.int, serialize_as='list',
                          default=num.arange(2), optional=True),
                [None, num.arange(0), num.arange(2), num.arange(3)],
                [num.arange(2), num.arange(0), num.arange(2), num.arange(3)]),
            ('q', Dict.T(String.T(), Int.T()),
                [None, {}, {'a': 1}],
                [{}, {}, {'a': 1}]),
            ('r', Dict.T(String.T(), Int.T(), optional=True),
                [None, {}, {'a': 1}],
                [None, {}, {'a': 1}]),
            ('s', Dict.T(String.T(), Int.T(), default={'a': 1}),
                [None, {}, {'a': 1}],
                [{'a': 1}, {}, {'a': 1}]),
            ('t', Dict.T(String.T(), Int.T(), default={'a': 1}, optional=True),
                [None, {}, {'a': 1}],
                [{'a': 1}, {}, {'a': 1}]),
        ]

        for k, t, vals, exp, in data:
            last = [None]

            class A(Object):
                def __init__(self, **kwargs):
                    last[0] = len(kwargs)
                    Object.__init__(self, **kwargs)

                v = t

            A.T.class_signature()

            for v, e in zip(vals, exp):
                if isinstance(e, str) and e == 'aerr':
                    with self.assertRaises(ArgumentError):
                        if v is not None:
                            a1 = A(v=v)
                        else:
                            a1 = A()

                    continue
                else:
                    if v is not None:
                        a1 = A(v=v)
                    else:
                        a1 = A()

                if isinstance(e, str) and e == 'err':
                    with self.assertRaises(ValidationError):
                        a1.validate()
                else:
                    a1.validate()
                    a2 = load_string(dump(a1))
                    if isinstance(e, num.ndarray):
                        assert last[0] == int(
                            not (array_equal_noneaware(t.default(), a1.v)
                                 and t.optional))
                        assert_ae(a1.v, e)
                        assert_ae(a1.v, e)
                    else:
                        assert last[0] == int(
                            not(t.default() == a1.v and t.optional))
                        self.assertEqual(a1.v, e)
                        self.assertEqual(a2.v, e)

    def testArray(self):
        from pyrocko.guts_array import Array
        import numpy as num

        shapes = [(None,), (1,), (10,), (1000,)]
        for shape in shapes:
            for serialize_as in ('base64', 'table', 'npy',
                                 'base64+meta', 'base64-compat'):
                class A(Object):
                    xmltagname = 'aroot'
                    arr = Array.T(
                        shape=shape,
                        dtype=num.int,
                        serialize_as=serialize_as,
                        serialize_dtype='>i8')

                n = shape[0] or 10
                a = A(arr=num.arange(n, dtype=num.int))
                b = load_string(a.dump())
                self.assertTrue(num.all(a.arr == b.arr))

                if serialize_as != 'base64+meta':
                    b = load_xml_string(a.dump_xml())
                    self.assertTrue(num.all(a.arr == b.arr))

                if shape[0] is not None:
                    with self.assertRaises(ValidationError):
                        a = A(arr=num.arange(n+10, dtype=num.int))
                        a.validate()

        for s0 in [None, 2, 10]:
            for s1 in [None, 2, 10]:
                class A(Object):
                    xmltagname = 'aroot'
                    arr = Array.T(
                        shape=(s0, s1),
                        dtype=num.int)

                n0 = s0 or 100
                n1 = s1 or 100
                a = A(arr=num.arange(n0*n1, dtype=num.int).reshape((n0, n1)))
                b = load_string(a.dump())
                self.assertTrue(num.all(a.arr == b.arr))

                b = load_xml_string(a.dump_xml())
                self.assertTrue(num.all(a.arr == b.arr))

    def testArrayNoDtype(self):
        from pyrocko.guts_array import Array
        import numpy as num

        class A(Object):
            arr = Array.T(serialize_as='base64+meta')

        for dtype in (num.int, num.float):
            a = A(arr=num.zeros((3, 3), dtype=dtype))
            b = load_string(a.dump())
            assert a.arr.shape == b.arr.shape
            self.assertTrue(num.all(a.arr == b.arr))

        b_int = load_string  # noqa

    def testPO(self):
        class SKU(StringPattern):
            pattern = '\\d{3}-[A-Z]{2}'

        class Comment(String):
            xmltagname = 'comment'

        class Quantity(Int):
            pass

        class USAddress(Object):
            country = String.T(
                default='US', optional=True, xmlstyle='attribute')
            name = String.T()
            street = String.T()
            city = String.T()
            state = String.T()
            zip = Float.T()

        class Item(Object):
            part_num = SKU.T(xmlstyle='attribute')
            product_name = String.T()
            quantity = Quantity.T()
            us_price = Float.T(xmltagname='USPrice')
            comment = Comment.T(optional=True)
            ship_date = DateTimestamp.T(optional=True)

        class Items(Object):
            item_list = List.T(Item.T())

        class PurchaseOrderType(Object):
            order_date = DateTimestamp.T(optional=True, xmlstyle='attribute')
            ship_to = USAddress.T()
            bill_to = USAddress.T()
            comment = Comment.T(optional=True)
            items = Items.T()

        class PurchaseOrder(PurchaseOrderType):
            xmltagname = 'purchaseOrder'

        xml = '''<?xml version="1.0"?>
<purchaseOrder orderDate="1999-10-20">
   <shipTo country="US">
      <name>Alice Smith</name>
      <street>123 Maple Street</street>
      <city>Mill Valley</city>
      <state>CA</state>
      <zip>90952</zip>
   </shipTo>
   <billTo country="US">
      <name>Robert Smith</name>
      <street>8 Oak Avenue</street>
      <city>Old Town</city>
      <state>PA</state>
      <zip>95819</zip>
   </billTo>
   <comment>Hurry, my lawn is going wild</comment>
   <items>
      <item partNum="872-AA">
         <productName>Lawnmower</productName>
         <quantity>1</quantity>
         <USPrice>148.95</USPrice>
         <comment>Confirm this is electric</comment>
      </item>
      <item partNum="926-AA">
         <productName>Baby Monitor</productName>
         <quantity>1</quantity>
         <USPrice>39.98</USPrice>
         <shipDate>1999-05-21</shipDate>
      </item>
   </items>
</purchaseOrder>
'''
        po1 = load_xml_string(xml)
        po2 = load_xml_string(po1.dump_xml())

        for (path1, obj1), (path2, obj2) in zip(walk(po1), walk(po2)):
            assert path1 == path2
            assert path_to_str(path1) == path_to_str(path2)
            assert type(obj1) is type(obj2)
            if not isinstance(obj1, Object):
                assert obj1 == obj2

        for _ in zip_walk(po1):
            pass

        self.assertEqual(po1.dump(), po2.dump())

    def testDumpLoad(self):

        from tempfile import NamedTemporaryFile as NTF

        class A(Object):
            xmltagname = 'a'
            p = Int.T()

        a1 = A(p=33)
        an = [a1, a1, a1]

        def check1(a, b):
            self.assertEqual(a.p, b.p)

        def checkn(a, b):
            for ea, eb in zip(a, b):
                self.assertEqual(ea.p, eb.p)

        for (a, xdump, xload, check) in [
                (a1, dump, load, check1),
                (a1, dump_xml, load_xml, check1),
                (an, dump_all, load_all, checkn),
                (an, dump_all, iload_all, checkn),
                (an, dump_all_xml, load_all_xml, checkn),
                (an, dump_all_xml, iload_all_xml, checkn)]:

            for header in (False, True, 'custom header'):
                # via string
                s = xdump(a, header=header)
                b = xload(string=s)
                check(a, b)

                # via file
                f = NTF(mode='w+')
                xdump(a, filename=f.name, header=header)
                b = xload(filename=f.name)
                check(a, b)
                f.close()

                # via stream
                for mode in ['w+b', 'w+']:
                    f = NTF(mode=mode)
                    xdump(a, stream=f, header=header)
                    f.seek(0)
                    b = xload(stream=f)
                    check(a, b)
                    f.close()

        b1 = A.load(string=a1.dump())
        check1(a1, b1)

        f = NTF(mode='w+')
        a1.dump(filename=f.name)
        b1 = A.load(filename=f.name)
        check1(a1, b1)
        f.close()

        f = NTF(mode='w+')
        a1.dump(stream=f)
        f.seek(0)
        b1 = A.load(stream=f)
        check1(a1, b1)
        f.close()

        b1 = A.load_xml(string=a1.dump_xml())
        check1(a1, b1)

        f = NTF(mode='w+')
        a1.dump_xml(filename=f.name)
        b1 = A.load_xml(filename=f.name)
        check1(a1, b1)
        f.close()

        f = NTF(mode='w+')
        a1.dump_xml(stream=f)
        f.seek(0)
        b1 = A.load_xml(stream=f)
        check1(a1, b1)
        f.close()

    def testCustomValidator(self):

        class RangeFloat(Float):
            class __T(Float.T):
                def __init__(self, min=0., max=1., *args, **kwargs):
                    Float.T.__init__(self, *args, **kwargs)
                    self.min = min
                    self.max = max

                def validate_extra(self, val):
                    if val < self.min or self.max < val:
                        raise ValidationError('out of range [%g, %g]: %g' % (
                            self.min, self.max, val))

        class A(Object):
            x = RangeFloat.T(min=-1., max=+1., default=0.)

        class B(A):
            y = RangeFloat.T(min=-2., max=+2., default=1.)

            class __T(A.T):
                def validate_extra(self, val):
                    if val.y <= val.x:
                        raise ValidationError('y must be greater than x')

        class C(B):
            class __T(B.T):
                def validate_extra(self, val):
                    if val.y >= val.x:
                        raise ValidationError('x must be greater than y')

        a1 = A()
        a1.validate()

        a2 = A(x=10.)
        with self.assertRaises(ValidationError):
            a2.validate()

        b1 = B()
        b1.validate()

        b2 = B(x=1., y=0.)
        with self.assertRaises(ValidationError):
            b2.validate()

        c1 = C()
        with self.assertRaises(ValidationError):
            c1.validate()

        c2 = C(x=1., y=0.)
        c2.validate()

    def testTypedListClass(self):

        FloatList = make_typed_list_class(Float)

        class A(Object):
            vals = FloatList.T()

        a = A(vals=[1., 2., 3.])
        a.validate()
        a2 = load_string(a.dump())
        assert a2.vals == a.vals

    def testClone(self):

        class A(Object):
            a = Int.T(optional=True)

        class B(Object):
            a_list = List.T(A.T())
            a_tuple = Tuple.T(3, A.T())
            a_dict = Dict.T(Int.T(), A.T())
            b = Float.T()

        a1 = A()
        a2 = A(a=1)
        b = B(
            a_list=[a1, a2],
            a_tuple=(a1, a2, a2),
            a_dict={1: a1, 2: a2},
            b=1.0)
        b_clone = clone(b)
        b.validate()
        b_clone.validate()
        self.assertEqual(b.dump(), b_clone.dump())
        assert b is not b_clone
        assert b.a_list is not b_clone.a_list
        assert b.a_tuple is not b_clone.a_tuple
        assert b.a_list[0] is not b_clone.a_list[0]
        assert b.a_tuple[0] is not b_clone.a_tuple[0]

    def testYPath(self):

        class A(Object):
            i = Int.T()
            i_list = List.T(Int.T())

        class B(Object):
            a_list = List.T(A.T())

        class C(Object):
            b_list = List.T(B.T())

        c = C(b_list=[B(a_list=[A(i=1), A(i=2)]), B(a_list=[A(i=3), A(i=4)])])

        assert get_elements(c, 'b_list[:].a_list[:].i') == [1, 2, 3, 4]
        assert get_elements(c, 'b_list[0].a_list[:].i') == [1, 2]
        assert get_elements(c, 'b_list[:1].a_list[:].i') == [1, 2]
        assert get_elements(c, 'b_list[:1].a_list[1:].i') == [2]
        assert [x.i for x in get_elements(c, 'b_list[-1].a_list[:]')] == [3, 4]

        with self.assertRaises(YPathError):
            get_elements(c, 'b_list[:].x_list[:].i')

        with self.assertRaises(YPathError):
            get_elements(c, 'b_list[:].a_list[:].x')

        with self.assertRaises(YPathError):
            get_elements(c, 'b_list[:].a_list[5]')

        with self.assertRaises(YPathError):
            get_elements(c, 'b_list[:].a_list[:].i.xxx')

        with self.assertRaises(YPathError):
            get_elements(c, '...')

        set_elements(c, 'b_list[1].a_list', [A(i=5), A(i=6)])
        assert get_elements(c, 'b_list[1].a_list[:].i') == [5, 6]

        set_elements(c, 'b_list[:].a_list[:].i', 7)
        assert get_elements(c, 'b_list[:].a_list[:].i') == [7, 7, 7, 7]

        with self.assertRaises(ValidationError):
            set_elements(c, 'b_list[:].a_list[:].i', '7', validate=True)

        set_elements(c, 'b_list[:].a_list[:].i', '7', regularize=True)
        assert get_elements(c, 'b_list[:].a_list[:].i') == [7, 7, 7, 7]

        set_elements(c, 'b_list[:].a_list[:].i_list', [1, 2, 3, 4])
        set_elements(c, 'b_list[:].a_list[:].i_list[1]', 5)
        set_elements(c, 'b_list[:].a_list[:].i_list[:]', 5)
        assert get_elements(c, 'b_list[:].a_list[:].i_list[:]') == [5] * 16

    def testXMLNamespaces(self):
        ns1 = 'http://www.w3.org/TR/html4/'
        ns2 = 'https://www.w3schools.com/furniture'

        class Row(Object):
            xmlns = ns1
            cells = List.T(String.T(xmltagname='td'))

        class Table1(Object):
            xmlns = ns1
            rows = List.T(Row.T(xmltagname='tr'))

        class Table2(Object):
            xmlns = ns2
            name = String.T()
            width = Int.T()
            length = Int.T()

        class Root(Object):
            xmltagname = 'root'
            tables1 = List.T(Table1.T(xmltagname='table'))
            tables2 = List.T(Table2.T(xmltagname='table'))

        doc = '''
<root xmlns:h="http://www.w3.org/TR/html4/"
xmlns:f="https://www.w3schools.com/furniture">

<h:table>
  <h:tr>
    <h:td>Apples</h:td>
    <h:td>Bananas</h:td>
  </h:tr>
</h:table>

<f:table>
  <f:name>African Coffee Table</f:name>
  <f:width>80</f:width>
  <f:length>120</f:length>
</f:table>

</root>
        '''

        o = load_xml(string=doc)
        s = o.dump_xml()
        o2 = load_xml(string=s)
        del o2

        assert isinstance(o.tables1[0], Table1)
        assert isinstance(o.tables2[0], Table2)

    def testXMLNamespaces2(self):
        ns1 = 'http://www.w3.org/TR/html4/'

        class Row(Object):
            xmlns = ns1
            cells = List.T(String.T(xmltagname='td'))

        class Table1(Object):
            xmlns = ns1
            rows = List.T(Row.T(xmltagname='tr'))

        class Root(Object):
            xmltagname = 'root'
            tables1 = List.T(Table1.T(xmltagname='table'))

        doc = '''
<root xmlns:h="http://www.w3.org/TR/html4/">

<h:table>
  <h:tr>
    <h:td>Apples</h:td>
    <h:td>Bananas</h:td>
  </h:tr>
</h:table>

</root>
        '''

        o = load_xml(string=doc)
        assert isinstance(o.tables1[0], Table1)
        s = o.dump_xml()

        o2 = load_xml(string=s)
        assert isinstance(o2.tables1[0], Table1)
        s2 = o2.dump_xml(ns_ignore=True)

        o3 = load_xml(string=s2, ns_hints=['', 'http://www.w3.org/TR/html4/'])
        assert isinstance(o3.tables1[0], Table1)

    def testStyles(self):
        for cls, Class in [(str, String), (unicode, Unicode)]:
            class A(Object):
                s = Class.T(yamlstyle=None)
                s_singlequoted = Class.T(yamlstyle="'")
                s_doublequoted = Class.T(yamlstyle='"')
                s_literal = Class.T(yamlstyle='|')
                s_folded = Class.T(yamlstyle='>')
                l_block = List.T(Class.T(yamlstyle="'"), yamlstyle='block')
                l_flow = List.T(Class.T(yamlstyle="'"), yamlstyle='flow')

            a = A(
                s=cls('hello'),
                s_singlequoted=cls('hello'),
                s_doublequoted=cls('hello'),
                s_literal=cls('hello\nhello\n'),
                s_folded=cls('hello'),
                l_block=[cls('a'), cls('b'), cls('c')],
                l_flow=[cls('a'), cls('b'), cls('c')])

            a.validate()

            a2 = load_string(a.dump())
            s2 = ('\n'.join(a2.dump().splitlines()[1:]))
            assert type(a2.s) == cls

            assert s2 == '''
s: hello
s_singlequoted: 'hello'
s_doublequoted: "hello"
s_literal: |
  hello
  hello
s_folded: >-
  hello
l_block:
- 'a'
- 'b'
- 'c'
l_flow: ['a', 'b', 'c']
'''.strip()

    def testEmpty(self):

        class A(Object):
            pass

        class B(Object):
            a = A.T()

        b = B(a=A())
        b2 = load_string(b.dump())
        assert(isinstance(b2.a, A))

    def testNumpyFloat(self):

        class A(Object):
            f = Float.T()
            i = Int.T()

        try:
            import numpy as num

            a = A(f=num.float64(1.0), i=num.int64(1))
            a2 = load_string(a.dump())
            assert a2.f == 1.0
            assert a2.i == 1

            with self.assertRaises(ValidationError):
                a.validate()

            a = A(f=num.float32(1.0), i=num.int32(1))
            a2 = load_string(a.dump())
            assert a2.f == 1.0
            assert a2.i == 1

            with self.assertRaises(ValidationError):
                a.validate()

        except ImportError:
            pass

    def testYAMLinclude(self):
        from tempfile import NamedTemporaryFile as NFT
        pyrocko.guts.ALLOW_INCLUDE = True

        class A(Object):
            f = Float.T()
            i = Int.T()
            s = String.T()

        def assert_equal(obj):
            assert obj.f == a.f
            assert obj.i == a.i
            assert obj.s == a.s

        a = A(f=123.2, i=1024, s='hello')

        with NFT('w') as f1:
            a.dump(filename=f1.name)
            with NFT('w') as f2:
                f2.write('''---
a: !include {fname}
b: !include {fname}
c: [!include {fname}]
'''.format(fname=f1.name))
                f2.flush()
                o_abs = load(filename=f2.name)

            assert_equal(o_abs['a'])
            assert_equal(o_abs['b'])
            assert_equal(o_abs['c'][0])

            # Relative import
            pyrocko.guts.ALLOW_INCLUDE = False
            with NFT('w') as f2:
                f2.write('''---
a: !include ./{fname}
b: !include ./{fname}
c: [!include ./{fname}]
'''.format(fname=op.basename(f1.name)))
                f2.flush()
                o_rel = load(filename=f2.name, allow_include=True)

            assert_equal(o_rel['a'])
            assert_equal(o_rel['b'])
            assert_equal(o_rel['c'][0])

        with self.assertRaises(ImportError):
            with NFT('w') as f:
                f.write('''
!include {fname}
'''.format(fname=f.name))
                f.flush()
                load(filename=f.name, allow_include=True)
        with self.assertRaises(FileNotFoundError):
            with NFT('w') as f:
                f.write('!include /tmp/does_not_exist.yaml')
                f.flush()
                load(filename=f.name, allow_include=True)

        with self.assertRaises(FileNotFoundError):
            with NFT('w') as f:
                f.write('!include ./does_not_exist.yaml')
                f.flush()
                load(filename=f.name, allow_include=True)

    def testTimestamp(self):

        class X(Object):
            t = Timestamp.T()

        time_float = get_time_float()
        now = num.floor(time_float(time.time()))

        x = X(t=now)
        x2 = load_string(x.dump())

        assert isinstance(x2.t, get_time_float())

        x3 = load_string('''--- !guts_test.X
t: 2018-08-06 12:53:20
''')
        assert isinstance(x3.t, time_float)


def makeBasicTypeTest(Type, sample, sample_in=None, xml=False):

    if sample_in is None:
        sample_in = sample

    def basicTypeTest(self):

        class X(Object):
            a = Type.T()
            b = Type.T(optional=True)
            c = Type.T(default=sample)
            d = List.T(Type.T())
            e = Tuple.T(1, Type.T())
            xmltagname = 'x'

        x = X(a=sample_in, e=(sample_in,))
        x.d.append(sample_in)
        if sample_in is not sample:
            with self.assertRaises(ValidationError):
                x.validate()

        x.validate(regularize=sample_in is not sample)
        self.assertEqualNanAware(sample, x.a)

        if not xml:
            x2 = load_string(x.dump())

        else:
            x2 = load_xml_string(x.dump_xml())

        self.assertEqualNanAware(x.a, x2.a)
        self.assertIsNone(x.b)
        self.assertIsNone(x2.b)
        self.assertEqualNanAware(sample, x.c)
        self.assertEqualNanAware(sample, x2.c)
        self.assertTrue(isinstance(x.d, list))
        self.assertTrue(isinstance(x2.d, list))
        self.assertEqualNanAware(x.d[0], sample)
        self.assertEqualNanAware(x2.d[0], sample)
        self.assertEqual(len(x.d), 1)
        self.assertEqual(len(x2.d), 1)
        self.assertTrue(isinstance(x.e, tuple))
        self.assertTrue(isinstance(x2.e, tuple))
        self.assertEqualNanAware(x.e[0], sample)
        self.assertEqualNanAware(x2.e[0], sample)
        self.assertEqual(len(x.e), 1)
        self.assertEqual(len(x2.e), 1)

    return basicTypeTest


for Type in samples:
    for isample, sample in enumerate(samples[Type]):
        for xml in (False, True):
            name = 'testBasicType' + Type.__name__ + str(isample) \
                + ['', 'XML'][xml]
            func = makeBasicTypeTest(Type, sample, xml=xml)
            func.__name__ = name
            setattr(GutsTestCase, name, func)
            del func

for Type in regularize:
    for isample, (sample_in, sample) in enumerate(regularize[Type]):
        for xml in (False, True):
            name = 'testBasicTypeRegularize' + Type.__name__ + str(isample) \
                + ['', 'XML'][xml]
            func = makeBasicTypeTest(
                Type, sample, sample_in=sample_in, xml=xml)
            func.__name__ = name
            setattr(GutsTestCase, name, func)
            del func


if __name__ == '__main__':
    unittest.main()
