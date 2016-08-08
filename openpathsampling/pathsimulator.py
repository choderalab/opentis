import time
import sys
import logging
import numpy as np
import pandas as pd

from openpathsampling.netcdfplus import StorableNamedObject, StorableObject

import openpathsampling as paths
import openpathsampling.tools

from openpathsampling.pathmover import SubPathMover
from ops_logging import initialization_logging
import abc

logger = logging.getLogger(__name__)
init_log = logging.getLogger('openpathsampling.initialization')


class MCStep(StorableObject):
    """
    A monte-carlo step in the main PathSimulation loop

    It references all objects created and used in a MC step. The used mover,
    and simulator as well as the initial and final sampleset, the step
    number and the generated movechange.

    Attributes
    ----------
    simulation : PathSimulation
        the running pathsimulation responsible for generating the step
    mccycle : int
        the step number counting from the root sampleset
    previous : SampleSet
        the initial (pre) sampleset
    active : SampleSet
        the final (post) sampleset
    change : MoveChange
        the movechange describing the transition from pre to post
    """
    def __init__(self,
                 simulation=None,
                 mccycle=-1,
                 previous=None,
                 active=None,
                 change=None
                 ):

        super(MCStep, self).__init__()
        self.simulation = simulation
        self.previous = previous
        self.active = active
        self.change = change
        self.mccycle = mccycle


class PathSimulator(StorableNamedObject):
    __metaclass__ = abc.ABCMeta

    calc_name = "PathSimulator"
    _excluded_attr = ['sample_set', 'step', 'save_frequency',
                      'output_stream']

    def __init__(self, storage):
        super(PathSimulator, self).__init__()
        self.storage = storage
        self.save_frequency = 1
        self.step = 0
        initialization_logging(
            logger=init_log, obj=self,
            entries=['storage']#, 'engine']
        )
        self.sample_set = None
        self.output_stream = sys.stdout  # user can change to file handler

    # TODO: Remove, is not used
    def set_replicas(self, samples):
        self.sample_set = paths.SampleSet(samples)

    def sync_storage(self):
        """
        Will sync all collective variables and the storage to disk
        """
        if self.storage is not None:
            self.storage.sync_all()

    @abc.abstractmethod
    def run(self, n_steps):
        """
        Run the simulator for a number of steps

        Parameters
        ----------
        n_steps : int
            number of step to be run
        """
        pass

    def save_initial(self):
        """
        Save the initial state as an MCStep to the storage
        """
        mcstep = MCStep(
            simulation=self,
            mccycle=self.step,
            previous=None,
            active=self.sample_set,
            change=paths.EmptyMoveChange()
        )

        if self.storage is not None:
            self.storage.steps.save(mcstep)
            self.storage.sync_all()

        return mcstep


class BootstrapPromotionMove(SubPathMover):
    """
    Bootstrap promotion is the combination of an EnsembleHop (to the next
    ensemble up) with incrementing the replica ID.
    """
    def __init__(self, bias=None, shooters=None, ensembles=None):
        """
        Parameters
        ----------
        bias : None
            not used yet, only for API consistency and later implementation
        shooters : list of ShootingMovers
            list of ShootingMovers for each ensemble
        ensembles : list of Ensembles
            list of ensembles the move should act on

        Notes
        -----
        The bootstrapping will use the ensembles sequentially so it requires
        that all ensembles have a reasonable overlab using shooting moves.

        """
        self.shooters = shooters
        self.bias = bias
        self.ensembles = ensembles
        initialization_logging(logger=init_log, obj=self,
                               entries=['bias', 'shooters', 'ensembles'])

        ens_pairs = [[self.ensembles[i], self.ensembles[i+1]]
                     for i in range(len(self.ensembles)-1)]

        # Bootstrapping sets numeric replica IDs. If the user wants it done
        # differently, the user can change it.
        self._ensemble_dict = {ens : rep for rep, ens in enumerate(ensembles) }
        
        # Create all possible hoppers so we do not have to recreate these
        # every time which will result in more efficient storage
        mover = paths.LastAllowedMover([
            # writing an algorithm this convoluted can get you shot in Texas
            paths.PartialAcceptanceSequentialMover(
                movers=[
                    shoot,
                    paths.EnsembleHopMover(
                        ensemble=enss[0],
                        target_ensemble=enss[1],
                        change_replica=self._ensemble_dict[enss[1]]
                    )
                ]
            ) for (enss, shoot) in zip(ens_pairs, shooters)
        ])

        super(BootstrapPromotionMove, self).__init__(mover)


