# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import difflib

from pyrocko.guts import Object, List, clone
from weakref import ref


class listdict(dict):
    def __missing__(self, k):
        self[k] = []
        return self[k]


def root_and_path(obj, name=None):
    root = obj
    path = []
    if name is not None:
        path.append(name)

    while True:
        try:
            root, name_at_parent = root._talkie_parent
            path.append(name_at_parent)
        except AttributeError:
            break

    return root, '.'.join(path[::-1])


def lclone(xs):
    [clone(x) for x in xs]


g_uid = 0


def new_uid():
    global g_uid
    g_uid += 1
    return '#%i' % g_uid


class Talkie(Object):

    def __setattr__(self, name, value):
        try:
            t = self.T.get_property(name)
        except ValueError:
            Object.__setattr__(self, name, value)
            return

        if isinstance(t, List.T):
            value = TalkieList(value)

        oldvalue = getattr(self, name, None)
        if oldvalue:
            if isinstance(oldvalue, (Talkie, TalkieList)):
                oldvalue.unset_parent()

        if isinstance(value, (Talkie, TalkieList)):
            value.set_parent(self, name)

        Object.__setattr__(self, name, value)
        self.fire([name], value)

    def fire(self, path, value):
        self.fire_event(path, value)
        if hasattr(self, '_talkie_parent'):
            root, name_at_parent = self._talkie_parent
            path.append(name_at_parent)
            root.fire(path, value)

    def set_parent(self, parent, name):
        Object.__setattr__(self, '_talkie_parent', (parent, name))

    def unset_parent(self):
        Object.__delattr__(self, '_talkie_parent')

    def fire_event(self, path, value):
        pass

    def diff(self, other, path=()):
        assert type(self) is type(other), '%s %s' % (type(self), type(other))

        for (s_prop, s_val), (o_prop, o_val) in zip(
                self.T.ipropvals(self), other.T.ipropvals(other)):

            if not s_prop.multivalued:
                if isinstance(s_val, Talkie) \
                        and type(s_val) is type(o_val):

                    for x in s_val.diff(o_val, path + (s_prop.name,)):
                        yield x
                else:
                    if not equal(s_val, o_val):
                        yield 'set', path + (s_prop.name,), clone(o_val)
            else:
                if issubclass(s_prop.content_t.cls, Talkie):
                    sm = difflib.SequenceMatcher(
                        None,
                        type_eq_proxy_seq(s_val),
                        type_eq_proxy_seq(o_val))
                    mode = 1

                else:
                    sm = difflib.SequenceMatcher(
                        None,
                        eq_proxy_seq(s_val),
                        eq_proxy_seq(o_val))
                    mode = 2

                for tag, i1, i2, j1, j2 in list(sm.get_opcodes()):
                    if tag == 'equal' and mode == 1:
                        for koff, (s_element, o_element) in enumerate(zip(
                                s_val[i1:i2], o_val[j1:j2])):

                            for x in s_element.diff(
                                    o_element,
                                    path + ((s_prop.name, i1+koff),)):
                                yield x

                    if tag == 'replace':
                        yield (
                            'replace',
                            path + ((s_prop.name, i1, i2),),
                            lclone(o_val[j1:j2]))

                    elif tag == 'delete':
                        yield (
                            'delete',
                            path + ((s_prop.name, i1, i2),),
                            None)

                    elif tag == 'insert':
                        yield (
                            'insert',
                            path + ((s_prop.name, i1, i2)),
                            lclone(o_val[j1:j2]))

    def diff_update(self, other, path=()):
        assert type(self) is type(other), '%s %s' % (type(self), type(other))

        for (s_prop, s_val), (o_prop, o_val) in zip(
                self.T.ipropvals(self), other.T.ipropvals(other)):

            if not s_prop.multivalued:
                if isinstance(s_val, Talkie) \
                        and type(s_val) is type(o_val):

                    s_val.diff_update(o_val, path + (s_prop.name,))
                else:
                    if not equal(s_val, o_val):
                        setattr(self, s_prop.name, clone(o_val))
            else:
                if issubclass(s_prop.content_t.cls, Talkie):
                    sm = difflib.SequenceMatcher(
                        None,
                        type_eq_proxy_seq(s_val),
                        type_eq_proxy_seq(o_val))
                    mode = 1

                else:
                    sm = difflib.SequenceMatcher(
                        None,
                        eq_proxy_seq(s_val),
                        eq_proxy_seq(o_val))
                    mode = 2

                ioff = 0
                for tag, i1, i2, j1, j2 in list(sm.get_opcodes()):
                    if tag == 'equal' and mode == 1:
                        for koff, (s_element, o_element) in enumerate(zip(
                                s_val[i1+ioff:i2+ioff], o_val[j1:j2])):

                            s_element.diff_update(
                                o_element,
                                path + ((s_prop.name, i1+ioff+koff),))

                    elif tag == 'replace':
                        for _ in range(i1, i2):
                            s_val.pop(i1+ioff)

                        for j in range(j1, j2):
                            s_val.insert(i1+ioff, clone(o_val[j]))

                        ioff += (j2 - j1) - (i2 - i1)

                    elif tag == 'delete':
                        for _ in range(i1, i2):
                            s_val.pop(i1 + ioff)

                        ioff -= (i2 - i1)

                    elif tag == 'insert':
                        for j in range(j1, j2):
                            s_val.insert(i1+ioff, clone(o_val[j]))

                        ioff += (j2 - j1)


