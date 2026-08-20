"""Event stations, slabs, and the loops each slab's section closes.

The 2.5D decomposition, done host-side in stdlib arithmetic over the same dump
the fits came from.  Three ideas, in the order the evidence supports them:

* **Events** are the stations along the datum primary axis where the
  cross-section's topology can change.  Every accepted plane whose normal lies
  on that axis contributes one, carrying its own fitted offset sigma; every
  side region's axial span *ends* somewhere, and each end corroborates an event
  or becomes one.  They merge by complete linkage at a tolerance derived from
  those sigmas -- no millimetre constant decides whether two stations are one.
* **Slabs** are what lies between consecutive events.  The topology is constant
  there by construction, so one section characterises the slab -- and that claim
  is *checked* by sectioning at two more declared fractions and requiring the
  three to agree, rather than asserted.
* **Loops** are classified from the walls' own winding (``mesh_fitting``'s loop
  evidence) crossed with even-odd nesting: outer boundary, bore, cavity, island.

**Nothing here raises.**  Every way the decomposition can fail is recorded as a
named gate on the record, and the caller falls back to whatever it built before
slabs existed.  A stage that can only improve a plan has no business stopping
one, and the fail-closed outcome for a part this cannot decompose is exactly the
single-extrude plan it already had.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .mesh_datum import DatumFrame, RegionFit
from .mesh_fitting import (
    LOOP_EVIDENCE_GATES,
    Vec3,
    _dot,
    _sub,
    loop_material_evidence,
    section_mesh,
)

#: Every gate this stage can record.  Closed for the same reason every other
#: vocabulary in this package is: a token nobody declared is a token nobody can
#: write a handler for, and these reach the program's own `unreconstructed`.
SLAB_GATES = {
    "event-stations-absent",
    "slab-section-inconstant",
    "slab-axis-not-primary",
    "slab-loops-unclassified",
    # A station whose section left an open polyline or a junction behind: the
    # closed loops it did resolve are not the whole section, and the profile
    # built from them omits whatever the rest was.
    "slab-section-open",
    # Recorded by the planner rather than here: a gated slab with surviving
    # slabs on both sides leaves the stack in two pieces, and a join across the
    # gap fuses nothing.  The single-extrude plan stands instead.
    "slab-stack-discontinuous",
# A slab also carries whatever its own loops' evidence recorded -- a loop can
# reach a verdict *and* say how far that verdict can be trusted -- so those
# tokens are part of this stage's closed set rather than arriving from outside
# it. They are declared once, in `mesh_fitting`, and imported rather than
# restated so the two cannot drift.
} | set(LOOP_EVIDENCE_GATES)

#: How a slab's outline compares with the slab below it.  Recorded, never acted
#: on: slabs are join-only, so this drives no operation choice (see the design's
#: argument in C).  It is here so a reader can see which station parameter is
#: "this pocket's depth" without re-deriving it.
SLAB_RELATIONS = {"first", "same-outline", "step-in", "step-out", "disjoint"}

#: What a classified loop becomes.  ``unclassified`` is the honest fourth: the
#: loop's own evidence did not reach a verdict the table has a row for.
LOOP_ROLES = {"outer", "bore", "cavity", "island", "unclassified"}


def _positional_sigma(region: RegionFit) -> float | None:
    """The region's own positional uncertainty, whatever its kind calls it.

    Used for a *span end*, which is a bounding-box corner rather than a fitted
    parameter, so the record carries no sigma of its own for it.  A box corner is
    no better located than the surface that produced it, and that surface's own
    positional sigma is the only measurement of it this record holds -- which is
    why it is read here rather than a new constant being declared for it.
    """
    if region.fit is None:
        return None
    for key in ("offset", "axis_point", "center", "apex"):
        value = region.sigma(key)
        if value is not None and value > 0.0:
            return float(value)
    return None


def _angle_deg(a: Vec3, b: Vec3) -> float:
    dot = max(-1.0, min(1.0, _dot(a, b)))
    return math.degrees(math.acos(abs(dot)))


def _station(frame: DatumFrame, axis: Vec3, point: Vec3) -> float:
    return _dot(axis, _sub(point, frame.origin))


def _span(frame: DatumFrame, axis: Vec3, box: tuple[Vec3, Vec3]) -> tuple[float, float]:
    lo, hi = box
    stations = [
        _station(frame, axis, (x, y, z))
        for x in (lo[0], hi[0])
        for y in (lo[1], hi[1])
        for z in (lo[2], hi[2])
    ]
    return min(stations), max(stations)


def collect_event_candidates(
    regions: Sequence[RegionFit],
    frame: DatumFrame,
    axis: Vec3,
    *,
    angle_tolerance_deg: float,
    fallback_sigma: float,
) -> list[dict[str, Any]]:
    """Every station along ``axis`` the fit record has evidence for.

    Two kinds, and the record says which each one is:

    * ``plane-fit`` -- an accepted plane whose normal lies on the axis. Its
      station is its anchor projected onto the axis and its sigma is the fit's
      own ``offset`` sigma. This is the event-*defining* evidence: a plane
      perpendicular to the axis is where material starts or stops along it.
    * ``span-end`` -- one end of a side region's axial interval. This is
      *corroborating*: a side wall ends where some face bounds it, and that face
      may be one no fitter accepted, so its end is the only evidence that
      boundary exists at all.

    ``fallback_sigma`` is the caller's own declared length, used only where a
    fit carries no positional sigma; every use of it is recorded on the member
    so a reader can see which stations rest on a measured sigma and which do not.
    """
    candidates: list[dict[str, Any]] = []
    for region in regions:
        if not region.accepted or region.fit is None:
            continue
        direction = region.direction()
        if direction is None:
            continue
        on_axis = _angle_deg(direction, axis) <= angle_tolerance_deg
        anchor = region.anchor()
        if region.fit.kind == "plane" and on_axis and anchor is not None:
            sigma = region.sigma("offset")
            candidates.append(
                {
                    "kind": "plane-fit",
                    "region": region.region_hash,
                    "station": _station(frame, axis, anchor),
                    "sigma": float(sigma) if sigma is not None else float(fallback_sigma),
                    "sigma_source": "fit.offset" if sigma is not None else "declared-fallback",
                }
            )
            continue
        # Everything else that is a *side* of this axis: a plane perpendicular to
        # it, or a curved surface swept along it. Its span ends corroborate.
        perpendicular = region.fit.kind == "plane" and abs(_angle_deg(direction, axis) - 90.0) <= angle_tolerance_deg
        if not (perpendicular or (region.fit.kind != "plane" and on_axis)):
            continue
        sigma = _positional_sigma(region)
        low, high = _span(frame, axis, region.bounding_box)
        for label, value in (("low", low), ("high", high)):
            candidates.append(
                {
                    "kind": "span-end",
                    "region": region.region_hash,
                    "end": label,
                    "station": value,
                    "sigma": float(sigma) if sigma is not None else float(fallback_sigma),
                    "sigma_source": "fit.position" if sigma is not None else "declared-fallback",
                }
            )
    candidates.sort(key=lambda row: (row["station"], row["region"], row.get("end") or ""))
    return candidates


def merge_events(
    candidates: Sequence[Mapping[str, Any]],
    *,
    event_merge_sigmas: float,
    sigma_floor: float,
) -> list[dict[str, Any]]:
    """Complete-linkage merge at a tolerance derived from the members' own sigmas.

    A station joins the open cluster only while it lies within
    ``event_merge_sigmas * sqrt(sigma_i^2 + sigma_first^2)`` of the cluster's
    **first** member, never of its last: linking to the last is single linkage,
    and single linkage chains a row of closely-spaced real stations into one
    smear.  The same anti-chaining argument the normal-direction merge already
    makes.

    The merged station is the inverse-variance weighted mean of its members, so
    a fitted plane with a small sigma dominates the bounding-box corroborations
    that agree with it rather than being averaged away by them.

    ``sigma_floor`` is the caller's declared **section** tolerance, and it is the
    one thing here that is not derived from the fits.  It has to be: a plane
    fitted through analytically planar points -- which is what every one of these
    parts is, being an export from a solid modeller rather than a scan -- reports
    an offset sigma of *zero*, the derived tolerance collapses to zero with it,
    and nothing merges with anything.  Measured on POD-C-LID that produced 76
    event stations and a slab **nine microns** thick.  A sigma of zero is not a
    claim of infinite precision; it is the fitter saying the residual is below
    what it can see, and below the tolerance this stage sections at, two stations
    are not two stations it can tell apart.  So every member's sigma is floored
    there, using a number the caller already declares with its rationale.
    """
    floor = max(float(sigma_floor), 0.0)
    clusters: list[list[dict[str, Any]]] = []
    for row in candidates:
        entry = dict(row)
        entry["sigma_measured"] = entry["sigma"]
        entry["sigma"] = max(entry["sigma"], floor)
        if clusters and all(
            abs(entry["station"] - member["station"])
            <= event_merge_sigmas * math.hypot(entry["sigma"], member["sigma"])
            for member in clusters[-1]
        ):
            # *Complete* linkage: against every member, not against the first.
            # Testing only the first makes one imprecise member the cluster's
            # whole admission rule -- with sigmas 100, 0.01, 0.01 at stations
            # 0, 1, 2 the two precise plane fits merge through the loose one
            # even though their own joint tolerance is 0.042, which collapses
            # two real defining events and deletes the slab between them.
            clusters[-1].append(entry)
            continue
        clusters.append([entry])

    events: list[dict[str, Any]] = []
    for index, members in enumerate(clusters):
        weights = [1.0 / (m["sigma"] ** 2) if m["sigma"] > 0.0 else 0.0 for m in members]
        total = sum(weights)
        if total > 0.0:
            station = sum(w * m["station"] for w, m in zip(weights, members)) / total
            sigma = math.sqrt(1.0 / total)
        else:
            # No member carried a usable sigma, so nothing weights anything:
            # the plain mean, and a sigma of None rather than a fabricated zero.
            station = sum(m["station"] for m in members) / len(members)
            sigma = None
        for weight, member in zip(weights, members):
            member["weight"] = (weight / total) if total > 0.0 else None
        events.append(
            {
                "index": index,
                "station": station,
                "sigma": sigma,
                "defining_members": sum(1 for m in members if m["kind"] == "plane-fit"),
                "members": members,
            }
        )
    return events


# --------------------------------------------------------------------------
# sections, congruence, and the constancy guard
# --------------------------------------------------------------------------


def _project(points: Sequence[Vec3], frame: DatumFrame, u: Vec3, v: Vec3) -> list[tuple[float, float]]:
    return [(_dot(u, _sub(p, frame.origin)), _dot(v, _sub(p, frame.origin))) for p in points]


def _point_to_segment(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    span = dx * dx + dy * dy
    if span <= 0.0:
        return math.dist(p, a)
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / span))
    return math.dist(p, (a[0] + t * dx, a[1] + t * dy))


def hausdorff(first: Sequence[tuple[float, float]], second: Sequence[tuple[float, float]]) -> float:
    """Symmetric point-to-polyline Hausdorff between two closed loops.

    Point-to-*polyline*, not point-to-point: two sections of the same wall are
    sampled at different places along it, so a point-to-point distance would
    report the sampling rather than the geometry.

    ``ponytail:`` O(n*m) over loops of a few hundred points, which is
    microseconds; a segment index if a section ever gets long enough to matter.
    """

    def one_way(a: Sequence[tuple[float, float]], b: Sequence[tuple[float, float]]) -> float:
        worst = 0.0
        for point in a:
            best = min(
                _point_to_segment(point, b[i], b[(i + 1) % len(b)]) for i in range(len(b))
            )
            worst = max(worst, best)
        return worst

    if not first or not second:
        return math.inf
    return max(one_way(first, second), one_way(second, first))


def _centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(p[0] for p in points) / len(points),
        sum(p[1] for p in points) / len(points),
    )


def _signed_area(points: Sequence[tuple[float, float]]) -> float:
    n = len(points)
    return (
        sum(
            points[k][0] * points[(k + 1) % n][1] - points[(k + 1) % n][0] * points[k][1]
            for k in range(n)
        )
        / 2.0
    )


def _contains(polygon: Sequence[tuple[float, float]], point: tuple[float, float]) -> bool:
    inside = False
    n = len(polygon)
    for index in range(n):
        ax, ay = polygon[index]
        bx, by = polygon[(index + 1) % n]
        if (ay > point[1]) != (by > point[1]):
            span = by - ay
            if span == 0.0:
                continue
            if ax + (point[1] - ay) / span * (bx - ax) > point[0]:
                inside = not inside
    return inside


def polygon_centroid(points: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """The *area* centroid of a closed polygon, not the mean of its vertices.

    A vertex mean drifts toward wherever the tessellation happened to put more
    samples.  This centroid is what a planned profile is matched to Fusion's own
    enumeration by, so it has to be the property Fusion computes -- which is the
    area one.  Falls back to the vertex mean on a zero-area loop, which has no
    area centroid to have.
    """
    n = len(points)
    twice = sum(
        points[k][0] * points[(k + 1) % n][1] - points[(k + 1) % n][0] * points[k][1]
        for k in range(n)
    )
    if twice == 0.0:
        return _centroid(points)
    cross = [
        points[k][0] * points[(k + 1) % n][1] - points[(k + 1) % n][0] * points[k][1]
        for k in range(n)
    ]
    return (
        sum((points[k][0] + points[(k + 1) % n][0]) * cross[k] for k in range(n)) / (3.0 * twice),
        sum((points[k][1] + points[(k + 1) % n][1]) * cross[k] for k in range(n)) / (3.0 * twice),
    )


def roles_agree(
    here: Sequence[Mapping[str, Any]],
    there: Sequence[Mapping[str, Any]],
    pairs: Sequence[tuple[int, int]],
) -> bool:
    """Do two sections' loops carry the same roles, through their own pairing?

    Compared through the pairing ``congruence`` matched on, because
    ``section_mesh`` orders its polylines by the triangles it intersected and
    that order is not the same at two stations.
    """
    here_roles = [loop["role"] for loop in here]
    there_roles = [loop["role"] for loop in there]
    return all(
        here_roles[first] == there_roles[second]
        for first, second in pairs
        if first < len(here_roles) and second < len(there_roles)
    )


def _minimax_assignment(cost: Sequence[Sequence[float]]) -> dict[int, int]:
    """The one-to-one pairing whose worst pair is as cheap as possible.

    Bottleneck assignment, because that is the question the caller asks: is
    there a pairing in which *every* pair is plausible? Feasibility at a given
    ceiling is a bipartite matching, and the smallest workable ceiling is one
    of the costs -- so binary search the sorted costs and keep the last
    matching that was perfect. Sections carry loops in the tens, so O(n^3 log n)
    on numbers already computed is nothing beside the Hausdorff pass that
    follows.

    ponytail: minimises the worst pair, not the sum. The verdict is a maximum,
    so a total-cost assignment (Hungarian) would optimise the wrong number;
    swap it in only if some consumer ever needs the sum.
    """
    size = len(cost)
    if size == 0:
        return {}

    def perfect_within(ceiling: float) -> list[int] | None:
        owner = [-1] * size
        def augment(row: int, seen: set[int]) -> bool:
            for column in range(size):
                if cost[row][column] > ceiling or column in seen:
                    continue
                seen.add(column)
                if owner[column] == -1 or augment(owner[column], seen):
                    owner[column] = row
                    return True
            return False
        for row in range(size):
            if not augment(row, set()):
                return None
        return owner

    ceilings = sorted({value for row in cost for value in row})
    low, high, best = 0, len(ceilings) - 1, None
    while low <= high:
        middle = (low + high) // 2
        owner = perfect_within(ceilings[middle])
        if owner is None:
            low = middle + 1
        else:
            best, high = owner, middle - 1
    # The largest cost admits every pair, so a perfect matching always exists.
    assert best is not None
    return {row: column for column, row in enumerate(best)}


def containment_parents(loops: Sequence[Sequence[tuple[float, float]]]) -> list[int | None]:
    """Each loop's *immediate* parent: the innermost loop that still contains it."""
    depths = [
        sum(
            1
            for other, polygon in enumerate(loops)
            if other != index and _contains(polygon, points[0])
        )
        for index, points in enumerate(loops)
    ]
    parents: list[int | None] = []
    for index, points in enumerate(loops):
        containing = [
            other
            for other, polygon in enumerate(loops)
            if other != index and _contains(polygon, points[0])
        ]
        parents.append(max(containing, key=lambda other: depths[other]) if containing else None)
    return parents


