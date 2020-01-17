# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import math
import numpy as num
from .geometry import arr_vertices, arr_faces, normalize, refine_triangles, \
    vdot, vnorm, face_centers

r2d = 180./math.pi


def cube():
    vertices = arr_vertices([
        [-1, -1, -1],
        [-1, -1, 1],
        [-1, 1, -1],
        [-1, 1, 1],
        [1, -1, -1],
        [1, -1, 1],
        [1, 1, -1],
        [1, 1, 1]])

    faces = arr_faces([
        [0, 1, 3, 2],
        [0, 4, 5, 1],
        [4, 6, 7, 5],
        [2, 3, 7, 6],
        [1, 5, 7, 3],
        [0, 2, 6, 4]])

    return vertices, faces


def triangles_to_center(vertices, faces):

    vs = vertices
    fs = faces

    vcs = face_centers(vs, fs)

    nv = vs.shape[0]
    nf = fs.shape[0]
    nc = fs.shape[1]

    intc = (nv + num.arange(nf))[:, num.newaxis]
    f2s = num.vstack([
        num.hstack([fs[:, (ic, (ic+1) % nc)], intc])
        for ic in range(nc)])

    v2s = num.vstack([vs, vcs])
    return v2s, f2s


def tcube():
    vs, fs = cube()
    return triangles_to_center(vs, fs)


def tetrahedron():
    vertices = arr_vertices([
        [math.sqrt(8./9.), 0., -1./3.],
        [-math.sqrt(2./9.), math.sqrt(2./3.), -1./3.],
        [-math.sqrt(2./9.), -math.sqrt(2./3.), -1./3.],
        [0., 0., 1.]
    ])

    faces = arr_faces([
        [2, 1, 0],
        [3, 2, 0],
        [2, 3, 1],
        [3, 0, 1]
    ])
    return vertices, faces


def icosahedron():
    a = 0.5 * (math.sqrt(5) - 1.0)

    vertices = arr_vertices([
        [0, 1, a], [a, 0, 1], [1, a, 0],
        [0, 1, -a], [-a, 0, 1], [1, -a, 0],
        [0, -1, -a], [-a, 0, -1], [-1, -a, 0],
        [0, -1, a], [a, 0, -1], [-1, a, 0]
    ])

    faces = arr_faces([
        [6, 5, 9], [9, 8, 6], [8, 7, 6], [7, 10, 6], [10, 5, 6],
        [5, 10, 2], [2, 1, 5], [5, 1, 9], [9, 1, 4], [4, 8, 9],
        [4, 11, 8], [8, 11, 7], [7, 11, 3], [3, 10, 7], [3, 2, 10],
        [3, 0, 2], [0, 1, 2], [0, 4, 1], [0, 11, 4], [0, 3, 11]
    ])

    return vertices, faces


def neighbors(vertices, faces):

    nv = vertices.shape[0]
    nf, nc = faces.shape
    fedges = num.zeros((nf*nc, 2), dtype=num.int)
    for ic in range(nc):
        fedges[ic::nc, :] = faces[:, (ic, (ic+1) % nc)]

    indface = num.repeat(num.arange(nf), nc)
    fedges1 = fedges[:, 0] + fedges[:, 1]*nv
    sortorder = fedges1.argsort()
    fedges1_rev = fedges[:, 1] + fedges[:, 0]*nv

    inds = num.searchsorted(fedges1, fedges1_rev, sorter=sortorder)
    # todo: handle cases without neighbors
    assert num.all(fedges1[sortorder[inds]] == fedges1_rev)
    neighbors = indface[sortorder[inds]].reshape((nf, nc))
    return neighbors


