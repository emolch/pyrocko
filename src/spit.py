# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

'''
N-dimensional space partitioning multi-linear interpolator.
'''

import struct
import logging
import numpy as num

try:
    range = xrange
except NameError:
    pass

logger = logging.getLogger('pyrocko.spit')

or_ = num.logical_or
and_ = num.logical_and
not_ = num.logical_not
all_ = num.all
any_ = num.any


class OutOfBounds(Exception):
    pass


class Cell(object):
    def __init__(self, tree, index, f=None):
        self.tree = tree
        self.index = index
        self.depths = num.log2(index).astype(int)
        self.bad = False
        self.children = []
        n = 2**self.depths
        i = self.index - n
        delta = (self.tree.xbounds[:, 1] - self.tree.xbounds[:, 0])/n
        xmin = self.tree.xbounds[:, 0]
        self.xbounds = self.tree.xbounds.copy()
        self.xbounds[:, 0] = xmin + i * delta
        self.xbounds[:, 1] = xmin + (i+1) * delta
        self.a = self.xbounds[:, ::-1].copy()
        self.b = self.a.copy()
        self.b[:, 1] = self.xbounds[:, 1] - self.xbounds[:, 0]
        self.b[:, 0] = - self.b[:, 1]

        self.a[:, 0] += (self.b[:, 0] == 0.0)*0.5
        self.a[:, 1] -= (self.b[:, 1] == 0.0)*0.5
        self.b[:, 0] -= (self.b[:, 0] == 0.0)
        self.b[:, 1] += (self.b[:, 1] == 0.0)

        if f is None:
            it = nditer_outer(tuple(self.xbounds) + (None,))
            for vvv in it:
                vvv[-1][...] = self.tree._f_cached(vvv[:-1])

            self.f = it.operands[-1]
        else:
            self.f = f

    def interpolate(self, x):
        if self.children:
            for cell in self.children:
                if all_(and_(cell.xbounds[:, 0] <= x,
                        x <= cell.xbounds[:, 1])):
                    return cell.interpolate(x)

        else:
            if all_(num.isfinite(self.f)):
                ws = (x[:, num.newaxis] - self.a)/self.b
                wn = num.multiply.reduce(
                    num.array(num.ix_(*ws), dtype=object))
                return num.sum(self.f * wn)
            else:
                return None

    def interpolate_many(self, x):
        if self.children:
            result = num.empty(x.shape[0], dtype=float)
            result[:] = None
            for cell in self.children:
                indices = num.where(
                    self.tree.ndim == num.sum(and_(
                        cell.xbounds[:, 0] <= x,
                        x <= cell.xbounds[:, 1]), axis=-1))[0]

                if indices.size != 0:
                    result[indices] = cell.interpolate_many(x[indices])

            return result

        else:
            if all_(num.isfinite(self.f)):
                ws = (x[..., num.newaxis] - self.a)/self.b
                npoints = ws.shape[0]
                ndim = self.tree.ndim
                ws_pimped = [ws[:, i, :] for i in range(ndim)]
                for i in range(ndim):
                    s = [npoints] + [1] * ndim
                    s[1+i] = 2
                    ws_pimped[i].shape = tuple(s)

                wn = ws_pimped[0]
                for idim in range(1, ndim):
                    wn = wn * ws_pimped[idim]

                result = wn * self.f
                for i in range(ndim):
                    result = num.sum(result, axis=-1)

                return result
            else:
                result = num.empty(x.shape[0], dtype=float)
                result[:] = None
                return result

    def slice(self, x):
        x = num.array(x, dtype=float)
        x_mask = not_(num.isfinite(x))
        x_ = x.copy()
        x_[x_mask] = 0.0
        return [
            cell for cell in self.children if all_(or_(
                x_mask,
                and_(
                    cell.xbounds[:, 0] <= x_,
                    x_ <= cell.xbounds[:, 1])))]

    def plot_rects(self, axes, x, dims):
        if self.children:
            for cell in self.slice(x):
                cell.plot_rects(axes, x, dims)

        else:
            points = []
            for iy, ix in ((0, 0), (0, 1), (1, 1), (1, 0), (0, 0)):
                points.append(
                    (self.xbounds[dims[0], iy], self.xbounds[dims[1], ix]))

            points = num.transpose(points)
            axes.plot(points[1], points[0], color=(0.1, 0.1, 0.0, 0.1))

    def check_holes(self):
        '''
        Check if :py:class:`Cell` or its children contain NaNs.
        '''
        if self.children:
            return any([child.check_holes() for child in self.children])
        else:
            return num.any(num.isnan(self.f))

    def plot_2d(self, axes, x, dims):
        idims = num.array(dims)
        self.plot_rects(axes, x, dims)
        coords = [
            num.linspace(xb[0], xb[1], 1+int((xb[1]-xb[0])/d))
            for (xb, d) in zip(self.xbounds[idims, :], self.tree.xtols[idims])]

        npoints = coords[0].size * coords[1].size
        g = num.meshgrid(*coords[::-1])[::-1]
        points = num.empty((npoints, self.tree.ndim), dtype=float)
        for idim in range(self.tree.ndim):
            try:
                idimout = dims.index(idim)
                points[:, idim] = g[idimout].ravel()
            except ValueError:
                points[:, idim] = x[idim]

        fi = num.empty((coords[0].size, coords[1].size), dtype=float)
        fi_r = fi.ravel()
        fi_r[...] = self.interpolate_many(points)

        if num.any(num.isnan(fi)):
            logger.warning('')
        if any_(num.isfinite(fi)):
            fi = num.ma.masked_invalid(fi)
            axes.imshow(
                fi, origin='lower',
                extent=[coords[1].min(), coords[1].max(),
                        coords[0].min(), coords[0].max()],
                interpolation='nearest',
                aspect='auto',
                cmap='RdYlBu')

    def plot_1d(self, axes, x, dim):
        xb = self.xbounds[dim]
        d = self.tree.xtols[dim]
        coords = num.linspace(xb[0], xb[1], 1+int((xb[1]-xb[0])/d))

        npoints = coords.size
        points = num.empty((npoints, self.tree.ndim), dtype=float)
        for idim in range(self.tree.ndim):
            if idim == dim:
                points[:, idim] = coords
            else:
                points[:, idim] = x[idim]

        fi = self.interpolate_many(points)
        if any_(num.isfinite(fi)):
            fi = num.ma.masked_invalid(fi)
            axes.plot(coords, fi)

    def __iter__(self):
        yield self
        for c in self.children:
            for x in c:
                yield x

    def dump(self, file):
        self.index.astype('<i4').tofile(file)
        self.f.astype('<f8').tofile(file)
        for c in self.children:
            c.dump(file)


