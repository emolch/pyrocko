# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from math import pi as PI
import logging
import numpy as num

from matplotlib.collections import PatchCollection
from matplotlib.patches import Polygon
from matplotlib.transforms import Transform
from matplotlib.colors import LinearSegmentedColormap

from pyrocko import moment_tensor as mtm

logger = logging.getLogger('pyrocko.plot.beachball')

NA = num.newaxis
d2r = num.pi / 180.


def view_rotation(strike, dip):
    return mtm.euler_to_matrix(
        dip*d2r, strike*d2r, -90.*d2r)


_view_south = view_rotation(90., 90.)
_view_north = view_rotation(-90., 90.)
_view_east = view_rotation(0., 90.)
_view_west = view_rotation(180., 90.)


class BeachballError(Exception):
    pass


class _FixedPointOffsetTransform(Transform):
    def __init__(self, trans, dpi_scale_trans, fixed_point):
        Transform.__init__(self)
        self.input_dims = self.output_dims = 2
        self.has_inverse = False
        self.trans = trans
        self.dpi_scale_trans = dpi_scale_trans
        self.fixed_point = num.asarray(fixed_point, dtype=num.float64)

    def transform_non_affine(self, values):
        fp = self.trans.transform(self.fixed_point)
        return fp + self.dpi_scale_trans.transform(values)


def vnorm(points):
    return num.sqrt(num.sum(points**2, axis=1))


def clean_poly(points):
    if not num.all(points[0, :] == points[-1, :]):
        points = num.vstack((points, points[0:1, :]))

    dupl = num.concatenate(
        (num.all(points[1:, :] == points[:-1, :], axis=1), [False]))
    points = points[num.logical_not(dupl)]
    return points


def close_poly(points):
    if not num.all(points[0, :] == points[-1, :]):
        points = num.vstack((points, points[0:1, :]))

    return points


def circulation(points, axis):
    # assert num.all(points[:, axis] >= 0.0) or num.all(points[:, axis] <= 0.0)

    points2 = points[:, ((axis+2) % 3, (axis+1) % 3)].copy()
    points2 *= 1.0 / num.sqrt(1.0 + num.abs(points[:, axis]))[:, num.newaxis]

    result = -num.sum(
        (points2[1:, 0] - points2[:-1, 0]) *
        (points2[1:, 1] + points2[:-1, 1]))

    result -= (points2[0, 0] - points2[-1, 0]) \
        * (points2[0, 1] + points2[-1, 1])
    return result


