"""The reconstruction program: what will be built, decided before anything is.

This is the reviewable artifact of the reconstruction pipeline — a versioned,
hash-bound, closed-vocabulary *data* description of the model to be built, from
which U4 emits Fusion features.  It is never executable code, and its executor
refuses anything it does not fully understand rather than best-efforting it.

Four things happen here, in this order, because each depends on the last:

1. **Screening.** ``mesh_fitting.propose_design_intent`` measures every
   near-relationship between accepted fits.  Screening is generous on purpose.
2. **Licensing.** Each proposal is re-judged against a tolerance derived from
   the *fits' own uncertainty* — two axes are coaxial when their difference is
   small relative to how well each was measured, not relative to a constant
   somebody typed.  When the record carries no uncertainty, an uncertainty-based
   judgement refuses; it does not silently become an absolute one.
3. **Adoption and reconciliation.** An adopted relationship must be made *true*
   of the numbers, not merely asserted beside them.  Adopted `parameter`
   relationships are re-solved jointly per group (see ``reconcile`` below);
   adopted `constraint` relationships leave the numbers alone and record the
   deviation Fusion's sketch solver will be asked to absorb, which U4 then
   measures per KTD7.  A proposal nobody adopted appears in the program as a
   proposal and in no constraint list.
4. **Frame and archetypes**, derived from the *reconciled* fits, so the datum is
   consistent with the relationships the program asserts.

**What the joint re-solve here is, and what it is not.** Reconciliation projects
the fitted parameters onto the constraint manifold, weighted by inverse
variance: for equal radii that is exactly the maximum-likelihood estimate under
the constraint; for a shared axis it is the first-order one, since the exact
solution needs the position-direction covariance the record does not carry.  It
is **not** a re-solve of the least-squares problem against the region point
sets — those live in the mesh dump, which the fit record does not carry, so U3
cannot reach them.  The distance each parameter moved is recorded per subject as
``shift``, and an adoption whose shift exceeds its own licensing tolerance is
refused rather than recorded, so the residual inconsistency against the original
points is bounded by the same statistic that licensed the relationship.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Callable, Mapping, Sequence

from .manifest import ManifestValidationError, ValidationIssue, _reject_unknown_fields
from .mesh_datum import (
    DATUM_REFUSALS,
    REFUSAL_ALTERNATIVES,
    DatumFrame,
    FitRecord,
    ReconstructionRefused,
    RegionFit,
    TOLERANCE_BASES,
    derive_datum_frame,
    refusal,
    require_uncertainty,
)
from .mesh_fitting import (
    INTENT_KINDS,
    IntentProposal,
    PrimitiveFit,
    Vec3,
    _angle_deg,
    _canonical_direction,
    _dot,
    _length,
    _scale,
    _sub,
    _unit,
    propose_design_intent,
    route_kinematic_group,
)


PROGRAM_VERSION = 1

# R8's archetype vocabulary in full.  This planner assigns only the two U4
# emits; `hole` and `fillet` are U6's, and they are named here so that adding
# them does not need a program version bump.  `unreconstructed` is deliberately
# not an archetype: it is a separate list, so a region that was not rebuilt can
# never be counted as one that was.
ARCHETYPE_KINDS = {"sketch-extrude", "revolve", "hole", "fillet"}

# The fit kinds a fillet proposal may sit on.  A torus is the textbook blend; a
# partial-arc cylinder is what a face-grouped mesh actually delivers an edge
# round as, and U2 measures the arc that separates one from a bore.  This planner
# does not re-measure it -- the fit record carries no angular span -- so the list
# is a vocabulary check on U2's proposal, not a second opinion about the shape.
BLEND_FIT_KINDS = frozenset({"torus", "cylinder"})

ADOPTION_TARGETS = {"parameter", "constraint"}

# A `parameter` adoption must be made true of the numbers, so only the kinds
# reconciliation can actually solve may be adopted that way.  A `constraint`
# adoption hands the relationship to Fusion's sketch solver instead.
PARAMETER_ADOPTABLE = {"coaxial", "parallel", "equal_radius", "nominal"}
CONSTRAINT_ADOPTABLE = {"coaxial", "parallel", "perpendicular", "tangent", "symmetric"}

PROGRAM_SPEC_FIELDS = {"thresholds", "adopted"}
ADOPTION_FIELDS = {"kind", "subjects", "target", "rationale"}

THRESHOLD_FIELDS = {
    "frame_margin",
    "angle_tolerance_deg",
    "offset_tolerance",
    "tangent_tolerance",
    "equal_radius_tolerance",
    "nominal_tolerance",
    "tolerance_basis",
    "sigma_multiple",
    "absolute_angle_tolerance_deg",
    "absolute_length_tolerance",
    # The kinematic router's five gates, nested because they are one decision:
    # they judge a candidate revolve's own motion, and none of them means
    # anything without the other four.
    "motion_evidence",
}

# Every threshold that is a declared number carrying its own rationale.
DECLARED_NUMBERS = (
    "frame_margin",
    "angle_tolerance_deg",
    "offset_tolerance",
    "tangent_tolerance",
    "equal_radius_tolerance",
    "nominal_tolerance",
    "sigma_multiple",
)

PROGRAM_REFUSALS = DATUM_REFUSALS | {
    "adoption-unmeasured",
    "adoption-unlicensed",
    "adoption-unsupported-target",
    "adoption-conflict",
    "adoption-shift-exceeds-license",
}

PROGRAM_REFUSAL_ALTERNATIVES = dict(REFUSAL_ALTERNATIVES) | {
    "adoption-unmeasured": (
        "Adopt only relationships this run measured. Widen the screening tolerances and re-run if the "
        "relationship should have been proposed and was not."
    ),
    "adoption-unlicensed": (
        "The measured deviation is larger than the fits' own uncertainty allows. Either the "
        "relationship is not there, or the fits are worse than the sigma_multiple assumes."
    ),
    "adoption-unsupported-target": (
        "Adopt this kind as a sketch constraint instead, or as a shared parameter instead, whichever "
        "this kind supports."
    ),
    "adoption-conflict": (
        "Two adoptions demand different values for the same parameter. Drop one, or reconcile them "
        "upstream by adopting the relationship that subsumes both."
    ),
    "adoption-shift-exceeds-license": (
        "Making this relationship true moves a parameter further than the measurement supports. This "
        "is usually a chain of pairwise relationships whose ends are further apart than either pair."
    ),
}


def _refuse(reason: str, message: str, detail: dict[str, Any] | None = None) -> ReconstructionRefused:
    return refusal(
        reason,
        message,
        detail,
        vocabulary=PROGRAM_REFUSALS,
        alternatives=PROGRAM_REFUSAL_ALTERNATIVES,
    )


# --------------------------------------------------------------------------
# 1. licensing a proposal against the fits' own uncertainty
# --------------------------------------------------------------------------

_DIRECTION_SIGMAS = {
    "plane": (("normal_deg", 1.0),),
    "cylinder": (("axis_direction_deg", 1.0),),
    "cone": (("axis_direction_deg", 1.0),),
}

_RADIUS_SIGMAS = {
    "cylinder": (("radius", 1.0),),
    "sphere": (("radius", 1.0),),
}

# Which sigmas contribute to the deviation each proposal reports, keyed by
# (kind, deviation unit) and then by the fit's own kind.  A pair this table
# cannot reach is *unlicensable*: reported, and not adoptable.  It is never
# licensed by omission.
LICENSE_SIGMAS: dict[tuple[str, str], dict[str, tuple[tuple[str, float], ...]]] = {
    ("coaxial", "length"): {"cylinder": (("axis_point", 1.0),), "cone": (("apex", 1.0),)},
    ("parallel", "deg"): _DIRECTION_SIGMAS,
    ("perpendicular", "deg"): _DIRECTION_SIGMAS,
    ("symmetric", "deg"): _DIRECTION_SIGMAS,
    ("symmetric", "length"): _RADIUS_SIGMAS,
    ("tangent", "length"): {
        "plane": (("offset", 1.0),),
        "cylinder": (("axis_point", 1.0), ("radius", 1.0)),
    },
    ("equal_radius", "length"): _RADIUS_SIGMAS,
    # A nominal proposal is about a diameter, so the radius sigma doubles.
    ("nominal", "length"): {"cylinder": (("radius", 2.0),), "sphere": (("radius", 2.0),)},
}


def _subject_regions(
    proposal: IntentProposal, by_hash: Mapping[str, RegionFit]
) -> list[RegionFit] | None:
    out: list[RegionFit] = []
    for subject in proposal.subjects:
        # A nominal proposal names "<region hash> diameter"; every other kind
        # names the region directly.
        region = by_hash.get(subject) or by_hash.get(subject.split(" ")[0])
        if region is None:
            return None
        out.append(region)
    return out


def license_proposal(
    proposal: IntentProposal,
    by_hash: Mapping[str, RegionFit],
    *,
    basis: str,
    sigma_multiple: float,
    absolute_angle_tolerance_deg: float,
    absolute_length_tolerance: float,
) -> dict[str, Any]:
    """Judge one proposal against a tolerance, and say where the tolerance came from.

    Returns the judgement as data.  ``licensed`` false with basis
    ``unlicensable`` means *we have no statistic for this pair* — which is not
    the same as, and must never be reported as, "the relationship is absent".
    """
    regions = _subject_regions(proposal, by_hash)
    table = LICENSE_SIGMAS.get((proposal.kind, proposal.deviation_unit))
    if regions is None or table is None:
        return {
            "licensed": False,
            "basis": "unlicensable",
            "tolerance": None,
            "reason": (
                "no uncertainty model covers this proposal's kind, unit or subject kinds, so it "
                "cannot be licensed and cannot be adopted."
            ),
        }
    if basis == "declared-absolute":
        tolerance = (
            absolute_angle_tolerance_deg
            if proposal.deviation_unit == "deg"
            else absolute_length_tolerance
        )
        return {
            "licensed": proposal.deviation <= tolerance,
            "basis": "declared-absolute",
            "tolerance": tolerance,
            "reason": "judged against the caller's declared absolute tolerance, not against the fits.",
        }

    total = 0.0
    contributions: dict[str, float] = {}
    for region in regions:
        assert region.fit is not None  # accepted fits only reach here
        entry = table.get(region.fit.kind)
        if entry is None:
            return {
                "licensed": False,
                "basis": "unlicensable",
                "tolerance": None,
                "reason": (
                    f"no uncertainty model for a {region.fit.kind} in a {proposal.kind} proposal."
                ),
            }
        for key, scale in entry:
            sigma = region.sigma(key)
            if sigma is None:
                return {
                    "licensed": False,
                    "basis": "unlicensable",
                    "tolerance": None,
                    "reason": f"region {region.region_hash[:12]} carries no uncertainty for {key}.",
                }
            contributions[f"{region.region_hash[:12]}.{key}"] = sigma * scale
            total += (sigma * scale) ** 2
    tolerance = sigma_multiple * math.sqrt(total)
    return {
        "licensed": proposal.deviation <= tolerance,
        "basis": "uncertainty",
        "tolerance": tolerance,
        "sigma_multiple": sigma_multiple,
        "combined_sigma": math.sqrt(total),
        "contributions": contributions,
        "reason": (
            "the measured deviation is compared against the combined standard deviation of the "
            "parameters it is built from, scaled by the declared sigma_multiple."
        ),
    }


# --------------------------------------------------------------------------
# 2. adoption and joint reconciliation
# --------------------------------------------------------------------------


class _Groups:
    """Union-find over region hashes, so a chain of pairs solves as one group."""

    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Merge towards the lexicographically smaller root so the grouping
            # does not depend on the order the pairs arrived in.
            self.parent[max(ra, rb)] = min(ra, rb)

    def grouped(self) -> list[tuple[str, ...]]:
        out: dict[str, list[str]] = {}
        for item in sorted(self.parent):
            out.setdefault(self.find(item), []).append(item)
        return [tuple(sorted(members)) for _root, members in sorted(out.items())]


def _weights(regions: Sequence[RegionFit], key: str) -> list[float]:
    """Inverse-variance weights, or equal weights when there is no variance.

    Equal weighting is a stated fallback rather than a hidden one: the caller
    already chose ``declared-absolute`` to get here, and the choice is recorded
    beside the result.
    """
    # Note this is independent of the licensing basis: uncertainty is used for
    # weighting whenever the record carries it, because a better-measured fit
    # should pull harder regardless of which tolerance the caller chose to
    # judge the relationship by.
    sigmas = [region.sigma(key) for region in regions]
    if any(sigma is None or sigma <= 0.0 for sigma in sigmas):
        return [1.0] * len(regions)
    return [1.0 / (sigma * sigma) for sigma in sigmas]  # type: ignore[operator]


def _weighted_direction(regions: Sequence[RegionFit], weights: Sequence[float]) -> Vec3 | None:
    reference = regions[0].direction()
    if reference is None:
        return None
    total: Vec3 = (0.0, 0.0, 0.0)
    for region, weight in zip(regions, weights):
        direction = region.direction()
        if direction is None:
            return None
        sign = 1.0 if _dot(direction, reference) >= 0.0 else -1.0
        scaled = _scale(direction, sign * weight)
        total = (total[0] + scaled[0], total[1] + scaled[1], total[2] + scaled[2])
    unit = _unit(total)
    return None if unit is None else _canonical_direction(unit)


def _weighted_point(points: Sequence[Vec3], weights: Sequence[float]) -> Vec3:
    total = sum(weights)
    return (
        sum(p[0] * w for p, w in zip(points, weights)) / total,
        sum(p[1] * w for p, w in zip(points, weights)) / total,
        sum(p[2] * w for p, w in zip(points, weights)) / total,
    )


def _distance_to_line(point: Vec3, anchor: Vec3, direction: Vec3) -> float:
    offset = _sub(point, anchor)
    return _length(_sub(offset, _scale(direction, _dot(offset, direction))))


@dataclass(frozen=True, slots=True)
class Reconciliation:
    """What making the adopted relationships true did to the fitted numbers."""

    regions: dict[str, RegionFit]
    shifts: tuple[dict[str, Any], ...]

    def to_dict(self) -> list[dict[str, Any]]:
        return [dict(shift) for shift in self.shifts]


def _anchor_key(kind: str) -> str:
    return "apex" if kind == "cone" else "axis_point"


def reconcile(
    by_hash: Mapping[str, RegionFit],
    adoptions: Sequence[dict[str, Any]],
    tolerances: Mapping[str, float | None],
) -> Reconciliation:
    """Re-solve the fitted parameters so the adopted relationships are true of them.

    Groups first, then one joint solve per group: a chain of pairwise adoptions
    that all name the same parameter is one constraint, not several applied in
    whatever order they were written down.  Every moved parameter is checked
    against the licensing tolerance of the adoptions that moved it, so a chain
    whose ends are further apart than any of its links refuses instead of
    quietly averaging them together.
    """
    axis_groups, parallel_groups, radius_groups = _Groups(), _Groups(), _Groups()
    nominal: dict[str, float] = {}
    budget: dict[str, float] = {}

    for adoption in adoptions:
        if adoption["target"] != "parameter":
            continue
        kind = adoption["kind"]
        hashes = [subject.split(" ")[0] for subject in adoption["subjects"]]
        tolerance = tolerances.get(adoption["proposal_id"])
        for region_hash in hashes:
            if tolerance is not None:
                budget[region_hash] = max(budget.get(region_hash, 0.0), tolerance)
        if kind == "coaxial":
            axis_groups.union(hashes[0], hashes[1])
        elif kind == "parallel":
            parallel_groups.union(hashes[0], hashes[1])
        elif kind == "equal_radius":
            radius_groups.union(hashes[0], hashes[1])
        elif kind == "nominal":
            value = adoption["proposed_value"]
            existing = nominal.get(hashes[0])
            if existing is not None and existing != value:
                raise _refuse(
                    "adoption-conflict",
                    f"region {hashes[0][:12]} is adopted to two different nominal values "
                    f"({existing:g} and {value:g}).",
                    {"region_hash": hashes[0], "values": [existing, value]},
                )
            nominal[hashes[0]] = float(value)

    axis_members = {member for group in axis_groups.grouped() for member in group}
    for group in parallel_groups.grouped():
        overlap = sorted(set(group) & axis_members)
        if overlap:
            raise _refuse(
                "adoption-conflict",
                "a region is adopted both coaxial and parallel as parameters; coaxial already fixes "
                "the direction, so the two would set it twice.",
                {"regions": overlap},
            )

    updated: dict[str, RegionFit] = dict(by_hash)
    shifts: list[dict[str, Any]] = []

    def parameters_of(region_hash: str) -> dict[str, Any]:
        fit = updated[region_hash].fit
        assert fit is not None
        return dict(fit.parameters)

    def replace(region_hash: str, parameters: dict[str, Any]) -> None:
        region = updated[region_hash]
        assert region.fit is not None
        fit = region.fit
        updated[region_hash] = region.with_fit(
            PrimitiveFit(
                kind=fit.kind,
                accepted=fit.accepted,
                rms_residual=fit.rms_residual,
                relative_residual=fit.relative_residual,
                extent=fit.extent,
                parameters=parameters,
                rejection=fit.rejection,
            )
        )

    def record(region_hash: str, parameter: str, before: Any, after: Any, magnitude: float, unit: str, constraint: str) -> None:
        tolerance = budget.get(region_hash)
        # Only length shifts are gated. An angular shift is bounded by
        # construction: a weighted mean of unit vectors lies inside the cone
        # they span, so it can never exceed the screening angle every member
        # pair already passed. It is still recorded, because "bounded" is not
        # "zero" and the reader should see what moved.
        if tolerance is not None and magnitude > tolerance and unit == "length":
            raise _refuse(
                "adoption-shift-exceeds-license",
                f"making {constraint} true moves {region_hash[:12]}.{parameter} by "
                f"{magnitude:.6g}, beyond the {tolerance:.6g} its licensing tolerance allows.",
                {
                    "region_hash": region_hash,
                    "parameter": parameter,
                    "shift": magnitude,
                    "tolerance": tolerance,
                    "constraint": constraint,
                },
            )
        shifts.append(
            {
                "region_hash": region_hash,
                "parameter": parameter,
                "constraint": constraint,
                "before": list(before) if isinstance(before, tuple) else before,
                "after": list(after) if isinstance(after, tuple) else after,
                "shift": magnitude,
                "shift_unit": unit,
                "tolerance": tolerance,
            }
        )

    for group in axis_groups.grouped():
        members = [updated[h] for h in group]
        weights = _weights(members, "axis_direction_deg")
        direction = _weighted_direction(members, weights)
        anchors = [region.anchor() for region in members]
        if direction is None or any(anchor is None for anchor in anchors):
            raise _refuse(
                "adoption-conflict",
                "a region adopted coaxial carries no axis to reconcile.",
                {"regions": list(group)},
            )
        position_weights = _weights(members, _anchor_key(members[0].fit.kind))  # type: ignore[union-attr]
        centre = _weighted_point([a for a in anchors if a is not None], position_weights)
        # Put the shared anchor on the shared axis, at the station the members'
        # own anchors average to.
        for region_hash, region, anchor in zip(group, members, anchors):
            assert region.fit is not None and anchor is not None
            key = _anchor_key(region.fit.kind)
            # Keep each member's own station along the shared axis; only the
            # off-axis part of its anchor is what coaxiality actually fixes.
            station = _dot(_sub(anchor, centre), direction)
            new_anchor = (
                centre[0] + direction[0] * station,
                centre[1] + direction[1] * station,
                centre[2] + direction[2] * station,
            )
            parameters = parameters_of(region_hash)
            old_direction = parameters.get("axis_direction")
            parameters["axis_direction"] = direction
            parameters[key] = new_anchor
            replace(region_hash, parameters)
            record(
                region_hash,
                key,
                anchor,
                new_anchor,
                _distance_to_line(anchor, centre, direction),
                "length",
                f"coaxial group {group[0][:12]}",
            )
            if isinstance(old_direction, tuple):
                record(
                    region_hash,
                    "axis_direction",
                    old_direction,
                    direction,
                    _angle_deg(old_direction, direction),
                    "deg",
                    f"coaxial group {group[0][:12]}",
                )

    for group in parallel_groups.grouped():
        members = [updated[h] for h in group]
        weights = _weights(members, "axis_direction_deg")
        direction = _weighted_direction(members, weights)
        if direction is None:
            raise _refuse(
                "adoption-conflict",
                "a region adopted parallel carries no direction to reconcile.",
                {"regions": list(group)},
            )
        for region_hash, region in zip(group, members):
            assert region.fit is not None
            key = "normal" if region.fit.kind == "plane" else "axis_direction"
            parameters = parameters_of(region_hash)
            before = parameters.get(key)
            parameters[key] = direction
            if key == "normal" and isinstance(parameters.get("point_on_plane"), tuple):
                parameters["offset"] = _dot(direction, parameters["point_on_plane"])
            replace(region_hash, parameters)
            if isinstance(before, tuple):
                record(
                    region_hash,
                    key,
                    before,
                    direction,
                    _angle_deg(before, direction),
                    "deg",
                    f"parallel group {group[0][:12]}",
                )

    radius_group_of: dict[str, tuple[str, ...]] = {}
    for group in radius_groups.grouped():
        for member in group:
            radius_group_of[member] = group
    handled: set[tuple[str, ...]] = set()
    singles = [(h,) for h in sorted(nominal) if h not in radius_group_of]
    for group in radius_groups.grouped() + singles:
        if group in handled:
            continue
        handled.add(group)
        members = [updated[h] for h in group]
        radii = [region.fit.parameters.get("radius") for region in members]  # type: ignore[union-attr]
        if any(not isinstance(radius, float) for radius in radii):
            raise _refuse(
                "adoption-conflict",
                "a region adopted for a shared or nominal radius has no fitted radius.",
                {"regions": list(group)},
            )
        weights = _weights(members, "radius")
        shared = sum(r * w for r, w in zip(radii, weights)) / sum(weights)  # type: ignore[operator]
        snaps = {nominal[h] for h in group if h in nominal}
        if len(snaps) > 1:
            raise _refuse(
                "adoption-conflict",
                "one shared-radius group is adopted to two different nominal diameters, so the "
                "shared parameter has no single value.",
                {"regions": list(group), "values": sorted(snaps)},
            )
        constraint = f"equal-radius group {group[0][:12]}" if len(group) > 1 else "nominal snap"
        if snaps:
            shared = snaps.pop() / 2.0
            constraint = f"{constraint} snapped to nominal"
        for region_hash, region, radius in zip(group, members, radii):
            parameters = parameters_of(region_hash)
            parameters["radius"] = shared
            replace(region_hash, parameters)
            record(region_hash, "radius", radius, shared, abs(shared - float(radius)), "length", constraint)  # type: ignore[arg-type]

    return Reconciliation(regions=updated, shifts=tuple(shifts))


# --------------------------------------------------------------------------
# 3. archetype planning
# --------------------------------------------------------------------------


def _is_coaxial_with(
    region: RegionFit, origin: Vec3, z: Vec3, angle_tol: float, offset_tol: float
) -> bool:
    """Is this region a surface of revolution about the axis, on its own evidence?

    A *turned* surface answers with its fitted axis: same direction, same line.

    A **plane** cannot answer with its normal, and this is where the planner used
    to go wrong: a plane perpendicular to the axis was taken as a surface of
    revolution about it, so every cap, ledge and rectangular plate in the part
    joined the revolve.  A plane's normal field genuinely cannot tell an annulus
    from a rectangular plate -- both are ``+-z`` everywhere -- so the normals are
    not the evidence to ask.  Its *footprint* is: a disc or an annulus swept
    about the axis is centred on the axis, and its axis-aligned bounding box is
    centred on it exactly.  A plate whose axis passes near one corner is not, and
    the offset is metres of millimetres rather than tolerance-sized -- measured
    over the eleven-part benchmark, every large coaxial plane's box centre sat
    23 to 160 mm off the candidate axis, and not one of them was turned.

    The tolerance is the caller's already-declared ``offset_tolerance``, which is
    the same question it was declared for: how far off the axis a thing may sit
    before it is not on the axis.  A partial annulus -- a shoulder with a flat
    milled across it -- fails this and joins the extrude instead, which is the
    conservative direction: it is left out of a revolve rather than dragging a
    revolve into existence.
    """
    direction, anchor = region.direction(), region.anchor()
    if direction is None or anchor is None or region.fit is None:
        return False
    if region.fit.kind == "plane":
        if _angle_deg(direction, z) > angle_tol:
            return False
        lo, hi = region.bounding_box
        centre = ((lo[0] + hi[0]) / 2.0, (lo[1] + hi[1]) / 2.0, (lo[2] + hi[2]) / 2.0)
        return _distance_to_line(centre, origin, z) <= offset_tol
    if _angle_deg(direction, z) > angle_tol:
        return False
    return _distance_to_line(anchor, origin, z) <= offset_tol


# The router's gates, as this planner names them in a program spec. Declared
# together or not at all: four of the five are meaningless without the fifth,
# and a partially declared router would run against numbers nobody chose.
MOTION_GATE_FIELDS = (
    "sigma_theta_deg",
    "residual_sigma_factor",
    "eigengap_min",
    "translation_epsilon",
    "pitch_epsilon",
)


def _motion_evidence(
    regions: Sequence[RegionFit],
    frame: DatumFrame,
    gates: Mapping[str, float] | None,
    angle_tolerance_deg: float,
    offset_tolerance: float,
) -> dict[str, Any]:
    """Does this candidate group's own motion certify a rotation about the datum axis?

    ``mesh_fitting.route_kinematic_surface`` answers extrusion, revolution and
    helix from one 6x6 eigenproblem over the facet normals, and every region
    carries the raw block for its own facets, so the group's system is the sum
    of its members'.  Three things make this a real discriminator rather than a
    restatement of the group's membership:

    * the weights are **areas**, re-normalized over the group, so a 4 mm^2
      corner round contributes 4 mm^2 of evidence against a 2000 mm^2 plate --
      which is why a plate with one small coaxial round comes back ambiguous
      rather than "a solid of revolution";
    * the eigengap gate asks whether the invariant motion is *unique*.  A stack
      of coaxial cylinders admits a rotation and a translation both, and picking
      the rotation out of that two-parameter family is a guess;
    * the recovered axis is checked against the datum axis this program would
      actually revolve about, so a rotation about some *other* line never
      licenses a revolve about this one.

    Returns the decision as data, always.  ``confirmed`` false is never silence:
    it carries the router's own record, or the named reason the router could not
    be run at all.
    """
    if gates is None:
        return {
            "confirmed": False,
            "reason": "motion-evidence-undeclared",
            "detail": (
                "no motion_evidence thresholds were declared, so this program has no gate to judge "
                "a candidate revolve's motion against. A revolve asserts that the whole group is "
                "swept by one rotation, and that assertion is not made on an undeclared gate."
            ),
            "router": None,
        }
    missing = [region.region_hash for region in regions if region.motion_moments is None]
    if missing:
        return {
            "confirmed": False,
            "reason": "motion-evidence-unavailable",
            "detail": (
                f"{len(missing)} of this group's {len(regions)} regions carry no facet moment block, "
                "so the group's invariant motion cannot be measured. An older fit record carries "
                "none; re-run `fit-regions` against the same dump to add them."
            ),
            "router": None,
            "regions_without_moments": sorted(missing),
        }
    lo = [min(r.bounding_box[0][i] for r in regions) for i in range(3)]
    hi = [max(r.bounding_box[1][i] for r in regions) for i in range(3)]
    extent = _length((hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]))
    try:
        router = route_kinematic_group(
            [region.motion_moments for region in regions],  # type: ignore[misc]
            extent,
            sigma_theta_rad=math.radians(gates["sigma_theta_deg"]),
            residual_sigma_factor=gates["residual_sigma_factor"],
            eigengap_min=gates["eigengap_min"],
            translation_epsilon=gates["translation_epsilon"],
            pitch_epsilon=gates["pitch_epsilon"],
        )
    except ValueError as error:
        return {
            "confirmed": False,
            "reason": "motion-evidence-unavailable",
            "detail": f"the router could not be run over this group: {error}",
            "router": None,
        }
    if router["verdict"] != "revolution":
        return {
            "confirmed": False,
            "reason": f"motion-{router['refusal'] or router['verdict'] or 'none'}",
            "detail": (
                "this group's own facets do not show it swept by a rotation: "
                + str(router.get("reason", "the router reached no verdict."))
                + " A perpendicular cap is consistent with a revolve and is not evidence for one, "
                "so the group falls through to the next archetype in the precedence."
            ),
            "router": router,
        }
    direction = _unit(tuple(router["direction"]))  # type: ignore[arg-type]
    axis_point = tuple(router["axis_point"])  # type: ignore[assignment]
    tilt = 180.0 if direction is None else _angle_deg(direction, frame.z_axis)
    offset = _distance_to_line(axis_point, frame.origin, frame.z_axis)  # type: ignore[arg-type]
    if tilt > angle_tolerance_deg or offset > offset_tolerance:
        return {
            "confirmed": False,
            "reason": "motion-axis-mismatch",
            "detail": (
                f"the group is swept by a rotation, but about a line {tilt:.6g} degrees from the "
                f"datum Z axis and {offset:.6g} away from it, against declared tolerances of "
                f"{angle_tolerance_deg:.6g} and {offset_tolerance:.6g}. A revolve here would turn "
                "the profile about an axis the geometry does not name."
            ),
            "router": router,
            "axis_tilt_deg": tilt,
            "axis_offset": offset,
        }
    return {
        "confirmed": True,
        "reason": "motion-revolution-confirmed",
        "detail": (
            "the group's facet normals are invariant under a single rotation about the datum Z "
            "axis, and under no other one-parameter motion: that is affirmative evidence of a "
            "surface of revolution, not merely consistency with one."
        ),
        "router": router,
        "axis_tilt_deg": tilt,
        "axis_offset": offset,
    }


def _datum_plane_for_normal(frame: DatumFrame, normal: Vec3, angle_tol: float) -> str | None:
    """Which origin plane a normal is expressible against, or ``None``.

    ``ConstructionPlaneInput.setByPlane`` is direct-edit-only, so a sketch plane
    in a parametric design must be an origin plane or an offset from one.  A
    plane whose normal is oblique to every datum axis is therefore not something
    this program may ask for; it becomes an unreconstructed region naming
    ``plane-unmappable``, host-side, before any transaction exists.
    """
    for axis, name in ((frame.z_axis, "XY"), (frame.x_axis, "YZ"), (frame.y_axis, "XZ")):
        if _angle_deg(normal, axis) <= angle_tol:
            return name
    return None


def _frame_station(frame: DatumFrame, axis: Vec3, point: Vec3) -> float:
    """A point's offset along a datum axis, measured from the datum origin."""
    return _dot(axis, _sub(point, frame.origin))