def bread(f, fmt):
    s = f.read(struct.calcsize(fmt))
    return struct.unpack(fmt, s)


class SPTree(object):
    '''
    N-dimensional space partitioning interpolator.

    :param f: callable function ``f(x)`` where ``x`` is a vector of size ``n``
    :param ftol: target accuracy ``|f_interp(x) - f(x)| <= ftol``
    :param xbounds: bounds of ``x``, shape ``(n, 2)``
    :param xtols: target coarsenesses in ``x``, vector of size ``n``
    :param addargs: additional arguments to pass to ``f``
    '''

    def __init__(self, f=None, ftol=None, xbounds=None, xtols=None,
                 filename=None, addargs=()):

        if filename is None:
            assert all(v is not None for v in (f, ftol, xbounds, xtols))

            self.f = f
            self.ftol = float(ftol)
            self.f_values = {}
            self.ncells = 0
            self.addargs = addargs

            self.xbounds = num.asarray(xbounds, dtype=float)
            assert self.xbounds.ndim == 2
            assert self.xbounds.shape[1] == 2
            self.ndim = self.xbounds.shape[0]

            self.xtols = num.asarray(xtols, dtype=float)
            assert self.xtols.ndim == 1 and self.xtols.size == self.ndim

            self.maxdepths = num.ceil(num.log2(
                num.maximum(
                    1.0,
                    (self.xbounds[:, 1] - self.xbounds[:, 0]) / self.xtols)
                )).astype(int)

            self.root = None
            self.ones_int = num.ones(self.ndim, dtype=int)

            cc = num.ix_(*[num.arange(3)]*self.ndim)
            w = num.zeros([3]*self.ndim + [self.ndim, 2])
            for i, c in enumerate(cc):
                w[..., i, 0] = (2-c)*0.5
                w[..., i, 1] = c*0.5

            self.pointmaker = w
            self.pointmaker_mask = num.sum(w[..., 0] == 0.5, axis=-1) != 0
            self.pointmaker_masked = w[self.pointmaker_mask]

            self.nothing_found_yet = True

            self.root = Cell(self, self.ones_int)
            self.ncells += 1

            self.fraction_bad = 0.0
            self.nbad = 0
            self.cells_to_continue = []
            for clipdepth in range(0, num.max(self.maxdepths)+1):
                self.clipdepth = clipdepth
                self.tested = 0
                if self.clipdepth == 0:
                    self._fill(self.root)
                else:
                    self._continue_fill()

                self.status()

                if not self.cells_to_continue:
                    break

        else:
            self._load(filename)

    def status(self):
        perc = (1.0-self.fraction_bad)*100
        s = '%6.1f%%' % perc

        if self.fraction_bad != 0.0 and s == ' 100.0%':
            s = '~100.0%'

        logger.info('at level %2i: %s covered, %6i cell%s' % (
            self.clipdepth, s, self.ncells, ['s', ''][self.ncells == 1]))

    def __iter__(self):
        return iter(self.root)

    def __len__(self):
        return self.ncells

    def dump(self, filename):
        with open(filename, 'wb') as file:
            version = 1
            file.write(b'SPITREE ')
            file.write(struct.pack(
                '<QQQd', version, self.ndim, self.ncells, self.ftol))
            self.xbounds.astype('<f8').tofile(file)
            self.xtols.astype('<f8').tofile(file)
            self.root.dump(file)

    def _load(self, filename):
        with open(filename, 'rb') as file:
            marker, version, self.ndim, self.ncells, self.ftol = bread(
                file, '<8sQQQd')
            assert marker == b'SPITREE '
            assert version == 1
            self.xbounds = num.fromfile(
                file, dtype='<f8', count=self.ndim*2).reshape(self.ndim, 2)
            self.xtols = num.fromfile(
                file, dtype='<f8', count=self.ndim)

            path = []
            for icell in range(self.ncells):
                index = num.fromfile(
                    file, dtype='<i4', count=self.ndim)
                f = num.fromfile(
                    file, dtype='<f8', count=2**self.ndim).reshape(
                        [2]*self.ndim)

                cell = Cell(self, index, f)
                if not path:
                    self.root = cell
                    path.append(cell)

                else:
                    while not any_(path[-1].index == (cell.index >> 1)):
                        path.pop()

                    path[-1].children.append(cell)
                    path.append(cell)

    def _f_cached(self, x):
        return getset(
            self.f_values, tuple(float(xx) for xx in x), self.f, self.addargs)

    def interpolate(self, x):
        x = num.asarray(x, dtype=float)
        assert x.ndim == 1 and x.size == self.ndim
        if not all_(and_(self.xbounds[:, 0] <= x, x <= self.xbounds[:, 1])):
            raise OutOfBounds()

        return self.root.interpolate(x)

    def __call__(self, x):
        return self.interpolate(x)

    def interpolate_many(self, x):
        return self.root.interpolate_many(x)

    def _continue_fill(self):
        cells_to_continue, self.cells_to_continue = self.cells_to_continue, []
        for cell in cells_to_continue:
            self._deepen_cell(cell)

    def _fill(self, cell):

        self.tested += 1
        xtestpoints = num.sum(cell.xbounds * self.pointmaker_masked, axis=-1)

        fis = cell.interpolate_many(xtestpoints)
        fes = num.array(
            [self._f_cached(x) for x in xtestpoints], dtype=float)

        iffes = num.isfinite(fes)
        iffis = num.isfinite(fis)
        works = iffes == iffis
        iif = num.logical_and(iffes, iffis)

        works[iif] *= num.abs(fes[iif] - fis[iif]) < self.ftol

        nundef = num.sum(not_(num.isfinite(fes))) + \
            num.sum(not_(num.isfinite(cell.f)))

        some_undef = 0 < nundef < (xtestpoints.shape[0] + cell.f.size)

        if any_(works):
            self.nothing_found_yet = False

        if not all_(works) or some_undef or self.nothing_found_yet:
            deepen = self.ones_int.copy()
            if not some_undef:
                works_full = num.ones([3]*self.ndim, dtype=bool)
                works_full[self.pointmaker_mask] = works
                for idim in range(self.ndim):
                    dimcorners = [slice(None, None, 2)] * self.ndim
                    dimcorners[idim] = 1
                    if all_(works_full[tuple(dimcorners)]):
                        deepen[idim] = 0

            if not any_(deepen):
                deepen = self.ones_int

            deepen = num.where(
                cell.depths + deepen > self.maxdepths, 0, deepen)

            cell.deepen = deepen

            if any_(deepen) and all_(cell.depths + deepen <= self.clipdepth):
                self._deepen_cell(cell)
            else:
                if any_(deepen):
                    self.cells_to_continue.append(cell)

                cell.bad = True
                self.fraction_bad += num.prod(1.0/2**cell.depths)
                self.nbad += 1

    def _deepen_cell(self, cell):
        if cell.bad:
            self.fraction_bad -= num.prod(1.0/2**cell.depths)
            self.nbad -= 1
            cell.bad = False

        for iadd in num.ndindex(*(cell.deepen+1)):
            index_child = (cell.index << cell.deepen) + iadd
            child = Cell(self, index_child)
            self.ncells += 1
            cell.children.append(child)
            self._fill(child)

    def check_holes(self):
        '''
        Check for NaNs in :py:class:`SPTree`
        '''
        return self.root.check_holes()

    def plot_2d(self, axes=None, x=None, dims=None):
        assert self.ndim >= 2

        if x is None:
            x = num.zeros(self.ndim)
            x[-2:] = None

        x = num.asarray(x, dtype=float)
        if dims is None:
            dims = [i for (i, v) in enumerate(x) if not num.isfinite(v)]

        assert len(dims) == 2

        plt = None
        if axes is None:
            from matplotlib import pyplot as plt
            axes = plt.gca()

        self.root.plot_2d(axes, x, dims)

        axes.set_xlabel('Dim %i' % dims[1])
        axes.set_ylabel('Dim %i' % dims[0])

        if plt:
            plt.show()

    def plot_1d(self, axes=None, x=None, dims=None):

        if x is None:
            x = num.zeros(self.ndim)
            x[-1:] = None

        x = num.asarray(x, dtype=float)
        if dims is None:
            dims = [i for (i, v) in enumerate(x) if not num.isfinite(v)]

        assert len(dims) == 1

        plt = None
        if axes is None:
            from matplotlib import pyplot as plt
            axes = plt.gca()

        self.root.plot_1d(axes, x, dims[0])

        axes.set_xlabel('Dim %i' % dims[0])

        if plt:
            plt.show()


