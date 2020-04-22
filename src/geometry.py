# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import numpy as num

from pyrocko import orthodrome as od

d2r = num.pi/180.
r2d = 1.0 / d2r


def arr_vertices(obj):
    a = num.array(obj, dtype=num.float)
    assert len(a.shape) == 2
    assert a.shape[1] == 3
    return a


def arr_faces(obj):
    a = num.array(obj, dtype=num.int)
    assert len(a.shape) == 2
    return a


def vsqr(vertices):
    return num.sum(vertices**2, axis=1)


def vdot(a, b):
    return num.sum(a*b, axis=-1)


def vnorm(vertices):
    return num.linalg.norm(vertices, axis=1)


def normalize(vertices):
    return vertices / vnorm(vertices)[:, num.newaxis]


def face_centers(vertices, faces):
    return num.mean(vertices[faces], axis=1)


def rtp2xyz(rtp):
    r = rtp[:, 0]
    theta = rtp[:, 1]
    phi = rtp[:, 2]
    vecs = num.empty(rtp.shape, dtype=num.float)
    vecs[:, 0] = r*num.sin(theta)*num.cos(phi)
    vecs[:, 1] = r*num.sin(theta)*num.sin(phi)
    vecs[:, 2] = -r*num.cos(theta)
    return vecs


def latlon2xyz(latlon, radius=1.0):
    rtp = num.empty((latlon.shape[0], 3))
    rtp[:, 0] = radius
    rtp[:, 1] = (latlon[:, 0] + 90.) * d2r
    rtp[:, 2] = latlon[:, 1] * d2r
    return rtp2xyz(rtp)


def latlondepth2xyz(latlondepth, planetradius):
    rtp = num.empty((latlondepth.shape[0], 3))
    rtp[:, 0] = 1.0 - (latlondepth[:, 2] / planetradius)
    rtp[:, 1] = (latlondepth[:, 0] + 90.) * d2r
    rtp[:, 2] = latlondepth[:, 1] * d2r
    return rtp2xyz(rtp)


def ned2xyz(ned, latlondepth, planetradius):
    endpoints = num.empty_like(latlondepth)
    endpoints[:, 0], endpoints[:, 1] = od.ne_to_latlon(
        latlondepth[:, 0], latlondepth[:, 1], ned[:, 0], ned[:, 1])
    endpoints[:, 2] = latlondepth[:, 2] + ned[:, 2]

    start_xyz = latlondepth2xyz(latlondepth, planetradius)
    end_xyz = latlondepth2xyz(endpoints, planetradius)

    return end_xyz - start_xyz


def topo_to_vertices(lat, lon, ele, planetradius):
    nlat = lat.size
    nlon = lon.size
    assert nlat > 1 and nlon > 1 and ele.shape == (nlat, nlon)
    rtp = num.empty((ele.size, 3))
    rtp[:, 0] = 1.0 + ele.flatten() / planetradius
    rtp[:, 1] = (num.repeat(lat, nlon) + 90.) * d2r
    rtp[:, 2] = num.tile(lon, nlat) * d2r
    vertices = rtp2xyz(rtp)
    return vertices


g_topo_faces = {}


def topo_to_faces(nlat, nlon):
    k = (nlat, nlon)
    if k not in g_topo_faces:

        nfaces = 2 * (nlat - 1) * (nlon - 1)
        faces = num.empty((nfaces, 3), dtype=num.int)
        ilon = num.arange(nlon - 1)
        for ilat in range(nlat - 1):
            ibeg = ilat*(nlon-1) * 2
            iend = (ilat+1)*(nlon-1) * 2
            faces[ibeg:iend:2, 0] = ilat*nlon + ilon
            faces[ibeg:iend:2, 1] = ilat*nlon + ilon + 1
            faces[ibeg:iend:2, 2] = ilat*nlon + ilon + nlon
            faces[ibeg+1:iend+1:2, 0] = ilat*nlon + ilon + 1
            faces[ibeg+1:iend+1:2, 1] = ilat*nlon + ilon + nlon + 1
            faces[ibeg+1:iend+1:2, 2] = ilat*nlon + ilon + nlon

        g_topo_faces[k] = faces

    return g_topo_faces[k]


g_topo_faces_quad = {}