def _plane_axis(frame: DatumFrame, datum_plane: str) -> Vec3:
    return {"XY": frame.z_axis, "YZ": frame.x_axis, "XZ": frame.y_axis}[datum_plane]


# The two datum axes that lie *in* each origin plane, in the order a sketch on
# that plane uses them. Defined here because the archetype planner is the first
# stage that needs them; the emitter imports this rather than restating it, so
# the sketch's u/v axes and the program's cannot drift apart.
IN_PLANE_AXES = {"XY": ("X", "Y"), "XZ": ("X", "Z"), "YZ": ("Y", "Z")}


def _named_axis(frame: DatumFrame, name: str) -> Vec3:
    return {"X": frame.x_axis, "Y": frame.y_axis, "Z": frame.z_axis}[name]


def _cap_station(region: RegionFit, normal: Vec3) -> float:
    anchor = region.anchor()
    assert anchor is not None
    return _dot(normal, anchor)


def _extrude_caps(
    regions: Sequence[RegionFit], angle_tolerance_deg: float
) -> tuple[RegionFit, RegionFit, Vec3] | None:
    """The most separated pair of parallel planes, chosen deterministically."""
    planes = [
        region
        for region in regions
        if region.fit is not None and region.fit.kind == "plane" and region.anchor() is not None
    ]
    best: tuple[Any, ...] | None = None
    for index, first in enumerate(planes):
        for second in planes[index + 1 :]:
            a, b = first.direction(), second.direction()
            if a is None or b is None or _angle_deg(a, b) > angle_tolerance_deg:
                continue
            separation = abs(_cap_station(second, a) - _cap_station(first, a))
            if separation <= 0.0:
                continue
            key = (-separation, first.region_hash, second.region_hash)
            if best is None or key < best[0]:
                low, high = (
                    (first, second)
                    if _cap_station(first, a) <= _cap_station(second, a)
                    else (second, first)
                )
                best = (key, low, high, a)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _is_extrude_side(region: RegionFit, normal: Vec3, angle_tolerance_deg: float) -> bool:
    direction = region.direction()
    if direction is None or region.fit is None:
        return False
    if region.fit.kind == "plane":
        return abs(_angle_deg(direction, normal) - 90.0) <= angle_tolerance_deg
    return _angle_deg(direction, normal) <= angle_tolerance_deg


