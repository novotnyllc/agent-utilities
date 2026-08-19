"""Robust primitive detection over a mesh dump, and the disproof-gated fit record.

Host-side crux of the mesh-to-parametric pipeline. It takes the hash-bound dump
``mesh_dump`` reads, welds it under a declared tolerance, measures its own noise,
detects analytic primitives in it, tries to *falsify* every one, and emits the
fit record U3 consumes. It needs no Fusion, imports no ``adsk``, and is provable
in full under ``scripts/test.sh`` against synthetic meshes with known analytic
answers. That total offline testability is why the architecture puts the
numerics here, so nothing in this module may acquire a live-session dependency.

Implements ``docs/plans/2026-08-19-007-research-reconstruction-algorithms.md``
sections 2-6 and 10. The mathematics and its citations live there; this file
carries the reasons a reader of the *code* needs.

**Why detection-first rather than crease-threshold region growing.** Thresholding
the dihedral angle at each edge makes a hard, irreversible decision from one
noisy local measurement, so its accuracy is bounded by the noisiest triangle in
the mesh. Per-triangle normal jitter is about ``2.3 sigma/l`` radians (spec 3.1)
-- 13 degrees at the contested 0.05 mm noise on 0.5 mm triangles -- which swamps
any crease threshold worth setting. But that is an *estimator* property, not a
property of the data: trimmed PCA over a neighbourhood of radius ``h`` drops it
to ``2 sigma/(h sqrt(k))`` (spec 4.1), about 1 degree at h = 1.25 mm on the same
mesh. Averaging first is the whole argument. Detection then runs on normals that
are twenty times better than the ones a crease threshold would have used, and
Schnabel/Wahl/Klein's Efficient RANSAC (CGF 26:2, 2007) does the rest.

So refusal moves rather than disappearing. It is no longer "the noise floor
approached a threshold"; it is ``feature-scale-below-noise`` -- the recoverable
feature size, about ten sigma, has risen above the smallest feature the caller
declared they need. That is a statement about information content, and it is
reported as a budget the caller can check before asking.

**Consensus size is not proof.** RANSAC always returns something, and its score
measures agreement with the model it was told to look for. Every accepted fit
therefore also passes three disproof gates -- support span, residual structure by
Moran's I on the mesh graph, and spatially blocked held-out residual -- plus a
nested-kind parsimony F test that refuses a richer primitive that has not earned
its extra parameters. A fit that fails is recorded with the gate that killed it,
never dropped.

**Welding is this module's responsibility and it is fail-closed.** An unwelded
mesh repeats a position under separate node indices, so two triangles that touch
in space share no index; every neighbourhood degenerates to a single triangle and
every edge reads as a boundary. Nothing here *fails* on such a mesh -- the
normals, the dihedral estimator and Moran's I all return confidently wrong
answers, which is the worst failure mode available. The dump reader measures and
reports it (welding needs a tolerance, and a tolerance is a declared threshold);
this module welds under that declared tolerance, reports how many nodes merged,
and refuses ``mesh-not-welded`` if the result still is not connected.

Every threshold is caller-declared with a rationale. The handful of module
constants are structural minima (a least-squares fit needs four points),
published calibration constants with their source named, or float-noise floors,
and each says which where it is defined.

Determinism: each stage draws from its own ``random.Random`` seeded from the dump
hash and the stage name, iteration is over sorted keys or index order, and region
identity is a hash of sorted triangle indices bound to the dump -- never a Fusion
face-group temp id, which is not stable across sessions. The same dump gives a
bit-identical record.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import math
import random
import re
from typing import Any, Callable, Iterable, Mapping, Sequence

from .manifest import ValidationIssue, _in_closed_set, _reject_unknown_fields
from .mesh_dump import MeshDump
from .mesh_fitting import (
    PrimitiveFit,
    Vec3,
    _add,
    _canonical_direction,
    _centroid,
    _covariance,
    _cross,
    _dot,
    _extent,
    _fit_circle_2d,
    _frame,
    _length,
    _raw_fit,
    _residuals,
    _rms,
    _scale,
    _solve,
    _sub,
    _surface_normal,
    _symmetric_eigen,
    _unit,
    fit_primitive,
    parameter_uncertainty,
)


RECORD_VERSION = 1

#: Closed refusal vocabulary. A refusal is a declared outcome with a named
#: reason and a stated alternative -- never an exception the caller guesses at.
REFUSAL_REASONS = {
    "triangle-budget-exceeded",
    "mesh-degenerate",
    "mesh-not-welded",
    "feature-scale-below-noise",
    "segmentation-coverage-insufficient",
    "fit-record-stage-failed",
}

#: Flags: measured facts that qualify every verdict downstream but do not stop
#: the run. ``noise-model-inconsistent`` says the two independent noise
#: estimators disagreed by more than 2x, so the iid assumption every statistical
#: gate is calibrated against does not hold and its verdicts are approximate.
RECORD_FLAGS = {"noise-model-inconsistent", "normals-unoriented", "angular-resolution-degraded"}

DETECTED_KINDS = ("plane", "cylinder", "sphere", "cone", "torus")

#: Stages in order. Each appends its own name to ``checked`` only after it has
#: run and returned no refusal (R12), so the record can never claim a check that
#: did not happen. The enforcing test stubs one of these to raise.
STAGES = (
    "triangle-budget",
    "weld",
    "topology",
    "noise-scale",
    "feature-scale",
    "normals",
    "curvature",
    "detection",
    "segmentation",
    "disproof",
    "face-group-agreement",
    "coverage",
)

_SHA256_RE = re.compile(r"\A[0-9a-f]{64}\Z")

# Structural minima, not tuning knobs: a least-squares primitive fit needs four
# points and its minimal sets need up to four oriented ones.
_MIN_REGION_TRIANGLES = 4
_MIN_REGION_POINTS = 4

# Published calibration constants, with their derivations in the spec. They are
# properties of the estimators, not decisions about this part: changing one
# would mean the estimator no longer estimates what it claims to.
_SIGMA_A_NEIGHBOURS = 16          # spec 3.1: small on purpose, to limit curvature bias
# Spec 3.1 takes the median over sampled neighbourhoods, which is robust as long
# as fewer than half of them straddle a crease. On a mechanical part that
# assumption is weaker than it looks: a box has six faces and twelve edges, and
# most of its nodes sit within two rings of an edge, so the median measures the
# box rather than the noise. Contamination here is strictly *one-sided* --
# crossing a crease can only inflate lambda0, never deflate it -- which is what
# licenses a low quantile as a principled estimator rather than a fudge. The
# tenth percentile tolerates ninety percent contamination; the price is a
# calibration constant, since a low quantile of a chi-like statistic is biased
# low. For a plane fitted to 16 points of iid Gaussian noise the tenth
# percentile of sqrt(lambda0 * k/(k-3)) sits at 0.735 sigma. Both numbers are
# re-derived by Monte Carlo in the test suite rather than trusted here.
_SIGMA_A_QUANTILE = 0.10
_SIGMA_A_QUANTILE_CALIBRATION = 0.735
# The same statistic with a *quadric* in place of the plane. A plane residual on
# a curved patch contains the sagitta as well as the noise -- spec 3.1 argues the
# contamination is negligible at scan densities, and it is, but it is not
# negligible on a coarsely tessellated CAD export, where a 64-gon cylinder of
# radius 8 makes a plane estimator read 0.13 mm of "noise" on a mesh with none.
# A quadric absorbs curvature, so this measures the *noise* and the difference
# between the two measures the *discretization*. Both are wanted, for different
# jobs: noise sets the recoverable feature size, and the surface scale -- noise
# and discretization together -- sets the consensus band, because otherwise no
# facet of a coarse cylinder is ever an inlier of the cylinder it came from.
# Calibration for six parameters over 16 points: 0.698 sigma at the tenth
# percentile, re-derived by Monte Carlo in the test suite.
_SIGMA_QUADRIC_PARAMETERS = 6
_SIGMA_QUADRIC_CALIBRATION = 0.698
_DIHEDRAL_CALIBRATION = 2.2       # spec 3.2: theta_med ~ 2.2 sigma / l
_H_MIN_EDGE_MULTIPLE = 2.5        # spec 4.2: below this k < 10 and the variance law fails
_THETA_TARGET_FRACTION = 5.0      # spec 4.2: theta_tgt = alpha / 5
_TRIM_SIGMAS = 2.5                # spec 4.1: trimming band for the second PCA pass
_EDGE_ADJACENT_SIGMAS = 2.0       # spec 4.1: residual above this means the patch straddles a crease
_FEATURE_SIGMA_FLOOR = 10.0       # spec 12.1: features below ~10 sigma are not separable
_CURVATURE_NOISE_COEFFICIENT = 6.0  # spec 4.3: sigma_kappa ~ 6 sigma / (h^2 sqrt(k))
_MORAN_MIN_POINTS = 12            # below this the variance formula is not meaningful

# Float-noise floors and degeneracy guards. No verdict turns on their values;
# they exist so a band or a determinant comparison stays meaningful on an
# exactly-planar synthetic mesh.
_BAND_FLOOR_RATIO = 1e-9
_DEGENERATE_SINE = 1e-2           # spec 5.1: parallel normals, axis unobservable
_DEGENERATE_DENOMINATOR = 1e-4    # spec 5.1: sphere centre unobservable
_DEGENERATE_DETERMINANT = 1e-12
# The torus axis construction's structural conditions. Neither is a tuning knob:
# one bounds an alternating solve, the other asks whether a null direction is
# unique at all.
_TORUS_AXIS_PASSES = 6
# The axis is the null direction of the samples' moment scatter. If the second
# eigenvalue is not clearly larger, that direction is not unique and the sample
# is describing a cylinder or a sphere, not a torus.
_TORUS_AXIS_UNIQUENESS = 4.0


# --------------------------------------------------------------------------
# declared thresholds
# --------------------------------------------------------------------------


def _positive(value: Any) -> bool:
    return value > 0.0


def _non_negative(value: Any) -> bool:
    return value >= 0.0


def _probability(value: Any) -> bool:
    return 0.0 < value < 1.0


def _unit_fraction(value: Any) -> bool:
    return 0.0 < value <= 1.0


#: name -> (json type, predicate, what the rationale must be about).
#: Every one is declared by the caller. None has a default here, and validation
#: rejects a threshold whose rationale is missing or empty -- a number nobody
#: justified is a module constant wearing a spec's clothes.
THRESHOLDS: dict[str, tuple[str, Callable[[Any], bool], str]] = {
    # transport and budget
    "max_triangles": (
        "int",
        lambda v: v >= _MIN_REGION_TRIANGLES,
        "what the algorithm can honestly use, not how long pure Python takes",
    ),
    "weld_tolerance": (
        "float",
        _non_negative,
        "how far apart two nodes may sit and still be the same point on this scanner",
    ),
    "min_feature_size": (
        "float",
        _positive,
        "the smallest feature this part actually has that the caller needs recovered",
    ),
    # noise, normals, curvature
    "epsilon_sigmas": (
        "float",
        _positive,
        "how many measured sigmas wide the RANSAC consensus band is",
    ),
    "normal_alpha_deg": (
        "float",
        lambda v: 0.0 < v < 90.0,
        "how far an estimated normal may sit from the primitive's own normal",
    ),
    "curvature_dead_zone_sigmas": (
        "float",
        _positive,
        "how many estimator sigmas of curvature read as zero when ranking candidate kinds",
    ),
    # RANSAC
    "ransac_eta_extract": (
        "float",
        _probability,
        "the miss probability at which the best candidate is good enough to extract",
    ),
    "ransac_eta_stop": (
        "float",
        _probability,
        "the miss probability at which no interesting shape is likely left undiscovered",
    ),
    "max_candidate_rounds": (
        "int",
        lambda v: v >= 1,
        "the hard ceiling on sampling rounds, so the search always terminates",
    ),
    "score_sample_size": ("int", lambda v: v >= 16, "how many points a candidate is lazily scored against"),
    "refine_iterations": ("int", lambda v: 1 <= v <= 64, "how many fit/inlier/refit rounds sharpen the estimate"),
    "max_primitives": ("int", lambda v: 1 <= v <= 4096, "the ceiling on detected features"),
    "min_inlier_area_fraction": (
        "float",
        _unit_fraction,
        "the smallest share of the part that is worth calling a feature",
    ),
    "rng_seed": ("int", _non_negative, "why this seed, and that reruns must reproduce it"),
    # segmentation (Potts ICM)
    "icm_sweeps": ("int", lambda v: 1 <= v <= 64, "how many relabelling sweeps before the labelling is called settled"),
    "icm_smoothness": ("float", _non_negative, "how much a label boundary costs, in units of one typical edge"),
    "icm_normal_weight": ("float", _non_negative, "how much normal disagreement counts against distance agreement"),
    "icm_unclaimed_chi2": (
        "float",
        _positive,
        "how badly a triangle must fit every primitive before unclaimed is the honest label",
    ),
    # exact-fit gates (passed through to mesh_fitting)
    "max_relative_residual": ("float", _positive, "the residual gate, relative to sampled extent"),
    "max_radius_ratio": ("float", _positive, "how far a fitted radius may exceed the sampled extent"),
    "bounds_margin_ratio": ("float", _non_negative, "how far a fitted anchor may escape the part"),
    "min_taper_ratio": ("float", _positive, "the taper below which a cone is really a cylinder"),
    "min_torus_major_ratio": (
        "float",
        lambda v: v > 1.0,
        "how much larger a torus's major radius must be than its tube before it is a torus",
    ),
    # disproof gates
    "min_angular_span_deg": (
        "float",
        lambda v: 0.0 < v <= 360.0,
        "how much of a circular section must be seen before its radius is determined",
    ),
    "min_axial_span_ratio": (
        "float",
        _non_negative,
        "how long a cylinder or cone must be, in radii, before its axis is determined",
    ),
    "min_sphere_occupancy": ("float", _unit_fraction, "how much of a sphere must be seen before it is a sphere"),
    "min_plane_aspect": (
        "float",
        _unit_fraction,
        "how far from a sliver a plane's footprint must be before its normal is determined",
    ),
    "max_radius_rel_sigma": (
        "float",
        _positive,
        "how uncertain a fitted radius may be, relative to itself, for downstream use",
    ),
    "max_axis_sigma_deg": (
        "float",
        _positive,
        "how uncertain a fitted axis direction may be before relationships built on it are fiction",
    ),
    "moran_z_max": (
        "float",
        _positive,
        "how much spatial structure in the residuals is still consistent with correlated noise",
    ),
    "moran_baseline_slack": (
        "float",
        _non_negative,
        "how far above the part's own best plane a feature's residual structure may sit",
    ),
    "directional_bin_sigmas": (
        "float",
        _positive,
        "how many standard errors a per-bin mean residual may reach before it is structure",
    ),
    "heldout_ratio_max": (
        "float",
        lambda v: v >= 1.0,
        "how much worse spatially blocked held-out residuals may be before the fit is overfitted",
    ),
    "parsimony_alpha": (
        "float",
        _probability,
        "the significance a richer primitive kind must reach to earn its extra parameters",
    ),
    "min_covered_area_fraction": (
        "float",
        lambda v: 0.0 <= v <= 1.0,
        "how much of the part must be explained before the record is worth anything",
    ),
}

#: Passed straight through to ``mesh_fitting.fit_primitive``.
_FIT_GATE_NAMES = (
    "max_relative_residual",
    "max_radius_ratio",
    "bounds_margin_ratio",
    "min_taper_ratio",
    "min_torus_major_ratio",
)

#: Besl and Jain (PAMI 1988): the (sgn H, sgn K) pair classifies the local
#: surface type. Used to *rank* which minimal-set constructions are worth trying
#: for a given seed, and to say what an unclaimed region actually looks like.
#: Never a veto: the signature is per-seed, the dead zones already encode how
#: noisy it is, and an ambiguous signature prunes nothing.
CURVATURE_CLASSES = {"flat", "ridge-valley", "peak-pit", "saddle", "ambiguous"}

#: Every list contains every kind. The signature sets the *order* -- the kinds it
#: predicts are tried first -- and it never removes one. Pruning was tempting,
#: because it is where the speed is, and it is wrong: the classifier collapses
#: toward "flat" exactly when the mesh is coarse or noisy, and a pruning
#: classifier would then offer RANSAC nothing but planes on precisely the parts
#: that need a cylinder. Bias, not veto, is what the noise in the signature
#: licenses. What the ranking still buys is the diagnostic: an unclaimed region
#: reports its dominant signature, so the record can say "saddle, and no
#: supported primitive fits a saddle" rather than "nothing fit".
_RANKED_KINDS: dict[str, tuple[str, ...]] = {
    "flat": ("plane", "cylinder", "cone", "sphere", "torus"),
    "ridge-valley": ("cylinder", "cone", "torus", "plane", "sphere"),
    "peak-pit": ("sphere", "torus", "cone", "cylinder", "plane"),
    "saddle": ("torus", "cone", "cylinder", "sphere", "plane"),
    "ambiguous": DETECTED_KINDS,
}

#: Minimal-set size per kind (spec 5.1), which is also what the (5.1) sampling
#: probability bound is a function of.
_MINIMAL_SET_SIZE = {"plane": 3, "sphere": 2, "cylinder": 2, "cone": 3, "torus": 4}

#: Free parameters per kind, for the parsimony F test (spec 10.4).
_FREE_PARAMETERS = {"plane": 3, "sphere": 4, "cylinder": 5, "cone": 6, "torus": 7}

#: Which kinds nest inside which, for the parsimony test: cylinder is a cone
#: with zero taper and a torus with infinite major radius; a sphere is a torus
#: with zero major radius.
_NESTED_IN = {"cone": ("cylinder",), "torus": ("cylinder", "sphere")}

#: The same nesting read the other way: what a rejected kind may be promoted to.
#: A fillet band is the case this exists for -- it is locally cylinder-shaped,
#: RANSAC proposes a cylinder, and the residual-structure gate correctly refuses
#: it. Refusing and stopping there would send every fillet to unreconstructed
#: area, which is the thing a torus was added to prevent. So a refused kind gets
#: one chance at the richer kind that contains it, on the same points, through
#: the same gates -- and the parsimony F test still has to license the extra
#: parameters, so this can promote but never smuggle.
_RICHER_KINDS = {"cylinder": ("torus", "cone"), "sphere": ("torus",)}


class SegmentationSpecError(ValueError):
    """A malformed detection spec or dump, with every issue named."""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__("\n".join(str(issue) for issue in self.issues))


@dataclass(frozen=True, slots=True)
class DetectionSpec:
    """Every threshold this run used, each with the rationale that justified it."""

    thresholds: dict[str, Any]
    rationales: dict[str, str]

    def value(self, name: str) -> Any:
        return self.thresholds[name]

    def to_dict(self) -> dict[str, Any]:
        return {
            name: {"value": self.thresholds[name], "rationale": self.rationales[name]}
            for name in sorted(self.thresholds)
        }

    def fit_gates(self) -> dict[str, float]:
        return {name: float(self.thresholds[name]) for name in _FIT_GATE_NAMES}


def load_spec(raw: Any) -> DetectionSpec:
    """Validate a detection spec: closed vocabulary, and a rationale on every threshold."""
    issues: list[ValidationIssue] = []
    if not isinstance(raw, Mapping):
        raise SegmentationSpecError(
            [ValidationIssue("detection-spec-must-be-object", "spec", "A detection spec must be an object.")]
        )
    _reject_unknown_fields(issues, dict(raw), set(THRESHOLDS), "spec")

    values: dict[str, Any] = {}
    rationales: dict[str, str] = {}
    for name in sorted(THRESHOLDS):
        kind, predicate, about = THRESHOLDS[name]
        entry = raw.get(name)
        if entry is None:
            issues.append(
                ValidationIssue(
                    "detection-threshold-missing",
                    f"spec.{name}",
                    f"{name} must be declared as an object with value and rationale; "
                    f"the rationale must say {about}.",
                )
            )
            continue
        if not isinstance(entry, Mapping):
            issues.append(
                ValidationIssue(
                    "detection-threshold-must-be-object",
                    f"spec.{name}",
                    f"{name} must be an object with value and rationale, not a bare number.",
                )
            )
            continue
        _reject_unknown_fields(issues, dict(entry), {"value", "rationale"}, f"spec.{name}")
        value = entry.get("value")
        ok = not isinstance(value, bool)
        if ok and kind == "int":
            ok = isinstance(value, int)
        elif ok:
            ok = isinstance(value, (int, float)) and math.isfinite(value)
        if ok:
            ok = bool(predicate(value))
        if not ok:
            issues.append(
                ValidationIssue(
                    "detection-threshold-invalid",
                    f"spec.{name}.value",
                    f"{name}.value must be a valid {kind} for this threshold.",
                )
            )
        rationale = entry.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            # The sibling requirement a reviewer already flagged as missing
            # elsewhere in this skill: a threshold without a stated reason is not
            # a declared threshold, it is a magic number with a home.
            issues.append(
                ValidationIssue(
                    "detection-threshold-rationale-required",
                    f"spec.{name}.rationale",
                    f"{name} needs a non-empty rationale saying {about}.",
                )
            )
            continue
        if ok:
            values[name] = value if kind == "int" else float(value)
            rationales[name] = rationale.strip()

    if issues:
        raise SegmentationSpecError(issues)
    return DetectionSpec(thresholds=values, rationales=rationales)


# --------------------------------------------------------------------------
# welding: the mesh this module is allowed to reason about
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WeldedMesh:
    """A welded working mesh, bound to the dump digest it came from.

    ``node_sources`` and ``dump_triangles`` map every welded index back to the
    dump it came from. Downstream needs the *dump's* indices, not this module's:
    the dump is what is hash-bound, and a consumer that sections the mesh to
    build a profile has to address the same bytes the fit was derived from.
    """

    dump_sha256: str
    units: str
    vertices: tuple[Vec3, ...]
    triangles: tuple[tuple[int, int, int], ...]
    face_groups: tuple[int, ...] | None
    node_sources: tuple[tuple[int, ...], ...]
    dump_triangles: tuple[int, ...]
    weld: dict[str, Any]


def weld_dump(dump: MeshDump, tolerance: float) -> WeldedMesh:
    """Merge nodes within ``tolerance`` into one point, and report how many merged.

    Quantized bucketing on a grid of side ``tolerance``, checking the 27
    neighbouring buckets so two points either side of a bucket boundary still
    weld. That is O(N) and deterministic; it is not a true metric clustering, so
    a chain of points each within tolerance of the next can merge transitively.
    ``ponytail:`` union-find over a radius query would be exact; the cost is a
    spatial index pass, and the difference only shows up on point clouds far
    denser than the tolerance, which is a scan that should have been decimated.

    A tolerance of zero welds exact duplicates only, which is what a mesh
    exported from a solid modeller needs and what a scanner mesh will not have.
    """
    count = dump.vertex_count
    raw = [
        (dump.vertices_mm[3 * i], dump.vertices_mm[3 * i + 1], dump.vertices_mm[3 * i + 2])
        for i in range(count)
    ]
    remap = [0] * count
    representatives: list[Vec3] = []
    if tolerance <= 0.0:
        exact: dict[Vec3, int] = {}
        for index, point in enumerate(raw):
            target = exact.get(point)
            if target is None:
                target = len(representatives)
                exact[point] = target
                representatives.append(point)
            remap[index] = target
    else:
        buckets: dict[tuple[int, int, int], list[int]] = {}
        for index, point in enumerate(raw):
            key = tuple(int(math.floor(c / tolerance)) for c in point)
            found = -1
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for other in buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                            if _length(_sub(point, representatives[other])) <= tolerance:
                                found = other
                                break
                        if found >= 0:
                            break
                    if found >= 0:
                        break
                if found >= 0:
                    break
            if found < 0:
                found = len(representatives)
                representatives.append(point)
                buckets.setdefault(key, []).append(found)  # type: ignore[arg-type]
            remap[index] = found

    triangles: list[tuple[int, int, int]] = []
    collapsed = 0
    kept_original: list[int] = []
    for index in range(dump.triangle_count):
        a, b, c = (
            remap[dump.triangles[3 * index]],
            remap[dump.triangles[3 * index + 1]],
            remap[dump.triangles[3 * index + 2]],
        )
        if a == b or b == c or a == c:
            # Welding collapsed this triangle to a sliver or a point. It carries
            # no surface and is dropped, counted, and reported.
            collapsed += 1
            continue
        triangles.append((a, b, c))
        kept_original.append(index)

    groups = (
        tuple(dump.face_group_ids[i] for i in kept_original)
        if dump.face_group_ids is not None
        else None
    )
    sources: list[list[int]] = [[] for _ in representatives]
    for original, target in enumerate(remap):
        sources[target].append(original)
    return WeldedMesh(
        dump_sha256=dump.sha256,
        units="mm",
        vertices=tuple(representatives),
        triangles=tuple(triangles),
        face_groups=groups,
        node_sources=tuple(tuple(s) for s in sources),
        dump_triangles=tuple(kept_original),
        weld={
            "tolerance": tolerance,
            "node_count_before": count,
            "node_count_after": len(representatives),
            "nodes_merged": count - len(representatives),
            "triangles_before": dump.triangle_count,
            "triangles_after": len(triangles),
            "triangles_collapsed": collapsed,
        },
    )


# --------------------------------------------------------------------------
# topology and the uniform grid
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _Topology:
    """Everything the estimators read, computed once."""

    tri_normals: list[Vec3]
    areas: list[float]
    centroids: list[Vec3]
    tri_neighbours: list[list[int]]
    point_neighbours: list[list[int]]
    point_weights: list[float]
    edges: dict[tuple[int, int], list[int]]
    valid: list[int]
    degenerate: list[int]
    boundary_edges: int
    non_manifold_edges: int
    interior_edges: int
    total_area: float
    extent: float
    median_edge: float


def _build_topology(mesh: WeldedMesh) -> _Topology:
    verts = mesh.vertices
    tri_normals: list[Vec3] = []
    areas: list[float] = []
    centroids: list[Vec3] = []
    valid: list[int] = []
    degenerate: list[int] = []
    for index, (a, b, c) in enumerate(mesh.triangles):
        pa, pb, pc = verts[a], verts[b], verts[c]
        raw = _cross(_sub(pb, pa), _sub(pc, pa))
        area = 0.5 * _length(raw)
        unit = _unit(raw)
        centroids.append(_scale(_add(_add(pa, pb), pc), 1.0 / 3.0))
        areas.append(area)
        if unit is None or area <= 0.0:
            # A zero-area triangle has no normal. Counted and excluded, never
            # given a fabricated one.
            tri_normals.append((0.0, 0.0, 1.0))
            degenerate.append(index)
            continue
        tri_normals.append(unit)
        valid.append(index)

    edges: dict[tuple[int, int], list[int]] = {}
    for index in valid:
        a, b, c = mesh.triangles[index]
        for i, j in ((a, b), (b, c), (c, a)):
            edges.setdefault((i, j) if i < j else (j, i), []).append(index)

    tri_neighbours: list[list[int]] = [[] for _ in mesh.triangles]
    point_sets: list[set[int]] = [set() for _ in verts]
    interior = boundary = non_manifold = 0
    for (i, j), incident in edges.items():
        point_sets[i].add(j)
        point_sets[j].add(i)
        if len(incident) == 2:
            interior += 1
            tri_neighbours[incident[0]].append(incident[1])
            tri_neighbours[incident[1]].append(incident[0])
        elif len(incident) == 1:
            boundary += 1
        else:
            non_manifold += 1

    point_weights = [0.0] * len(verts)
    for index in valid:
        share = areas[index] / 3.0
        for vertex in mesh.triangles[index]:
            point_weights[vertex] += share

    lengths = [_length(_sub(verts[j], verts[i])) for (i, j) in edges]
    return _Topology(
        tri_normals=tri_normals,
        areas=areas,
        centroids=centroids,
        tri_neighbours=tri_neighbours,
        point_neighbours=[sorted(s) for s in point_sets],
        point_weights=point_weights,
        edges=edges,
        valid=valid,
        degenerate=degenerate,
        boundary_edges=boundary,
        non_manifold_edges=non_manifold,
        interior_edges=interior,
        total_area=sum(areas[i] for i in valid),
        extent=_extent(verts) if verts else 0.0,
        median_edge=_median(lengths) if lengths else 0.0,
    )


class _Grid:
    """Uniform grid over the point set: fixed-radius queries and localized sampling.

    Spec 11.1 chooses a grid over a kd-tree because the queries here are all
    fixed-radius at a single scale and a grid is O(1) per query with no tree to
    build. Localized sampling wants a *hierarchy*, and one grid supplies it: a
    cell at level L is the base cell key right-shifted by L, so L levels cost one
    dict each and no octree.
    """

    def __init__(self, points: Sequence[Vec3], indices: Sequence[int], cell: float) -> None:
        self.cell = max(cell, 1e-12)
        self.keys: dict[int, tuple[int, int, int]] = {}
        self.base: dict[tuple[int, int, int], list[int]] = {}
        for index in indices:
            p = points[index]
            key = (
                int(math.floor(p[0] / self.cell)),
                int(math.floor(p[1] / self.cell)),
                int(math.floor(p[2] / self.cell)),
            )
            self.keys[index] = key
            self.base.setdefault(key, []).append(index)
        self.levels: list[dict[tuple[int, int, int], list[int]]] = [self.base]

    def build_levels(self, count: int) -> None:
        while len(self.levels) < max(1, count):
            level = len(self.levels)
            merged: dict[tuple[int, int, int], list[int]] = {}
            for key, members in self.levels[0].items():
                merged.setdefault((key[0] >> level, key[1] >> level, key[2] >> level), []).extend(members)
            for members in merged.values():
                members.sort()
            self.levels.append(merged)

    def near(self, points: Sequence[Vec3], centre: Vec3, radius: float) -> list[int]:
        span = int(math.ceil(radius / self.cell))
        base = (
            int(math.floor(centre[0] / self.cell)),
            int(math.floor(centre[1] / self.cell)),
            int(math.floor(centre[2] / self.cell)),
        )
        out: list[int] = []
        for dx in range(-span, span + 1):
            for dy in range(-span, span + 1):
                for dz in range(-span, span + 1):
                    for index in self.base.get((base[0] + dx, base[1] + dy, base[2] + dz), ()):
                        if _length(_sub(points[index], centre)) <= radius:
                            out.append(index)
        out.sort()
        return out

    def cell_members(self, index: int, level: int) -> list[int]:
        key = self.keys[index]
        return self.levels[level].get((key[0] >> level, key[1] >> level, key[2] >> level), [])


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])


def _stage_rng(dump_sha256: str, stage: str) -> random.Random:
    """Per-stage seeding, so stages cannot perturb each other's streams (spec 2.3)."""
    digest = hashlib.sha256(f"{dump_sha256}:{stage}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


# --------------------------------------------------------------------------
# noise scale, normals, curvature
# --------------------------------------------------------------------------


def _quantile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]


