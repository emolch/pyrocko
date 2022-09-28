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
from vtk.util import vtkAlgorithm as va

from pyrocko import geometry, cake, orthodrome as od
from pyrocko.plot import cpt as pcpt
from pyrocko.color import Color

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


def cpt_to_vtk_lookuptable(cpt, n=1024):
    lut = vtk.vtkLookupTable()
    lut.Allocate(n, n)
    values = num.linspace(cpt.vmin, cpt.vmax, n)
    colors = cpt(values)
    lut.SetTableRange(cpt.vmin, cpt.vmax)
    for i in range(n):
        lut.SetTableValue(
            i, colors[i, 0]/255., colors[i, 1]/255., colors[i, 2]/255.)

    return lut


def vtk_set_prop_interpolation(prop, name):
    if name == 'gouraud':
        prop.SetInterpolationToGouraud()
    elif name == 'phong':
        prop.SetInterpolationToPhong()
    elif name == 'flat':
        prop.SetInterpolationToFlat()
    elif name == 'pbr':
        if hasattr(prop, 'SetInterpolationToPBR'):
            prop.SetInterpolationToPBR()
        else:
            logger.warn(
                'PBR shading not available - update your VTK installation.')


def make_multi_polyline(
        lines_rtp=None, lines_latlon=None, depth=0.0, lines_latlondepth=None):
    if lines_rtp is not None:
        points = geometry.rtp2xyz(num.vstack(lines_rtp))
        lines = lines_rtp
    elif lines_latlon is not None:
        points = geometry.latlon2xyz(
            num.vstack(lines_latlon), radius=1.0 - depth/cake.earthradius)
        lines = lines_latlon
    elif lines_latlondepth is not None:
        if not lines_latlondepth:
            points = num.zeros((0, 3))
        else:
            points = geometry.latlondepth2xyz(
                num.vstack(lines_latlondepth), planetradius=cake.earthradius)
        lines = lines_latlondepth

    vpoints = vtk.vtkPoints()
    vpoints.SetNumberOfPoints(points.shape[0])
    vpoints.SetData(numpy_to_vtk(points))

    poly_data = vtk.vtkPolyData()
    poly_data.Allocate(len(lines), len(lines))
    poly_data.SetPoints(vpoints)

    ioff = 0
    celltype = vtk.vtkPolyLine().GetCellType()
    for iline, line in enumerate(lines):
        # should be faster but doesn't work (SetArray seems to be the problem)
        # arr = numpy_to_vtkIdTypeArray(num.arange(line.shape[0]) + ioff, 1)
        # pids.SetArray(
        #     int(arr.GetPointer(0).split('_')[1], base=16), line.shape[0])

        poly_data.InsertNextCell(
            celltype, line.shape[0], range(ioff, ioff+line.shape[0]))

        ioff += line.shape[0]

    return poly_data


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
        self.polydata = pd
        pd.ShallowCopy(vertex_filter.GetOutput())

        self._colors = num.ones((nvertices, 4))
        self._update_colors()

        map = vtk.vtkPolyDataMapper()
        try:
            map.SetInputConnection(pd.GetProducerPort())
        except AttributeError:
            map.SetInputData(pd)

        act = vtk.vtkActor()
        act.SetMapper(map)

        prop = act.GetProperty()
        prop.SetPointSize(10)

        self.prop = prop
        self.actor = act

        self._symbol = ''
        self.set_symbol('point')

    def set_colors(self, colors):
        self._colors[:, :3] = colors
        self._update_colors()

    def set_alpha(self, alpha):
        # print('colors', self._colors.shape)
        self._colors[:, 3] = alpha
        self._update_colors()

    def _update_colors(self):
        vcolors = numpy_to_vtk_colors(self._colors)
        self.polydata.GetPointData().SetScalars(vcolors)

    def set_size(self, size):
        self.prop.SetPointSize(size)

    def set_symbol(self, symbol):
        assert symbol in ('point', 'sphere')

        if self._symbol != symbol:
            try:
                self.prop.SetRenderPointsAsSpheres(symbol == 'sphere')
            except AttributeError:
                if symbol == 'sphere':
                    logger.warn(
                        'Cannot render points as sphere with this version of '
                        'VTK')

            self._symbol = symbol