def spoly_cut(l_points, axis=0, nonsimple=True, arcres=181):
    dphi = 2.*PI / (2*arcres)

    # cut sub-polygons and gather crossing point information
    crossings = []
    snippets = {}
    for ipath, points in enumerate(l_points):
        if not num.all(points[0, :] == points[-1, :]):
            points = num.vstack((points, points[0:1, :]))

        # get upward crossing points
        iup = num.where(num.logical_and(points[:-1, axis] <= 0.,
                                        points[1:, axis] > 0.))[0]
        aup = - points[iup, axis] / (points[iup+1, axis] - points[iup, axis])
        pup = points[iup, :] + aup[:, num.newaxis] * (points[iup+1, :] -
                                                      points[iup, :])
        phiup = num.arctan2(pup[:, (axis+2) % 3], pup[:, (axis+1) % 3])

        for i in range(len(iup)):
            crossings.append((phiup[i], ipath, iup[i], 1, pup[i], [1, -1]))

        # get downward crossing points
        idown = num.where(num.logical_and(points[:-1, axis] > 0.,
                                          points[1:, axis] <= 0.))[0]
        adown = - points[idown+1, axis] / (points[idown, axis] -
                                           points[idown+1, axis])
        pdown = points[idown+1, :] + adown[:, num.newaxis] * (
            points[idown, :] - points[idown+1, :])
        phidown = num.arctan2(pdown[:, (axis+2) % 3], pdown[:, (axis+1) % 3])

        for i in range(idown.size):
            crossings.append(
                (phidown[i], ipath, idown[i], -1, pdown[i], [1, -1]))

        icuts = num.sort(num.concatenate((iup, idown)))

        for i in range(icuts.size-1):
            snippets[ipath, icuts[i]] = (
                ipath, icuts[i+1], points[icuts[i]+1:icuts[i+1]+1])

        if icuts.size:
            points_last = num.concatenate((
                points[icuts[-1]+1:],
                points[:icuts[0]+1]))

            snippets[ipath, icuts[-1]] = (ipath, icuts[0], points_last)
        else:
            snippets[ipath, 0] = (ipath, 0, points)

    crossings.sort()

    # assemble new sub-polygons
    current = snippets.pop(list(snippets.keys())[0])
    outs = [[]]
    while True:
        outs[-1].append(current[2])
        for i, c1 in enumerate(crossings):
            if c1[1:3] == current[:2]:
                direction = -1 * c1[3]
                break
        else:
            if not snippets:
                break
            current = snippets.pop(list(snippets.keys())[0])
            outs.append([])
            continue

        while True:
            i = (i + direction) % len(crossings)
            if crossings[i][3] == direction and direction in crossings[i][-1]:
                break

        c2 = crossings[i]
        c2[-1].remove(direction)

        phi1 = c1[0]
        phi2 = c2[0]
        if direction == 1:
            if phi1 > phi2:
                phi2 += PI * 2.

        if direction == -1:
            if phi1 < phi2:
                phi2 -= PI * 2.

        n = int(abs(phi2 - phi1) / dphi) + 2

        phis = num.linspace(phi1, phi2, n)
        cpoints = num.zeros((n, 3))
        cpoints[:, (axis+1) % 3] = num.cos(phis)
        cpoints[:, (axis+2) % 3] = num.sin(phis)
        cpoints[:, axis] = 0.0

        outs[-1].append(cpoints)

        try:
            current = snippets[c2[1:3]]
            del snippets[c2[1:3]]

        except KeyError:
            if not snippets:
                break

            current = snippets.pop(list(snippets.keys())[0])
            outs.append([])

    # separate hemispheres, force polygons closed, remove duplicate points
    # remove polygons with less than 3 points (4, when counting repeated
    # endpoint)

    outs_upper = []
    outs_lower = []
    for out in outs:
        if out:
            out = clean_poly(num.vstack(out))
            if out.shape[0] >= 4:
                if num.sum(out[:, axis]) > 0.0:
                    outs_upper.append(out)
                else:
                    outs_lower.append(out)

    if nonsimple and (
            len(crossings) == 0 or
            len(outs_upper) == 0 or
            len(outs_lower) == 0):

        # check if we are cutting between holes
        need_divider = False
        if outs_upper:
            candis = sorted(
                outs_upper, key=lambda out: num.min(out[:, axis]))

            if circulation(candis[0], axis) > 0.0:
                need_divider = True

        if outs_lower:
            candis = sorted(
                outs_lower, key=lambda out: num.max(out[:, axis]))

            if circulation(candis[0], axis) < 0.0:
                need_divider = True

        if need_divider:
            phi1 = 0.
            phi2 = PI*2.
            n = int(abs(phi2 - phi1) / dphi) + 2

            phis = num.linspace(phi1, phi2, n)
            cpoints = num.zeros((n, 3))
            cpoints[:, (axis+1) % 3] = num.cos(phis)
            cpoints[:, (axis+2) % 3] = num.sin(phis)
            cpoints[:, axis] = 0.0

            outs_upper.append(cpoints)
            outs_lower.append(cpoints[::-1, :])

    return outs_lower, outs_upper


def numpy_rtp2xyz(rtp):
    r = rtp[:, 0]
    theta = rtp[:, 1]
    phi = rtp[:, 2]
    vecs = num.empty(rtp.shape, dtype=num.float64)
    vecs[:, 0] = r*num.sin(theta)*num.cos(phi)
    vecs[:, 1] = r*num.sin(theta)*num.sin(phi)
    vecs[:, 2] = r*num.cos(theta)
    return vecs


def numpy_xyz2rtp(xyz):
    x, y, z = xyz[:, 0], xyz[:, 1], xyz[:, 2]
    vecs = num.empty(xyz.shape, dtype=num.float64)
    vecs[:, 0] = num.sqrt(x**2+y**2+z**2)
    vecs[:, 1] = num.arctan2(num.sqrt(x**2+y**2), z)
    vecs[:, 2] = num.arctan2(y, x)
    return vecs


def circle_points(aphi, sign=1.0):
    vecs = num.empty((aphi.size, 3), dtype=num.float64)
    vecs[:, 0] = num.cos(sign*aphi)
    vecs[:, 1] = num.sin(sign*aphi)
    vecs[:, 2] = 0.0
    return vecs