def _quadric_residual(patch: Sequence[Vec3]) -> float | None:
    """RMS residual of the 16-point patch about its own local quadric.

    Six parameters absorb the surface's curvature, so what is left is the noise
    -- unlike a plane residual, which on a curved patch is dominated by the
    sagitta at any tessellation coarse enough for it to matter.
    """
    centre = _centroid(patch)
    _values, vectors = _symmetric_eigen(_covariance(patch, centre))
    normal = vectors[0]
    u, v = _frame(normal)
    rows = [[0.0] * 6 for _ in range(6)]
    rhs = [0.0] * 6
    local: list[tuple[float, float, float]] = []
    for p in patch:
        w = _sub(p, centre)
        x, y, z = _dot(w, u), _dot(w, v), _dot(w, normal)
        local.append((x, y, z))
        basis = (x * x, x * y, y * y, x, y, 1.0)
        for i in range(6):
            rhs[i] += basis[i] * z
            for j in range(6):
                rows[i][j] += basis[i] * basis[j]
    solution = _solve(rows, rhs)
    if solution is None:
        return None
    a, b, c, d, e, f = solution
    residuals = [
        z - (a * x * x + b * x * y + c * y * y + d * x + e * y + f) for x, y, z in local
    ]
    dof = len(patch) - _SIGMA_QUADRIC_PARAMETERS
    if dof <= 0:
        return None
    return math.sqrt(sum(r * r for r in residuals) / dof)


