
from pyrocko import guts
from pyrocko.io.io_common import FileLoadError


def load(path, want=None):
    obj = guts.load(filename=path)
    if want is not None and not isinstance(obj, want):
        raise FileLoadError(
            'Object in file "%s" must be of type "%s".' % (
                path, want.__name__))

    return obj


def load_all(path, want=None):
    objects = guts.load_all(filename=path)

    if want is not None and not all(isinstance(obj, want) for obj in objects):
        raise FileLoadError(
            'All objects in file "%s" must be of type "%s".' % (
                path, want.__name__))

    return objects


__all__ = [
    'load',
    'load_all',
]