def profile_regions(loops: Sequence[Sequence[tuple[float, float]]]) -> list[dict[str, Any]]:
    """Every region Fusion enumerates for this loop set, and which of them is material.

    **Measured against a live Fusion, because the obvious model is wrong.** A
    sketch of four nested and disjoint rectangles -- an outer square, two islands
    in it, and one more square inside the first island -- enumerates *four*
    profiles, not two: Fusion reports one region per loop, each being that loop
    minus its immediate children, regardless of nesting parity. It does not know
    which regions are holes; it reports the planar subdivision.

    So this returns a region for every loop, and flags the even-depth ones as
    ``material``. The executor extrudes the material regions and must still
    account for the rest, because a profile the plan cannot name is geometry the
    transaction would be silently leaving out of the feature.

    A region's area is its own minus its immediate children's, and its centroid
    is the area-weighted difference of the same -- the two properties Fusion
    reports, computed the way Fusion computes them. Verified against the probe:
    92, 3, 4 and 1 cm2 planned, 92, 3, 4 and 1 reported.
    """
    parents = containment_parents(loops)
    depths: list[int] = []
    for index in range(len(loops)):
        depth, walk = 0, parents[index]
        while walk is not None:
            depth += 1
            walk = parents[walk]
        depths.append(depth)

    regions: list[dict[str, Any]] = []
    for index, points in enumerate(loops):
        area = abs(_signed_area(points))
        moment = [value * area for value in polygon_centroid(points)]
        children = sorted(other for other, parent in enumerate(parents) if parent == index)
        for child in children:
            child_area = abs(_signed_area(loops[child]))
            child_centre = polygon_centroid(loops[child])
            area -= child_area
            moment = [moment[k] - child_centre[k] * child_area for k in range(2)]
        regions.append(
            {
                "boundary_loop": index,
                "hole_loops": children,
                "depth": depths[index],
                "material": depths[index] % 2 == 0,
                "area_mm2": area,
                "centroid_mm": (
                    [moment[k] / area for k in range(2)]
                    if area > 0.0
                    else list(polygon_centroid(points))
                ),
            }
        )
    return regions