def _local_scale_estimates(
    mesh: WeldedMesh, topo: _Topology, live: Sequence[int]
) -> tuple[float, float]:
    """Estimator A (spec 3.1), run twice: about a plane and about a quadric.

    Contamination of these statistics is strictly *one-sided* -- crossing a
    crease or a curved surface can only inflate the residual, never deflate it --
    which is what licenses the tenth percentile as a principled robust estimator
    rather than a fudge, and it is what makes the pair separable: the plane
    number is noise plus discretization, the quadric number is noise alone.

    Returns ``(surface_scale, noise)``.
    """
    # Sixteen points at mesh density sit within about 2.1 median edges; query at
    # three, from a grid whose cell matches, so the scan is 27 cells not 125.
    radius = max(3.0 * topo.median_edge, 1e-12)
    grid = _Grid(mesh.vertices, live, radius)
    step = max(1, len(live) // 2000)
    plane_estimates: list[float] = []
    quadric_estimates: list[float] = []
    for offset in range(0, len(live), step):
        index = live[offset]
        centre_point = mesh.vertices[index]
        near = grid.near(mesh.vertices, centre_point, radius)
        if len(near) < _SIGMA_A_NEIGHBOURS:
            continue
        near.sort(key=lambda i: (_length(_sub(mesh.vertices[i], centre_point)), i))
        patch = [mesh.vertices[i] for i in near[:_SIGMA_A_NEIGHBOURS]]
        values, _vectors = _symmetric_eigen(_covariance(patch, _centroid(patch)))
        plane_estimates.append(
            math.sqrt(max(0.0, values[0]) * _SIGMA_A_NEIGHBOURS / (_SIGMA_A_NEIGHBOURS - 3))
        )
        quadric = _quadric_residual(patch)
        if quadric is not None:
            quadric_estimates.append(quadric)
    if not plane_estimates:
        return 0.0, 0.0
    surface = _quantile(plane_estimates, _SIGMA_A_QUANTILE) / _SIGMA_A_QUANTILE_CALIBRATION
    noise = (
        _quantile(quadric_estimates, _SIGMA_A_QUANTILE) / _SIGMA_QUADRIC_CALIBRATION
        if quadric_estimates
        else surface
    )
    return surface, min(noise, surface)


def _sigma_dihedral(topo: _Topology) -> float:
    """Estimator B (spec 3.2): the median interior-edge dihedral, calibrated.

    Real creases are a small minority of interior edges on a mechanical part, so
    the median sees only the noise. The 2.2 is the derived calibration constant,
    not a tuning knob.
    """
    angles = _dihedral_degrees(topo)
    if not angles or topo.median_edge <= 0.0:
        return 0.0
    return math.radians(_median(angles)) * topo.median_edge / _DIHEDRAL_CALIBRATION


def _dihedral_degrees(topo: _Topology) -> list[float]:
    out: list[float] = []
    for incident in topo.edges.values():
        if len(incident) != 2:
            continue
        a, b = incident
        out.append(
            math.degrees(math.acos(max(-1.0, min(1.0, _dot(topo.tri_normals[a], topo.tri_normals[b])))))
        )
    return out


def _neighbourhood_radius(sigma: float, spec: DetectionSpec, topo: _Topology) -> dict[str, Any]:
    """Spec 4.2: size h so normal noise hits a target, then clamp and report the truth.

    sigma_theta falls as 1/h^2, so the right h is derived rather than guessed.
    The two clamps say what h may not do: below 2.5 median edges the variance law
    itself is invalid, and above half the smallest declared feature a normal
    describes neither side of that feature. When they conflict, the feature clamp
    wins, the achieved angular noise is recomputed, and the normal-agreement
    half-angle widens to match -- degradation stated in numbers rather than a
    refusal.
    """
    alpha = math.radians(float(spec.value("normal_alpha_deg")))
    feature = float(spec.value("min_feature_size"))
    edge = topo.median_edge
    density = 2.0 / (math.sqrt(3.0) * edge * edge) if edge > 0.0 else 0.0
    target = alpha / _THETA_TARGET_FRACTION
    floor = _H_MIN_EDGE_MULTIPLE * edge
    ceiling = feature / 2.0

    if sigma <= 0.0 or density <= 0.0:
        ideal = floor
    else:
        ideal = math.sqrt(2.0 * sigma / (math.sqrt(math.pi * density) * target))
    h = max(ideal, floor)
    clamped_by_feature = h > ceiling and ceiling > 0.0
    if clamped_by_feature:
        h = max(ceiling, 1e-12)
    k = max(1.0, density * math.pi * h * h)
    achieved = (2.0 * sigma / (h * math.sqrt(k))) if h > 0.0 else math.inf
    if achieved > target:
        # Widen the check rather than reject every point for a noise level the
        # neighbourhood was never allowed to average away.
        alpha = max(alpha, _THETA_TARGET_FRACTION * achieved)
    return {
        "h": h,
        "k_estimate": k,
        "sigma_theta_rad": achieved,
        "sigma_theta_deg": math.degrees(achieved),
        "alpha_deg": math.degrees(alpha),
        "clamped_by_feature_size": clamped_by_feature,
        "clamped_by_edge_length": h <= floor + 1e-15,
    }


@dataclass(slots=True)
class _PointFrame:
    normals: list[Vec3 | None]
    edge_adjacent: list[bool]
    curvature_class: list[str]
    kappa: list[tuple[float, float]]
    sigma_kappa: float


def _estimate_normals(
    mesh: WeldedMesh, topo: _Topology, grid: _Grid, live: Sequence[int], h: float, scale: float
) -> tuple[list[Vec3 | None], list[bool], list[list[int]]]:
    """Trimmed PCA (spec 4.1): fit, discard the far tail, refit once. Two passes.

    The trim is what makes this robust rather than merely smooth: a neighbourhood
    that reaches across a crease has a minority of points on the far surface, and
    one trimming pass removes them. A neighbourhood whose residual is *still*
    above 2 sigma after trimming genuinely straddles a crease, and its normal is
    flagged unreliable rather than used -- such points keep contributing distance
    evidence but are exempted from the normal-agreement check, because otherwise
    every point near a crease fails it and boundary support is eaten
    systematically.
    """
    normals: list[Vec3 | None] = [None] * len(mesh.vertices)
    edge_adjacent = [False] * len(mesh.vertices)
    patches: list[list[int]] = [[] for _ in mesh.vertices]
    # Trimmed against the *surface* scale, not the noise alone: on a coarsely
    # tessellated curved patch the sagitta is a real deviation from the local
    # plane, and trimming it away would discard the surface rather than the
    # outliers.
    trim = _TRIM_SIGMAS * scale
    for index in live:
        centre_point = mesh.vertices[index]
        near = grid.near(mesh.vertices, centre_point, h)
        if len(near) < _MIN_REGION_POINTS:
            near = sorted({index, *topo.point_neighbours[index]})
        if len(near) < _MIN_REGION_POINTS:
            continue
        patch = [mesh.vertices[i] for i in near]
        centre = _centroid(patch)
        _values, vectors = _symmetric_eigen(_covariance(patch, centre))
        normal = vectors[0]
        if trim > 0.0:
            kept = [i for i in near if abs(_dot(normal, _sub(mesh.vertices[i], centre))) <= trim]
            if len(kept) >= _MIN_REGION_POINTS:
                near = kept
                patch = [mesh.vertices[i] for i in near]
                centre = _centroid(patch)
                _values, vectors = _symmetric_eigen(_covariance(patch, centre))
                normal = vectors[0]
        residual = _rms(_dot(normal, _sub(p, centre)) for p in patch)
        # Orient by the incident triangles' winding, which is the only orientation
        # information a mesh carries; on an unoriented mesh this is arbitrary and
        # every consumer sees it only through |cos|.
        vote = (0.0, 0.0, 0.0)
        for tri in _incident_triangles(mesh, topo, index):
            vote = _add(vote, _scale(topo.tri_normals[tri], topo.areas[tri]))
        if _dot(vote, normal) < 0.0:
            normal = _scale(normal, -1.0)
        normals[index] = normal
        edge_adjacent[index] = residual > _EDGE_ADJACENT_SIGMAS * scale and scale > 0.0
        patches[index] = near
    return normals, edge_adjacent, patches


def _incident_triangles(mesh: WeldedMesh, topo: _Topology, vertex: int) -> list[int]:
    out: list[int] = []
    for other in topo.point_neighbours[vertex]:
        key = (vertex, other) if vertex < other else (other, vertex)
        out.extend(topo.edges.get(key, ()))
    return sorted(set(out))


def _estimate_curvature(
    mesh: WeldedMesh,
    topo: _Topology,
    normals: Sequence[Vec3 | None],
    patches: Sequence[Sequence[int]],
    live: Sequence[int],
    h: float,
    sigma: float,
    dead_zone_sigmas: float,
) -> _PointFrame:
    """Local quadric (spec 4.3) then the HK signature (spec 4.4) with noise dead zones.

    Curvature at scan noise levels tells a 5 mm radius from a flat; it does not
    tell a 20 mm radius from a 25 mm one. So it ranks candidates and explains
    refusals, and is never an acceptance gate. The dead zones make it degrade
    honestly: as noise grows, more of the part reads ambiguous, ranking prunes
    less, RANSAC tries more kinds, and cost rises while correctness does not fall.
    """
    k_typical = max(4.0, sum(len(patches[i]) for i in live) / max(1, len(live)))
    sigma_kappa = (
        _CURVATURE_NOISE_COEFFICIENT * sigma / (h * h * math.sqrt(k_typical)) if h > 0.0 else math.inf
    )
    classes = ["ambiguous"] * len(mesh.vertices)
    kappa: list[tuple[float, float]] = [(0.0, 0.0)] * len(mesh.vertices)
    dead = dead_zone_sigmas * sigma_kappa
    for index in live:
        normal = normals[index]
        near = patches[index]
        if normal is None or len(near) < 6:
            continue
        u, v = _frame(normal)
        origin = mesh.vertices[index]
        rows = [[0.0] * 5 for _ in range(5)]
        rhs = [0.0] * 5
        scale = max(h, 1e-12)
        for other in near:
            w = _sub(mesh.vertices[other], origin)
            x, y = _dot(w, u) / scale, _dot(w, v) / scale
            z = _dot(w, normal) / scale
            basis = (x * x, x * y, y * y, x, y)
            for i in range(5):
                rhs[i] += basis[i] * z
                for j in range(5):
                    rows[i][j] += basis[i] * basis[j]
        solution = _solve(rows, rhs)
        if solution is None:
            continue
        a, b, c = solution[0] / scale, solution[1] / scale, solution[2] / scale
        # Shape operator [[2a, b], [b, 2c]] in the normalized frame.
        mean_term = a + c
        spread = math.sqrt((a - c) ** 2 + b * b)
        k1, k2 = mean_term + spread, mean_term - spread
        kappa[index] = (k1, k2)
        mean = 0.5 * (k1 + k2)
        gauss = k1 * k2
        gauss_dead = dead * (abs(k1) + abs(k2) + dead)
        sign_h = 0 if abs(mean) <= dead else (1 if mean > 0 else -1)
        sign_k = 0 if abs(gauss) <= gauss_dead else (1 if gauss > 0 else -1)
        if sign_k < 0:
            classes[index] = "saddle"
        elif sign_k > 0:
            classes[index] = "peak-pit"
        elif sign_h == 0:
            classes[index] = "flat"
        else:
            classes[index] = "ridge-valley"
    return _PointFrame(
        normals=list(normals),
        edge_adjacent=[],
        curvature_class=classes,
        kappa=kappa,
        sigma_kappa=sigma_kappa,
    )


# --------------------------------------------------------------------------
# minimal-set candidate construction (spec 5.1)
# --------------------------------------------------------------------------

_Candidate = tuple[str, dict[str, Any]]


def _plane_from(samples: Sequence[tuple[Vec3, Vec3]], epsilon: float, cos_alpha: float) -> _Candidate | None:
    (p1, n1), (p2, _n2), (p3, _n3) = samples[:3]
    normal = _unit(_cross(_sub(p2, p1), _sub(p3, p1)))
    if normal is None:
        return None
    # A plane through three points whose measured normals disagree with it is a
    # chord through curved surface. Rejecting here is what keeps plane candidates
    # from poisoning cylinders.
    for _p, n in samples[:3]:
        if abs(_dot(normal, n)) < cos_alpha:
            return None
    canonical = _canonical_direction(normal)
    return ("plane", {"normal": canonical, "offset": _dot(canonical, p1), "point_on_plane": p1})


def _sphere_from(p1: Vec3, n1: Vec3, p2: Vec3, n2: Vec3, epsilon: float) -> _Candidate | None:
    b = _dot(n1, n2)
    den = 1.0 - b * b
    if den < _DEGENERATE_DENOMINATOR:
        return None
    d = _sub(p2, p1)
    t1 = (_dot(n1, d) - b * _dot(n2, d)) / den
    t2 = (b * _dot(n1, d) - _dot(n2, d)) / den
    f1 = _add(p1, _scale(n1, t1))
    f2 = _add(p2, _scale(n2, t2))
    if _length(_sub(f1, f2)) > 2.0 * epsilon:
        return None
    centre = _scale(_add(f1, f2), 0.5)
    r1, r2 = _length(_sub(centre, p1)), _length(_sub(centre, p2))
    if abs(r1 - r2) > 2.0 * epsilon:
        return None
    radius = 0.5 * (r1 + r2)
    if not math.isfinite(radius) or radius <= 0.0:
        return None
    return ("sphere", {"center": centre, "radius": radius})


def _cylinder_from(p1: Vec3, n1: Vec3, p2: Vec3, n2: Vec3, epsilon: float) -> _Candidate | None:
    normal_cross = _cross(n1, n2)
    if _length(normal_cross) < _DEGENERATE_SINE:
        return None
    axis = _unit(normal_cross)
    if axis is None:
        return None
    u, v = _frame(axis)
    a2 = (_dot(_sub(p2, p1), u), _dot(_sub(p2, p1), v))
    d1 = (_dot(n1, u), _dot(n1, v))
    d2 = (_dot(n2, u), _dot(n2, v))
    den = -d1[0] * d2[1] + d1[1] * d2[0]
    if abs(den) < _DEGENERATE_DETERMINANT:
        return None
    t = (-a2[0] * d2[1] + a2[1] * d2[0]) / den
    anchor = _add(p1, _add(_scale(u, t * d1[0]), _scale(v, t * d1[1])))
    r1 = _axis_distance(p1, anchor, axis)
    r2 = _axis_distance(p2, anchor, axis)
    if abs(r1 - r2) > 2.0 * epsilon:
        return None
    radius = 0.5 * (r1 + r2)
    if not math.isfinite(radius) or radius <= 0.0:
        return None
    return ("cylinder", {"axis_point": anchor, "axis_direction": _canonical_direction(axis), "radius": radius})


def _axis_distance(point: Vec3, anchor: Vec3, axis: Vec3) -> float:
    w = _sub(point, anchor)
    return _length(_sub(w, _scale(axis, _dot(w, axis))))


def _cone_from(samples: Sequence[tuple[Vec3, Vec3]], min_half_angle: float) -> _Candidate | None:
    (p1, n1), (p2, n2), (p3, n3) = samples[:3]
    apex = _solve([n1, n2, n3], [_dot(n1, p1), _dot(n2, p2), _dot(n3, p3)])
    if apex is None:
        # Normals coplanar: this sample describes a cylinder, and a cylinder
        # candidate from the same sample will find it.
        return None
    apex_point: Vec3 = (apex[0], apex[1], apex[2])
    rays = [_unit(_sub(p, apex_point)) for p, _n in samples[:3]]
    if any(r is None for r in rays):
        return None
    axis = _unit(_cross(_sub(rays[1], rays[0]), _sub(rays[2], rays[0])))  # type: ignore[arg-type]
    if axis is None:
        return None
    if _dot(axis, _add(_add(rays[0], rays[1]), rays[2])) < 0.0:  # type: ignore[arg-type]
        axis = _scale(axis, -1.0)
    half = sum(math.acos(max(-1.0, min(1.0, _dot(r, axis)))) for r in rays) / 3.0  # type: ignore[arg-type]
    if not (min_half_angle < half < math.radians(89.0)):
        return None
    return ("cone", {"apex": apex_point, "axis_direction": axis, "half_angle_deg": math.degrees(half)})


def _torus_from(
    samples: Sequence[tuple[Vec3, Vec3]], epsilon: float, extent: float, max_radius_ratio: float
) -> _Candidate | None:
    """Every surface normal line of a torus meets its axis. Solve for that axis.

    Spec 5.1 constructs this from the pairwise closest-approach midpoints of four
    normal lines, rejecting a pair whose gap exceeds ``2 * epsilon``. **That
    construction cannot fire on a real torus**, and this is measured rather than
    argued: two normal lines of a torus meet *the axis*, not each other, and they
    meet each other only when their two points share a tube angle. Over six
    hundred sampled minimal sets on a clean 110x34 torus it produced zero
    candidates. Relaxing the gap does not fix it either -- the midpoints are then
    not axis points and the line through them is not the axis.

    The condition that is actually true of every sample is coplanarity: the axis
    ``a`` through a point ``c`` satisfies ``det[p_i - c, n_i, a] = 0`` for every
    oriented sample, because the normal line and the axis must meet. That is four
    equations, and each unknown is linear when the other is held:

    * given ``c``: ``a . ((p_i - c) x n_i) = 0``, so ``a`` is the null direction
      of those four vectors -- the smallest eigenvector of their scatter;
    * given ``a``: ``c . (n_i x a) = p_i . (n_i x a)``, a linear system in ``c``.

    Alternating the two converges in a handful of passes from the sample
    centroid. Then the torus is a circle in the axial half-plane (spec 5.8), so
    ``_fit_circle_2d`` over the four ``(rho, t)`` projections finishes it.

    Degeneracies fall through to the simpler kinds rather than becoming a wild
    torus: normals that give no null direction (a plane), a scatter with no
    unique smallest eigenvector (a cylinder or sphere), a tube at least as fat as
    its major radius (a spindle), or a major radius past the flat-strip gate.
    """
    if len(samples) < 4:
        return None
    points = [p for p, _n in samples[:4]]
    normals = [n for _p, n in samples[:4]]
    centre = _centroid(points)
    axis: Vec3 | None = None
    for _ in range(_TORUS_AXIS_PASSES):
        moments = [_cross(_sub(p, centre), n) for p, n in zip(points, normals)]
        scatter = [[sum(m[i] * m[j] for m in moments) for j in range(3)] for i in range(3)]
        values, vectors = _symmetric_eigen(scatter)
        # Eigenvalues ascend, so values[0] is the candidate null direction. It is
        # only a *direction* if the next one is clearly larger; otherwise the
        # moments span less than two dimensions and the sample is describing a
        # cylinder or a sphere, which their own candidates will find.
        if values[1] <= _TORUS_AXIS_UNIQUENESS * values[0]:
            # No unique null direction: the normals are already consistent with a
            # cylinder or a sphere, and those candidates will find it.
            return None
        axis = vectors[0]
        # Solve for the centre *across* the axis only. Every row here is
        # ``n_i x a``, which is perpendicular to ``a`` by construction, so the
        # along-axis component of the centre is genuinely undetermined and a 3x3
        # solve for it is singular every time -- not sometimes. Two unknowns in
        # the perpendicular frame is the well-posed version of the same equation.
        u, v = _frame(axis)
        rows = [[0.0, 0.0], [0.0, 0.0]]
        rhs = [0.0, 0.0]
        for p, n in zip(points, normals):
            row = _cross(n, axis)
            basis = (_dot(u, row), _dot(v, row))
            target = _dot(_sub(p, centre), row)
            for i in range(2):
                rhs[i] += basis[i] * target
                for j in range(2):
                    rows[i][j] += basis[i] * basis[j]
        solution = _solve(rows, rhs)
        if solution is None or not all(math.isfinite(c) for c in solution):
            return None
        centre = _add(centre, _add(_scale(u, solution[0]), _scale(v, solution[1])))
    if axis is None:
        return None

    rhos = [_axis_distance(p, centre, axis) for p in points]
    ts = [_dot(_sub(p, centre), axis) for p in points]
    circle = _fit_circle_2d(rhos, ts)
    if circle is None:
        return None
    major, t0, minor = circle
    if not all(math.isfinite(value) for value in (major, t0, minor)) or minor <= 0.0:
        return None
    if minor >= major:
        return None
    if major > max_radius_ratio * extent:
        return None
    return (
        "torus",
        {
            "center": _add(centre, _scale(axis, t0)),
            "axis_direction": _canonical_direction(axis),
            "radius": major,
            "minor_radius": minor,
        },
    )


def _construct(
    kind: str,
    samples: Sequence[tuple[Vec3, Vec3]],
    epsilon: float,
    cos_alpha: float,
    extent: float,
    spec: DetectionSpec,
) -> _Candidate | None:
    if kind == "plane":
        return _plane_from(samples, epsilon, cos_alpha)
    if kind == "sphere":
        return _sphere_from(samples[0][0], samples[0][1], samples[1][0], samples[1][1], epsilon)
    if kind == "cylinder":
        return _cylinder_from(samples[0][0], samples[0][1], samples[1][0], samples[1][1], epsilon)
    if kind == "cone":
        return _cone_from(samples, math.atan(float(spec.value("min_taper_ratio"))))
    return _torus_from(samples, epsilon, extent, float(spec.value("max_radius_ratio")))


# --------------------------------------------------------------------------
# scoring, refinement, extraction cascade (spec 5.5 - 5.8)
# --------------------------------------------------------------------------


@dataclass(slots=True)
class _Detected:
    kind: str
    parameters: dict[str, Any]
    points: list[int]


def _inliers(
    candidate: _Candidate,
    pool: Sequence[int],
    mesh: WeldedMesh,
    frame: _PointFrame,
    edge_adjacent: Sequence[bool],
    epsilon: float,
    cos_alpha: float,
) -> list[int]:
    """Distance band plus normal agreement (spec 5.5).

    Distance alone is not consensus: a plane cutting through a solid has every
    triangle it crosses inside the band, and only the normal test tells the
    surface from the section. Points flagged ``edge_adjacent`` are exempt from
    the normal test, per spec 4.1.
    """
    kind, parameters = candidate
    points = [mesh.vertices[i] for i in pool]
    residuals = _residuals(kind, parameters, points)
    out: list[int] = []
    for offset, index in enumerate(pool):
        if abs(residuals[offset]) > epsilon:
            continue
        if not edge_adjacent[index]:
            normal = frame.normals[index]
            surface = _surface_normal(kind, parameters, points[offset])
            if normal is None or surface is None or abs(_dot(normal, surface)) < cos_alpha:
                continue
        out.append(index)
    return out


def _largest_point_component(indices: Sequence[int], topo: _Topology) -> list[int]:
    """The biggest mesh-connected run of the inlier set.

    Spec 5.5 rasterizes each kind's own 2-D chart and flood-fills it. This uses
    the mesh's own adjacency graph instead: it needs no per-kind chart, no
    wraparound stitching and no octahedral sphere map, and it answers the same
    question -- is this one piece of surface? -- from real topology rather than
    from a rasterization of it. The one thing the chart would add is joining two
    inlier patches across a hole in the mesh, which is not a join we want.
    ``ponytail:`` chart bitmaps if a real scan shows components split by
    tessellation artifacts that the mesh graph should have joined.
    """
    members = set(indices)
    best: list[int] = []
    seen: set[int] = set()
    for start in indices:
        if start in seen:
            continue
        component = [start]
        seen.add(start)
        frontier = [start]
        while frontier:
            nxt: list[int] = []
            for index in frontier:
                for other in topo.point_neighbours[index]:
                    if other in members and other not in seen:
                        seen.add(other)
                        component.append(other)
                        nxt.append(other)
            frontier = nxt
        if len(component) > len(best):
            best = component
    return sorted(best)


def _refine(
    candidate: _Candidate,
    pool: Sequence[int],
    mesh: WeldedMesh,
    topo: _Topology,
    frame: _PointFrame,
    edge_adjacent: Sequence[bool],
    epsilon: float,
    cos_alpha: float,
    spec: DetectionSpec,
) -> _Detected | None:
    """Propose, refine, iterate to a fixed point (spec 5.8).

    RANSAC's candidate is built from as few as two points; the exact fitters are
    what give the parameters least-squares meaning. The loop is not monotone --
    the inlier set is a step function of the parameters -- so the criterion is
    fixed point or best-seen, bounded. A refit that fails is candidate rejection,
    never a fallback to the raw RANSAC parameters, which carry no least-squares
    meaning at all.
    """
    kind = candidate[0]
    current = candidate
    best: _Detected | None = None
    best_score = (-1, math.inf)
    previous: list[int] | None = None
    for _ in range(int(spec.value("refine_iterations"))):
        component = _largest_point_component(
            _inliers(current, pool, mesh, frame, edge_adjacent, epsilon, cos_alpha), topo
        )
        if len(component) < _MIN_REGION_POINTS:
            break
        points = [mesh.vertices[i] for i in component]
        extent = _extent(points)
        if extent <= 0.0:
            break
        refit = _raw_fit(
            points,
            kind,
            extent,
            float(spec.value("min_taper_ratio")),
            float(spec.value("min_torus_major_ratio")),
            _fit_axis_hint(current),
        )
        # The pair kept is (parameters, the inliers *those* parameters produced).
        # Pairing the refit's parameters with the pre-refit inlier set is the
        # subtle version of this loop's only real trap: a refit that wanders then
        # inherits the previous estimate's support and wins on a count it did not
        # earn, and every downstream gate is handed a large region whose points
        # are nowhere near its own surface.
        residual = _rms(_residuals(current[0], current[1], points))
        score = (len(component), residual)
        if score[0] > best_score[0] or (score[0] == best_score[0] and score[1] < best_score[1]):
            best_score = score
            best = _Detected(kind=kind, parameters=dict(current[1]), points=component)
        if not refit.accepted:
            break
        if previous is not None and component == previous:
            break
        previous = component
        current = (kind, dict(refit.parameters))
    return best


def _fit_axis_hint(candidate: _Candidate) -> Vec3 | None:
    return candidate[1].get("axis_direction")


def _miss_probability(shape_points: int, live: int, levels: int, minimal_set: int, rounds: int) -> float:
    """Spec 5.2: (1 - p_hat)^T, with p_hat the localized-sampling lower bound (5.1)."""
    if live <= 0 or shape_points <= 0 or rounds <= 0:
        return 1.0
    p = (shape_points / live) * (1.0 / max(1, levels)) * (0.5 ** (minimal_set - 1))
    p = min(max(p, 0.0), 1.0)
    if p <= 0.0:
        return 1.0
    return (1.0 - p) ** rounds


def _detect(state: dict[str, Any]) -> list[_Detected]:
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    spec: DetectionSpec = state["spec"]
    frame: _PointFrame = state["frame"]
    edge_adjacent: list[bool] = state["edge_adjacent"]
    grid: _Grid = state["grid"]
    epsilon: float = state["epsilon"]
    cos_alpha = math.cos(math.radians(state["normals"]["alpha_deg"]))
    rng = _stage_rng(mesh.dump_sha256, f"detection:{int(spec.value('rng_seed'))}")

    live = sorted(state["live_points"])
    live_set = set(live)
    levels = len(grid.levels)
    detected: list[_Detected] = []
    minimum_points = max(
        _MIN_REGION_POINTS,
        int(float(spec.value("min_inlier_area_fraction")) * len(live)),
    )
    rounds = 0
    max_rounds = int(spec.value("max_candidate_rounds"))
    eta_extract = float(spec.value("ransac_eta_extract"))
    eta_stop = float(spec.value("ransac_eta_stop"))
    sample_size = int(spec.value("score_sample_size"))
    serial = 0
    best: tuple[int, int, _Candidate] | None = None  # (score, -serial, candidate)

    while len(detected) < int(spec.value("max_primitives")) and len(live_set) >= minimum_points:
        pool = sorted(live_set)
        subsample = sorted(rng.sample(pool, min(sample_size, len(pool))))
        # The best candidate *per kind*, not one best overall. A minimal set of
        # four points constrains a plane far better than it constrains a torus,
        # so raw consensus at proposal time systematically favours the simpler
        # kinds -- and the whole point of refinement is that a rough candidate of
        # the right kind beats a sharp candidate of the wrong one once it has
        # been fitted to its own inliers. Refining one per kind costs at most
        # five refinements per extraction and is what lets a torus ever win.
        best_by_kind: dict[str, tuple[int, int, _Candidate]] = {}
        rounds_this_shape = 0
        while rounds_this_shape < max_rounds:
            rounds += 1
            rounds_this_shape += 1
            seed = pool[rng.randrange(len(pool))]
            level = rng.randrange(levels)
            cell = [i for i in grid.cell_members(seed, level) if i in live_set]
            picks = [seed]
            source = cell if len(cell) >= 4 else pool
            for _ in range(3):
                picks.append(source[rng.randrange(len(source))])
            samples: list[tuple[Vec3, Vec3]] = []
            for index in picks:
                normal = frame.normals[index]
                if normal is None:
                    samples = []
                    break
                samples.append((mesh.vertices[index], normal))
            if len(samples) < 4:
                continue
            for kind in _RANKED_KINDS[frame.curvature_class[seed]]:
                candidate = _construct(kind, samples, epsilon, cos_alpha, topo.extent, spec)
                if candidate is None:
                    continue
                serial += 1
                hits = len(
                    _inliers(candidate, subsample, mesh, frame, edge_adjacent, epsilon, cos_alpha)
                )
                score = int(hits * len(pool) / max(1, len(subsample)))
                held = best_by_kind.get(kind)
                if held is None or score > held[0] or (score == held[0] and -serial > held[1]):
                    best_by_kind[kind] = (score, -serial, candidate)
            leader = max((v[0] for v in best_by_kind.values()), default=0)
            if leader > 0 and _miss_probability(
                leader, len(live_set), levels, 4, rounds_this_shape
            ) <= eta_extract:
                break
            if _miss_probability(minimum_points, len(live_set), levels, 4, rounds_this_shape) <= eta_stop:
                break
        if not best_by_kind:
            break

        refined_best: _Detected | None = None
        for kind in DETECTED_KINDS:
            held = best_by_kind.get(kind)
            if held is None:
                continue
            refined = _refine(
                held[2], pool, mesh, topo, frame, edge_adjacent, epsilon, cos_alpha, spec
            )
            if refined is None:
                continue
            if refined_best is None or len(refined.points) > len(refined_best.points):
                refined_best = refined
        if refined_best is None or len(refined_best.points) < minimum_points:
            break
        detected.append(refined_best)
        live_set.difference_update(refined_best.points)
        if not live_set:
            break
    state["candidate_rounds"] = rounds
    return detected


# --------------------------------------------------------------------------
# segmentation as refinement: Potts ICM over triangles (spec 6)
# --------------------------------------------------------------------------


def _label_triangles(state: dict[str, Any], detected: Sequence[_Detected]) -> list[int]:
    """Assign every triangle to a primitive or to unclaimed, by local energy descent.

    Exact multi-label minimization is graph-cut alpha-expansion, which needs a
    max-flow solver: implementable in stdlib but large and slow in CPython at
    200k triangles. ICM is the substitute the spec chooses, and it is a good one
    here because the data terms are strong -- primitives are 3 sigma apart except
    in blend bands -- so its local minima are confined to one or two triangles of
    boundary jitter. ``ponytail:`` alpha-expansion if boundary quality on real
    scans proves insufficient; cost is a max-flow implementation.

    Reopening assignment globally is also what fixes greedy extraction's known
    failure: a large plane can steal the flank of an adjacent tangent cylinder
    during the cascade, so cascade order affects discovery but must not affect
    the final labelling.
    """
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    spec: DetectionSpec = state["spec"]
    epsilon: float = state["epsilon"]
    # The labelling has to use the same scales detection used, or a triangle that
    # was an inlier of a surface becomes an outlier of its own label. That means
    # the *surface* scale -- noise plus discretization -- not the noise alone,
    # and the agreement half-angle the normal check actually ran at.
    sigma: float = max(state["noise"]["sigma"], _BAND_FLOOR_RATIO * topo.extent)
    sigma_theta = max(math.radians(state["normals"]["alpha_deg"]) / 3.0, 1e-9)
    smoothness = float(spec.value("icm_smoothness"))
    normal_weight = float(spec.value("icm_normal_weight"))
    unclaimed_cost = float(spec.value("icm_unclaimed_chi2"))
    edge_unit = topo.median_edge if topo.median_edge > 0.0 else 1.0

    labels = [-1] * len(mesh.triangles)
    data: list[dict[int, float]] = [{} for _ in mesh.triangles]
    for index in topo.valid:
        centre = topo.centroids[index]
        corners = [mesh.vertices[v] for v in mesh.triangles[index]]
        for label, primitive in enumerate(detected):
            # Measured at the triangle's own vertices, not at its barycenter: a
            # facet's barycenter sits a sagitta inside the surface its vertices
            # lie on, and on a coarse mesh that offset is larger than the noise.
            distance = _rms(_residuals(primitive.kind, primitive.parameters, corners))
            if distance > 5.0 * epsilon:
                continue
            surface = _surface_normal(primitive.kind, primitive.parameters, centre)
            angle = (
                math.acos(max(-1.0, min(1.0, abs(_dot(surface, topo.tri_normals[index])))))
                if surface is not None
                else math.pi / 2.0
            )
            data[index][label] = topo.areas[index] * (
                (distance / sigma) ** 2 + normal_weight * (angle / sigma_theta) ** 2
            )
        best_label, best_cost = -1, topo.areas[index] * unclaimed_cost
        for label, cost in sorted(data[index].items()):
            if cost < best_cost:
                best_label, best_cost = label, cost
        labels[index] = best_label

    for _sweep in range(int(spec.value("icm_sweeps"))):
        changed = False
        for index in topo.valid:
            options = sorted(data[index]) + [-1]
            best_label, best_cost = labels[index], math.inf
            for option in options:
                cost = (
                    data[index].get(option, topo.areas[index] * unclaimed_cost)
                    if option >= 0
                    else topo.areas[index] * unclaimed_cost
                )
                for other in topo.tri_neighbours[index]:
                    if labels[other] != option:
                        cost += smoothness * edge_unit
                if cost < best_cost:
                    best_label, best_cost = option, cost
            if best_label != labels[index]:
                labels[index] = best_label
                changed = True
        if not changed:
            break
    return labels


# --------------------------------------------------------------------------
# disproof gates (spec 10)
# --------------------------------------------------------------------------


def _angular_span(fit: PrimitiveFit, points: Sequence[Vec3]) -> float:
    """Degrees of arc swept about the axis: 360 minus the largest gap (64 bins)."""
    anchor = fit.parameters.get("axis_point") or fit.parameters.get("apex") or fit.parameters.get("center")
    axis = fit.parameters["axis_direction"]
    u, v = _frame(axis)
    occupied = [False] * 64
    for p in points:
        w = _sub(p, anchor)
        angle = math.atan2(_dot(w, v), _dot(w, u))
        occupied[int((angle + math.pi) / (2.0 * math.pi) * 64) % 64] = True
    if not any(occupied):
        return 0.0
    gap = run = 0
    for k in range(128):
        if occupied[k % 64]:
            run = 0
        else:
            run += 1
            gap = max(gap, min(run, 64))
    return 360.0 * (64 - gap) / 64.0


def _support_floors(
    fit: PrimitiveFit, points: Sequence[Vec3], spec: DetectionSpec, median_edge: float
) -> tuple[bool, dict[str, Any]]:
    """Spec 10.1's hard floors.

    These run *before* any uncertainty is trusted, and that ordering is the whole
    point: a shallow arc's radius uncertainty grows as 1/phi^2, and the
    covariance that would detect it is computed from the very matrix that is
    going near-singular. A geometric span is measured directly and cannot lie
    about itself.
    """
    measured: dict[str, Any] = {}
    if fit.kind == "plane":
        u, v = _frame(fit.parameters["normal"])
        us = [_dot(p, u) for p in points]
        vs = [_dot(p, v) for p in points]
        du, dv = max(us) - min(us), max(vs) - min(vs)
        wide = max(du, dv)
        aspect = 0.0 if wide <= 0.0 else min(du, dv) / wide
        measured["plane_aspect"] = aspect
        return aspect >= float(spec.value("min_plane_aspect")), measured
    if fit.kind == "sphere":
        occupancy = min(1.0, _extent(points) / max(2.0 * fit.parameters["radius"], 1e-12))
        measured["sphere_occupancy"] = occupancy
        return occupancy >= float(spec.value("min_sphere_occupancy")), measured

    span = _angular_span(fit, points)
    measured["angular_span_deg"] = span
    if span < float(spec.value("min_angular_span_deg")):
        return False, measured
    anchor = (
        fit.parameters.get("axis_point") or fit.parameters.get("apex") or fit.parameters["center"]
    )
    axis = fit.parameters["axis_direction"]
    stations = [_dot(_sub(p, anchor), axis) for p in points]
    # Emitted for every axis-bearing kind under exactly this key: downstream
    # treats its absence as a refusal, and an absent number is not a small number.
    measured["axial_span"] = max(stations) - min(stations)
    if fit.kind in ("cylinder", "cone"):
        radius = fit.parameters.get("radius") or _median(
            [_axis_distance(p, anchor, axis) for p in points]
        )
        floor = max(float(spec.value("min_axial_span_ratio")) * radius, 4.0 * median_edge)
        measured["axial_span_floor"] = floor
        if measured["axial_span"] < floor:
            return False, measured
    return True, measured


def _uncertainty_gate(
    uncertainty: Mapping[str, float], fit: PrimitiveFit, spec: DetectionSpec
) -> str | None:
    """Spec 10.1's primary test: are the parameters determined well enough to use?

    This runs *after* the hard geometric floors, deliberately. Near a shallow arc
    the radius uncertainty grows as ``1/phi^2``, and the covariance that would
    report the disaster is computed from the very matrix that is going singular
    -- so the floors, which measure geometry directly and cannot lie about
    themselves, have to clear the way first.

    An empty uncertainty mapping means the parameters were *not determined*, and
    that is a rejection, not a pass. Treating an absent sigma as zero is the
    exact shape of inventing precision.
    """
    if not uncertainty:
        return (
            f"parameter uncertainty: the normal equations for this {fit.kind} are singular over "
            "its supporting points, so its parameters are not determined by the data at all."
        )
    # Per-parameter absence here means *this kind has no such parameter* -- a
    # plane has no radius, a sphere has no axis -- not "the check passed". The
    # whole-mapping absence, which does mean the parameters are undetermined, is
    # the refusal above; these two are genuinely not-applicable.
    radius = fit.parameters.get("radius")
    sigma_r = uncertainty.get("radius")
    if isinstance(radius, float) and radius > 0.0 and sigma_r is not None:
        relative = sigma_r / radius
        if relative > float(spec.value("max_radius_rel_sigma")):
            return (
                f"parameter uncertainty: the fitted radius is {radius:.6g} with a one-sigma of "
                f"{sigma_r:.4g} ({relative:.3g} relative), above the declared "
                f"{float(spec.value('max_radius_rel_sigma')):g}."
            )
    tilt = uncertainty.get("axis_tilt_deg")
    if tilt is not None and tilt > float(spec.value("max_axis_sigma_deg")):
        return (
            f"parameter uncertainty: the fitted axis direction carries a one-sigma of "
            f"{tilt:.4g} deg, above the declared {float(spec.value('max_axis_sigma_deg')):g} deg; "
            "relationships built on an axis this uncertain would be fiction."
        )
    return None


def _moran_i(residuals: Sequence[float], indices: Sequence[int], topo: _Topology) -> dict[str, float] | None:
    """Spec 10.2: Moran's I with its exact variance, on the mesh adjacency graph.

    A wrong-kind fit puts whole bands of residuals on the same side of zero, and
    that is spatial autocorrelation, which this measures with a closed-form null.
    The iid null is conservative-false because scanner noise is itself mildly
    correlated, which is why the threshold is a large z and is *also* compared
    against the part's own best plane as an empirical baseline.
    """
    n = len(indices)
    if n < _MORAN_MIN_POINTS:
        return None
    position = {index: offset for offset, index in enumerate(indices)}
    mean = sum(residuals) / n
    centred = [r - mean for r in residuals]
    denominator = sum(c * c for c in centred)
    if denominator <= 0.0:
        return None
    s0 = 0.0
    numerator = 0.0
    degrees = [0] * n
    for offset, index in enumerate(indices):
        for other in topo.point_neighbours[index]:
            target = position.get(other)
            if target is None:
                continue
            s0 += 1.0
            degrees[offset] += 1
            numerator += centred[offset] * centred[target]
    if s0 <= 0.0:
        return None
    moran = (n / s0) * (numerator / denominator)
    expectation = -1.0 / (n - 1)
    s1 = 2.0 * s0
    s2 = 4.0 * sum(d * d for d in degrees)
    variance = (n * n * s1 - n * s2 + 3.0 * s0 * s0) / (s0 * s0 * (n * n - 1)) - expectation * expectation
    if variance <= 0.0:
        return None
    return {
        "i": moran,
        "expectation": expectation,
        "z": (moran - expectation) / math.sqrt(variance),
        "n": float(n),
    }


def _directional_bins(
    fit: PrimitiveFit, points: Sequence[Vec3], residuals: Sequence[float], sigma: float, sigmas: float
) -> tuple[bool, str | None, float]:
    """Spec 10.2's complement: which chart coordinate the structure lives in.

    Naming the coordinate is the most actionable diagnostic in the gate set --
    axial structure means cone-versus-cylinder, azimuthal means an off-axis fit.
    Two *adjacent* bins must both exceed the bound, so one unlucky bin is noise
    rather than a verdict.
    """
    from .mesh_fitting import _structure_stations

    names = _station_names(fit.kind)
    worst = 0.0
    culprit: str | None = None
    for axis_index, station in enumerate(_structure_stations(fit, points)):
        order = sorted(range(len(points)), key=lambda i: station[i])
        bins = 16
        size = len(order) / bins
        means: list[float] = []
        bounds: list[float] = []
        for b in range(bins):
            lo = int(b * size)
            hi = len(order) if b == bins - 1 else int((b + 1) * size)
            if hi - lo < 2:
                means.append(0.0)
                bounds.append(math.inf)
                continue
            means.append(sum(residuals[i] for i in order[lo:hi]) / (hi - lo))
            bounds.append(sigmas * sigma / math.sqrt(hi - lo))
        for b in range(bins - 1):
            if abs(means[b]) > bounds[b] and abs(means[b + 1]) > bounds[b + 1]:
                magnitude = min(abs(means[b]) / max(bounds[b], 1e-30), abs(means[b + 1]) / max(bounds[b + 1], 1e-30))
                if magnitude > worst:
                    worst = magnitude
                    culprit = names[axis_index] if axis_index < len(names) else f"coordinate-{axis_index}"
    return culprit is not None, culprit, worst


def _station_names(kind: str) -> tuple[str, ...]:
    if kind == "plane":
        return ("in-plane-u", "in-plane-v")
    if kind == "sphere":
        return ("polar", "azimuthal")
    if kind == "torus":
        return ("axial", "azimuthal", "tube-angle")
    return ("axial", "azimuthal")


def _blocked_heldout(
    fit: PrimitiveFit,
    indices: Sequence[int],
    mesh: WeldedMesh,
    grid: _Grid,
    spec: DetectionSpec,
) -> dict[str, float] | None:
    """Spec 10.3: checkerboard by grid-cell parity, not a random point split.

    A random split is optimistic under correlated noise: every held-out point has
    an in-sample neighbour half a millimetre away, so the model has effectively
    seen it. Blocking by cell parity puts whole neighbourhoods on one side.
    """
    parts: dict[int, list[int]] = {0: [], 1: []}
    for index in indices:
        key = grid.keys.get(index)
        if key is None:
            continue
        parts[(key[0] + key[1] + key[2]) & 1].append(index)
    if min(len(parts[0]), len(parts[1])) < _MIN_REGION_POINTS:
        return None
    taper = float(spec.value("min_taper_ratio"))
    major = float(spec.value("min_torus_major_ratio"))
    floor = _BAND_FLOOR_RATIO * fit.extent
    worst = 0.0
    heldout_rms = 0.0
    in_sample_rms = 0.0
    for train_key, test_key in ((0, 1), (1, 0)):
        train = [mesh.vertices[i] for i in parts[train_key]]
        test = [mesh.vertices[i] for i in parts[test_key]]
        extent = _extent(train)
        if extent <= 0.0:
            return None
        trial = _raw_fit(train, fit.kind, extent, taper, major)
        if not trial.accepted:
            return None
        held = _rms(_residuals(trial.kind, trial.parameters, test))
        # Against *this* fit's own in-sample residual, not the full fit's. The
        # question is whether a model generalizes beyond the data that produced
        # it; comparing a half-data fit's held-out error against a full-data
        # fit's in-sample error asks a different and much harsher question, and
        # it fails a correct model whenever the fitter is merely less
        # well-conditioned on half the points -- which is a property of the
        # fitter, not evidence of overfitting.
        ratio = held / max(trial.rms_residual, floor)
        if ratio > worst:
            worst = ratio
            heldout_rms = held
            in_sample_rms = trial.rms_residual
    return {"heldout_rms": heldout_rms, "in_sample_rms": in_sample_rms, "ratio": worst}


def _betai(a: float, b: float, x: float) -> float:
    """Regularized incomplete beta, by the standard continued fraction.

    Needed for one thing only: the p-value of the parsimony F test. stdlib has no
    F distribution and this is thirty lines of textbook arithmetic, which is a
    better trade than importing scipy for a single tail probability.
    """
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log(1.0 - x)
    )
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def _betacf(a: float, b: float, x: float) -> float:
    tiny = 1e-30
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 201):
        m2 = 2 * m
        numerator = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        numerator = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + numerator * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + numerator / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 3e-12:
            break
    return h


