# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Data-model free processing of :py:mod:`pyrocko.guts` generated YAML files.
'''

import copy

try:
    from yaml import CSafeLoader as SafeLoader, CSafeDumper as SafeDumper
except ImportError:
    from yaml import SafeLoader, SafeDumper

from pyrocko import guts


class AgnosticSafeLoader(SafeLoader):
    pass


class AgnosticSafeDumper(SafeDumper):
    pass


class xstr(str):
    pass


def to_xstr(x):
    if isinstance(x, str):
        return xstr(x)
    elif isinstance(x, list):
        return [to_xstr(e) for e in x]
    elif isinstance(x, dict):
        return dict((k, to_xstr(v)) for (k, v) in x.items())
    else:
        return x


def quoted_presenter(dumper, data):
    return dumper.represent_scalar(
        'tag:yaml.org,2002:str', str(data), style="'")


AgnosticSafeDumper.add_representer(xstr, quoted_presenter)


class Object(object):

    def __init__(self, tagname, inamevals):
        self._tagname = tagname
        self._data = []
        for kv in inamevals:
            self._data.append(list(kv))

    def inamevals_to_save(self):
        for k, v in self._data:
            yield (k, to_xstr(v))

    def inamevals(self):
        for k, v in self._data:
            yield (k, v)

    def __iter__(self):
        for k, _ in self._data:
            yield k

    def rename_attribute(self, old, new):
        for kv in self._data:
            if kv[0] == old:
                kv[0] = new

    def drop_attribute(self, k):
        self._data = [kv for kv in self._data if kv[0] != k]

    def replace(self, other):
        self._tagname = other._tagname
        self._data = copy.deepcopy(other._data)

    def __setitem__(self, k, v):
        for kv in self._data:
            if kv[0] == k:
                kv[1] = v
                return

        self._data.append([k, v])

    def __getitem__(self, item):
        for kv in self._data:
            if kv[0] == item:
                return kv[1]

        raise KeyError(item)

    def get(self, *args):
        if len(args) == 1:
            return self.__getitem__(args[0])
        else:
            try:
                return self.__getitem__(args[0])
            except KeyError:
                return args[1]


def multi_representer(dumper, data):
    node = dumper.represent_mapping(
        '!'+data._tagname, data.inamevals_to_save(), flow_style=False)

    return node


def multi_constructor(loader, tag_suffix, node):
    tagname = str(tag_suffix)

    o = Object(tagname, loader.construct_pairs(node, deep=True))
    return o


AgnosticSafeDumper.add_multi_representer(Object, multi_representer)
AgnosticSafeLoader.add_multi_constructor('!', multi_constructor)


@guts.expand_stream_args('w')
def dump(*args, **kwargs):
    return guts._dump(Dumper=AgnosticSafeDumper, *args, **kwargs)


@guts.expand_stream_args('r')
def load(*args, **kwargs):
    return guts._load(Loader=AgnosticSafeLoader, *args, **kwargs)


def load_string(s, *args, **kwargs):
    return load(string=s, *args, **kwargs)


@guts.expand_stream_args('w')
def dump_all(*args, **kwargs):
    return guts._dump_all(Dumper=AgnosticSafeDumper, *args, **kwargs)


@guts.expand_stream_args('r')
def load_all(*args, **kwargs):
    return guts._load_all(Loader=AgnosticSafeLoader, *args, **kwargs)


@guts.expand_stream_args('r')
def iload_all(*args, **kwargs):
    return guts._iload_all(Loader=AgnosticSafeLoader, *args, **kwargs)


def walk(x, path=()):
    yield path, x

    if isinstance(x, Object):
        for (name, val) in x.inamevals():
            if isinstance(val, (list, tuple)):
                for iele, ele in enumerate(val):
                    for y in walk(ele, path=path + ((name, iele),)):
                        yield y
            elif isinstance(val, dict):
                for ele_k, ele_v in val.items():
                    for y in walk(ele_v, path=path + ((name, ele_k),)):
                        yield y
            else:
                for y in walk(val, path=path+(name,)):
                    yield y


def apply_tree(x, func, path=()):
    if isinstance(x, Object):
        for (name, val) in x.inamevals():
            if isinstance(val, (list, tuple)):
                for iele, ele in enumerate(val):
                    apply_tree(ele,  func, path=path + ((name, iele),))
            elif isinstance(val, dict):
                for ele_k, ele_v in val.items():
                    apply_tree(ele_v, func, path=path + ((name, ele_k),))
            else:
                apply_tree(val, func, path=path+(name,))

        func(path, x)
