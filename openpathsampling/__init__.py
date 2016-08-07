# start by importing version, because for some weird reason, I sometimes get
# networkx as over-riding the version here (no idea why...)
try:
    # should work if installed through normal means: setup.py-based with
    # pip, conda, easy_install, etc.
    import version
except ImportError:  # pragma: no cover
    import os
    # should work if someone just set the $PYTHONPATH to include OPS
    directory = os.path.dirname(os.path.realpath(__file__))
    prev_dir = os.path.split(directory)[0]
    setupfile = os.path.join(prev_dir, "setup.py")

    if not os.path.exists(setupfile):
        # now we're screwed
        raise ImportError("Unable to identify OPS version. " + 
			  "OPS probably not installed correctly.")

    # continue force-setting version based on `setup.py`
    import imp  # may be Py2 only!
    ops_setup = imp.load_source("ops_setup", setupfile)
    version = imp.new_module("openpathsampling.version")

    version.version = ops_setup.preferences['version']
    version.short_version = ops_setup.preferences['version']
    version.git_version  = ops_setup.get_git_version()
    version.full_version = ops_setup.preferences['version']
    if not ops_setup.preferences['released']:
        version.full_version += ".dev-" + version.git_version[:7]
    isrelease = str(ops_setup.preferences['released'])
        
        
from analysis.move_scheme import (
    MoveScheme, DefaultScheme, LockedMoveScheme, SRTISScheme, OneWayShootingMoveScheme
)

from analysis.tis_analysis import (
    TISTransition, Transition, TPSTransition, FixedLengthTPSTransition
)

from analysis.network import (
    MSTISNetwork, TransitionNetwork, MISTISNetwork, TPSNetwork,
    FixedLengthTPSNetwork
)

from analysis.path_histogram import PathDensityHistogram

from analysis.replica_network import (
    ReplicaNetwork, trace_ensembles_for_replica,
    trace_replicas_for_ensemble, condense_repeats,
    ReplicaNetworkGraph
)

from analysis.shooting_point_analysis import (
    ShootingPointAnalysis, SnapshotByCoordinateDict
)

from analysis.single_trajectory_analysis import (
    SingleTrajectoryAnalysis,
    TrajectorySegmentContainer
)

from bias_function import (
    BiasFunction, BiasLookupFunction, BiasEnsembleTable
)

from collectivevariable import (
    FunctionCV, MDTrajFunctionCV, MSMBFeaturizerCV,
    InVolumeCV, CollectiveVariable, CoordinateGeneratorCV,
    CoordinateFunctionCV, CallableCV, PyEMMAFeaturizerCV,
    GeneratorCV)

from ensemble import (
    Ensemble, EnsembleCombination, EnsembleFactory, EntersXEnsemble,
    EmptyEnsemble, ExitsXEnsemble, FullEnsemble, PartInXEnsemble,
    AllInXEnsemble, AllOutXEnsemble, WrappedEnsemble,
    SuffixTrajectoryEnsemble, PrefixTrajectoryEnsemble,
    PartOutXEnsemble, LengthEnsemble, NegatedEnsemble,
    ReversedTrajectoryEnsemble, SequentialEnsemble, VolumeEnsemble,
    SequentialEnsemble, IntersectionEnsemble, UnionEnsemble,
    SymmetricDifferenceEnsemble, RelativeComplementEnsemble,
    SingleFrameEnsemble, MinusInterfaceEnsemble, TISEnsemble,
    OptionalEnsemble, join_ensembles
)

from high_level.interface_set import (
    InterfaceSet, VolumeInterfaceSet, PeriodicVolumeInterfaceSet
)

from high_level.ms_outer_interface import MSOuterTISInterface

from live_visualization import LiveVisualization

from movechange import (
    EmptyMoveChange, ConditionalSequentialMoveChange,
    MoveChange, PartialAcceptanceSequentialMoveChange,
    RandomChoiceMoveChange, SampleMoveChange,
    SequentialMoveChange, KeepLastSampleMoveChange,
    FilterSamplesMoveChange,
    PathSimulatorMoveChange, AcceptedSampleMoveChange,
    RejectedSampleMoveChange, SubMoveChange,
    FilterByEnsembleMoveChange
)

from pathmover import Details, MoveDetails, SampleDetails

from pathmover import (
    RandomChoiceMover, PathMover, ConditionalSequentialMover,
    PartialAcceptanceSequentialMover, BackwardShootMover, ForwardShootMover,
    BackwardExtendMover, ForwardExtendMover, MinusMover,
    SingleReplicaMinusMover, PathMoverFactory, PathReversalMover,
    ReplicaExchangeMover, EnsembleHopMover, ReplicaIDChangeMover,
    SequentialMover, ConditionalMover,
    PathSimulatorMover, PathReversalSet, NeighborEnsembleReplicaExchange,
    SampleMover, StateSwapMover, FinalSubtrajectorySelectMover, EngineMover,
    FirstSubtrajectorySelectMover, MultipleSetMinusMover,
    OneWayShootingMover, RandomSubtrajectorySelectMover, SubPathMover,
    EnsembleFilterMover, SelectionMover, FirstAllowedMover,
    LastAllowedMover, OneWayExtendMover, SubtrajectorySelectMover,
    IdentityPathMover, RandomAllowedChoiceMover
)

from pathsimulator import (
    PathSimulator, FullBootstrapping, Bootstrapping, PathSampling, MCStep,
    CommittorSimulation, DirectSimulation
)

from sample import Sample, SampleSet

from shooting import ShootingPointSelector, UniformSelector, \
    GaussianBiasSelector, FirstFrameSelector, FinalFrameSelector

from snapshot_modifier import NoModification, RandomVelocities

from storage.storage import Storage, AnalysisStorage

from volume import (
    Volume, VolumeCombination, VolumeFactory, VoronoiVolume,
    EmptyVolume, FullVolume, CVDefinedVolume, PeriodicCVDefinedVolume,
    IntersectionVolume, UnionVolume, SymmetricDifferenceVolume,
    RelativeComplementVolume, join_volumes
)

import numerics

from openpathsampling.engines import Trajectory, BaseSnapshot
import openpathsampling.engines.openmm as openmm
import openpathsampling.engines.toy as toy


def git_HEAD():  # pragma: no cover
    from subprocess import check_output
    import os.path
    git_dir = os.path.dirname(os.path.realpath(__file__))
    return check_output(["git", "-C", git_dir, "rev-parse", "HEAD"])[:-1]
    # chops the newline at the end


