# http://pyrocko.org - GPLv3
#
# The Pyrocko Developers, 21st Century
# ---|P------/S----------~Lg----------

from ..snuffling import Snuffling, Param, Switch, Choice
from ..marker import PhaseMarker
from pyrocko import gf
from pyrocko import cake
import numpy as num


class CakePhase(Snuffling):

    def help(self):
        return '''
<html>
<head>
<style type="text/css">
    body { margin-left:10px };
</style>
</head>
<body>
<h1 align="center">Theoretical Phase Arrivals</h1>
<p>
This snuffling uses pyrocko's
<a href="http://emolch.github.io/pyrocko/v0.3/cake_doc.html">Cake</a>
module to calculate seismic rays for layered earth models. </p>
<p>
<b>Parameters:</b><br />
    <b>&middot; Global shift</b>  -  Add time onset to phases. <br />
    <b>&middot; Add Model</b>  -  Add a model to drop down menu. <br />
    <b>&middot; Add Phase</b>  -  Add a phase definition.
        (GUI reset required)<br />
</p>
<p>
Instructions and information on Cake's syntax of seismic rays can be
found in the
<a href="http://emolch.github.io/pyrocko/
v0.3/cake_doc.html#cmdoption-cake--phase">Cake documentation</a>.
</p>
</body>
</html>
        '''

    def setup(self):
        self.set_name('Cake Phase')

        # self._phase_names = ('PmP ~S ~P ~P(moho)s ~P(sill-top)s'
        #                       ' ~P(sill-bottom)s Pdiff').split()
        self._phase_names = ('~P Pg Sg pP p P Pdiff PKP PcP PcS PKIKP pPKIKP'
                             ' SSP PPS SPP PSP SP PS ~PS ~SP Pn s S Sn PP PPP'
                             ' ScS Sdiff SS SSS SKS SKIKS').split()

        for iphase, name in enumerate(self._phase_names):
            self.add_parameter(Switch(name, 'wantphase_%i' % iphase,
                                      iphase == 0))

        model_names = cake.builtin_models()
        model_names = [
                'Cake builtin: %s' % model_name for model_name in model_names]

        self._engine = gf.LocalEngine(use_config=True)
        store_ids = self._engine.get_store_ids()

        for store_id in store_ids:
            model_names.append('GF Store: %s' % store_id)

        self._models = model_names

        self.model_choice = Choice('Model', 'chosen_model',
                                   'ak135-f-continental.m', self._models)

        self.add_parameter(self.model_choice)

        self.add_parameter(Param('Global shift', 'tshift', 0., -20., 20.))
        self.add_parameter(Switch('Use station depth',
                                  'use_station_depth', False))
        self.add_trigger('Add Phase', self.add_phase_definition)
        self.add_trigger('Add Model', self.add_model_to_choice)
        self.add_trigger('Plot Model', self.plot_model)
        self.add_trigger('Plot Rays', self.plot_rays)

        self._phases = {}
        self._model = None

    def panel_visibility_changed(self, bool):
        pass

    def wanted_phases(self):
        try:
            wanted = []
            for iphase, name in enumerate(self._phase_names):
                if getattr(self, 'wantphase_%i' % iphase):
                    if name in self._phases:
                        phases = self._phases[name]
                    else:
                        if name.startswith('~'):
                            phases = [cake.PhaseDef(name[1:])]
                        else:
                            phases = cake.PhaseDef.classic(name)

                        self._phases[name] = phases
                        for pha in phases:
                            pha.name = name

                    wanted.extend(phases)
        except (cake.UnknownClassicPhase, cake.PhaseDefParseError) as e:
            self.fail(str(e))

        return wanted

    def call(self, plot_rays=False):

        self.cleanup()
        wanted = self.wanted_phases()

        if not wanted:
            return

        event, stations = self.get_active_event_and_stations()

        if not stations:
            self.fail('No station information available.')

        self.update_model()
        model = self._model[1]

        depth = event.depth
        if depth is None:
            depth = 0.0

        allrays = []
        alldists = []
        for station in stations:
            dist = event.distance_to(station)
            alldists.append(dist)

            if self.use_station_depth:
                rdepth = station.depth
            else:
                rdepth = 0.0

            multi_dists = []
            nmax = 1
            for i in range(0, nmax):
                multi_dists.append(dist*cake.m2d + 360.*i)
                multi_dists.append((i+1)*360. - dist*cake.m2d)

            rays = model.arrivals(
                phases=wanted,
                distances=multi_dists,
                zstart=depth,
                zstop=rdepth)

            for ray in rays:
                time = ray.t
                name = ray.given_phase().name
                incidence_angle = ray.incidence_angle()
                takeoff_angle = ray.takeoff_angle()

                time += event.time + self.tshift
                m = PhaseMarker([(station.network, station.station, '*', '*')],
                                time, time, 2,
                                phasename=name,
                                event=event,
                                incidence_angle=incidence_angle,
                                takeoff_angle=takeoff_angle)
                self.add_marker(m)

            allrays.extend(rays)

        if plot_rays:
            fig = self.figure(name='Ray Paths')
            from pyrocko.plot import cake_plot
            cake_plot.my_rays_plot(model, None, allrays, depth, 0.0,
                                   num.array(alldists)*cake.m2d,
                                   axes=fig.gca())

            fig.canvas.draw()

    def update_model(self):
        if not self._model or self._model[0] != self.chosen_model:
            if self.chosen_model.startswith('Cake builtin: '):
                load_model = cake.load_model(
                    self.chosen_model.split(': ', 1)[1])

            elif self.chosen_model.startswith('GF Store: '):
                store_id = self.chosen_model.split(': ', 1)[1]

                load_model = self._engine.get_store(store_id)\
                    .config.earthmodel_1d
            else:
                load_model = cake.load_model(self.chosen_model)

            self._model = (self.chosen_model, load_model)

    def update_model_choices(self):
        self.set_parameter_choices('chosen_model', self._models)

    def add_model_to_choice(self):
        '''
        Called from trigger 'Add Model'.

        Adds another choice to the drop down 'Model' menu.
        '''

        in_model = self.input_filename('Load Model')
        if in_model not in self._models:
            self._models.append(in_model)
            self.update_model_choices()

        self.set_parameter('chosen_model', in_model)
        self.call()

    def add_phase_definition(self):
        '''
        Called from trigger 'Add Phase Definition'.

        Adds another phase option.
        Requires a reset of the GUI.
        '''
        phase_def = str(self.input_dialog('Add New Phase',
                                          'Enter Phase Definition'))
        self._phase_names.append(phase_def)

        self.add_parameter(
            Switch(phase_def,
                   'wantphase_%s' % str(len(self._phase_names)-1), True))
        self.reset_gui(reloaded=True)
        self.call()

    def plot_model(self):
        self.update_model()

        from pyrocko.plot import cake_plot

        fig = self.figure(name='Model: %s' % self._model[0])

        cake_plot.my_model_plot(self._model[1], axes=fig.gca())

        fig.canvas.draw()

    def plot_rays(self):
        self.call(plot_rays=True)


def __snufflings__():
    '''
    Returns a list of snufflings to be exported by this module.
    '''

    return [CakePhase()]