def adjacent_faces(vertices, faces):

    nv = vertices.shape[0]
    nf, nc = faces.shape

    iverts = faces.reshape(nf*nc)
    ifaces = num.repeat(num.arange(nf), nc)
    iverts_order = iverts.argsort()

    vs = vertices[faces]
    gs = num.zeros(vs.shape)
    gs[:, :-1, :] = vs[:, 1:, :] - vs[:, :-1, :]
    gs[:, -1, :] = vs[:, 0, :] - vs[:, -1, :]

    vecs = gs.reshape((nf*nc, 3))
    iverts_ordered = iverts[iverts_order]
    ifirsts = nextval_indices(iverts_ordered)
    iselected = iverts_ordered[ifirsts]

    plane_en = normalize(vertices)
    plane_e1 = num.zeros((nv, 3))
    plane_e1[iselected, :] = normalize(
        project_to_plane_nn(plane_en[iselected, :], vecs[ifirsts, :]))
    plane_e2 = num.zeros((nv, 3))
    plane_e2[iselected, :] = num.cross(
        plane_en[iselected, :], plane_e1[iselected, :])

    a1 = vdot(vecs[iverts_order, :], plane_e1[iverts_ordered, :])
    a2 = vdot(vecs[iverts_order, :], plane_e2[iverts_ordered, :])
    angles = num.arctan2(a1, a2) * r2d + 360. * iverts_ordered
    iverts_order2 = num.argsort(angles)

    return iverts_ordered, ifaces[iverts_order][iverts_order2]


def nextval_indices(a):
    return num.concatenate(
        [[0], num.where(num.diff(a) != 0)[0] + 1])


def project_to_plane(vns, vas):
    return vas - (vdot(vas, vns) / vdot(vns, vns))[:, num.newaxis] * vns


def project_to_plane_nn(vns, vas):
    return vas - (vdot(vas, vns))[:, num.newaxis] * vns


def corner_handednesses(vertices, faces):
    vs = vertices[faces]
    gs = num.zeros(vs.shape)
    gs[:, :-1, :] = vs[:, 1:, :] - vs[:, :-1, :]
    gs[:, -1, :] = vs[:, 0, :] - vs[:, -1, :]
    hs = num.zeros((faces.shape[0], faces.shape[1]))
    hs[:, 1:] = vdot(num.cross(gs[:, :-1, :], gs[:, 1:, :]), vs[:, 1:, :])
    hs[:, 0] = vdot(num.cross(gs[:, -1, :], gs[:, 0, :]), vs[:, 0, :])
    return hs


def truncate(vertices, faces):

    nv = vertices.shape[0]
    iverts, ifaces = adjacent_faces(vertices, faces)
    ifirsts = nextval_indices(iverts)
    ilengths = num.zeros(ifirsts.size, dtype=num.int)
    ilengths[:-1] = num.diff(ifirsts)
    ilengths[-1] = iverts.size - ifirsts[-1]
    nc = num.max(ilengths)
    nf = nv
    vertices_new = face_centers(vertices, faces)
    faces_new = num.zeros((nf, nc), dtype=num.int)
    for iface in range(nf):
        ifirst = ifirsts[iface]
        ilength = ilengths[iface]
        faces_new[iface, :ilength] = ifaces[ifirst:ifirst+ilength]
        faces_new[iface, ilength:] = ifaces[ifirst+ilength-1]

    faces_new = faces_new[:, ::-1]

    return vertices_new, faces_new


def iter_icospheres(order, inflate=True):
    vertices, faces = icosahedron()
    vertices /= vnorm(vertices)[:, num.newaxis]
    yield (vertices, faces)

    for i in range(order):
        vertices, faces = refine_triangles(vertices, faces)
        if inflate:
            vertices = normalize(vertices)

        yield (vertices, faces)


bases = {
    'icosahedron': icosahedron,
    'tetrahedron': tetrahedron,
    'tcube': tcube}


def sphere(
        order,
        base=icosahedron,
        kind='kind1',
        inflate=True,
        radius=1.0,
        triangulate=True):

    if isinstance(base, str):
        base = bases[base]

    vertices, faces = base()
    vertices /= vnorm(vertices)[:, num.newaxis]

    for i in range(order):
        vertices, faces = refine_triangles(vertices, faces)
        if inflate:
            vertices = normalize(vertices)
            if radius != 1.0:
                vertices *= radius

    if kind == 'kind2':
        vertices, faces = truncate(vertices, faces)
        if triangulate:
            vertices, faces = triangles_to_center(vertices, faces)

    return vertices, faces