class Bootstrapping(PathSimulator):
    """Creates a SampleSet with one sample per ensemble.
    
    The ensembles for the Bootstrapping pathsimulator must be one ensemble
    set, in increasing order. Replicas are named numerically.
    """

    calc_name = "Bootstrapping"

    def __init__(
            self,
            storage,
            engine=None,
            movers=None,
            trajectory=None,
            ensembles=None
    ):
        """
        Parameters
        ----------
        storage : openpathsampling.storage.Storage
            the storage all results should be stored in
        engine : openpathsampling.DynamicsEngine
            the dynamics engine to be used
        movers : list of openpathsampling.PathMover
            list of shooters to be used in the BootstrapPromotionMove
        trajectory : openpathsampling.Trajectory
            an initial trajectory to be started from
        ensembles : nested list of openpathsampling.Ensemble
            the ensembles this move should act on
        """
        # TODO: Change input from trajectory to sample
        super(Bootstrapping, self).__init__(storage)
        self.engine = engine
        paths.EngineMover.default_engine = engine  # set the default
        self.ensembles = ensembles
        self.trajectory = trajectory

        sample = paths.Sample(
            replica=0,
            trajectory=trajectory,
            ensemble=self.ensembles[0]
        )

        self.sample_set = paths.SampleSet([sample])

        if movers is None:
            pass # TODO: implement defaults: one per ensemble, uniform sel
        else:
            self.movers = movers
        initialization_logging(init_log, self,
                               ['movers', 'ensembles'])
        init_log.info("Parameter: %s : %s", 'trajectory', str(trajectory))

        self._bootstrapmove = BootstrapPromotionMove(bias=None,
                                               shooters=self.movers,
                                               ensembles=self.ensembles
                                              )


    def run(self, n_steps):
        bootstrapmove = self._bootstrapmove

        cvs = []
        n_samples = 0

        if self.storage is not None:
            cvs = list(self.storage.cvs)
            n_samples = len(self.storage.snapshots)

        ens_num = len(self.sample_set)-1

        if self.step == 0:
            self.save_initial()

        failsteps = 0
        # if we fail n_steps times in a row, kill the job

        while ens_num < len(self.ensembles) - 1 and failsteps < n_steps:
            self.step += 1
            logger.info("Step: " + str(self.step)
                        + "   Ensemble: " + str(ens_num)
                        + "  failsteps = " + str(failsteps)
                       )
            paths.tools.refresh_output(
                ("Working on Bootstrapping cycle step %d" +
                " in ensemble %d/%d .\n") %
                ( self.step, ens_num + 1, len(self.ensembles) ),
                output_stream=self.output_stream
            )

            movepath = bootstrapmove.move(self.sample_set)
            samples = movepath.results
            new_sampleset = self.sample_set.apply_samples(samples)

#            samples = movepath.results
#            logger.debug("SAMPLES:")
#            for sample in samples:
#                logger.debug("(" + str(sample.replica)
#                             + "," + str(sample.trajectory)
#                             + "," + repr(sample.ensemble)
#                            )


            mcstep = MCStep(
                simulation=self,
                mccycle=self.step,
                previous=self.sample_set,
                active=new_sampleset,
                change=movepath
            )


#            logger.debug("GLOBALSTATE:")
#            for sample in self.sample_set:
#                logger.debug("(" + str(sample.replica)
#                             + "," + str(sample.trajectory)
#                             + "," + repr(sample.ensemble)
#                            )



            if self.storage is not None:
                # compute all cvs now
                for cv in cvs:
                    n_len = len(self.storage.snapshots)
                    cv(self.storage.snapshots[n_samples:n_len])
                    n_samples = n_len

                self.storage.steps.save(mcstep)

            self.sample_set = new_sampleset

            old_ens_num = ens_num
            ens_num = len(self.sample_set)-1
            if ens_num == old_ens_num:
                failsteps += 1

            if self.step % self.save_frequency == 0:
                self.sample_set.sanity_check()
                self.sync_storage()

        self.sync_storage()

        paths.tools.refresh_output(
            ("DONE! Completed Bootstrapping cycle step %d" +
            " in ensemble %d/%d.\n") %
            ( self.step, ens_num + 1, len(self.ensembles) ),
            output_stream=self.output_stream
        )


