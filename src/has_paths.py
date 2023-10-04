# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Support for relative paths in :py:mod:`~pyrocko.guts`-based configuration
files.
'''

from .guts import Object, String
import os.path as op

guts_prefix = 'pf'


def xjoin(basepath, path):
    if path is None and basepath is not None:
        return basepath
    elif op.isabs(path) or basepath is None:
        return path
    else:
        return op.join(basepath, path)


def xrelpath(path, start):
    if op.isabs(path):
        return path
    else:
        return op.relpath(path, start)


class Path(String):
    pass


class HasPaths(Object):
    path_prefix = Path.T(optional=True)

    def __init__(self, *args, **kwargs):
        Object.__init__(self, *args, **kwargs)
        self._basepath = None
        self._parent_path_prefix = None

    def ichildren(self):
        for (prop, val) in self.T.ipropvals(self):
            if isinstance(val, HasPaths):
                yield val

            elif prop.multivalued and val is not None:
                for ele in val:
                    if isinstance(ele, HasPaths):
                        yield ele

    def effective_path_prefix(self):
        return self.path_prefix or self._parent_path_prefix

    def set_basepath(self, basepath, parent_path_prefix=None):
        self._basepath = basepath
        self._parent_path_prefix = parent_path_prefix
        for val in self.ichildren():
            val.set_basepath(
                basepath, self.effective_path_prefix())

    def set_basepath_from(self, other):
        self.set_basepath(other.get_basepath(), other.effective_path_prefix())

    def get_basepath(self):
        assert self._basepath is not None

        return self._basepath

    def change_basepath(self, new_basepath, parent_path_prefix=None):
        assert self._basepath is not None

        self._parent_path_prefix = parent_path_prefix
        if self.path_prefix or not self._parent_path_prefix:

            self.path_prefix = op.normpath(xjoin(xrelpath(
                self._basepath, new_basepath), self.path_prefix))

        for val in self.ichildren():
            val.change_basepath(new_basepath, self.effective_path_prefix())

        self._basepath = new_basepath

    def expand_path(self, path, extra=None):
        assert self._basepath is not None

        if extra is None:
            def extra(path):
                return path

        path_prefix = self.effective_path_prefix()

        if path is None:
            return None

        elif isinstance(path, str):
            return extra(
                op.normpath(xjoin(self._basepath, xjoin(path_prefix, path))))
        else:
            return [
                extra(
                    op.normpath(xjoin(self._basepath, xjoin(path_prefix, p))))
                for p in path]

    def rel_path(self, path):
        return xrelpath(path, self.get_basepath())
