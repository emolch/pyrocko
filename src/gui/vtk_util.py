# https://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from __future__ import absolute_import, print_function, division

import logging
import numpy as num
import vtk

from vtk.util.numpy_support import \
    numpy_to_vtk as numpy_to_vtk_, get_vtk_array_type
# , numpy_to_vtkIdTypeArray

from pyrocko import geometry, cake

logger = logging.getLogger('pyrocko.gui.vtk_util')


def vtk_set_input(obj, source):
    try:
        obj.SetInputData(source)
    except AttributeError:
        obj.SetInput(source)


def numpy_to_vtk(a):
    return numpy_to_vtk_(
        a, deep=1, array_type=get_vtk_array_type(a.dtype))


def numpy_to_vtk_colors(a):
    c = numpy_to_vtk((a*255.).astype(num.uint8))
    c.SetName('Colors')
    return c


def make_multi_polyline(
        lines_rtp=None, lines_latlon=None, lines_latlondepth=None):
    if lines_rtp is not None:
        points = geometry.rtp2xyz(num.vstack(lines_rtp))
        lines = lines_rtp
    elif lines_latlon is not None:
        points = geometry.latlon2xyz(
            num.vstack(lines_latlon), radius=1.0)
        lines = lines_latlon
    elif lines_latlondepth is not None:
        points = geometry.latlondepth2xyz(
            num.vstack(lines_latlondepth), planetradius=cake.earthradius)
        lines = lines_latlondepth

    vpoints = vtk.vtkPoints()
    vpoints.SetNumberOfPoints(points.shape[0])
    vpoints.SetData(numpy_to_vtk(points))

    polyline_grid = vtk.vtkUnstructuredGrid()
    polyline_grid.Allocate(len(lines), len(lines))
    polyline_grid.SetPoints(vpoints)
    ioff = 0
    celltype = vtk.vtkPolyLine().GetCellType()
    for iline, line in enumerate(lines):
        pids = vtk.vtkIdList()

        # slow:
        pids.SetNumberOfIds(line.shape[0])
        for i in range(line.shape[0]):
            pids.SetId(i, ioff+i)

        # should be faster but doesn't work:
        # arr = numpy_to_vtkIdTypeArray(num.arange(line.shape[0]) + ioff, 1)
        # pids.SetArray(arr, line.shape[0])

        polyline_grid.InsertNextCell(
            celltype, pids)

        ioff += line.shape[0]

    return polyline_grid


class ScatterPipe(object):
    def __init__(self, vertices):
        nvertices = vertices.shape[0]
        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(nvertices)
        i = 0
        for x, y, z in vertices:
            vpoints.InsertPoint(i, x, y, z)
            i += 1

        ppd = vtk.vtkPolyData()
        ppd.SetPoints(vpoints)

        vertex_filter = vtk.vtkVertexGlyphFilter()
        try:
            vertex_filter.SetInputData(ppd)
        except AttributeError:
            vertex_filter.SetInputConnection(ppd.GetProducerPort())

        vertex_filter.Update()

        pd = vtk.vtkPolyData()
        pd.ShallowCopy(vertex_filter.GetOutput())

        # colors = num.random.random((nvertices, 3))
        colors = num.ones((nvertices, 3))
        vcolors = numpy_to_vtk_colors(colors)
        pd.GetPointData().SetScalars(vcolors)

        map = vtk.vtkPolyDataMapper()
        try:
            map.SetInputConnection(pd.GetProducerPort())
        except AttributeError:
            map.SetInputData(pd)

        self.polydata = pd

        act = vtk.vtkActor()
        act.SetMapper(map)

        prop = act.GetProperty()
        prop.SetPointSize(10)
        try:
            prop.SetRenderPointsAsSpheres(True)
        except AttributeError:
            logger.warn(
                'Cannot render points as sphere with this version of VTK')

        self.prop = prop

        self.actor = act

    def set_colors(self, colors):
        vcolors = numpy_to_vtk_colors(colors)
        self.polydata.GetPointData().SetScalars(vcolors)

    def set_size(self, size):
        self.prop.SetPointSize(size)