class FullBootstrapping(PathSimulator):
    """
    Takes a snapshot as input; gives you back a sampleset with trajectories
    for every ensemble in the transition.

    This includes

    Parameters
    ----------
    transition : :class:`.TISTransition`
        the TIS transition to fill by bootstrapping
    snapshot : :class:`.Snapshot`
        the initial snapshot
    storage : :class:`.Storage`
        storage file to record the steps (optional)
    engine : :class:`.DynamicsEngine`
        MD engine to use for dynamics
    extra_interfaces : list of :class:`.Volume`
        additional interfaces to make into TIS ensembles (beyond those in
        the transition)
    extra_ensembles : list of :class:`.Ensemble`
        additional ensembles to sample after the TIS ensembles
    forbidden_states : list of :class:`.Volume`
        regions that are disallowed during the initial trajectory. Note that
        these region *are* allowed during the interface sampling
    initial_max_length : int
        maximum length of the initial A->A trajectory
    """
    calc_name = "FullBootstrapping"

    def __init__(self, transition, snapshot, storage=None, engine=None,
                 extra_interfaces=None, extra_ensembles=None,
                 forbidden_states=None, initial_max_length=None):
        super(FullBootstrapping, self).__init__(storage)
        self.engine = engine
        paths.EngineMover.default_engine = engine  # set the default
        if extra_interfaces is None:
            extra_interfaces = list()

        if forbidden_states is None:
            forbidden_states = list()
        interface0 = transition.interfaces[0]
        ensemble0 = transition.ensembles[0]
        state = transition.stateA
        self.state = state
        self.first_traj_ensemble = paths.SequentialEnsemble([
            paths.OptionalEnsemble(paths.AllOutXEnsemble(state)),
            paths.AllInXEnsemble(state),
            paths.OptionalEnsemble(
                paths.AllOutXEnsemble(state) & paths.AllInXEnsemble(interface0)
            ),
            paths.OptionalEnsemble(paths.AllInXEnsemble(interface0)),
            paths.AllOutXEnsemble(interface0),
            paths.OptionalEnsemble(paths.AllOutXEnsemble(state)),
            paths.SingleFrameEnsemble(paths.AllInXEnsemble(state))
        ]) & paths.AllOutXEnsemble(paths.join_volumes(forbidden_states))

        self.initial_max_length = initial_max_length

        if self.initial_max_length is not None:
            self.first_traj_ensemble = (
                paths.LengthEnsemble(slice(0, self.initial_max_length)) & 
                self.first_traj_ensemble
            )

        if extra_ensembles is None:
            extra_ensembles = []
        self.extra_ensembles = [
            paths.TISEnsemble(transition.stateA, transition.stateB, iface,
                              transition.orderparameter)
            for iface in extra_interfaces
        ] + extra_ensembles

        self.transition_shooters = [
            paths.OneWayShootingMover(selector=paths.UniformSelector(), 
                                      ensemble=ens,
                                      engine=self.engine) 
            for ens in transition.ensembles
        ]

        self.extra_shooters = [
            paths.OneWayShootingMover(selector=paths.UniformSelector(), 
                                      ensemble=ens,
                                      engine=self.engine) 
            for ens in self.extra_ensembles
        ]
        self.snapshot = snapshot.copy()
        self.ensemble0 = ensemble0
        self.all_ensembles = transition.ensembles + self.extra_ensembles
        self.n_ensembles = len(self.all_ensembles)
        self.error_max_rounds = True


    def run(self, max_ensemble_rounds=None, n_steps_per_round=20,
            build_attempts=20):
        #print first_traj_ensemble #DEBUG
        has_AA_path = False
        while not has_AA_path:
            self.engine.current_snapshot = self.snapshot.copy()
            self.engine.snapshot = self.snapshot.copy()
            self.output_stream.write("Building first trajectory\n")
            sys.stdout.flush()
            first_traj = self.engine.generate(
                self.engine.current_snapshot, 
                [self.first_traj_ensemble.can_append]
            )
            self.output_stream.write("Selecting segment\n")
            sys.stdout.flush()
            subtrajs = self.ensemble0.split(first_traj)
            if len(subtrajs) > 0:
                # if we have a short enough path go ahead
                subtraj = subtrajs[0]
                # check that this is A->A as well
                has_AA_path = self.state(subtraj[-1]) and self.state(subtraj[0])

            build_attempts -= 1
            if build_attempts == 0:
                raise RuntimeError('Too many attempts. Try another initial snapshot instead.')

            
        self.output_stream.write("Sampling " + str(self.n_ensembles) +
                                 " ensembles.\n")
        bootstrap = paths.Bootstrapping(
            storage=self.storage,
            ensembles=self.all_ensembles,
            movers=self.transition_shooters + self.extra_shooters,
            trajectory=subtraj
        )
        bootstrap.output_stream = self.output_stream
        self.output_stream.write("Beginning bootstrapping\n")
        n_rounds = 0
        n_filled = len(bootstrap.sample_set)
        while n_filled < self.n_ensembles:
            bootstrap.run(n_steps_per_round)

            if n_filled == len(bootstrap.sample_set):
                n_rounds += 1
            else:
                n_rounds = 0
            if n_rounds == max_ensemble_rounds:
                # hard equality instead of inequality so that None gives us
                # effectively infinite (rounds add one at a time
                msg = ("Too many rounds of bootstrapping: " + str(n_rounds)
                       + " round of " + str(n_steps_per_round) + " steps.")
                if self.error_max_rounds:
                    raise RuntimeError(msg)
                else: # pragma: no cover
                    logger.warning(msg)
                    break
            n_filled = len(bootstrap.sample_set)

        return bootstrap.sample_set