def eig2gx(eig, arcres=181):
    aphi = num.linspace(0., 2.*PI, arcres)
    ep, en, et, vp, vn, vt = eig

    mt_sign = num.sign(ep + en + et)

    groups = []
    for (pt_name, pt_sign) in [('P', -1.), ('T', 1.)]:
        patches = []
        patches_lower = []
        patches_upper = []
        lines = []
        lines_lower = []
        lines_upper = []
        for iperm, (va, vb, vc, ea, eb, ec) in enumerate([
                (vp, vn, vt, ep, en, et),
                (vt, vp, vn, et, ep, en)]):  # (vn, vt, vp, en, et, ep)]):

            perm_sign = [-1.0, 1.0][iperm]
            to_e = num.vstack((vb, vc, va))
            from_e = to_e.T

            poly_es = []
            polys = []
            for sign in (-1., 1.):
                xphi = perm_sign*pt_sign*sign*aphi
                denom = eb*num.cos(xphi)**2 + ec*num.sin(xphi)**2
                if num.any(denom == 0.):
                    continue

                Y = -ea/denom
                if num.any(Y < 0.):
                    continue

                xtheta = num.arctan(num.sqrt(Y))
                rtp = num.empty(xphi.shape+(3,), dtype=num.float64)
                rtp[:, 0] = 1.
                if sign > 0:
                    rtp[:, 1] = xtheta
                else:
                    rtp[:, 1] = PI - xtheta

                rtp[:, 2] = xphi
                poly_e = numpy_rtp2xyz(rtp)
                poly = num.dot(from_e, poly_e.T).T
                poly[:, 2] -= 0.001

                poly_es.append(poly_e)
                polys.append(poly)

            if polys:
                polys_lower, polys_upper = spoly_cut(polys, 2, arcres=arcres)
                lines.extend(polys)
                lines_lower.extend(polys_lower)
                lines_upper.extend(polys_upper)

            if poly_es:
                for aa in spoly_cut(poly_es, 0, arcres=arcres):
                    for bb in spoly_cut(aa, 1, arcres=arcres):
                        for cc in spoly_cut(bb, 2, arcres=arcres):
                            for poly_e in cc:
                                poly = num.dot(from_e, poly_e.T).T
                                poly[:, 2] -= 0.001
                                polys_lower, polys_upper = spoly_cut(
                                    [poly], 2, nonsimple=False, arcres=arcres)

                                patches.append(poly)
                                patches_lower.extend(polys_lower)
                                patches_upper.extend(polys_upper)

        if not patches:
            if mt_sign * pt_sign == 1.:
                patches_lower.append(circle_points(aphi, -1.0))
                patches_upper.append(circle_points(aphi, 1.0))
                lines_lower.append(circle_points(aphi, -1.0))
                lines_upper.append(circle_points(aphi, 1.0))

        groups.append((
            pt_name,
            patches, patches_lower, patches_upper,
            lines, lines_lower, lines_upper))

    return groups


def eig2gx_singleforce(force, arcres=181):
    from pyrocko.moment_tensor import euler_to_matrix

    aphi = num.linspace(0., 2.*PI, arcres)

    groups = []
    for (pt_name, pt_sign) in [('P', -1.), ('T', 1.)]:
        patches = []
        patches_lower = []
        patches_upper = []
        lines = []
        lines_lower = []
        lines_upper = []

        force_length = num.linalg.norm(force)
        force *= 1. / force_length

        xphi = pt_sign * aphi

        alpha = num.arccos(num.dot(num.array([0., 0., 1.]), force))
        beta = num.arctan2(force[1], force[0])

        rotmat = euler_to_matrix(
            alpha=alpha,
            beta=beta + num.pi / 2.,
            gamma=0.)

        rtp = num.zeros(xphi.shape + (3,))
        rtp[:, 0] = 1.
        rtp[:, 1] = num.pi / 2.
        rtp[:, 2] = xphi

        xyz = numpy_rtp2xyz(rtp)

        poly = num.array([
            num.dot(xyz[i, :], rotmat) for i in range(xyz.shape[0])]).reshape(
            -1, 3)

        if False:
            import matplotlib.pyplot as plt
            from matplotlib import cm  # noqa
            from mpl_toolkits.mplot3d import Axes3D
            from matplotlib.patches import FancyArrowPatch
            from mpl_toolkits.mplot3d import proj3d

            class Arrow3D(FancyArrowPatch):
                def __init__(self, xs, ys, zs, *args, **kwargs):
                    FancyArrowPatch.__init__(
                        self, (0, 0), (0, 0), *args, **kwargs)
                    self._verts3d = xs, ys, zs

                def draw(self, renderer):
                    xs3d, ys3d, zs3d = self._verts3d
                    xs, ys, zs = proj3d.proj_transform(
                        xs3d, ys3d, zs3d, renderer.M)
                    self.set_positions((xs[0], ys[0]), (xs[1], ys[1]))
                    FancyArrowPatch.draw(self, renderer)

            fig = plt.figure()
            ax = Axes3D(fig, auto_add_to_figure=False)
            fig.add_axes(ax)
            ax.plot(xyz[:, 0], xyz[:, 1], xyz[:, 2], c='k')
            ax.plot(poly[:, 0], poly[:, 1], poly[:, 2], c='r')

            f = num.linalg.norm(force)
            force /= f

            a = Arrow3D(xs=[0, force[0]], ys=[0, force[1]], zs=[0, force[2]],
                        mutation_scale=20,
                        lw=3, arrowstyle="-|>", color="r")
            ax.add_artist(a)

            ax.set_xlabel('N')
            ax.set_ylabel('E')
            ax.set_zlabel('D')

            plt.draw()
            plt.show()

        polys = [poly]

        if polys:
            polys_lower, polys_upper = spoly_cut(polys, 2, arcres=arcres)
            lines.extend(polys)
            lines_lower.extend(polys_lower)
            lines_upper.extend(polys_upper)

            patches_lower.extend(polys_lower)
            patches_upper.extend(polys_upper)

        groups.append((
            pt_name,
            patches, patches_lower, patches_upper,
            lines, lines_lower, lines_upper))

    return groups