def _f_survival(f: float, d1: int, d2: int) -> float:
    """P(F_{d1,d2} > f)."""
    if f <= 0.0 or d1 <= 0 or d2 <= 0:
        return 1.0
    return _betai(d2 / 2.0, d1 / 2.0, d2 / (d2 + d1 * f))


def _parsimony(
    fit: PrimitiveFit, points: Sequence[Vec3], spec: DetectionSpec, n_eff: float
) -> tuple[bool, dict[str, Any]]:
    """Spec 10.4: a richer kind is kept only when the F test says it earned its parameters.

    The kinds nest -- a cylinder is a cone with no taper and a torus with an
    infinite major radius, a sphere is a torus with none -- so the question "is
    this really a torus?" has an exact answer in the residual sums, and the
    answer does not depend on anyone's opinion about a radius ratio.
    """
    detail: dict[str, Any] = {}
    rich_p = _FREE_PARAMETERS[fit.kind]
    extent = fit.extent
    for simpler in _NESTED_IN.get(fit.kind, ()):
        rival = _raw_fit(
            points,
            simpler,
            extent,
            float(spec.value("min_taper_ratio")),
            float(spec.value("min_torus_major_ratio")),
        )
        if not rival.accepted:
            continue
        simple_p = _FREE_PARAMETERS[simpler]
        delta = rich_p - simple_p
        rich_ssr = fit.rms_residual ** 2 * len(points)
        simple_ssr = rival.rms_residual ** 2 * len(points)
        dof = max(1, int(n_eff) - rich_p)
        if rich_ssr <= 0.0 or delta <= 0:
            continue
        f_value = ((simple_ssr - rich_ssr) / delta) / (rich_ssr / dof)
        p_value = _f_survival(f_value, delta, dof)
        detail[f"f_vs_{simpler}"] = f_value
        detail[f"p_vs_{simpler}"] = p_value
        if p_value >= float(spec.value("parsimony_alpha")):
            detail["parsimony_loser"] = simpler
            return False, detail
    return True, detail