class PointDataInjector(va.VTKAlgorithm):
    def __init__(self, scalars):
        va.VTKAlgorithm.__init__(
            self,
            nInputPorts=1, inputType='vtkPolyData',
            nOutputPorts=1, outputType='vtkPolyData')

        self.scalars = scalars

    def RequestData(self, vtkself, request, inInfo, outInfo):
        inp = self.GetInputData(inInfo, 0, 0)
        out = self.GetOutputData(outInfo, 0)
        out.ShallowCopy(inp)
        out.GetPointData().SetScalars(self.scalars)

        return 1


def lighten(c, f):
    return tuple(255.-(255.-x)*f for x in c)


class BeachballPipe(object):

    def __init__(
            self, positions, m6s, sizes, depths, ren,
            level=3,
            face='backside',
            lighting=False):

        from pyrocko import moment_tensor, icosphere

        # cpt tricks

        cpt = pcpt.get_cpt('global_event_depth_2')
        cpt2 = pcpt.CPT()
        for ilevel, clevel in enumerate(cpt.levels):

            cpt_data = [
                (-1.0, ) + lighten(clevel.color_min, 0.2),
                (-0.05, ) + lighten(clevel.color_min, 0.2),
                (0.05, ) + clevel.color_min,
                (1.0, ) + clevel.color_min]

            cpt2.levels.extend(
                pcpt.CPTLevel(
                    vmin=a[0] + ilevel * 2.0,
                    vmax=b[0] + ilevel * 2.0,
                    color_min=a[1:],
                    color_max=b[1:])
                for (a, b) in zip(cpt_data[:-1], cpt_data[1:]))

        def depth_to_ilevel(cpt, depth):
            for ilevel, clevel in enumerate(cpt.levels):
                if depth < clevel.vmax:
                    return ilevel

            return len(cpt.levels) - 1

        # source

        vertices, faces = icosphere.sphere(
            level, 'icosahedron', 'kind1', radius=1.0,
            triangulate=False)

        p_vertices = vtk.vtkPoints()
        p_vertices.SetNumberOfPoints(vertices.shape[0])
        p_vertices.SetData(numpy_to_vtk(vertices))

        pd = vtk.vtkPolyData()
        pd.SetPoints(p_vertices)

        cells = faces_to_cells(faces)

        pd.SetPolys(cells)

        # positions

        p_positions = vtk.vtkPoints()
        p_positions.SetNumberOfPoints(positions.shape[0])
        p_positions.SetData(numpy_to_vtk(positions))

        pd_positions = vtk.vtkPolyData()
        pd_positions.SetPoints(p_positions)
        pd_positions.GetPointData().SetScalars(numpy_to_vtk(sizes))

        latlons = od.xyz_to_latlon(positions)

        # glyph

        glyph = vtk.vtkGlyph3D()
        glyph.ScalingOn()
        glyph.SetScaleModeToScaleByScalar()
        glyph.SetSourceData(pd)

        if True:
            glyph.SetInputData(pd_positions)
            glyph.SetScaleFactor(0.005)
        else:
            pd_distance_scaler = vtk.vtkDistanceToCamera()
            pd_distance_scaler.SetInputData(pd_positions)
            pd_distance_scaler.SetRenderer(ren)
            pd_distance_scaler.SetScreenSize(10)

            glyph.SetInputConnection(pd_distance_scaler.GetOutputPort())
            glyph.SetInputArrayToProcess(
                0, 0, 0,
                vtk.vtkDataObject.FIELD_ASSOCIATION_POINTS, "DistanceToCamera")

        self.glyph = glyph

        nvertices = vertices.shape[0]
        amps = num.zeros(m6s.shape[0] * nvertices)
        for i, m6 in enumerate(m6s):
            m = moment_tensor.symmat6(*m6)
            m /= num.linalg.norm(m) / num.sqrt(2.0)
            (ep, en, et), m_evecs = num.linalg.eigh(m)
            if num.linalg.det(m_evecs) < 0.:
                m_evecs *= -1.
            vp, vn, vt = m_evecs.T
            to_e = num.vstack((vn, vt, vp))

            xyz_to_ned_00 = num.array([
                        [0., 0., 1.],
                        [0., 1., 0.],
                        [-1., 0., 0.]])

            zero_to_latlon = od.rot_to_00(*latlons[i])

            rot = num.dot(num.dot(to_e, xyz_to_ned_00), zero_to_latlon)

            vecs_e = num.dot(rot, vertices.T).T

            rtp = geometry.xyz2rtp(vecs_e)

            atheta, aphi = rtp[:, 1], rtp[:, 2]
            amps_this = ep * num.cos(atheta)**2 + (
                en * num.cos(aphi)**2 +
                et * num.sin(aphi)**2) * num.sin(atheta)**2

            amps_this = num.clip(amps_this, -0.9, 0.9) \
                + depth_to_ilevel(cpt, depths[i]) * 2

            amps[i*nvertices:(i+1)*nvertices] = amps_this

        vamps = numpy_to_vtk(amps)

        glyph.Update()

        pd_injector = PointDataInjector(vamps)

        pd_injector_pa = vtk.vtkPythonAlgorithm()
        pd_injector_pa.SetPythonObject(pd_injector)

        pd_injector_pa.SetInputConnection(glyph.GetOutputPort())

        mapper = vtk.vtkPolyDataMapper()
        mapper.ScalarVisibilityOn()
        mapper.InterpolateScalarsBeforeMappingOn()

        mapper.SetInputConnection(pd_injector_pa.GetOutputPort())
        mapper.Update()

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        self.prop = actor.GetProperty()
        self.set_lighting(lighting)
        self.set_face(face)

        lut = cpt_to_vtk_lookuptable(cpt2, n=10000)
        mapper.SetUseLookupTableScalarRange(True)
        mapper.SetLookupTable(lut)

        self.actor = actor

    def set_face(self, face='backside'):
        if face == 'backside':
            self.prop.FrontfaceCullingOn()
            self.prop.BackfaceCullingOff()
        elif face == 'frontside':
            self.prop.FrontfaceCullingOff()
            self.prop.BackfaceCullingOn()

    def set_lighting(self, lighting=False):
        self.prop.SetLighting(lighting)

    def set_size_factor(self, factor):
        self.glyph.SetScaleFactor(factor)