def extr(points):
    pmean = num.mean(points, axis=0)
    return points + pmean*0.05


def draw_eigenvectors_mpl(eig, axes):
    vp, vn, vt = eig[3:]
    for lab, v in [('P', vp), ('N', vn), ('T', vt)]:
        sign = num.sign(v[2]) + (v[2] == 0.0)
        axes.plot(sign*v[1], sign*v[0], 'o', color='black')
        axes.text(sign*v[1], sign*v[0], '  '+lab)


def project(points, projection='lambert'):
    '''
    Project 3D points to 2D.

    :param projection:
        Projection to use. Choices: ``'lambert'``, ``'stereographic'``,
        ``'orthographic'``.
    :type projection:
        str
    '''
    points_out = points[:, :2].copy()
    if projection == 'lambert':
        factor = 1.0 / num.sqrt(1.0 + points[:, 2])
    elif projection == 'stereographic':
        factor = 1.0 / (1.0 + points[:, 2])
    elif projection == 'orthographic':
        factor = None
    else:
        raise BeachballError(
            'invalid argument for projection: %s' % projection)

    if factor is not None:
        points_out *= factor[:, num.newaxis]

    return points_out


def inverse_project(points, projection='lambert'):
    points_out = num.zeros((points.shape[0], 3))

    rsqr = points[:, 0]**2 + points[:, 1]**2
    if projection == 'lambert':
        points_out[:, 2] = 1.0 - rsqr
        points_out[:, 1] = num.sqrt(2.0 - rsqr) * points[:, 1]
        points_out[:, 0] = num.sqrt(2.0 - rsqr) * points[:, 0]
    elif projection == 'stereographic':
        points_out[:, 2] = - (rsqr - 1.0) / (rsqr + 1.0)
        points_out[:, 1] = 2.0 * points[:, 1] / (rsqr + 1.0)
        points_out[:, 0] = 2.0 * points[:, 0] / (rsqr + 1.0)
    elif projection == 'orthographic':
        points_out[:, 2] = num.sqrt(num.maximum(1.0 - rsqr, 0.0))
        points_out[:, 1] = points[:, 1]
        points_out[:, 0] = points[:, 0]
    else:
        raise BeachballError(
            'invalid argument for projection: %s' % projection)

    return points_out


def deco_part(mt, mt_type='full', view='top'):
    mt = mtm.as_mt(mt)

    if isinstance(view, str):
        if view == 'top':
            pass
        elif view == 'north':
            mt = mt.rotated(_view_north)
        elif view == 'south':
            mt = mt.rotated(_view_south)
        elif view == 'east':
            mt = mt.rotated(_view_east)
        elif view == 'west':
            mt = mt.rotated(_view_west)
    elif isinstance(view, tuple):
        mt = mt.rotated(view_rotation(*view))
    else:
        raise BeachballError(
            'Invaild argument for `view`. Allowed values are "top", "north", '
            '"south", "east", "west" or a tuple of angles `(strike, dip)` '
            'orienting the view plane.')

    if mt_type == 'full':
        return mt

    res = mt.standard_decomposition()
    m = dict(
        dc=res[1][2],
        deviatoric=res[3][2])[mt_type]

    return mtm.MomentTensor(m=m)