def _archetype_id(kind: str, regions: Sequence[str]) -> str:
    return f"{kind}-{sorted(regions)[0][:12]}"


def _station_range(frame: DatumFrame, axis: Vec3, box: tuple[Vec3, Vec3]) -> tuple[float, float]:
    """How far a region reaches along a datum axis, from its bounding box.

    All eight corners are projected rather than the two given points, because the
    box is axis-aligned in *mesh* coordinates and the datum axis need not be.  For
    the case this is used on — a bore whose axis has just been shown parallel to
    this very axis — the projection is exact.
    """
    lo, hi = box
    stations = [
        _frame_station(frame, axis, (x, y, z))
        for x in (lo[0], hi[0])
        for y in (lo[1], hi[1])
        for z in (lo[2], hi[2])
    ]
    return min(stations), max(stations)


def _plan_holes(
    bores: Sequence[RegionFit],
    groups: Sequence[Mapping[str, Any]],
    frame: DatumFrame,
    angle_tolerance_deg: float,
    offset_tolerance: float,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Turn inward cylinders into hole features, or gate each one by name.

    The discriminator is ``material_side == "inside"``, which the caller has
    already applied; what is decided here is whether a bore has somewhere to be a
    hole *in*.  A hole is a cut, and a cut needs a body, an axis this design can
    express, and containment — and a bore that fails any of the three is left
    unreconstructed naming which, never widened into a hole on the strength of
    the two it passed.
    """
    gates: dict[str, str] = {}
    bases = [group for group in groups if group["kind"] in ("sketch-extrude", "revolve")]
    if len(bases) != 1:
        reason = (
            "this program builds no body for a hole to cut."
            if not bases
            else (
                f"this program builds {len(bases)} bodies and nothing in the fit record says which "
                "one this bore is a hole in; choosing would be a guess with a 1-in-"
                f"{len(bases)} chance of cutting the wrong body."
            )
        )
        for bore in bores:
            gates[bore.region_hash] = f"hole-base-ambiguous: {reason}"
        return [], gates
    base = bases[0]
    if base["kind"] != "sketch-extrude":
        for bore in bores:
            gates[bore.region_hash] = (
                "hole-base-not-extruded: the only body this program builds is a revolve, whose "
                "half-profile already rebuilds every surface coaxial with its axis. A bore that is "
                "not coaxial with it is a real feature and this unit does not place one against a "
                "revolved body."
            )
        return [], gates

    datum_plane = str(base["plane"]["datum_plane"])
    axis = _plane_axis(frame, datum_plane)
    u_name, v_name = IN_PLANE_AXES[datum_plane]
    u_axis, v_axis = _named_axis(frame, u_name), _named_axis(frame, v_name)
    base_lo = float(base["plane"]["offset"])
    base_hi = base_lo + float(base["extent"]["value"])

    holes: list[dict[str, Any]] = []
    for bore in bores:
        direction = bore.direction()
        assert direction is not None and bore.fit is not None
        if _datum_plane_for_normal(frame, direction, angle_tolerance_deg) != datum_plane:
            gates[bore.region_hash] = (
                "hole-axis-oblique: the bore's axis is not parallel to the extrusion direction of "
                f"the body it would cut (datum {datum_plane}). A hole is placed on the body's own "
                "sketch plane, so an axis oblique to it has no placement this unit can express."
            )
            continue
        low, high = _station_range(frame, axis, bore.bounding_box)
        if low < base_lo - offset_tolerance or high > base_hi + offset_tolerance:
            gates[bore.region_hash] = (
                f"hole-not-contained: the bore spans {low:.6g} to {high:.6g} along datum "
                f"{datum_plane}'s normal and the body it would cut spans {base_lo:.6g} to "
                f"{base_hi:.6g}. A cut that starts or ends outside the body it cuts is not a hole "
                "in it."
            )
            continue
        anchor = bore.anchor()
        assert anchor is not None
        radius = bore.fit.parameters.get("radius")
        if not isinstance(radius, float) or radius <= 0.0:
            gates[bore.region_hash] = (
                "hole-radius-absent: the accepted cylinder fit carries no positive radius, so no "
                "diameter can be written for the hole."
            )
            continue
        identifier = _archetype_id("hole", [bore.region_hash])
        holes.append(
            {
                "id": identifier,
                "kind": "hole",
                "operation": "cut",
                "regions": [bore.region_hash],
                # The hole's own sketch plane, at the station where the bore
                # starts -- not the body's, so a blind hole is placed where the
                # bore actually is rather than where the body happens to begin.
                "plane": {"datum_plane": datum_plane, "offset": low, "rotation": None},
                "hole": {
                    "diameter": {"parameter": None, "value": 2.0 * radius},
                    "position": {
                        "u_axis": u_name,
                        "v_axis": v_name,
                        "u": {"parameter": None, "value": _frame_station(frame, u_axis, anchor)},
                        "v": {"parameter": None, "value": _frame_station(frame, v_axis, anchor)},
                    },
                },
                "profile": None,
                "profile_source": "fit-primitive",
                "extent": {"kind": "distance", "parameter": None, "value": high - low},
                "constraints": [],
                "dependencies": [str(base["id"])],
                "reason": (
                    f"an accepted cylinder fit whose material_side is 'inside' -- the mesh's own "
                    f"winding puts solid on the far side of this surface -- lying wholly within "
                    f"{base['id']} with its axis along datum {datum_plane}'s normal. That is a bore, "
                    "and a bore is a hole."
                ),
            }
        )
    return holes, gates


def _same_feature_edge(
    group: Mapping[str, Any], first: str, second: str
) -> tuple[str | None, str | None]:
    """Which pair of one archetype's own face sets a blend sits between.

    Fusion rounds an edge between two faces of a single feature as readily as one
    between two features, so a blend whose neighbours share an owner is not
    automatically unroundable -- but the *edge* still has to be nameable, and the
    only archetype whose faces come partitioned is the extrude:
    ``ExtrudeFeature`` hands back ``startFaces``, ``endFaces`` and ``sideFaces``,
    and this program already recorded which of its regions were caps and in which
    station order.  A revolve's faces carry no such partition, so a blend inside
    one names no edge and keeps its refusal.

    Returns ``(selector, None)`` or ``(None, reason)``; the selector is the pair
    of face sets ``_build_fillet`` intersects.
    """
    if group.get("kind") != "sketch-extrude":
        return None, (
            f"both of this blend's neighbours are surfaces of {group['id']}, a "
            f"{group['kind']}, whose faces this emitter cannot partition into named sets. "
            "An edge inside it is not nameable, so no fillet is claimed here."
        )
    caps = list(group.get("cap_regions") or ())
    roles = tuple(
        "start" if h == caps[0] else "end" if h == caps[-1] else "side" for h in (first, second)
    )
    if roles == ("side", "side"):
        return "side-side", None
    if "side" not in roles:
        return None, (
            f"both of this blend's neighbours are cap planes of {group['id']}, which face away "
            "from each other and share no edge."
        )
    cap = roles[0] if roles[0] != "side" else roles[1]
    return f"{cap}-side", None


def _plan_fillets(
    regions: Sequence[RegionFit],
    groups: Sequence[Mapping[str, Any]],
    *,
    equal_radius_tolerance: float | None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Turn U2's two-neighbour blend proposals into fillet features, or gate them.

    U2 marks a *blend* adjacent to exactly two non-blend primaries.  Two surfaces
    qualify as a blend and both arrive here: a torus, whose minor radius is the
    round, and a **partial-arc cylinder**, which is what Fusion's face grouping
    actually delivers an edge round as -- the measured segmentation put every one
    of the benchmark's blends in that bucket and not one torus.  Requiring a torus
    here was pre-pivot: it refused the only shape the producer emits.  The arc is
    measured upstream, by U2, against the caller's declared ceiling; nothing is
    re-derived from shape here, because the fit record does not carry the angular
    span and a planner that guessed it would be inventing the measurement.

    What U2 cannot know is whether those two neighbours were themselves rebuilt:
    a fillet needs an edge to sit on, so a blend whose neighbours did not both
    become features is not emitted.  Nor can it know whether the blend surface
    was itself claimed by another archetype -- a partial-arc cylinder can be,
    where a torus never was -- and a region rebuilt twice is counted twice in the
    coverage account.

    Two neighbours *sharing* an owner is not by itself a reason to refuse.  A
    box's own top edge runs between two faces of one extrude and Fusion rounds it
    without complaint; what this stage has to establish is that the edge is
    **nameable**, which for an extrude it is -- ``_same_feature_edge`` picks the
    pair of face sets -- and for a revolve it is not.  Blends landing on the same
    face-set pair of the same feature are one fillet, not several: they are
    fragments of one round, and emitting one archetype each would ask Fusion to
    round an already-rounded edge.  They may only be pooled when the caller has
    declared an ``equal_radius_tolerance`` and every fragment's measured radius
    lies inside it -- otherwise the fragments disagree about the round and
    choosing between them here would be inventing the measurement.
    """
    gates: dict[str, str] = {}
    owner: dict[str, str] = {}
    by_id = {str(group["id"]): group for group in groups}
    for group in groups:
        for region_hash in group["regions"]:
            owner[str(region_hash)] = str(group["id"])
    same_feature: dict[tuple[str, str], list[RegionFit]] = {}

    fillets: list[dict[str, Any]] = []
    for region in regions:
        if region.fillet is None:
            continue
        if not region.accepted or region.fit is None or region.fit.kind not in BLEND_FIT_KINDS:
            gates[region.region_hash] = (
                "fillet-fit-unaccepted: the record proposes a fillet here and the region carries no "
                f"accepted {' or '.join(sorted(BLEND_FIT_KINDS))} fit, so there is no measured blend "
                "surface behind the proposal."
            )
            continue
        claimant = owner.get(region.region_hash)
        if claimant is not None:
            # The blend surface is already rebuilt -- as a side of an extrude
            # whose section runs through the round, or as the wall of a bore.
            # Rounding it again would put the same area in two archetypes, and
            # the coverage account would report more than the scan.
            gates[region.region_hash] = (
                "fillet-region-already-reconstructed: this blend surface is already part of "
                f"{claimant}, whose own profile rebuilds it. A fillet here would rebuild the same "
                "area a second time."
            )
            continue
        first, second = region.fillet["between"]
        owners = sorted({owner.get(first), owner.get(second)} - {None})
        if owner.get(first) is None or owner.get(second) is None:
            gates[region.region_hash] = (
                "fillet-neighbour-unreconstructed: a fillet rounds the edge between two features, "
                "and this blend's neighbours did not both become features. There is no edge to "
                "round."
            )
            continue
        if len(owners) != 2:
            selector, refusal = _same_feature_edge(by_id[owners[0]], first, second)
            if selector is None:
                gates[region.region_hash] = "fillet-neighbour-shared: " + str(refusal)
            else:
                same_feature.setdefault((owners[0], selector), []).append(region)
            continue
        fillets.append(_fillet_archetype([region], owners, None))

    for (owner_id, selector), members in sorted(same_feature.items()):
        # Largest fragment first: its measured radius is the one emitted, so the
        # program carries a radius something actually measured rather than a mean
        # of several, which no fit ever produced.
        members.sort(key=lambda r: (-r.area, r.region_hash))
        radius = members[0].fillet["radius"]
        spread = max(abs(r.fillet["radius"] - radius) for r in members)
        if len(members) > 1 and equal_radius_tolerance is None:
            for region in members:
                gates[region.region_hash] = (
                    f"fillet-radius-undeclared: {len(members)} blend fragments land on the same edge "
                    f"of {owner_id}, and whether they measured one round or several turns on an "
                    "equal_radius_tolerance this caller did not declare."
                )
            continue
        if len(members) > 1 and spread > equal_radius_tolerance:
            for region in members:
                gates[region.region_hash] = (
                    f"fillet-radius-disagrees: {len(members)} blend fragments land on the same edge "
                    f"of {owner_id} carrying radii that spread by {spread:.4g}, beyond the declared "
                    f"equal_radius_tolerance {equal_radius_tolerance:g}. They do not describe one "
                    "round, and this stage does not choose between them."
                )
            continue
        fillets.append(_fillet_archetype(members, [owner_id], selector))
    return fillets, gates


def _fillet_archetype(
    members: Sequence[RegionFit], owners: Sequence[str], edge_faces: str | None
) -> dict[str, Any]:
    hashes = sorted(region.region_hash for region in members)
    if edge_faces is None:
        reason = (
            f"an accepted {members[0].fit.kind} blend adjacent to exactly two non-blend "
            f"primaries, both of which this program rebuilds ({owners[0]}, {owners[1]}). "
            "Emitted as a fillet radius on their shared edge -- parametric and editable -- "
            "rather than as blend surface geometry, which Fusion has no editable home for."
        )
    else:
        reason = (
            f"{len(members)} accepted blend fragment(s) adjacent to two non-blend primaries that "
            f"are both surfaces of {owners[0]}, one a {edge_faces.split('-')[0]} face and one a "
            "side face. Emitted as a fillet radius on the edge those two face sets share -- "
            "parametric and editable -- rather than as blend surface geometry."
        )
    return {
        "id": _archetype_id("fillet", hashes),
        "kind": "fillet",
        # Neither new-body, join nor cut: a fillet on a convex edge
        # removes material and one on a concave edge adds it, and the
        # program does not measure which. Naming it a cut would assert
        # the half it did not establish.
        "operation": "finish",
        "regions": hashes,
        "plane": None,
        "radius": {"parameter": None, "value": members[0].fillet["radius"]},
        "between": [str(item) for item in owners],
        "edge_faces": edge_faces,
        "profile": None,
        "profile_source": None,
        "constraints": [],
        "dependencies": [str(item) for item in owners],
        "reason": reason,
    }


def plan_archetypes(
    regions: Sequence[RegionFit],
    frame: DatumFrame,
    *,
    angle_tolerance_deg: float,
    offset_tolerance: float,
    equal_radius_tolerance: float | None = None,
    motion_gates: Mapping[str, float] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Assign regions to the archetypes U4 emits; declare everything else.

    Precedence is stated and fixed: **revolve first, then sketch-extrude.** A
    coaxial stack is both a legal revolve and a legal extrude (KTD9 — we recover
    *a* parameterization, not *the* original), so the choice has to be a rule
    rather than whichever test happened to run first.  Revolve wins because it
    rebuilds the whole coaxial stack as one feature.

    Precedence decides between two archetypes that the evidence *both* supports.
    It is not a licence to claim one the evidence does not support at all, and
    that is the distinction this stage used to miss: any plane perpendicular to
    the primary axis counted as a surface of revolution, so a rectangular plate
    with one small coaxial round planned as a 360-degree revolve of that round's
    radius.  A revolve now has to be earned before precedence is consulted —
    ``_motion_evidence`` puts the candidate group's own facet normals through
    the kinematic router and requires an affirmative *rotation about this axis*.
    A group whose motion is a translation, or whose invariant motions form a
    family rather than a single one, falls through to ``sketch-extrude`` with
    the router's record carried on whichever archetype ends up claiming it.

    ``hole`` and ``fillet`` are assigned from evidence U2 measures and this stage
    reads, never from shape alone.  A cylinder becomes a **hole** only when its
    ``material_side`` is ``"inside"`` — the mesh's own winding putting solid on
    the far side of the surface, which is what makes a bore a bore and not a
    boss.  ``material_side`` is ``None`` on an open or inconsistently wound mesh
    and on every plane; when it is ``None`` the region stays unreconstructed
    carrying U2's own reason for the absence.  A **fillet** is assigned only
    where U2 marked an accepted blend -- a torus, or a cylinder whose measured
    arc is short enough to be an edge round rather than a bore -- adjacent to
    exactly two non-blend primaries, *and* both neighbours became features here,
    *and* the blend surface was not already claimed by one of them.

    Bores are classified **before** the extrude group chooses its sides, because
    an inward cylinder piercing a plate is a hole through it, not a wall of it —
    and because leaving it in the side set puts a second closed loop in the
    extrude's section, which the profile builder refuses outright.

    Everything geometry is stated **in the datum frame**: plane offsets are
    stations along a datum axis measured from the datum origin, and axes are
    named datum axes.  Nothing here is in mesh coordinates with an implied
    transform.
    """
    origin, z = frame.origin, frame.z_axis
    accepted = [region for region in regions if region.accepted]
    groups: list[dict[str, Any]] = []
    claimed: set[str] = set()
    unmappable: dict[str, str] = {}

    revolve = [
        region
        for region in accepted
        if _is_coaxial_with(region, origin, z, angle_tolerance_deg, offset_tolerance)
    ]
    turned = [r for r in revolve if r.fit is not None and r.fit.kind in ("cylinder", "cone")]
    # A solid of revolution needs an outer surface of revolution. When every
    # turned surface on the axis is *known* to be a bore, the part is not turned
    # -- it is a body with a hole down it, and revolving the bore's own profile
    # would build a disc where a plate belongs. The test is on positive evidence
    # only: a cylinder whose side the record does not state still licenses the
    # revolve exactly as it did before, because "unknown" is not "inward".
    outward_turned = [r for r in turned if r.material_side != "inside"]
    motion: dict[str, Any] | None = None
    if outward_turned and len(revolve) >= 2:
        motion = _motion_evidence(
            revolve, frame, motion_gates, angle_tolerance_deg, offset_tolerance
        )
    if motion is not None and motion["confirmed"]:
        members = sorted(region.region_hash for region in revolve)
        claimed.update(members)
        radius = max(
            float(r.fit.parameters["radius"])
            for r in outward_turned
            if r.fit is not None and isinstance(r.fit.parameters.get("radius"), float)
        )
        stations = [_frame_station(frame, z, r.anchor()) for r in revolve if r.anchor() is not None]
        groups.append(
            {
                "id": _archetype_id("revolve", members),
                "kind": "revolve",
                "operation": "new-body",
                "regions": members,
                # A revolve's sketch plane contains the axis; with the axis on
                # datum Z, the datum XZ plane always contains it, so a revolve
                # group is mappable by construction of the frame.
                "plane": {"datum_plane": "XZ", "offset": 0.0, "rotation": None},
                "axis": {"datum_axis": "Z", "angle_deg": 360.0},
                "profile": None,
                "profile_source": "mesh-section",
                "extent": {
                    "kind": "revolve-full",
                    "parameter": None,
                    "value": max(stations) - min(stations) if stations else 0.0,
                },
                "radius": {"parameter": None, "value": radius},
                "constraints": [],
                "dependencies": [],
                "motion_evidence": motion,
                "reason": (
                    f"{len(revolve)} accepted fits are coaxial about the primary axis, including "
                    f"{len(turned)} turned surface(s), and the kinematic router finds their facet "
                    "normals invariant under a single rotation about that axis and under no other "
                    "one-parameter motion; one revolve rebuilds the stack."
                ),
            }
        )

    remaining = [region for region in accepted if region.region_hash not in claimed]
    # An inward cylinder is a bore. Held out of the extrude's side set here, so
    # the walls of a hole are never mistaken for the walls of the part.
    bores = [
        region
        for region in remaining
        if region.fit is not None
        and region.fit.kind == "cylinder"
        and region.material_side == "inside"
    ]
    bore_hashes = {region.region_hash for region in bores}
    remaining = [region for region in remaining if region.region_hash not in bore_hashes]

    caps = _extrude_caps(remaining, angle_tolerance_deg)
    if caps is not None:
        low, high, normal = caps
        sides = [
            region
            for region in remaining
            if region.region_hash not in (low.region_hash, high.region_hash)
            and _is_extrude_side(region, normal, angle_tolerance_deg)
        ]
        datum_plane = _datum_plane_for_normal(frame, normal, angle_tolerance_deg)
        if sides and datum_plane is None:
            for region in (low, high, *sides):
                unmappable[region.region_hash] = (
                    "plane-unmappable: the cap plane's normal is oblique to every datum axis, and a "
                    "sketch plane in a parametric design can only be an origin plane or an offset "
                    "from one (setByPlane is direct-edit-only)."
                )
        elif sides and datum_plane is not None:
            axis = _plane_axis(frame, datum_plane)
            # `low` and `high` were ordered along the caps' own fit normal, which
            # is only *parallel* to the datum axis -- it can be anti-parallel. The
            # sketch plane must name the cap the body extrudes away from in the
            # +axis direction, so the station order is re-established here, in the
            # datum frame the offset is expressed in. Handing over the far cap
            # made U4 refuse `cap-order-inverted` on a plain rectangular box: the
            # emitter had documented this exact inversion as U3's to fix.
            ordered = sorted(
                ((_frame_station(frame, axis, cap.anchor()), cap) for cap in (low, high)),
                key=lambda pair: pair[0],
            )
            (low_station, low), (high_station, high) = ordered
            members = sorted(region.region_hash for region in (low, high, *sides))
            claimed.update(members)
            groups.append(
                {
                    "id": _archetype_id("sketch-extrude", members),
                    "kind": "sketch-extrude",
                    "operation": "new-body" if not groups else "join",
                    "regions": members,
                    "plane": {
                        "datum_plane": datum_plane,
                        "offset": low_station,
                        "rotation": None,
                    },
                    # Station order, not hash order: the low cap is the one the
                    # sketch sits on, which is the feature's `startFaces`, and a
                    # fillet on a cap-to-side edge has to name which cap.
                    "cap_regions": [low.region_hash, high.region_hash],
                    "profile": None,
                    "profile_source": "mesh-section",
                    "extent": {
                        "kind": "distance",
                        "parameter": None,
                        "value": abs(high_station - low_station),
                    },
                    "constraints": [],
                    "dependencies": [],
                    # Carried here, not only on a revolve: when a candidate
                    # revolve was refused, these are the very regions it wanted,
                    # and the reader of this extrude is the one who needs to see
                    # why they are not a revolve. Null when no group was ever a
                    # revolve candidate, which is not the same as "refused".
                    "motion_evidence": None if motion is None or motion["confirmed"] else motion,
                    "reason": (
                        f"two parallel cap planes {abs(high_station - low_station):.6g} apart on datum "
                        f"{datum_plane}, with {len(sides)} side surface(s) perpendicular to them."
                    ),
                }
            )

    if motion is not None and not motion["confirmed"]:
        # Only reaches a region no archetype claimed: `unmappable` is consulted
        # for unclaimed regions alone, so an extrude that took these caps hides
        # this gate rather than contradicting it.
        for region in revolve:
            unmappable[region.region_hash] = (
                f"revolve-motion-unproven ({motion['reason']}): {motion['detail']}"
            )

    holes, hole_gates = _plan_holes(
        bores, groups, frame, angle_tolerance_deg, offset_tolerance
    )
    for group in holes:
        claimed.update(group["regions"])
    groups.extend(holes)
    unmappable.update(hole_gates)

    # Fillets last: they depend on the features they round, so they can only be
    # judged once every base, cut and hole has claimed its regions.
    fillets, fillet_gates = _plan_fillets(
        regions, groups, equal_radius_tolerance=equal_radius_tolerance
    )
    for group in fillets:
        claimed.update(group["regions"])
    groups.extend(fillets)
    unmappable.update(fillet_gates)

    unreconstructed = []
    for region in regions:
        if region.region_hash in claimed:
            continue
        if region.region_hash in unmappable:
            gate = unmappable[region.region_hash]
        elif (
            region.fit is not None
            and region.fit.accepted
            and region.fit.kind == "cylinder"
            and region.material_side is None
        ):
            # The one gate that must never round down to "no archetype fits". A
            # cylinder of unknown side is the *bore-or-boss* question left open,
            # and saying so is what stops the next reader from closing it by eye.
            gate = (
                "material-side-unavailable: this is an accepted cylinder, and whether it is a bore "
                "or a boss turns on which side of it the material lies. The fit record does not "
                "say, so no hole is claimed here. "
                + (region.orientation_gate or "No reason was recorded for the absence.")
            )
        elif region.fit is None:
            gate = "no fit was attempted for this region."
        elif not region.fit.accepted:
            gate = region.fit.rejection or "the fit was not accepted and stated no reason."
        else:
            gate = (
                f"the accepted {region.fit.kind} fit is neither coaxial with the primary axis nor a "
                "cap or side of an extrude group, so no archetype in this unit's vocabulary covers it."
            )
        unreconstructed.append(
            {
                "region_id": region.region_hash,
                "area": region.area,
                "area_fraction": None,
                "bounding_box": [list(region.bounding_box[0]), list(region.bounding_box[1])],
                "gate": gate,
            }
        )
    return groups, unreconstructed


# --------------------------------------------------------------------------
# 4. user parameters
# --------------------------------------------------------------------------

# Which observable U5 should watch when a parameter of each quantity changes.
# A size-like parameter moves volume; a position-like one moves the centroid and
# may leave volume untouched, which is why the proof cannot be volume-only.
OBSERVABLE_FOR_QUANTITY = {
    "depth": "volume",
    "radius": "volume",
    "diameter": "volume",
    "position": "centroid",
}

OBSERVABLES = {"volume", "centroid", "bbox"}


def _user_parameters(
    groups: Sequence[Mapping[str, Any]],
    adoptions: Sequence[Mapping[str, Any]],
    units: str,
) -> list[dict[str, Any]]:
    """One named parameter per driven quantity, shared where a relationship says so.

    Each parameter declares **which observable should move when it changes**, so
    U5's perturbation proof asserts against the thing this parameter actually
    affects.  Volume-only would report a correct hole-position parameter as
    inert, so the observable is declared per parameter rather than assumed.
    """
    shared_by_region: dict[str, str] = {}
    parameters: list[dict[str, Any]] = []
    counters: dict[str, int] = {}

    def name_for(role: str, quantity: str) -> str:
        counters[role] = counters.get(role, 0) + 1
        return f"recon_{role}_{counters[role]}_{quantity}"

    for adoption in adoptions:
        if adoption["target"] != "parameter" or adoption["kind"] not in ("equal_radius", "nominal"):
            continue
        hashes = [subject.split(" ")[0] for subject in adoption["subjects"]]
        existing = next((shared_by_region[h] for h in hashes if h in shared_by_region), None)
        shared = existing or name_for("shared", "radius")
        for region_hash in hashes:
            shared_by_region[region_hash] = shared

    for group in groups:
        role = "revolve" if group["kind"] == "revolve" else "base"
        if group["kind"] == "sketch-extrude":
            parameter = name_for(role, "depth")
            parameters.append(
                {
                    "name": parameter,
                    "quantity": "depth",
                    "unit": units,
                    "nominal": group["extent"]["value"],
                    "expected_observable": OBSERVABLE_FOR_QUANTITY["depth"],
                    "observable_rationale": (
                        "The extrude distance sets how much material the feature adds, so a change "
                        "must move the solid's volume; a depth change that does not is a dead parameter."
                    ),
                    "rationale": (
                        f"distance between the two cap planes of {group['id']}, measured from the fits."
                    ),
                    "driving_archetypes": [group["id"]],
                }
            )
            group["extent"]["parameter"] = parameter
        elif group["kind"] == "revolve":
            shared = next(
                (shared_by_region[h] for h in group["regions"] if h in shared_by_region), None
            )
            parameter = shared or name_for(role, "radius")
            if shared is None:
                parameters.append(
                    {
                        "name": parameter,
                        "quantity": "radius",
                        "unit": units,
                        "nominal": group["radius"]["value"],
                        "expected_observable": OBSERVABLE_FOR_QUANTITY["radius"],
                        "observable_rationale": (
                            "The revolved profile's radius sets the swept area, so a change must move "
                            "the solid's volume."
                        ),
                        "rationale": (
                            f"largest fitted radius in the coaxial stack of {group['id']}."
                        ),
                        "driving_archetypes": [group["id"]],
                    }
                )
            else:
                for entry in parameters:
                    if entry["name"] == parameter and group["id"] not in entry["driving_archetypes"]:
                        entry["driving_archetypes"].append(group["id"])
            group["radius"]["parameter"] = parameter
        elif group["kind"] == "hole":
            counters["hole"] = counters.get("hole", 0) + 1
            stem = f"recon_hole_{counters['hole']}"
            position = group["hole"]["position"]
            for slot, quantity, target, why in (
                (
                    group["hole"]["diameter"],
                    "diameter",
                    f"{stem}_dia",
                    "The bore's diameter sets how much material the cut removes, so a change must "
                    "move the solid's volume.",
                ),
                (
                    group["extent"],
                    "depth",
                    f"{stem}_depth",
                    "The hole's depth sets how far the cut reaches, so a change must move the "
                    "solid's volume.",
                ),
                (
                    position["u"],
                    "position",
                    f"{stem}_{position['u_axis'].lower()}",
                    "Sliding the hole across the face moves material from one side of it to the "
                    "other without changing how much is removed. The centroid moves; the volume "
                    "need not, and a volume-only proof would call this correct parameter dead.",
                ),
                (
                    position["v"],
                    "position",
                    f"{stem}_{position['v_axis'].lower()}",
                    "Sliding the hole across the face moves material from one side of it to the "
                    "other without changing how much is removed. The centroid moves; the volume "
                    "need not, and a volume-only proof would call this correct parameter dead.",
                ),
            ):
                parameters.append(
                    {
                        "name": target,
                        "quantity": quantity,
                        "unit": units,
                        "nominal": slot["value"],
                        "expected_observable": OBSERVABLE_FOR_QUANTITY[quantity],
                        "observable_rationale": why,
                        "rationale": (
                            f"{quantity} of {group['id']}, measured from the accepted cylinder fit "
                            "whose material_side is 'inside'."
                        ),
                        "driving_archetypes": [group["id"]],
                    }
                )
                slot["parameter"] = target
        elif group["kind"] == "fillet":
            counters["fillet"] = counters.get("fillet", 0) + 1
            target = f"recon_fillet_{counters['fillet']}_radius"
            parameters.append(
                {
                    "name": target,
                    "quantity": "radius",
                    "unit": units,
                    "nominal": group["radius"]["value"],
                    "expected_observable": OBSERVABLE_FOR_QUANTITY["radius"],
                    "observable_rationale": (
                        "A fillet radius sets how much material the blend adds or removes at the "
                        "edge, so a change must move the solid's volume. Which direction it moves "
                        "is not declared, because this program does not measure whether the edge "
                        "is convex or concave."
                    ),
                    "rationale": (
                        f"the blend radius U2 measured on {group['id']}'s surface -- a torus's "
                        "minor radius, or a partial-arc cylinder's radius -- rounding the edge "
                        + (
                            f"between {group['between'][0]} and {group['between'][1]}."
                            if len(group["between"]) == 2
                            else f"between the {group['edge_faces']} faces of {group['between'][0]}."
                        )
                    ),
                    "driving_archetypes": [group["id"]],
                }
            )
            group["radius"]["parameter"] = target

    for adoption in adoptions:
        if adoption["target"] != "parameter" or adoption["kind"] not in ("equal_radius", "nominal"):
            continue
        hashes = [subject.split(" ")[0] for subject in adoption["subjects"]]
        shared = shared_by_region[hashes[0]]
        if any(entry["name"] == shared for entry in parameters):
            continue
        parameters.append(
            {
                "name": shared,
                "quantity": "radius",
                "unit": units,
                "nominal": adoption["proposed_value"]
                if isinstance(adoption["proposed_value"], (int, float))
                else None,
                "expected_observable": OBSERVABLE_FOR_QUANTITY["radius"],
                "observable_rationale": (
                    "A shared radius drives every feature adopted equal to it, so a change must move "
                    "the solid's volume."
                ),
                "rationale": (
                    f"one radius shared by {len(hashes)} region(s) because the run adopted "
                    f"{adoption['kind']}: {adoption['rationale']}"
                ),
                "driving_archetypes": [],
            }
        )
    parameters.sort(key=lambda entry: entry["name"])
    return parameters


def _attach_constraints(
    groups: Sequence[dict[str, Any]], adoptions: Sequence[Mapping[str, Any]]
) -> None:
    """Localize each adopted sketch constraint onto the archetype it belongs to.

    Every attached constraint carries ``snapped_from`` — the deviation applying
    it will erase — beside the tolerance that licensed erasing it.  Those are
    the same number seen two ways, and the program states both so a reviewer can
    see what the snap cost and what permitted it.
    """
    for group in groups:
        members = set(group["regions"])
        for adoption in adoptions:
            if adoption["target"] != "constraint":
                continue
            hashes = {subject.split(" ")[0] for subject in adoption["subjects"]}
            if not hashes <= members:
                continue
            group["constraints"].append(
                {
                    "kind": adoption["kind"],
                    "subjects": list(adoption["subjects"]),
                    "snapped_from": adoption["deviation"],
                    "snapped_from_unit": adoption["deviation_unit"],
                    "license_tolerance": adoption["license"]["tolerance"],
                    "license_basis": adoption["license"]["basis"],
                    "rationale": adoption["rationale"],
                }
            )
        group["constraints"].sort(key=lambda entry: (entry["kind"], entry["subjects"]))


def _emission_order(groups: Sequence[Mapping[str, Any]]) -> list[str]:
    """Bases before cuts before finishing, and deterministic within each class."""
    rank = {"new-body": 0, "join": 1, "cut": 2, "finish": 3}
    return [
        group["id"]
        for group in sorted(groups, key=lambda g: (rank[g["operation"]], g["id"]))
    ]


# --------------------------------------------------------------------------
# 5. the program itself
# --------------------------------------------------------------------------


def _declared_number(issues: list[ValidationIssue], raw: Any, path: str) -> None:
    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue(
                "threshold-must-be-declared",
                path,
                "Every threshold is an object with a value and the rationale for it; a bare number "
                "is a module constant with extra steps.",
            )
        )
        return
    _reject_unknown_fields(issues, raw, {"value", "rationale"}, path)
    value = raw.get("value")
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or float(value) <= 0.0
    ):
        issues.append(
            ValidationIssue(
                "threshold-invalid-value", f"{path}.value", "value must be a positive finite number."
            )
        )
    rationale = raw.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "threshold-missing-rationale",
                f"{path}.rationale",
                "State why this number is the right one for this part. A threshold without a "
                "rationale is not reviewable, and this validator rejects it rather than assume one.",
            )
        )


OPTIONAL_THRESHOLDS = ("tangent_tolerance", "equal_radius_tolerance", "nominal_tolerance")


def validate_program_spec(spec: Any) -> list[ValidationIssue]:
    """Validate the caller's declared thresholds and adoption decisions."""
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "program-spec-must-be-object", "program_spec", "A program spec must be an object."
            )
        ]
    _reject_unknown_fields(issues, spec, PROGRAM_SPEC_FIELDS, "program_spec")

    thresholds = spec.get("thresholds")
    if not isinstance(thresholds, dict):
        issues.append(
            ValidationIssue(
                "program-spec-invalid-thresholds",
                "program_spec.thresholds",
                "thresholds must be an object; every threshold this stage uses is declared by the "
                "caller with its rationale.",
            )
        )
    else:
        _reject_unknown_fields(issues, thresholds, THRESHOLD_FIELDS, "program_spec.thresholds")
        basis = thresholds.get("tolerance_basis")
        for name in DECLARED_NUMBERS:
            if name in OPTIONAL_THRESHOLDS and thresholds.get(name) is None:
                # Absent means that relationship kind is not screened at all —
                # an explicit "not judged", never a default tolerance.
                continue
            if name == "sigma_multiple" and basis != "uncertainty":
                continue
            _declared_number(issues, thresholds.get(name), f"program_spec.thresholds.{name}")
        if not isinstance(basis, str) or basis not in TOLERANCE_BASES:
            issues.append(
                ValidationIssue(
                    "program-spec-invalid-basis",
                    "program_spec.thresholds.tolerance_basis",
                    "tolerance_basis must be 'uncertainty' (tolerances derived from each fit's own "
                    "measured uncertainty) or 'declared-absolute' (the caller's own numbers).",
                )
            )
        elif basis == "declared-absolute":
            for name in ("absolute_angle_tolerance_deg", "absolute_length_tolerance"):
                _declared_number(issues, thresholds.get(name), f"program_spec.thresholds.{name}")
        motion = thresholds.get("motion_evidence")
        # Absent is a decision this stage acts on -- no revolve is claimed
        # without a declared gate to judge its motion against -- so it is not an
        # issue here. Present and partial is, because four of the five gates
        # cannot judge a spectrum on their own.
        if motion is not None:
            if not isinstance(motion, dict):
                issues.append(
                    ValidationIssue(
                        "program-spec-invalid-thresholds",
                        "program_spec.thresholds.motion_evidence",
                        "motion_evidence must be an object carrying the kinematic router's five "
                        f"declared gates: {', '.join(MOTION_GATE_FIELDS)}.",
                    )
                )
            else:
                _reject_unknown_fields(
                    issues,
                    motion,
                    set(MOTION_GATE_FIELDS),
                    "program_spec.thresholds.motion_evidence",
                )
                for name in MOTION_GATE_FIELDS:
                    _declared_number(
                        issues,
                        motion.get(name),
                        f"program_spec.thresholds.motion_evidence.{name}",
                    )

    adopted = spec.get("adopted")
    if not isinstance(adopted, list):
        issues.append(
            ValidationIssue(
                "program-spec-invalid-adoptions",
                "program_spec.adopted",
                "adopted must be an array; adopting nothing is written as an empty array, because "
                "'no relationships were adopted' is a decision and is recorded as one.",
            )
        )
        return issues
    for index, adoption in enumerate(adopted):
        path = f"program_spec.adopted[{index}]"
        if not isinstance(adoption, dict):
            issues.append(
                ValidationIssue("program-spec-invalid-adoptions", path, "Each adoption is an object.")
            )
            continue
        _reject_unknown_fields(issues, adoption, ADOPTION_FIELDS, path)
        if adoption.get("kind") not in INTENT_KINDS:
            issues.append(
                ValidationIssue(
                    "program-spec-invalid-adoptions",
                    f"{path}.kind",
                    f"kind must be one of {', '.join(sorted(INTENT_KINDS))}.",
                )
            )
        subjects = adoption.get("subjects")
        if (
            not isinstance(subjects, list)
            or not subjects
            or not all(isinstance(s, str) and s.strip() for s in subjects)
        ):
            issues.append(
                ValidationIssue(
                    "program-spec-invalid-adoptions",
                    f"{path}.subjects",
                    "subjects must be the proposal's own subject strings.",
                )
            )
        if adoption.get("target") not in ADOPTION_TARGETS:
            issues.append(
                ValidationIssue(
                    "program-spec-invalid-adoptions",
                    f"{path}.target",
                    "target must be 'parameter' (re-solve the numbers so the relationship is true) "
                    "or 'constraint' (emit it for Fusion's sketch solver to enforce).",
                )
            )
        rationale = adoption.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            issues.append(
                ValidationIssue(
                    "program-spec-invalid-adoptions",
                    f"{path}.rationale",
                    "Adoption is a decision and carries the reason it was made.",
                )
            )
    return issues


