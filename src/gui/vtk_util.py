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
    def __init__(self, vertices, faces, values=None, contour=False, **kwargs):
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
            if contour:
                factors = [0.01, 0.1, 1., 2., 5., 10., 20., 50.]
                limits = num.array([
                    num.max(num.ceil(values / fac)) for fac in factors])

                factor_ind = num.argmin(num.abs(limits - 10.))
                fac = factors[factor_ind]
                lim = int(limits[factor_ind])
                kwargs = dict(kwargs, numcolor=lim - 1)

                for i in range(lim):
                    values[(values >= i * fac) & (values < (i + 1) * fac)] = \
                        i * fac

            self.set_values(values)

        if kwargs:
            colorbar_actor = self.get_colorbar_actor(**kwargs)
            colorbar_actor.GetProperty()
            self.actor = [act, colorbar_actor]

    def set_opacity(self, value):
        self.prop.SetOpacity(value)

    def set_vertices(self, vertices):
        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(numpy_to_vtk(vertices))
        self.polydata.SetPoints(vpoints)

    def set_values(self, values):
        vvalues = numpy_to_vtk(values.astype(num.float64))

        vvalues = vtk.vtkDoubleArray()
        for value in values:
            vvalues.InsertNextValue(value)

        self.polydata.GetCellData().SetScalars(vvalues)
        self.mapper.SetScalarRange(values.min(), values.max())

    def get_colorbar_actor(self, cbar_title=None, numcolor=None):
        lut = vtk.vtkLookupTable()
        if numcolor:
            lut.SetNumberOfTableValues(numcolor)
        lut.Build()
        self.mapper.SetLookupTable(lut)

        scalar_bar = vtk.vtkScalarBarActor()
        if numcolor:
            scalar_bar.SetNumberOfLabels(numcolor + 1)
        scalar_bar.SetMaximumHeightInPixels(500)
        scalar_bar.SetMaximumWidthInPixels(50)
        scalar_bar.SetLookupTable(lut)
        scalar_bar.SetTitle(cbar_title)
        try:
            scalar_bar.SetUnconstrainedFontSize(True)
        except AttributeError:
            pass

        prop_title = vtk.vtkTextProperty()
        prop_title.SetFontFamilyToArial()
        prop_title.SetColor(.8, .8, .8)
        prop_title.SetFontSize(int(prop_title.GetFontSize() * 1.3))
        prop_title.BoldOn()
        scalar_bar.SetTitleTextProperty(prop_title)
        try:
            scalar_bar.SetVerticalTitleSeparation(20)
        except AttributeError:
            pass

        prop_label = vtk.vtkTextProperty()
        prop_label.SetFontFamilyToArial()
        prop_label.SetColor(.8, .8, .8)
        prop_label.SetFontSize(int(prop_label.GetFontSize() * 1.1))
        scalar_bar.SetLabelTextProperty(prop_label)

        pos = scalar_bar.GetPositionCoordinate()
        pos.SetCoordinateSystemToNormalizedViewport()
        pos.SetValue(0.95, 0.05)

        return scalar_bar


class ArrowPipe(object):
    def __init__(self, start, end, value=None):
        from vtk import vtkMath as vm

        arrow = vtk.vtkArrowSource()
        arrow.SetTipResolution(31)
        arrow.SetShaftResolution(21)
        arrow.Update()

        normalized_x = [0.0] * 3
        normalized_y = [0.0] * 3
        normalized_z = [0.0] * 3

        vm.Subtract(end, start, normalized_x)
        length = vm.Norm(normalized_x)
        vm.Normalize(normalized_x)

        arbitrary = [0.0] * 3
        arbitrary[0] = vm.Random(-10, 10)
        arbitrary[1] = vm.Random(-10, 10)
        arbitrary[2] = vm.Random(-10, 10)
        vm.Cross(normalized_x, arbitrary, normalized_z)
        vm.Normalize(normalized_z)

        vm.Cross(normalized_z, normalized_x, normalized_y)

        matrix = vtk.vtkMatrix4x4()

        matrix.Identity()
        for i in range(0, 3):
            matrix.SetElement(i, 0, normalized_x[i])
            matrix.SetElement(i, 1, normalized_y[i])
            matrix.SetElement(i, 2, normalized_z[i])

        transform = vtk.vtkTransform()
        transform.Translate(start)
        transform.Concatenate(matrix)
        transform.Scale(length, length, length)

        transform_filter = vtk.vtkTransformPolyDataFilter()
        transform_filter.SetTransform(transform)
        transform_filter.SetInputConnection(arrow.GetOutputPort())

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(transform_filter.GetOutputPort())

        act = vtk.vtkActor()
        act.SetMapper(mapper)

        prop = act.GetProperty()
        self.prop = prop
        self.mapper = mapper
        self.actor = act


class Glyph3DPipe(object):
    def __init__(self, vertices, vectors, sizefactor=1.):
        assert len(vertices) == len(vectors)

        if isinstance(vectors, list):
            vectors = num.array(vectors)

        assert vectors.shape[1] == 3

        vectors = vectors
        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(numpy_to_vtk(vertices))

        vvectors = vtk.vtkDoubleArray()
        vvectors.SetNumberOfComponents(3)
        vvectors.SetNumberOfTuples(vectors.shape[0])

        for iv, vec in enumerate(vectors):
            for ic, comp in enumerate(vec):
                vvectors.SetComponent(iv, ic, comp)

        pd = vtk.vtkPolyData()
        pd.SetPoints(vpoints)
        pd.GetPointData().SetVectors(vvectors)

        arrow = vtk.vtkArrowSource()
        arrow.SetTipResolution(31)
        arrow.SetShaftResolution(21)
        arrow.Update()

        glyph = vtk.vtkGlyph3D()
        glyph.SetSourceData(arrow.GetOutput())
        glyph.SetInputData(pd)
        glyph.ScalingOn()
        glyph.SetVectorModeToUseVector()
        glyph.OrientOn()
        glyph.SetScaleModeToScaleByVector()
        glyph.SetScaleFactor(10**sizefactor)
        glyph.Update()

        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(glyph.GetOutputPort())

        act = vtk.vtkActor()
        act.SetMapper(mapper)

        prop = act.GetProperty()
        self.prop = prop

        self.polydata = pd
        self.mapper = mapper

        # if scale_bar:
        #     self.actor = [act, self.scale_bar_actor(glyph.GetScaleFactor())]
        # else:
        self.actor = act

    def scale_bar_actor(self, ScalingFactor):
        leader = vtk.vtkLeaderActor2D()

        pos = leader.GetPositionCoordinate()
        pos2c = leader.GetPosition2Coordinate()
        pos.SetCoordinateSystemToNormalizedViewport()
        pos2c.SetCoordinateSystemToNormalizedViewport()
        pos.SetValue(0.8, 0.12)
        pos2c.SetValue(0.9, 0.12)
        leader.SetArrowStyleToFilled()
        leader.SetLabel('Disp. = %.2f m' % 10.)
        leader.SetArrowPlacementToPoint1()

        try:
            leader.SetUnconstrainedFontSize(True)
        except AttributeError:
            pass

        prop_label = vtk.vtkTextProperty()
        prop_label.SetFontFamilyToArial()
        prop_label.BoldOn()
        prop_label.SetColor(.8, .8, .8)
        prop_label.SetJustificationToCentered()
        prop_label.SetVerticalJustificationToBottom()
        leader.SetLabelTextProperty(prop_label)
        leader.SetLabelFactor(0.5)
        leader.GetProperty().SetColor(1., 1., 0.69)

        return leader