# --------------------------------------------------------------------------
# stages
# --------------------------------------------------------------------------


def _refusal(reason: str, detail: Mapping[str, Any], alternative: str) -> dict[str, Any]:
    if not _in_closed_set(reason, REFUSAL_REASONS):
        raise ValueError(f"refusal reason must be one of {', '.join(sorted(REFUSAL_REASONS))}.")
    return {"reason": reason, "detail": dict(detail), "alternative": alternative}


def _stage_triangle_budget(state: dict[str, Any]) -> dict[str, Any] | None:
    dump: MeshDump = state["dump"]
    budget = int(state["spec"].value("max_triangles"))
    state["record"]["dump"] = {
        "sha256": dump.sha256,
        "triangle_count": dump.triangle_count,
        "vertex_count": dump.vertex_count,
        "face_groups_source": dump.metadata.get("face_groups_source"),
        "vertex_units": dump.metadata.get("vertex_units"),
    }
    if dump.triangle_count > budget:
        return _refusal(
            "triangle-budget-exceeded",
            {"triangle_count": dump.triangle_count, "max_triangles": budget},
            "Decimate the mesh to within the declared budget and re-extract; the new dump has a "
            "new hash, and the fit record binds to that hash while the deviation verdict still "
            "grades against the original.",
        )
    return None