def _proposal_id(proposal: IntentProposal) -> str:
    return f"{proposal.kind}:{'|'.join(sorted(proposal.subjects))}"


def _threshold(thresholds: Mapping[str, Any], name: str) -> float | None:
    entry = thresholds.get(name)
    return None if entry is None else float(entry["value"])


def _motion_gates(thresholds: Mapping[str, Any]) -> dict[str, float] | None:
    entry = thresholds.get("motion_evidence")
    if not isinstance(entry, dict):
        return None
    return {name: float(entry[name]["value"]) for name in MOTION_GATE_FIELDS}


def program_sha256(program: Mapping[str, Any]) -> str:
    """Canonical hash over every field but the hash itself."""
    body = {key: value for key, value in program.items() if key != "program_sha256"}
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_reconstruction_program(
    fit_record: FitRecord,
    spec: Mapping[str, Any],
    *,
    manifest_sha256: str,
) -> dict[str, Any]:
    """Screen, license, adopt, reconcile, derive the frame, and plan archetypes."""
    issues = validate_program_spec(spec)
    if issues:
        raise ManifestValidationError(issues)
    thresholds = spec["thresholds"]
    basis = thresholds["tolerance_basis"]
    accepted = list(fit_record.accepted())
    if basis == "uncertainty":
        require_uncertainty(accepted)
    by_hash = {region.region_hash: region for region in accepted}

    proposals: tuple[IntentProposal, ...] = ()
    if accepted:
        proposals = propose_design_intent(
            {region.region_hash: region.fit for region in accepted},  # type: ignore[misc]
            angle_tolerance_deg=_threshold(thresholds, "angle_tolerance_deg"),
            offset_tolerance=_threshold(thresholds, "offset_tolerance"),
            nominal_tolerance=_threshold(thresholds, "nominal_tolerance"),
            tangent_tolerance=_threshold(thresholds, "tangent_tolerance"),
            equal_radius_tolerance=_threshold(thresholds, "equal_radius_tolerance"),
        )

    licences: dict[str, dict[str, Any]] = {}
    recorded: list[dict[str, Any]] = []
    for proposal in proposals:
        judgement = license_proposal(
            proposal,
            by_hash,
            basis=basis,
            sigma_multiple=_threshold(thresholds, "sigma_multiple") or 0.0,
            absolute_angle_tolerance_deg=_threshold(thresholds, "absolute_angle_tolerance_deg")
            or 0.0,
            absolute_length_tolerance=_threshold(thresholds, "absolute_length_tolerance") or 0.0,
        )
        identifier = _proposal_id(proposal)
        licences[identifier] = judgement
        recorded.append({"proposal_id": identifier, **proposal.to_dict(), "license": judgement})
    recorded.sort(key=lambda entry: entry["proposal_id"])

    by_id = {_proposal_id(proposal): proposal for proposal in proposals}
    adoptions: list[dict[str, Any]] = []
    for adoption in spec["adopted"]:
        identifier = f"{adoption['kind']}:{'|'.join(sorted(adoption['subjects']))}"
        proposal = by_id.get(identifier)
        if proposal is None:
            raise _refuse(
                "adoption-unmeasured",
                f"no proposal named {identifier} was measured in this run, so adopting it would "
                "assert a relationship this run never saw.",
                {"proposal_id": identifier, "measured": sorted(by_id)},
            )
        judgement = licences[identifier]
        if not judgement["licensed"]:
            raise _refuse(
                "adoption-unlicensed",
                f"{identifier} measures {proposal.deviation:.6g} {proposal.deviation_unit} against a "
                f"tolerance of {judgement['tolerance']} ({judgement['basis']}); {judgement['reason']}",
                {"proposal_id": identifier, "license": judgement},
            )
        target = adoption["target"]
        allowed = PARAMETER_ADOPTABLE if target == "parameter" else CONSTRAINT_ADOPTABLE
        if adoption["kind"] not in allowed:
            raise _refuse(
                "adoption-unsupported-target",
                f"{adoption['kind']} cannot be adopted as a {target}: "
                + (
                    "this stage cannot re-solve the numbers to make it true, so adopting it that way "
                    "would record a relationship the program's own values contradict."
                    if target == "parameter"
                    else "it does not correspond to a sketch constraint U4 emits."
                ),
                {"proposal_id": identifier, "target": target},
            )
        adoptions.append(
            {
                "proposal_id": identifier,
                "kind": adoption["kind"],
                "subjects": list(adoption["subjects"]),
                "target": target,
                "rationale": adoption["rationale"].strip(),
                "proposed_value": proposal.proposed_value,
                "deviation": proposal.deviation,
                "deviation_unit": proposal.deviation_unit,
                "license": judgement,
            }
        )
    adoptions.sort(key=lambda entry: (entry["proposal_id"], entry["target"]))

    reconciliation = reconcile(
        by_hash,
        adoptions,
        {identifier: judgement["tolerance"] for identifier, judgement in licences.items()},
    )
    reconciled = [reconciliation.regions[region.region_hash] for region in accepted]

    frame = derive_datum_frame(
        reconciled,
        frame_margin=_threshold(thresholds, "frame_margin"),
        angle_tolerance_deg=_threshold(thresholds, "angle_tolerance_deg"),
        offset_tolerance=_threshold(thresholds, "offset_tolerance"),
    )
    all_regions = [
        reconciliation.regions.get(region.region_hash, region) for region in fit_record.regions
    ]
    groups, unreconstructed = plan_archetypes(
        all_regions,
        frame,
        angle_tolerance_deg=_threshold(thresholds, "angle_tolerance_deg"),
        offset_tolerance=_threshold(thresholds, "offset_tolerance"),
        equal_radius_tolerance=_threshold(thresholds, "equal_radius_tolerance"),
        motion_gates=_motion_gates(thresholds),
    )
    _attach_constraints(groups, adoptions)
    parameters = _user_parameters(groups, adoptions, fit_record.units)
    # Each archetype carries the share of the scan it accounts for. Without it
    # the coverage account could only subtract regions the *program* left out,
    # never one the *build* failed to deliver -- and a fillet that was planned
    # and then skipped would silently keep counting as reconstructed.
    by_hash = {region.region_hash: region for region in all_regions}
    for group in groups:
        group["area_fraction"] = sum(
            by_hash[h].area for h in group["regions"] if h in by_hash
        ) / fit_record.total_area
    covered = sum(
        region.area
        for region in all_regions
        if any(region.region_hash in group["regions"] for group in groups)
    )
    for entry in unreconstructed:
        entry["area_fraction"] = entry.pop("area") / fit_record.total_area

    program = {
        "program_version": PROGRAM_VERSION,
        "dump_sha256": fit_record.dump_sha256,
        "manifest_sha256": manifest_sha256,
        "units": fit_record.units,
        "thresholds": {key: value for key, value in thresholds.items()},
        "datum": frame.to_dict(),
        "user_parameters": parameters,
        "archetypes": groups,
        "order": _emission_order(groups),
        "unreconstructed": unreconstructed,
        "relationships": {
            "proposals": recorded,
            "adopted": adoptions,
            "constraints": [a for a in adoptions if a["target"] == "constraint"],
            "shared_parameters": [a for a in adoptions if a["target"] == "parameter"],
            "reconciliation": reconciliation.to_dict(),
            "reconciliation_scope": (
                "Adopted parameter relationships were re-solved jointly per group as an "
                "inverse-variance-weighted projection of the fitted parameters onto the constraint. "
                "This is the maximum-likelihood solution for a shared radius and the first-order one "
                "for a shared axis; it is not a re-solve against the region point sets, which the fit "
                "record does not carry. Each parameter's movement is recorded in reconciliation."
            ),
        },
        "covered_area_fraction": covered / fit_record.total_area,
        "profile_note": (
            "Archetype profiles are null here: a section profile comes from the mesh dump's "
            "triangles, which the fit record does not carry, so U3 cannot produce one. The emitter "
            "sections the bound dump at the declared plane. This is stated rather than left as an "
            "absent key so that a null profile cannot read as an empty profile."
        ),
    }
    program["program_sha256"] = program_sha256(program)
    return program