def equal(a, b):
    return str(a) == str(b)  # to be replaced by recursive guts.equal


def ghash(obj):
    return hash(str(obj))


class GutsEqProxy(object):
    def __init__(self, obj):
        self._obj = obj

    def __eq__(self, other):
        return equal(self._obj, other._obj)

    def __hash__(self):
        return ghash(self._obj)


class TypeEqProxy(object):
    def __init__(self, obj):
        self._obj = obj

    def __eq__(self, other):
        return type(self._obj) is type(other._obj)  # noqa

    def __hash__(self):
        return hash(type(self._obj))


def eq_proxy_seq(seq):
    return list(GutsEqProxy(x) for x in seq)


def type_eq_proxy_seq(seq):
    return list(TypeEqProxy(x) for x in seq)


class ListenerRef(object):
    def __init__(self, talkie_root, listener, path, ref_listener):
        self._talkie_root = talkie_root
        self._listener = listener
        self._path = path
        self._ref_listener = ref_listener

    def release(self):
        self._talkie_root.remove_listener(self)


class TalkieRoot(Talkie):

    def __init__(self, **kwargs):
        self._listeners = listdict()
        Talkie.__init__(self, **kwargs)

    def add_listener(self, listener, path=''):
        ref_listener = ref(listener)
        self._listeners[path].append(ref_listener)
        return ListenerRef(self, listener, path, ref_listener)

    def remove_listener(self, listener_ref):
        self._listeners[listener_ref.path].remove(listener_ref.ref_listener)

    def fire_event(self, path, value):
        path = '.'.join(path[::-1])
        # print('fire_event:', path, value)
        parts = path.split('.')
        for i in range(len(parts)+1):
            subpath = '.'.join(parts[:i])
            target_refs = self._listeners[subpath]
            delete = []
            for target_ref in target_refs:
                target = target_ref()
                if target:
                    target(path, value)
                else:
                    delete.append(target_ref)

            for target_ref in delete:
                target_refs.remove(target_ref)

    def get(self, path):
        x = self
        for s in path.split('.'):
            x = getattr(x, s)

        return x

    def set(self, path, value):
        x = self
        p = path.split('.')
        for s in p[:-1]:
            x = getattr(x, s)

        setattr(x, p[-1], value)


class TalkieList(list):

    def fire(self, path, value):
        if self._talkie_parent:
            root, name_at_parent = self._talkie_parent
            path.append(name_at_parent)
            root.fire(path, value)

    def set_parent(self, parent, name):
        list.__setattr__(self, '_talkie_parent', (parent, name))

    def unset_parent(self):
        list.__delattr__(self, '_talkie_parent')

    def append(self, element):
        retval = list.append(self, element)
        name = new_uid()
        if isinstance(element, (Talkie, TalkieList)):
            element.set_parent(self, name)

        self.fire([], self)
        return retval

    def insert(self, index, element):
        retval = list.insert(self, index, element)
        name = new_uid()
        if isinstance(element, (Talkie, TalkieList)):
            element.set_parent(self, name)

        self.fire([], self)
        return retval

    def remove(self, element):
        list.remove(self, element)
        if isinstance(element, (Talkie, TalkieList)):
            element.unset_parent()

        self.fire([], self)

    def pop(self, index=-1):
        element = list.pop(self, index)
        if isinstance(element, (Talkie, TalkieList)):
            element.unset_parent()

        self.fire([], self)
        return element

    def extend(self, elements):
        for element in elements:
            self.append(element)

        self.fire([], self)

    def __setitem__(self, key, value):
        try:
            element = self[key]
            if isinstance(element, (Talkie, TalkieList)):
                element.unset_parent()

        except IndexError:
            pass

        list.__setitem__(self, key, value)
        self.fire([], self)

    def __setslice__(self, *args, **kwargs):
        raise Exception('not implemented')

    def __iadd__(self, *args, **kwargs):
        raise Exception('not implemented')

    def __imul__(self, *args, **kwargs):
        raise Exception('not implemented')


for method_name in ['reverse', 'sort']:

    def x():
        list_meth = getattr(list, method_name)

        def meth(self, *args, **kwargs):
            retval = list_meth(self, *args, **kwargs)
            self.fire([], self)
            return retval

        return meth

    try:
        setattr(TalkieList, method_name, x())
    except AttributeError:
        pass