def faces_to_cells(faces):
    cells = vtk.vtkCellArray()

    for face in faces:
        cells.InsertNextCell(face.size)
        for ivert in face:
            cells.InsertCellPoint(ivert)

    return cells


class TrimeshPipe(object):
    def __init__(
            self, vertices,
            faces=None,
            cells=None,
            values=None,
            smooth=False,
            cpt=None,
            lut=None,
            backface_culling=True):

        self._opacity = 1.0
        self._smooth = None
        self._lut = None

        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(numpy_to_vtk(vertices))

        pd = vtk.vtkPolyData()
        pd.SetPoints(vpoints)

        if faces is not None:
            cells = faces_to_cells(faces)

        pd.SetPolys(cells)

        mapper = vtk.vtkPolyDataMapper()

        mapper.ScalarVisibilityOff()

        act = vtk.vtkActor()
        act.SetMapper(mapper)
        prop = act.GetProperty()
        self.prop = prop
        prop.SetColor(0.5, 0.5, 0.5)

        if backface_culling:
            prop.BackfaceCullingOn()
        else:
            prop.BackfaceCullingOff()

        # prop.EdgeVisibilityOn()
        # prop.SetInterpolationToGouraud()
        self._shading = None
        self.set_shading('phong')
        self._color = None
        self.set_color(Color('aluminium3'))

        self._ambient = None
        self.set_ambient(0.0)
        self._diffuse = None
        self.set_diffuse(1.0)
        self._specular = None
        self.set_specular(0.0)

        self.polydata = pd
        self.mapper = mapper
        self.actor = act

        self.set_smooth(smooth)

        if values is not None:
            mapper.ScalarVisibilityOn()
            self.set_values(values)

        if cpt is not None:
            self.set_cpt(cpt)

        if lut is not None:
            self.set_lookuptable(lut)

    def set_color(self, color):
        if self._color is None or color != self._color:
            self.prop.SetColor(*color.rgb)
            self._color = color

    def set_ambient(self, ambient):
        if self._ambient is None or ambient != self._ambient:
            self.prop.SetAmbient(ambient)
            self._ambient = ambient

    def set_diffuse(self, diffuse):
        if self._diffuse is None or diffuse != self._diffuse:
            self.prop.SetDiffuse(diffuse)
            self._diffuse = diffuse

    def set_specular(self, specular):
        if self._specular is None or specular != self._specular:
            self.prop.SetSpecular(specular)
            self._specular = specular

    def set_shading(self, shading):
        if self._shading is None or self._shading != shading:
            vtk_set_prop_interpolation(self.prop, shading)
            self._shading = shading

    def set_smooth(self, smooth):
        if self._smooth is None or self._smooth != smooth:
            if not smooth:
                # stripper = vtk.vtkStripper()
                # stripper.SetInputData(self.polydata)
                # stripper.Update()
                # self.mapper.SetInputConnection(stripper.GetOutputPort())

                vtk_set_input(self.mapper, self.polydata)
            else:
                # stripper = vtk.vtkStripper()
                # stripper.SetInputData(self.polydata)
                # stripper.Update()

                normals = vtk.vtkPolyDataNormals()
                normals.SetFeatureAngle(60.)
                normals.ConsistencyOff()
                normals.SplittingOff()
                # normals.SetInputConnection(stripper.GetOutputPort())
                normals.SetInputData(self.polydata)

                self.mapper.SetInputConnection(normals.GetOutputPort())

            self._smooth = smooth

    def set_opacity(self, opacity):
        opacity = float(opacity)
        if self._opacity != opacity:
            self.prop.SetOpacity(opacity)
            self._opacity = opacity

    def set_vertices(self, vertices):
        self.polydata.GetPoints().SetData(numpy_to_vtk(vertices))

    def set_values(self, values):
        vvalues = numpy_to_vtk(values)
        self.polydata.GetCellData().SetScalars(vvalues)
        # self.mapper.SetScalarRange(values.min(), values.max())

    def set_lookuptable(self, lut):
        if self._lut is not lut:
            self.mapper.SetUseLookupTableScalarRange(True)
            self.mapper.SetLookupTable(lut)
            self._lut = lut

    def set_cpt(self, cpt):
        self.set_lookuptable(cpt_to_vtk_lookuptable(cpt))


