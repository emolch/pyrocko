# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

from pyrocko.guts import Object, List
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


class TalkieRoot(Talkie):

    def __init__(self, **kwargs):
        self._listeners = listdict()
        Talkie.__init__(self, **kwargs)

    def add_listener(self, listener, path=''):
        self._listeners[path].append(ref(listener))

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

        def meth(self, *args):
            retval = list_meth(self, *args)
            self.fire([], self)
            return retval

        return meth

    try:
        setattr(TalkieList, method_name, x())
    except AttributeError:
        pass
