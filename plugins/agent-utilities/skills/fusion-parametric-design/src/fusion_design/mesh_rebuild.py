"""U4: turning the reconstruction program into a Fusion timeline.

The split is deliberate and it is the whole design: **a smart host-side planner
and a deliberately dumb Fusion-side executor.**  Everything decidable without
Fusion is decided here, under ``scripts/test.sh`` — plane mapping, the 2-D
profile, the constraint schedule, the dimension set, feature order, parameter
names.  The output is an *emission plan*: closed-vocabulary JSON, embedded into
the generated transaction as data.  The transaction is one interpreter over that
plan.  It makes no choices.  Anything it cannot build exactly as declared is a
named refusal with rollback, never an improvisation.

**Where profiles come from.**  U3 emits ``archetype.profile: null`` and says why
in ``profile_note``: a section profile lives in the dump's triangles, and the fit
record does not carry them.  So this module takes the dump alongside the program
and sections it — through ``mesh_dump.read_mesh_dump``, which hashes the bytes
against ``program["dump_sha256"]`` and refuses before parsing.  The binding is
therefore verified *before* any geometry is read from it, which is the house rule
this whole skill exists to enforce.  A profile is never invented: if the section
does not chain into a closed loop, the archetype refuses ``profile-not-closed``
and no transaction is written.

**Why ``setByPlane`` never appears.**  It is direct-edit-only.  Every sketch
plane here is an origin plane or a parameter-driven offset from one, which is
possible only because U3 states all geometry in the datum frame and already
refuses oblique caps as ``plane-unmappable``.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from .manifest import (
    ManifestValidationError,
    ValidationIssue,
    _in_closed_set,
    _reject_unknown_fields,
)
from .mesh_datum import ReconstructionRefused, refusal
from .mesh_dump import MeshDump, read_mesh_dump
from .mesh_fitting import (
    LOOP_EVIDENCE_GATES,
    Vec3,
    _add,
    _dot,
    _length,
    _scale,
    _sub,
    classify_polyline,
    loop_material_evidence,
    section_mesh,
)
from .mesh_reconstruction import _source_evidence, require_classification
from .reconstruction_program import (
    IN_PLANE_AXES,
    OBSERVABLES,
    _declared_number,
    check_reconstruction_program,
)

if TYPE_CHECKING:
    from .manifest import Manifest


PLAN_VERSION = 1

# The archetype kinds this emitter builds — the program's whole vocabulary.
# `hole` and `fillet` joined the other two once U3 gained a producer for them:
# U2 measures each region's `material_side`, which is the bore-versus-boss
# evidence hole classification was previously missing, and marks the blend
# adjacency a fillet needs. The emitter reads the archetype, never the fit
# behind it: a fillet step is a radius parameter and two archetype ids, so a
# blend measured as a partial-arc cylinder emits exactly as a torus one does.
EMITTED_KINDS = {"sketch-extrude", "revolve", "hole", "fillet"}

# The kinds that own a sketch.  A fillet does not: it names a radius and two
# features whose shared edge it rounds, and has no profile of its own.
SKETCHED_KINDS = {"sketch-extrude", "revolve", "hole"}

# Fusion's geometry layer is centimetres; the dump and the program are
# millimetres.  Every raw coordinate in the plan is converted once, here, and
# every expression carries an explicit unit string instead.
MM_TO_CM = 0.1

UNITS_NOTE = (
    "Point coordinates in this plan are centimetres (the Fusion API's own unit for Point3D); "
    "every parameter expression carries an explicit unit string instead, so nothing downstream has "
    "to remember which one it is holding."
)

# Which sketch axes each datum plane's local u/v correspond to.  Stated as data
# rather than left as an implied convention, because a reader of the plan has to
# be able to check the projection without knowing Fusion's plane orientations.
# The planner and the emitter must agree on which datum axis is a sketch's u and
# which is its v, so there is one definition and this is an alias to it.
SKETCH_AXES = IN_PLANE_AXES

# The face-set pairs of a *single* extrude whose shared edges a fillet may round,
# mapped to the ExtrudeFeature members that deliver them.  A revolve exposes no
# such partition, which is why the planner never emits one naming a revolve.
EDGE_FACE_SETS = {
    "start-side": ("startFaces", "sideFaces"),
    "end-side": ("endFaces", "sideFaces"),
    "side-side": ("sideFaces", "sideFaces"),
}

REBUILD_SPEC_FIELDS = {"component_name", "dump_path", "thresholds", "rationale"}

REBUILD_THRESHOLD_FIELDS = {
    "section_tolerance_mm",
    "classify_tolerance_mm",
    "profile_chain_tolerance_mm",
    "snap_tolerance_deg",
    "snap_tolerance_mm",
    "constraint_displacement_tolerance_mm",
    "constraint_rejection_budget",
    "entity_match_tolerance_mm",
    "loop_material_consensus_fraction",
    "loop_attribution_min_fraction",
}

#: The two loop-evidence thresholds are *fractions of a length*, so on top of the
#: usual positive-and-declared check they carry an upper bound: a consensus floor
#: above 1.0 can never be met and a tolerated-unattributed share above 1.0
#: tolerates everything, and both would be a threshold that silently does not
#: work. Declared like every other number this stage compares against; they buy
#: diagnosis and nothing else today, because the verdicts they gate are recorded
#: and acted on by nothing.
REBUILD_FRACTION_THRESHOLDS = {
    "loop_material_consensus_fraction",
    "loop_attribution_min_fraction",
}

REBUILD_REFUSALS = {
    "program-schema-violation",
    "program-order-invalid",
    "program-order-cyclic",
    "plane-unmappable",
    "profile-not-closed",
    "profile-not-found",
    "profile-ambiguous",
    "units-unsupported",
    "cap-order-inverted",
    "archetype-kind-unsupported",
    "entity-resolution-ambiguous",
    "parameter-name-collision",
    "program-parameter-unbound",
    # Declared now, raised by nothing yet: the 2.5D loop ladder measures these
    # and records them on the profile-ambiguous evidence table, and the slab
    # planner that refuses on them is a later unit. Declaring them here is what
    # makes the diagnostic record's tokens lookup-able instead of free text.
    *LOOP_EVIDENCE_GATES,
}

REBUILD_REFUSAL_ALTERNATIVES = {
    "program-schema-violation": (
        "The program does not match the contract this emitter implements. Re-plan it with "
        "plan-reconstruction from this version of the skill rather than hand-editing it."
    ),
    "program-order-invalid": (
        "The program's declared order is not a topological order over its own dependencies. "
        "Re-plan rather than reordering by hand: the order is the parametric structure."
    ),
    "program-order-cyclic": (
        "The archetype dependencies contain a cycle, so no build order exists. This is a malformed "
        "program, not a hard model; re-plan it."
    ),
    "plane-unmappable": (
        "A sketch plane in a parametric design can only be an origin plane or an offset from one. "
        "Re-derive the datum frame so this feature's cap plane is parallel to a datum plane, or "
        "accept the region as unreconstructed."
    ),
    "profile-not-closed": (
        "The mesh section at this plane does not chain into one closed loop. Nothing here will "
        "force it closed. Check the mesh for holes at this station, or widen classify_tolerance_mm "
        "if the section is closed but noisy."
    ),
    "profile-not-found": (
        "The mesh section at this plane produced no usable polyline. The declared plane may not "
        "cross the body at all, which means the archetype's cap stations disagree with the mesh."
    ),
    "units-unsupported": (
        "The mesh dump format writes millimetres, so every number reaching this emitter is a "
        "millimetre figure. Re-plan the program against a millimetre fit record rather than "
        "relabelling the numbers."
    ),
    "cap-order-inverted": (
        "The program's sketch-plane offset names the far cap, not the near one, so the extrude "
        "would run away from the body. This happens when the cap normal is anti-parallel to the "
        "datum axis. Re-plan the program; do not flip the sign by hand."
    ),
    "profile-ambiguous": (
        "The section closed more than one loop, so the part has an internal void or a second solid "
        "at this station. A bore is the common cause and it has a home: it emits as a hole "
        "archetype, held out of the extrude's profile. That needs the fit record to say the "
        "cylinder is inward, which needs a closed, consistently wound mesh -- so check "
        "orientation.material_side on the region first. Otherwise declare the extra region "
        "unreconstructed."
    ),
    "archetype-kind-unsupported": (
        "This emitter builds every kind the program's vocabulary carries -- sketch-extrude, "
        "revolve, hole and fillet -- so a kind it does not recognise came from a program this "
        "version of the skill did not plan. Re-plan it with plan-reconstruction."
    ),
    "entity-resolution-ambiguous": (
        "The program's declared value matched no section entity, or matched several. Tighten "
        "entity_match_tolerance_mm, or re-plan: a parameter bound to the wrong curve is worse than "
        "one that refuses."
    ),
    "parameter-name-collision": (
        "A user parameter of this name already exists in the manifest. Rename the manifest "
        "parameter, or re-plan so the reconstruction's names do not collide."
    ),
    "program-parameter-unbound": (
        "An archetype's extent, radius, hole diameter or hole position names no user parameter, so "
        "its dimension would be a magic number in the timeline. Re-plan the program."
    ),
    # The four below are measured today and refused by nobody. Their alternatives
    # are written now because the token and the way out of it are one thought,
    # and splitting them across units is how a token ends up meaning whatever
    # the next reader assumed.
    "loop-orientation-unavailable": (
        "The mesh is not closed with a non-zero signed volume, so its winding carries no "
        "inside/outside information and no loop at any station can be told from a hole. This is a "
        "capture problem, not a threshold: re-export the mesh from a solid, or repair it, and "
        "check the capture's own isClosed/isOriented before re-running. Nothing here will guess a "
        "material side."
    ),
    "loop-material-contradictory": (
        "This loop's own wall triangles disagree about which side of it the material is on, by "
        "more than the declared loop_material_consensus_fraction. That is usually a section "
        "crossing a junction, a self-touching wall, or a duplicated triangle -- not a tolerance. "
        "Read the dissenting arc length on the evidence table before moving the fraction: a floor "
        "loosened until a contradiction passes is a contradiction nobody recorded."
    ),
    "loop-parity-contradiction": (
        "The winding says material is on one side of this loop and even-odd nesting says the "
        "other. One of the two is wrong about the geometry, which is the signature of a section "
        "through a junction or a self-intersecting chain. Section at a different station, or "
        "accept the region as unreconstructed."
    ),
    "slab-wall-unattributed": (
        "More than the declared loop_attribution_min_fraction of this loop's length lies on "
        "triangles that cast no vote -- degenerate facets, or facets parallel to the section plane "
        "that bound material along the axis rather than across the loop. Section away from the cap "
        "if the station grazes one; otherwise the walls at this station are not evidence."
    ),
}


# What the *transaction* can refuse with, as opposed to the planner. Kept as a
# closed set for the same reason as REBUILD_REFUSALS: a token nobody declared is
# a token nobody can write a handler for, and `replan-without` records one into
# a program that downstream stages then trust.
REBUILD_TRANSACTION_FAILURES = {
    "rebuild-capability",
    "dump-hash-mismatch",
    "parameter-name-collision",
    "entity-resolution-ambiguous",
    "constraint-rejected-budget-exceeded",
    "feature-failed",
    "solver-unhealthy",
    "profile-not-found",
    "document-changed",
    "rollback-incomplete",
}


def _refuse(reason: str, message: str, detail: dict[str, Any] | None = None) -> ReconstructionRefused:
    return refusal(
        reason,
        message,
        detail,
        vocabulary=REBUILD_REFUSALS,
        alternatives=REBUILD_REFUSAL_ALTERNATIVES,
    )


# --------------------------------------------------------------------------
# 1. the caller's declared thresholds
# --------------------------------------------------------------------------


def validate_rebuild_spec(spec: Any) -> list[ValidationIssue]:
    """Every threshold this stage uses, declared by the caller with its reason."""
    issues: list[ValidationIssue] = []
    if not isinstance(spec, dict):
        return [
            ValidationIssue(
                "rebuild-spec-must-be-object", "rebuild_spec", "A rebuild spec must be an object."
            )
        ]
    _reject_unknown_fields(issues, spec, REBUILD_SPEC_FIELDS, "rebuild_spec")

    name = spec.get("component_name")
    if not isinstance(name, str) or not name.strip():
        issues.append(
            ValidationIssue(
                "rebuild-spec-invalid-component",
                "rebuild_spec.component_name",
                "Name the component the rebuild lands in. It is never the root component: the "
                "source mesh stays where it is and the rebuild overlays it.",
            )
        )
    dump_path = spec.get("dump_path")
    if not isinstance(dump_path, str) or not dump_path.strip():
        issues.append(
            ValidationIssue(
                "rebuild-spec-invalid-dump-path",
                "rebuild_spec.dump_path",
                "The emitter sections the bound mesh dump to derive profiles, so it needs the dump "
                "the program was fitted from. Its bytes are hashed against program.dump_sha256 "
                "before anything is read out of it.",
            )
        )

    thresholds = spec.get("thresholds")
    if not isinstance(thresholds, dict):
        issues.append(
            ValidationIssue(
                "rebuild-spec-invalid-thresholds",
                "rebuild_spec.thresholds",
                "thresholds must be an object; every number this stage compares against is declared "
                "here with its rationale, never as a module constant.",
            )
        )
    else:
        _reject_unknown_fields(
            issues, thresholds, REBUILD_THRESHOLD_FIELDS, "rebuild_spec.thresholds"
        )
        for field in sorted(REBUILD_THRESHOLD_FIELDS - {"constraint_rejection_budget"}):
            path = f"rebuild_spec.thresholds.{field}"
            _declared_number(issues, thresholds.get(field), path)
            if field in REBUILD_FRACTION_THRESHOLDS:
                declared = thresholds.get(field)
                value = declared.get("value") if isinstance(declared, dict) else None
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and float(value) > 1.0
                ):
                    issues.append(
                        ValidationIssue(
                            "threshold-invalid-value",
                            f"{path}.value",
                            "This threshold is a fraction of a loop's own length, so it cannot "
                            "exceed 1.0; above that it is a gate that can never fire or one that "
                            "never refuses, and either way it is not the number it reads as.",
                        )
                    )
        _declared_budget(
            issues,
            thresholds.get("constraint_rejection_budget"),
            "rebuild_spec.thresholds.constraint_rejection_budget",
        )
    rationale = spec.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "rebuild-spec-invalid-rationale",
                "rebuild_spec.rationale",
                "Record why these thresholds are the right ones for this part.",
            )
        )
    return issues


def _declared_budget(issues: list[ValidationIssue], raw: Any, path: str) -> None:
    """Like a declared threshold, but zero is a meaningful budget."""
    if not isinstance(raw, dict):
        issues.append(
            ValidationIssue(
                "threshold-must-be-declared",
                path,
                "Every threshold is an object with a value and the rationale for it.",
            )
        )
        return
    _reject_unknown_fields(issues, raw, {"value", "rationale"}, path)
    value = raw.get("value")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        issues.append(
            ValidationIssue(
                "threshold-invalid-value",
                f"{path}.value",
                "A rejection budget is a non-negative whole number of constraints. Zero means the "
                "solver is allowed to reject nothing, which is a real choice and is written as 0.",
            )
        )
    rationale = raw.get("rationale")
    if not isinstance(rationale, str) or not rationale.strip():
        issues.append(
            ValidationIssue(
                "threshold-missing-rationale",
                f"{path}.rationale",
                "State why this budget is the right one. A budget nobody justified can be set high "
                "enough that it never fires.",
            )
        )


def _value(thresholds: Mapping[str, Any], name: str) -> float:
    return float(thresholds[name]["value"])


# --------------------------------------------------------------------------
# 2. the dependency order, re-derived and cross-checked
# --------------------------------------------------------------------------


def total_order(archetypes: Sequence[Mapping[str, Any]]) -> list[str]:
    """Topologically sort the archetypes, deterministically.

    Cycles cannot arise from U3's edge set, but a hand-edited program is an
    input rather than an impossibility, so the sort detects one and refuses.
    Ties break on ``(rank of operation, id)`` — never on dict order.
    """
    rank = {"new-body": 0, "join": 1, "cut": 2}
    pending = {str(group["id"]): set(group.get("dependencies") or ()) for group in archetypes}
    keys = {
        str(group["id"]): (rank.get(str(group.get("operation")), 3), str(group["id"]))
        for group in archetypes
    }
    unknown = sorted(
        dependency
        for dependencies in pending.values()
        for dependency in dependencies
        if dependency not in pending
    )
    if unknown:
        raise _refuse(
            "program-order-invalid",
            f"archetypes depend on ids this program does not contain: {', '.join(unknown)}.",
            {"missing_dependencies": unknown},
        )
    ordered: list[str] = []
    while pending:
        ready = sorted(
            (identifier for identifier, deps in pending.items() if not deps),
            key=lambda identifier: keys[identifier],
        )
        if not ready:
            raise _refuse(
                "program-order-cyclic",
                "the archetype dependencies contain a cycle, so no build order exists: "
                + ", ".join(sorted(pending)),
                {"remaining": sorted(pending)},
            )
        for identifier in ready:
            ordered.append(identifier)
            del pending[identifier]
        for deps in pending.values():
            deps.difference_update(ready)
    return ordered


# --------------------------------------------------------------------------
# 3. profiles, derived from the hash-bound dump
# --------------------------------------------------------------------------


def _frame_axes(datum: Mapping[str, Any]) -> dict[str, Vec3]:
    return {
        "X": tuple(float(v) for v in datum["x_axis"]),  # type: ignore[misc]
        "Y": tuple(float(v) for v in datum["y_axis"]),  # type: ignore[misc]
        "Z": tuple(float(v) for v in datum["z_axis"]),  # type: ignore[misc]
    }


def _plane_normal_axis(datum_plane: str) -> str:
    return {"XY": "Z", "XZ": "Y", "YZ": "X"}[datum_plane]


def _dump_triangles(dump: MeshDump) -> list[tuple[int, int, int]]:
    raw = dump.triangles
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]


def _dump_vertices(dump: MeshDump) -> list[Vec3]:
    raw = dump.vertices_mm
    return [(raw[i], raw[i + 1], raw[i + 2]) for i in range(0, len(raw), 3)]


def _project(point: Vec3, origin: Vec3, u: Vec3, v: Vec3) -> tuple[float, float]:
    offset = _sub(point, origin)
    return (_dot(offset, u), _dot(offset, v))


def _single_closed(
    section: Any,
    archetype_id: str,
    station: float,
    bores: Sequence[Any] = (),
    evidence: Mapping[str, Any] | None = None,
) -> Any:
    """The one closed polyline at this station that is not a bore, or a refusal.

    Deliberately not "the largest": choosing among candidate loops is a decision,
    and E1 puts every decision host-side *and under test* rather than in a
    heuristic nobody declared. A section that closes two loops means an internal
    void or a second solid at this station, which is geometry this emitter does
    not build -- so it refuses by name instead of silently rebuilding the outer
    shell and quietly losing the bore.

    ``bores`` are the loops the caller *identified* as holes this same program
    cuts, matched to their declared centres and radii. Those are not a second
    profile: they are features of their own, already in the program and ordered
    after this one. Everything else still refuses.

    ``evidence`` is the per-loop material record from ``loop_material_evidence``,
    carried onto the ``profile-ambiguous`` detail unchanged. It changes no
    decision here -- a second loop refuses exactly as it did before it existed --
    and its whole job is that the reader of the refusal sees *which* loops, on
    which walls, with material on which side, instead of a loop count.
    """
    closed = [line for line in section.polylines if line.closed and len(line.points) >= 3]
    if not closed:
        raise _refuse(
            "profile-not-found",
            f"sectioning the dump at station {station:.6g} mm produced no closed polyline for "
            f"{archetype_id}; the declared stations do not agree with the mesh.",
            {
                "archetype_id": archetype_id,
                "station_mm": station,
                "open_polylines": len(section.polylines),
                "junctions": len(section.junctions),
            },
        )
    if len(closed) > 1:
        bore_ids = {id(line) for line in bores}
        outer = [line for line in closed if id(line) not in bore_ids]
        if len(outer) == 1:
            return outer[0]
        detail: dict[str, Any] = {
            "archetype_id": archetype_id,
            "station_mm": station,
            "closed_loop_point_counts": [len(line.points) for line in closed],
            "loops_matched_to_holes": len(closed) - len(outer),
        }
        if evidence is not None:
            detail["loop_evidence"] = evidence
        raise _refuse(
            "profile-ambiguous",
            f"the section at station {station:.6g} mm closed {len(closed)} loops for "
            f"{archetype_id}, of which {len(closed) - len(outer)} are bores this program cuts; "
            "a single-loop profile cannot describe what is left and picking one would discard "
            "the rest without saying so.",
            detail,
        )
    return closed[0]


def _loops_cut_by_holes(
    closed: Sequence[Any],
    holes: Sequence[Mapping[str, Any]],
    origin: Vec3,
    u: Vec3,
    v: Vec3,
    tolerance: float,
) -> list[Any]:
    """Which of a section's closed loops are bores this same program cuts.

    A plate with thirteen bores down it sections into fourteen loops, and the one
    that matters is the outline: the other thirteen are the holes this program
    already carries as their own cut features, and rebuilding them into the
    profile would cut each of them twice.  This is not "take the largest loop" --
    that is the heuristic ``_single_closed`` exists to refuse.  Each interior loop
    has to be *identified*: its centre within the caller's declared
    ``entity_match_tolerance_mm`` of a hole's own declared centre, and its radius
    within that of the hole's own declared radius, both in the datum frame the
    hole's position is stated in.  A loop nothing matches leaves the section
    ambiguous and the refusal stands.
    """
    matched: list[Any] = []
    for line in closed:
        points = [_project(point, origin, u, v) for point in line.points]
        centre = (
            sum(point[0] for point in points) / len(points),
            sum(point[1] for point in points) / len(points),
        )
        radii = [math.dist(point, centre) for point in points]
        radius = sum(radii) / len(radii)
        for hole in holes:
            position = (hole.get("hole") or {}).get("position") or {}
            u_value = (position.get("u") or {}).get("value")
            v_value = (position.get("v") or {}).get("value")
            diameter = ((hole.get("hole") or {}).get("diameter") or {}).get("value")
            if not all(isinstance(item, (int, float)) for item in (u_value, v_value, diameter)):
                # A hole that does not state where it is cannot claim a loop. It
                # is left unmatched rather than defaulted to the origin, which
                # would claim whichever loop happened to sit there.
                continue
            declared = (float(u_value), float(v_value))
            if (
                math.dist(centre, declared) <= tolerance
                and abs(radius - float(diameter) / 2.0) <= tolerance
            ):
                matched.append(line)
                break
    return matched


def _entities_2d(
    entities: Sequence[Any], origin: Vec3, u: Vec3, v: Vec3
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for entity in entities:
        row: dict[str, Any] = {
            "kind": entity.kind,
            "start_mm": list(_project(entity.start, origin, u, v)),
            "end_mm": list(_project(entity.end, origin, u, v)),
            "residual_mm": entity.residual,
            "point_count": entity.point_count,
        }
        if entity.center is not None:
            row["center_mm"] = list(_project(entity.center, origin, u, v))
        if entity.radius is not None:
            row["radius_mm"] = entity.radius
        if entity.mid is not None:
            row["mid_mm"] = list(_project(entity.mid, origin, u, v))
        out.append(row)
    return out


def _require_chained(
    entities: Sequence[Mapping[str, Any]], tolerance: float, archetype_id: str
) -> None:
    """A profile is closed or it is not a profile. Nothing here closes it."""
    if not entities:
        raise _refuse(
            "profile-not-closed",
            f"{archetype_id}'s section produced no entities to chain.",
            {"archetype_id": archetype_id},
        )
    if len(entities) == 1 and entities[0]["kind"] == "circle":
        return
    for index, entity in enumerate(entities):
        following = entities[(index + 1) % len(entities)]
        gap = math.dist(entity["end_mm"], following["start_mm"])
        if gap > tolerance:
            raise _refuse(
                "profile-not-closed",
                f"{archetype_id}'s section leaves a {gap:.6g} mm gap between entity {index} and "
                f"{(index + 1) % len(entities)}, beyond the declared "
                f"{tolerance:.6g} mm profile_chain_tolerance_mm.",
                {"archetype_id": archetype_id, "gap_mm": gap, "entity_index": index},
            )


def _loop_evidence(
    section: Any, dump: MeshDump, normal: Vec3, thresholds: Mapping[str, Any]
) -> dict[str, Any]:
    """The per-loop winding record for this station -- measured, never acted on.

    This emitter receives the program and the dump and never the fit record
    (see ``ADOPTED_CONSTRAINT_NOTE``), so ``triangle_regions`` stays absent here
    and the loops report their walls' material side without naming the regions
    those walls belong to. That is the correct split: the verdict is winding
    evidence, which the dump carries on its own; region identity is fit-record
    evidence, and a stage that does not hold the fit record must not pretend to.
    """
    return loop_material_evidence(
        section,
        _dump_vertices(dump),
        _dump_triangles(dump),
        normal,
        consensus_fraction=_value(thresholds, "loop_material_consensus_fraction"),
        attribution_min_fraction=_value(thresholds, "loop_attribution_min_fraction"),
    )


def _extrude_profile(
    group: Mapping[str, Any],
    dump: MeshDump,
    datum: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    holes: Sequence[Mapping[str, Any]] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Section the dump midway between the caps and classify the result.

    The section station is the *midpoint*, not the cap: a plane laid exactly on a
    cap cuts coplanar triangles, and a real scanned cap is never exactly planar,
    so the outline there is the least robust place to measure a cross-section
    that is the same everywhere along the extrusion.  The station is recorded
    with this reason so the choice is reviewable rather than implied.

    ``holes`` are the cut features this same program places in this body. A
    midpoint section of a bored plate closes one loop per bore it crosses, and
    those loops are already carried as their own features; they are identified
    against the holes' declared centres and radii and left out of the profile,
    never simply discarded as "the smaller loops".
    """
    axes = _frame_axes(datum)
    origin = tuple(float(v) for v in datum["origin"])
    plane = group["plane"]
    normal_name = _plane_normal_axis(plane["datum_plane"])
    normal = axes[normal_name]
    u_name, v_name = SKETCH_AXES[plane["datum_plane"]]
    u, v = axes[u_name], axes[v_name]

    low = float(plane["offset"])
    depth = float(group["extent"]["value"])
    station = low + depth / 2.0
    tolerance = _value(thresholds, "section_tolerance_mm")

    def section_at(value: float) -> Any:
        return section_mesh(
            _dump_vertices(dump),
            _dump_triangles(dump),
            _add(origin, _scale(normal, value)),
            normal,
            tolerance=tolerance,
        )

    section = section_at(station)
    if not any(line.closed and len(line.points) >= 3 for line in section.polylines):
        # The extent is an absolute distance, so the declared offset could name
        # either cap; a cap normal anti-parallel to the datum axis makes U3 hand
        # over the far one. Probing the mirrored station distinguishes "the plan
        # disagrees with the mesh" from "the cap order is inverted", and the
        # difference is what the user has to act on. The sign is never flipped
        # here: the extrude direction would still be wrong, and repairing a
        # program in the emitter is exactly the improvisation this unit bans.
        mirrored = low - depth / 2.0
        if any(
            line.closed and len(line.points) >= 3 for line in section_at(mirrored).polylines
        ):
            raise _refuse(
                "cap-order-inverted",
                f"{group['id']} declares its sketch plane at {low:.6g} mm on datum "
                f"{plane['datum_plane']}, but the body lies on the other side of it: the mesh "
                f"sections at {mirrored:.6g} mm and not at {station:.6g} mm. The program's cap "
                "ordering is inverted, so its extrude would run away from the body.",
                {
                    "archetype_id": group["id"],
                    "declared_offset_mm": low,
                    "declared_station_mm": station,
                    "mirrored_station_mm": mirrored,
                },
            )
    closed = [line for line in section.polylines if line.closed and len(line.points) >= 3]
    bores = _loops_cut_by_holes(
        closed,
        holes,
        origin,
        u,
        v,
        _value(thresholds, "entity_match_tolerance_mm"),
    )
    # Measured only when the station is about to be ambiguous. On the one-loop
    # path there is nothing to disambiguate, and an O(triangles) winding pass
    # per archetype to produce a table nobody reads is cost with no reader.
    evidence_table = _loop_evidence(section, dump, normal, thresholds) if len(closed) > 1 else None
    polyline = _single_closed(section, str(group["id"]), station, bores, evidence_table)
    entities = classify_polyline(
        polyline.points,
        tolerance=_value(thresholds, "classify_tolerance_mm"),
        closed=True,
        normal=normal,
        segment_triangles=polyline.segment_triangles or None,
    )
    rows = _entities_2d(entities, origin, u, v)
    _require_chained(rows, _value(thresholds, "profile_chain_tolerance_mm"), str(group["id"]))
    evidence = {
        "source": "mesh-section",
        "station_mm": station,
        "station_rationale": (
            "Sectioned midway between the two cap stations rather than on a cap: a plane laid on a "
            "cap cuts coplanar triangles, and a scanned cap is never exactly planar, so the "
            "mid-station cross-section is the same geometry measured where the mesh is well "
            "conditioned."
        ),
        "open_polyline_count": sum(1 for line in section.polylines if not line.closed),
        "junction_count": len(section.junctions),
        "coplanar_triangles": section.coplanar_triangles,
        "selected_point_count": len(polyline.points),
    }
    return rows, evidence


