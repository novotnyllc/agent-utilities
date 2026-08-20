"""The disproof-gated fit record, over Fusion's own face-group segmentation.

Host-side crux of the mesh-to-parametric pipeline. It takes the hash-bound dump
``mesh_dump`` reads, welds it under a declared tolerance, measures its own noise,
fits an analytic primitive to each of the dump's face groups, tries to *falsify*
every one, and emits the fit record U3 consumes. It needs no Fusion, imports no
``adsk``, and is provable in full under ``scripts/test.sh`` against synthetic
meshes with known analytic answers. That total offline testability is why the
architecture puts the numerics here, so nothing in this module may acquire a
live-session dependency.

Implements ``docs/plans/2026-08-19-007-research-reconstruction-algorithms.md``
sections 2-4 and 10. The mathematics and its citations live there; this file
carries the reasons a reader of the *code* needs.

**Where the regions come from, and why they no longer come from here.** This
module used to segment the mesh itself: Efficient RANSAC (Schnabel/Wahl/Klein,
CGF 26:2, 2007) over oriented points, then a Potts energy minimized by ICM over
triangles. It was measured against Fusion's own ``MeshGenerateFaceGroups`` on
real production STLs and lost outright -- on POD-A2-BASE it claimed 8 regions
and 27.4% of the area and found *zero* cylinders, where Fusion's grouping under
``AccurateGenerateFaceGroupsType`` returned 151 regions covering 100%, and our
exact fitters then accepted a fit on all 1,908 groups across 11 parts. So the
segmentation layer is deleted and the regions arrive in the dump, one face-group
id per triangle. ``references/unsupported.md`` records the measurement.

What does *not* move is the judgement. Fusion has no opinion about whether a fit
is justified, and a grouping is not a fit: every region it delivers still passes
support floors, residual structure by Moran's I on the mesh graph, a spatially
blocked held-out refit, a nested-kind parsimony F test, and the parameter
uncertainty gate. A fit that fails is recorded with the gate that killed it,
never dropped, and a dump that carries no grouping is refused rather than
segmented by a fallback nobody measured.

Refusal is therefore about information, not thresholds: ``feature-scale-below-noise``
says the recoverable feature size, about ten sigma, has risen above the smallest
feature the caller declared they need -- a budget the caller can check before
asking -- and ``face-groups-absent`` says the segmentation stage was never run.

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

Determinism: nothing here samples, iteration is over sorted keys or index order,
and region identity is a hash of sorted triangle indices bound to the dump --
never a Fusion face-group temp id, which is a *temp* id and is not stable across
sessions. The same dump gives a bit-identical record.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import struct
from typing import Any, Callable, Iterable, Mapping, Sequence

from .manifest import ValidationIssue, _in_closed_set, _reject_unknown_fields
from .mesh_dump import MeshDump
from .mesh_fitting import (
    PrimitiveFit,
    Vec3,
    _add,
    _angle_deg,
    _centroid,
    _covariance,
    _cross,
    _dot,
    _extent,
    _fit_circle_2d,
    _frame,
    _length,
    _passed,
    _raw_fit,
    _residuals,
    _rms,
    _scale,
    _solve,
    _sub,
    _surface_normal,
    _symmetric_eigen,
    _unit,
    fit_face_group,
    fit_primitive,
    parameter_uncertainty,
    region_motion_moments,
)


RECORD_VERSION = 1

#: Closed refusal vocabulary. A refusal is a declared outcome with a named
#: reason and a stated alternative -- never an exception the caller guesses at.
REFUSAL_REASONS = {
    "triangle-budget-exceeded",
    "mesh-degenerate",
    "mesh-not-welded",
    "feature-scale-below-noise",
    "face-groups-absent",
    "segmentation-coverage-insufficient",
    "fit-record-stage-failed",
}

#: Flags: measured facts that qualify every verdict downstream but do not stop
#: the run. ``noise-model-inconsistent`` says the two independent noise
#: estimators disagreed by more than 2x, so the iid assumption every statistical
#: gate is calibrated against does not hold and its verdicts are approximate;
#: ``angular-resolution-degraded`` says the normals are too coarse to separate
#: the features the caller asked for. A declared flag no stage can raise reads
#: as a check this module performs and does not, so ``normals-unoriented`` was
#: deleted rather than left standing: the mesh's winding is reported per region
#: in ``orientation`` and per part in ``mesh_orientation``, each with the reason
#: it is unavailable, which is the same fact with a measurement behind it.
RECORD_FLAGS = {"noise-model-inconsistent", "angular-resolution-degraded"}

#: Flags a *region* can carry, as opposed to the record. Declared here so the
#: token is greppable from the one place that sets it.
BOUNDARY_CIRCLE_DISAGREES = "boundary-circle-disagrees"
REGION_FLAGS = {BOUNDARY_CIRCLE_DISAGREES}

#: The two measurement regimes, plus the caller's "decide it from the mesh".
#: An exact tessellation exported from CAD has vertices on the analytic surface
#: to float precision and sparse; a scan has dense noisy ones. Assuming a scan
#: everywhere is what made ``noise-model-inconsistent`` fire on every noise-free
#: mesh: the two estimators are *meant* to disagree there, because one absorbs
#: curvature and the other measures the facet turn angle, and on a mesh with no
#: noise the whole of that difference is discretization.
TESSELLATION_REGIMES = {"auto", "tessellation", "scan"}

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
    "face-groups",
    "disproof",
    "coverage",
)

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
# Estimator C, the form-error estimator: a plane fitted over a *feature-sized*
# patch rather than a facet-sized one. Both estimators above are facet-to-facet
# by construction -- 16 nearest points is about 2.1 median edges, and a quadric
# over that span absorbs anything smoother than the span itself -- so a surface
# that is locally smooth and globally wavy reads as noise-free to both. On the
# first real structured-light capture the pipeline saw, they reported
# sigma = 0.0054 mm while the part's own genuinely-flat board faces carried a
# plane-fit rms of 0.033-0.076 mm. That gap is not measurement noise and it is
# not discretization: it is *form error*, the surface's departure from the shape
# it is nominally, and it is the dominant error on a scan.
#
# The smallest rung is one feature across, which is the same span
# `_neighbourhood_radius` already refuses to exceed (`ceiling = feature / 2.0`)
# and for the same reason: at that radius the patch describes one side of one
# feature. The ladder doubles from there because form error is a function of
# scale and a single number cannot be one -- a part whose faces are flat at 2 mm
# and wavy at 10 mm carries both, and the gate judging a 10 mm region needs the
# 10 mm answer. Measured on the 524k-triangle capture with min_feature_size =
# 1.6 mm, confined to face groups and taken over the surfaces that span each
# rung: 0.0032 mm over 1000 surfaces at 0.8 mm, 0.0043 over 288 at 1.6, and
# 0.0106 over 17 at 3.2. The ladder stops there because fewer than four
# surfaces on this part span 12.8 mm, and a rung measured on three surfaces is
# three surfaces' shape rather than the part's form error.
_SIGMA_FORM_PATCH_FRACTION = 0.5
_SIGMA_FORM_LADDER_FACTOR = 2.0   # one octave per rung: the part is asked about scales, not about a grid
_SIGMA_FORM_CENTRES_PER_SURFACE = 30
_SIGMA_FORM_MAX_SURFACE_POINTS = 20000
#: A rung measured on fewer surfaces than this is one surface's shape, not the
#: part's form error, and the ladder stops rather than reporting it.
_SIGMA_FORM_MIN_SURFACES = 4
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


#: The coarsest storage precision a caller may declare, relative to the part's
#: own extent. Three orders above float32's own 1.2e-07 leaves room for a coarser
#: format nobody has met yet; a decade above this is 1 part in 1000 of the part,
#: at which the "precision floor" is larger than the features being fitted and
#: every statistical gate is judging the declaration instead of the mesh.
_MAX_VERTEX_PRECISION_REL = 1e-04


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
    # kind selection over a face group
    "cylinder_normal_perpendicular_deg": (
        "float",
        lambda v: 0.0 < v < 90.0,
        "how far a facet normal may sit from perpendicular to a cylinder's axis and still be "
        "evidence of a cylinder rather than the sphere that fits the same vertices",
    ),
    "max_fillet_arc_deg": (
        "float",
        lambda v: 0.0 < v <= 360.0,
        "how much arc a cylindrical region may sweep and still be an edge round rather than a "
        "bore or a boss",
    ),
    "regime": (
        "choice",
        lambda v: v in TESSELLATION_REGIMES,
        "which measurement regime this mesh is in -- 'auto' to decide from the mesh's own "
        "evidence, or 'tessellation'/'scan' when the caller knows what they captured",
    ),
    "vertex_precision_rel": (
        "float",
        lambda v: 0.0 < v <= _MAX_VERTEX_PRECISION_REL,
        "the relative precision the vertex coordinates are *stored* at -- a binary STL holds "
        "float32, so about 1.2e-07 of the coordinate magnitude -- below which a residual is "
        "quantization rather than geometry. Bounded above at 1e-04 because this floors sigma: "
        "declared at 1e-04 a 100 mm part carries a 0.01 mm noise floor, which is already the "
        "layer height of a printed feature, and every gate above it stops testing the geometry "
        "and starts testing the declaration. The measured answer is recorded beside it in "
        "noise.vertex_precision, from a float32 round trip over the coordinates themselves",
    ),
    "tessellation_sigma_over_extent": (
        "float",
        _positive,
        "how small the quadric-residual noise must be, relative to the part extent, before the "
        "vertices read as exact rather than measured",
    ),
    "min_normal_axis_eigengap": (
        "float",
        _positive,
        "how much of the facet-normal spectrum must sit away from the axis direction before the "
        "normals determine an axis the vertices cannot",
    ),
    "normal_sigma_theta_floor_deg": (
        "float",
        _non_negative,
        "the measurement floor on facet-normal direction: how far a normal may be wrong on a mesh "
        "whose vertices are exact, so a noise-free tessellation does not report zero uncertainty",
    ),
    "min_cylinder_normal_directions_per_turn": (
        "float",
        _positive,
        "how many distinct facet-normal directions a full turn of genuine cylinder must carry "
        "before a face group is a tessellated circle rather than a prism of planar walls whose "
        "corners happen to lie on one",
    ),
    "max_fillet_radius_rel_spread": (
        "float",
        _non_negative,
        "how far the radii along one chain of partial-arc cylinders may spread, relative to their "
        "mean, and still be one constant-radius fillet",
    ),
    "boundary_circle_sigmas": (
        "float",
        _positive,
        "how many joint sigmas a bore's own boundary circle may disagree with its fitted radius "
        "before the corroboration is recorded as a disagreement",
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
#: surface type. Never a veto and never a kind selector -- curvature at scan
#: noise is not accurate enough to be either. It says what an unfitted or
#: unclaimed region actually *looks* like, so the record can report "saddle, and
#: no supported primitive fits a saddle" rather than "nothing fit".
CURVATURE_CLASSES = {"flat", "ridge-valley", "peak-pit", "saddle", "ambiguous"}

#: The kinds that carry an axis and a radius, and can therefore be checked
#: against the circle their own group boundary traces.
_AXIS_KINDS = ("cylinder", "cone", "torus")

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
        if ok and kind == "choice":
            ok = isinstance(value, str)
        elif ok and kind == "int":
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
            values[name] = value if kind in ("int", "choice") else float(value)
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
    """Uniform grid over the point set: fixed-radius queries, and block parity.

    Spec 11.1 chooses a grid over a kd-tree because the queries here are all
    fixed-radius at a single scale and a grid is O(1) per query with no tree to
    build. Two survivors of the deleted RANSAC layer use it: neighbourhood
    normals (``near``) and the held-out gate's checkerboard split (``keys``).
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


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return 0.0
    mid = n // 2
    return ordered[mid] if n % 2 else 0.5 * (ordered[mid - 1] + ordered[mid])


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