class OutlinesPipe(object):

    def __init__(self, geom, color, cs='latlon'):

        self._polyline_grid = None
        self.actors = None

        lines = []
        for outline in geom.outlines:
            latlon = outline.get_col('latlon')
            depth = outline.get_col('depth')

            points = num.concatenate(
                (latlon, depth.reshape(len(depth), 1)),
                axis=1)
            points = num.concatenate(
                (points, points[0].reshape(1, -1)), axis=0)

            lines.append(points)

        mapper = vtk.vtkDataSetMapper()
        if cs == 'latlondepth':
            self._polyline_grid = make_multi_polyline(
                lines_latlondepth=lines)
        elif cs == 'latlon':
            self._polyline_grid = make_multi_polyline(
                lines_latlon=lines)
        else:
            raise ValueError('cs=%s is not supported!' % cs)

        vtk_set_input(mapper, self._polyline_grid)

        actor = vtk.vtkActor()
        actor.SetMapper(mapper)

        prop = actor.GetProperty()
        prop.SetDiffuseColor(color)
        prop.SetOpacity(1.)

        self.actor = actor


class PolygonPipe(object):
    def __init__(self, vertices, faces, values=None, cpt=None, lut=None):
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
        self.prop = prop

        self.polydata = pd
        self.mapper = mapper
        self.actor = act

        self._colors = num.ones((faces.shape[0], 4))

        if values is not None:
            self.set_values(values)

        if cpt is not None:
            self.set_cpt(cpt)

        self._lut = None
        if lut is not None:
            self.set_lookuptable(lut)
            self._lut = lut

    def set_colors(self, colors):
        self._colors[:, :3] = colors
        self._update_colors()

    def set_uniform_color(self, color):
        npolys = self.polydata.GetNumberOfCells()

        colors = num.ones((npolys, 4))
        colors[:, :3] *= color
        self._colors = colors

        self._update_colors()

    def set_alpha(self, alpha):
        self._colors[:, 3] = alpha
        self._update_colors()

    def _update_colors(self):
        vcolors = numpy_to_vtk_colors(self._colors)
        self.polydata.GetCellData().SetScalars(vcolors)

    def set_opacity(self, value):
        self.prop.SetOpacity(value)

    def set_vertices(self, vertices):
        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(numpy_to_vtk(vertices))
        self.polydata.SetPoints(vpoints)

    def set_values(self, values):
        vvalues = numpy_to_vtk(values.astype(num.float64))
        self.polydata.GetCellData().SetScalars(vvalues)
        self.mapper.SetScalarRange(values.min(), values.max())

    def set_lookuptable(self, lut):
        if self._lut is not lut:
            self.mapper.SetUseLookupTableScalarRange(True)
            self.mapper.SetLookupTable(lut)
            self._lut = lut

    def set_cpt(self, cpt):
        self.set_lookuptable(cpt_to_vtk_lookuptable(cpt))