def _clip_half(
    points: Sequence[Vec3], u: Vec3, origin: Vec3, tolerance: float
) -> tuple[list[Vec3], bool] | None:
    """Keep the run of a closed section on the ``u >= 0`` side of the axis.

    A revolve profile is a *half* section: the full section through the axis
    carries both sides, and revolving both would sweep the body twice.  The clip
    is exact — the crossing point is interpolated on the segment, not snapped to
    the nearest sample — and it refuses (returns None) unless the section enters
    the positive side exactly once and leaves it exactly once, because more than
    one run means the half-profile is not a single curve and picking one would
    be a guess.

    ``tolerance`` is the same declared section tolerance used to decide whether a
    vertex lies on a plane; here it only drops a crossing point that landed on a
    sample it already carries, which would otherwise leave a zero-length segment.
    """
    signed = [_dot(_sub(p, origin), u) for p in points]
    n = len(points)
    if all(value >= 0.0 for value in signed):
        # The section never crosses the axis, so it is already a closed loop --
        # a ring revolved about a line it does not touch. It needs no closure,
        # and adding one would be a zero-length line at an arbitrary place.
        return list(points), False
    if all(value <= 0.0 for value in signed):
        return None
    entries = [
        index for index in range(n) if signed[index] < 0.0 and signed[(index + 1) % n] >= 0.0
    ]
    exits = [
        index for index in range(n) if signed[index] >= 0.0 and signed[(index + 1) % n] < 0.0
    ]
    if len(entries) != 1 or len(exits) != 1:
        return None

    def crossing_point(index: int) -> Vec3:
        a, b = points[index], points[(index + 1) % n]
        sa, sb = signed[index], signed[(index + 1) % n]
        span = sb - sa
        t = 0.5 if span == 0.0 else -sa / span
        return _add(a, _scale(_sub(b, a), t))

    run: list[Vec3] = [crossing_point(entries[0])]
    index = (entries[0] + 1) % n
    guard = 0
    while signed[index] >= 0.0:
        run.append(points[index])
        index = (index + 1) % n
        guard += 1
        if guard > n:
            return None
    run.append(crossing_point(exits[0]))

    deduped: list[Vec3] = []
    for point in run:
        if deduped and _length(_sub(point, deduped[-1])) <= tolerance:
            continue
        deduped.append(point)
    if len(deduped) < 3:
        return None
    return deduped, True