# --------------------------------------------------------------------------
# 6. the executor-side validator
# --------------------------------------------------------------------------


def _check_version(program: Mapping[str, Any], _dump: str, _manifest: str) -> list[ValidationIssue]:
    version = program.get("program_version")
    if version != PROGRAM_VERSION:
        return [
            ValidationIssue(
                "program-version-unsupported",
                "program.program_version",
                f"This executor implements program_version {PROGRAM_VERSION} and the program declares "
                f"{version!r}. A program from another version is refused, never best-efforted.",
            )
        ]
    return []


_PROGRAM_FIELDS = {
    "program_version",
    "dump_sha256",
    "manifest_sha256",
    "units",
    "thresholds",
    "datum",
    "user_parameters",
    "archetypes",
    "order",
    "unreconstructed",
    "relationships",
    "covered_area_fraction",
    "profile_note",
    # Present only on a program produced by `replan-without` (U4/D8): it records
    # which program this one was derived from and which refusal caused the drop,
    # so a second emission run is traceable to the first one's failure.
    "replanned_from",
    "program_sha256",
}

_ARCHETYPE_FIELDS = {
    "id",
    "kind",
    "operation",
    "regions",
    "plane",
    "axis",
    "cap_regions",
    "profile",
    "profile_source",
    "extent",
    "radius",
    "constraints",
    "dependencies",
    "reason",
    # every kind: the share of the scan's area this archetype accounts for, so a
    # planned-but-undelivered archetype can be subtracted from coverage by name.
    "area_fraction",
    # hole only: the diameter and the in-plane position of its placement point.
    "hole",
    # fillet only: the archetype ids whose shared edge it rounds -- two of them,
    # or one when the edge runs between two face sets of a single feature.
    "between",
    # fillet only: which pair of that single feature's face sets, when `between`
    # names one archetype; null when it names two.
    "edge_faces",
    # revolve and sketch-extrude: the kinematic router's verdict on the revolve
    # candidate group -- what licensed a revolve, or what refused one and sent
    # these regions here instead. Null when no revolve was ever a candidate.
    "motion_evidence",
}