def topo_to_faces_quad(nlat, nlon):
    k = (nlat, nlon)
    if k not in g_topo_faces_quad:

        nfaces = (nlat - 1) * (nlon - 1)
        faces = num.empty((nfaces, 4), dtype=num.int)
        ilon = num.arange(nlon - 1)
        for ilat in range(nlat - 1):
            ibeg = ilat*(nlon-1)
            iend = (ilat+1)*(nlon-1)
            faces[ibeg:iend, 0] = ilat*nlon + ilon
            faces[ibeg:iend, 1] = ilat*nlon + ilon + 1
            faces[ibeg:iend, 2] = ilat*nlon + ilon + nlon + 1
            faces[ibeg:iend, 3] = ilat*nlon + ilon + nlon

        g_topo_faces_quad[k] = faces

    return g_topo_faces_quad[k]


def topo_to_mesh(lat, lon, ele, planetradius):
    return \
        topo_to_vertices(lat, lon, ele, planetradius), \
        topo_to_faces_quad(*ele.shape)


def refine_triangles(vertices, faces):

    nv = vertices.shape[0]
    nf = faces.shape[0]
    assert faces.shape[1] == 3

    fedges = num.concatenate((
        faces[:, (0, 1)],
        faces[:, (1, 2)],
        faces[:, (2, 0)]))

    fedges.sort(axis=1)
    fedges1 = fedges[:, 0] + fedges[:, 1]*nv
    sortorder = fedges1.argsort()

    ne = fedges.shape[0] // 2
    edges = fedges[sortorder[::2], :]

    vertices_new = num.zeros((nv+ne, 3), dtype=num.float)
    vertices_new[:nv] = vertices
    vertices_new[nv:] = 0.5 * (vertices[edges[:, 0]] + vertices[edges[:, 1]])

    faces_new = num.zeros((nf*4, 3), dtype=num.int)

    vind = nv + sortorder.argsort()/2

    faces_new[:nf, 0] = faces[:, 0]
    faces_new[:nf, 1] = vind[:nf]
    faces_new[:nf, 2] = vind[2*nf:]

    faces_new[nf:nf*2, 0] = faces[:, 1]
    faces_new[nf:nf*2, 1] = vind[nf:2*nf]
    faces_new[nf:nf*2, 2] = vind[:nf]

    faces_new[nf*2:nf*3, 0] = faces[:, 2]
    faces_new[nf*2:nf*3, 1] = vind[2*nf:]
    faces_new[nf*2:nf*3, 2] = vind[nf:2*nf]

    faces_new[nf*3:, 0] = vind[:nf]
    faces_new[nf*3:, 1] = vind[nf:2*nf]
    faces_new[nf*3:, 2] = vind[2*nf:]

    return vertices_new, faces_new


def refine_triangle_parents(nfaces):
    return num.arange(nfaces) % (nfaces / 4)


def triangle_barycentric_transforms(vertices, faces):
    a = vertices[faces[:, 1]] - vertices[faces[:, 0]]
    b = vertices[faces[:, 2]] - vertices[faces[:, 0]]

    norm = 1.0 / (vsqr(a) * vsqr(b) - vdot(a, b)**2)

    transforms = num.zeros((faces.shape[0], 2, 3))

    transforms[:, 0, :] = norm[:, num.newaxis] \
        * (vsqr(b)[:, num.newaxis] * a - vdot(a, b)[:, num.newaxis] * b)
    transforms[:, 1, :] = norm[:, num.newaxis] \
        * (vsqr(a)[:, num.newaxis] * b - vdot(a, b)[:, num.newaxis] * a)

    return transforms


def triangle_barycentric_coordinates(transform, origin, points):
    c = points - origin[num.newaxis, :]
    uv = num.dot(transform[:, :], c.T).T
    return uv


def triangle_cartesian_system(vertices, faces):
    a = normalize(vertices[faces[:, 1]] - vertices[faces[:, 0]])
    b = vertices[faces[:, 2]] - vertices[faces[:, 1]]
    c = normalize(num.cross(a, b))
    uvw = num.zeros((faces.shape[0], 3, 3))
    uvw[:, 0, :] = a
    uvw[:, 1, :] = num.cross(c, a)
    uvw[:, 2, :] = c
    return uvw


def triangle_planes(vertices, faces):
    a = vertices[faces[:, 1]] - vertices[faces[:, 0]]
    b = vertices[faces[:, 2]] - vertices[faces[:, 0]]
    anormals = normalize(num.cross(a, b))
    anormals *= vdot(vertices[faces[:, 0]], anormals)[:, num.newaxis]
    return anormals