def _stage_weld(state: dict[str, Any]) -> dict[str, Any] | None:
    """Weld under the declared tolerance, then refuse if the mesh still is not connected.

    This is the fail-closed guard the whole module rests on. An unwelded mesh
    does not make the estimators fail; it makes them confidently wrong, because
    every vertex neighbourhood degenerates to one triangle and every edge reads
    as a boundary. A refusal naming the numbers is enormously better than a fit
    that looks fine and is not.
    """
    dump: MeshDump = state["dump"]
    mesh = weld_dump(dump, float(state["spec"].value("weld_tolerance")))
    state["mesh"] = mesh
    state["record"]["weld"] = dict(mesh.weld)
    if len(mesh.triangles) < _MIN_REGION_TRIANGLES:
        return _refusal(
            "mesh-degenerate",
            dict(mesh.weld),
            "Welding left too few triangles to fit anything. Check the weld tolerance against the "
            "mesh's own scale, or repair the mesh upstream.",
        )
    topo = _build_topology(mesh)
    state["topology"] = topo
    interior_fraction = topo.interior_edges / max(1, topo.interior_edges + topo.boundary_edges)
    state["record"]["weld"]["interior_edge_fraction"] = interior_fraction
    if topo.interior_edges == 0:
        return _refusal(
            "mesh-not-welded",
            {
                **mesh.weld,
                "interior_edges": topo.interior_edges,
                "boundary_edges": topo.boundary_edges,
            },
            "Every edge reads as a boundary, so this mesh carries no adjacency: neighbourhood "
            "normals, the dihedral noise estimator and the residual-structure test would all "
            "return confidently wrong answers. Declare a weld_tolerance matched to the scanner's "
            "point spacing and run again.",
        )
    return None


def _stage_topology(state: dict[str, Any]) -> dict[str, Any] | None:
    topo: _Topology = state["topology"]
    state["record"]["topology"] = {
        "usable_triangles": len(topo.valid),
        "degenerate_triangles": len(topo.degenerate),
        "interior_edges": topo.interior_edges,
        "boundary_edges": topo.boundary_edges,
        "non_manifold_edges": topo.non_manifold_edges,
        "total_area": topo.total_area,
        "extent": topo.extent,
        "median_edge_length": topo.median_edge,
    }
    if len(topo.valid) < _MIN_REGION_TRIANGLES or topo.total_area <= 0.0 or topo.extent <= 0.0:
        return _refusal(
            "mesh-degenerate",
            {"usable_triangles": len(topo.valid), "total_area": topo.total_area, "extent": topo.extent},
            "Repair the mesh so it carries non-degenerate triangles with a positive extent, "
            "re-extract, and try again.",
        )
    mesh: WeldedMesh = state["mesh"]
    live = sorted({v for index in topo.valid for v in mesh.triangles[index]})
    state["live_points"] = live
    state["grid"] = _Grid(mesh.vertices, live, max(2.0 * topo.median_edge, 1e-9))
    state["grid"].build_levels(max(1, int(math.log2(max(2.0, topo.extent / max(topo.median_edge, 1e-9))))))
    return None


def _stage_noise_scale(state: dict[str, Any]) -> dict[str, Any] | None:
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    surface_scale, sigma_quadric = _local_scale_estimates(mesh, topo, state["live_points"])
    sigma_dihedral = _sigma_dihedral(topo)
    # Two independent *noise* estimators, cross-checked. The larger is used --
    # the conservative choice, since every downstream band widens with it.
    sigma = max(sigma_quadric, sigma_dihedral)
    lo, hi = sorted((sigma_quadric, sigma_dihedral))
    inconsistent = hi > 0.0 and (lo <= 0.0 or hi / lo > 2.0)
    surface_scale = max(surface_scale, sigma)
    discretization = math.sqrt(max(0.0, surface_scale * surface_scale - sigma * sigma))
    state["noise"] = {"sigma": sigma, "surface_scale": surface_scale}
    if inconsistent:
        state["flags"].append("noise-model-inconsistent")
    # The band is sized by the *noise*, not the surface scale, because every
    # point it tests is a mesh vertex and mesh vertices lie on the surface -- the
    # facet chord sags between them, not at them. Sizing it by the surface scale
    # instead would set the band by how much the surface curves across a
    # neighbourhood, which is real geometry rather than error, and a plane
    # candidate would then harvest a swathe of any gently curved part.
    state["epsilon"] = max(
        float(state["spec"].value("epsilon_sigmas")) * sigma,
        _BAND_FLOOR_RATIO * topo.extent,
    )
    dihedral = _dihedral_degrees(topo)
    state["record"]["noise"] = {
        "sigma": sigma,
        "sigma_quadric": sigma_quadric,
        "sigma_dihedral": sigma_dihedral,
        "surface_scale": surface_scale,
        "discretization_scale": discretization,
        "sigma_over_extent": sigma / topo.extent if topo.extent > 0.0 else math.inf,
        "sigma_over_median_edge": sigma / topo.median_edge if topo.median_edge > 0.0 else math.inf,
        "median_abs_dihedral_deg": _median(dihedral) if dihedral else None,
        "interior_edge_count": len(dihedral),
        "consensus_band": state["epsilon"],
        "estimators_consistent": not inconsistent,
        "note": (
            "sigma is measurement noise, estimated about a local quadric so surface curvature "
            "does not read as noise, and cross-checked against the calibrated dihedral median. "
            "surface_scale adds the mesh's own discretization, and it is what sizes the consensus "
            "band. Neither decides whether to give up: that is the feature-scale budget."
        ),
    }
    return None