def rotate_singleforce(force, view='top'):
    assert view in ('top',),\
        'Allowed views are top'

    assert view in ('top', 'north', 'south', 'east', 'west'),\
        'Allowed views are top, north, south, east and west'

    if view == 'top':
        pass
    elif view == 'north':
        force = num.dot(_view_north, force)
    elif view == 'south':
        force = num.dot(_view_south, force)
    elif view == 'east':
        force = num.dot(_view_east, force)
    elif view == 'west':
        force = num.dot(_view_west, force)

    return force


def choose_transform(axes, size_units, position, size):

    if size_units == 'points':
        transform = _FixedPointOffsetTransform(
            axes.transData,
            axes.figure.dpi_scale_trans,
            position)

        if size is None:
            size = 12.

        size = size * 0.5 / 72.
        position = (0., 0.)

    elif size_units == 'data':
        transform = axes.transData

        if size is None:
            size = 1.0

        size = size * 0.5

    elif size_units == 'axes':
        transform = axes.transAxes
        if size is None:
            size = 1.

        size = size * .5

    else:
        raise BeachballError(
            'invalid argument for size_units: %s' % size_units)

    position = num.asarray(position, dtype=num.float64)

    return transform, position, size


def mt2beachball(
        mt,
        beachball_type='deviatoric',
        position=(0., 0.),
        size=None,
        color_t='red',
        color_p='white',
        edgecolor='black',
        linewidth=2,
        projection='lambert',
        view='top'):

    position = num.asarray(position, dtype=num.float64)
    size = size or 1
    mt = deco_part(mt, beachball_type, view)

    eig = mt.eigensystem()
    if eig[0] == 0. and eig[1] == 0. and eig[2] == 0:
        raise BeachballError('eigenvalues are zero')

    data = []
    for (group, patches, patches_lower, patches_upper,
            lines, lines_lower, lines_upper) in eig2gx(eig):

        if group == 'P':
            color = color_p
        else:
            color = color_t

        for poly in patches_upper:
            verts = project(poly, projection)[:, ::-1] * size + \
                position[NA, :]
            data.append((verts, color, color, 1.0))

        for poly in lines_upper:
            verts = project(poly, projection)[:, ::-1] * size + \
                position[NA, :]
            data.append((verts, 'none', edgecolor, linewidth))
    return data


def plot_beachball_mpl(
        mt, axes,
        beachball_type='deviatoric',
        position=(0., 0.),
        size=None,
        zorder=0,
        color_t='red',
        color_p='white',
        edgecolor='black',
        linewidth=2,
        alpha=1.0,
        arcres=181,
        decimation=1,
        projection='lambert',
        size_units='points',
        view='top'):

    '''
    Plot beachball diagram to a Matplotlib plot

    :param mt: :py:class:`pyrocko.moment_tensor.MomentTensor` object or an
        array or sequence which can be converted into an MT object
    :param beachball_type: ``'deviatoric'`` (default), ``'full'``, or ``'dc'``
    :param position: position of the beachball in data coordinates
    :param size: diameter of the beachball either in points or in data
        coordinates, depending on the ``size_units`` setting
    :param zorder: (passed through to matplotlib drawing functions)
    :param color_t: color for compressional quadrants (default: ``'red'``)
    :param color_p: color for extensive quadrants (default: ``'white'``)
    :param edgecolor: color for lines (default: ``'black'``)
    :param linewidth: linewidth in points (default: ``2``)
    :param alpha: (passed through to matplotlib drawing functions)
    :param projection: ``'lambert'`` (default), ``'stereographic'``, or
        ``'orthographic'``
    :param size_units: ``'points'`` (default) or ``'data'``, where the
        latter causes the beachball to be projected in the plots data
        coordinates (axes must have an aspect ratio of 1.0 or the
        beachball will be shown distorted when using this).
    :param view: View the beachball from ``'top'``, ``'north'``, ``'south'``,
        ``'east'`` or ``'west'``, or project onto plane given by
        ``(strike, dip)``. Useful to show beachballs in cross-sections.
        Default is ``'top'``.
    '''

    transform, position, size = choose_transform(
        axes, size_units, position, size)

    mt = deco_part(mt, beachball_type, view)

    eig = mt.eigensystem()
    if eig[0] == 0. and eig[1] == 0. and eig[2] == 0:
        raise BeachballError('eigenvalues are zero')

    data = []
    for (group, patches, patches_lower, patches_upper,
            lines, lines_lower, lines_upper) in eig2gx(eig, arcres):

        if group == 'P':
            color = color_p
        else:
            color = color_t

        # plot "upper" features for lower hemisphere, because coordinate system
        # is NED

        for poly in patches_upper:
            verts = project(poly, projection)[:, ::-1] * size + position[NA, :]
            if alpha == 1.0:
                data.append(
                    (verts[::decimation], color, color, linewidth))
            else:
                data.append(
                    (verts[::decimation], color, 'none', 0.0))

        for poly in lines_upper:
            verts = project(poly, projection)[:, ::-1] * size + position[NA, :]
            data.append(
                (verts[::decimation], 'none', edgecolor, linewidth))

    patches = []
    for (path, facecolor, edgecolor, linewidth) in data:
        patches.append(Polygon(
            xy=path, facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            alpha=alpha))

    collection = PatchCollection(
        patches, zorder=zorder, transform=transform, match_original=True)

    axes.add_artist(collection)
    return collection