class ColorbarPipe(object):

    def __init__(self, parent_pipe=None, cbar_title=None, cpt=None, lut=None):
        act = vtk.vtkScalarBarActor()

        act.SetMaximumHeightInPixels(500)
        act.SetMaximumWidthInPixels(50)

        try:
            act.SetUnconstrainedFontSize(True)
        except AttributeError:
            pass

        self.prop = act.GetProperty()
        self.actor = act

        self._format_text()
        self._set_position(0.95, 0.05)

        if cbar_title is not None:
            self.set_title(cbar_title)

        if cpt is not None:
            self.set_cpt(cpt)

        if lut is not None:
            self.set_lookuptable(lut)

    def set_lookuptable(self, lut):
        lut.Build()
        self.actor.SetLookupTable(lut)

    def set_title(self, cbar_title):
        self.actor.SetTitle(cbar_title)

    def _format_text(self):

        prop_title = vtk.vtkTextProperty()
        prop_title.SetFontFamilyToArial()
        prop_title.SetColor(.8, .8, .8)
        prop_title.SetFontSize(int(prop_title.GetFontSize() * 1.3))
        prop_title.BoldOn()
        self.actor.SetTitleTextProperty(prop_title)
        try:
            self.actor.SetVerticalTitleSeparation(20)
        except AttributeError:
            pass

        prop_label = vtk.vtkTextProperty()
        prop_label.SetFontFamilyToArial()
        prop_label.SetColor(.8, .8, .8)
        prop_label.SetFontSize(int(prop_label.GetFontSize() * 1.1))
        self.actor.SetLabelTextProperty(prop_label)

    def _set_position(self, xpos, ypos):
        pos = self.actor.GetPositionCoordinate()
        pos.SetCoordinateSystemToNormalizedViewport()
        pos.SetValue(xpos, ypos)


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
        if vtk.vtkVersion.GetVTKMajorVersion() > 5:
            glyph.SetSourceData(arrow.GetOutput())
            glyph.SetInputData(pd)
        else:
            glyph.SetSource(arrow.GetOutput())
            glyph.SetInput(pd)

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