def congruence(
    first: Sequence[Sequence[tuple[float, float]]],
    second: Sequence[Sequence[tuple[float, float]]],
    *,
    tolerance: float,
) -> dict[str, Any]:
    """Do two sections close the same loops in the same places?

    Loops are matched between the two sections by nearest centroid, one to one,
    and every matched pair must lie within ``tolerance`` of the other as a
    polyline.  A count mismatch is a topology change and needs no distance to be
    a disagreement.
    """
    if len(first) != len(second):
        return {
            "agrees": False,
            "reason": f"loop counts differ: {len(first)} and {len(second)}",
            "worst_hausdorff": None,
            "loop_counts": [len(first), len(second)],
        }
    # A *global* assignment, not a per-loop greedy and not a greedy over the
    # sorted pairs either. Taking the cheapest available pair in turn
    # still lets one pair consume the only viable partner another needed: with
    # centres at 0 and 3 against 1 and -2, the cheapest pair is 0-1 at a cost of
    # 1, which forces 3--2 at 5, while pairing 0--2 with 3-1 costs 2 for both.
    # A tolerance between the two then gates a constant slab. So the assignment
    # minimises the *worst* pair rather than accepting the best one first, which
    # is the quantity the verdict below is about.
    #
    # The cost is the *area* centroid's distance plus the normalised area
    # difference, and both terms are needed. The vertex mean drifts with the
    # tessellation, and concentric loops share a centre exactly -- an outer
    # wall, its cavity and the island in it are indistinguishable by centroid
    # alone, which paired an outer loop with an island and reported a perfectly
    # prismatic slab as inconstant.
    centres_first = [polygon_centroid(loop) for loop in first]
    centres_second = [polygon_centroid(loop) for loop in second]
    areas_first = [abs(_signed_area(loop)) for loop in first]
    areas_second = [abs(_signed_area(loop)) for loop in second]
    # The area term is normalised by *each pair's own* size, not by the
    # section's largest loop. Normalising by the section made a big outer
    # boundary swamp the term and let two differently sized inner loops pair on
    # centroid alone. Hausdorff would be the direct geometric cost, and it is
    # deliberately not the one used here: it is O(n*m) per pair over every pair
    # of a section that can carry tens of loops of hundreds of points, inside a
    # per-slab loop, and centroid-plus-relative-area separates the cases that
    # were measured to go wrong. The Hausdorff still decides *agreement* on the
    # pairing this produces.
    cost = [
        [
            math.dist(centres_first[i], centres_second[j])
            + abs(areas_first[i] - areas_second[j])
            / max(areas_first[i], areas_second[j], 1e-09)
            for j in range(len(second))
        ]
        for i in range(len(first))
    ]
    matched = _minimax_assignment(cost)
    worst = 0.0
    pairs: list[tuple[int, int, float]] = []
    for index in sorted(matched):
        partner = matched[index]
        distance = hausdorff(first[index], second[partner])
        pairs.append((index, partner, distance))
        worst = max(worst, distance)
    agrees = bool(pairs) and worst <= tolerance
    return {
        "agrees": agrees if pairs else len(first) == 0,
        "reason": (
            None
            if agrees or not pairs
            else f"loop pair {max(pairs, key=lambda p: p[2])[:2]} differs by {worst:.6g}"
        ),
        "worst_hausdorff": worst if pairs else None,
        "loop_counts": [len(first), len(second)],
        # Which loop of the first section is which loop of the second. The
        # geometry is matched by centroid, so anything else compared between
        # the two sections has to be compared through the same pairing --
        # `section_mesh` orders its polylines by the triangles it intersected,
        # and that order is not the same at two stations.
        "pairs": [(index, other) for index, other, _distance in pairs],
    }