def plot_singleforce_beachball_mpl(
        fn, fe, fd, axes,
        position=(0., 0.),
        size=None,
        zorder=0,
        color_t='red',
        color_p='white',
        edgecolor='black',
        linewidth=2,
        alpha=1.0,
        arcres=181,
        decimation=1,
        projection='lambert',
        size_units='points',
        view='top'):

    '''
    Plot single force beachball diagram to a Matplotlib plot

    :param fn: northward force in [N]
    :type fn: float
    :param fe: eastward force in [N]
    :type fe: float
    :param fd: downward force in [N]
    :type fd: float
    :param position: position of the beachball in data coordinates
    :param size: diameter of the beachball either in points or in data
        coordinates, depending on the ``size_units`` setting
    :param zorder: (passed through to matplotlib drawing functions)
    :param color_t: color for compressional quadrants (default: ``'red'``)
    :param color_p: color for extensive quadrants (default: ``'white'``)
    :param edgecolor: color for lines (default: ``'black'``)
    :param linewidth: linewidth in points (default: ``2``)
    :param alpha: (passed through to matplotlib drawing functions)
    :param projection: ``'lambert'`` (default), ``'stereographic'``, or
        ``'orthographic'``
    :param size_units: ``'points'`` (default) or ``'data'``, where the
        latter causes the beachball to be projected in the plots data
        coordinates (axes must have an aspect ratio of 1.0 or the
        beachball will be shown distorted when using this).
    :param view: View the beachball from ``top``, ``north``, ``south``,
        ``east`` or ``west``. Useful for to show beachballs in cross-sections.
        Default is ``top``.
    '''

    transform, position, size = choose_transform(
        axes, size_units, position, size)

    force = num.array([fn, fe, fd], dtype=num.float64)

    # TODO check rotation!
    force = rotate_singleforce(force, view)

    idx = num.argsort(force)

    ep, en, et = force[idx]
    vp, vn, vt = num.hsplit(num.identity(3)[:, idx], 3)

    eig = (ep, en, et, vp.ravel(), vn.ravel(), vt.ravel())

    if eig[0] == 0. and eig[1] == 0. and eig[2] == 0:
        raise BeachballError('eigenvalues are zero')

    data = []
    for (group, patches, patches_lower, patches_upper,
            lines, lines_lower, lines_upper) in eig2gx_singleforce(
            force, arcres):

        if group == 'P':
            color = color_p
        else:
            color = color_t

        # plot "upper" features for lower hemisphere, because coordinate system
        # is NED

        for poly in patches_upper:
            verts = project(poly, projection)[:, ::-1] * size + position[NA, :]
            if alpha == 1.0:
                data.append(
                    (verts[::decimation], color, color, linewidth))
            else:
                data.append(
                    (verts[::decimation], color, 'none', 0.0))

        for poly in lines_upper:
            verts = project(poly, projection)[:, ::-1] * size + position[NA, :]
            data.append(
                (verts[::decimation], 'none', edgecolor, linewidth))

    patches = []
    for (path, facecolor, edgecolor, linewidth) in data:
        patches.append(Polygon(
            xy=path, facecolor=facecolor,
            edgecolor=edgecolor,
            linewidth=linewidth,
            alpha=alpha))

    collection = PatchCollection(
        patches, zorder=zorder, transform=transform, match_original=True)

    axes.add_artist(collection)
    return collection


def amplitudes_ned(mt, vecs):
    ep, en, et, vp, vn, vt = mt.eigensystem()
    to_e = num.vstack((vn, vt, vp))
    vecs_e = num.dot(to_e, vecs.T).T
    rtp = numpy_xyz2rtp(vecs_e)
    atheta, aphi = rtp[:, 1], rtp[:, 2]
    return ep * num.cos(atheta)**2 + (
        en * num.cos(aphi)**2 + et * num.sin(aphi)**2) * num.sin(atheta)**2


