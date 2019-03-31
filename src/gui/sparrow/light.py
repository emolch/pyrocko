from pyrocko.plot import mpl_color
from pyrocko import icosphere
import vtk


tetra, _ = icosphere.tetrahedron()
tetra *= -1.0

lighting_themes = [
    ('warm', [
        ((1., 1., 0.69),    tetra[0, :]),
        ((1., 0.53, 0.0), tetra[1, :]),
        ((0.53, 0.53, 0.37),     tetra[2, :])]),
    ('tilda', [
        ((1., 0.5, 0.5),  tetra[0, :]),
        ((0.5, 1.0, 1.0), tetra[1, :]),
        ((1., 0.5, 0.5),  tetra[2, :])]),
    ('test1', [
        ((1.0, 0.8, 0.8), tetra[0, :]),
        ((1.0, 1.0, 0.8), tetra[1, :]),
        ((1.0, 1.0, 0.8), tetra[2, :])]),
    ('desk', [
        ((1.0, 0.9, 0.8),  (-1.0, 1.0, 1.0))]),
    ('morning', [
        ((1.0, 0.9, 0.8),  (1.0, 0.0, 0.0))]),
    ('forenoon', [
        ((1.0, 0.9, 0.8),  (1.0, 0.0, 1.0))]),
    ('afternoon', [
        ((1.0, 0.9, 0.8),  (-1.0, 0.0, 1.0))]),
    ('evening', [
        ((1.0, 0.8, 0.7),  (-1.0, 0.0, 0.0))]),
    ('interrogation', [
        ((1.0, 1.0, 1.0),  (0.0, 0.0, 1.0))]),
    ('tango', [
        (mpl_color('scarletred1'), tetra[0, :]),
        (mpl_color('skyblue1'), tetra[1, :]),
        (mpl_color('orange1'), tetra[2, :])])]

lighting_themes_d = dict(lighting_themes)


def get_lighting_theme(theme):
    # also check for user defined?
    return lighting_themes_d[theme]


def get_lighting_theme_names():
    return [name for (name, _) in lighting_themes]


def get_lights(theme):
    lights = []
    for color, position in lighting_themes_d[theme]:
        light = vtk.vtkLight()
        light.SetColor(*color)
        light.SetPosition(*position)
        light.SetFocalPoint(0., 0., 0.)
        light.SetLightTypeToCameraLight()
        lights.append(light)

    return lights