def _sigma_form(mesh: WeldedMesh, topo: _Topology, spec: DetectionSpec) -> dict[str, Any]:
    """Estimator C: the surface's departure from flat, as a function of scale.

    Estimators A and B measure facet-to-facet noise.  Neither can see what a
    scanner mostly does wrong: a nominally flat face that is smooth everywhere
    and wavy across its span reads as noise-free to both, because both work
    inside a couple of median edges where it *is* flat.  This measures that --
    the RMS residual to a best-fit plane over a patch, at a ladder of patch radii
    starting at half the declared feature size and doubling.

    Two things this does that a naive version does not, both forced by
    measurement on the first real capture:

    * **the patch stays on one face group.**  A patch is a ball of vertices, and
      on a 1.6 mm board a ball of radius 0.8 mm centred on the top face contains
      the bottom face and the neighbouring components.  Sampled without that
      restriction the median patch RMS on the capture reads 0.0709 mm, and that
      number is not form error: it is one un-segmented face group holding 448,122
      of the mesh's 524,614 triangles, so 85% of the sampled patches are centred
      in it and straddle whatever it happens to contain.  Confined to a face
      group -- which is what the segmentation stage means by "one surface" -- the
      same statistic at the same radius reads 0.0035 mm.
    * **a rung is measured only on surfaces large enough to show it,** and
      aggregated as the median over *surfaces* rather than over patches.  A
      1.4 mm face group cannot report the form error at 3.2 mm; including it
      makes every rung above the median group's own size read that group's size
      instead of the part's waviness.  On the capture, the honest ladder is
      0.0037 mm at 0.8 mm, 0.0085 at 1.6, 0.0151 at 3.2, saturating there --
      form error that is real, and an order of magnitude below what the
      unconfined sample claims.

    The single ``sigma`` is the ladder read at the declared feature size, which
    is the number the record reports beside the other two estimators.  The table
    is what the structure gates actually read, through ``_form_error_at``, at
    each region's own extent -- because a region's residual has to be compared
    against the form error at *its* scale, and a part whose faces are flat at
    2 mm and wavy at 10 mm carries both.

    Cost is bounded by the sample counts, not by the mesh: a fixed number of
    patch centres per surface per rung, over a point set sub-sampled where a
    surface is denser than the estimate needs.
    """
    feature = float(spec.value("min_feature_size"))
    detail: dict[str, Any] = {
        "sigma": 0.0,
        "min_feature_size": feature,
        "median_edge_length": topo.median_edge,
        "scale_table": [],
        "unavailable_reason": None,
        "note": (
            "form error: the RMS departure from a best-fit plane over a patch confined to one face "
            "group, at a ladder of radii doubling from half the declared feature size. Each rung is "
            "measured only on the surfaces whose own extent spans it, and aggregated as the median "
            "over surfaces. The facet estimators cannot see this -- both work at facet scale, where "
            "a wavy surface is locally flat -- and on a measured surface it is what a residual "
            "inside it is made of. sigma is the ladder read at the declared feature size; the "
            "structure gates read the table at each region's own extent."
        ),
    }
    if feature <= 0.0 or mesh.face_groups is None:
        detail["unavailable_reason"] = (
            "the dump carries no face grouping, so there is no surface to confine a patch to and a "
            "patch would measure the part's geometry rather than its form"
            if mesh.face_groups is None
            else "a non-positive declared feature size"
        )
        return detail

    surfaces: list[tuple[list[int], float]] = []
    by_group: dict[int, list[int]] = {}
    for index in topo.valid:
        # `face_groups` is compressed to the *kept* triangles by `weld_dump`, so
        # it is addressed by the welded index like every other per-triangle
        # array here. `dump_triangles[index]` is the original index, which is
        # larger whenever welding collapsed anything earlier in the dump: it
        # reads the wrong group, and on the last kept triangle of a mesh with
        # any collapsed sliver it raises IndexError -- which the stage turns
        # into `fit-record-stage-failed` for the whole part.
        by_group.setdefault(mesh.face_groups[index], []).append(index)
    for label in sorted(by_group):
        triangles = by_group[label]
        if len(triangles) < _MIN_REGION_TRIANGLES:
            continue
        points = sorted({v for t in triangles for v in mesh.triangles[t]})
        if len(points) < _SIGMA_A_NEIGHBOURS:
            continue
        # A surface denser than the estimate needs is sub-sampled -- but only in
        # its *centres*. Thinning the point set itself thins the patches too: on
        # a 100 mm face thinned to 20,000 points a 0.8 mm patch holds a handful
        # of them, under `_SIGMA_A_NEIGHBOURS`, so every estimate on that
        # surface is skipped and the floor can go unavailable on the very parts
        # it was measured for. The neighbourhood keeps every point the scan
        # captured; the estimate converges long before a quarter of a million
        # *centres*, which is what the cap is for.
        centres = points
        if len(centres) > _SIGMA_FORM_MAX_SURFACE_POINTS:
            centres = centres[:: len(centres) // _SIGMA_FORM_MAX_SURFACE_POINTS]
        surfaces.append((points, centres, _extent([mesh.vertices[i] for i in points])))
    if not surfaces:
        detail["unavailable_reason"] = "no face group carries enough points for a plane residual"
        return detail

    alpha = float(spec.value("normal_alpha_deg"))
    radius = _SIGMA_FORM_PATCH_FRACTION * feature
    table: list[dict[str, Any]] = []
    while radius <= topo.extent:
        per_surface: list[float] = []
        curved = 0
        for points, centres, extent in surfaces:
            # A surface that does not span the rung cannot report it. Without
            # this every rung above the median surface's own size reports that
            # size instead of the part's waviness.
            if extent < 2.0 * radius:
                continue
            grid = _Grid(mesh.vertices, points, radius)
            step = max(1, len(centres) // _SIGMA_FORM_CENTRES_PER_SURFACE)
            estimates: list[float] = []
            normals: list[Vec3] = []
            for offset in range(0, len(centres), step):
                centre_point = mesh.vertices[centres[offset]]
                near = grid.near(mesh.vertices, centre_point, radius)
                if len(near) < _SIGMA_A_NEIGHBOURS:
                    continue
                patch = [mesh.vertices[i] for i in near]
                centre = _centroid(patch)
                _values, vectors = _symmetric_eigen(_covariance(patch, centre))
                normal = vectors[0]
                normals.append(normal)
                residuals = [_dot(_sub(p, centre), normal) for p in patch]
                estimates.append(math.sqrt(sum(r * r for r in residuals) / (len(patch) - 3)))
            if not estimates:
                continue
            # This is a *plane* residual, so on a curved surface it measures the
            # sagitta -- which is that surface's nominal shape, not its
            # departure from it. The module already says so for a tessellated
            # part; the same holds one level down, per surface, on a scan: a
            # scanned cylinder's own curvature is geometry, and pooling it into
            # a form-error floor would let a wrong primitive pass a gate this
            # floor inflates. A surface is admitted at this rung only when its
            # own patch normals stay inside the declared `normal_alpha_deg` --
            # the same angle at which this package calls two normals the same
            # normal. Patch normals rather than facet normals because a patch
            # normal is fitted over `_SIGMA_A_NEIGHBOURS` points and averages
            # the sampling noise down, and per rung rather than once because a
            # surface can be flat at one scale and curved at the next. The
            # comparison is over every *pair*, not against one reference: PCA
            # fixes a normal only up to sign, and `_angle_deg` is unoriented, so
            # a half-cylinder's far side would read as agreeing with its near
            # side against a single reference while some pair on it is at 90.
            if any(
                _angle_deg(normals[i], normals[j]) > alpha
                for i in range(len(normals))
                for j in range(i + 1, len(normals))
            ):
                curved += 1
                continue
            per_surface.append(_median(estimates))
        if len(per_surface) < _SIGMA_FORM_MIN_SURFACES:
            break
        table.append(
            {
                "radius": radius,
                "form_error": _median(per_surface),
                "surfaces": len(per_surface),
                "curved_surfaces_excluded": curved,
            }
        )
        radius *= _SIGMA_FORM_LADDER_FACTOR
    detail["scale_table"] = table
    if not table:
        detail["unavailable_reason"] = (
            f"fewer than {_SIGMA_FORM_MIN_SURFACES} face groups both span twice the smallest rung "
            f"({_SIGMA_FORM_PATCH_FRACTION * feature:.6g}) and stay flat across it to within the "
            f"declared normal_alpha_deg ({alpha:g}), so no rung is measured on enough surfaces to "
            "be a statement about the part rather than about its curvature"
        )
        return detail
    detail["sigma"] = _form_error_at(table, feature)
    return detail


def _form_error_at(table: Sequence[Mapping[str, Any]], extent: float) -> float:
    """The measured form error at ``extent``, by log-log interpolation of the ladder.

    Clamped at both ends rather than extrapolated. Below the smallest rung the
    answer is that rung: the facet estimators already own that scale and a form
    error extrapolated below where it was measured would be invented. Above the
    largest, the ladder stopped because no surface spanned the next rung, so the
    part has said nothing about larger scales and the last measurement stands.
    """
    if not table:
        return 0.0
    half = max(0.5 * extent, 1e-12)
    if half <= table[0]["radius"]:
        return float(table[0]["form_error"])
    for lo, hi in zip(table, table[1:]):
        if half <= hi["radius"]:
            a, b = float(lo["form_error"]), float(hi["form_error"])
            if a <= 0.0 or b <= 0.0:
                return max(a, b)
            t = math.log(half / lo["radius"]) / math.log(hi["radius"] / lo["radius"])
            return a * (b / a) ** t
    return float(table[-1]["form_error"])


def _sigma_dihedral(topo: _Topology) -> float:
    """Estimator B (spec 3.2): the median interior-edge dihedral, calibrated.

    Real creases are a small minority of interior edges on a mechanical part, so
    the median sees only the noise. The 2.2 is the derived calibration constant,
    not a tuning knob.

    That assumption is the estimator's *domain*, and it is not always true: on a
    honeycomb 61.5% of interior edges are genuine 60-degree cell walls, so the
    median reads 59.99993 degrees and this returns 13.108 mm of "noise" for a
    mesh that carries none. The caller is `_stage_noise_scale`, and it is the
    detected regime -- not this function -- that decides whether what comes back
    is a noise estimate or a measurement of the part's own creases.
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
# regions from Fusion's face groups
# --------------------------------------------------------------------------


def _axis_distance(point: Vec3, anchor: Vec3, axis: Vec3) -> float:
    w = _sub(point, anchor)
    return _length(_sub(w, _scale(axis, _dot(w, axis))))


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
        # The axial-span floor exists for one stated reason -- "how long a
        # cylinder or cone must be, in radii, before its axis is determined" --
        # and it measures the *vertices'* baseline for that determination. When
        # the axis came from the facet normals instead, at an eigengap the caller
        # declared sufficient, this floor is testing evidence the fit does not
        # rest on: a bore two rings deep has almost no vertex baseline and a
        # perfectly determined normal system. The floor is therefore recorded and
        # not applied, with the evidence that replaced it, rather than loosened --
        # the threshold's value is untouched and every fit whose axis did come
        # from the vertices still meets it.
        evidence = fit.support.get("axis_evidence")
        if isinstance(evidence, Mapping) and evidence.get("source") == "facet-normals":
            measured["axial_span_floor_applied"] = False
            measured["axis_determined_by"] = "facet-normals"
            measured["normal_axis_eigengap"] = evidence.get("eigengap")
            return True, measured
        measured["axial_span_floor_applied"] = True
        measured["axis_determined_by"] = "vertices"
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
    form_error: float = 0.0,
) -> dict[str, Any]:
    """Spec 10.3: checkerboard by grid-cell parity, not a random point split.

    Returns either the comparison -- ``heldout_rms``, ``in_sample_rms``,
    ``ratio`` -- or a single ``underpowered`` key naming why there was no
    comparison to make. Those are different answers and the caller treats them
    differently: a ratio is a verdict, and "this region cannot be split into two
    halves that each determine the primitive" is a fact about the split.

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
        return {
            "underpowered": (
                f"one blocked half of this region holds {min(len(parts[0]), len(parts[1]))} points, "
                f"below the {_MIN_REGION_POINTS} a fit needs, so there is no half-data fit to "
                "compare against"
            )
        }
    taper = float(spec.value("min_taper_ratio"))
    major = float(spec.value("min_torus_major_ratio"))
    # The denominator's floor, and what it is a floor *of*: the resolution at
    # which "the half-fit's own residual" is a meaningful denominator at all. A
    # half-fit whose in-sample RMS is 0.001 mm on a surface whose shape departs
    # from the primitive by 0.015 mm has not fitted the surface that well -- it
    # has fitted its own half of the waviness -- and dividing by it turns the
    # part's form into a ratio of 15 and a verdict of "over-parameterized".
    floor = max(_BAND_FLOOR_RATIO * fit.extent, form_error)
    worst = 0.0
    heldout_rms = 0.0
    in_sample_rms = 0.0
    for train_key, test_key in ((0, 1), (1, 0)):
        train = [mesh.vertices[i] for i in parts[train_key]]
        test = [mesh.vertices[i] for i in parts[test_key]]
        extent = _extent(train)
        if extent <= 0.0:
            return {
                "underpowered": (
                    "one blocked half of this region has no extent, so there is no half-data fit "
                    "to compare against"
                )
            }
        trial = _raw_fit(train, fit.kind, extent, taper, major)
        if not trial.accepted:
            # A half that cannot itself determine the primitive says nothing
            # about the full fit. On a scan the halves of a nine-triangle group
            # fail their own span floors, which is a fact about how the region
            # was split and not evidence that the fit is over-parameterized --
            # and it was refusing the fit outright.
            return {
                "underpowered": (
                    f"a spatially blocked half of these points does not itself determine a "
                    f"{fit.kind} ({trial.rejection}), so the comparison has no power: this is a "
                    "property of the split, not evidence about the full fit"
                )
            }
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
        "extent": topo.extent,
        "median_edge_length": topo.median_edge,
    }
    # Top level, beside `covered_area_fraction` and the regions' `area_fraction`,
    # because it is the denominator of every fraction in this record and U3 reads
    # it as `fit_record.total_area`. It lived inside the `topology` diagnostic
    # block once and the whole pipeline was unrunnable for it: U3 refused every
    # real record with `fit-record-malformed`, and the only thing that ever
    # reached U3 was a fixture hand-built to U3's expectation.
    state["record"]["total_area"] = topo.total_area
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
    return None


def _stage_noise_scale(state: dict[str, Any]) -> dict[str, Any] | None:
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    surface_scale, sigma_quadric = _local_scale_estimates(mesh, topo, state["live_points"])
    sigma_dihedral = _sigma_dihedral(topo)
    form = _sigma_form(mesh, topo, state["spec"])
    lo, hi = sorted((sigma_quadric, sigma_dihedral))
    disagree = hi > 0.0 and (lo <= 0.0 or hi / lo > 2.0)
    dihedral = _dihedral_degrees(topo)
    # The regime is detected *before* sigma is selected, because it is the regime
    # that says which estimator is estimating noise at all. Estimator B assumes
    # real creases are a small minority of interior edges; on a honeycomb 61.5%
    # of them are genuine 60-degree cell walls, so its median reads the part's
    # own geometry and it reported 13.108 mm of "noise" on a mesh whose quadric
    # estimator reported exactly 0.0 and whose regime detector said tessellation.
    # Selecting sigma first and detecting the regime afterwards is how that value
    # escaped the check that already suppressed the flag.
    regime = _detect_regime(state["spec"], topo, sigma_quadric, dihedral)
    state["regime"] = regime
    state["record"]["regime"] = regime
    if regime["regime"] == "tessellation":
        # An exact tessellation carries no measurement noise, so a dihedral is a
        # facet turn angle and belongs to `discretization_scale`, which is where
        # the surface scale already puts it. The quadric estimator is the only
        # one still measuring noise here, and the precision floor below is what
        # keeps it from claiming a certainty float32 cannot support.
        sigma, estimator = sigma_quadric, "quadric"
        why = (
            "the mesh reads as an exact tessellation, where the dihedral estimator measures the "
            "facet turn angle of a noise-free mesh rather than noise; the quadric estimator is the "
            "only one estimating noise, and the vertex precision floor bounds it from below"
        )
    else:
        # Three estimators of how far this surface departs from the shape it is
        # nominally, cross-checked. The largest is used -- the conservative
        # choice, since every downstream band widens with it.
        #
        # Estimator C is the one that is not facet-scale, and it is taken here
        # rather than only at the structure gates because every consumer of
        # `sigma` is making the same claim about the same surface: the
        # neighbourhood radius, the curvature dead zone, the normal-direction
        # floor and the recoverable feature size are all statements about how
        # much of what this mesh shows is the part. A form error the facet
        # estimators cannot see makes every one of them claim a precision the
        # measurement does not support.
        candidates = {
            "quadric": sigma_quadric,
            "dihedral": sigma_dihedral,
            "form": form["sigma"],
        }
        estimator = max(sorted(candidates), key=lambda name: candidates[name])
        sigma = candidates[estimator]
        why = (
            "all three estimators are estimating how far this measured surface departs from the "
            "shape it is nominally, so the largest is taken: every downstream band widens with "
            "sigma, and the conservative side is the honest one"
            if estimator != "form"
            else "the form-error estimator reads above both facet estimators, and it is the only "
            "one of the three that can see low-frequency departure from the nominal shape: on a "
            "measured surface that is the error that dominates, and calibrating anything below it "
            "claims a precision the measurement does not support"
        )
    # No estimator can see below the precision the coordinates are *stored* at.
    # A binary STL holds float32, so a 100 mm part carries about 1e-05 mm of
    # quantization in every vertex -- deterministic, and therefore systematically
    # signed, which is exactly the signature the residual-structure gates are
    # built to catch. Without this floor those gates spend their power testing
    # the file format: measured over the 11 production STLs it refused 56 of the
    # 85 full-turn bores for "azimuthal structure" that was the quantization of a
    # perfectly round hole. The floor binds only where the mesh is quiet enough
    # for it to matter; on a scan the estimators are orders of magnitude above it.
    declared_precision = float(state["spec"].value("vertex_precision_rel"))
    precision_floor = declared_precision * topo.extent
    selected = sigma
    sigma = max(sigma, precision_floor)
    # And the declaration is *checked* against the coordinates themselves. It is
    # a claim about the file format, which the file can answer: a coordinate that
    # came through float32 survives a float32 round trip exactly, and one that
    # did not, does not. Declared and measured are both recorded; they are not
    # reconciled here, because which one is right is the caller's to say -- a
    # mesh may honestly carry finer coordinates than the floor they declared.
    measured_precision = _measured_vertex_precision(mesh.vertices, topo.extent, declared_precision)
    # What the dihedral estimator measures on a tessellation is the facet turn
    # angle, and that *is* the discretization scale -- so it moves here rather
    # than being discarded. It was already reaching this line through `sigma` in
    # both regimes, which is why the power floors that read `surface_scale` are
    # unchanged by the selection above; only the feature-scale budget, which is a
    # statement about noise, sees the difference. In the scan regime `sigma` is
    # already the larger of the two, so this max is a no-op there.
    surface_scale = max(surface_scale, sigma, sigma_dihedral)
    discretization = math.sqrt(max(0.0, surface_scale * surface_scale - sigma * sigma))
    # The scale the residual-*structure* gates have to clear, which is not the
    # same scale the feature budget and the neighbourhood radius read.
    #
    # `sigma` above is facet-to-facet: it is what the normals, the curvature
    # classes and the recoverable feature size are statements about, and it stays
    # exactly what it was. But a residual-structure test asks a different
    # question -- "is this residual the wrong primitive, or is it the surface?"
    # -- and on a measured surface the answer includes form error, which no facet
    # estimator can see. Calibrating those gates below the form error hands them
    # the part's own waviness to test: on the capture they refused 286 regions
    # for Moran z of 12-54 on faces that are genuinely planes, and 2,207 for a
    # held-out half that had merely landed on a different part of the same wave.
    #
    # So the structure scale is the larger of the facet scale and the form error,
    # and only in the `scan` regime. An exact tessellation carries no form error
    # by construction -- its vertices sit on the analytic surface -- so what
    # estimator C measures there is the surface's own curvature over a
    # feature-sized patch, which is geometry and not error. It is recorded in
    # both regimes and taken in one.
    form_table = form["scale_table"] if regime["regime"] != "tessellation" else []
    form_error = form["sigma"] if regime["regime"] != "tessellation" else 0.0
    structure_scale = max(surface_scale, form_error)
    state["noise"] = {
        "sigma": sigma,
        "surface_scale": surface_scale,
        "structure_scale": structure_scale,
        "form_error": form_error,
        # The ladder, so the gates can read it at each region's own extent
        # rather than at the one scale this record reports.
        "form_error_table": form_table,
    }
    # The flag says the *noise model* is inconsistent, and that claim only means
    # something where both estimators are estimating noise. On an exact
    # tessellation the dihedral estimator is measuring the facet turn angle of a
    # mesh with no noise in it at all, so the two are meant to disagree and the
    # disagreement is discretization rather than a failed iid assumption. The
    # measured ratio stays in the record either way; what the regime changes is
    # whether it is reported as a defect.
    inconsistent = disagree and regime["regime"] != "tessellation"
    if inconsistent:
        state["flags"].append("noise-model-inconsistent")
    state["record"]["noise"] = {
        "regime": regime["regime"],
        "estimators_disagree": disagree,
        "vertex_precision_floor": precision_floor,
        "vertex_precision": measured_precision,
        "precision_floor_binds": precision_floor >= selected,
        "sigma": sigma,
        "sigma_quadric": sigma_quadric,
        "sigma_dihedral": sigma_dihedral,
        "sigma_form": form["sigma"],
        "sigma_estimator": estimator,
        "sigma_estimator_reason": why,
        "form_error": form,
        # The three estimators and which of them each consumer takes, in one
        # place, because "sigma" alone can no longer answer "sigma of what".
        "structure_scale": structure_scale,
        "structure_scale_estimator": (
            "form"
            if form_error > surface_scale
            else ("facet-turn-angle" if regime["regime"] == "tessellation" else estimator)
        ),
        "structure_scale_reason": (
            "the form-error estimator reads above the facet scale at the declared feature size, so "
            "the residual-structure and held-out gates are calibrated to it: a residual inside the "
            "surface's own departure from its nominal shape is not evidence about which primitive "
            "the surface is. Each gate reads form_error.scale_table at its own region's extent, so "
            "this number is the ladder at one scale and not the whole of what they use"
            if form_error > surface_scale
            else (
                "an exact tessellation carries no form error, so estimator C is recorded and not "
                "taken; the facet scale is the whole measurement error here"
                if regime["regime"] == "tessellation"
                else "at the declared feature size the facet estimators read at or above the "
                "form-error estimator. The gates still read form_error.scale_table at each "
                "region's own extent, where a larger region can sit above this number"
            )
        ),
        "surface_scale": surface_scale,
        "discretization_scale": discretization,
        # What `surface_scale` and `discretization_scale` are a scale *of*, which
        # the regime decides and the names do not say. On a scan both are lengths
        # over which the surface is uncertain. On a tessellation the mesh carries
        # no noise, `sigma_dihedral` is the median facet turn angle, and a
        # honeycomb's turn angles are its own 60-degree cell walls: the 13.108 mm
        # it reported on a 249 mm part is the scale of the part's *features*, not
        # of any discretization. The number is unchanged -- it is the right power
        # floor either way, since a residual-structure test has nothing to test
        # below the scale at which the surface itself turns -- and it is now
        # labelled with what it measures rather than left to be read as noise.
        "surface_scale_basis": (
            "facet-turn-angle" if regime["regime"] == "tessellation" else "measurement-noise"
        ),
        "sigma_over_extent": sigma / topo.extent if topo.extent > 0.0 else math.inf,
        "sigma_over_median_edge": sigma / topo.median_edge if topo.median_edge > 0.0 else math.inf,
        "median_abs_dihedral_deg": _median(dihedral) if dihedral else None,
        "interior_edge_count": len(dihedral),
        "estimators_consistent": not inconsistent,
        "note": (
            "sigma is measurement noise, estimated about a local quadric so surface curvature "
            "does not read as noise, and cross-checked against the calibrated dihedral median. "
            "All three estimators are always reported; sigma_estimator says which one sigma was "
            "taken from and sigma_estimator_reason says why, because the regime decides which of "
            "them is estimating noise at all. sigma_form is the third and it is not facet-scale: "
            "it is the surface's departure from a plane over a patch one declared feature across, "
            "which is the error a measured surface actually carries and the one the other two are "
            "blind to by construction. sigma stays facet-scale -- it is what the normals, the "
            "curvature classes and the recoverable feature size are statements about -- and "
            "structure_scale is the larger of the facet scale and the form error, which is what "
            "the residual-structure and held-out gates are calibrated to. structure_scale_estimator "
            "and structure_scale_reason say which and why. surface_scale adds the mesh's own "
            "discretization; it sizes the facet-scale term in the power floor below which the "
            "residual-structure test has nothing to test. Neither "
            "decides whether to give up: that is the feature-scale budget. surface_scale_basis "
            "says what surface_scale is a scale of: on a scan it is measurement noise, and on a "
            "tessellation it is the facet turn angle -- the scale at which the surface itself "
            "turns, which on a part whose walls meet at 60 degrees is the part's own geometry and "
            "not a discretization. discretization_scale is surface_scale with sigma taken out of "
            "it and carries the same meaning."
        ),
    }
    return None


#: A dihedral below this reads as *exactly* coplanar. It is a float-noise
#: comparison, not a decision threshold: the question it answers is whether two
#: facets were generated from one analytic face, and a tessellator's answer is
#: exact while a scanner's is never within a billionth of a degree of it.
#:
#: A billionth of a degree is below what ``acos`` can resolve near 1 -- one ulp
#: off a unit dot product already reads 1.2e-06 degrees -- so in practice this
#: comparison asks whether the dot product rounded to exactly 1.0, and a pair
#: that misses by an ulp counts as *not* coplanar. That is the conservative
#: direction (it can only push a mesh towards `scan`, which keeps the wider
#: bands), it needs a *whole mesh* of near misses to change the regime because
#: `bimodal` needs only one exact pair, and it does not happen on any mesh
#: measured here: the fixtures put 89% of interior edges at exactly 0.0 with no
#: near-zero band at all, and the honeycomb organiser -- a vendor STL, normals
#: computed per facet from different vertex triples -- puts 38.5% there. Widening
#: it to acos's own resolution would be a threshold moved for a failure nobody
#: has measured; the regression fixture below pins the behaviour instead.
_EXACT_COPLANAR_DEG = 1e-9


#: One ulp of float32 at 1.0, doubled: the worst relative spacing anywhere in
#: the format, and therefore the precision a float32 coordinate carries.
_FLOAT32_PRECISION_REL = 2.0 * 2.0**-24


def _measured_vertex_precision(
    vertices: Sequence[Vec3], extent: float, declared: float, limit: int = 4096
) -> dict[str, Any]:
    """Is ``vertex_precision_rel`` the precision these coordinates were stored at?

    The declaration is a statement about the file the dump came from -- "a binary
    STL holds float32" -- and it sets a floor under sigma, so declaring it too
    coarse silences the residual-structure gates and declaring it too fine hands
    them the file format to test.  It is also a statement the coordinates can
    answer: a value that arrived through float32 is exactly representable in
    float32 and survives ``struct.pack``/``unpack`` unchanged, and one that did
    not, does not.

    Sampled at a fixed stride rather than exhaustively -- a mesh is millions of
    numbers and this is a question about the format, not about any one vertex.
    Reported, never enforced: a mesh that carries finer coordinates than the
    caller declared is a conservative declaration, not a malformed record.
    """
    if not vertices:
        return {"sampled_vertices": 0, "reads_as_float32": None}
    step = max(1, len(vertices) // limit)
    sampled = vertices[::step]
    worst = 0.0
    for vertex in sampled:
        for value in vertex:
            round_trip = struct.unpack("<f", struct.pack("<f", float(value)))[0]
            worst = max(worst, abs(float(value) - round_trip))
    exact = worst == 0.0
    return {
        "sampled_vertices": len(sampled),
        "max_float32_round_trip": worst,
        "reads_as_float32": exact,
        # What the coordinates say their own precision is: float32's own relative
        # spacing where they round-trip through it, and otherwise the round trip
        # they failed by, which is a lower bound on the precision they carry.
        "measured_precision_rel": (
            _FLOAT32_PRECISION_REL if exact else (worst / extent if extent > 0.0 else math.inf)
        ),
        "declared_precision_rel": declared,
        "note": (
            "float32 if every sampled coordinate survives a float32 round trip exactly, which is "
            "what a binary STL guarantees and what the declared floor assumes. Finer coordinates "
            "mean the declaration is conservative; coarser ones mean the floor is under-declared "
            "and the residual-structure gates are testing the file format."
            if exact
            else "these coordinates do not round-trip through float32, so they carry more "
            "precision than a binary STL does and the declared floor is a conservative one."
        ),
    }


def _detect_regime(
    spec: DetectionSpec, topo: _Topology, sigma_quadric: float, dihedral: Sequence[float]
) -> dict[str, Any]:
    """Exact tessellation or scan, from evidence this run already measured.

    Two independent readings, because either alone is fooled by a mesh the other
    catches:

    * **the measured noise.** A quadric absorbs curvature, so ``sigma_quadric``
      is the vertices' departure from a smooth surface. On an STL written by a
      solid modeller that departure is float precision -- some 1e-12 of the part
      -- and on any scan it is orders of magnitude larger. The caller declares
      where the line sits.
    * **the dihedral distribution.** A tessellation is bimodal: facet pairs
      generated from one analytic planar face meet at *exactly* zero, and feature
      edges are sharp. A scan has neither -- every dihedral carries noise, so no
      pair is ever exactly coplanar.

    Both must say tessellation for the regime to be tessellation. When they
    disagree the answer is `scan`, which is the conservative regime -- it keeps
    the wider noise bands and the floors sized for them -- and the disagreement
    is named in the record rather than resolved silently.

    The caller may override with `regime`, and the override is recorded beside
    the evidence it overrode, so a reader can always see what the mesh said.
    """
    extent = topo.extent
    ratio = sigma_quadric / extent if extent > 0.0 else math.inf
    declared = float(spec.value("tessellation_sigma_over_extent"))
    exact = sum(1 for angle in dihedral if abs(angle) < _EXACT_COPLANAR_DEG)
    exact_fraction = exact / len(dihedral) if dihedral else 0.0
    quiet = ratio <= declared
    bimodal = exact > 0
    detected = "tessellation" if (quiet and bimodal) else "scan"
    requested = str(spec.value("regime"))
    regime = detected if requested == "auto" else requested
    return {
        "regime": regime,
        "detected": detected,
        "declared": requested,
        "overridden": requested != "auto" and requested != detected,
        "evidence": {
            "sigma_quadric_over_extent": ratio,
            "tessellation_sigma_over_extent": declared,
            "vertices_read_as_exact": quiet,
            "exactly_coplanar_edge_fraction": exact_fraction,
            "exactly_coplanar_edge_count": exact,
            "interior_edge_count": len(dihedral),
            "dihedral_reads_as_bimodal": bimodal,
            "readings_agree": quiet == bimodal,
        },
        "note": (
            "Both readings must say tessellation for the regime to be tessellation; they disagree "
            "into 'scan', which is the conservative side. A declared regime overrides the "
            "detection and both are reported."
        ),
    }


def _normal_sigma_floor_deg(state: dict[str, Any]) -> float:
    """The measurement floor on a facet normal's direction, in degrees.

    On an exact tessellation the vertices are exact, so the only floor is the one
    the caller declared for float precision. On a scan the floor is whichever is
    larger of that and the noise the mesh actually carries: a vertex displaced by
    ``sigma`` across an edge of length ``l`` tilts its facet by about
    ``sigma / l`` radians, and reporting a tighter axis than that noise supports
    would be inventing precision out of the same evidence that refuses it.
    """
    declared = float(state["spec"].value("normal_sigma_theta_floor_deg"))
    if state["regime"]["regime"] == "tessellation":
        return declared
    topo: _Topology = state["topology"]
    if topo.median_edge <= 0.0:
        return declared
    return max(declared, math.degrees(state["noise"]["sigma"] / topo.median_edge))


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


def _stage_face_groups(state: dict[str, Any]) -> dict[str, Any] | None:
    """The regions, read from the dump. Refused when the dump carries none.

    ``MeshGenerateFaceGroups`` under ``AccurateGenerateFaceGroupsType`` matches
    mesh faces to analytic primitives, and ``triangleFaceGroupTempIds`` delivers
    the result as one group id per triangle. That is a complete region
    assignment, so this stage assigns and does not infer.

    There is deliberately no fallback. A dump with no grouping was extracted
    before the face-group transaction ran, or from a Fusion that reported none,
    and inventing regions here is exactly the silently-wrong answer the deleted
    RANSAC layer produced. The refusal names the command that fixes it.
    """
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    record = state["record"]
    if mesh.face_groups is None:
        record["face_groups"] = {"present": False, "group_count": 0, "source": None}
        return _refusal(
            "face-groups-absent",
            {"face_groups_source": state["dump"].metadata.get("face_groups_source")},
            "The regions are Fusion's face groups and this dump carries none. Run "
            "`emit-mesh-face-groups` against the mesh body, then re-extract: extraction reads "
            "whatever grouping the body carries and never generates one of its own.",
        )
    groups: dict[int, list[int]] = {}
    for index in topo.valid:
        groups.setdefault(int(mesh.face_groups[index]), []).append(index)
    # Relabelled to a dense range in sorted temp-id order. The temp id itself is
    # never carried into the record: it is a *temp* id and does not survive the
    # session it was read in.
    state["regions_by_label"] = {
        label: sorted(groups[temp_id]) for label, temp_id in enumerate(sorted(groups))
    }
    record["face_groups"] = {
        "present": True,
        "group_count": len(groups),
        "source": "triangleFaceGroupTempIds",
        # One group over a whole part is a grouping that failed, and the
        # face-group transaction refuses it there, where re-running with a
        # different method is the fix. Here it is simply one region: a fixture of
        # a single tube honestly *is* one group, and the coverage floor already
        # decides whether what came back explains enough of the part.
        "single_group": len(groups) == 1,
    }
    record["segmentation"] = {
        "method": (
            "Fusion MeshGenerateFaceGroups, read per triangle from triangleFaceGroupTempIds; "
            "this module fits and disproves, it does not segment"
        ),
        "labelled_triangles": sum(len(v) for v in groups.values()),
        "unclaimed_triangles": 0,
        "group_count": len(groups),
    }
    return None


def _stage_disproof(state: dict[str, Any]) -> dict[str, Any] | None:
    mesh: WeldedMesh = state["mesh"]
    topo: _Topology = state["topology"]
    spec: DetectionSpec = state["spec"]
    groups: dict[int, list[int]] = state["regions_by_label"]
    surface_scale = state["noise"]["surface_scale"]
    form_table = state["noise"]["form_error_table"]
    grid: _Grid = state["grid"]
    gates = spec.fit_gates()
    perpendicular = float(spec.value("cylinder_normal_perpendicular_deg"))
    sigma_theta_floor = _normal_sigma_floor_deg(state)

    regions: list[dict[str, Any]] = []
    # The residual-structure baseline: how much spatial structure this part's own
    # planes carry, as a floor under the Moran cap. It needs *two* planes to
    # exist. With one, the baseline is that plane's own z and the gate licenses
    # whatever it was about to test -- a 20-degree arc of a cylinder fitted as a
    # plane raised a Moran z of 15.7 and then raised its own cap to 19.7.
    plane_zs: list[float] = []
    plane_baseline: float | None = None
    prepared: list[tuple[int, list[int], list[int], PrimitiveFit]] = []
    for label in sorted(groups):
        triangles = sorted(groups[label])
        if len(triangles) < _MIN_REGION_TRIANGLES:
            continue
        point_indices = sorted({v for t in triangles for v in mesh.triangles[t]})
        if len(point_indices) < _MIN_REGION_POINTS:
            continue
        points = [mesh.vertices[i] for i in point_indices]
        # Every kind, ranked by residual, then the facet normals break the one
        # tie the vertices cannot: a two-ring bore or round lies exactly on a
        # sphere as well as on its cylinder. There is no seed axis to pass -- the
        # deleted detector was where one came from -- so each fitter derives its
        # own from the group's points, which is what the measurement over the
        # real STLs exercised.
        fits = fit_face_group(
            points,
            kinds=DETECTED_KINDS,
            facet_normals=[topo.tri_normals[t] for t in triangles],
            cylinder_perpendicular_deg=perpendicular,
            # The facets are the evidence the vertices do not carry: their
            # normals are perpendicular to a cylinder's axis by construction, and
            # weighting by area is what makes the recovered sigma a statement
            # about surface rather than about triangle count.
            facet_centroids=[topo.centroids[t] for t in triangles],
            facet_areas=[topo.areas[t] for t in triangles],
            normal_axis_eigengap_min=float(spec.value("min_normal_axis_eigengap")),
            normal_sigma_theta_floor_deg=sigma_theta_floor,
            # The same normals that determine the axis also say whether there is
            # an axis to determine: a prism's walls are spikes, a cylinder's
            # facets are a sweep, and the vertices cannot tell them apart because
            # a regular polygon's corners lie exactly on its circumscribed circle.
            min_cylinder_normal_directions_per_turn=float(
                spec.value("min_cylinder_normal_directions_per_turn")
            ),
            **gates,
        )
        fit = fits[0]
        prepared.append((label, triangles, point_indices, fit))
        if fit.accepted and fit.kind == "plane":
            structure = _moran_i(list(_residuals(fit.kind, fit.parameters, points)), point_indices, topo)
            if structure is not None:
                plane_zs.append(structure["z"])
    if len(plane_zs) >= 2:
        plane_baseline = min(plane_zs)

    for label, triangles, point_indices, fit in prepared:
        points = [mesh.vertices[i] for i in point_indices]
        area = sum(topo.areas[t] for t in triangles)
        # The kind the ranking selected, before any promotion rebinds ``fit``.
        selected_kind = fit.kind
        support: dict[str, Any] = dict(fit.support)
        checked: list[str] = list(support.get("checked", ()))
        support["checked"] = checked
        rejection = fit.rejection
        accepted = fit.accepted

        if accepted:
            residuals = list(_residuals(fit.kind, fit.parameters, points))
            # Bound before the first branch that can clear `accepted`. Both
            # structure gates below read it from this scope, and when the support
            # floors refuse first the block that used to bind it never runs --
            # leaving the reads safe only because `and` happens to short-circuit
            # on `accepted` first. That is an operand order, not an invariant,
            # and an UnboundLocalError here becomes `fit-record-stage-failed` for
            # the whole mesh.
            #
            # The form error *at this region's own extent*, read off the ladder
            # the noise stage measured. A residual has to be compared against the
            # form error at its own scale: this part's faces are flat to 0.0037 mm
            # over 0.8 mm and wavy to 0.015 mm over 3.2, and a gate that judges a
            # 3 mm region against the 0.8 mm number is testing the waviness.
            # Empty outside the scan regime -- an exact tessellation carries no
            # form error -- and `_form_error_at` then returns 0.0, so everything
            # below reduces to what it was.
            form_error = _form_error_at(form_table, fit.extent)
            # `form_error` enters undivided while `surface_scale` enters at a
            # tenth, and the asymmetry is the point. `surface_scale` is a
            # *per-facet* scale: a region's RMS averages it down over its points,
            # so a residual has to sit an order of magnitude above it before it
            # stops being facet noise. Form error is a *whole-patch* scale --
            # a plane fitted to a wavy face has an RMS equal to the waviness, not
            # a tenth of it -- so a tenth of it would be a floor an order of
            # magnitude below anything it is meant to floor.
            noise_floor = max(_BAND_FLOOR_RATIO * fit.extent, 0.1 * surface_scale)
            power_floor = max(noise_floor, form_error)
            # Which term bound it, so a skipped gate says what it had no power
            # against rather than naming a scale that was not the operative one.
            floor_basis = (
                "the surface's own form error"
                if form_error >= noise_floor
                else "the measurement noise"
            )
            support["form_error"] = form_error
            support["power_floor"] = power_floor
            support["power_floor_basis"] = floor_basis
            passed, measured = _support_floors(fit, points, spec, topo.median_edge)
            support.update(measured)
            if not passed:
                accepted, rejection = False, (
                    f"support floors: this {fit.kind} is supported by too narrow a span of surface "
                    f"for its parameters to be determined ({measured})."
                )
            else:
                _passed(checked, "support-span-floor")

            if accepted:
                # A test has no power against residuals that sit an order of
                # magnitude inside the measurement noise, and on an exact
                # synthetic fit it would be reading float noise. Say so rather
                # than pass or fail on it -- and do not claim the check in
                # `checked`, because it did not run. `power_floor` is bound above.
                structure = (
                    _moran_i(residuals, point_indices, topo)
                    if fit.rms_residual > power_floor
                    else None
                )
                if structure is None:
                    support["moran_z"] = None
                    support["moran_unavailable_reason"] = (
                        f"residuals are below {floor_basis}, so a spatial-autocorrelation "
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
                        # The scale a systematically-signed bin mean has to beat.
                        # On a scan that is the form error where it exceeds the
                        # facet scale: a wavy face's bins *are* systematically
                        # signed, and against the facet scale every one of them
                        # reads as the wrong primitive.
                        max(surface_scale, form_error),
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
                        _passed(checked, "residual-structure")

            if accepted and fit.rms_residual <= noise_floor:
                # The same rule the Moran block above already states, applied to
                # its sibling: a test has no power against residuals an order of
                # magnitude inside the measurement noise. Held-out residuals of
                # 2e-06 mm against in-sample residuals of 1e-06 mm are a ratio of
                # two quantization patterns, and calling that "over-parameterized
                # for the evidence" is a verdict about the file format. Reported
                # as unavailable, and deliberately *not* appended to `checked`,
                # because the check did not run.
                support["heldout_unavailable_reason"] = (
                    "residuals are below the measurement noise, so a held-out comparison has no "
                    "power here"
                )
            elif accepted:
                # Unlike the two structure tests above, this one is *not* skipped
                # by the form error: it stays a real gate on a scan and takes the
                # form error as the resolution of its own comparison instead. Two
                # halves of a wavy face sit on different parts of the wave, so the
                # difference between them is only evidence of over-fitting once it
                # exceeds what the surface's own shape puts there.
                held = _blocked_heldout(fit, point_indices, mesh, grid, spec, form_error)
                if "underpowered" in held:
                    # Underpowered is not disproved. This branch used to refuse
                    # the fit outright and it is the single largest refusal class
                    # on a real scan: a face group of nine triangles cannot be
                    # halved into two groups that each determine a primitive, and
                    # calling that "does not survive being asked for half the
                    # evidence" is a verdict about the split. Recorded as a skip
                    # with its reason, and deliberately not appended to `checked`.
                    support["heldout_unavailable_reason"] = held["underpowered"]
                else:
                    support.update(held)
                    if held["ratio"] > float(spec.value("heldout_ratio_max")):
                        accepted, rejection = False, (
                            f"held-out residual {held['heldout_rms']:.6g} is {held['ratio']:.4g}x "
                            f"the in-sample residual; the fit is over-parameterized for the "
                            "evidence."
                        )
                    else:
                        _passed(checked, "heldout-residual")

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
                    _passed(checked, "nested-kind-parsimony")

        if not accepted and fit.accepted and fit.kind in _RICHER_KINDS:
            promoted = _promote(fit, points, spec, support.get("n_eff", float(len(points))))
            if promoted is not None:
                refused_kind = fit.kind
                fit, accepted, rejection = promoted, True, None
                support = dict(fit.support)
                checked = list(support.get("checked", ()))
                support["checked"] = checked
                support["promoted_from"] = refused_kind
                _passed(checked, "kind-promotion")

        uncertainty: dict[str, float] = {}
        if accepted:
            uncertainty = parameter_uncertainty(
                fit, points, n_eff=support.get("n_eff", float(len(points)))
            )
            failure = _uncertainty_gate(uncertainty, fit, spec)
            if failure is not None:
                accepted, rejection = False, failure
            else:
                _passed(checked, "parameter-uncertainty")

        if accepted and fit.kind in _AXIS_KINDS:
            corroboration = _boundary_corroboration(
                fit,
                uncertainty,
                triangles,
                mesh,
                topo,
                float(spec.value("boundary_circle_sigmas")),
                surface_scale,
            )
            if corroboration is not None:
                support["boundary_circle"] = corroboration
                _passed(checked, "boundary-circle-corroboration")

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
                "detected_kind": selected_kind,
                "fit": recorded.to_dict(),
                "accepted": accepted,
                "dominant_curvature": _dominant_class(state["frame"], point_indices),
                "orientation": _region_orientation(fit, triangles, mesh, topo, state),
                # The kinematic router's sufficient statistic over this region's
                # own facets. U3 has the fit record and no triangles, and the
                # question "is this group of regions swept by a rotation?" is one
                # only the facet normals can answer, so the answer's raw material
                # crosses the seam here rather than being re-invented there.
                "motion_moments": region_motion_moments(
                    [topo.centroids[t] for t in triangles],
                    [topo.tri_normals[t] for t in triangles],
                    [topo.areas[t] for t in triangles],
                ),
            }
        )

    state["regions"] = regions
    # The part-level winding judgement the regions were licensed against. The
    # module docstring above has claimed it lands here since the `normals-unoriented`
    # flag was deleted in its favour; it did not, and a region's null
    # `material_side` was readable only as "the mesh is not closed" with no way to
    # see which of the two licences failed.
    if "mesh_orientation" not in state:
        state["mesh_orientation"] = _mesh_orientation(mesh, topo)
    state["record"]["mesh_orientation"] = state["mesh_orientation"]
    state["record"]["disproof"] = dict(
        _disproof_gate_census(regions),
        moran_plane_baseline_z=plane_baseline,
    )
    return None


#: Each disproof gate, by the token its block appends to ``checked`` once it has
#: run and passed, with where that block records why it did not run.
_DISPROOF_GATES = (
    ("support-span-floor", None),
    ("residual-structure", "moran_unavailable_reason"),
    ("heldout-residual", "heldout_unavailable_reason"),
    ("nested-kind-parsimony", None),
)


def _disproof_gate_census(regions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What actually ran, counted from the per-region ``checked`` lists.

    The note here used to claim that every accepted fit had survived all four
    gates.  It had not: both structure gates carry a power floor -- against
    residuals an order of magnitude inside the measurement noise they have
    nothing to test -- and on the honeycomb organiser that floor skipped Moran
    and the held-out refit on all 39 accepted planes.  Kind promotion is a third
    path: a promoted fit is accepted on the promotion's own evidence and carries
    the promoted fit's ``checked``, not the refused one's.

    The per-region lists were honest throughout, so the summary is derived from
    them rather than written alongside them.  A gate is counted as *run* only
    where its own block appended its token, and every skip is counted under the
    reason that block recorded.
    """
    accepted = [region for region in regions if region["accepted"]]
    gates: dict[str, Any] = {}
    for token, reason_key in _DISPROOF_GATES:
        ran, reasons = 0, {}
        for region in accepted:
            support = region["fit"].get("support", {})
            if token in support.get("checked", ()):
                ran += 1
                continue
            reason = support.get(reason_key) if reason_key else None
            if reason is None:
                reason = (
                    "the fit was promoted to another kind, and carries the promoted fit's gates"
                    if "promoted_from" in support
                    else "the gate did not run on this region and recorded no reason"
                )
            reasons[reason] = reasons.get(reason, 0) + 1
        gates[token] = {
            "ran": ran,
            "skipped": len(accepted) - ran,
            "skip_reasons": dict(sorted(reasons.items())),
        }
    return {
        "accepted_fits": len(accepted),
        "gates": gates,
        "note": (
            "Counted from each region's own `checked` list, which is appended only by the block "
            "that ran the gate: `ran` is how many accepted fits that gate actually judged, and "
            "every skip is counted under the reason the skipping block recorded. A gate with no "
            "power against residuals inside the measurement noise reports that rather than "
            "passing. Fusion supplied the regions; it has no opinion about whether a fit is "
            "justified, so a face group that failed a gate is kept with the gate that killed it, "
            "never dropped."
        ),
    }


def _open_boundary(mesh: WeldedMesh, topo: _Topology) -> dict[str, Any]:
    """The mesh's open boundary, as loops, with the cap each one is missing.

    A boundary edge is one carried by a single triangle; a non-manifold edge is
    one carried by three or more.  Both are *dirt*: the mesh does not describe a
    solid there.  The loops are assembled by chaining each boundary edge in the
    direction its own triangle traverses it, so a loop is oriented consistently
    with the surface it came off.

    For each loop this reports the area of the fan cap from the loop's own
    centroid -- an achievable cap, not a lower bound -- and the loop's greatest
    distance from the centroid frame's origin.  Together those bound how far the
    surface integral below could be from the closed solid's volume.
    """
    directed: dict[int, list[int]] = {}
    dirty_vertices: set[int] = set()
    # The dirty *edges* themselves, not only their endpoints: a local-licence
    # query is about distance to the edge, and on a coarse mesh an edge can pass
    # close to a region while both its endpoints are far from it.
    dirty_edges: list[tuple[int, int]] = []
    non_manifold = 0
    for (i, j), incident in topo.edges.items():
        if len(incident) == 2:
            continue
        dirty_vertices.add(i)
        dirty_vertices.add(j)
        dirty_edges.append((i, j))
        if len(incident) != 1:
            non_manifold += 1
            continue
        # Direction as the one owning triangle traverses it.
        a, b, c = mesh.triangles[incident[0]]
        forward = (i, j) in ((a, b), (b, c), (c, a))
        head, tail = (i, j) if forward else (j, i)
        directed.setdefault(head, []).append(tail)

    loops: list[list[int]] = []
    open_chains = 0
    remaining = {head: list(tails) for head, tails in directed.items()}
    for start in sorted(remaining):
        while remaining.get(start):
            loop = [start]
            node = remaining[start].pop()
            guard = 0
            while node != start and remaining.get(node) and guard <= len(directed) + 1:
                loop.append(node)
                node = remaining[node].pop()
                guard += 1
            if node != start:
                # The chain dead-ended or branched at a non-manifold vertex, so
                # it is not a loop. Recording it as one made the caller's
                # centroid fan close it implicitly, and `cap_volume_bound` then
                # bounded a filling of a boundary that is not the mesh's --
                # granting `oriented-and-bounded` on a winding nothing licenses.
                open_chains += 1
                continue
            loops.append(loop)
    return {
        "open_boundary_chains": open_chains,
        "boundary_edges": topo.boundary_edges,
        "non_manifold_edges": non_manifold,
        "loops": loops,
        "dirty_vertices": dirty_vertices,
        "dirty_edges": dirty_edges,
    }


def _mesh_orientation(mesh: WeldedMesh, topo: _Topology) -> dict[str, Any]:
    """Is this mesh's winding outward, and is it oriented enough for the question to mean anything?

    The signed volume of a closed, consistently wound mesh is positive when the
    winding faces outward. On an *inconsistently* wound mesh the number is
    meaningless, and this says so rather than returning a sign nobody should
    trust -- because the consumer of this field decides whether a cylinder is a
    bore or a boss, and guessing there is exactly the invention this skill exists
    to prevent.

    Closure, though, is not the same question, and demanding it globally is what
    made this field useless on the first real scan the pipeline saw: 158 boundary
    edges in 9 loops, the largest 7.5 mm across on a 90 mm part, made
    ``material_side`` null on all 98 curved regions, which made every bore
    unemittable three stages later. Those loops are dirt on a part whose winding
    is otherwise perfectly well defined.

    So the global licence is *consistent orientation plus a bound*, not closure:

    * **consistent orientation** -- every interior edge is traversed in opposite
      directions by its two triangles. This is a topological fact, measured, with
      no threshold in it. Without it no signed volume means anything.
    * **a sign the open boundary cannot flip, over the fillings this bound
      covers.** The surface integral is taken about the mesh centroid, where it
      is origin-dependent only through the caps the boundary loops are missing.
      A cap surface ``C`` contributes at most ``R * area(C) / 3``, ``R`` its
      greatest radius from the frame origin. Filling each loop with the fan from
      its own centroid gives one concrete such surface, and its ``R * A / 3`` is
      what is summed here. When the integral exceeds that sum, no filling
      **whose own area does not exceed that fan's, and which stays inside the
      loop's own radius from the origin**, can change the sign.

      That scope is narrower than "no filling", and saying so is the point: a
      surface spanning the same loop may have arbitrarily greater area -- a tube
      running out and back through a small hole is one -- and no bound computed
      from the loop alone covers it. What licenses reading this as a licence is
      what these boundaries *are*: dirt, where the scanner missed a patch of the
      surface the loop lies in. That missing patch is a piece of that surface,
      so it is fan-sized and fan-located. It is an assumption about the capture,
      it is named on the record as ``licence_assumption``, and the token is
      ``oriented-and-bounded`` rather than proved. A caller who cannot make that
      assumption about its own capture should require ``closed``.

    Closure is still reported, because a consumer may want to know; it is no
    longer what licenses the answer. What the caps cannot license is the answer
    *near* them, and that is the local licence in ``_region_orientation``.
    """
    closed = topo.boundary_edges == 0 and topo.non_manifold_edges == 0
    # About the mesh centroid: for a closed surface the integral is
    # origin-independent, so this changes nothing on a closed mesh, and for an
    # open one it is the frame that makes the missing caps' bound smallest.
    live = sorted({v for index in topo.valid for v in mesh.triangles[index]})
    origin = _centroid([mesh.vertices[i] for i in live]) if live else (0.0, 0.0, 0.0)
    volume = 0.0
    # A directed edge used twice is two triangles that disagree about which side
    # is out, and that is the whole test: an edge shared by two triangles is
    # traversed twice, so if neither traversal repeats the other they must be
    # opposite. No threshold, and it needs no separate pass over the edge table.
    seen: set[tuple[int, int]] = set()
    inconsistent = 0
    for index in topo.valid:
        a, b, c = mesh.triangles[index]
        pa = _sub(mesh.vertices[a], origin)
        pb = _sub(mesh.vertices[b], origin)
        pc = _sub(mesh.vertices[c], origin)
        volume += _dot(pa, _cross(pb, pc)) / 6.0
        for edge in ((a, b), (b, c), (c, a)):
            if edge in seen:
                inconsistent += 1
            seen.add(edge)

    boundary = _open_boundary(mesh, topo)
    cap_area = 0.0
    cap_volume_bound = 0.0
    for loop in boundary["loops"]:
        if len(loop) < 3:
            continue
        points = [_sub(mesh.vertices[i], origin) for i in loop]
        centre = _centroid(points)
        area = 0.0
        for k in range(len(points)):
            area += 0.5 * _length(
                _cross(_sub(points[k], centre), _sub(points[(k + 1) % len(points)], centre))
            )
        cap_area += area
        cap_volume_bound += max(_length(p) for p in points) * area / 3.0

    consistent = inconsistent == 0
    # Two licences, and the second is *added* to the first rather than replacing
    # it. `closed` is the licence this module has always used, and every verdict
    # measured over the 11 production parts and the benchmark corpus rests on it;
    # tightening it here would be a different change, with its own measurement to
    # make, smuggled into this one. What is new is the second disjunct, which is
    # the one that unlocks a scan: a mesh with dirt on it is not closed and can
    # still carry a usable winding.
    #
    # The record says which one held -- `consistently_oriented` false with
    # `licence` "closed" is a mesh whose signed volume this module is trusting
    # on precedent rather than on measurement. And `bounded` is a bound over
    # fan-sized fillings, not a proof over every filling: see the docstring, and
    # `licence_assumption` on the record.
    # An open or branching boundary chain is not a loop, so nothing computed
    # from the loops bounds a filling of *this* mesh's boundary. The licence
    # that rests on that bound is therefore unavailable, whatever the numbers
    # say.
    open_chains = boundary["open_boundary_chains"]
    bounded = consistent and not open_chains and abs(volume) > cap_volume_bound
    licensed = (closed or bounded) and volume != 0.0
    return {
        "closed": closed,
        "consistently_oriented": consistent,
        "inconsistent_edges": inconsistent,
        "signed_volume": volume,
        "boundary_loop_count": len(boundary["loops"]),
        "open_boundary_chains": open_chains,
        "open_cap_area": cap_area,
        "open_cap_area_fraction": cap_area / topo.total_area if topo.total_area > 0.0 else None,
        "cap_volume_bound": cap_volume_bound,
        "licence_assumption": (
            None
            if closed or not licensed
            else (
                "cap_volume_bound bounds the volume a cap can contribute only for a filling whose "
                "own area does not exceed the centroid fan's and which stays inside the loop's own "
                "radius from the frame origin. A surface spanning the same loop with arbitrarily "
                "greater area is not bounded by it, and no bound computed from the loop alone "
                "covers one. This licence therefore assumes the open boundaries are capture dirt "
                "-- a missed patch of the surface the loop lies in, which is fan-sized and "
                "fan-located. A capture where that does not hold should require licence 'closed'."
            )
        ),
        "licence": ("closed" if closed else "oriented-and-bounded") if licensed else None,
        "winding": ("outward" if volume > 0.0 else "inward") if licensed else None,
        "unavailable_reason": (
            None
            if licensed
            else (
                f"{inconsistent} interior edges are traversed the same way by both their "
                "triangles, so this mesh is neither closed nor consistently wound and its signed "
                "volume carries no inside/outside information"
                if not consistent
                else f"{open_chains} of this mesh's boundary chains do not close -- they branch at "
                "a non-manifold vertex or dead-end -- so nothing computed from its boundary loops "
                "bounds a filling of the boundary it actually has"
                if open_chains
                else f"the surface integral {volume:.6g} does not exceed the "
                f"{cap_volume_bound:.6g} that fan-sized fillings of this mesh's "
                f"{len(boundary['loops'])} open boundary loops could contribute, so the sign is "
                "not bounded"
            )
        ),
        "note": (
            "The winding is licensed either by closure, which is what this module has always used, "
            "or -- for a mesh with dirt on it -- by consistent orientation together with an open "
            "boundary too small for a fan-sized filling to flip the surface integral's sign. "
            "`licence` says which held, and `licence_assumption` says what the second rests on. "
            "Whether the answer holds near a particular boundary loop is a separate, local "
            "question, answered per region in orientation.local_winding."
        ),
    }


def _local_winding(
    triangles: Sequence[int],
    mesh: WeldedMesh,
    topo: _Topology,
    state: dict[str, Any],
) -> dict[str, Any]:
    """Is *this* region far enough from the mesh's dirt for its winding to be usable?

    The global licence says the mesh as a whole carries a usable winding. That is
    a statement about the part, and
    it is not a statement about a region sitting on the lip of a hole: there the
    surface the winding describes simply is not there, and the inside/outside
    question has no answer the mesh can give.

    The local licence is therefore: this region's own triangles, and everything
    within a declared margin of them, touch no boundary and no non-manifold edge.

    The margin is one ``min_feature_size``, derived rather than separately
    declared. ``material_side`` is a claim about which side of *this* surface the
    solid is on, and a surface is only a side of a solid over the feature it
    belongs to -- so dirt within one feature of the region is dirt in the very
    geometry the claim is about, and dirt further away than that is describing a
    different feature. Deriving it from the same declaration that sizes every
    other feature-scale decision here keeps a caller who declares one number from
    having to keep a second one consistent with it.

    Reports the distance to the nearest dirty edge whenever the region is refused
    for one, because "near a hole" is not actionable and "0.42 mm from a boundary
    edge, margin 1.6 mm" is.
    """
    margin = float(state["spec"].value("min_feature_size"))
    cache = state.get("boundary_dirt")
    if cache is None:
        boundary = _open_boundary(mesh, topo)
        dirty = sorted(boundary["dirty_vertices"])
        edges = boundary["dirty_edges"]
        incident: dict[int, list[tuple[int, int]]] = {}
        longest = 0.0
        for edge in edges:
            longest = max(longest, _length(_sub(mesh.vertices[edge[0]], mesh.vertices[edge[1]])))
            incident.setdefault(edge[0], []).append(edge)
            incident.setdefault(edge[1], []).append(edge)
        cache = {
            "vertices": dirty,
            "incident": incident,
            # A dirty edge of length L can pass within `margin` of a point while
            # both its endpoints are as far as hypot(margin, L/2) away, so the
            # vertex query has to reach that far before the point-to-segment
            # distances below can be trusted. On a fine mesh this is barely
            # wider than the margin; on a coarse one it is what stops a long
            # edge sliding past unseen.
            "reach": math.hypot(margin, longest / 2.0),
            "grid": _Grid(mesh.vertices, dirty, max(margin, 1e-9)) if dirty else None,
        }
        state["boundary_dirt"] = cache
    if cache["grid"] is None:
        return {"clean": True, "margin": margin, "nearest_dirty_distance": None}
    grid: _Grid = cache["grid"]
    incident = cache["incident"]
    reach = cache["reach"]
    nearest = math.inf
    for index in triangles:
        corners = [mesh.vertices[vertex] for vertex in mesh.triangles[index]]
        # Every dirty edge that could reach this triangle: found from the
        # triangle's own corners and its centroid, at a radius wide enough that
        # no qualifying edge's endpoints can both fall outside it.
        seen: set[tuple[int, int]] = set()
        for point in corners + [topo.centroids[index]]:
            for other in grid.near(mesh.vertices, point, reach + _extent(corners)):
                for edge in incident.get(other, ()):
                    seen.add(edge)
        for edge in seen:
            # Segment to *triangle*, not segment to four sampled points. A dirty
            # edge can pass inside the margin of a large triangle while every
            # corner and the centroid stay outside it, and a region marked clean
            # on that gets a `material_side` its geometry does not support.
            nearest = min(
                nearest,
                _segment_triangle_distance(
                    mesh.vertices[edge[0]], mesh.vertices[edge[1]], corners
                ),
            )
            if nearest == 0.0:
                break
    return {
        "clean": nearest > margin,
        "margin": margin,
        "margin_basis": "min_feature_size",
        "measured_against": "dirty edge segments, from each triangle's corners and centroid",
        "nearest_dirty_distance": None if nearest == math.inf else nearest,
    }


def _point_segment_distance(point: Vec3, start: Vec3, end: Vec3) -> float:
    """Distance from a point to a segment -- not to its endpoints."""
    span = _sub(end, start)
    length_sq = _dot(span, span)
    if length_sq <= 0.0:
        return _length(_sub(point, start))
    t = max(0.0, min(1.0, _dot(_sub(point, start), span) / length_sq))
    return _length(_sub(point, _add(start, _scale(span, t))))


def _segment_segment_distance(a0: Vec3, a1: Vec3, b0: Vec3, b1: Vec3) -> float:
    """Closest approach of two segments, clamped at both ends.

    Sampled endpoints are not enough for either one: two segments can cross
    within microns of each other with every endpoint far away.  Solved on the
    two parameters, clamped to [0, 1] on each, and falling back to the
    point-to-segment cases where the pair is parallel or degenerate.
    """
    u, v, w = _sub(a1, a0), _sub(b1, b0), _sub(a0, b0)
    uu, uv, vv = _dot(u, u), _dot(u, v), _dot(v, v)
    uw, vw = _dot(u, w), _dot(v, w)
    denominator = uu * vv - uv * uv
    if uu <= 0.0 or vv <= 0.0 or denominator <= 1e-18 * uu * vv:
        # Degenerate or parallel: the minimum is attained at an endpoint.
        return min(
            _point_segment_distance(a0, b0, b1),
            _point_segment_distance(a1, b0, b1),
            _point_segment_distance(b0, a0, a1),
            _point_segment_distance(b1, a0, a1),
        )
    s = max(0.0, min(1.0, (uv * vw - vv * uw) / denominator))
    t = max(0.0, min(1.0, (uu * vw - uv * uw) / denominator))
    # Re-clamp the other parameter against the clamped one, which is what makes
    # the answer right on the boundary of the unit square rather than inside it.
    s = max(0.0, min(1.0, (t * uv - uw) / uu))
    t = max(0.0, min(1.0, (s * uv + vw) / vv))
    return _length(_sub(_add(a0, _scale(u, s)), _add(b0, _scale(v, t))))


def _segment_triangle_distance(start: Vec3, end: Vec3, corners: Sequence[Vec3]) -> float:
    """Closest approach of a segment to a whole triangle, edges and interior.

    Three cases, and all three are needed: the segment can approach an edge, it
    can stand off the face with an endpoint over the interior, or it can pierce
    the interior without coming near any edge at all -- which is zero, and which
    neither of the other two finds.
    """
    normal = _unit(_cross(_sub(corners[1], corners[0]), _sub(corners[2], corners[0])))

    def over_face(point: Vec3) -> bool:
        """Is this point's foot on the face inside the triangle?"""
        height = _dot(_sub(point, corners[0]), normal)
        foot = _sub(point, _scale(normal, height))
        for index in range(3):
            edge = _sub(corners[(index + 1) % 3], corners[index])
            if _dot(_cross(edge, _sub(foot, corners[index])), normal) < 0.0:
                return False
        return True

    if normal is not None:
        # Pierces the face: the segment crosses the plane inside the triangle.
        low = _dot(_sub(start, corners[0]), normal)
        high = _dot(_sub(end, corners[0]), normal)
        if (low <= 0.0 <= high or high <= 0.0 <= low) and low != high:
            crossing = _add(start, _scale(_sub(end, start), low / (low - high)))
            if over_face(crossing):
                return 0.0
    nearest = min(
        _segment_segment_distance(start, end, corners[index], corners[(index + 1) % 3])
        for index in range(3)
    )
    if normal is None:
        return nearest
    for point in (start, end):
        if over_face(point):
            nearest = min(nearest, abs(_dot(_sub(point, corners[0]), normal)))
    return nearest


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
    whenever the mesh's own winding does not license the claim -- globally,
    because the mesh is not consistently wound, or locally, because this region
    is sitting on the mesh's dirt.
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
    local: dict[str, Any] | None = None
    if fit.kind == "plane":
        reason = "a plane encloses no volume; its outward direction is reported instead"
    elif global_orientation["winding"] is not None and fraction is not None:
        local = _local_winding(triangles, mesh, topo, state)
        if not local["clean"]:
            reason = (
                f"this region is {local['nearest_dirty_distance']:.4g} mm from a boundary or "
                f"non-manifold edge, inside the {local['margin']:.4g} mm margin (one declared "
                "min_feature_size); the mesh does not describe a solid there, so which side of "
                "this surface the material is on is not a question its winding can answer"
            )
        else:
            # A curved primitive's own normal points away from its axis or
            # centre. When the winding normal agrees, material is behind the
            # surface (a boss); when it opposes, the surface wraps material (a
            # bore). Licensed globally by consistent orientation and a proved
            # sign, and locally by this region being clear of the mesh's dirt.
            outward_winding = global_orientation["winding"] == "outward"
            agrees = fraction >= 0.5
            material_side = "outside" if agrees == outward_winding else "inside"
            reason = None
    return {
        "surface_normal_agreement": fraction,
        "outward_normal": list(outward_unit) if outward_unit is not None else None,
        "mesh_winding": global_orientation["winding"],
        "mesh_closed": global_orientation["closed"],
        "mesh_consistently_oriented": global_orientation["consistently_oriented"],
        "local_winding": local,
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


def _stage_coverage(state: dict[str, Any]) -> dict[str, Any] | None:
    topo: _Topology = state["topology"]
    mesh: WeldedMesh = state["mesh"]
    regions: list[dict[str, Any]] = state["regions"]
    record = state["record"]
    frame: _PointFrame = state["frame"]

    accepted = [r for r in regions if r["accepted"]]
    _mark_fillet_candidates(
        accepted,
        topo,
        float(state["spec"].value("max_fillet_arc_deg")),
        float(state["spec"].value("max_fillet_radius_rel_spread")),
    )
    covered = sum(r["area"] for r in accepted) / topo.total_area if topo.total_area > 0.0 else 0.0

    # Welded indices on both sides: `topo.valid` is welded, so comparing it
    # against the dump's own indices would silently mismatch on any mesh where
    # welding collapsed a triangle.
    claimed = {t for r in regions for t in r["welded_triangle_indices"]}
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


def _boundary_loops(
    triangles: Sequence[int], mesh: WeldedMesh, topo: _Topology
) -> list[list[int]]:
    """The vertex loops where this face group stops, largest first.

    Fusion's grouping is a partition, so a group's boundary is free evidence
    nobody has spent anything to get: the loop between a bore and the face it
    breaks through is a *circle*, and the loop is shared with the neighbouring
    group rather than being one more reading of the bore's own wall.

    Loops are returned as vertex index lists, unordered within a loop -- a circle
    fit does not care about traversal order, and reconstructing a consistent one
    would be work in aid of nothing.
    """
    owned = set(triangles)
    border: list[tuple[int, int]] = []
    for index in triangles:
        a, b, c = mesh.triangles[index]
        for i, j in ((a, b), (b, c), (c, a)):
            key = (i, j) if i < j else (j, i)
            incident = topo.edges.get(key, ())
            if not any(other in owned for other in incident if other != index):
                border.append(key)
    if not border:
        return []
    adjacency: dict[int, set[int]] = {}
    for i, j in border:
        adjacency.setdefault(i, set()).add(j)
        adjacency.setdefault(j, set()).add(i)
    loops: list[list[int]] = []
    seen: set[int] = set()
    for start in adjacency:
        if start in seen:
            continue
        component = [start]
        seen.add(start)
        frontier = [start]
        while frontier:
            nxt: list[int] = []
            for node in frontier:
                for other in adjacency[node]:
                    if other not in seen:
                        seen.add(other)
                        component.append(other)
                        nxt.append(other)
            frontier = nxt
        loops.append(component)
    loops.sort(key=len, reverse=True)
    return loops


def _boundary_corroboration(
    fit: PrimitiveFit,
    uncertainty: Mapping[str, float],
    triangles: Sequence[int],
    mesh: WeldedMesh,
    topo: _Topology,
    sigmas: float,
    surface_scale: float,
) -> dict[str, Any] | None:
    """Check a turned surface's radius and axis against its own boundary circle.

    The loop is fitted in *its own* best-fit plane, not in the plane the cylinder
    fit produced, so the two readings are independent: the loop's normal is
    evidence about the axis, and the loop's radius is evidence about the radius.
    Agreement strengthens the fit; disagreement beyond the joint uncertainty is a
    named flag and never a silent preference for either number. Nothing here
    changes a parameter -- corroboration that quietly moved the answer would stop
    being corroboration.

    A loop is only evidence when it *is* a circle. The border of a partial-arc
    round is a long rectangle-ish loop around the whole patch, and a circle
    fitted through it is a number with no meaning; loops whose own circle fit
    misses by more than the declared sigmas of measured surface scale are skipped
    rather than reported as a disagreement, because "this is not a circle" and
    "this circle has the wrong radius" are different findings.

    ``None`` when the group has no usable boundary loop, which is the honest
    answer for a group that closes on itself and for one whose border is not
    round.
    """
    axis = fit.parameters.get("axis_direction")
    if axis is None:
        return None
    # A cylinder and a torus carry one radius. A cone's varies along its axis, so
    # the number a loop is comparable to is the cone's own radius *at that loop's
    # station* -- which is what makes ``cone`` in ``_AXIS_KINDS`` true rather than
    # only declared. It was excluded before any loop was looked at, by a dead
    # ``anchor`` local that matched ``axis_point`` and ``center`` and so was
    # always ``None`` for a cone, whose anchor key is ``apex``.
    apex = fit.parameters.get("apex")
    half_angle = fit.parameters.get("half_angle_deg")
    radius = fit.parameters.get("radius")
    taper = 0.0
    if fit.kind == "cone":
        if not isinstance(apex, tuple) or not isinstance(half_angle, float):
            return None
        taper = math.tan(math.radians(half_angle))
        if not math.isfinite(taper) or taper <= 0.0:
            return None
    elif not isinstance(radius, float) or radius <= 0.0:
        return None
    for loop in _boundary_loops(triangles, mesh, topo):
        # Four points fix a circle and its plane with one to spare; fewer is not
        # a small loop, it is no loop.
        if len(loop) < 5:
            continue
        points = [mesh.vertices[i] for i in loop]
        centre = _centroid(points)
        _values, vectors = _symmetric_eigen(_covariance(points, centre))
        normal = vectors[0]
        u, v = _frame(normal)
        circle = _fit_circle_2d(
            [_dot(_sub(p, centre), u) for p in points],
            [_dot(_sub(p, centre), v) for p in points],
        )
        if circle is None:
            continue
        cx, cy, loop_radius = circle
        if not math.isfinite(loop_radius) or loop_radius <= 0.0:
            continue
        residual = _rms(
            math.hypot(_dot(_sub(p, centre), u) - cx, _dot(_sub(p, centre), v) - cy) - loop_radius
            for p in points
        )
        if residual > sigmas * surface_scale:
            continue
        tilt = math.degrees(math.acos(min(1.0, abs(_dot(_unit(normal) or normal, axis)))))
        sigma_r = uncertainty.get("radius")
        sigma_axis = uncertainty.get("axis_direction_deg")
        # Absent sigma means the disagreement cannot be sized, so it is reported
        # as unsized rather than as agreement. Empty is unknown, never zero.
        if fit.kind == "cone":
            # The cone's radius where this loop sits: the loop's own fitted
            # centre, projected onto the axis from the apex, times the taper.
            loop_centre = _add(centre, _add(_scale(u, cx), _scale(v, cy)))
            fitted_radius = taper * _dot(_sub(loop_centre, apex), axis)
            if not math.isfinite(fitted_radius) or fitted_radius <= 0.0:
                continue
        else:
            fitted_radius = float(radius)
        radius_delta = loop_radius - fitted_radius
        agrees_radius = (
            None if sigma_r is None else abs(radius_delta) <= sigmas * max(sigma_r, residual)
        )
        agrees_axis = None if sigma_axis is None else tilt <= sigmas * sigma_axis
        return {
            "loop_point_count": len(loop),
            "loop_radius": loop_radius,
            "loop_circle_rms": residual,
            "fitted_radius": fitted_radius,
            "radius_delta": radius_delta,
            "loop_normal_to_axis_deg": tilt,
            "declared_sigmas": sigmas,
            "radius_sigma": sigma_r,
            "axis_sigma_deg": sigma_axis,
            "agrees_on_radius": agrees_radius,
            "agrees_on_axis": agrees_axis,
            "flag": (
                None
                if agrees_radius is not False and agrees_axis is not False
                else BOUNDARY_CIRCLE_DISAGREES
            ),
            "note": (
                "the boundary loop between this group and its neighbour, fitted as a circle in its "
                "own best-fit plane; independent of the surface fit and never allowed to move it"
            ),
        }
    return None


def _blend_radius(region: dict[str, Any], max_arc_deg: float) -> tuple[float, str] | None:
    """The radius this region would round an edge with, or ``None`` if it rounds none.

    Two shapes qualify. A **torus** is the textbook constant-radius blend and its
    minor radius is the fillet radius. A **partial-arc cylinder** is what Fusion's
    face groups actually deliver an edge round as -- the measured segmentation
    put 298 groups in that bucket, and that is where the fillets are -- and its
    radius is the fillet radius.

    The arc is what separates a round from a bore, and it is measured, not
    assumed: a bore or a boss closes on itself, an edge round never does. The
    ceiling is the caller's. A cylinder whose ``angular_span_deg`` was not
    measured is not a blend candidate, because an absent span is not a small one.
    """
    fit = region["fit"]
    if fit["kind"] == "torus":
        return float(fit["parameters"]["minor_radius"]), "the torus minor radius"
    if fit["kind"] != "cylinder":
        return None
    span = fit.get("support", {}).get("angular_span_deg")
    if not isinstance(span, (int, float)) or isinstance(span, bool):
        return None
    if float(span) > max_arc_deg:
        return None
    return float(fit["parameters"]["radius"]), "the cylinder radius over a partial arc"


def _mark_fillet_candidates(
    accepted: Sequence[dict[str, Any]],
    topo: _Topology,
    max_arc_deg: float,
    max_radius_rel_spread: float,
) -> None:
    """Chain the blend regions along an edge, and call each chain one fillet.

    A real edge round does not arrive as one face group. Fusion's grouping cuts
    it into a *run* of partial-arc cylinders -- the measured segmentation put 298
    groups in that bucket -- and each member of the run touches its two
    neighbouring blends as well as the two faces the round lies between. Marking
    them one at a time produces one "fillet" per tessellation artefact and none
    of them describes the feature: what the rebuild has to emit is a single
    constant-radius fillet on the edge those two faces share.

    So the run is assembled first, from group adjacency, and the chain is the
    candidate. Two blends join a chain when they are adjacent, when their radii
    agree to within the caller's declared relative spread -- a constant-radius
    round is constant, and a run whose radius drifts is not one round -- and when
    they lie between the same two primaries.

    The evidence discipline is unchanged, and is applied to the chain rather than
    to the fragment: a fillet still needs exactly *two* accepted neighbours that
    are themselves non-blend features. A chain against one face, against three,
    or against another chain stays an ordinary run of fits and says so. A lone
    blend is simply a chain of one, which is why this replaces the per-region
    rule rather than sitting beside it.
    """
    owner: dict[int, str] = {}
    for region in accepted:
        # Welded indices, because `topo` is welded. The dump's own indices live
        # in `triangle_indices` for downstream consumers and are not adjacency.
        for index in region["welded_triangle_indices"]:
            owner[index] = region["region_hash"]
    # Resolved for every region first: whether a neighbour is a primary feature
    # cannot depend on the order regions happen to be visited in.
    blends = {r["region_hash"]: _blend_radius(r, max_arc_deg) for r in accepted}
    by_hash = {r["region_hash"]: r for r in accepted}

    neighbours_of: dict[str, set[str]] = {}
    for region in accepted:
        found: set[str] = set()
        for index in region["welded_triangle_indices"]:
            for other in topo.tri_neighbours[index]:
                target = owner.get(other)
                if target is not None and target != region["region_hash"]:
                    found.add(target)
        neighbours_of[region["region_hash"]] = found
        region["adjacent_regions"] = sorted(found)
        region["fillet_candidate"] = False
        region.pop("fillet", None)

    def primaries_of(name: str) -> tuple[str, ...]:
        return tuple(sorted(n for n in neighbours_of[name] if blends.get(n) is None))

    # Connected components over "adjacent blends that lie between the same two
    # primaries", by union of the walk. The radius is deliberately *not* tested
    # link by link: a pairwise test lets a slow drift creep along a run one small
    # step at a time and still call the whole thing one chain. It is tested once,
    # on the assembled chain, against the area-weighted mean below -- which is
    # the stricter check, because every member has to agree with the whole run
    # rather than only with its neighbour.
    seen: set[str] = set()
    for start_hash in sorted(blends):
        if start_hash in seen or blends[start_hash] is None:
            continue
        chain = [start_hash]
        seen.add(start_hash)
        frontier = [start_hash]
        anchor = primaries_of(start_hash)
        while frontier:
            nxt: list[str] = []
            for name in frontier:
                for other in sorted(neighbours_of[name]):
                    if other in seen or blends.get(other) is None:
                        continue
                    if primaries_of(other) != anchor:
                        continue
                    seen.add(other)
                    chain.append(other)
                    nxt.append(other)
            frontier = nxt

        radii = [blends[name][0] for name in chain]  # type: ignore[index]
        areas = [by_hash[name]["area"] for name in chain]
        total = sum(areas)
        mean = (
            sum(r * a for r, a in zip(radii, areas)) / total
            if total > 0.0
            else sum(radii) / len(radii)
        )
        spread = (max(radii) - min(radii)) / mean if mean > 0.0 else math.inf
        # The chain id is the chain's own content, so it is stable across runs
        # and carries no ordering or session state.
        chain_id = hashlib.sha256("|".join(sorted(chain)).encode("utf-8")).hexdigest()
        detail = {
            "id": chain_id,
            "members": sorted(chain),
            "member_count": len(chain),
            "radius_spread_rel": spread,
            "max_radius_rel_spread": max_radius_rel_spread,
            "mean_radius": mean,
        }
        if len(anchor) != 2 or spread > max_radius_rel_spread:
            for name in chain:
                by_hash[name]["fillet_chain"] = dict(
                    detail,
                    accepted=False,
                    reason=(
                        f"this chain lies between {len(anchor)} accepted non-blend regions, and a "
                        "fillet is an edge between exactly two"
                        if len(anchor) != 2
                        else f"the radii along this chain spread by {spread:.4g} of their mean, "
                        f"above the declared {max_radius_rel_spread:g}; a constant-radius round is "
                        "constant"
                    ),
                )
            continue
        source = blends[chain[0]][1]  # type: ignore[index]
        for name in chain:
            region = by_hash[name]
            region["fillet_candidate"] = True
            region["fillet_chain"] = dict(detail, accepted=True, reason=None)
            region["fillet"] = {
                "radius": mean,
                "between": list(anchor),
                "chain_id": chain_id,
                "chain_member_count": len(chain),
                "emission": (
                    f"one filletFeatures on the shared edge for the whole chain; radius = {source}, "
                    f"area-weighted over the chain's {len(chain)} group(s)"
                ),
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
        "face-groups": _stage_face_groups,
        "disproof": _stage_disproof,
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
        # Filled by the topology stage. Zero until then, so a record that refused
        # before topology carries the key with a value U3 rejects rather than an
        # absent key U3 has to guess about.
        "total_area": 0.0,
        # Filled by the noise stage. Null until then, so a record that refused
        # earlier carries the key with a value that reads as "not decided"
        # rather than an absent key a consumer has to guess about.
        "regime": None,
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