# --------------------------------------------------------------------------
# loop roles
# --------------------------------------------------------------------------


def classify_loops(
    loops: Sequence[Mapping[str, Any]],
    projected: Sequence[Sequence[tuple[float, float]]],
    bore_regions: set[str],
) -> list[dict[str, Any]]:
    """The design's classification table, applied to measured loop evidence.

    | depth | verdict | walls | role |
    | even | material-inside | -- | outer (depth 0) or island (depth >= 2, inside a cavity) |
    | odd | material-outside | all fitted walls are bores this program cuts | bore |
    | odd | material-outside | anything else | cavity |

    A bore is identified by the **region identity** of its walls, not by matching
    a declared centre and diameter: at plan time the bore regions are already
    known by hash, and identity is stronger evidence than a centre agreeing to a
    tolerance. A loop whose evidence reached no material verdict is
    ``unclassified`` and carries whatever gate the evidence recorded.
    """
    parents: list[int | None] = []
    for index, points in enumerate(projected):
        containing = [
            other
            for other, polygon in enumerate(projected)
            if other != index and _contains(polygon, points[0])
        ]
        parents.append(
            max(containing, key=lambda other: len(projected[other])) if containing else None
        )
        if containing:
            # The immediate parent is the containing loop that is itself most
            # deeply contained -- the innermost box that still holds this one.
            parents[index] = max(containing, key=lambda other: loops[other]["depth"])

    classified: list[dict[str, Any]] = []
    for index, loop in enumerate(loops):
        depth, verdict = loop["depth"], loop["verdict"]
        parent = parents[index]
        walls = set(loop["wall_regions"])
        role = "unclassified"
        if verdict == "material-inside" and depth % 2 == 0:
            role = "outer" if depth == 0 else "island"
        elif verdict == "material-outside" and depth % 2 == 1:
            # `cavity` is what "these walls belong to no bore this program
            # cuts" means, and that is only a statement when the walls are
            # *known*. A fit record written before `triangle_indices` existed
            # leaves every loop with no wall regions at all, and calling those
            # loops cavities would label a real bore -- one the same program
            # separately plans as a hole -- on the absence of evidence.
            if walls:
                role = "bore" if walls <= bore_regions else "cavity"
            elif not bore_regions:
                # No bore is planned anywhere on this part, so there is no bore
                # for an unattributed loop to be one of.
                role = "cavity"
        classified.append(
            {
                "polyline_index": loop["polyline_index"],
                "role": role,
                "depth": depth,
                "parent": parent,
                "verdict": verdict,
                "consensus_fraction": loop["consensus_fraction"],
                "parity_agrees": loop["parity_agrees"],
                "signed_area_mm2": loop["signed_area_mm2"],
                "perimeter_mm": loop["perimeter_mm"],
                "point_count": loop["point_count"],
                "wall_regions": loop["wall_regions"],
                "gates": loop["gates"],
            }
        )
    return classified


