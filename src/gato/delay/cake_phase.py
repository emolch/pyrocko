# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

import numpy as num

from pyrocko.guts import Float, List, String
from pyrocko import cake
from pyrocko import spit
from .base import DelayMethod
from ..grid.location import LocationGrid, distances_surface
from pyrocko.gf import Earthmodel1D

NA = num.newaxis


class CakePhaseDM(DelayMethod):

    earthmodel = Earthmodel1D.T()
    phases = List.T(String.T())
    offset = Float.T(default=0.0)
    factor = Float.T(default=1.0)
    time_tolerance = Float.T()
    distance_tolerance = Float.T()
    depth_tolerance = Float.T()

    def evaluate(self, source_depth, receiver_depth, distance_surface):
        phase_defs = [cake.PhaseDef(phase) for phase in self.phases]
        t = [ray.t for ray in self.earthmodel.arrivals(
            phases=phase_defs,
            distances=[distance_surface*cake.m2d],
            zstart=source_depth,
            zstop=receiver_depth)]

        return min(t) if t else None

    def make_sptree(self, ddd):
        x_tolerance = num.array(
            [self.depth_tolerance, self.depth_tolerance,
             self.distance_tolerance], dtype=float)

        x_bounds = num.zeros((3, 2))
        x_bounds[:, 0] = num.min(ddd, axis=(0, 1))
        x_bounds[:, 1] = num.max(ddd, axis=(0, 1))

        def evaluate(x):
            return self.evaluate(*x)

        sptree = spit.SPTree(
            f=evaluate,
            ftol=self.time_tolerance,
            xbounds=x_bounds,
            xtols=x_tolerance)

        return sptree

    def calculate(self, source_grid, receiver_grid):
        self._check_type('source_grid', source_grid, LocationGrid)
        self._check_type('receiver_grid', receiver_grid, LocationGrid)

        ddd = num.zeros((len(source_grid), len(receiver_grid), 3))
        ddd[:, :, 0] = source_grid.get_nodes('latlondepth')[:, NA, 2]
        ddd[:, :, 1] = receiver_grid.get_nodes('latlondepth')[NA, :, 2]
        ddd[:, :, 1] = 0.0
        ddd[:, :, 2] = distances_surface(source_grid, receiver_grid)

        sptree = self.make_sptree(ddd)
        ddd2 = ddd.reshape((len(source_grid)*len(receiver_grid), 3))
        tt2 = sptree.interpolate_many(
            ddd2).reshape(len(source_grid), len(receiver_grid))

        tt1 = num.vectorize(self.evaluate)(
            ddd[:, :, 0], ddd[:, :, 1], ddd[:, :, 2])

        print(tt1)
        print(tt2)


# class CakePhaseShifter(Shifter):
#
#     def setup(self, config):
#         Shifter.setup(self, config)
#         self._earthmodels = config.earthmodels
#         self._earthmodels.extend(
#             [
#                 CakeEarthmodel(
#                     id=fn,
#                     earthmodel_1d=cake.load_model(
#                         cake.builtin_model_filename(fn)))
#                 for fn in cake.builtin_models()
#             ]
#         )
#         self._tabulated_phases = config.tabulated_phases
#
#         if not self._tabulated_phases:
#             raise LassieError('missing tabulated phases in config')
#
#         self._cache_path = config.expand_path(config.cache_path)
#
#     def get_earthmodel(self):
#         for earthmodel in self._earthmodels:
#             if isinstance(earthmodel, CakeEarthmodel):
#                 if earthmodel.id == self.earthmodel_id:
#                     return earthmodel.earthmodel_1d
#
#         raise LassieError(
#             'no cake earthmodel with id "%s" found' % self.earthmodel_id)
#
#     def get_vmin(self):
#         vs = self.get_earthmodel().profile('vs')
#         vp = self.get_earthmodel().profile('vp')
#         v = num.concatenate((vs, vp))
#         vmin = num.min(v[v != 0.0])
#         return vmin
#
#     def ttt_path(self, ehash):
#         return op.join(self._cache_path, ehash + '.spit')
#
#     def ttt_hash(self, earthmodel, phases, x_bounds, x_tolerance,
# t_tolerance):
#         f = BytesIO()
#         earthmodel.profile('z').dump(f)
#         earthmodel.profile('vp').dump(f)
#         earthmodel.profile('vs').dump(f)
#         earthmodel.profile('rho').dump(f)
#
#         f.write(b','.join(phase.definition().encode() for phase in phases))
#         x_bounds.dump(f)
#         x_tolerance.dump(f)
#         f.write(str(t_tolerance).encode())
#         s = f.getvalue()
#         h = hashlib.sha1(s).hexdigest()
#         f.close()
#         return h
#
#     def get_table(self, grid, receivers):
#         distances = grid.lateral_distances(receivers)
#         r_depths = num.array([r.z for r in receivers], dtype=float)
#         s_depths = grid.depths()
#         x_bounds = num.array(
#             [[num.min(r_depths), num.max(r_depths)],
#              [num.min(s_depths), num.max(s_depths)],
#              [num.min(distances), num.max(distances)]], dtype=float)
#
#         x_tolerance = num.array((grid.dz/2., grid.dz/2., grid.dx/2.))
#         t_tolerance = grid.max_delta()/(self.get_vmin()*5.)
#         earthmodel = self.get_earthmodel()
#
#         interpolated_tts = {}
#
#         for phase_def in self._tabulated_phases:
#             ttt_hash = self.ttt_hash(
#                 earthmodel, phase_def.phases, x_bounds, x_tolerance,
#                 t_tolerance)
#
#             fpath = self.ttt_path(ttt_hash)
#
#             if not op.exists(fpath):
#                 def evaluate(args):
#                     receiver_depth, source_depth, x = args
#                     t = []
#                     rays = earthmodel.arrivals(
#                         phases=phase_def.phases,
#                         distances=[x*cake.m2d],
#                         zstart=source_depth,
#                         zstop=receiver_depth)
#
#                     for ray in rays:
#                         t.append(ray.t)
#
#                     if t:
#                         return min(t)
#                     else:
#                         return None
#
#                 logger.info(
#                     'prepare tabulated phases: %s [%s]' % (
#                         phase_def.id, ttt_hash))
#
#                 sptree = spit.SPTree(
#                     f=evaluate,
#                     ftol=t_tolerance,
#                     xbounds=x_bounds,
#                     xtols=x_tolerance)
#
#                 util.ensuredirs(fpath)
#                 sptree.dump(filename=fpath)
#             else:
#                 sptree = spit.SPTree(filename=fpath)
#
#             interpolated_tts["stored:"+str(phase_def.id)] = sptree
#
#         arrivals = num.zeros(distances.shape)
#
#         def interpolate(phase_id):
#             return interpolated_tts[phase_id].interpolate_many
#
#         for i_r, r in enumerate(receivers):
#             r_depths = num.zeros(distances.shape[0]) + r.z
#             coords = num.zeros((distances.shape[0], 3))
#             coords[:, 0] = r_depths
#             coords[:, 1] = s_depths
#             coords[:, 2] = distances[:, i_r]
#             arr = self.timing.evaluate(interpolate, coords)
#             arrivals[:, i_r] = arr
#
#         return arrivals * self.factor + self.offset

__all__ = [
    'CakePhaseDM',
]
