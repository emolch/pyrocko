# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
Helper classes to implement simple processing pipelines with cacheing.
'''


class Stage(object):
    def __init__(self, f):
        self._f = f
        self._parent = None
        self._cache = {}

    def __call__(self, *x, **kwargs):
        if kwargs.get('nocache', False):
            return self.call_nocache(*x)

        if x not in self._cache:
            if self._parent is not None:
                self._cache[x] = self._f(self._parent(*x[:-1]), *x[-1])
            else:
                self._cache[x] = self._f(*x[-1])

        return self._cache[x]

    def call_nocache(self, *x):
        if self._parent is not None:
            return self._f(self._parent.call_nocache(*x[:-1]), *x[-1])
        else:
            return self._f(*x[-1])

    def clear(self):
        self._cache.clear()


class Chain(object):
    def __init__(self, *stages):
        parent = None
        self.stages = []
        for stage in stages:
            if not isinstance(stage, Stage):
                stage = Stage(stage)

            stage._parent = parent
            parent = stage
            self.stages.append(stage)

    def clear(self):
        for stage in self.stages:
            stage.clear()

    def __call__(self, *x, **kwargs):
        return self.stages[len(x)-1](*x, **kwargs)