class PathSampling(PathSimulator):
    """
    General path sampling code. 
    
    Takes a single move_scheme and generates samples from that, keeping one
    per replica after each move. 
    """

    calc_name = "PathSampling"
    def __init__(
            self,
            storage,
            move_scheme=None,
            sample_set=None
    ):
        """
        Parameters
        ----------
        storage : openpathsampling.storage.Storage
            the storage where all results should be stored in
        engine : openpathsampling.DynamicsEngine
            the engine to be used with shooting moves
        move_scheme : openpathsampling.MoveScheme
            the move scheme used for the pathsampling cycle
        sample_set : openpathsampling.SampleSet
            the initial SampleSet for the Simulator
        """
        super(PathSampling, self).__init__(storage)
        self.move_scheme = move_scheme
        self.root_mover = move_scheme.move_decision_tree()
#        self.move_scheme.name = "PathSamplingRoot"

        samples = []
        if sample_set is not None:
            for sample in sample_set:
                samples.append(sample.copy_reset())

        self.sample_set = paths.SampleSet(samples)
        self.root = self.sample_set

        initialization_logging(init_log, self, 
                               ['move_scheme', 'sample_set'])
        self.live_visualization = None
        self.visualize_frequency = 1
        self._mover = paths.PathSimulatorMover(self.root_mover, self)

    def run_until(self, n_steps):
        if self.storage is not None:
            if len(self.storage.steps) > 0:
                self.step = len(self.storage.steps)
        n_steps_to_run = n_steps - self.step
        self.run(n_steps_to_run)

    def run(self, n_steps):
        mcstep = None

        cvs = list()
        n_samples = 0

        if self.storage is not None:
            n_samples = len(self.storage.snapshots)
            cvs = list(self.storage.cvs)

        if self.step == 0:
            if self.storage is not None:
                self.storage.save(self.move_scheme)
            self.save_initial()

        for nn in range(n_steps):
            self.step += 1
            logger.info("Beginning MC cycle " + str(self.step))
            refresh=True
            if self.step % self.visualize_frequency == 0:
                # do we visualize this step?
                if self.live_visualization is not None and mcstep is not None:
                    # do we visualize at all?
                    self.live_visualization.draw_ipynb(mcstep)
                    refresh=False

                paths.tools.refresh_output(
                    "Working on Monte Carlo cycle number " + str(self.step)
                    + ".\n", 
                    refresh=refresh
                )

            time_start = time.time() 
            movepath = self._mover.move(self.sample_set, step=self.step)
            samples = movepath.results
            new_sampleset = self.sample_set.apply_samples(samples)
            time_elapsed = time.time() - time_start

            # TODO: we can save this with the MC steps for timing? The bit
            # below works, but is only a temporary hack
            setattr(movepath.details, "timing", time_elapsed)

            mcstep = MCStep(
                simulation=self,
                mccycle=self.step,
                previous=self.sample_set,
                active=new_sampleset,
                change=movepath
            )


            if self.storage is not None:
                for cv in cvs:
                    n_len = len(self.storage.snapshots)
                    cv(self.storage.snapshots[n_samples:n_len])
                    n_samples = n_len

                self.storage.steps.save(mcstep)

            if self.step % self.save_frequency == 0:
                self.sample_set.sanity_check()
                self.sync_storage()

            self.sample_set = new_sampleset

        self.sync_storage()

        if self.live_visualization is not None and mcstep is not None:
            self.live_visualization.draw_ipynb(mcstep)
        paths.tools.refresh_output(
            "DONE! Completed " + str(self.step) + " Monte Carlo cycles.\n",
            refresh=False
        )