# --------------------------------------------------------------------------
# the decomposition
# --------------------------------------------------------------------------


def _relation(
    outer: Mapping[str, Any] | None,
    below: Mapping[str, Any] | None,
    tolerance: float,
    *,
    is_first: bool,
) -> str:
    """How this slab's outline compares with the one under it -- reporting only.

    ``is_first`` is passed rather than inferred from ``below is None``: a slab
    whose neighbour closed no outer loop is not the bottom of the stack, and
    reporting it as ``first`` would say the stack starts in the middle.
    """
    if is_first:
        return "first"
    if outer is None or below is None:
        return "disjoint"
    here, there = abs(outer["signed_area_mm2"]), abs(below["signed_area_mm2"])
    scale = math.sqrt(max(here, there)) if max(here, there) > 0.0 else 1.0
    if abs(here - there) <= tolerance * scale:
        return "same-outline"
    return "step-in" if here < there else "step-out"


def decompose(
    regions: Sequence[RegionFit],
    frame: DatumFrame,
    vertices: Sequence[Vec3],
    triangles: Sequence[Sequence[int]],
    *,
    gates: Mapping[str, Any],
    angle_tolerance_deg: float,
    fallback_sigma: float,
    bore_regions: set[str] | None = None,
    triangle_regions: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    """Events, slabs, sections, constancy and loop roles, in one record.

    Never raises.  ``usable`` says whether the caller may plan slabs from this;
    when it is false, ``gate`` names why in the closed vocabulary above and the
    caller keeps whatever it planned without slabs.
    """
    axis = frame.z_axis
    u, v = frame.x_axis, frame.y_axis
    bores = set(bore_regions or ())
    merge_sigmas = float(gates["event_merge_sigmas"])
    constancy_tolerance = float(gates["slab_constancy_tolerance_mm"])
    fractions = [float(f) for f in gates["slab_section_fractions"]]
    section_tolerance = float(gates["section_tolerance_mm"])

    candidates = collect_event_candidates(
        regions,
        frame,
        axis,
        angle_tolerance_deg=angle_tolerance_deg,
        fallback_sigma=fallback_sigma,
    )
    events = merge_events(
        candidates, event_merge_sigmas=merge_sigmas, sigma_floor=section_tolerance
    )
    defining = sum(1 for event in events if event["defining_members"])
    if len(events) < 2 or defining < 2:
        return {
            "usable": False,
            "gate": "event-stations-absent",
            "detail": (
                f"{len(events)} event station(s) on the datum primary axis, of which {defining} "
                "rest on an accepted axis-normal plane. A part with fewer than two caps along its "
                "own datum axis has no 2.5D structure to decompose, so the existing single-extrude "
                "path stands."
            ),
            "events": events,
            "slabs": [],
        }

    def section_at(station: float) -> Any:
        point = tuple(
            frame.origin[i] + axis[i] * station for i in range(3)
        )
        return section_mesh(vertices, triangles, point, axis, tolerance=section_tolerance)

    def measure(station: float) -> tuple[dict[str, Any], list[list[tuple[float, float]]]]:
        section = section_at(station)
        evidence = loop_material_evidence(
            section,
            vertices,
            triangles,
            axis,
            consensus_fraction=float(gates["loop_material_consensus_fraction"]),
            attribution_min_fraction=float(gates["loop_attribution_min_fraction"]),
            triangle_regions=triangle_regions,
        )
        closed = [
            line for line in section.polylines if line.closed and len(line.points) >= 3
        ]
        # What this filter drops is evidence, not noise. An open polyline or a
        # junction at this station is material the section could not resolve
        # into a boundary, and every gate below reads the retained closed loops
        # only -- so a slab with an unresolved component stayed usable, claimed
        # its regions as reconstructed, and emitted a profile that omits it.
        unresolved = sum(1 for line in section.polylines if not line.closed) + len(
            section.junctions
        )
        return evidence, [_project(line.points, frame, u, v) for line in closed], unresolved

    slabs: list[dict[str, Any]] = []
    for index in range(len(events) - 1):
        lower, upper = events[index], events[index + 1]
        height = upper["station"] - lower["station"]
        mid = lower["station"] + height / 2.0
        evidence, projected, unresolved = measure(mid)
        loops = classify_loops(evidence["loops"], projected, bores)
        checks = []
        constant = True
        station_gates: set[str] = set()
        station_projected: list[list[list[tuple[float, float]]]] = []
        for fraction in fractions:
            other_station = lower["station"] + height * fraction
            other_evidence, other_projected, other_unresolved = measure(other_station)
            station_projected.append(other_projected)
            unresolved += other_unresolved
            verdict = congruence(projected, other_projected, tolerance=constancy_tolerance)
            verdict["fraction"] = fraction
            verdict["station"] = other_station
            if verdict["agrees"]:
                # Through the pairing `congruence` just established, not by
                # list position: two stations can close the same loops and emit
                # them in a different order, and a positional comparison then
                # reports differing verdicts for a slab that is constant.
                here_verdicts = [loop["verdict"] for loop in evidence["loops"]]
                there_verdicts = [loop["verdict"] for loop in other_evidence["loops"]]
                # Every station's own evidence gates, not only the midpoint's.
                # A quarter-section loop can carry `slab-wall-unattributed`
                # while keeping the midpoint's material verdict, and the slab's
                # gates are derived from the midpoint loops alone -- so that
                # station's failure was measured, recorded on nothing, and the
                # slab's regions were claimed as reconstructed.
                station_gates.update(
                    gate for loop in other_evidence["loops"] for gate in loop["gates"] or ()
                )
                verdict["agrees"] = all(
                    here_verdicts[index] == there_verdicts[other]
                    for index, other in verdict["pairs"]
                    if index < len(here_verdicts) and other < len(there_verdicts)
                )
                if not verdict["agrees"]:
                    verdict["reason"] = "the loops' material verdicts differ between stations"
            if verdict["agrees"] and not roles_agree(
                loops,
                classify_loops(other_evidence["loops"], other_projected, bores),
                verdict["pairs"],
            ):
                # The same argument the coalescing test makes, one level down:
                # a material verdict is not a role. Two stations of one slab can
                # close congruent loops that agree about being holes and
                # disagree about *which* hole -- a same-radius inner loop that
                # is a planned bore's wall at one station and an unclaimed
                # cavity at the other, which is a section change, and the slab's
                # `loops` (the midpoint's) would then describe only half its own
                # height while the record called it constant.
                verdict["agrees"] = False
                verdict["reason"] = "the loops' roles differ between stations"
            constant = constant and bool(verdict["agrees"])
            checks.append(verdict)
        outer = next((loop for loop in loops if loop["role"] == "outer"), None)
        slabs.append(
            {
                "index": index,
                "lower_event": index,
                "upper_event": index + 1,
                "station_lo": lower["station"],
                "station_hi": upper["station"],
                "height": height,
                "section_station": mid,
                "constancy": {
                    "constant": constant,
                    "tolerance": constancy_tolerance,
                    "fractions": fractions,
                    "checks": checks,
                },
                "winding": evidence["winding"],
                "loops": loops,
                # `slab-loops-unclassified` is about the whole section, not only
                # its outer boundary. An inner loop whose own walls reached no
                # material verdict is one this stage cannot tell a bore from a
                # cavity, and building the slab anyway would count its regions
                # as reconstructed on a question nobody answered.
                #
                # A loop that *did* reach a verdict can still carry its own gate
                # -- `slab-wall-unattributed` is the case: enough of the walls
                # voted to name a role, and more of the length than the caller
                # declared tolerable was attributed to nothing. The role is a
                # verdict; the gate is the evidence saying how far it can be
                # trusted, and reading only the role throws that away.
                # `slab-section-open` leads, because it is a fact about the
                # section itself and everything below is derived from that
                # section: loops that did not classify and stations that did not
                # agree are what an unresolved section produces, and naming the
                # derived failure first sends a reader to the wrong measurement.
                "gates": ([] if not unresolved else ["slab-section-open"])
                + (
                    []
                    if constant
                    else ["slab-section-inconstant"]
                )
                + (
                    []
                    if outer is not None
                    and not any(loop["role"] == "unclassified" for loop in loops)
                    else ["slab-loops-unclassified"]
                )
                + sorted(
                    {gate for loop in loops for gate in loop["gates"] or ()} | station_gates
                ),
                "relation_to_below": "first",
                "_projected": projected,
                "_station_projected": station_projected,
                "_outer": outer,
            }
        )

    # Coalescing: an event whose two adjacent slabs section to congruent loop
    # sets is not a topology change -- it is a real plane that happens to sit
    # flush, a boss top level with a wall. It is demoted to corroboration and the
    # slabs merge, recorded on the event rather than silently dropped.
    coalesced: list[int] = []
    index = 0
    while index < len(slabs) - 1:
        here, below = slabs[index], slabs[index + 1]
        verdict = congruence(
            here["_projected"], below["_projected"], tolerance=constancy_tolerance
        )
        if verdict["agrees"]:
            # Congruent geometry is not the same section. Two slabs can close
            # the same loops in the same places and disagree about what those
            # loops *are* -- a same-radius inner loop that is a planned bore's
            # wall below and an unclaimed cavity above. Merging keeps only the
            # lower slab's `loops`, so the upper slab's roles would be dropped
            # and the program would describe that cavity as the bore. Compared
            # through the pairing `congruence` matched on, for the same reason
            # the constancy check compares its verdicts through it.
            if not roles_agree(here["loops"], below["loops"], verdict["pairs"]):
                index += 1
                continue
            # Congruence is not transitive at a fixed tolerance. Each slab holds
            # its own sections to within the tolerance and their midpoints agree
            # to within it, so two stations at opposite ends of the merged slab
            # are bounded only by the sum -- twice the tolerance for one merge,
            # and more for a chain of them -- while the record keeps the lower
            # slab's `loops` and calls the whole merged height constant. Every
            # station the upper slab actually sampled is therefore checked
            # against the profile that survives the merge, which is the one
            # reference the constancy claim is about, so the bound stays one
            # tolerance however many slabs coalesce.
            if not all(
                congruence(here["_projected"], sampled, tolerance=constancy_tolerance)[
                    "agrees"
                ]
                for sampled in below["_station_projected"]
            ):
                index += 1
                continue
            coalesced.append(here["upper_event"])
            events[here["upper_event"]]["coalesced"] = {
                "into": [here["index"], below["index"]],
                "worst_hausdorff": verdict["worst_hausdorff"],
                "reason": (
                    "both adjacent slabs section to congruent loop sets, so this plane bounds no "
                    "topology change; it is corroboration for the geometry, not a slab boundary."
                ),
            }
            merged = dict(here)
            # Every station either slab sampled, so a third slab coalescing on
            # top is checked against the whole merged range rather than only
            # the range the first pair happened to cover.
            merged["_station_projected"] = (
                here["_station_projected"]
                + below["_station_projected"]
                + [below["_projected"]]
            )
            merged["upper_event"] = below["upper_event"]
            merged["station_hi"] = below["station_hi"]
            merged["height"] = merged["station_hi"] - merged["station_lo"]
            merged["gates"] = sorted(set(here["gates"]) | set(below["gates"]))
            # `section_station`, `constancy.checks` and `loops` came off the
            # lower slab and are not re-measured: the two slabs sectioned to
            # congruent loop sets, which is *why* they merged, so the evidence
            # does describe the merged slab -- but it was taken over the lower
            # slab's stations only, and `section_station` is no longer the
            # merged slab's midpoint.  Say so on the record rather than leave a
            # reader to notice that the checks lie in one half of what they are
            # attached to.  A slab merged twice keeps the range it was first
            # measured over, not the widened one.
            merged["constancy"] = dict(
                here["constancy"],
                measured_over=here["constancy"].get(
                    "measured_over", [here["station_lo"], here["station_hi"]]
                ),
                measured_over_note=(
                    "this slab is two or more coalesced slabs; section_station, "
                    "constancy.checks and loops were measured over measured_over, not over the "
                    "merged slab's full height. The coalescing test is what licenses reading "
                    "them as the merged slab's: see the events' coalesced.worst_hausdorff."
                ),
            )
            slabs[index : index + 2] = [merged]
            continue
        index += 1

    relations = [
        _relation(
            slab["_outer"],
            slabs[position - 1]["_outer"] if position else None,
            constancy_tolerance,
            is_first=position == 0,
        )
        for position, slab in enumerate(slabs)
    ]
    for position, slab in enumerate(slabs):
        slab["index"] = position
        slab["relation_to_below"] = relations[position]
        del slab["_projected"]
        del slab["_station_projected"]
        del slab["_outer"]

    return {
        "usable": True,
        "gate": None,
        "detail": None,
        "events": events,
        "coalesced_events": coalesced,
        "slabs": slabs,
        "declared": {
            "event_merge_sigmas": merge_sigmas,
            "slab_constancy_tolerance_mm": constancy_tolerance,
            "slab_section_fractions": fractions,
            "section_tolerance_mm": section_tolerance,
            "loop_material_consensus_fraction": float(gates["loop_material_consensus_fraction"]),
            "loop_attribution_min_fraction": float(gates["loop_attribution_min_fraction"]),
        },
        "note": (
            "Event stations come from the fits' own offsets and sigmas, corroborated by side "
            "regions' axial span ends; the merge tolerance is derived per pair from those sigmas "
            "and no millimetre constant decides it. Loop roles come from the walls' own winding "
            "crossed with even-odd nesting, never from the fits' coverage. Nothing here raises: a "
            "decomposition that does not hold is recorded and the single-extrude plan stands."
        ),
    }
