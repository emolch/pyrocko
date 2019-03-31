class Overlay(object):

    def __init__(self):
        pass

    def set_parent(self, parent):
        pass

    def unset_parent(self):
        pass

    def show(self):
        pass

    def hide(self):
        pass


class TimeRangeOverlay(Overlay):

    def __init__(self):
        self._tmin

    def update_ranges(self, tmin, tmax, wmin, wmax):
        self._trange = tmin, tmax
        self._wrange = wmin, wmax

    def update_size(self, renwin):

        size_x, size_y = renwin.GetSize()
        cx = size_x / 2.0
        cy = size_y / 2.0

        vertices = num.array([
            [cx - 100., cx - 100., 0.0],
            [cx - 100., cx + 100., 0.0],
            [cx + 100., cx + 100., 0.0],
            [cx - 100., cx - 100., 0.0]])

        vpoints = vtk.vtkPoints()
        vpoints.SetNumberOfPoints(vertices.shape[0])
        vpoints.SetData(vtk_util.numpy_to_vtk(vertices))

        faces = num.array([[0, 1, 2, 3]], dtype=num.int)
        cells = vtk_util.faces_to_cells(faces)

        pd = vtk.vtkPolyData()
        pd.SetPoints(vpoints)
        pd.SetLines(cells)

        mapper = vtk.vtkPolyDataMapper2D()

        vtk_util.vtk_set_input(mapper, pd)

        act = vtk.vtkActor2D()
        act.SetMapper(mapper)

        prop = act.GetProperty()
        prop.SetColor(1.0, 1.0, 1.0)
        prop.SetOpacity(0.5)
        prop.SetLineWidth(2.0)
        print(type(prop), dir(prop))
        #prop.EdgeVisibilityOn()

        self.ren.AddActor2D(act)