def _stage_feature_scale(state: dict[str, Any]) -> dict[str, Any] | None:
    """The revised noise refusal (spec 12.1, 14.1): information content, not estimator noise.

    Two surfaces closer together than about ten sigma cannot be told apart by any
    distance-band method -- within the patch the two hypotheses differ by less
    than the noise, which is information-theoretic rather than a limitation of
    this implementation. So the honest refusal is that the recoverable feature
    size has risen above the smallest feature the caller declared they need, and
    it is reported as a budget either way.
    """
    sigma = state["noise"]["sigma"]
    declared = float(state["spec"].value("min_feature_size"))
    recoverable = _FEATURE_SIGMA_FLOOR * sigma
    state["record"]["feature_scale"] = {
        "recoverable_feature_size": recoverable,
        "min_feature_size": declared,
        "margin": declared / recoverable if recoverable > 0.0 else math.inf,
    }
    if recoverable >= declared:
        return _refusal(
            "feature-scale-below-noise",
            {"recoverable_feature_size": recoverable, "min_feature_size": declared, "sigma": sigma},
            "The smallest feature this scan can separate from its neighbours is larger than the "
            "smallest feature you declared you need. Rescan at higher fidelity, or declare a "
            "min_feature_size this scan can actually support -- the record states both numbers.",
        )
    return None


def _stage_normals(state: dict[str, Any]) -> dict[str, Any] | None:
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    sigma = state["noise"]["sigma"]
    sizing = _neighbourhood_radius(sigma, state["spec"], topo)
    # A grid whose cell matches the query radius keeps every neighbourhood scan
    # to its 27 surrounding cells.
    grid = _Grid(mesh.vertices, state["live_points"], max(sizing["h"], 1e-12))
    normals, edge_adjacent, patches = _estimate_normals(
        mesh, topo, grid, state["live_points"], sizing["h"], state["noise"]["surface_scale"]
    )
    state["normals"] = sizing
    state["normal_vectors"] = normals
    state["edge_adjacent"] = edge_adjacent
    state["patches"] = patches
    if sizing["clamped_by_feature_size"]:
        state["flags"].append("angular-resolution-degraded")
    state["record"]["normals"] = {
        "neighbourhood_radius": sizing["h"],
        "neighbourhood_points": sizing["k_estimate"],
        "sigma_theta_deg": sizing["sigma_theta_deg"],
        "normal_alpha_deg_used": sizing["alpha_deg"],
        "clamped_by_feature_size": sizing["clamped_by_feature_size"],
        "clamped_by_edge_length": sizing["clamped_by_edge_length"],
        "edge_adjacent_points": sum(1 for value in edge_adjacent if value),
        "unresolved_points": sum(1 for index in state["live_points"] if normals[index] is None),
        "note": (
            "Trimmed PCA over a radius derived from the measured noise, not a per-triangle normal. "
            "sigma_theta is the achieved angular noise; the agreement half-angle widens to match "
            "when the feature-size clamp prevents reaching the target."
        ),
    }
    return None


def _stage_curvature(state: dict[str, Any]) -> dict[str, Any] | None:
    frame = _estimate_curvature(
        state["mesh"],
        state["topology"],
        state["normal_vectors"],
        state["patches"],
        state["live_points"],
        state["normals"]["h"],
        state["noise"]["sigma"],
        float(state["spec"].value("curvature_dead_zone_sigmas")),
    )
    frame.edge_adjacent = state["edge_adjacent"]
    state["frame"] = frame
    histogram: dict[str, int] = {name: 0 for name in sorted(CURVATURE_CLASSES)}
    for index in state["live_points"]:
        histogram[frame.curvature_class[index]] += 1
    state["record"]["curvature"] = {
        "sigma_kappa": frame.sigma_kappa,
        "histogram": histogram,
        "note": (
            "Besl-Jain HK signs with noise-sized dead zones. Ranks which primitive kinds are worth "
            "constructing per seed and explains unclaimed regions; never an acceptance gate, "
            "because curvature at scan noise is not accurate enough to be one."
        ),
    }
    return None


def _stage_detection(state: dict[str, Any]) -> dict[str, Any] | None:
    state["detected"] = _detect(state)
    state["record"]["detection"] = {
        "candidate_rounds": state.get("candidate_rounds", 0),
        "detected": [
            {"kind": d.kind, "point_count": len(d.points)} for d in state["detected"]
        ],
    }
    return None


def _stage_segmentation(state: dict[str, Any]) -> dict[str, Any] | None:
    detected: list[_Detected] = state["detected"]
    labels = _label_triangles(state, detected)
    topo: _Topology = state["topology"]
    groups: dict[int, list[int]] = {}
    for index in topo.valid:
        groups.setdefault(labels[index], []).append(index)
    state["labels"] = labels
    state["regions_by_label"] = groups
    state["record"]["segmentation"] = {
        "method": "Potts energy minimized by ICM over triangles, then connectivity enforced",
        "labelled_triangles": sum(len(v) for k, v in groups.items() if k >= 0),
        "unclaimed_triangles": len(groups.get(-1, [])),
    }
    return None


def _stage_disproof(state: dict[str, Any]) -> dict[str, Any] | None:
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    spec: DetectionSpec = state["spec"]
    detected: list[_Detected] = state["detected"]
    groups: dict[int, list[int]] = state["regions_by_label"]
    surface_scale = state["noise"]["surface_scale"]
    grid: _Grid = state["grid"]
    gates = spec.fit_gates()

    regions: list[dict[str, Any]] = []
    plane_baseline: float | None = None
    prepared: list[tuple[int, list[int], list[int], PrimitiveFit]] = []
    for label in sorted(k for k in groups if k >= 0):
        triangles = sorted(groups[label])
        if len(triangles) < _MIN_REGION_TRIANGLES:
            continue
        point_indices = sorted({v for t in triangles for v in mesh.triangles[t]})
        if len(point_indices) < _MIN_REGION_POINTS:
            continue
        points = [mesh.vertices[i] for i in point_indices]
        # Seeded with the axis detection already established. Re-deriving it from
        # the principal axes discards evidence the pipeline paid for, and on a
        # surface of revolution whose points form a band the principal axes are a
        # poor start -- which is exactly when the seed matters.
        fit = fit_primitive(
            points,
            detected[label].kind,
            seed_axis=detected[label].parameters.get("axis_direction"),
            **gates,
        )
        prepared.append((label, triangles, point_indices, fit))
        if fit.accepted and fit.kind == "plane":
            structure = _moran_i(list(_residuals(fit.kind, fit.parameters, points)), point_indices, topo)
            if structure is not None and (plane_baseline is None or structure["z"] < plane_baseline):
                plane_baseline = structure["z"]

    for label, triangles, point_indices, fit in prepared:
        points = [mesh.vertices[i] for i in point_indices]
        area = sum(topo.areas[t] for t in triangles)
        support: dict[str, Any] = dict(fit.support)
        checked: list[str] = list(support.get("checked", ()))
        support["checked"] = checked
        rejection = fit.rejection
        accepted = fit.accepted

        if accepted:
            residuals = list(_residuals(fit.kind, fit.parameters, points))
            passed, measured = _support_floors(fit, points, spec, topo.median_edge)
            support.update(measured)
            if not passed:
                accepted, rejection = False, (
                    f"support floors: this {fit.kind} is supported by too narrow a span of surface "
                    f"for its parameters to be determined ({measured})."
                )
            else:
                checked.append("support-span-floor")

            if accepted:
                # A test has no power against residuals that sit an order of
                # magnitude inside the measurement noise, and on an exact
                # synthetic fit it would be reading float noise. Say so rather
                # than pass or fail on it -- and do not claim the check in
                # `checked`, because it did not run.
                power_floor = max(_BAND_FLOOR_RATIO * fit.extent, 0.1 * surface_scale)
                structure = (
                    _moran_i(residuals, point_indices, topo)
                    if fit.rms_residual > power_floor
                    else None
                )
                if structure is None:
                    support["moran_z"] = None
                    support["moran_unavailable_reason"] = (
                        "residuals are below the measurement noise, so a spatial-autocorrelation "
                        "test has no power here"
                        if fit.rms_residual <= power_floor
                        else "too few connected inliers for the variance formula to mean anything"
                    )
                n_eff = float(len(points))
                if structure is not None:
                    support["moran_z"] = structure["z"]
                    support["moran_i"] = structure["i"]
                    # First-order n_eff inflation for correlated residuals: an
                    # AR(1)-style patch, not a derivation, and conservative
                    # defaults are what keep it honest (spec 7.3, 12.3).
                    correlation = max(0.0, min(0.95, structure["i"]))
                    n_eff = max(
                        float(_FREE_PARAMETERS[fit.kind] + 1),
                        len(points) * (1.0 - correlation) / (1.0 + correlation),
                    )
                    cap = float(spec.value("moran_z_max"))
                    if plane_baseline is not None:
                        cap = max(cap, plane_baseline + float(spec.value("moran_baseline_slack")))
                    support["moran_z_cap"] = cap
                    if structure["z"] > cap:
                        accepted, rejection = False, (
                            f"residual structure: Moran's I z = {structure['z']:.4g} on the mesh "
                            f"graph exceeds {cap:.4g}; the residuals agree with their neighbours in "
                            "sign over whole bands, which is the wrong primitive with a flattering "
                            "RMS."
                        )
                support["n_eff"] = n_eff
                if accepted:
                    structured, coordinate, magnitude = _directional_bins(
                        fit,
                        points,
                        residuals,
                        surface_scale,
                        float(spec.value("directional_bin_sigmas")),
                    )
                    support["directional_structure"] = magnitude
                    support["directional_coordinate"] = coordinate
                    if structured:
                        accepted, rejection = False, (
                            f"residual structure: the per-bin mean residual is systematically "
                            f"signed along the {coordinate} coordinate at {magnitude:.4g} standard "
                            "errors over adjacent bins."
                        )
                    elif structure is not None:
                        checked.append("residual-structure")

            if accepted:
                held = _blocked_heldout(fit, point_indices, mesh, grid, spec)
                if held is None:
                    accepted, rejection = False, (
                        f"held-out residual: refitting this {fit.kind} on a spatially blocked half "
                        "of its points produced no fit, so it does not survive being asked for half "
                        "the evidence."
                    )
                else:
                    support.update(held)
                    if held["ratio"] > float(spec.value("heldout_ratio_max")):
                        accepted, rejection = False, (
                            f"held-out residual {held['heldout_rms']:.6g} is {held['ratio']:.4g}x "
                            f"the in-sample residual; the fit is over-parameterized for the "
                            "evidence."
                        )
                    else:
                        checked.append("heldout-residual")

            if accepted:
                earned, detail = _parsimony(fit, points, spec, support.get("n_eff", len(points)))
                support.update(detail)
                if not earned:
                    accepted, rejection = False, (
                        f"parsimony: a {detail.get('parsimony_loser')} explains these points as "
                        "well as this "
                        f"{fit.kind}, and the F test does not justify the extra parameters."
                    )
                else:
                    checked.append("nested-kind-parsimony")

        if not accepted and fit.accepted and fit.kind in _RICHER_KINDS:
            promoted = _promote(fit, points, spec, support.get("n_eff", float(len(points))))
            if promoted is not None:
                fit, accepted, rejection = promoted, True, None
                support = dict(fit.support)
                checked = list(support.get("checked", ()))
                support["checked"] = checked
                support["promoted_from"] = detected[label].kind
                checked.append("kind-promotion")

        uncertainty: dict[str, float] = {}
        if accepted:
            uncertainty = parameter_uncertainty(
                fit, points, n_eff=support.get("n_eff", float(len(points)))
            )
            failure = _uncertainty_gate(uncertainty, fit, spec)
            if failure is not None:
                accepted, rejection = False, failure
            else:
                checked.append("parameter-uncertainty")

        region_hash = _region_hash(mesh.dump_sha256, triangles)
        recorded = PrimitiveFit(
            kind=fit.kind,
            accepted=accepted,
            rms_residual=fit.rms_residual,
            relative_residual=fit.relative_residual,
            extent=fit.extent,
            parameters=dict(fit.parameters),
            rejection=rejection,
            support=support,
            uncertainty=uncertainty,
        )
        lo, hi = _extent_box(points)
        regions.append(
            {
                "region_hash": region_hash,
                "triangle_indices": sorted(mesh.dump_triangles[t] for t in triangles),
                "inlier_vertex_indices": sorted(
                    node for i in point_indices for node in mesh.node_sources[i]
                ),
                "welded_triangle_indices": triangles,
                "triangle_count": len(triangles),
                "point_count": len(point_indices),
                "area": area,
                "area_fraction": area / topo.total_area if topo.total_area > 0.0 else 0.0,
                "bounding_box": [list(lo), list(hi)],
                "detected_kind": detected[label].kind,
                "fit": recorded.to_dict(),
                "accepted": accepted,
                "dominant_curvature": _dominant_class(state["frame"], point_indices),
                "orientation": _region_orientation(fit, triangles, mesh, topo, state),
            }
        )

    state["regions"] = regions
    state["record"]["disproof"] = {
        "moran_plane_baseline_z": plane_baseline,
        "note": (
            "Every accepted fit survived support floors, Moran's I on the mesh graph, a spatially "
            "blocked held-out refit, and a nested-kind parsimony F test. A consensus set that "
            "failed one is kept with the gate that killed it, never dropped."
        ),
    }
    return None


