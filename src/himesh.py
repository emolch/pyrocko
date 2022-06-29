# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko.guts import Object, Int

from pyrocko import icosphere, geometry as g

guts_prefix = 'sparrow'

and_ = num.logical_and


class Level(object):
    def __init__(self, vertices, faces):
        self.vertices = vertices
        self.faces = faces
        self.next = None
        self.nvertices = vertices.shape[0]
        self.nfaces = faces.shape[0]
        self.prepare_projections()

    def points_in_face(self, iface, points):
        uv = g.triangle_barycentric_coordinates(
            self.bary_trans[iface, :, :],
            self.vertices[self.faces[iface, 0]],
            points)

        return and_(
            and_(uv[:, 0] >= 0., uv[:, 1] >= 0.), uv[:, 0] + uv[:, 1] <= 1.)

    def points_to_face(self, points, icandidates=None):

        if icandidates is None:
            icandidates = num.arange(self.nfaces)

        npoints = points.shape[0]
        ifaces = num.zeros(npoints, dtype=num.int)
        points_flat_all = num.zeros((npoints, 3))
        for icandidate in icandidates:
            points_flat, mask = self.project(icandidate, points)
            ipoints = num.where(num.logical_and(
                self.points_in_face(icandidate, points_flat),
                mask))[0]

            if self.next:
                icandidates_child = num.where(
                    self.next.parents == icandidate)[0]
                ifaces[ipoints], points_flat_all[ipoints, :] \
                    = self.next.points_to_face(
                        points[ipoints], icandidates_child)

            else:
                ifaces[ipoints] = icandidate
                points_flat_all[ipoints, :] = points_flat[ipoints, :]

        return ifaces, points_flat_all

    def project(self, iface, points):
        denom = g.vdot(points, self.aplanes[iface, :])
        mask = denom > 0.0
        points = points.copy()
        points[mask, :] /= denom[mask, num.newaxis]
        points[num.logical_not(mask), :] = 0.0
        return points, mask

    def prepare_projections(self):
        planes = g.triangle_planes(
            self.vertices, self.faces)

        planes /= g.vdot(
            planes,
            self.vertices[self.faces[:, 0]])[:, num.newaxis]

        self.aplanes = planes

        self.bary_trans = g.triangle_barycentric_transforms(
            self.vertices, self.faces)


class HiMesh(Object):

    order = Int.T(default=0)

    def __init__(self, **kwargs):
        Object.__init__(self, **kwargs)
        self.levels = self.make_levels()

    def make_levels(self):
        root = None
        level = None
        for vertices, faces in icosphere.iter_icospheres(
                self.order, inflate=False):

            new = Level(vertices, faces)
            if not root:
                new.parents = None
                root = new
            else:
                new.parents = g.refine_triangle_parents(faces.shape[0])
                level.next = new

            level = new

        return root

    def points_to_faces(self, points):

        level = self.levels

        ifaces = level.points_to_face(points)
        return ifaces