def amplitudes(mt, azimuths, takeoff_angles):
    '''
    Get beachball amplitude values for selected azimuths and takeoff angles.

    :param azimuths:
        Azimuths, measured clockwise from north [deg].
    :type azimuths:
        :py:class:`~numpy.ndarray`

    :param takeoff_angles:
        Takeoff angles, measured from downward vertical [deg].
    :type takeoff_angles:
        :py:class:`~numpy.ndarray`
    '''
    azimuths = num.asarray(azimuths, dtype=float)
    takeoff_angles = num.asarray(takeoff_angles, dtype=float)
    assert azimuths.size == takeoff_angles.size
    rtps = num.vstack(
        (num.ones(azimuths.size), takeoff_angles*d2r, azimuths*d2r)).T
    vecs = numpy_rtp2xyz(rtps)
    return amplitudes_ned(mt, vecs)


def mts2amps(
        mts,
        projection,
        beachball_type,
        grid_resolution=200,
        mask=True,
        view='top'):

    n_balls = len(mts)
    nx = grid_resolution
    ny = grid_resolution

    x = num.linspace(-1., 1., nx)
    y = num.linspace(-1., 1., ny)

    vecs2 = num.zeros((nx * ny, 2), dtype=num.float64)
    vecs2[:, 0] = num.tile(x, ny)
    vecs2[:, 1] = num.repeat(y, nx)

    ii_ok = vecs2[:, 0]**2 + vecs2[:, 1]**2 <= 1.0
    amps = num.full(nx * ny, num.nan, dtype=num.float64)

    amps[ii_ok] = 0.
    vecs3_ok = inverse_project(vecs2[ii_ok, :], projection)

    for mt in mts:
        amps_ok = amplitudes_ned(deco_part(mt, beachball_type, view), vecs3_ok)
        if mask:
            amps_ok[amps_ok > 0] = 1.
            amps_ok[amps_ok < 0] = 0.

        amps[ii_ok] += amps_ok

    return num.reshape(amps, (ny, nx)) / n_balls, x, y


def plot_fuzzy_beachball_mpl_pixmap(
        mts, axes,
        best_mt=None,
        beachball_type='deviatoric',
        position=(0., 0.),
        size=None,
        zorder=0,
        color_t='red',
        color_p='white',
        edgecolor='black',
        best_color='red',
        linewidth=2,
        alpha=1.0,
        projection='lambert',
        size_units='data',
        grid_resolution=200,
        method='imshow',
        view='top'):
    '''
    Plot fuzzy beachball from a list of given MomentTensors

    :param mts: list of
        :py:class:`pyrocko.moment_tensor.MomentTensor` object or an
        array or sequence which can be converted into an MT object
    :param best_mt: :py:class:`pyrocko.moment_tensor.MomentTensor` object or
        an array or sequence which can be converted into an MT object
        of most likely or minimum misfit solution to extra highlight
    :param best_color: mpl color for best MomentTensor edges,
        polygons are not plotted

    See plot_beachball_mpl for other arguments
    '''
    if size_units == 'points':
        raise BeachballError(
            'size_units="points" not supported in '
            'plot_fuzzy_beachball_mpl_pixmap')

    transform, position, size = choose_transform(
        axes, size_units, position, size)

    amps, x, y = mts2amps(
        mts,
        grid_resolution=grid_resolution,
        projection=projection,
        beachball_type=beachball_type,
        mask=True,
        view=view)

    ncolors = 256
    cmap = LinearSegmentedColormap.from_list(
        'dummy', [color_p, color_t], N=ncolors)

    levels = num.linspace(0, 1., ncolors)
    if method == 'contourf':
        axes.contourf(
            position[0] + y * size, position[1] + x * size, amps.T,
            levels=levels,
            cmap=cmap,
            transform=transform,
            zorder=zorder,
            alpha=alpha)

    elif method == 'imshow':
        axes.imshow(
            amps.T,
            extent=(
                position[0] + y[0] * size,
                position[0] + y[-1] * size,
                position[1] - x[0] * size,
                position[1] - x[-1] * size),
            cmap=cmap,
            transform=transform,
            zorder=zorder-0.1,
            alpha=alpha)
    else:
        assert False, 'invalid `method` argument'

    # draw optimum edges
    if best_mt is not None:
        best_amps, bx, by = mts2amps(
            [best_mt],
            grid_resolution=grid_resolution,
            projection=projection,
            beachball_type=beachball_type,
            mask=False)

        axes.contour(
            position[0] + by * size, position[1] + bx * size, best_amps.T,
            levels=[0.],
            colors=[best_color],
            linewidths=linewidth,
            transform=transform,
            zorder=zorder,
            alpha=alpha)

    phi = num.linspace(0., 2 * PI, 361)
    x = num.cos(phi)
    y = num.sin(phi)
    axes.plot(
        position[0] + x * size, position[1] + y * size,
        linewidth=linewidth,
        color=edgecolor,
        transform=transform,
        zorder=zorder,
        alpha=alpha)