def _revolve_profile(
    group: Mapping[str, Any],
    dump: MeshDump,
    datum: Mapping[str, Any],
    thresholds: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Section through the axis, keep one side, and close it against the axis."""
    axes = _frame_axes(datum)
    origin = tuple(float(v) for v in datum["origin"])
    plane = group["plane"]
    normal = axes[_plane_normal_axis(plane["datum_plane"])]
    u_name, v_name = SKETCH_AXES[plane["datum_plane"]]
    u, v = axes[u_name], axes[v_name]

    point = _add(origin, _scale(normal, float(plane["offset"])))
    section = section_mesh(
        _dump_vertices(dump),
        _dump_triangles(dump),
        point,
        normal,
        tolerance=_value(thresholds, "section_tolerance_mm"),
    )
    axial_loops = sum(1 for line in section.polylines if line.closed and len(line.points) >= 3)
    polyline = _single_closed(
        section,
        str(group["id"]),
        float(plane["offset"]),
        (),
        _loop_evidence(section, dump, normal, thresholds) if axial_loops > 1 else None,
    )
    clipped = _clip_half(
        polyline.points, u, origin, _value(thresholds, "section_tolerance_mm")
    )
    if clipped is None:
        raise _refuse(
            "profile-not-closed",
            f"{group['id']}'s axial section does not cross the revolve axis exactly twice, so it "
            "has no single half-profile. Revolving the whole section would sweep the body twice, "
            "and picking one of several runs would be a guess.",
            {"archetype_id": group["id"], "section_point_count": len(polyline.points)},
        )
    half, touches_axis = clipped
    entities = classify_polyline(
        half,
        tolerance=_value(thresholds, "classify_tolerance_mm"),
        closed=not touches_axis,
        normal=normal,
    )
    rows = _entities_2d(entities, origin, u, v)
    if not rows:
        raise _refuse(
            "profile-not-closed",
            f"{group['id']}'s half-section classified into no entities.",
            {"archetype_id": group["id"]},
        )
    if touches_axis:
        # Close the open half-profile with one line lying on the revolve axis.
        # That line is the axis itself, so it adds no geometry the section did
        # not already imply, and it is the only closure a half-profile can
        # legally take. A section that never met the axis is already closed and
        # gets no line: a zero-length one would be a curve Fusion rejects and a
        # claim the evidence does not support.
        rows.append(
            {
                "kind": "line",
                "start_mm": list(rows[-1]["end_mm"]),
                "end_mm": list(rows[0]["start_mm"]),
                "residual_mm": 0.0,
                "point_count": 2,
                "on_axis": True,
            }
        )
    _require_chained(rows, _value(thresholds, "profile_chain_tolerance_mm"), str(group["id"]))
    evidence = {
        "source": "mesh-section",
        "station_mm": float(plane["offset"]),
        "station_rationale": (
            "A revolve profile is the section in the plane containing the axis, clipped to one side "
            "of it and closed by the axis line. The clip is exact at the axis crossing; a section "
            "that crosses the axis more or fewer than twice refuses rather than picking a run."
        ),
        "half_section_point_count": len(half),
        "touches_axis": touches_axis,
        "closing_line_on_axis": touches_axis,
        "junction_count": len(section.junctions),
        "coplanar_triangles": section.coplanar_triangles,
    }
    return rows, evidence


# --------------------------------------------------------------------------
# 4. the constraint schedule and the dimension set
# --------------------------------------------------------------------------


def _direction(entity: Mapping[str, Any]) -> tuple[float, float] | None:
    dx = entity["end_mm"][0] - entity["start_mm"][0]
    dy = entity["end_mm"][1] - entity["start_mm"][1]
    magnitude = math.hypot(dx, dy)
    if magnitude <= 0.0:
        return None
    return (dx / magnitude, dy / magnitude)


def _angle_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    dot = max(-1.0, min(1.0, abs(a[0] * b[0] + a[1] * b[1])))
    return math.degrees(math.acos(dot))


def _origin_offset(entity: Mapping[str, Any]) -> float | None:
    """The *perpendicular* distance from the sketch origin to a line.

    Perpendicular, because that is what ``SketchDimensions.addOffsetDimension``
    measures between a line and a point. Dimensioning the midpoint distance
    instead would write a nominal Fusion does not agree with, and the executor
    would then bind a parameter whose value silently moves the wall.
    """
    direction = _direction(entity)
    if direction is None:
        return None
    ox = -entity["start_mm"][0]
    oy = -entity["start_mm"][1]
    return abs(ox * direction[1] - oy * direction[0])


def _constraint_schedule(
    entities: Sequence[Mapping[str, Any]], thresholds: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The layered snap schedule, in fixed application order.

    Every entry records ``snapped_from`` — the deviation applying it will erase —
    measured from the section itself.  That number is what makes the executor's
    displacement check meaningful: a snap is *expected* to move geometry by up to
    its own ``snapped_from``, and only the excess beyond that counts against the
    displacement tolerance.

    These are measured from the 2-D section, not read off the program's adopted
    relationships.  See ``ADOPTED_CONSTRAINT_NOTE``: the program names its
    relationships by region hash, and a section point carries no region
    provenance, so the mapping from an adopted 3-D relationship to a sketch
    entity does not exist in this emitter's inputs. Claiming otherwise would be
    the over-claim this skill exists to prevent.
    """
    angle_tolerance = _value(thresholds, "snap_tolerance_deg")
    length_tolerance = _value(thresholds, "snap_tolerance_mm")
    lines = [
        (index, entity, _direction(entity))
        for index, entity in enumerate(entities)
        if entity["kind"] == "line" and _direction(entity) is not None
    ]
    curves = [
        (index, entity)
        for index, entity in enumerate(entities)
        if entity["kind"] in ("arc", "circle") and "center_mm" in entity
    ]
    schedule: list[dict[str, Any]] = []

    # Layer 1a: orientation against the sketch's own axes, cheapest and least
    # likely to conflict, so it goes first.
    for index, _entity, direction in lines:
        assert direction is not None
        horizontal = _angle_between(direction, (1.0, 0.0))
        vertical = _angle_between(direction, (0.0, 1.0))
        if horizontal <= angle_tolerance and horizontal <= vertical:
            schedule.append(
                {"layer": 1, "kind": "horizontal", "entities": [index], "snapped_from": horizontal,
                 "snapped_from_unit": "deg"}
            )
        elif vertical <= angle_tolerance:
            schedule.append(
                {"layer": 1, "kind": "vertical", "entities": [index], "snapped_from": vertical,
                 "snapped_from_unit": "deg"}
            )

    oriented = {entry["entities"][0] for entry in schedule}

    # Layer 1b: perpendicular and parallel between lines the axes did not already
    # pin. A line already made horizontal or vertical needs neither.
    for position, (index, _entity, direction) in enumerate(lines):
        for other_index, _other, other_direction in lines[position + 1 :]:
            if index in oriented and other_index in oriented:
                continue
            assert direction is not None and other_direction is not None
            angle = _angle_between(direction, other_direction)
            if angle <= angle_tolerance:
                schedule.append(
                    {"layer": 1, "kind": "parallel", "entities": [index, other_index],
                     "snapped_from": angle, "snapped_from_unit": "deg"}
                )
            elif abs(angle - 90.0) <= angle_tolerance:
                schedule.append(
                    {"layer": 1, "kind": "perpendicular", "entities": [index, other_index],
                     "snapped_from": abs(angle - 90.0), "snapped_from_unit": "deg"}
                )

    # Layer 1c: tangency at line-arc junctions, measured at the shared endpoint.
    count = len(entities)
    for index, entity in enumerate(entities):
        following_index = (index + 1) % count
        following = entities[following_index]
        if count < 2 or {entity["kind"], following["kind"]} != {"line", "arc"}:
            continue
        line, arc = (
            (entity, following) if entity["kind"] == "line" else (following, entity)
        )
        direction = _direction(line)
        centre = arc.get("center_mm")
        if direction is None or centre is None:
            continue
        junction = entity["end_mm"]
        radial = (junction[0] - centre[0], junction[1] - centre[1])
        magnitude = math.hypot(*radial)
        if magnitude <= 0.0:
            continue
        radial = (radial[0] / magnitude, radial[1] / magnitude)
        deviation = abs(_angle_between(direction, radial) - 90.0)
        if deviation <= angle_tolerance:
            schedule.append(
                {"layer": 1, "kind": "tangent", "entities": [index, following_index],
                 "snapped_from": deviation, "snapped_from_unit": "deg"}
            )

    # Layer 1d: a line the section puts through the datum origin is *at* the
    # datum, and that is a measurement. Saying so with a coincidence removes the
    # degree of freedom that a zero-length offset dimension could not express --
    # Fusion has no dimension for "this line passes through that point".
    for index, entity, _direction_unused in lines:
        offset = _origin_offset(entity)
        if offset is not None and offset <= length_tolerance:
            schedule.append(
                {"layer": 1, "kind": "origin-coincident", "entities": [index],
                 "snapped_from": offset, "snapped_from_unit": "mm"}
            )

    # Layer 1e: concentric and equal radii between curves.
    for position, (index, entity) in enumerate(curves):
        for other_index, other in curves[position + 1 :]:
            gap = math.dist(entity["center_mm"], other["center_mm"])
            if gap <= length_tolerance:
                schedule.append(
                    {"layer": 1, "kind": "concentric", "entities": [index, other_index],
                     "snapped_from": gap, "snapped_from_unit": "mm"}
                )
            radii = (entity.get("radius_mm"), other.get("radius_mm"))
            if all(isinstance(value, (int, float)) for value in radii):
                difference = abs(float(radii[0]) - float(radii[1]))  # type: ignore[arg-type]
                if difference <= length_tolerance:
                    schedule.append(
                        {"layer": 1, "kind": "equal", "entities": [index, other_index],
                         "snapped_from": difference, "snapped_from_unit": "mm"}
                    )
    schedule.sort(key=lambda entry: (entry["layer"], entry["kind"], entry["entities"]))
    return schedule


def _dimension_set(
    entities: Sequence[Mapping[str, Any]],
    archetype_id: str,
    units: str,
    thresholds: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """One origin-offset distance per line, one radius per curve.

    That set is the one an ideal solver takes to zero remaining degrees of
    freedom without redundancy for the profiles this emitter builds: a closed
    chain of *n* line entities has 2n point degrees of freedom, the chaining
    coincidences remove n, the horizontal/vertical snaps remove up to n more, and
    what is left is one offset per line.  Every one of them is bound to a named
    user parameter, so nothing in the timeline is a magic number.

    The line lying on a revolve axis is deliberately not dimensioned: it is the
    axis, its position is the datum, and a dimension on it would be a parameter
    whose only legal value is zero.
    """
    dimensions: list[dict[str, Any]] = []
    parameters: list[dict[str, Any]] = []
    slug = str(archetype_id).replace("-", "_")
    length_tolerance = _value(thresholds, "snap_tolerance_mm")
    for index, entity in enumerate(entities):
        if entity.get("on_axis"):
            continue
        if entity["kind"] == "line":
            offset = _origin_offset(entity)
            # A line through the datum origin got an origin coincidence in the
            # constraint schedule instead; a dimension of zero here would be a
            # parameter whose only legal value is the one it already has.
            if offset is None or offset <= length_tolerance:
                continue
            name = f"recon_{slug}_offset_{index}"
            dimensions.append(
                {
                    "kind": "distance-to-origin",
                    "entity": index,
                    "parameter": name,
                    "measured_mm": offset,
                }
            )
            parameters.append(
                {
                    "name": name,
                    "quantity": "position",
                    "unit": units,
                    "nominal": offset,
                    "expected_observable": "volume",
                    "observable_rationale": (
                        "This offset places one wall of the profile, so moving it moves that wall "
                        "and changes how much material the feature encloses."
                    ),
                    "rationale": (
                        f"perpendicular distance from the sketch origin to section entity {index} "
                        f"of {archetype_id}, measured from the bound dump."
                    ),
                    "driving_archetypes": [str(archetype_id)],
                }
            )
        elif entity["kind"] in ("arc", "circle") and isinstance(entity.get("radius_mm"), (int, float)):
            name = f"recon_{slug}_radius_{index}"
            dimensions.append(
                {
                    "kind": "radius",
                    "entity": index,
                    "parameter": name,
                    "measured_mm": float(entity["radius_mm"]),
                }
            )
            parameters.append(
                {
                    "name": name,
                    "quantity": "radius",
                    "unit": units,
                    "nominal": float(entity["radius_mm"]),
                    "expected_observable": "volume",
                    "observable_rationale": (
                        "A profile radius sets the swept area of the feature, so a change must move "
                        "the solid's volume."
                    ),
                    "rationale": (
                        f"fitted radius of section entity {index} of {archetype_id}, measured from "
                        "the bound dump."
                    ),
                    "driving_archetypes": [str(archetype_id)],
                }
            )
    return dimensions, parameters


def _bind_declared_parameter(
    dimensions: list[dict[str, Any]],
    parameters: list[dict[str, Any]],
    *,
    archetype_id: str,
    parameter: str,
    value: float,
    tolerance: float,
) -> None:
    """Point the program's own parameter at the dimension that measures it.

    A revolve's radius is declared by the program and also shows up as one of the
    half-profile's origin offsets.  Minting a second parameter for it would leave
    the program's radius driving nothing -- a parameter U5 would then correctly
    report inert.  So the match is resolved geometrically, here, at the moment
    the dimension is consumed: exactly one section entity may sit within the
    declared match tolerance of the declared value.  Zero or several refuses.
    """
    matches = [
        entry
        for entry in dimensions
        if abs(float(entry["measured_mm"]) - value) <= tolerance
    ]
    if len(matches) != 1:
        raise _refuse(
            "entity-resolution-ambiguous",
            f"{archetype_id} declares {parameter} = {value:.6g} mm and "
            f"{len(matches)} section entities sit within {tolerance:.6g} mm of it, so the "
            "parameter cannot be bound to one curve.",
            {
                "archetype_id": archetype_id,
                "parameter": parameter,
                "declared_value_mm": value,
                "candidates_mm": [float(entry["measured_mm"]) for entry in dimensions],
            },
        )
    minted = matches[0]["parameter"]
    matches[0]["parameter"] = parameter
    matches[0]["bound_from_program"] = True
    for index, row in enumerate(parameters):
        if row["name"] == minted:
            parameters.pop(index)
            break


ADOPTED_CONSTRAINT_NOTE = (
    "The program names its adopted relationships by region hash. A mesh section carries no region "
    "provenance -- section_mesh returns points, not regions -- and this emitter receives the "
    "program and the dump, never the fit record, so nothing here can say which sketch entity came "
    "from which region. Adopted constraints are therefore carried as evidence and are NOT asserted "
    "to have been enforced in the sketch. The sketch constraints that are applied were measured "
    "independently from the 2-D section, each with the deviation it snapped from."
)


# --------------------------------------------------------------------------
# 5. the emission plan
# --------------------------------------------------------------------------


def _expression(value: float, unit: str, *, zero_is_a_value: bool = False) -> str:
    """Format one parameter expression, or refuse a value it cannot represent.

    Fixed-point rather than ``repr``: ``repr(1e-05)`` is ``'1e-05'``, and an
    expression Fusion may or may not parse is not something to find out about
    inside Fusion.  Six decimals of a millimetre is a nanometre, which is below
    anything a mesh can carry -- but a *non-zero* value that formats to zero
    would be a silent no-op, so it refuses instead.

    ``zero_is_a_value`` says that for this quantity zero is not a no-op: a hole
    *on* the datum axis has u = 0, and the station comes off the frame at float
    noise -- 4e-07 mm on the benchmark -- so refusing it would refuse the whole
    program over a nanometre nobody measured. A depth or a radius has no such
    reading, and those still refuse.
    """
    text = f"{value:.6f}"
    if zero_is_a_value and float(text) == 0.0:
        return f"0.000000 {unit}"
    if value != 0.0 and float(text) == 0.0:
        raise _refuse(
            "program-parameter-unbound",
            f"{value!r} is smaller than the nanometre this emitter can write as a fixed-point "
            "expression, so writing it would silently produce a zero.",
            {"value": value, "unit": unit},
        )
    return f"{text} {unit}"


def _edge_evidence_cm(evidence: Any) -> dict[str, Any] | None:
    """A fillet's edge evidence in centimetres, or ``None`` when it carries none.

    Absent is the older contract, not a malformation: a program planned before
    the evidence existed names one fillet per face-set pair and its fillet rounds
    every edge that pair shares, exactly as it did.  What must not happen is a
    *present* evidence block being read loosely, so the shape is checked whole.
    """
    if evidence is None:
        return None
    if not isinstance(evidence, dict):
        raise _refuse(
            "program-schema-violation",
            "a fillet's edge_evidence must be an object naming the datum-frame box its blend "
            "fragments occupy.",
            {"edge_evidence": evidence},
        )
    out: dict[str, Any] = {}
    for key in ("box_min", "box_max", "centroid"):
        value = evidence.get(key)
        # The members are checked, not only the container: `float(item)` on a
        # hand-edited program's string or None escapes as a bare ValueError or
        # TypeError, where every other malformed input here refuses by name.
        if (
            not isinstance(value, (list, tuple))
            or len(value) != 3
            or any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(item)
                for item in value
            )
        ):
            raise _refuse(
                "program-schema-violation",
                f"a fillet's edge_evidence.{key} must be three finite datum-frame stations.",
                {"edge_evidence": evidence},
            )
        out[key + "_cm"] = [float(item) * MM_TO_CM for item in value]
    return out


def _datum_transform_cm(datum: Mapping[str, Any], dump: MeshDump) -> dict[str, Any]:
    """The datum->mesh transform, composed with the mesh body's own if it has one.

    Row-major 4x4 in ``Matrix3D.asArray`` order, translation in centimetres. When
    the dump recorded no body transform the overlay is only correct in the mesh
    body's own space, and that is what the record says -- it never claims world
    alignment it cannot establish.
    """
    axes = _frame_axes(datum)
    origin = tuple(float(v) for v in datum["origin"])
    x, y, z = axes["X"], axes["Y"], axes["Z"]
    datum_to_dump = [
        x[0], y[0], z[0], origin[0] * MM_TO_CM,
        x[1], y[1], z[1], origin[1] * MM_TO_CM,
        x[2], y[2], z[2], origin[2] * MM_TO_CM,
        0.0, 0.0, 0.0, 1.0,
    ]
    body = dump.metadata.get("transform")
    source = dump.metadata.get("transform_source")
    if not isinstance(body, list) or len(body) != 16:
        return {
            "matrix": datum_to_dump,
            "frame": "mesh-body space",
            "dump_transform_source": source,
            "note": (
                "The dump recorded no mesh body transform, so this places the rebuild in the mesh "
                "body's own space. It overlays the source mesh exactly when that body sits at "
                "identity, and this record does not claim more than that."
            ),
        }
    composed = [
        sum(float(body[4 * row + k]) * datum_to_dump[4 * k + column] for k in range(4))
        for row in range(4)
        for column in range(4)
    ]
    return {
        "matrix": composed,
        "frame": "world",
        "dump_transform_source": source,
        "note": (
            "The datum->mesh-body transform composed with the mesh body's own recorded transform, "
            "so the rebuilt component overlays the source mesh where it actually sits."
        ),
    }


def _hole_placement(
    group: Mapping[str, Any], identifier: str, datum_plane: str
) -> dict[str, Any]:
    """The hole's placement point and the two dimensions that drive it.

    The point is dimensioned to the *sketch origin*, which is datum geometry and
    therefore exists independently of any face this build creates.  That is the
    whole reason hole position survives a rebuild: nothing in the placement
    references a B-Rep entity whose identity could shuffle (D5).
    """
    body = group.get("hole")
    if not isinstance(body, dict):
        raise _refuse(
            "program-schema-violation",
            f"{identifier} is a hole and carries no hole block, so it names neither a diameter nor "
            "a position.",
            {"archetype_id": identifier},
        )
    diameter = body.get("diameter") or {}
    position = body.get("position") or {}
    u, v = position.get("u") or {}, position.get("v") or {}
    for label, slot in (("diameter", diameter), ("position.u", u), ("position.v", v)):
        if not slot.get("parameter"):
            raise _refuse(
                "program-parameter-unbound",
                f"{identifier}'s {label} names no user parameter, so it would be a magic number in "
                "the timeline.",
                {"archetype_id": identifier, "field": label},
            )
    expected = SKETCH_AXES[datum_plane]
    declared = (position.get("u_axis"), position.get("v_axis"))
    if declared != expected:
        # The point's u/v are stations along named datum axes. Sketching them on
        # a plane whose in-plane axes are a different pair would place the hole
        # somewhere else entirely, and no downstream check measures placement.
        raise _refuse(
            "program-schema-violation",
            f"{identifier} positions its hole against datum axes {declared} while sketching on "
            f"datum {datum_plane}, whose in-plane axes are {expected}.",
            {"archetype_id": identifier, "declared": list(declared), "expected": list(expected)},
        )
    return {
        "u_cm": float(u["value"]) * MM_TO_CM,
        "v_cm": float(v["value"]) * MM_TO_CM,
        "u_parameter": str(u["parameter"]),
        "v_parameter": str(v["parameter"]),
        "u_axis": expected[0],
        "v_axis": expected[1],
        "diameter_parameter": str(diameter["parameter"]),
    }


def plan_emission(
    program: Mapping[str, Any],
    dump: MeshDump,
    spec: Mapping[str, Any],
    *,
    manifest_parameter_names: Sequence[str] = (),
) -> dict[str, Any]:
    """Decide everything decidable offline, and hand the executor a build list."""
    issues = validate_rebuild_spec(spec)
    if issues:
        raise ManifestValidationError(issues)

    verdict = check_reconstruction_program(
        program,
        dump_sha256=dump.sha256,
        manifest_sha256=str(program.get("manifest_sha256")),
    )
    if verdict["issues"]:
        raise _refuse(
            "program-schema-violation",
            "; ".join(f"{issue.path}: {issue.message}" for issue in verdict["issues"]),
            {
                "checked": list(verdict["checked"]),
                "issues": [
                    {"code": issue.code, "path": issue.path, "message": issue.message}
                    for issue in verdict["issues"]
                ],
            },
        )

    thresholds = spec["thresholds"]
    units = str(program["units"])
    if units != "mm":
        # The dump format writes millimetres (MeshDump.vertices_mm), so every
        # coordinate, offset and nominal reaching this emitter is a millimetre
        # figure. Labelling those numbers with another unit would put the sketch
        # geometry and the dimension driving it a conversion factor apart.
        raise _refuse(
            "units-unsupported",
            f"the program declares units {units!r}; the mesh dump this emitter sections is "
            "millimetres by format, and relabelling those numbers would silently rescale the "
            "model.",
            {"units": units},
        )
    archetypes = list(program["archetypes"])
    by_id = {str(group["id"]): group for group in archetypes}

    unsupported = sorted(
        str(group["id"]) for group in archetypes if group["kind"] not in EMITTED_KINDS
    )
    if unsupported:
        raise _refuse(
            "archetype-kind-unsupported",
            "this emitter builds "
            + ", ".join(sorted(EMITTED_KINDS))
            + f"; the program declares {len(unsupported)} archetype(s) it does not: "
            + ", ".join(unsupported),
            {"archetype_ids": unsupported},
        )

    derived = total_order(archetypes)
    declared = [str(identifier) for identifier in program["order"]]
    if declared != derived:
        raise _refuse(
            "program-order-invalid",
            "the program's declared order is not the order its own dependencies imply; a "
            "hand-edited order cannot be smuggled into Fusion.",
            {"declared": declared, "derived": derived},
        )

    parameters: list[dict[str, Any]] = []
    seen: dict[str, dict[str, Any]] = {}

    def add_parameter(entry: Mapping[str, Any]) -> None:
        name = str(entry["name"])
        existing = seen.get(name)
        if existing is not None:
            for archetype_id in entry.get("driving_archetypes") or ():
                if archetype_id not in existing["driving_archetypes"]:
                    existing["driving_archetypes"].append(archetype_id)
            return
        row = {
            "name": name,
            "quantity": entry.get("quantity"),
            "unit": str(entry.get("unit") or units),
            "nominal": entry.get("nominal"),
            "expected_observable": entry.get("expected_observable"),
            "observable_rationale": entry.get("observable_rationale"),
            "comment": str(entry.get("rationale") or ""),
            "driving_archetypes": list(entry.get("driving_archetypes") or ()),
        }
        if row["expected_observable"] not in OBSERVABLES:
            raise _refuse(
                "program-schema-violation",
                f"user parameter {name!r} declares expected_observable "
                f"{row['expected_observable']!r}, which is not one of "
                + ", ".join(sorted(OBSERVABLES)),
                {"parameter": name},
            )
        if not isinstance(row["nominal"], (int, float)) or isinstance(row["nominal"], bool):
            raise _refuse(
                "program-parameter-unbound",
                f"user parameter {name!r} carries no numeric nominal value, so no expression can "
                "be written for it.",
                {"parameter": name},
            )
        row["expression"] = _expression(
            float(row["nominal"]), units, zero_is_a_value=row["quantity"] == "position"
        )
        seen[name] = row
        parameters.append(row)

    for entry in program["user_parameters"]:
        add_parameter(entry)

    steps: list[dict[str, Any]] = []
    for identifier in derived:
        group = by_id[identifier]
        if group["kind"] == "fillet":
            radius = group.get("radius") or {}
            if not radius.get("parameter"):
                raise _refuse(
                    "program-parameter-unbound",
                    f"{identifier} is a fillet whose radius names no user parameter, so its radius "
                    "would be a magic number in the timeline.",
                    {"archetype_id": identifier},
                )
            between = [str(item) for item in group.get("between") or ()]
            edge_faces = group.get("edge_faces")
            if len(between) not in (1, 2) or any(item not in by_id for item in between):
                raise _refuse(
                    "program-schema-violation",
                    f"{identifier} rounds the edge between {between}, which is not one or two "
                    "archetypes this program contains.",
                    {"archetype_id": identifier, "between": between},
                )
            # One archetype means the edge runs between two face sets of a single
            # feature, and which two is not derivable here -- the planner read it
            # off the cap order it recorded, and an emitter that guessed would be
            # rounding whichever edge it liked.
            # `_in_closed_set` rather than `in`: an unhashable edge_faces
            # from a hand-edited program raises TypeError on `in`, where
            # every other malformed input here refuses by name.
            if (len(between) == 1) != _in_closed_set(edge_faces, set(EDGE_FACE_SETS)):
                raise _refuse(
                    "program-schema-violation",
                    f"{identifier} names {len(between)} archetype(s) and edge_faces "
                    f"{edge_faces!r}; a fillet inside one feature must name one of "
                    + ", ".join(sorted(EDGE_FACE_SETS))
                    + ", and one between two features must name none.",
                    {"archetype_id": identifier, "between": between, "edge_faces": edge_faces},
                )
            steps.append(
                {
                    "archetype_id": identifier,
                    "kind": "fillet",
                    "operation": group["operation"],
                    "feature_name": f"recon_{identifier.replace('-', '_')}",
                    "radius_parameter": str(radius["parameter"]),
                    "between": between,
                    "edge_faces": edge_faces if len(between) == 1 else None,
                    # One face-set pair carries as many rounded edges as the part
                    # has rounds on it, and the API hands back all of them. This
                    # is where the plan says which one -- the datum-frame extent
                    # of the blend fragments it was planned from, in centimetres
                    # because that is the unit the built body is measured in.
                    "edge_evidence": _edge_evidence_cm(group.get("edge_evidence")),
                    # The same tolerance that binds a parameter to a curve: two
                    # edges this close to equally near the evidence are not told
                    # apart by it, and the fillet says so rather than guessing.
                    "edge_match_tolerance_cm": (
                        _value(thresholds, "entity_match_tolerance_mm") * MM_TO_CM
                    ),
                    # Resolved to the ExtrudeFeature member names here rather than
                    # inside the transaction: the mapping is this emitter's
                    # knowledge of the Fusion API, and the script that runs in
                    # Fusion should carry the answer, not the lookup table.
                    "face_sets": (
                        list(EDGE_FACE_SETS[edge_faces]) if len(between) == 1 else None
                    ),
                }
            )
            continue

        plane = group["plane"]
        if plane.get("rotation") is not None:
            # Rotated planes are constructible (setByAngle from a datum axis) but
            # U3 emits none, so there is no producer to test the path against.
            raise _refuse(
                "plane-unmappable",
                f"{identifier}'s sketch plane declares a rotation about a datum axis; this emitter "
                "builds origin planes and parameter-driven offsets from them only.",
                {"archetype_id": identifier, "rotation": plane["rotation"]},
            )
        axis_name = None
        if group["kind"] == "revolve":
            axis_name = str((group.get("axis") or {}).get("datum_axis"))
            expected = SKETCH_AXES[plane["datum_plane"]][1]
            if axis_name != expected:
                # The half-profile is clipped to one side of the sketch plane's
                # u axis, which is only the right half if the revolve axis is
                # that plane's v axis. A mismatch here revolves the wrong half
                # about the wrong line, and nothing downstream would notice.
                raise _refuse(
                    "program-schema-violation",
                    f"{identifier} revolves about datum axis {axis_name!r} while sketching on datum "
                    f"{plane['datum_plane']}, whose in-plane axes are "
                    f"{SKETCH_AXES[plane['datum_plane']]}. A revolve axis must be the sketch "
                    f"plane's own second axis ({expected}).",
                    {
                        "archetype_id": identifier,
                        "datum_axis": axis_name,
                        "datum_plane": plane["datum_plane"],
                        "expected_axis": expected,
                    },
                )
            entities, evidence = _revolve_profile(group, dump, program["datum"], thresholds)
        elif group["kind"] == "hole":
            # A hole's geometry comes from the fitted cylinder, not from a mesh
            # section: the bore's radius and axis *are* the measurement, and
            # sectioning to rediscover them would add a second, noisier estimate
            # of a number the fit already carries with its uncertainty.
            entities, evidence = [], {
                "source": "fit-primitive",
                "note": (
                    "Diameter and position come from the accepted cylinder fit that made this "
                    "region a bore, not from a section of the dump. The sketch holds one point and "
                    "no curves; the hole feature carries the diameter."
                ),
            }
        else:
            entities, evidence = _extrude_profile(
                group,
                dump,
                program["datum"],
                thresholds,
                [g for g in archetypes if g["kind"] == "hole" and identifier in g["dependencies"]],
            )
        dimensions, dimension_parameters = _dimension_set(
            entities, identifier, units, thresholds
        )
        if group["kind"] == "revolve":
            radius = group.get("radius") or {}
            if not radius.get("parameter"):
                raise _refuse(
                    "program-parameter-unbound",
                    f"{identifier} is a revolve whose radius names no user parameter.",
                    {"archetype_id": identifier},
                )
            _bind_declared_parameter(
                dimensions,
                dimension_parameters,
                archetype_id=identifier,
                parameter=str(radius["parameter"]),
                value=float(radius["value"]),
                tolerance=_value(thresholds, "entity_match_tolerance_mm"),
            )
        for entry in dimension_parameters:
            add_parameter(entry)

        offset = float(plane["offset"])
        offset_parameter = None
        if abs(offset) > 0.0:
            offset_parameter = f"recon_{identifier.replace('-', '_')}_plane_offset"
            add_parameter(
                {
                    "name": offset_parameter,
                    "quantity": "position",
                    "unit": units,
                    "nominal": offset,
                    "expected_observable": "centroid",
                    "observable_rationale": (
                        "Moving the sketch plane slides the whole feature along the datum axis "
                        "without changing how much material it adds, so the centroid moves and the "
                        "volume need not. This is exactly the parameter a volume-only inertness "
                        "test would wrongly call dead."
                    ),
                    "rationale": (
                        f"offset of {identifier}'s sketch plane from datum {plane['datum_plane']}, "
                        "measured from the fits."
                    ),
                    "driving_archetypes": [identifier],
                }
            )

        step: dict[str, Any] = {
            "archetype_id": identifier,
            "kind": group["kind"],
            "operation": group["operation"],
            "feature_name": f"recon_{identifier.replace('-', '_')}",
            "sketch_name": f"recon_sketch_{identifier.replace('-', '_')}",
            "plane": {
                "datum_plane": plane["datum_plane"],
                "sketch_u_axis": SKETCH_AXES[plane["datum_plane"]][0],
                "sketch_v_axis": SKETCH_AXES[plane["datum_plane"]][1],
                "offset_parameter": offset_parameter,
                "offset_mm": offset,
            },
            "entities": [_to_cm(entity) for entity in entities],
            "constraints": _constraint_schedule(entities, thresholds),
            "dimensions": dimensions,
            "profile_evidence": evidence,
            "adopted_constraints": [
                {
                    "kind": entry["kind"],
                    "subjects": list(entry["subjects"]),
                    "snapped_from": entry["snapped_from"],
                    "snapped_from_unit": entry["snapped_from_unit"],
                    "localized": False,
                }
                for entry in group.get("constraints") or ()
            ],
        }
        if group["kind"] == "revolve":
            step["axis"] = {
                "datum_axis": axis_name,
                "angle_expression": _expression(float(group["axis"]["angle_deg"]), "deg"),
            }
        else:
            parameter = (group.get("extent") or {}).get("parameter")
            if not parameter:
                raise _refuse(
                    "program-parameter-unbound",
                    f"{identifier} is a {group['kind']} whose distance extent names no user "
                    "parameter, so its depth would be a magic number in the timeline.",
                    {"archetype_id": identifier},
                )
            step["extent"] = {"kind": "distance", "parameter": parameter}
        if group["kind"] == "hole":
            step["placement"] = _hole_placement(group, identifier, plane["datum_plane"])
        steps.append(step)

    collisions = sorted(set(manifest_parameter_names) & {row["name"] for row in parameters})
    if collisions:
        raise _refuse(
            "parameter-name-collision",
            "the rebuild would create user parameters that already exist in this document: "
            + ", ".join(collisions),
            {"names": collisions},
        )

    parameters.sort(key=lambda row: row["name"])
    return {
        "plan_version": PLAN_VERSION,
        "component_name": str(spec["component_name"]).strip(),
        "units": units,
        "units_note": UNITS_NOTE,
        "dump_sha256": dump.sha256,
        "program_sha256": str(program["program_sha256"]),
        "manifest_sha256": str(program["manifest_sha256"]),
        "datum_transform": _datum_transform_cm(program["datum"], dump),
        "thresholds": {key: dict(value) for key, value in thresholds.items()},
        "threshold_rationale": str(spec["rationale"]).strip(),
        "user_parameters": parameters,
        "steps": steps,
        "order": derived,
        "covered_area_fraction": program["covered_area_fraction"],
        "unreconstructed": [dict(entry) for entry in program["unreconstructed"]],
        "adopted_constraint_note": ADOPTED_CONSTRAINT_NOTE,
    }


def _to_cm(entity: Mapping[str, Any]) -> dict[str, Any]:
    """Convert one plan entity's millimetre coordinates to Fusion's centimetres."""
    row: dict[str, Any] = {"kind": entity["kind"]}
    for key in ("start_mm", "end_mm", "center_mm", "mid_mm"):
        if key in entity:
            row[key.replace("_mm", "_cm")] = [value * MM_TO_CM for value in entity[key]]
    if isinstance(entity.get("radius_mm"), (int, float)):
        row["radius_cm"] = float(entity["radius_mm"]) * MM_TO_CM
    if entity.get("on_axis"):
        row["on_axis"] = True
    row["residual_mm"] = entity["residual_mm"]
    return row


# --------------------------------------------------------------------------
# 6. the transaction
# --------------------------------------------------------------------------


def emit_mesh_rebuild_script(
    manifest: "Manifest",
    classification_record: Any,
    source_record: Any,
    program: Mapping[str, Any],
    spec: Mapping[str, Any],
    nonce: str,
) -> str:
    """Emit the rebuild transaction: verify, construct, measure, report."""
    from .scripts import _json_literal, _script_prelude

    classification = require_classification(
        classification_record, "mesh-rebuild", {"parametric-rebuild"}, source_record
    )
    issues = validate_rebuild_spec(spec)
    if issues:
        raise ManifestValidationError(issues)
    if not isinstance(nonce, str) or len(nonce) < 16:
        raise ValueError("The rebuild nonce must be minted by the CLI, not derived from the plan.")

    dump = read_mesh_dump(spec["dump_path"], str(program["dump_sha256"]))
    plan = plan_emission(
        program,
        dump,
        spec,
        manifest_parameter_names=[str(entry["name"]) for entry in manifest.parameters],
    )
    plan["nonce"] = nonce
    plan["classification"] = classification.to_dict()
    plan["mesh_source"] = _source_evidence(source_record)
    return _script_prelude(manifest) + _REBUILD_TRANSACTION.replace(
        "__REBUILD_PLAN__", _json_literal(plan)
    )


_REBUILD_TRANSACTION = '''PLAN = json.loads(__REBUILD_PLAN__)

_MISSING = object()

PROFILE_DISPLACEMENT_NOTE = (
    "How far the furthest sketch point ended up from where the mesh section put it, after every "
    "applied snap and every rolled-back one. A snap is meant to move geometry by the deviation it "
    "erases, so this is not zero on a real part. It is reported rather than asserted because "
    "deleting a rejected constraint removes the constraint and this transaction cannot establish "
    "that Fusion also returns the geometry -- the downstream instruments for a profile that "
    "wandered are the sketch's own fully_constrained flag and the deviation run against the source "
    "mesh."
)

ROLLBACK_NOTE = (
    "A half-emitted model differs from the program it claims to implement, which would make every "
    "downstream hash binding a lie. On any refusal this transaction deletes everything it created, "
    "in reverse creation order, and produces no geometry."
)


class Refused(RuntimeError):
    """A named refusal from the closed vocabulary. Never a bare failure."""

    def __init__(self, token, message, detail=None):
        RuntimeError.__init__(self, token + ": " + message)
        self.token = token
        self.message = message
        self.detail = detail or {}


def _probe(owner, name, missing, label):
    """Read an API member, or record it missing. Never defaults."""
    value = getattr(owner, name, _MISSING)
    if value is _MISSING or value is None:
        missing.append(label)
        return None
    return value


def _point(x, y):
    return adsk.core.Point3D.create(x, y, 0.0)


def _distance_2d(a, b):
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return (dx * dx + dy * dy) ** 0.5


def _sketch_point_positions(sketch):
    """Every sketch point's position, in millimetres, in index order."""
    points = sketch.sketchPoints
    out = []
    for index in range(points.count):
        geometry = points.item(index).geometry
        out.append([geometry.x * 10.0, geometry.y * 10.0])
    return out


def _worst_displacement(before, after):
    if len(before) != len(after):
        # The constraint added or removed a point; that is a change the position
        # comparison cannot describe, so it is reported as unbounded rather than
        # as zero.
        return float("inf")
    worst = 0.0
    for first, second in zip(before, after):
        worst = max(worst, _distance_2d(first, second))
    return worst


def _build_entities(sketch, step, missing):
    """Create the profile curves, chaining shared endpoints by construction."""
    curves = _probe(sketch, "sketchCurves", missing, "Sketch.sketchCurves")
    if curves is None:
        return None
    lines = _probe(curves, "sketchLines", missing, "Sketch.sketchCurves.sketchLines")
    arcs = _probe(curves, "sketchArcs", missing, "Sketch.sketchCurves.sketchArcs")
    circles = _probe(curves, "sketchCircles", missing, "Sketch.sketchCurves.sketchCircles")
    if lines is None or arcs is None or circles is None:
        return None

    created = []
    previous_end = None
    first_start = None
    entities = step["entities"]
    for index, entity in enumerate(entities):
        kind = entity["kind"]
        if kind == "circle":
            centre = entity["center_cm"]
            curve = circles.addByCenterRadius(_point(centre[0], centre[1]), entity["radius_cm"])
            created.append(curve)
            continue
        start = previous_end if previous_end is not None else _point(
            entity["start_cm"][0], entity["start_cm"][1]
        )
        last = index == len(entities) - 1
        end = first_start if (last and first_start is not None) else _point(
            entity["end_cm"][0], entity["end_cm"][1]
        )
        if kind == "line":
            curve = lines.addByTwoPoints(start, end)
        else:
            mid = entity["mid_cm"]
            curve = arcs.addByThreePoints(start, _point(mid[0], mid[1]), end)
        created.append(curve)
        if first_start is None:
            first_start = curve.startSketchPoint
        previous_end = curve.endSketchPoint
    return created


def _apply_one(sketch, curves, entry, missing):
    """Apply one constraint or dimension. Returns the created object."""
    constraints = _probe(sketch, "geometricConstraints", missing, "Sketch.geometricConstraints")
    if constraints is None:
        return None
    kind = entry["kind"]
    picked = [curves[index] for index in entry["entities"]]
    if kind == "horizontal":
        return constraints.addHorizontal(picked[0])
    if kind == "vertical":
        return constraints.addVertical(picked[0])
    if kind == "parallel":
        return constraints.addParallel(picked[0], picked[1])
    if kind == "perpendicular":
        return constraints.addPerpendicular(picked[0], picked[1])
    if kind == "tangent":
        return constraints.addTangent(picked[0], picked[1])
    if kind == "concentric":
        return constraints.addConcentric(picked[0], picked[1])
    if kind == "equal":
        return constraints.addEqual(picked[0], picked[1])
    if kind == "origin-coincident":
        origin = _probe(sketch, "originPoint", missing, "Sketch.originPoint")
        if origin is None:
            return None
        return constraints.addCoincident(origin, picked[0])
    raise Refused(
        "feature-failed",
        "the plan names constraint kind " + repr(kind) + ", which this executor does not build.",
        {"kind": kind},
    )


def _apply_dimension(sketch, curves, entry, missing):
    dimensions = _probe(sketch, "sketchDimensions", missing, "Sketch.sketchDimensions")
    origin = _probe(sketch, "originPoint", missing, "Sketch.originPoint")
    if dimensions is None or origin is None:
        return None
    curve = curves[entry["entity"]]
    text = _point(1.0, 1.0)
    if entry["kind"] == "radius":
        return dimensions.addRadialDimension(curve, text)
    return dimensions.addOffsetDimension(curve, origin, text)


def _bind(dimension, parameter_name, missing):
    """Point a dimension at a named user parameter, or refuse."""
    parameter = _probe(dimension, "parameter", missing, "SketchDimension.parameter")
    if parameter is None:
        return False
    parameter.expression = parameter_name
    return True


def _profile(sketch, step):
    profiles = sketch.profiles
    if profiles.count < 1:
        raise Refused(
            "profile-not-found",
            "the sketch for " + step["archetype_id"] + " closed no region, so there is no profile "
            "to extrude. The plan's entities chained closed host-side; the solver disagreed.",
            {"archetype_id": step["archetype_id"]},
        )
    # Seeded from nothing rather than from the first profile: the largest-area
    # scan below picks the winner outright, and a constant subscript here would
    # be the one place in this transaction that named geometry by position.
    best = None
    best_area = None
    for index in range(profiles.count):
        candidate = profiles.item(index)
        area = candidate.areaProperties().area
        if best_area is None or area > best_area:
            best, best_area = candidate, area
    return best


def _operation(name, missing):
    enumeration = _probe(adsk.fusion, "FeatureOperations", missing, "adsk.fusion.FeatureOperations")
    if enumeration is None:
        return None
    attribute = {
        "new-body": "NewBodyFeatureOperation",
        "join": "JoinFeatureOperation",
        "cut": "CutFeatureOperation",
    }[name]
    return _probe(enumeration, attribute, missing, "adsk.fusion.FeatureOperations." + attribute)


def _place_hole_point(sketch, step, missing):
    """One sketch point, dimensioned to the sketch origin on both axes.

    Returns the point, or None when an API member is missing. The dimensions are
    bound to the hole's position parameters, so moving the hole is editing a
    number rather than dragging geometry.
    """
    points = _probe(sketch, "sketchPoints", missing, "Sketch.sketchPoints")
    dimensions = _probe(sketch, "sketchDimensions", missing, "Sketch.sketchDimensions")
    origin = _probe(sketch, "originPoint", missing, "Sketch.originPoint")
    orientations = _probe(
        adsk.fusion, "DimensionOrientations", missing, "adsk.fusion.DimensionOrientations"
    )
    if points is None or dimensions is None or origin is None or orientations is None:
        return None, []
    placement = step["placement"]
    point = points.add(_point(placement["u_cm"], placement["v_cm"]))
    applied = []
    for attribute, parameter in (
        ("HorizontalDimensionOrientation", placement["u_parameter"]),
        ("VerticalDimensionOrientation", placement["v_parameter"]),
    ):
        orientation = _probe(
            orientations, attribute, missing, "adsk.fusion.DimensionOrientations." + attribute
        )
        if orientation is None:
            return None, []
        dimension = dimensions.addDistanceDimension(
            origin, point, orientation, _point(1.0, 1.0)
        )
        if not _bind(dimension, parameter, missing):
            return None, []
        applied.append({"kind": "hole-position", "parameter": parameter})
    return point, applied


def _feature_faces(feature, label, missing, member="faces"):
    """One of a feature's face collections, or None when this Fusion has none.

    `member` is "faces" for a whole feature and one of an ExtrudeFeature's
    startFaces / endFaces / sideFaces when the caller is after the edge between
    two face sets of that single feature.
    """
    faces = _probe(feature, member, missing, label + "." + member)
    if faces is None:
        return None
    return [faces.item(index) for index in range(faces.count)]


def _internal_edges(faces, missing):
    """Edges that two faces of this one set share.

    The same question _shared_edges asks, asked of one feature instead of two.
    Every edge of a closed solid belongs to exactly two faces, so an edge that
    appears twice inside a face set is interior to that set and an edge that
    appears once is the set's boundary with something else. A box's top edge is
    interior to (cap faces + side faces) and that is exactly what gets rounded.
    """
    seen = {}
    for face in faces:
        edges = _probe(face, "edges", missing, "BRepFace.edges")
        if edges is None:
            return None
        for index in range(edges.count):
            edge = edges.item(index)
            temp_id = _probe(edge, "tempId", missing, "BRepEdge.tempId")
            if temp_id is None:
                return None
            seen.setdefault(temp_id, [edge, 0])[1] += 1
    return [seen[key][0] for key in sorted(seen) if seen[key][1] > 1]


def _edge_centre(edge, missing):
    """The centre of an edge's bounding box, in centimetres, or None.

    Every member is probed rather than read: an edge whose box this build cannot
    produce must make the fillet skip by name, never fall back to a point at the
    origin, which would select whichever edge happens to sit nearest there.
    """
    box = _probe(edge, "boundingBox", missing, "BRepEdge.boundingBox")
    if box is None:
        return None
    low = _probe(box, "minPoint", missing, "BoundingBox3D.minPoint")
    high = _probe(box, "maxPoint", missing, "BoundingBox3D.maxPoint")
    if low is None or high is None:
        return None
    centre = []
    for axis in ("x", "y", "z"):
        a = _probe(low, axis, missing, "Point3D." + axis)
        b = _probe(high, axis, missing, "Point3D." + axis)
        if a is None or b is None:
            return None
        centre.append((float(a) + float(b)) / 2.0)
    return centre


def _box_distance(point, low, high):
    """Distance from a point to an axis-aligned box; zero inside it."""
    return sum(
        max(low[i] - point[i], 0.0, point[i] - high[i]) ** 2 for i in range(3)
    ) ** 0.5


def _edge_for_evidence(edges, evidence, tolerance, missing):
    """Which of a face-set pair's edges this round was measured on.

    A lid's outer wall meets its top cap along two dozen separate rounds, and
    ``_internal_edges`` hands back every one of those edges.  The plan says which
    edge each radius belongs on by carrying where its blend fragments were
    measured, and the answer here is the nearest edge to that box.

    Nearest, and *distinguishably* nearest: two edges within the caller's
    declared ``entity_match_tolerance_mm`` of the same distance are not told
    apart by this evidence, and the fillet is skipped by name rather than rounding
    whichever sorted first.  Returns ``(edges, None)`` or ``(None, reason)``.
    """
    ranked = []
    for edge in edges:
        centre = _edge_centre(edge, missing)
        if centre is None:
            return None, (
                "fillet-capability",
                "this Fusion does not expose " + ", ".join(missing),
            )
        ranked.append((_box_distance(centre, evidence["box_min_cm"], evidence["box_max_cm"]), edge))
    ranked.sort(key=lambda entry: entry[0])
    best = ranked[0][0]
    contenders = [entry for entry in ranked if entry[0] - best <= tolerance]
    if len(contenders) > 1:
        return None, (
            "entity-resolution-ambiguous",
            f"{len(contenders)} of this face pair's {len(ranked)} edges lie within "
            f"{tolerance:.6g} cm of the same distance from where this round's blend fragments "
            f"were measured ({best:.6g} cm). The plan's evidence does not tell them apart, and "
            "rounding the wrong edge is worse than rounding none.",
        )
    return [ranked[0][1]], None


def _shared_edges(first, second, missing):
    """Edges belonging to a face of both features, keyed by temp id.

    Temp ids are the right identity here and nowhere else: the question is which
    edges two just-created features share *inside this one transaction*, and a
    temp id is exactly a within-session handle. Nothing about this survives the
    script and nothing is asked to.

    Both members go through _probe rather than _recorded, because the result is
    branched on. An absent one means this Fusion cannot answer the question, and
    the caller turns that into a named skip -- it must never quietly become an
    empty edge set, which reads identically to "these two features do not touch".
    """
    def by_temp_id(faces):
        out = {}
        for face in faces:
            edges = _probe(face, "edges", missing, "BRepFace.edges")
            if edges is None:
                return None
            for index in range(edges.count):
                edge = edges.item(index)
                temp_id = _probe(edge, "tempId", missing, "BRepEdge.tempId")
                if temp_id is None:
                    return None
                out[temp_id] = edge
        return out

    left, right = by_temp_id(first), by_temp_id(second)
    if left is None or right is None:
        return None
    return [left[key] for key in sorted(set(left) & set(right))]


def _origin_plane(component, datum_plane, missing):
    attribute = {"XY": "xYConstructionPlane", "XZ": "xZConstructionPlane", "YZ": "yZConstructionPlane"}[
        datum_plane
    ]
    return _probe(component, attribute, missing, "Component." + attribute)


def _origin_axis(component, datum_axis, missing):
    attribute = {"X": "xConstructionAxis", "Y": "yConstructionAxis", "Z": "zConstructionAxis"}[
        datum_axis
    ]
    return _probe(component, attribute, missing, "Component." + attribute)


def _recorded(owner, name, default=None):
    """Read a member for the *record only*.

    The distinction from _probe is the whole point of E16: _probe's result is
    branched on, so an absent member must refuse rather than default. A value
    read through _recorded is written into the report and compared against
    nothing, so recording it absent is honest rather than misleading.
    """
    value = getattr(owner, name, _MISSING)
    return default if value is _MISSING else value


def _token(entity):
    """An entityToken if this build exposes one. Evidence, never a premise."""
    value = _recorded(entity, "entityToken")
    return None if value is None else str(value)


def _build_fillet(component, step, built, created, undo, report, skipped, missing):
    """Round the edge two built features share, or record why this one was not.

    Fillets are the one archetype that is *individually optional*, and the
    reason is structural rather than lenient: a fillet is ordered last and
    nothing depends on it, so a fillet that cannot be placed costs exactly its
    own region and nothing downstream. Every other archetype carries dependents,
    which is why every other failure rolls the whole build back.

    Skipping is never silent. Each skip names the archetype, the two features,
    and what was missing, and the coverage account subtracts the region.

    Two features or one. A round on a box's own edge lies between two faces of a
    single extrude, and Fusion rounds it exactly as readily; what changes is only
    where the edge comes from. With two features it is the edges their face sets
    share; with one it is the edges shared by the two face sets the plan named --
    startFaces, endFaces or sideFaces -- and when those two sets are the same set
    it is that set's own interior edges. Nothing here decides which sets: the
    planner read that off the cap order it recorded, and an emitter that chose
    for itself would be rounding whichever edge it liked.
    """
    parents = [built.get(identifier) for identifier in step["between"]]
    if any(parent is None for parent in parents):
        first_missing = next(
            identifier
            for identifier, parent in zip(step["between"], parents)
            if parent is None
        )
        skipped.append(
            {
                "archetype_id": step["archetype_id"],
                "reason": "parent-feature-missing",
                "detail": "this run built no feature for " + first_missing,
            }
        )
        return
    fillets = _probe(component.features, "filletFeatures", missing, "Features.filletFeatures")
    if fillets is None:
        skipped.append(
            {
                "archetype_id": step["archetype_id"],
                "reason": "fillet-capability",
                "detail": "this Fusion does not expose " + ", ".join(missing),
            }
        )
        return
    one_feature = len(parents) == 1
    if one_feature:
        members = list(step["face_sets"])
        sources = [(parents[0], step["between"][0], member) for member in members]
    else:
        members = ["faces", "faces"]
        sources = list(zip(parents, step["between"], members))
    face_sets = [
        _feature_faces(parent, identifier, missing, member)
        for parent, identifier, member in sources
    ]
    if any(faces is None for faces in face_sets):
        skipped.append(
            {
                "archetype_id": step["archetype_id"],
                "reason": "fillet-capability",
                "detail": "a parent feature exposes no faces collection: " + ", ".join(missing),
            }
        )
        return
    if one_feature and members[0] == members[1]:
        # side-to-side: one face set against itself, whose shared edges are its
        # own interior ones. Intersecting the set with itself would return every
        # edge it touches, boundary edges included.
        edges = _internal_edges(face_sets[0], missing)
    else:
        edges = _shared_edges(face_sets[0], face_sets[1], missing)
    if edges is None:
        skipped.append(
            {
                "archetype_id": step["archetype_id"],
                "reason": "fillet-capability",
                "detail": "this Fusion does not expose " + ", ".join(missing),
            }
        )
        return
    if not edges:
        # Zero shared edges means the faces do not meet where the fit said they
        # do. Choosing some other edge to round would be inventing the geometry
        # the measurement failed to find.
        skipped.append(
            {
                "archetype_id": step["archetype_id"],
                "reason": "entity-resolution-ambiguous",
                "detail": (
                    "the faces this blend rounds share no edge, so there is no edge to round. "
                    "The blend fit says they meet; the built solid says they do not."
                ),
            }
        )
        return
    evidence = step.get("edge_evidence")
    selection = None
    if evidence is not None and len(edges) > 1:
        # More than one edge and a plan that says which: select. One edge needs
        # no selection, and a plan carrying no evidence names no edge to prefer.
        chosen, refusal = _edge_for_evidence(
            edges, evidence, float(step["edge_match_tolerance_cm"]), missing
        )
        if chosen is None:
            reason, detail = refusal
            skipped.append(
                {"archetype_id": step["archetype_id"], "reason": reason, "detail": detail}
            )
            return
        selection = {"candidates": len(edges), "selected": len(chosen)}
        edges = chosen
    collection = adsk.core.ObjectCollection.create()
    for edge in edges:
        collection.add(edge)
    try:
        fillet_input = fillets.createInput()
        fillet_input.addConstantRadiusEdgeSet(
            collection,
            adsk.core.ValueInput.createByString(step["radius_parameter"]),
            True,
        )
        feature = fillets.add(fillet_input)
    except Exception as error:
        skipped.append(
            {
                "archetype_id": step["archetype_id"],
                "reason": "feature-failed",
                "detail": str(error),
            }
        )
        return
    undo.append(("feature", feature))
    feature.name = step["feature_name"]
    built[step["archetype_id"]] = feature
    created.append(
        {
            "kind": "fillet",
            "archetype_id": step["archetype_id"],
            "feature_name": feature.name,
            "operation": step["operation"],
            "edge_count": len(edges),
            # Which edges, not just how many: with several rounds on one face
            # pair the count is one either way and only the identity says the
            # right edge was taken.
            "edge_tokens": [_token(edge) for edge in edges],
            # Present only when the plan's evidence chose among several edges,
            # so a reader can see that a choice was made and how wide the field
            # was; null when the face pair offered exactly one edge.
            "edge_selection": selection,
            "between": list(step["between"]),
            "edge_faces": step["edge_faces"],
            "token": _token(feature),
        }
    )


def run(context):
    report_attempted = False
    created = []
    undo = []
    report = {
        "kind": "mesh-rebuild",
        "ok": False,
        "project": PROJECT_NAME,
        "manifest_sha256": MANIFEST_SHA256,
        "plan_version": PLAN["plan_version"],
        "rebuild_nonce": PLAN["nonce"],
        "dump_sha256": PLAN["dump_sha256"],
        "program_sha256": PLAN["program_sha256"],
        "classification": PLAN["classification"],
        "mesh_source": PLAN["mesh_source"],
        "component_name": PLAN["component_name"],
        "units_note": PLAN["units_note"],
        "declared_thresholds": PLAN["thresholds"],
        "threshold_rationale": PLAN["threshold_rationale"],
        "adopted_constraint_note": PLAN["adopted_constraint_note"],
        "covered_area_fraction": PLAN["covered_area_fraction"],
        "unreconstructed": PLAN["unreconstructed"],
        "datum_transform": PLAN["datum_transform"],
        "created": [],
        "sketches": [],
        "user_parameters": [],
        "failures": [],
        "rollback": ROLLBACK_NOTE,
        "interactions_exercised": False,
    }
    try:
        app, design = _active_design()
        target_document = _require_target_document(app)
        _pump_events(app, design, target_document)
        report["fusion_version"] = _recorded(app, "version")

        missing = []
        root = _probe(design, "rootComponent", missing, "Design.rootComponent")
        user_parameters = _probe(design, "userParameters", missing, "Design.userParameters")
        occurrences = None
        if root is not None:
            occurrences = _probe(root, "occurrences", missing, "Component.occurrences")
        _probe(adsk.core, "ValueInput", missing, "adsk.core.ValueInput")
        _probe(adsk.core, "Matrix3D", missing, "adsk.core.Matrix3D")
        if missing:
            raise Refused(
                "rebuild-capability",
                "this Fusion does not expose the API members the rebuild needs: "
                + ", ".join(missing),
                {"missing": missing},
            )

        # A name already in use would be silently reused by `add`, and then the
        # rebuild would be driven by somebody else's number.
        existing = []
        for index in range(user_parameters.count):
            existing.append(user_parameters.item(index).name)
        planned = [row["name"] for row in PLAN["user_parameters"]]
        clashes = sorted(set(existing) & set(planned))
        if clashes:
            raise Refused(
                "parameter-name-collision",
                "these user parameters already exist in the document: " + ", ".join(clashes),
                {"names": clashes},
            )

        transform = adsk.core.Matrix3D.create()
        transform.setWithArray(PLAN["datum_transform"]["matrix"])
        occurrence = occurrences.addNewComponent(transform)
        undo.append(("occurrence", occurrence))
        component = occurrence.component
        component.name = PLAN["component_name"]
        created.append({"kind": "component", "name": component.name, "token": _token(occurrence)})

        for index, row in enumerate(PLAN["user_parameters"]):
            value = adsk.core.ValueInput.createByString(row["expression"])
            parameter = user_parameters.add(row["name"], value, row["unit"], row["comment"])
            undo.append(("parameter", parameter))
            # Re-read rather than trusting the call: `created` names what the
            # document now holds, not what was asked for.
            report["user_parameters"].append(
                {
                    "name": parameter.name,
                    "expression": parameter.expression,
                    "unit": row["unit"],
                    "quantity": row["quantity"],
                    "nominal": row["nominal"],
                    "expected_observable": row["expected_observable"],
                    "observable_rationale": row["observable_rationale"],
                    "driving_archetypes": row["driving_archetypes"],
                }
            )
            _pump_events_periodically(app, design, target_document, index)

        budget = int(PLAN["thresholds"]["constraint_rejection_budget"]["value"])
        displacement_tolerance = float(
            PLAN["thresholds"]["constraint_displacement_tolerance_mm"]["value"]
        )

        # Every feature this run builds, by archetype id. A fillet needs the two
        # features it rounds, and reads them from here rather than from the
        # timeline: what the fillet must round is what *this* transaction built.
        built = {}
        fillets_skipped = []

        for step in PLAN["steps"]:
            missing = []
            if step["kind"] == "fillet":
                _build_fillet(
                    component, step, built, created, undo, report, fillets_skipped, missing
                )
                _pump_events(app, design, target_document)
                continue
            plane_entity = _origin_plane(component, step["plane"]["datum_plane"], missing)
            if plane_entity is None:
                raise Refused(
                    "rebuild-capability",
                    "missing origin geometry: " + ", ".join(missing),
                    {"missing": missing},
                )
            offset_parameter = step["plane"]["offset_parameter"]
            if offset_parameter:
                planes = _probe(
                    component, "constructionPlanes", missing, "Component.constructionPlanes"
                )
                if planes is None:
                    raise Refused(
                        "rebuild-capability",
                        "missing origin geometry: " + ", ".join(missing),
                        {"missing": missing},
                    )
                plane_input = planes.createInput()
                plane_input.setByOffset(
                    plane_entity, adsk.core.ValueInput.createByString(offset_parameter)
                )
                plane_entity = planes.add(plane_input)
                undo.append(("plane", plane_entity))
                created.append(
                    {
                        "kind": "construction-plane",
                        "archetype_id": step["archetype_id"],
                        "offset_parameter": offset_parameter,
                        "token": _token(plane_entity),
                    }
                )

            sketch = component.sketches.add(plane_entity)
            undo.append(("sketch", sketch))
            sketch.name = step["sketch_name"]
            hole_point = None
            hole_dimensions = []
            if step["kind"] == "hole":
                # A hole's sketch holds one point and no curves: its size is the
                # fitted diameter carried on the feature, not a profile.
                hole_point, hole_dimensions = _place_hole_point(sketch, step, missing)
                curves = []
                if hole_point is None:
                    raise Refused(
                        "rebuild-capability",
                        "missing sketch placement API: " + ", ".join(missing),
                        {"missing": missing},
                    )
            else:
                curves = _build_entities(sketch, step, missing)
                if curves is None:
                    raise Refused(
                        "rebuild-capability",
                        "missing sketch geometry API: " + ", ".join(missing),
                        {"missing": missing},
                    )

            # The profile as the section measured it, before any snap touched it.
            # Deleting a rejected constraint removes the constraint; whether
            # Fusion also puts the geometry back where it was is not something
            # this transaction can establish, so the distance from this snapshot
            # is measured at the end and reported rather than assumed away.
            as_sectioned = _sketch_point_positions(sketch)
            applied = []
            rejected = []
            for entry in step["constraints"]:
                before = _sketch_point_positions(sketch)
                try:
                    handle = _apply_one(sketch, curves, entry, missing)
                except Refused:
                    raise
                except Exception as error:
                    rejected.append(dict(entry, reason="solver-error", error=str(error)))
                    continue
                if missing:
                    raise Refused(
                        "rebuild-capability",
                        "missing constraint API: " + ", ".join(missing),
                        {"missing": missing},
                    )
                moved = _worst_displacement(before, _sketch_point_positions(sketch))
                # A snap is *meant* to move geometry by up to the deviation it
                # erases; only the excess beyond that counts against the tolerance.
                snapped = entry["snapped_from"] if entry["snapped_from_unit"] == "mm" else 0.0
                excess = moved - snapped
                if excess > displacement_tolerance:
                    handle.deleteMe()
                    rejected.append(
                        dict(
                            entry,
                            reason="displacement",
                            measured_displacement_mm=moved,
                            excess_mm=excess,
                        )
                    )
                    continue
                applied.append(dict(entry, measured_displacement_mm=moved))

            dimensions_applied = []
            for entry in step["dimensions"]:
                before = _sketch_point_positions(sketch)
                try:
                    handle = _apply_dimension(sketch, curves, entry, missing)
                except Refused:
                    raise
                except Exception as error:
                    rejected.append(dict(entry, reason="solver-error", error=str(error)))
                    continue
                if handle is None:
                    raise Refused(
                        "rebuild-capability",
                        "missing dimension API: " + ", ".join(missing),
                        {"missing": missing},
                    )
                if not _bind(handle, entry["parameter"], missing):
                    raise Refused(
                        "rebuild-capability",
                        "missing dimension API: " + ", ".join(missing),
                        {"missing": missing},
                    )
                moved = _worst_displacement(before, _sketch_point_positions(sketch))
                if moved > displacement_tolerance:
                    handle.deleteMe()
                    rejected.append(
                        dict(entry, reason="displacement", measured_displacement_mm=moved)
                    )
                    continue
                dimensions_applied.append(dict(entry, measured_displacement_mm=moved))

            if len(rejected) > budget:
                raise Refused(
                    "constraint-rejected-budget-exceeded",
                    "the solver rejected "
                    + str(len(rejected))
                    + " of this sketch's constraints against a declared budget of "
                    + str(budget)
                    + "; a sketch where the solver fights the plan wholesale is evidence the plan "
                    "is wrong, and emitting its remnant would be improvisation.",
                    {"archetype_id": step["archetype_id"], "rejected": rejected},
                )

            constrained = _recorded(sketch, "isFullyConstrained", _MISSING)
            sketch_record = {
                "archetype_id": step["archetype_id"],
                "sketch_name": sketch.name,
                "entity_count": len(curves),
                "applied_constraints": applied,
                "rejected_constraints": rejected,
                "applied_dimensions": dimensions_applied + hole_dimensions,
                "rejection_budget": budget,
                "profile_displacement_mm": _worst_displacement(
                    as_sectioned, _sketch_point_positions(sketch)
                ),
                "profile_displacement_note": PROFILE_DISPLACEMENT_NOTE,
                "profile_evidence": step["profile_evidence"],
                "adopted_constraints": step["adopted_constraints"],
                "fully_constrained": (
                    "unavailable" if constrained is _MISSING else bool(constrained)
                ),
            }
            report["sketches"].append(sketch_record)

            # A hole is positioned by its sketch point and sized by its declared
            # diameter, so it needs no profile and no operation enum -- a hole
            # feature is a cut by construction.
            profile = None if step["kind"] == "hole" else _profile(sketch, step)
            operation = None
            if step["kind"] != "hole":
                operation = _operation(step["operation"], missing)
                if operation is None:
                    raise Refused(
                        "rebuild-capability",
                        "missing feature operation enum: " + ", ".join(missing),
                        {"missing": missing},
                    )
            features = component.features
            try:
                if step["kind"] == "hole":
                    holes = _probe(features, "holeFeatures", missing, "Features.holeFeatures")
                    if holes is None:
                        raise Refused(
                            "rebuild-capability",
                            "missing hole API: " + ", ".join(missing),
                            {"missing": missing},
                        )
                    feature_input = holes.createSimpleInput(
                        adsk.core.ValueInput.createByString(
                            step["placement"]["diameter_parameter"]
                        )
                    )
                    feature_input.setPositionBySketchPoint(hole_point)
                    feature_input.setDistanceExtent(
                        adsk.core.ValueInput.createByString(step["extent"]["parameter"])
                    )
                    feature = holes.add(feature_input)
                elif step["kind"] == "revolve":
                    axis = _origin_axis(component, step["axis"]["datum_axis"], missing)
                    if axis is None:
                        raise Refused(
                            "rebuild-capability",
                            "missing origin axis: " + ", ".join(missing),
                            {"missing": missing},
                        )
                    feature_input = features.revolveFeatures.createInput(profile, axis, operation)
                    feature_input.setAngleExtent(
                        False,
                        adsk.core.ValueInput.createByString(step["axis"]["angle_expression"]),
                    )
                    feature = features.revolveFeatures.add(feature_input)
                else:
                    feature_input = features.extrudeFeatures.createInput(profile, operation)
                    feature_input.setDistanceExtent(
                        False,
                        adsk.core.ValueInput.createByString(step["extent"]["parameter"]),
                    )
                    feature = features.extrudeFeatures.add(feature_input)
            except Refused:
                raise
            except Exception as error:
                raise Refused(
                    "feature-failed",
                    "Fusion refused to build " + step["archetype_id"] + ": " + str(error),
                    {"archetype_id": step["archetype_id"], "error": str(error)},
                )
            undo.append(("feature", feature))
            feature.name = step["feature_name"]
            built[step["archetype_id"]] = feature
            created.append(
                {
                    "kind": step["kind"],
                    "archetype_id": step["archetype_id"],
                    "feature_name": feature.name,
                    "operation": step["operation"],
                    "sketch_name": sketch.name,
                    "token": _token(feature),
                }
            )
            _pump_events(app, design, target_document)

        report["fillets_skipped"] = fillets_skipped
        if fillets_skipped:
            # Loud, and counted against coverage downstream. A fillet the build
            # could not place is a region that was planned and not delivered,
            # and a report that stayed quiet about it would let the coverage
            # fraction claim a feature nobody built.
            report["fillets_skipped_note"] = (
                "Fillets are individually optional: one whose edge set could not be resolved is "
                "skipped and named here rather than failing the whole rebuild. Each skipped fillet "
                "is an archetype the program declared and this run did not deliver, and the "
                "coverage account subtracts its region."
            )

        health = _timeline_health(design)
        report["timeline"] = health
        if health["unhealthy"]:
            raise Refused(
                "solver-unhealthy",
                "the timeline carries " + str(len(health["unhealthy"])) + " unhealthy item(s) "
                "after construction; the model Fusion holds is not the model the program declares.",
                {"unhealthy": health["unhealthy"]},
            )

        bodies = component.bRepBodies
        report["bodies"] = []
        for index in range(bodies.count):
            body = bodies.item(index)
            # Volume is recorded, not asserted, so an absent property is
            # recorded absent rather than aborting a build that succeeded.
            volume = _recorded(body, "volume")
            report["bodies"].append(
                {
                    "name": body.name,
                    "volume_mm3": None if volume is None else float(volume) * 1000.0,
                    "token": _token(body),
                }
            )
        report["created"] = created
        report["ok"] = True
        report_attempted = True
        _emit(report)
        return
    except Exception as error:
        if report_attempted:
            # The success report is already out. Rolling back now would delete a
            # model this transaction has told the caller it built.
            raise
        token = _recorded(error, "token")
        if isinstance(error, DocumentChangedError):
            token = "document-changed"
        remaining = []
        for kind, handle in reversed(undo):
            try:
                if not handle.deleteMe():
                    remaining.append(kind)
            except Exception as delete_error:
                remaining.append(kind + ": " + str(delete_error))
        # Both tokens, and the refusal first: an incomplete rollback is a second
        # thing that went wrong, not a replacement for the reason. `replan-without`
        # reads the first token, and attributing a drop to "rollback-incomplete"
        # would name the cleanup instead of the cause.
        report["failures"] = [token or "feature-failed"]
        if remaining:
            report["failures"].append("rollback-incomplete")
            report["rollback_remaining"] = remaining
        # `created` is what this transaction *delivers*, and a refusal delivers
        # nothing. What the document still holds is a separate question, and one
        # an empty `created` list must not be read as answering.
        report["created"] = []
        report["document_state"] = "dirty" if remaining else "rolled-back"
        report["document_state_note"] = (
            "Every entity this transaction created was deleted in reverse creation order."
            if not remaining
            else (
                "Deletion was attempted in reverse creation order and these did not go: "
                + ", ".join(remaining)
                + ". The document still holds them. Clean it up before re-running; do not replan "
                "against a dirty document."
            )
        )
        report["error"] = str(error)
        report["refusal_detail"] = _recorded(error, "detail", {})
        report_attempted = True
        report["traceback"] = traceback.format_exc()
        _emit(report)
        raise
'''


# --------------------------------------------------------------------------
# 7. the replan loop
# --------------------------------------------------------------------------


def replan_without(
    program: Mapping[str, Any], refusal_report: Mapping[str, Any]
) -> dict[str, Any]:
    """Move the archetype a refusal named into ``unreconstructed`` and re-hash.

    A mid-emission failure produces no geometry (E1/D8), and that is deliberate.
    It is also not the end of the workflow: this is the one explicit, recorded
    command that turns the refusal into a smaller program to try again with,
    rather than letting the transaction improvise inside Fusion.
    """
    from .reconstruction_program import program_sha256

    # Two refusal shapes reach this command and both are ours. The in-Fusion
    # transaction report carries `refusal_detail` and `failures`; the
    # *emission-time* refusal `emit-mesh-rebuild` prints is a
    # `ReconstructionRefused.to_dict()`, which carries `detail` and `refusal`.
    # `entity-resolution-ambiguous` is raised on both sides, so reading only the
    # transaction shape left the documented recovery loop dead for every refusal
    # that happened before the transaction ever ran.
    detail = refusal_report.get("refusal_detail") or refusal_report.get("detail") or {}
    named = detail.get("archetype_id")
    identifiers = [str(named)] if named else sorted(str(i) for i in detail.get("archetype_ids") or ())
    if not identifiers:
        raise ValueError(
            "The refusal report names no archetype, so there is nothing to replan without. Only "
            "archetype-scoped refusals can be replanned; a capability or hash refusal is about the "
            "document or the binding, not about one feature."
        )
    if refusal_report.get("document_state") == "dirty":
        raise ValueError(
            "The refusal report says its rollback was incomplete, so the document still holds "
            "part of the failed emission ("
            + ", ".join(refusal_report.get("rollback_remaining") or ())
            + "). Clean it up first: replanning against a dirty document would emit a second "
            "component beside the wreckage of the first."
        )
    failures = refusal_report.get("failures") or []
    if not failures and refusal_report.get("refusal"):
        # The emission-time shape names its one token under `refusal`.
        failures = [refusal_report["refusal"]]
    if not failures:
        raise ValueError(
            "The refusal report names no failure, so there is no recorded reason to write into "
            "the replanned program's gate."
        )
    token = str(failures[0])
    if token not in REBUILD_TRANSACTION_FAILURES | REBUILD_REFUSALS:
        raise ValueError(
            f"{token!r} is not in the rebuild's closed refusal vocabulary, so this is not a "
            "report this emitter produced. A gate nobody can look up is not a gate."
        )

    kept = [g for g in program["archetypes"] if str(g["id"]) not in identifiers]
    dropped = [g for g in program["archetypes"] if str(g["id"]) in identifiers]
    if not dropped:
        raise ValueError(
            f"The program contains none of the archetypes the refusal names ({', '.join(identifiers)})."
        )
    depending = sorted(
        str(g["id"]) for g in kept if set(g.get("dependencies") or ()) & set(identifiers)
    )
    if depending:
        raise ValueError(
            "Archetypes "
            + ", ".join(depending)
            + " depend on the one being dropped, so removing it alone would leave a dangling "
            "dependency. Replan the program from the fit record instead."
        )

    kept_regions = {region for group in kept for region in group["regions"]}
    unreconstructed = [dict(entry) for entry in program["unreconstructed"]]
    for group in dropped:
        for region in group["regions"]:
            if region in kept_regions:
                continue
            unreconstructed.append(
                {
                    "region_id": region,
                    "area_fraction": None,
                    "bounding_box": None,
                    "gate": (
                        f"{token}: emission refused this region's archetype {group['id']!r}, and "
                        "this replan moved it out of the built set rather than shipping a "
                        "half-emitted model."
                    ),
                }
            )
    unreconstructed.sort(key=lambda entry: str(entry["region_id"]))

    replanned = dict(program)
    replanned["archetypes"] = kept
    replanned["order"] = [i for i in program["order"] if str(i) not in identifiers]
    replanned["unreconstructed"] = unreconstructed
    replanned["user_parameters"] = [
        row
        for row in program["user_parameters"]
        if not row["driving_archetypes"]
        or any(str(a) not in identifiers for a in row["driving_archetypes"])
    ]
    # Coverage shrinks with the drop and is never carried forward: a coverage
    # fraction that outlived the features it counted would be a lie.
    replanned["covered_area_fraction"] = max(
        0.0, float(program["covered_area_fraction"]) - _dropped_coverage(program, identifiers)
    )
    replanned["replanned_from"] = {
        "program_sha256": str(program["program_sha256"]),
        "refusal": token,
        "dropped_archetypes": identifiers,
        "covered_area_fraction_basis": (
            "The dropped archetypes' own declared area fractions, summed and subtracted. Exact, "
            "except that a region shared by two archetypes is subtracted once per archetype, which "
            "understates the remaining coverage rather than overstating it."
        ),
    }
    replanned.pop("program_sha256", None)
    replanned["program_sha256"] = program_sha256(replanned)
    return replanned


def _dropped_coverage(program: Mapping[str, Any], identifiers: Sequence[str]) -> float:
    """The coverage the dropped archetypes contributed, from their own fractions.

    Every archetype the planner emits carries ``area_fraction``: the share of the
    scan's surface its regions account for. This used to prorate by *region
    count* instead, which on a real program said 0.4661 where the archetype's own
    number said 0.7731 -- an estimate standing next to the exact answer.

    Absent is refused rather than estimated: a program whose archetypes carry no
    area fraction was not planned by this version, and a coverage number derived
    from a guess would outlive the guess.
    """
    dropped = set(identifiers)
    total = 0.0
    for group in program["archetypes"]:
        if str(group["id"]) not in dropped:
            continue
        fraction = group.get("area_fraction")
        if isinstance(fraction, bool) or not isinstance(fraction, (int, float)):
            raise ValueError(
                f"Archetype {group['id']!r} carries no area_fraction, so the coverage it "
                "contributed cannot be subtracted. Re-plan the program with plan-reconstruction "
                "from this version of the skill."
            )
        total += float(fraction)
    # Two archetypes may share a region, in which case this subtracts that
    # region's share twice. That direction is the safe one: coverage is never
    # rounded up.
    return total


def load_program(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("A reconstruction program must be a JSON object.")
    return data