class CommittorSimulation(PathSimulator):
    def __init__(self, storage, engine=None, states=None, randomizer=None,
                 initial_snapshots=None, direction=None):
        super(CommittorSimulation, self).__init__(storage)
        self.engine = engine
        paths.EngineMover.default_engine = engine
        self.states = states
        self.randomizer = randomizer
        try:
            initial_snapshots = list(initial_snapshots)
        except TypeError:
            initial_snapshots = [initial_snapshots]
        self.initial_snapshots = initial_snapshots
        self.direction = direction

        all_state_volume = paths.join_volumes(states)

        # we should always start from a single frame not in any state
        self.starting_ensemble = (
            paths.AllOutXEnsemble(all_state_volume) &
            paths.LengthEnsemble(1)
        )
        # shoot forward until we hit a state
        self.forward_ensemble = paths.SequentialEnsemble([
            paths.AllOutXEnsemble(all_state_volume),
            paths.AllInXEnsemble(all_state_volume) & paths.LengthEnsemble(1)
        ])
        # or shoot backward until we hit a state
        self.backward_ensemble = paths.SequentialEnsemble([
            paths.AllInXEnsemble(all_state_volume) & paths.LengthEnsemble(1),
            paths.AllOutXEnsemble(all_state_volume)
        ])

        self.forward_mover = paths.ForwardExtendMover(
            ensemble=self.starting_ensemble,
            target_ensemble=self.forward_ensemble
        )
        self.backward_mover = paths.BackwardExtendMover(
            ensemble=self.starting_ensemble,
            target_ensemble=self.backward_ensemble
        )

        if self.direction is None:
            self.mover = paths.RandomChoiceMover([self.forward_mover,
                                                  self.backward_mover])
        elif self.direction > 0:
            self.mover = self.forward_mover
        elif self.direction < 0:
            self.mover = self.backward_mover

    def run(self, n_per_snapshot, as_chain=False):
        self.step = 0
        for snapshot in self.initial_snapshots:
            start_snap = snapshot
            # do what we need to get the snapshot set up
            for step in range(n_per_snapshot):
                if as_chain:
                    start_snap = self.randomizer(start_snap)
                else:
                    start_snap = self.randomizer(snapshot)

                sample_set = paths.SampleSet([
                    paths.Sample(replica=0,
                                 trajectory=paths.Trajectory([start_snap]),
                                 ensemble=self.starting_ensemble)
                ])
                sample_set.sanity_check()
                new_pmc = self.mover.move(sample_set)
                samples = new_pmc.results
                new_sample_set = sample_set.apply_samples(samples)

                mcstep = MCStep(
                    simulation=self,
                    mccycle = self.step,
                    previous=sample_set,
                    active=new_sample_set,
                    change=new_pmc
                )

                if self.storage is not None:
                    self.storage.steps.save(mcstep)
                    if self.step % self.save_frequency == 0:
                        self.sync_storage()