def getset(d, k, f, addargs):
    try:
        return d[k]
    except KeyError:
        v = d[k] = f(k, *addargs)
        return v


def nditer_outer(x):
    add = []
    if x[-1] is None:
        x_ = x[:-1]
        add = [None]
    else:
        x_ = x

    return num.nditer(
        x,
        op_axes=(num.identity(len(x_), dtype=int)-1).tolist() + add)


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    def f(x):
        x0 = num.array([0.5, 0.5, 0.5])
        r = 0.5
        if num.sqrt(num.sum((x-x0)**2)) < r:

            return x[2]**4 + x[1]

        return None

    tree = SPTree(f, 0.01, [[0., 1.], [0., 1.], [0., 1.]], [0.025, 0.05, 0.1])

    import tempfile
    import os
    fid, fn = tempfile.mkstemp()
    tree.dump(fn)
    tree = SPTree(filename=fn)
    os.unlink(fn)

    from matplotlib import pyplot as plt

    v = 0.5
    axes = plt.subplot(2, 2, 1)
    tree.plot_2d(axes, x=(v, None, None))
    axes = plt.subplot(2, 2, 2)
    tree.plot_2d(axes, x=(None, v, None))
    axes = plt.subplot(2, 2, 3)
    tree.plot_2d(axes, x=(None, None, v))

    axes = plt.subplot(2, 2, 4)
    tree.plot_1d(axes, x=(v, v, None))

    plt.show()