def plot_beachball_mpl_construction(
        mt, axes,
        show='patches',
        beachball_type='deviatoric',
        view='top'):

    mt = deco_part(mt, beachball_type, view)
    eig = mt.eigensystem()

    for (group, patches, patches_lower, patches_upper,
            lines, lines_lower, lines_upper) in eig2gx(eig):

        if group == 'P':
            color = 'blue'
            lw = 1
        else:
            color = 'red'
            lw = 1

        if show == 'patches':
            for poly in patches_upper:
                px, py, pz = poly.T
                axes.plot(*extr(poly).T, color=color, lw=lw, alpha=0.5)

        if show == 'lines':
            for poly in lines_upper:
                px, py, pz = poly.T
                axes.plot(*extr(poly).T, color=color, lw=lw, alpha=0.5)


def plot_beachball_mpl_pixmap(
        mt, axes,
        beachball_type='deviatoric',
        position=(0., 0.),
        size=None,
        zorder=0,
        color_t='red',
        color_p='white',
        edgecolor='black',
        linewidth=2,
        alpha=1.0,
        projection='lambert',
        size_units='data',
        view='top'):

    if size_units == 'points':
        raise BeachballError(
            'size_units="points" not supported in plot_beachball_mpl_pixmap')

    transform, position, size = choose_transform(
        axes, size_units, position, size)

    mt = deco_part(mt, beachball_type, view)

    ep, en, et, vp, vn, vt = mt.eigensystem()

    amps, x, y = mts2amps(
        [mt], projection, beachball_type, grid_resolution=200, mask=False)

    axes.contourf(
        position[0] + y * size, position[1] + x * size, amps.T,
        levels=[-num.inf, 0., num.inf],
        colors=[color_p, color_t],
        transform=transform,
        zorder=zorder,
        alpha=alpha)

    axes.contour(
        position[0] + y * size, position[1] + x * size, amps.T,
        levels=[0.],
        colors=[edgecolor],
        linewidths=linewidth,
        transform=transform,
        zorder=zorder,
        alpha=alpha)

    phi = num.linspace(0., 2 * PI, 361)
    x = num.cos(phi)
    y = num.sin(phi)
    axes.plot(
        position[0] + x * size, position[1] + y * size,
        linewidth=linewidth,
        color=edgecolor,
        transform=transform,
        zorder=zorder,
        alpha=alpha)


if __name__ == '__main__':
    import sys
    import os
    import matplotlib.pyplot as plt
    from pyrocko import model

    args = sys.argv[1:]

    data = []
    for iarg, arg in enumerate(args):

        if os.path.exists(arg):
            events = model.load_events(arg)
            for ev in events:
                if not ev.moment_tensor:
                    logger.warning('no moment tensor given for event')
                    continue

                data.append((ev.name, ev.moment_tensor))
        else:
            vals = list(map(float, arg.split(',')))
            mt = mtm.as_mt(vals)
            data.append(('%i' % (iarg+1), mt))

    n = len(data)

    ncols = 1
    while ncols**2 < n:
        ncols += 1

    nrows = ncols

    fig = plt.figure()
    axes = fig.add_subplot(1, 1, 1, aspect=1.)
    axes.axison = False
    axes.set_xlim(-0.05 - ncols, ncols + 0.05)
    axes.set_ylim(-0.05 - nrows, nrows + 0.05)

    for ibeach, (name, mt) in enumerate(data):
        irow = ibeach // ncols
        icol = ibeach % ncols
        plot_beachball_mpl(
            mt, axes,
            position=(icol*2-ncols+1, -irow*2+nrows-1),
            size_units='data')

        axes.annotate(
            name,
            xy=(icol*2-ncols+1, -irow*2+nrows-2),
            xycoords='data',
            xytext=(0, 0),
            textcoords='offset points',
            verticalalignment='center',
            horizontalalignment='center',
            rotation=0.)

    plt.show()