class TrimeshPipe(object):
    def __init__(self, vertices, faces, values=None, smooth=False):

        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(numpy_to_vtk(vertices))

        pd = vtk.vtkPolyData()
        pd.SetPoints(vpoints)

        cells = vtk.vtkCellArray()
        for face in faces:
            cells.InsertNextCell(face.size)
            for ivert in face:
                cells.InsertCellPoint(ivert)

        pd.SetPolys(cells)

        mapper = vtk.vtkPolyDataMapper()

        if smooth:
            normals = vtk.vtkPolyDataNormals()
            vtk_set_input(normals, pd)
            normals.SetFeatureAngle(60.)
            normals.ConsistencyOff()
            normals.SplittingOff()
            mapper.SetInputConnection(normals.GetOutputPort())
        else:
            vtk_set_input(mapper, pd)

        mapper.ScalarVisibilityOff()

        act = vtk.vtkActor()
        act.SetMapper(mapper)
        prop = act.GetProperty()
        prop.SetColor(0.5, 0.5, 0.5)
        prop.SetAmbientColor(0.3, 0.3, 0.3)
        prop.SetDiffuseColor(0.5, 0.5, 0.5)
        prop.SetSpecularColor(1.0, 1.0, 1.0)
        # prop.SetOpacity(0.7)
        self.prop = prop

        self.polydata = pd
        self.mapper = mapper
        self.actor = act

        if values is not None:
            self.set_values(values)

    def set_opacity(self, value):
        self.prop.SetOpacity(value)

    def set_vertices(self, vertices):
        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(numpy_to_vtk(vertices))
        self.polydata.SetPoints(vpoints)

    def set_values(self, values):
        vvalues = numpy_to_vtk(values.astype(num.float64), deep=1)

        vvalues = vtk.vtkDoubleArray()
        for value in values:
            vvalues.InsertNextValue(value)

        self.polydata.GetCellData().SetScalars(vvalues)
        self.mapper.SetScalarRange(values.min(), values.max())


class PolygonPipe(object):
    def __init__(self, vertices, faces, values=None, contour=False):

        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(numpy_to_vtk(vertices))

        pd = vtk.vtkPolyData()
        pd.SetPoints(vpoints)

        cells = vtk.vtkCellArray()
        for face in faces:
            cells.InsertNextCell(face.size)
            for ivert in face:
                cells.InsertCellPoint(ivert)

        pd.SetPolys(cells)

        mapper = vtk.vtkPolyDataMapper()

        vtk_set_input(mapper, pd)

        act = vtk.vtkActor()

        if contour:
            pass
            # scalar_range = pd.GetScalarRange()
            # vcontour = vtk.vtkContourFilter()
            # vcontour.SetInputConnection(mapper.GetOutputPort())
            # vcontour.GenerateValues(12, scalar_range)
            # mapper.SetInputConnection(vcontour.GetOutputPort())
            # act.SetMapper(mapper)

        else:
            act.SetMapper(mapper)

        prop = act.GetProperty()
        # prop.SetColor(0.5, 0.5, 0.5)
        # prop.SetAmbientColor(0.3, 0.3, 0.3)
        # prop.SetDiffuseColor(0.5, 0.5, 0.5)
        # prop.SetSpecularColor(1.0, 1.0, 1.0)
        # prop.SetOpacity(0.7)
        self.prop = prop

        self.polydata = pd
        self.mapper = mapper
        self.actor = act

        if values is not None:
            self.set_values(values)

    def set_opacity(self, value):
        self.prop.SetOpacity(value)

    def set_vertices(self, vertices):
        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(numpy_to_vtk(vertices))
        self.polydata.SetPoints(vpoints)

    def set_values(self, values):
        vvalues = numpy_to_vtk(values.astype(num.float64))#, deep=1)

        vvalues = vtk.vtkDoubleArray()
        for value in values:
            vvalues.InsertNextValue(value)

        self.polydata.GetCellData().SetScalars(vvalues)
        self.mapper.SetScalarRange(values.min(), values.max())