def _mesh_orientation(mesh: WeldedMesh, topo: _Topology) -> dict[str, Any]:
    """Is this mesh's winding outward, and is it closed enough for the question to mean anything?

    The signed volume of a closed, consistently wound mesh is positive when the
    winding faces outward. On an open or inconsistently wound mesh the number is
    meaningless, and this says so rather than returning a sign nobody should
    trust -- because the consumer of this field decides whether a cylinder is a
    bore or a boss, and guessing there is exactly the invention this skill exists
    to prevent.
    """
    closed = topo.boundary_edges == 0 and topo.non_manifold_edges == 0
    volume = 0.0
    for index in topo.valid:
        a, b, c = mesh.triangles[index]
        pa, pb, pc = mesh.vertices[a], mesh.vertices[b], mesh.vertices[c]
        volume += _dot(pa, _cross(pb, pc)) / 6.0
    return {
        "closed": closed,
        "signed_volume": volume,
        "winding": ("outward" if volume > 0.0 else "inward") if closed and volume != 0.0 else None,
        "unavailable_reason": (
            None
            if closed and volume != 0.0
            else "the mesh is not closed and consistently wound, so its winding carries no "
            "inside/outside information"
        ),
    }


def _region_orientation(
    fit: PrimitiveFit,
    triangles: Sequence[int],
    mesh: WeldedMesh,
    topo: _Topology,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Which way this region's surface faces -- the evidence a bore needs to be a bore.

    ``material_side`` is the answer downstream wants: ``outside`` means the solid
    is on the far side of the surface from the primitive's outward normal (a
    boss), ``inside`` means the surface wraps material (a bore). It is ``None``
    whenever the mesh's own winding does not license the claim.
    """
    global_orientation = state.setdefault("mesh_orientation", _mesh_orientation(mesh, topo))
    if not fit.accepted:
        # A rejected fit has no surface, so it has no side. Reporting one would
        # be describing geometry that was refused.
        return {
            "surface_normal_agreement": None,
            "mesh_winding": global_orientation["winding"],
            "mesh_closed": global_orientation["closed"],
            "material_side": None,
            "unavailable_reason": "the fit was rejected, so it has no surface to take a side of",
        }
    agree = 0
    total = 0
    for index in triangles:
        surface = _surface_normal(fit.kind, fit.parameters, topo.centroids[index])
        if surface is None:
            continue
        total += 1
        if _dot(surface, topo.tri_normals[index]) > 0.0:
            agree += 1
    fraction = (agree / total) if total else None
    # The area-weighted winding normal is the surface's own outward direction,
    # and for a plane it is the whole answer: a plane encloses nothing, so it has
    # an outward direction but no inside.
    outward = (0.0, 0.0, 0.0)
    for index in triangles:
        outward = _add(outward, _scale(topo.tri_normals[index], topo.areas[index]))
    outward_unit = _unit(outward)
    material_side: str | None = None
    reason = global_orientation["unavailable_reason"]
    if fit.kind == "plane":
        reason = "a plane encloses no volume; its outward direction is reported instead"
    elif global_orientation["winding"] is not None and fraction is not None:
        # A curved primitive's own normal points away from its axis or centre.
        # When the winding normal agrees, material is behind the surface (a
        # boss); when it opposes, the surface wraps material (a bore).
        outward_winding = global_orientation["winding"] == "outward"
        agrees = fraction >= 0.5
        material_side = "outside" if agrees == outward_winding else "inside"
    return {
        "surface_normal_agreement": fraction,
        "outward_normal": list(outward_unit) if outward_unit is not None else None,
        "mesh_winding": global_orientation["winding"],
        "mesh_closed": global_orientation["closed"],
        "material_side": material_side,
        "unavailable_reason": reason,
    }


def _promote(
    fit: PrimitiveFit, points: Sequence[Vec3], spec: DetectionSpec, n_eff: float
) -> PrimitiveFit | None:
    """One chance at the richer kind that contains a refused one, on the same points.

    Returns the promoted fit only when it is accepted by the exact fitter's own
    gates *and* the nested-kind F test licenses its extra parameters. A promotion
    that cannot clear parsimony is not a promotion, it is a bigger model fitted
    to the same evidence.
    """
    gates = spec.fit_gates()
    for kind in _RICHER_KINDS[fit.kind]:
        candidate = fit_primitive(points, kind, **gates)
        if not candidate.accepted:
            continue
        if candidate.rms_residual >= fit.rms_residual:
            continue
        earned, _detail = _parsimony(candidate, points, spec, n_eff)
        if earned:
            return candidate
    return None


def _dominant_class(frame: _PointFrame, indices: Sequence[int]) -> str:
    histogram: dict[str, int] = {}
    for index in indices:
        name = frame.curvature_class[index]
        histogram[name] = histogram.get(name, 0) + 1
    if not histogram:
        return "ambiguous"
    return max(sorted(histogram), key=lambda k: histogram[k])


def _region_hash(dump_sha256: str, indices: Sequence[int]) -> str:
    """Geometric region identity, bound to the dump it was derived from.

    Never a Fusion face-group temp id: those are temp ids and are not stable
    across sessions or edits. Re-deriving identity costs one hash and removes the
    dependency entirely.
    """
    payload = dump_sha256 + "|" + ",".join(str(i) for i in sorted(indices))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _stage_face_group_agreement(state: dict[str, Any]) -> dict[str, Any] | None:
    """Fusion's own grouping as a *checked* input, never a trusted one."""
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    regions: list[dict[str, Any]] = state["regions"]
    record = state["record"]
    if mesh.face_groups is None:
        record["face_groups"] = {
            "present": False,
            "agreement": None,
            "unavailable_reason": "the dump reported no triangleFaceGroupTempIds",
        }
        return None
    distinct = sorted({mesh.face_groups[i] for i in topo.valid})
    if len(distinct) < 2:
        record["face_groups"] = {
            "present": True,
            "group_count": len(distinct),
            "degenerate": True,
            "agreement": None,
            "unavailable_reason": (
                "a grouping that puts every triangle in one region is degenerate, not segmentation"
            ),
        }
        return None
    overlap: dict[tuple[str, int], float] = {}
    assigned = 0.0
    for region in regions:
        for index in region["triangle_indices"]:
            key = (region["region_hash"], mesh.face_groups[index])
            overlap[key] = overlap.get(key, 0.0) + topo.areas[index]
            assigned += topo.areas[index]
    used_regions: set[str] = set()
    used_groups: set[int] = set()
    matched = 0.0
    # ponytail: greedy matching, not Hungarian. It is a lower bound on the
    # optimal-assignment agreement, so it can understate but never overstate.
    for (region_hash, group), area in sorted(overlap.items(), key=lambda kv: (-kv[1], kv[0])):
        if region_hash in used_regions or group in used_groups:
            continue
        used_regions.add(region_hash)
        used_groups.add(group)
        matched += area
    record["face_groups"] = {
        "present": True,
        "group_count": len(distinct),
        "degenerate": False,
        "agreement": (matched / assigned) if assigned > 0.0 else None,
        "agreement_method": "greedy overlap matching, area-weighted; a lower bound on optimal",
        "unavailable_reason": None,
    }
    return None


def _stage_coverage(state: dict[str, Any]) -> dict[str, Any] | None:
    topo: _Topology = state["topology"]
    mesh: WeldedMesh = state["mesh"]
    regions: list[dict[str, Any]] = state["regions"]
    record = state["record"]
    frame: _PointFrame = state["frame"]

    accepted = [r for r in regions if r["accepted"]]
    _mark_fillet_candidates(accepted, mesh, topo)
    covered = sum(r["area"] for r in accepted) / topo.total_area if topo.total_area > 0.0 else 0.0

    claimed = {t for r in regions for t in r["triangle_indices"]}
    unclaimed = [t for t in topo.valid if t not in claimed]
    record["regions"] = regions
    record["covered_area_fraction"] = covered
    record["unfitted_regions"] = [
        {
            "region_hash": r["region_hash"],
            "area_fraction": r["area_fraction"],
            "detected_kind": r["detected_kind"],
            "dominant_curvature": r["dominant_curvature"],
            "failed_gate": r["fit"].get("rejection"),
        }
        for r in regions
        if not r["accepted"]
    ]
    record["unclaimed"] = _unclaimed_components(unclaimed, mesh, topo, frame)
    floor = float(state["spec"].value("min_covered_area_fraction"))
    if covered < floor:
        return _refusal(
            "segmentation-coverage-insufficient",
            {
                "covered_area_fraction": covered,
                "min_covered_area_fraction": floor,
                "unclaimed_signatures": sorted(
                    {c["dominant_curvature"] for c in record["unclaimed"]["components"]}
                ),
            },
            "Too little of the part survived disproof to rebuild from. The unclaimed components "
            "carry their curvature signatures: a saddle-dominated remainder means no supported "
            "primitive fits a saddle, which is a shape answer, not a threshold one.",
        )
    return None


def _mark_fillet_candidates(
    accepted: Sequence[dict[str, Any]], mesh: WeldedMesh, topo: _Topology
) -> None:
    """A torus adjacent to exactly two accepted primary regions is a fillet.

    Emitted downstream as a fillet feature on the shared edge with radius equal
    to the minor radius -- parametric and editable -- rather than as torus
    surface geometry, which Fusion has no editable home for. A torus that is not
    in that adjacency pattern (an O-ring groove, say) is a torus fit and nothing
    more, and says so.
    """
    owner: dict[int, str] = {}
    for region in accepted:
        for index in region["triangle_indices"]:
            owner[index] = region["region_hash"]
    for region in accepted:
        neighbours: set[str] = set()
        for index in region["triangle_indices"]:
            for other in topo.tri_neighbours[index]:
                target = owner.get(other)
                if target is not None and target != region["region_hash"]:
                    neighbours.add(target)
        region["adjacent_regions"] = sorted(neighbours)
        primaries = sorted(
            n for n in neighbours
            if next(r["fit"]["kind"] for r in accepted if r["region_hash"] == n) != "torus"
        )
        region["fillet_candidate"] = region["fit"]["kind"] == "torus" and len(primaries) == 2
        if region["fillet_candidate"]:
            region["fillet"] = {
                "radius": region["fit"]["parameters"]["minor_radius"],
                "between": primaries,
                "emission": "filletFeatures on the shared edge, radius = the torus minor radius",
            }


def _unclaimed_components(
    unclaimed: Sequence[int], mesh: WeldedMesh, topo: _Topology, frame: _PointFrame
) -> dict[str, Any]:
    """Unclaimed is a first-class outcome, and it says what it looks like.

    "Saddle signature, and no supported primitive fits a saddle" is a refusal
    message a user can act on. "Nothing fit" is not.
    """
    members = set(unclaimed)
    seen: set[int] = set()
    components: list[dict[str, Any]] = []
    total = 0.0
    for start in unclaimed:
        if start in seen:
            continue
        component = [start]
        seen.add(start)
        frontier = [start]
        while frontier:
            nxt: list[int] = []
            for index in frontier:
                for other in topo.tri_neighbours[index]:
                    if other in members and other not in seen:
                        seen.add(other)
                        component.append(other)
                        nxt.append(other)
            frontier = nxt
        area = sum(topo.areas[i] for i in component)
        total += area
        points = sorted({v for t in component for v in mesh.triangles[t]})
        lo, hi = (
            _extent_box([mesh.vertices[i] for i in points]) if points else ((0.0, 0.0, 0.0),) * 2
        )
        components.append(
            {
                "triangle_count": len(component),
                "area_fraction": area / topo.total_area if topo.total_area > 0.0 else 0.0,
                "bounding_box": [list(lo), list(hi)],
                "dominant_curvature": _dominant_class(frame, points),
            }
        )
    components.sort(key=lambda c: (-c["area_fraction"], c["triangle_count"]))
    return {
        "triangle_count": len(unclaimed),
        "area_fraction": total / topo.total_area if topo.total_area > 0.0 else 0.0,
        "components": components,
    }


def _extent_box(points: Sequence[Vec3]) -> tuple[Vec3, Vec3]:
    return (
        (min(p[0] for p in points), min(p[1] for p in points), min(p[2] for p in points)),
        (max(p[0] for p in points), max(p[1] for p in points), max(p[2] for p in points)),
    )


def _stage_runners() -> dict[str, Callable[[dict[str, Any]], dict[str, Any] | None]]:
    # Resolved from module globals at call time, so a test can stub one stage.
    return {
        "triangle-budget": _stage_triangle_budget,
        "weld": _stage_weld,
        "topology": _stage_topology,
        "noise-scale": _stage_noise_scale,
        "feature-scale": _stage_feature_scale,
        "normals": _stage_normals,
        "curvature": _stage_curvature,
        "detection": _stage_detection,
        "segmentation": _stage_segmentation,
        "disproof": _stage_disproof,
        "face-group-agreement": _stage_face_group_agreement,
        "coverage": _stage_coverage,
    }


# --------------------------------------------------------------------------
# the fit record
# --------------------------------------------------------------------------


def fit_regions(dump: MeshDump, spec: DetectionSpec) -> dict[str, Any]:
    """Detect primitives in ``dump`` and return the fit record U3 consumes.

    Refusal is a returned record with ``refusal`` set, ``regions`` empty and a
    named alternative -- not an exception. It is a declared outcome of the run,
    and the caller decides what to do about it.
    """
    record: dict[str, Any] = {
        "record_version": RECORD_VERSION,
        "dump_sha256": dump.sha256,
        # The dump reader normalizes to millimetres, and every length in this
        # record -- radii, spans, uncertainties, bounding boxes -- is in them.
        "units": "mm",
        "manifest_sha256": dump.metadata.get("manifest_sha256"),
        "mesh_source_sha256": dump.metadata.get("mesh_source_sha256"),
        "thresholds": spec.to_dict(),
        "regions": [],
        "unfitted_regions": [],
        "unclaimed": {"triangle_count": 0, "area_fraction": 0.0, "components": []},
        "covered_area_fraction": 0.0,
        "flags": [],
        "checked": [],
        "refusal": None,
    }
    state: dict[str, Any] = {
        "dump": dump,
        "spec": spec,
        "record": record,
        "regions": [],
        "flags": [],
    }

    checked: list[str] = []
    runners = _stage_runners()
    for stage in STAGES:
        try:
            refusal = runners[stage](state)
        except Exception as exc:  # noqa: BLE001 - naming the stage is the point
            record["refusal"] = _refusal(
                "fit-record-stage-failed",
                {"stage": stage, "error": f"{type(exc).__name__}: {exc}"},
                "This is a defect, not a property of the mesh. The record names the stage that "
                "failed and stops; no geometry is produced from a partial run.",
            )
            break
        if refusal is not None:
            record["refusal"] = refusal
            break
        # Appended here, and only here: after the stage ran and returned no
        # refusal. A stage that raises never reaches this line (R12).
        checked.append(stage)

    record["checked"] = checked
    record["flags"] = sorted(set(state["flags"]))
    if record["refusal"] is not None:
        record["regions"] = []
        record["unfitted_regions"] = []
        record["covered_area_fraction"] = 0.0
    return record
