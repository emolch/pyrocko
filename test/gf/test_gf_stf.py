import math
import unittest
import os
import numpy as num

from pyrocko import gf, util

r2d = 180. / math.pi
d2r = 1.0 / r2d
km = 1000.
show_plot = int(os.environ.get('MPL_SHOW', 0))


def numeq(a, b, eps):
    return (num.all(num.asarray(a).shape == num.asarray(b).shape and
            num.abs(num.asarray(a) - num.asarray(b)) < eps))


class GFSTFTestCase(unittest.TestCase):

    def __init__(self, *args, **kwargs):
        unittest.TestCase.__init__(self, *args, **kwargs)

    def test_stf_triangular(self):
        from matplotlib import pyplot as plt

        tref = 10.
        for duration in [0., 3.]:
            for peak_ratio in num.linspace(0., 1., 11):
                stf = gf.TriangularSTF(
                    duration=duration, peak_ratio=peak_ratio, anchor=0.)
                t, a = stf.discretize_t(deltat=0.1, tref=tref)
                assert numeq(stf.centroid_time(tref), tref, 1e-5)
                if show_plot:
                    plt.title('Triangular')
                    plt.plot(t, a)
                    plt.plot(t, a, 'o')

        if show_plot:
            plt.show()

    def test_stf_boxcar(self):
        from matplotlib import pyplot as plt

        for duration in [0., 1., 2., 3.]:
            tref = 10.02
            stf = gf.BoxcarSTF(duration=duration, anchor=0.)
            t, a = stf.discretize_t(deltat=0.1, tref=tref)
            assert numeq(stf.centroid_time(tref), tref, 1e-5)
            if show_plot:
                plt.title('Boxcar')
                plt.plot(t, a)
                plt.plot(t, a, 'o')

        if show_plot:
            plt.show()

    def test_stf_half_sinusoid(self):
        from matplotlib import pyplot as plt

        for duration in [0., 1., 2., 3.]:
            tref = 10.02
            stf = gf.HalfSinusoidSTF(duration=duration, anchor=0.)
            t, a = stf.discretize_t(deltat=0.1, tref=tref)
            assert numeq(stf.centroid_time(tref), tref, 1e-5)
            if show_plot:
                plt.title('Half Sinosoid')
                plt.plot(t, a)
                plt.plot(t, a, 'o')

        if show_plot:
            plt.show()

    def test_stf_resonator(self):
        from matplotlib import pyplot as plt

        duration = 30.
        frequency = 1./15
        tref = 20.
        deltat = 0.1

        stf = gf.ResonatorSTF(duration=duration, frequency=frequency)
        t, a = stf.discretize_t(deltat=deltat, tref=tref)
        if show_plot:
            plt.title('Resonator')
            plt.plot(t, a)
            plt.plot(t, a, 'o')

        if show_plot:
            plt.show()

    def test_stf_multi_triangle(self):
        stf = gf.MultiTriangleSTF(
            deltat=2.0,
            amplitudes=num.array([1.0, 3.0, 0.5]),
            anchor=0.0)

        for deltat in [0.1, 0.2, 5.0, 10.0, 20.0]:
            times, amplitudes = stf.discretize_t(deltat, 0.)
            integral = num.sum(amplitudes)
            assert numeq(integral, 9.0, 1e-6)

        stf.normalize()

        for deltat in [0.1, 0.2, 5.0, 10.0, 20.0]:
            times, amplitudes = stf.discretize_t(deltat, 0.)
            integral = num.sum(amplitudes)
            assert numeq(integral, 1.0, 1e-6)

    def test_effective_durations(self):
        deltat = 1e-4
        for stf in [
                gf.HalfSinusoidSTF(duration=2.0),
                gf.HalfSinusoidSTF(duration=2.0, exponent=2),
                gf.TriangularSTF(duration=2.0, peak_ratio=0.),
                gf.TriangularSTF(duration=2.0, peak_ratio=1.),
                gf.TriangularSTF(duration=2.0, peak_ratio=0.5),
                gf.BoxcarSTF(duration=2.0)]:

            t, a = stf.discretize_t(deltat, 0.0)
            t0 = stf.centroid_time(0.0)

            edur = num.sqrt(num.sum((t-t0)**2 * a)) * 2. * num.sqrt(3.)
            assert abs(edur - stf.effective_duration) < 1e-3

    def test_objects(self):
        for stf_class in gf.seismosizer.stf_classes:
            if stf_class in (
                    gf.STF,
                    gf.ResonatorSTF,
                    gf.SimpleLandslideSTF,
                    gf.MultiTriangleSTF):

                continue

            d1 = 2.0
            stf = stf_class(effective_duration=d1)
            d2 = stf.effective_duration
            assert abs(d2 - d1) < 1e-4


if __name__ == '__main__':
    util.setup_logging('test_gf_stf', 'warning')
    unittest.main()