class DirectSimulation(PathSimulator):
    """
    Direct simulation to calculate rates and fluxes.

    In practice, this is primarily used to calculate the flux if you want to
    do so without saving the entire trajectory. However, it will also save
    the trajectory, if you want it to.

    Parameters
    ----------
    storage : paths.Storage
        file to store the trajectory in. Default is None, meaning that the
        trajectory isn't stored (also faster)
    engine : paths.engine.DynamicsEngine
        the engine for the molecular dynamics
    states : list of paths.Volume
        states to look for transitions between
    flux_pairs : list of 2-tuples of (state, interface)
        fluxes will calculate the flux out of `state` and through
        `interface` for each pair in this list
    initial_snapshot : paths.engines.Snapshot
        initial snapshot for the MD

    Attributes
    ----------
    transitions : dict with keys 2-tuple of paths.Volume, values list of int
        for each pair of states (from_state, to_state) as a key, gives the
        number of frames for each transition from the entry into from_state
        to entry into to_state
    rate_matrix : pd.DataFrame
        calculates the rate matrix, in units of per-frames
    fluxes : dict with keys 2-tuple of paths.Volume, values float
        flux out of state and through interface for each (state, interface)
        key pair
    n_transitions : dict with keys 2-tuple of paths.Volume, values int
        number of transition events for each pair of states
    n_flux_events : dict with keys 2-tuple of paths.Volume, values int
        number of flux events for each (state, interface) pair
    """
    def __init__(self, storage=None, engine=None, states=None,
                 flux_pairs=None, initial_snapshot=None):
        super(DirectSimulation, self).__init__(storage)
        self.engine = engine
        self.states = states
        self.flux_pairs = flux_pairs
        if flux_pairs is None:
            self.flux_pairs = []
        self.initial_snapshot = initial_snapshot
        self.save_every = 1

        # TODO: might set these elsewhere for reloading purposes?
        self.transition_count = []
        self.flux_events = {pair: [] for pair in self.flux_pairs}

    def run(self, n_steps):
        most_recent_state = None
        last_interface_exit = {p : -1 for p in self.flux_pairs}
        last_state_visit = {s : -1 for s in self.states}
        was_in_interface = {p : None for p in self.flux_pairs}
        local_traj = paths.Trajectory([self.initial_snapshot])
        self.engine.current_snapshot = self.initial_snapshot
        for step in range(n_steps):
            frame = self.engine.generate_next_frame()

            # update the most recent state if we're in a state
            state = None # no state at all
            for s in self.states:
                if s(frame):
                    state = s
            if state: 
                last_state_visit[state] = step
                if state is not most_recent_state:
                    # we've made a transition: on the first entrance into
                    # this state, we reset the last_interface_exit
                    state_flux_pairs = [p for p in self.flux_pairs 
                                        if p[0] == state]
                    for p in state_flux_pairs:
                        last_interface_exit[p] = -1
                    # if this isn't the first change of state, we add the
                    # transition
                    if most_recent_state:
                        self.transition_count.append((state, step))
                    most_recent_state = state

            # update whether we've left any interface
            for p in self.flux_pairs:
                state = p[0]
                interface = p[1]
                is_in_interface = interface(frame)
                if not is_in_interface and was_in_interface[p]:
                    if state is most_recent_state:
                        last_exit = last_interface_exit[p]
                        # successful exit
                        if 0 < last_exit < last_state_visit[state]:
                            flux_time_range = (step, last_exit)
                            self.flux_events[p].append(flux_time_range)
                        last_interface_exit[p] = step
                was_in_interface[p] = is_in_interface

            if self.storage is not None:
                local_traj += [frame]

        if self.storage is not None:
            self.storage.save(local_traj)

    @property
    def transitions(self):
        prev_state = None
        prev_time = None
        results = {}
        for (new_state, time) in self.transition_count:
            if prev_state is not None and prev_time is not None:
                lag = time - prev_time
                try:
                    results[(prev_state, new_state)] += [lag]
                except KeyError:
                    results[(prev_state, new_state)] = [lag]
            prev_state = new_state
            prev_time = time
        return results

    @property
    def rate_matrix(self):
        transitions = self.transitions
        rates = {t : 1.0 / np.array(transitions[t]).mean() 
                 for t in transitions}
        rate_matrix = pd.DataFrame(columns=self.states,
                                   index=self.states)
        for t in rates:
            rate_matrix.set_value(t[0], t[1], rates[t])
        return rate_matrix

    @property
    def fluxes(self):
        results = {}
        for p in self.flux_events:
            lags = [t[0] - t[1] for t in self.flux_events[p]]
            results[p] = 1.0 / np.mean(lags)
        return results

        # return {p : 1.0 / np.array(self.flux_events[p]).mean()
                # for p in self.flux_events}

    @property
    def n_transitions(self):
        transitions = self.transitions
        return {t : len(transitions[t]) for t in transitions}

    @property
    def n_flux_events(self):
        return {p : len(self.flux_events[p]) for p in self.flux_events}