OPERATIONS = {"new-body", "join", "cut", "finish"}
"""``finish`` is the fillet's operation.

A fillet on a convex edge removes material and one on a concave edge adds it,
and this program measures which only for the blend surface, not for the edge.
Calling every fillet a ``cut`` would assert the half it never established, so
the vocabulary carries a fourth word instead of overloading a third.
"""

DATUM_PLANES = {"XY", "YZ", "XZ"}


def _check_vocabulary(
    program: Mapping[str, Any], _dump: str, _manifest: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _reject_unknown_fields(issues, dict(program), _PROGRAM_FIELDS, "program")
    archetypes = program.get("archetypes")
    if not isinstance(archetypes, list):
        issues.append(
            ValidationIssue("program-malformed", "program.archetypes", "archetypes must be an array.")
        )
        return issues
    identifiers = []
    for index, group in enumerate(archetypes):
        path = f"program.archetypes[{index}]"
        if not isinstance(group, dict):
            issues.append(ValidationIssue("program-malformed", path, "each archetype is an object."))
            continue
        _reject_unknown_fields(issues, group, _ARCHETYPE_FIELDS, path)
        identifiers.append(group.get("id"))
        if group.get("kind") not in ARCHETYPE_KINDS:
            issues.append(
                ValidationIssue(
                    "program-value-out-of-set",
                    f"{path}.kind",
                    f"kind must be one of {', '.join(sorted(ARCHETYPE_KINDS))}.",
                )
            )
        if group.get("operation") not in OPERATIONS:
            issues.append(
                ValidationIssue(
                    "program-value-out-of-set",
                    f"{path}.operation",
                    f"operation must be one of {', '.join(sorted(OPERATIONS))}.",
                )
            )
        plane = group.get("plane")
        if isinstance(plane, dict) and plane.get("datum_plane") not in DATUM_PLANES:
            issues.append(
                ValidationIssue(
                    "program-value-out-of-set",
                    f"{path}.plane.datum_plane",
                    f"datum_plane must be one of {', '.join(sorted(DATUM_PLANES))}; a sketch plane "
                    "can only be an origin plane or an offset from one.",
                )
            )
    order = program.get("order")
    if not isinstance(order, list) or sorted(order) != sorted(i for i in identifiers if i is not None):
        issues.append(
            ValidationIssue(
                "program-order-invalid",
                "program.order",
                "order must be a total order over exactly the archetype ids.",
            )
        )
    for name, entry in (("user_parameters", program.get("user_parameters")),):
        if not isinstance(entry, list):
            issues.append(
                ValidationIssue("program-malformed", f"program.{name}", f"{name} must be an array.")
            )
            continue
        for index, parameter in enumerate(entry):
            if not isinstance(parameter, dict):
                continue
            if parameter.get("expected_observable") not in OBSERVABLES:
                issues.append(
                    ValidationIssue(
                        "program-value-out-of-set",
                        f"program.{name}[{index}].expected_observable",
                        f"expected_observable must be one of {', '.join(sorted(OBSERVABLES))}; the "
                        "perturbation proof asserts against the observable this parameter moves, and "
                        "volume alone would call a correct position parameter inert.",
                    )
                )
    relationships = program.get("relationships")
    adopted = relationships.get("adopted") if isinstance(relationships, dict) else None
    if not isinstance(adopted, list):
        issues.append(
            ValidationIssue(
                "program-malformed", "program.relationships.adopted", "adopted must be an array."
            )
        )
        return issues
    for index, adoption in enumerate(adopted):
        if not isinstance(adoption, dict):
            issues.append(
                ValidationIssue(
                    "program-malformed",
                    f"program.relationships.adopted[{index}]",
                    "must be an object.",
                )
            )
            continue
        if adoption.get("kind") not in INTENT_KINDS:
            issues.append(
                ValidationIssue(
                    "program-value-out-of-set",
                    f"program.relationships.adopted[{index}].kind",
                    f"kind must be one of {', '.join(sorted(INTENT_KINDS))}.",
                )
            )
        if adoption.get("target") not in ADOPTION_TARGETS:
            issues.append(
                ValidationIssue(
                    "program-value-out-of-set",
                    f"program.relationships.adopted[{index}].target",
                    f"target must be one of {', '.join(sorted(ADOPTION_TARGETS))}.",
                )
            )
    return issues


def _check_hash_binding(
    program: Mapping[str, Any], dump_sha256: str, manifest_sha256: str
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if program.get("dump_sha256") != dump_sha256:
        issues.append(
            ValidationIssue(
                "program-hash-mismatch",
                "program.dump_sha256",
                f"The program was fitted from dump {program.get('dump_sha256')!r} and the mesh in "
                f"front of us hashes to {dump_sha256!r}. The geometry moved under the plan.",
            )
        )
    if program.get("manifest_sha256") != manifest_sha256:
        issues.append(
            ValidationIssue(
                "program-hash-mismatch",
                "program.manifest_sha256",
                f"The program was planned against manifest {program.get('manifest_sha256')!r}, not "
                f"{manifest_sha256!r}.",
            )
        )
    if program_sha256(program) != program.get("program_sha256"):
        issues.append(
            ValidationIssue(
                "program-hash-mismatch",
                "program.program_sha256",
                "The program's own canonical hash does not match its contents; it was edited after "
                "it was built.",
            )
        )
    return issues


def _check_coverage(
    program: Mapping[str, Any], _dump: str, _manifest: str
) -> list[ValidationIssue]:
    covered = program.get("covered_area_fraction")
    if (
        isinstance(covered, bool)
        or not isinstance(covered, (int, float))
        or not 0.0 <= float(covered) <= 1.0
    ):
        return [
            ValidationIssue(
                "program-malformed",
                "program.covered_area_fraction",
                "covered_area_fraction must be a fraction between 0 and 1; the program never claims "
                "more coverage than it can name.",
            )
        ]
    if not isinstance(program.get("unreconstructed"), list):
        return [
            ValidationIssue(
                "program-malformed",
                "program.unreconstructed",
                "unreconstructed must be an array, empty if nothing was left out.",
            )
        ]
    return []


PROGRAM_CHECKS: tuple[tuple[str, Callable[..., list[ValidationIssue]]], ...] = (
    ("program-version", _check_version),
    ("closed-vocabulary", _check_vocabulary),
    ("hash-binding", _check_hash_binding),
    ("coverage", _check_coverage),
)


def check_reconstruction_program(
    program: Mapping[str, Any],
    *,
    dump_sha256: str,
    manifest_sha256: str,
) -> dict[str, Any]:
    """Run every executor-side check, and report only the checks that ran.

    ``dump_sha256`` and ``manifest_sha256`` are required, not optional: an
    absent expectation would make the binding check pass by having nothing to
    compare against, which is the difference between "verified" and "not
    disproved" and is exactly the confusion this report exists to prevent.

    Each check's name is appended **after** it returns, inside the loop that ran
    it.  A check that raises therefore leaves no entry, so ``checked`` can never
    claim a check that did not complete.
    """
    checked: list[str] = []
    issues: list[ValidationIssue] = []
    for name, check in PROGRAM_CHECKS:
        issues.extend(check(program, dump_sha256, manifest_sha256))
        checked.append(name)
    return {"checked": tuple(checked), "issues": tuple(issues)}
