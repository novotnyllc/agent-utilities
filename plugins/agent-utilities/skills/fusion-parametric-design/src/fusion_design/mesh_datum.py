"""Fit-record parsing, fit uncertainty, and datum-frame derivation.

Pure arithmetic over U2's fit record: no Fusion, no live API, stdlib only.  Two
jobs live here, and they are together because the second is built from the first.

* **Reading the fit record** into typed regions, refusing a record that is
  missing a field this stage needs rather than substituting a default.  A
  missing field means *we cannot judge*, and turning that into *the condition
  was not met* is the exact defect this module is written to avoid.
* **Deriving the datum frame** from the accepted fits under a total, stated
  tie-break order.  When the scores do not separate two candidates by the
  caller's declared margin, the axis is settled by a canonical rule over their
  *directions* and labelled ``arbitrary-canonical`` in the program, and it is
  refused only when even that rule cannot be shown to be reproducible.  A datum
  chosen by an unstated rule is not reproducible, and reproducibility is what
  makes the model reviewable; a datum chosen by a stated arbitrary rule is
  reproducible, and saying which of the two it was is the honest part.

Uncertainty handling is deliberately a thin, replaceable layer: a fit's
uncertainty is read from the record, never estimated here.  When the record
carries none, an uncertainty-based judgement **refuses**; it never quietly
becomes an absolute-threshold judgement wearing the same label.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from .manifest import _in_closed_set
from .mesh_fitting import (
    MOTION_MOMENT_FIELDS,
    PRIMITIVE_KINDS,
    PrimitiveFit,
    Vec3,
    _add,
    _angle_deg,
    _canonical_direction,
    _cross,
    _dot,
    _length,
    _scale,
    _sub,
    _unit,
)


_HEX64_RE = re.compile(r"\A[0-9a-f]{64}\Z")

# The closed refusal vocabulary this stage can produce.  Nothing outside this
# set is raised as a refusal; an internal error stays an ordinary exception so
# it cannot be mistaken for a considered "no".
DATUM_REFUSALS = {
    "fit-record-malformed",
    "fit-record-moments-unbound",
    "fit-record-missing-axial-span",
    "fit-record-missing-uncertainty",
    "frame-no-accepted-fits",
    "frame-ambiguous",
    "frame-x-underdetermined",
}

# What each refusal leaves the caller able to do instead.  R14: a refusal names
# its alternative, or it is just a failure with better manners.
REFUSAL_ALTERNATIVES = {
    "fit-record-malformed": (
        "Re-run the fitting stage; this record cannot be read and nothing downstream may guess at it."
    ),
    "fit-record-moments-unbound": (
        "This region's moment block does not describe this region's facets: its facet count or its "
        "area disagrees with the region's own. Re-run the fitting stage against the same dump, "
        "which writes both from the same triangles."
    ),
    "fit-record-missing-axial-span": (
        "Re-run the fitting stage so each cylinder and cone carries its supporting axial span, or "
        "declare a frame source that does not rank cylinders."
    ),
    "fit-record-missing-uncertainty": (
        "Re-run the fitting stage so each accepted fit carries its parameter uncertainty, or declare "
        "tolerance_basis 'declared-absolute' and state the absolute tolerances and why they are right."
    ),
    "frame-no-accepted-fits": (
        "Nothing was fitted, so there is nothing to derive a frame from. Revisit segmentation and the "
        "disproof gates before asking for a frame."
    ),
    "frame-ambiguous": (
        "Two candidates are within the declared margin and the canonical tie-break cannot separate "
        "them reproducibly: their measured direction uncertainty reaches the quantization grid, so a "
        "re-tessellation could hand back the other one. Either declare a smaller angle_tolerance_deg "
        "with a rationale, re-fit so the directions carry a smaller sigma, or name the axis explicitly."
    ),
    "frame-x-underdetermined": (
        "No plane parallel to the primary axis and no second axis off it, so the rotation about the "
        "primary axis is not observable. Fit more of the part, or name the secondary axis explicitly."
    ),
}

# Which uncertainty keys a fit of each kind is expected to carry.  This is the
# drop-in point for the uncertainty-propagation work: widen the tuples, and the
# licensing arithmetic downstream picks the new sigmas up unchanged.
FIT_UNCERTAINTY_KEYS = {
    "plane": ("normal_deg", "offset"),
    "cylinder": ("axis_direction_deg", "axis_point", "radius"),
    "cone": ("axis_direction_deg", "apex", "half_angle_deg"),
    "sphere": ("center", "radius"),
    # A torus is never a licensable subject -- it appears in no entry of
    # LICENSE_SIGMAS, so no relationship is ever measured against one. The only
    # number this pipeline reads from a torus is its minor radius, which becomes
    # a fillet's radius parameter, so that is the only sigma it must carry.
    # Listed rather than omitted because an omitted kind raised KeyError here,
    # which is a crash where a named refusal belongs.
    "torus": ("minor_radius",),
}

TOLERANCE_BASES = {"uncertainty", "declared-absolute"}

#: How a datum axis was settled.  ``evidence`` is the normal path: one candidate
#: beat every differently-directed rival by the caller's declared margin.
#: ``arbitrary-canonical`` is the tie: the scores did not separate the
#: candidates, so the axis was picked by a reproducible rule over their
#: directions and is a *convention*, not a measurement.  The program carries the
#: token so a reader can tell the two apart without re-deriving anything.
FRAME_CHOICES = {"evidence", "arbitrary-canonical"}

#: The measurement regimes U2 can settle on, and what a caller may declare.
#: Carried across this seam because the regime changes what the numbers on the
#: far side of it *mean* -- the noise floors, the normal-direction merge width,
#: which estimator is estimating noise at all -- and a program that does not say
#: which regime produced it is byte-identical whether the mesh was measured or
#: the caller overrode the measurement.
MEASUREMENT_REGIMES = {"tessellation", "scan"}
DECLARABLE_REGIMES = MEASUREMENT_REGIMES | {"auto"}


class ReconstructionRefused(ValueError):
    """A named, closed-vocabulary refusal carrying its alternative."""

    def __init__(
        self,
        reason: str,
        message: str,
        detail: dict[str, Any] | None = None,
        alternative: str = "",
    ) -> None:
        super().__init__(f"{reason}: {message}")
        self.reason = reason
        self.message = message
        self.detail = dict(detail or {})
        self.alternative = alternative

    def to_dict(self) -> dict[str, Any]:
        return {
            "refusal": self.reason,
            "message": self.message,
            "alternative": self.alternative,
            "detail": dict(self.detail),
        }


def refusal(
    reason: str,
    message: str,
    detail: dict[str, Any] | None = None,
    *,
    vocabulary: set[str],
    alternatives: dict[str, str],
) -> ReconstructionRefused:
    """Build a refusal, refusing first to name one outside the closed set."""
    if reason not in vocabulary:
        raise ValueError(f"{reason!r} is not in the closed refusal vocabulary.")
    return ReconstructionRefused(reason, message, detail, alternatives.get(reason, ""))


def _refuse(reason: str, message: str, detail: dict[str, Any] | None = None) -> ReconstructionRefused:
    return refusal(
        reason,
        message,
        detail,
        vocabulary=DATUM_REFUSALS,
        alternatives=REFUSAL_ALTERNATIVES,
    )


# --------------------------------------------------------------------------
# 1. reading the fit record
# --------------------------------------------------------------------------


def _number(raw: Any) -> float | None:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    value = float(raw)
    return value if math.isfinite(value) else None


def _vector(raw: Any) -> Vec3 | None:
    if not isinstance(raw, (list, tuple)) or len(raw) != 3:
        return None
    values = [_number(item) for item in raw]
    if any(value is None for value in values):
        return None
    return (values[0], values[1], values[2])  # type: ignore[index]


def _parameter_value(raw: Any) -> Any:
    """JSON gives lists where the fitter produced tuples; restore the tuples.

    Only a three-element list of finite numbers converts, because that is the
    only shape any fit parameter uses for a point or a direction.
    """
    vector = _vector(raw)
    return vector if vector is not None else raw


@dataclass(frozen=True, slots=True)
class RegionFit:
    """One segmented region, its fit, and the evidence this stage needs from it."""

    region_hash: str
    area: float
    bounding_box: tuple[Vec3, Vec3]
    fit: PrimitiveFit | None
    axial_span: float | None
    uncertainty: dict[str, float] | None
    # Which side of this surface the solid is on: ``"inside"`` for a bore,
    # ``"outside"`` for a boss, ``None`` when the mesh's own winding does not
    # license the claim.  This is the bore-versus-boss discriminator, and it is
    # carried rather than re-derived because only U2 has the triangles.
    material_side: str | None = None
    # Why ``material_side`` is ``None``, in U2's own words.  A gate a caller can
    # print beats a caller inventing one, and an unreconstructed region that
    # names "the mesh is not closed" is actionable where "no hole here" is not.
    orientation_gate: str | None = None
    # U2's fillet proposal for this region: ``{"radius", "between"}`` when an
    # accepted torus is adjacent to exactly two non-torus primaries, else None.
    fillet: dict[str, Any] | None = None
    # Whether U2 measured this surface as a *round* -- an arc short enough to be
    # an edge blend against the caller's declared ceiling -- as opposed to a wall
    # that closes on itself.  ``fillet`` is the accepted proposal; this is the
    # shape, and it stays true for a round whose chain was refused.  The planner
    # needs the distinction because a round's axis runs along an edge, which may
    # lie along the sweep direction or across it, while a wall's axis is the
    # sweep direction.
    blend_shaped: bool = False
    # The kinematic router's raw moment block over this region's own facets, as
    # ``mesh_fitting.region_motion_moments`` builds it.  ``None`` on a record
    # written before this field existed, or on a region whose facets carried no
    # readable normal -- absent, and never a zero block, because a zero block
    # would sum into a group's evidence as if the region had been measured.
    motion_moments: dict[str, Any] | None = None
    # This region's own triangles, in the *dump's* index space -- the same space
    # a host-side section addresses. Carried because the 2.5D decomposition asks
    # "which region does this section segment's wall belong to?", and only the
    # triangle indices can answer it; the fit record has always written them and
    # this stage simply stopped discarding them. Empty on a record that predates
    # them, which is not the same as a region with no triangles.
    triangle_indices: tuple[int, ...] = ()

    @property
    def accepted(self) -> bool:
        return self.fit is not None and self.fit.accepted

    def anchor(self) -> Vec3 | None:
        """The fit's representative point, or ``None`` when it has none."""
        if self.fit is None:
            return None
        for label in ("axis_point", "point_on_plane", "center", "apex"):
            value = self.fit.parameters.get(label)
            if isinstance(value, tuple) and len(value) == 3:
                return value
        return None

    def direction(self) -> Vec3 | None:
        if self.fit is None:
            return None
        if self.fit.kind == "plane":
            value = self.fit.parameters.get("normal")
        elif self.fit.kind in ("cylinder", "cone"):
            value = self.fit.parameters.get("axis_direction")
        else:
            return None
        return value if isinstance(value, tuple) and len(value) == 3 else None

    def sigma(self, key: str) -> float | None:
        if self.uncertainty is None:
            return None
        return self.uncertainty.get(key)

    def with_fit(self, fit: PrimitiveFit) -> "RegionFit":
        return RegionFit(
            region_hash=self.region_hash,
            area=self.area,
            bounding_box=self.bounding_box,
            fit=fit,
            axial_span=self.axial_span,
            uncertainty=self.uncertainty,
            material_side=self.material_side,
            orientation_gate=self.orientation_gate,
            fillet=self.fillet,
            blend_shaped=self.blend_shaped,
            motion_moments=self.motion_moments,
            triangle_indices=self.triangle_indices,
        )


@dataclass(frozen=True, slots=True)
class FitRecord:
    dump_sha256: str
    units: str
    total_area: float
    regions: tuple[RegionFit, ...]
    #: U2's measurement regime: ``{"regime", "declared", "overridden"}``, or
    #: ``None`` on a record written before the regime was detected.  The
    #: evidence stays in the fit record; what crosses this seam is the verdict,
    #: whether the caller overrode it, and what they declared -- enough for a
    #: reader of the *program* to tell a measured regime from an asserted one.
    regime: dict[str, Any] | None = None

    def accepted(self) -> tuple[RegionFit, ...]:
        return tuple(region for region in self.regions if region.accepted)


def _malformed(path: str, expected: str) -> ReconstructionRefused:
    return _refuse(
        "fit-record-malformed",
        f"{path} must be {expected}.",
        {"path": path, "expected": expected},
    )


def _parse_fit(raw: Any, path: str) -> PrimitiveFit:
    if not isinstance(raw, dict):
        raise _malformed(path, "an object")
    kind = raw.get("kind")
    if kind not in PRIMITIVE_KINDS:
        raise _malformed(f"{path}.kind", f"one of {', '.join(sorted(PRIMITIVE_KINDS))}")
    accepted = raw.get("accepted")
    if not isinstance(accepted, bool):
        raise _malformed(f"{path}.accepted", "a boolean")
    numbers = {}
    for name in ("rms_residual", "relative_residual", "extent"):
        raw_value = raw.get(name)
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            raise _malformed(f"{path}.{name}", "a number")
        value = float(raw_value)
        if accepted and not math.isfinite(value):
            # A rejected fit carries infinite residuals by construction; an
            # accepted one carrying them would be a fit that passed its gates
            # without a measurement, which is not a thing to read past.
            raise _malformed(f"{path}.{name}", "finite on an accepted fit")
        numbers[name] = value
    parameters = raw.get("parameters")
    if not isinstance(parameters, dict):
        raise _malformed(f"{path}.parameters", "an object")
    rejection = raw.get("rejection")
    if rejection is not None and not isinstance(rejection, str):
        raise _malformed(f"{path}.rejection", "a string when present")
    return PrimitiveFit(
        kind=kind,
        accepted=accepted,
        rms_residual=numbers["rms_residual"],
        relative_residual=numbers["relative_residual"],
        extent=numbers["extent"],
        parameters={key: _parameter_value(value) for key, value in parameters.items()},
        rejection=rejection,
    )


def _parse_uncertainty(raw: Any, path: str) -> dict[str, float] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _malformed(path, "an object of parameter name to standard deviation, or absent")
    out: dict[str, float] = {}
    for key, value in raw.items():
        number = _number(value)
        if number is None or number < 0.0:
            raise _malformed(f"{path}.{key}", "a non-negative finite number")
        out[str(key)] = number
    return out


MATERIAL_SIDES = {"inside", "outside"}

_NO_ORIENTATION = (
    "the fit record carries no orientation block for this region, so nothing in it says which "
    "side of this surface the material is on"
)


def _parse_orientation(raw: Any, path: str) -> tuple[str | None, str | None]:
    """U2's material-side evidence, or the named reason there is none.

    Absent is not malformed: the orientation block is a later addition to the fit
    record and an older record simply does not carry one.  Absent yields ``None``
    with a gate naming the absence, which fails closed — a region whose side is
    unknown can never be classified a hole.  *Present and out of vocabulary* is a
    different thing and refuses, because an unrecognised value read past would be
    an answer nobody gave.
    """
    if raw is None:
        return None, _NO_ORIENTATION
    if not isinstance(raw, dict):
        raise _malformed(path, "an object when present")
    side = raw.get("material_side")
    if side is None:
        reason = raw.get("unavailable_reason")
        if reason is not None and not isinstance(reason, str):
            raise _malformed(f"{path}.unavailable_reason", "a string when present")
        return None, reason or _NO_ORIENTATION
    if side not in MATERIAL_SIDES:
        raise _malformed(
            f"{path}.material_side", f"one of {', '.join(sorted(MATERIAL_SIDES))}, or null"
        )
    return str(side), None


def _parse_triangle_indices(raw: Any, path: str) -> tuple[int, ...]:
    """The region's dump triangle indices, or empty when the record predates them.

    Absent is allowed and means "this record does not say"; present and not a
    list of non-negative integers is malformed, because a region that claims
    triangles has to name ones a dump could hold.
    """
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise _malformed(path, "an array of dump triangle indices")
    out = []
    for value in raw:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise _malformed(path, "an array of non-negative dump triangle indices")
        out.append(value)
    return tuple(out)


def _parse_fillet(raw_region: Mapping[str, Any], path: str) -> dict[str, Any] | None:
    """U2's fillet proposal, kept only when it arrives complete.

    ``fillet_candidate`` is the flag and ``fillet`` is the evidence.  A flag with
    no evidence refuses rather than reading as a fillet of unknown radius between
    unknown neighbours, which is precisely the guess this stage exists not to
    make.
    """
    flag = raw_region.get("fillet_candidate")
    if flag is None or flag is False:
        return None
    if flag is not True:
        raise _malformed(f"{path}.fillet_candidate", "a boolean when present")
    body = raw_region.get("fillet")
    if not isinstance(body, dict):
        raise _malformed(f"{path}.fillet", "an object whenever fillet_candidate is true")
    radius = _number(body.get("radius"))
    if radius is None or radius <= 0.0:
        raise _malformed(f"{path}.fillet.radius", "a positive number")
    between = body.get("between")
    if (
        not isinstance(between, list)
        or len(between) != 2
        or not all(isinstance(item, str) and _HEX64_RE.match(item) for item in between)
    ):
        raise _malformed(
            f"{path}.fillet.between",
            "exactly two region hashes; a blend that touches one region, or three, is not the "
            "two-neighbour adjacency a constant-radius fillet edge is",
        )
    # Which edge this fragment lies on, as U2's blend chaining named it: a chain
    # is a run of adjacent fragments that agree in radius and lie between the
    # same two primaries, which is exactly one rounded edge. Absent is not
    # malformed -- a record written before chaining existed carries none -- and
    # the planner refuses rather than pooling fragments whose edge it cannot tell
    # apart. Present and not a string is malformed: an edge identity that is not
    # an identity would silently pool two edges into one fillet.
    chain_id = body.get("chain_id")
    if chain_id is not None and not isinstance(chain_id, str):
        raise _malformed(f"{path}.fillet.chain_id", "a string when present")
    return {
        "radius": radius,
        "between": sorted(str(item) for item in between),
        "chain_id": chain_id,
    }


def _parse_motion_moments(
    raw: Any, path: str, triangle_count: Any, region_area: float, box: tuple[Vec3, Vec3]
) -> dict[str, Any] | None:
    """U2's kinematic moment block, kept only when it describes *this* region.

    Absent is not malformed — a record written before this field existed simply
    does not carry one, and a region whose facets carried no readable normal
    honestly has none.

    Present, the block is bound to the region it rides on.  Shape validation
    alone let fabricated blocks through — a matrix scaled by 1e6, a zero block,
    a centroid a kilometre away, another region's block copied over — and each
    one silently changed which archetypes the planner emitted, because a block
    is *summed* into a group's evidence and nothing downstream re-derives it.
    Three checks, all against numbers the record already carries:

    * ``facet_count`` equals the region's ``triangle_count`` and ``area`` its
      ``area``: U2 writes both from the same triangles in the same loop, so a
      block from anywhere else disagrees with one or the other;
    * the trace of the matrix's normal block is that same area.  ``M`` is
      ``sum(area_i * b b^T)`` with ``b = [x x n, n]`` and ``n`` a *unit* normal,
      so those three diagonal entries sum to ``sum(area_i)`` identically.  That
      is what ties the 21 numbers to the area rather than only the header;
    * the mean facet centroid lies inside the region's own bounding box, which
      it must, being an average of points that are all inside it.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _malformed(path, "an object when present")
    unknown = sorted(set(raw) - MOTION_MOMENT_FIELDS)
    missing = sorted(MOTION_MOMENT_FIELDS - set(raw))
    if unknown or missing:
        raise _malformed(path, f"exactly {sorted(MOTION_MOMENT_FIELDS)} (missing {missing}, unknown {unknown})")
    matrix = raw.get("matrix")
    if not isinstance(matrix, (list, tuple)) or len(matrix) != 21:
        raise _malformed(
            f"{path}.matrix",
            "21 numbers: the row-major upper triangle of the symmetric 6x6 moment block",
        )
    values = [_number(item) for item in matrix]
    if any(item is None for item in values):
        raise _malformed(f"{path}.matrix", "finite numbers")
    count = raw.get("facet_count")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise _malformed(f"{path}.facet_count", "a positive integer")
    area = _number(raw.get("area"))
    if area is None or area <= 0.0:
        raise _malformed(f"{path}.area", "a positive number")
    centroid = _vector(raw.get("centroid_sum"))
    if centroid is None:
        raise _malformed(f"{path}.centroid_sum", "three finite numbers")
    if isinstance(triangle_count, bool) or not isinstance(triangle_count, int):
        raise _malformed(
            f"{path}: the region carrying a moment block",
            "a triangle_count the block can be bound to; a block whose region does not say how "
            "many triangles it has cannot be checked against anything",
        )
    # (3,3), (4,4) and (5,5) of the row-major upper triangle: the normal block's
    # diagonal.
    normal_trace = float(values[15] + values[18] + values[20])  # type: ignore[operator]
    lo, hi = box
    mean = tuple(component / count for component in centroid)
    slack = 1e-06 * max(1.0, max(hi[i] - lo[i] for i in range(3)))
    disagreements = []
    if int(count) != int(triangle_count):
        disagreements.append(f"it counts {count} facets where the region has {triangle_count}")
    if not math.isclose(float(area), float(region_area), rel_tol=1e-09, abs_tol=0.0):
        disagreements.append(f"its area is {area:.6g} where the region's is {region_area:.6g}")
    if not math.isclose(normal_trace, float(area), rel_tol=1e-06, abs_tol=0.0):
        disagreements.append(
            f"the trace of its normal block is {normal_trace:.6g}, which for unit normals is the "
            f"area it also states as {area:.6g}"
        )
    if any(not (lo[i] - slack <= mean[i] <= hi[i] + slack) for i in range(3)):
        disagreements.append(
            f"its mean facet centroid {tuple(round(c, 6) for c in mean)} is outside the region's "
            f"own bounding box"
        )
    if disagreements:
        raise _refuse(
            "fit-record-moments-unbound",
            f"{path} does not describe this region's facets: {'; and '.join(disagreements)}. The "
            "block is summed into a group's motion evidence as-is, so one that does not describe "
            "this region's own facets is a measurement nobody made.",
            {
                "path": path,
                "block_facet_count": int(count),
                "region_triangle_count": triangle_count,
                "block_area": float(area),
                "region_area": float(region_area),
                "normal_block_trace": normal_trace,
                "mean_facet_centroid": list(mean),
                "region_bounding_box": [list(lo), list(hi)],
            },
        )
    return {
        "matrix": [float(v) for v in values],  # type: ignore[arg-type]
        "facet_count": int(count),
        "area": area,
        "centroid_sum": list(centroid),
    }


def parse_fit_record(raw: Any) -> FitRecord:
    """Read U2's fit record, refusing rather than defaulting a missing field.

    Unknown *additional* keys are ignored on purpose: this is an upstream record
    that will grow, and refusing it for carrying more than we read would couple
    two stages that should only share a contract.  The closed-vocabulary,
    reject-the-unknown discipline applies to the reconstruction program we
    *emit* (R16), which is the artifact whose executor must never best-effort.
    """
    if not isinstance(raw, dict):
        raise _malformed("fit_record", "an object")
    dump_sha256 = raw.get("dump_sha256")
    if not isinstance(dump_sha256, str) or not _HEX64_RE.match(dump_sha256):
        raise _malformed("fit_record.dump_sha256", "a lowercase 64-character hex SHA-256")
    units = raw.get("units")
    if not isinstance(units, str) or not units.strip():
        # Not defaulted to millimetres: the fitting stage knows the dump's unit
        # and a guess here would silently rescale an entire model.
        raise _malformed("fit_record.units", "the dump's declared length unit, as a string")
    total_area = _number(raw.get("total_area"))
    if total_area is None or total_area <= 0.0:
        raise _malformed("fit_record.total_area", "a positive number")
    raw_regions = raw.get("regions")
    if not isinstance(raw_regions, list) or not raw_regions:
        raise _malformed("fit_record.regions", "a non-empty array")

    regions: list[RegionFit] = []
    seen: set[str] = set()
    for index, raw_region in enumerate(raw_regions):
        path = f"fit_record.regions[{index}]"
        if not isinstance(raw_region, dict):
            raise _malformed(path, "an object")
        region_hash = raw_region.get("region_hash")
        if not isinstance(region_hash, str) or not _HEX64_RE.match(region_hash):
            raise _malformed(f"{path}.region_hash", "a lowercase 64-character hex digest")
        if region_hash in seen:
            raise _malformed(f"{path}.region_hash", "unique across the record")
        seen.add(region_hash)
        area = _number(raw_region.get("area"))
        if area is None or area <= 0.0:
            raise _malformed(f"{path}.area", "a positive number")
        box = raw_region.get("bounding_box")
        if not isinstance(box, (list, tuple)) or len(box) != 2:
            raise _malformed(f"{path}.bounding_box", "a two-element [min, max] array")
        lo, hi = _vector(box[0]), _vector(box[1])
        if lo is None or hi is None or any(h < l for l, h in zip(lo, hi)):
            raise _malformed(f"{path}.bounding_box", "two finite points with min <= max")
        raw_fit = raw_region.get("fit")
        fit = None if raw_fit is None else _parse_fit(raw_fit, f"{path}.fit")
        support = raw_fit.get("support") if isinstance(raw_fit, dict) else None
        axial_span = _number(support.get("axial_span")) if isinstance(support, dict) else None
        if axial_span is not None and axial_span <= 0.0:
            raise _malformed(f"{path}.fit.support.axial_span", "a positive number when present")
        uncertainty = _parse_uncertainty(
            raw_fit.get("uncertainty") if isinstance(raw_fit, dict) else None,
            f"{path}.fit.uncertainty",
        )
        material_side, orientation_gate = _parse_orientation(
            raw_region.get("orientation"), f"{path}.orientation"
        )
        regions.append(
            RegionFit(
                region_hash=region_hash,
                area=area,
                bounding_box=(lo, hi),
                fit=fit,
                axial_span=axial_span,
                uncertainty=uncertainty,
                material_side=material_side,
                orientation_gate=orientation_gate,
                fillet=_parse_fillet(raw_region, f"{path}"),
                # U2 walked this surface as a blend: its measured arc was short
                # enough to be an edge round rather than a wall that closes on
                # itself. True even when the chain was then refused, because the
                # *shape* is what this flag reports and the refusal is about the
                # chain's neighbours or its radius spread.
                blend_shaped=isinstance(raw_region.get("fillet_chain"), dict),
                motion_moments=_parse_motion_moments(
                    raw_region.get("motion_moments"),
                    f"{path}.motion_moments",
                    raw_region.get("triangle_count"),
                    area,
                    (lo, hi),
                ),
                triangle_indices=_parse_triangle_indices(
                    raw_region.get("triangle_indices"), f"{path}.triangle_indices"
                ),
            )
        )
    return FitRecord(
        dump_sha256=dump_sha256,
        units=units.strip(),
        total_area=total_area,
        regions=tuple(regions),
        regime=_parse_regime(raw.get("regime")),
    )


def _parse_regime(raw: Any) -> dict[str, Any] | None:
    """U2's regime verdict, or ``None`` on a record written before there was one.

    Only the three fields a reader of the program needs are carried: which
    regime the run was in, what the caller declared, and whether that declaration
    overrode what the mesh said.  The evidence behind the detection stays in the
    fit record, which is where a reader can already find it by dump hash.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _malformed("fit_record.regime", "an object when present")
    regime, declared = raw.get("regime"), raw.get("declared")
    overridden = raw.get("overridden")
    if not _in_closed_set(regime, MEASUREMENT_REGIMES):
        raise _malformed("fit_record.regime.regime", f"one of {sorted(MEASUREMENT_REGIMES)}")
    if not _in_closed_set(declared, DECLARABLE_REGIMES):
        raise _malformed("fit_record.regime.declared", f"one of {sorted(DECLARABLE_REGIMES)}")
    if not isinstance(overridden, bool):
        raise _malformed("fit_record.regime.overridden", "a boolean")
    return {"regime": regime, "declared": declared, "overridden": overridden}


def require_uncertainty(regions: Iterable[RegionFit]) -> None:
    """Refuse unless every accepted fit carries the sigmas its kind needs.

    Called before any uncertainty-based judgement.  Without this, a fit with no
    uncertainty would read as sigma zero, every deviation would exceed it, and
    "we could not judge this" would come out as "this relationship is absent" —
    which is a lie the caller has no way to see.
    """
    for region in regions:
        if not region.accepted or region.fit is None:
            continue
        expected = FIT_UNCERTAINTY_KEYS[region.fit.kind]
        missing = [key for key in expected if region.sigma(key) is None]
        if missing:
            raise _refuse(
                "fit-record-missing-uncertainty",
                f"region {region.region_hash[:12]} ({region.fit.kind}) is missing uncertainty for "
                f"{', '.join(missing)}; an uncertainty-based tolerance cannot be computed from it.",
                {"region_hash": region.region_hash, "kind": region.fit.kind, "missing": missing},
            )


# --------------------------------------------------------------------------
# 2. the datum frame
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AxisCandidate:
    """One scored candidate for an axis, with everything the tie-break reads."""

    region_hash: str
    kind: str
    score: float
    area: float
    direction: Vec3
    anchor: Vec3
    basis: str
    #: The measured standard deviation of ``direction``, in degrees, read from
    #: the fit record and never estimated here.  ``None`` when the record
    #: carries none for this candidate's kind, which makes the candidate
    #: ineligible for the canonical tie-break: a direction with no stated
    #: uncertainty cannot be shown to survive a re-tessellation.
    direction_sigma_deg: float | None = None
    #: How ``direction_sigma_deg`` was arrived at, so a reader can tell a number
    #: the record measured from one this module combined.  Closed set:
    #: ``"measured"`` -- read from the fit record for this candidate's own
    #: direction; ``"propagated"`` -- combined first-order from the record's
    #: measured sigmas because this direction is derived from more than one fit.
    direction_sigma_basis: str = "measured"
    #: A *deterministic* angular spread this direction can jump by, in degrees,
    #: kept apart from the sigma because it is not a measurement error: it is
    #: the whole distance the direction moves if a different member of a merged
    #: parallel group becomes its representative. A confidence multiple applies
    #: to a standard deviation and not to a jump, so this is added after the
    #: multiplication rather than before it.
    direction_spread_deg: float = 0.0

    def sort_key(self) -> tuple[Any, ...]:
        # Total order: score, then supporting area, then the canonicalised
        # direction, then the anchor, then the region hash. The last element
        # makes the order total even for two numerically identical candidates,
        # so nothing here can depend on dict or list ordering.
        return (-self.score, -self.area, self.direction, self.anchor, self.region_hash)

    def to_dict(self) -> dict[str, Any]:
        return {
            "region_hash": self.region_hash,
            "kind": self.kind,
            "score": self.score,
            "area": self.area,
            "direction": list(self.direction),
            "anchor": list(self.anchor),
            "basis": self.basis,
            "direction_sigma_deg": self.direction_sigma_deg,
            "direction_sigma_basis": self.direction_sigma_basis,
            "direction_spread_deg": self.direction_spread_deg,
        }


@dataclass(frozen=True, slots=True)
class DatumFrame:
    origin: Vec3
    x_axis: Vec3
    y_axis: Vec3
    z_axis: Vec3
    evidence: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": list(self.origin),
            "x_axis": list(self.x_axis),
            "y_axis": list(self.y_axis),
            "z_axis": list(self.z_axis),
            "evidence": dict(self.evidence),
        }


def _relative_margin(winner: float, runner_up: float) -> float:
    if winner <= 0.0:
        return 0.0
    return (winner - runner_up) / winner


def _first_rival(
    candidates: Sequence[AxisCandidate], winner: AxisCandidate, angle_tolerance_deg: float
) -> AxisCandidate | None:
    """The best candidate that would give a *different* axis.

    A second cylinder parallel to the first is not a rival for the axis
    direction — it agrees with it.  Only a candidate pointing somewhere else can
    make the choice ambiguous, so only those are compared for margin.
    """
    for candidate in candidates:
        if candidate is winner:
            continue
        if _angle_deg(candidate.direction, winner.direction) > angle_tolerance_deg:
            return candidate
    return None


def _canonical_cell(
    direction: Vec3,
    sigma_deg: float | None,
    grid_deg: float,
    sigma_multiple: float | None,
    spread_deg: float = 0.0,
) -> tuple[int, int, int] | None:
    """``direction`` as integer cells on a ``grid_deg`` angular grid, or ``None``.

    ``None`` means *this direction's cell is not reproducible*: the fit's own
    measured uncertainty reaches a cell boundary, so a re-tessellation could
    move it into the neighbouring cell and change the answer.  That is the case
    the ambiguity refusal still exists for.

    The grid is the caller's declared ``angle_tolerance_deg`` -- already this
    module's width for "these two directions are the same direction", and
    already declared with the rationale that it is wider than any fit's angular
    sigma.  Quantising the *components* rather than two spherical angles keeps
    the resolution the same in all three coordinates and leaves no pole to
    special-case; the cell width is the chord a ``grid_deg`` arc subtends, and a
    rotation by sigma moves any component of a unit vector by at most sin(sigma).
    Cells are centred on zero, so an axis-aligned direction sits in the middle
    of its cell rather than exactly on a boundary.

    The sign of an unoriented direction is fixed by ``_canonical_direction``,
    which flips on the sign of the largest-magnitude component.  That choice is
    itself only reproducible when the largest component is unambiguously the
    largest among those of a *different* sign -- two components of opposite sign
    and equal magnitude flip the whole vector under jitter -- so it is checked
    here on the same measured sigma.
    """
    if sigma_multiple is None:
        # No declared confidence multiple, which is what a `declared-absolute`
        # tolerance basis means: the caller has said their numbers are not
        # sigmas. A sigma-based certification has nothing to certify with, so
        # the tie is refused rather than settled on a multiple nobody declared.
        return None
    if sigma_deg is None or not isinstance(sigma_deg, (int, float)):
        return None
    if isinstance(sigma_deg, bool) or not math.isfinite(sigma_deg) or sigma_deg < 0.0:
        return None
    # `sigma_deg` is one standard deviation, read from the record -- not a hard
    # bound. A cell whose boundary is 1.1 sigma away is one an ordinary
    # re-tessellation crosses often enough to matter, and the record calls this
    # choice reproducible. So the distance a cell has to clear is the caller's
    # own declared `sigma_multiple`, the same confidence multiple the
    # relationship licences already turn a sigma into a tolerance with.
    # The multiple applies to the sigma and to nothing else. A deterministic
    # spread is already the whole jump; multiplying it by a confidence factor
    # would demand clearance for an excursion nothing can make.
    slack = math.sin(
        math.radians(min(float(sigma_deg) * sigma_multiple + float(spread_deg), 90.0))
    )
    half_cell = math.sin(math.radians(grid_deg) / 2.0)
    if slack >= half_cell:
        # The grid is not coarse compared with the uncertainty, which is the
        # whole premise: a tie between directions known to +-sigma needs cells
        # much wider than sigma or the quantization decides nothing.
        return None
    dominant = max(range(3), key=lambda i: (abs(direction[i]), -i))
    for other in range(3):
        if other == dominant:
            continue
        if (direction[other] < 0.0) == (direction[dominant] < 0.0):
            continue
        if abs(direction[other]) + 2.0 * slack > abs(direction[dominant]):
            return None
    cell: list[int] = []
    for value in direction:
        index = math.floor(value / (2.0 * half_cell) + 0.5)
        if abs(value - 2.0 * half_cell * index) + slack > half_cell:
            return None
        cell.append(index)
    return (cell[0], cell[1], cell[2])


def _tied(
    candidates: Sequence[AxisCandidate],
    winner: AxisCandidate,
    frame_margin: float,
    angle_tolerance_deg: float,
) -> list[AxisCandidate]:
    """The winner and every differently-directed candidate inside the margin."""
    return [winner] + [
        candidate
        for candidate in candidates
        if candidate is not winner
        and _angle_deg(candidate.direction, winner.direction) > angle_tolerance_deg
        and _relative_margin(winner.score, candidate.score) < frame_margin
    ]


def _decide_axis(
    candidates: Sequence[AxisCandidate],
    winner: AxisCandidate,
    rival: AxisCandidate | None,
    margin: float | None,
    *,
    axis: str,
    frame_margin: float,
    angle_tolerance_deg: float,
    sigma_multiple: float | None,
) -> tuple[AxisCandidate, dict[str, Any]]:
    """Settle one axis: by evidence when the scores separate, else canonically.

    A reconstruction does not need the designer's preferred frame; it needs a
    *deterministic* one.  Every archetype in the program is expressed relative
    to the datum, so any reproducible choice rebuilds the same model, and the
    ambiguity refusal was never protecting correctness -- it was protecting
    reproducibility against a re-tessellation flipping two near-equal scores.
    So when the scores tie, the axis is settled by a rule that reads the
    *directions*, which a re-tessellation does not move, instead of the scores,
    which it does: quantize each tied candidate's canonical direction onto the
    declared angular grid and take the lexicographically smallest cell.

    The refusal survives for the case it still protects.  A candidate whose
    measured direction uncertainty reaches the grid could quantize either way,
    and there the honest answer is still ``frame-ambiguous`` with its declared
    margin and its name-the-axis recourse.  A candidate that carries no measured
    uncertainty at all is in the same position: nothing licenses the claim that
    its cell is stable.
    """
    record: dict[str, Any] = {
        "basis": "evidence",
        "axis": axis,
        "winner": winner.to_dict(),
        "runner_up": None if rival is None else rival.to_dict(),
        "margin": margin,
        "frame_margin": frame_margin,
    }
    def membership_refusal(candidate: AxisCandidate, tied_side: bool):
        """Is this candidate's same-axis classification reproducible?

        Whether a candidate is *in* the tie set is itself an angular
        measurement against `angle_tolerance_deg`, and it decides the outcome.
        A candidate 1.99 deg from the winner is read as a re-measurement of the
        same axis and excluded, settling the axis on evidence; the same
        candidate at 2.01 deg joins the set and can carry a lexicographically
        smaller cell, selecting a different axis -- on a difference smaller
        than the sigmas both directions state, and in either direction. The
        cell test asks whether a tied candidate's *direction* is stable; this
        asks whether its membership is, which is the same question one step
        earlier.

        ponytail: only a candidate whose separation is provably near the line
        refuses. One whose direction states no sigma is left to the cell test,
        which refuses if it reaches the tie set -- upgrade to refusing here too
        if a record ever ships a scored candidate with no direction sigma.
        """
        if candidate is winner:
            return None
        if _relative_margin(winner.score, candidate.score) >= frame_margin:
            return None
        if (
            sigma_multiple is None
            or candidate.direction_sigma_deg is None
            or winner.direction_sigma_deg is None
        ):
            return None
        separation = _angle_deg(candidate.direction, winner.direction)
        if (separation > angle_tolerance_deg) != tied_side:
            return None
        bound = (
            sigma_multiple
            * math.hypot(candidate.direction_sigma_deg, winner.direction_sigma_deg)
            + candidate.direction_spread_deg
            + winner.direction_spread_deg
        )
        if abs(separation - angle_tolerance_deg) > bound:
            return None
        return _refuse(
            "frame-ambiguous",
            f"the {axis}-axis winner is within the declared margin {frame_margin:g} of candidate "
            f"{candidate.region_hash[:12]} in score, and the two are not reproducibly the same "
            f"axis or different ones: that candidate sits {separation:.4g} deg from the winner, "
            f"within {bound:.4g} deg of the {angle_tolerance_deg:g} deg line that decides whether "
            "it is this axis re-measured or a rival in the tie, so a re-tessellation can move it "
            "across and change the axis this rule selects.",
            {
                "axis": axis,
                "winner": winner.to_dict(),
                "runner_up": None if rival is None else rival.to_dict(),
                "margin": margin,
                "frame_margin": frame_margin,
                "quantization_grid_deg": angle_tolerance_deg,
                "unstable_membership": {
                    "candidate": candidate.to_dict(),
                    "separation_deg": separation,
                    "bound_deg": bound,
                    "side": "tied" if tied_side else "same-axis",
                },
            },
        )

    # The excluded side first, because it is reachable even when the scores
    # never tie: a candidate read as this axis re-measured never becomes a
    # rival, so nothing below would look at it.
    for candidate in candidates:
        refusal = membership_refusal(candidate, tied_side=False)
        if refusal is not None:
            raise refusal

    if margin is None or margin >= frame_margin:
        return winner, record

    # Inside the winner's own same-axis cluster the scores do not separate
    # either, and the highest of them was standing for the whole cluster. Two
    # cylinders 0.4 deg and 1.6 deg off the same axis have stable, *different*
    # cells; scoring 100 and 99.9 selects the first and 100 and 100.1 selects
    # the second, so the frame moves 1.2 deg on a number a re-tessellation
    # writes -- with nothing crossing the angular line or the margin, which is
    # what the guards above watch. The cluster's representative is therefore
    # chosen the way the tie between clusters is: smallest canonical cell.
    #
    # ponytail: only members whose own cell is stable can represent the
    # cluster. If every one of them is unstable the score order stands and the
    # cell test below refuses on it, which is the same answer by a longer road.
    # The score ranking's own winner, kept before the cluster rule can rebind
    # `winner`: `margin`, `highest_score_runner_up` and `margin_basis` below all
    # describe the *score* ranking, and `highest_score` naming the canonical
    # representative instead would make the record disagree with itself about
    # which candidate the margin was measured on.
    highest_scorer = winner
    cluster = [
        candidate
        for candidate in candidates
        if candidate is not winner
        and _angle_deg(candidate.direction, winner.direction) <= angle_tolerance_deg
        and _relative_margin(winner.score, candidate.score) < frame_margin
    ]
    if cluster:
        ranked: list[tuple[tuple[int, int, int], tuple[Any, ...], AxisCandidate]] = []
        for candidate in [winner] + cluster:
            cell = _canonical_cell(
                candidate.direction,
                candidate.direction_sigma_deg,
                angle_tolerance_deg,
                sigma_multiple,
                candidate.direction_spread_deg,
            )
            if cell is not None:
                ranked.append((cell, candidate.sort_key(), candidate))
        if ranked:
            ranked.sort()
            if ranked[0][2] is not winner:
                record["same_axis_representative"] = {
                    "replaced": winner.to_dict(),
                    "reason": (
                        "this candidate and the selected one are the same axis within "
                        f"{angle_tolerance_deg:g} deg and their scores do not separate, so the "
                        "higher score was standing for the cluster on a number a re-tessellation "
                        "moves. The cluster is represented by its smallest canonical cell, the "
                        "same rule that settles the tie between clusters."
                    ),
                }
                winner = ranked[0][2]

    tied = _tied(candidates, winner, frame_margin, angle_tolerance_deg)
    celled: list[tuple[tuple[int, int, int], tuple[Any, ...], AxisCandidate]] = []
    for candidate in tied:
        cell = _canonical_cell(
            candidate.direction,
            candidate.direction_sigma_deg,
            angle_tolerance_deg,
            sigma_multiple,
            candidate.direction_spread_deg,
        )
        if cell is None:
            raise _refuse(
                "frame-ambiguous",
                f"the {axis}-axis winner beats its nearest differently-directed rival by "
                f"{margin:.4g}, below the declared margin {frame_margin:g}, and the canonical "
                "tie-break cannot separate the tied candidates reproducibly: candidate "
                f"{candidate.region_hash[:12]} carries direction sigma "
                f"{candidate.direction_sigma_deg} deg, which reaches the "
                f"{angle_tolerance_deg:g} deg quantization grid.",
                {
                    "axis": axis,
                    "winner": winner.to_dict(),
                    "runner_up": None if rival is None else rival.to_dict(),
                    "margin": margin,
                    "frame_margin": frame_margin,
                    "quantization_grid_deg": angle_tolerance_deg,
                    "unstable_candidate": candidate.to_dict(),
                    "tied": [entry.to_dict() for entry in tied],
                },
            )
        celled.append((cell, candidate.sort_key(), candidate))
    celled.sort()
    if len({cell for cell, _key, _entry in celled}) != len(celled):
        # Two directions further apart than `angle_tolerance_deg` can still land
        # in one cell, because a cell spans that angle's chord in every
        # component rather than the angle itself.  `celled.sort()` would then
        # decide on `sort_key()`, whose first element is the score -- the number
        # a re-tessellation moves, and the reason this rule exists.  A cell that
        # does not separate the tied candidates is no better than an unstable
        # one, and gets the same answer.
        raise _refuse(
            "frame-ambiguous",
            f"the {axis}-axis winner beats its nearest differently-directed rival by "
            f"{margin:.4g}, below the declared margin {frame_margin:g}, and two tied "
            f"candidates quantize to the same {angle_tolerance_deg:g} deg cell, so the "
            "canonical tie-break does not separate them.",
            {
                "axis": axis,
                "winner": winner.to_dict(),
                "runner_up": None if rival is None else rival.to_dict(),
                "margin": margin,
                "frame_margin": frame_margin,
                "quantization_grid_deg": angle_tolerance_deg,
                "tied": [
                    dict(entry.to_dict(), canonical_cell=list(cell))
                    for cell, _sort, entry in celled
                ],
            },
        )
    # And the other side of the same line: a tied candidate can move below the
    # tolerance, leave the set, and hand the selection back to the score
    # winner. Checked after the cell tests, so a tie the quantization genuinely
    # cannot separate still reports as that.
    for candidate in tied:
        refusal = membership_refusal(candidate, tied_side=True)
        if refusal is not None:
            raise refusal
    chosen_cell, _key, chosen = celled[0]
    # `runner_up` so far is the highest scorer's rival, and the rule just
    # overrode the score ranking -- when it promoted that rival, the record
    # would name one candidate as both the winner and its own runner-up. Report
    # the runner-up against the candidate actually selected, and keep the score
    # ranking whole under `highest_score*`. `margin` stays the score-ranking
    # number, because it is the one the `frame_margin` gate above read to get
    # here; `margin_basis` says so rather than leaving it to be inferred.
    chosen_rival = _first_rival(candidates, chosen, angle_tolerance_deg)
    record.update(
        {
            "basis": "arbitrary-canonical",
            "winner": chosen.to_dict(),
            "runner_up": None if chosen_rival is None else chosen_rival.to_dict(),
            "margin_basis": (
                "score ranking: the highest scorer's lead over its nearest differently-directed "
                "rival, which is the number compared against frame_margin. The selection below "
                "was made on directions, not on this."
            ),
            "highest_score": highest_scorer.to_dict(),
            "highest_score_runner_up": None if rival is None else rival.to_dict(),
            "quantization_grid_deg": angle_tolerance_deg,
            "sigma_multiple": sigma_multiple,
            "quantization": (
                "each tied candidate's canonical direction quantized to integer cells of "
                f"{angle_tolerance_deg:g} deg (cells centred on zero, one cell width per component) "
                "and the lexicographically smallest cell taken; every tied candidate's stated "
                f"direction sigma times the declared sigma_multiple {sigma_multiple} is smaller than its "
                "distance to the nearest cell boundary, and no "
                "two of them share a cell, so the same candidate is chosen on any re-tessellation "
                "that leaves this tie set unchanged. Membership in the tie set is still a score "
                "comparison against the declared frame margin, so a re-tessellation that moves a "
                "rival's score across that margin can change the set and with it the answer."
            ),
            "canonical_cell": list(chosen_cell),
            "tied": [
                dict(entry.to_dict(), canonical_cell=list(cell)) for cell, _sort, entry in celled
            ],
            "note": (
                "the scores did not separate these candidates, so this axis is a convention rather "
                "than a measurement: it is reproducible, and it is not evidence that the designer "
                "would have chosen it."
            ),
        }
    )
    return chosen, record


def _merge_parallel(
    candidates: Sequence[AxisCandidate], angle_tolerance_deg: float
) -> list[AxisCandidate]:
    """Sum the areas of candidates that already agree on a direction.

    ``_first_rival`` states half of this rule already: a candidate parallel to
    the winner is not a rival, it *agrees*.  Agreement that only ever silenced a
    rival never counted for anything, so the ranking compared one face's area
    against one other face's area.  On a rectangular lid that is a coin toss --
    POD-A1-LID's two rival walls measured 95.40 mm2 and 94.80 mm2, a margin of
    0.0063 -- while the *stacks* they belong to measured 1008.4 mm2 facing one
    way against 189.6 mm2 facing the other.  The part is not ambiguous; the
    ranking was reading one face out of each stack.  Evidence that agrees adds.

    Only a score that *is* an amount of evidence may be summed, which is why
    this is applied to the area-scored candidate sets and to neither of the
    others: two coaxial cylinders do not make one with a longer axial span, and
    two bolt holes 100 mm off the axis do not make one 200 mm off it.

    The representative -- region hash, anchor, direction -- stays the group's
    largest single member, so the origin still lands on a face that exists.
    Greedy over the sorted list rather than the caller's, because greedy over an
    arbitrary order picks an arbitrary representative: the sort is what makes
    both the grouping and the representative total.
    """
    groups: list[list[Any]] = []
    for candidate in sorted(candidates, key=AxisCandidate.sort_key):
        for group in groups:
            if _angle_deg(candidate.direction, group[0][0].direction) <= angle_tolerance_deg:
                group[0].append(candidate)
                group[1] += candidate.area
                break
        else:
            groups.append([[candidate], candidate.area])
    merged: list[AxisCandidate] = []
    for members, total in groups:
        head = members[0]
        count = len(members)
        sigma = head.direction_sigma_deg
        basis = head.direction_sigma_basis
        if count > 1:
            # The representative is the largest single member, and *which*
            # member that is rests on areas a re-tessellation moves. Two members
            # each safely inside their own cell can put the merged direction on
            # either of two cells depending on which one won the area, so the
            # merged candidate's uncertainty has to cover the whole group's
            # spread, not just the representative's own. A member with no stated
            # sigma leaves the group with none, which is what makes it
            # ineligible for the canonical tie-break rather than quietly stable.
            # Carried *beside* the sigma, not folded into it. The
            # representative changing is a discrete jump of the whole spread,
            # not an independent random error that partly cancels, so the
            # clearance a cell needs is `sigma * multiple + spread` -- and the
            # confidence multiple belongs to the sigma alone. Folding it in
            # multiplied the jump too, which demanded clearance for an
            # excursion nothing can make.
            spread = max(_angle_deg(head.direction, member.direction) for member in members)
            sigmas = [member.direction_sigma_deg for member in members]
            sigma = None if any(s is None for s in sigmas) else max(sigmas)
            basis = "propagated"
        merged.append(
            replace(
                head,
                score=total,
                area=total,
                direction_sigma_deg=sigma,
                direction_sigma_basis=basis,
                direction_spread_deg=(spread if count > 1 else head.direction_spread_deg),
                basis=(
                    head.basis
                    if count == 1
                    else f"{head.basis}, summed over {count} parallel fits"
                ),
            )
        )
    return sorted(merged, key=AxisCandidate.sort_key)


def _primary_candidates(
    regions: Sequence[RegionFit], angle_tolerance_deg: float
) -> tuple[list[AxisCandidate], str]:
    """Cylinders ranked by radius x axial span; planes by area when none fits.

    Cones are deliberately not candidates: a cone's axis is well defined but its
    "size" along that axis has no single radius, so it cannot enter the same
    ranking without inventing one for it.
    """
    cylinders: list[AxisCandidate] = []
    for region in regions:
        fit = region.fit
        if fit is None or fit.kind != "cylinder":
            continue
        radius = fit.parameters.get("radius")
        direction, anchor = region.direction(), region.anchor()
        if not isinstance(radius, float) or direction is None or anchor is None:
            continue
        if region.axial_span is None:
            raise _refuse(
                "fit-record-missing-axial-span",
                f"region {region.region_hash[:12]} is an accepted cylinder with no "
                "fit.support.axial_span, so it cannot be ranked by radius x axial span.",
                {"region_hash": region.region_hash},
            )
        cylinders.append(
            AxisCandidate(
                region_hash=region.region_hash,
                kind="cylinder",
                score=radius * region.axial_span,
                area=region.area,
                direction=_canonical_direction(direction),
                anchor=anchor,
                basis="radius x axial span",
                direction_sigma_deg=region.sigma("axis_direction_deg"),
            )
        )
    if cylinders:
        return sorted(cylinders, key=AxisCandidate.sort_key), "cylinder"

    planes: list[AxisCandidate] = []
    for region in regions:
        fit = region.fit
        if fit is None or fit.kind != "plane":
            continue
        direction, anchor = region.direction(), region.anchor()
        if direction is None or anchor is None:
            continue
        planes.append(
            AxisCandidate(
                region_hash=region.region_hash,
                kind="plane",
                score=region.area,
                area=region.area,
                direction=_canonical_direction(direction),
                anchor=anchor,
                basis="supporting area",
                direction_sigma_deg=region.sigma("normal_deg"),
            )
        )
    return _merge_parallel(planes, angle_tolerance_deg), "plane"


def _origin_on_axis(
    regions: Sequence[RegionFit],
    z: Vec3,
    axis_anchor: Vec3,
    angle_tolerance_deg: float,
) -> tuple[Vec3, str, float | None]:
    """Where the primary axis meets the lowest plane perpendicular to it.

    Returns the origin, how it was found, and the positional sigma of the
    region that placed it -- ``None`` where no single region did. The origin is
    one end of every second-axis candidate's direction, so its own uncertainty
    turns that direction just as the far anchor's does, and a canonical tie over
    those directions cannot be called stable without it.
    """
    caps: list[tuple[Any, ...]] = []
    for region in regions:
        fit = region.fit
        if fit is None or fit.kind != "plane":
            continue
        normal, point = region.direction(), region.anchor()
        if normal is None or point is None:
            continue
        if _angle_deg(normal, z) > angle_tolerance_deg:
            continue
        caps.append((_dot(z, point), -region.area, normal, point, region.region_hash))
    if caps:
        station, _area, _normal, _point, region_hash = sorted(caps)[0]
        origin = _add(axis_anchor, _scale(z, station - _dot(z, axis_anchor)))
        # The sigma of the region that placed it. The caller combines this with
        # the primary axis anchor's own, which is what places the origin
        # *across* the axis -- and the across-axis term is the one that turns a
        # second-axis direction.
        cap = next(r for r in regions if r.region_hash == region_hash)
        return (
            origin,
            f"primary axis meets plane {region_hash[:12]} at station {station:.6g}",
            cap.sigma("offset"),
        )

    planes = sorted(
        (
            (-region.area, region.region_hash, region.anchor())
            for region in regions
            if region.fit is not None and region.fit.kind == "plane" and region.anchor() is not None
        )
    )
    if planes:
        _area, region_hash, point = planes[0]
        # `None`, deliberately. This point is a plane's *vertex centroid*, and
        # the only sigma the record carries for a plane is `offset`, which
        # bounds displacement along the normal and says nothing about where on
        # the plane the centroid sits. A re-tessellation moves that centroid
        # tangentially -- and can swap which of two near-equal-area planes is
        # picked at all -- by far more than `offset`. Returning `offset` here
        # would let the canonical tie-break certify a cell that the origin can
        # walk out of, so this fallback states no bound and the tie refuses.
        return (
            point,
            f"centroid of the largest plane {region_hash[:12]}; no plane is perpendicular to the "
            "primary axis",
            None,
        )

    anchors = sorted(
        (region.anchor(), region.region_hash) for region in regions if region.anchor() is not None
    )
    total = len(anchors)
    centroid = (
        sum(a[0][0] for a in anchors) / total,
        sum(a[0][1] for a in anchors) / total,
        sum(a[0][2] for a in anchors) / total,
    )
    # No single region placed this one, so no single region's sigma bounds it.
    # `None` here makes every second-axis candidate ineligible for the canonical
    # tie-break, which is the honest answer for an origin nothing measured.
    return (
        centroid,
        "centroid of every accepted fit's anchor point; the part has no fitted plane",
        None,
    )


def _secondary_candidates(
    regions: Sequence[RegionFit],
    z: Vec3,
    angle_tolerance_deg: float,
    z_sigma_deg: float | None,
    sigma_multiple: float | None,
) -> list[AxisCandidate]:
    """Planes containing the primary axis: their normal, orthogonalised, is X."""
    out: list[AxisCandidate] = []
    for region in regions:
        fit = region.fit
        if fit is None or fit.kind != "plane":
            continue
        normal, point = region.direction(), region.anchor()
        if normal is None or point is None:
            continue
        offset_from_parallel = abs(_angle_deg(normal, z) - 90.0)
        if offset_from_parallel > angle_tolerance_deg:
            continue
        x = _unit(_sub(normal, _scale(z, _dot(normal, z))))
        if x is None:
            continue
        # The orthogonalisation subtracts the primary axis, which is itself
        # measured, so the plane's own sigma is a *lower bound* on the
        # orthogonalised direction's -- and `_canonical_cell` reads whatever it
        # is given as the whole bound.  Feeding it the lower bound would certify
        # cells that the primary axis can move out of, so both measured sigmas
        # are combined here, first-order and in quadrature: a rotation of the
        # primary axis by delta tilts a normal perpendicular to it by delta.
        # Nothing is invented -- when the record states no sigma for either
        # input the combined bound is unavailable, and an unavailable bound is
        # what makes the candidate ineligible for the canonical tie-break.
        plane_sigma = region.sigma("normal_deg")
        combined = (
            None
            if plane_sigma is None or z_sigma_deg is None
            else math.hypot(plane_sigma, z_sigma_deg)
        )
        # Being *in* this candidate set is itself a measurement against
        # `angle_tolerance_deg`, and a plane 1.95 deg from perpendicular on
        # a 2 deg tolerance is one a permitted perturbation drops out of --
        # which changes what the canonical rule is choosing between, and so
        # the axis, while the record calls the cell stable. A candidate
        # whose own membership is not stable under its declared bound
        # carries no sigma, which is what makes it ineligible for the
        # tie-break rather than quietly certifiable.
        eligible = (
            combined is not None
            and sigma_multiple is not None
            and offset_from_parallel + combined * sigma_multiple <= angle_tolerance_deg
        )
        out.append(
            AxisCandidate(
                region_hash=region.region_hash,
                kind="plane",
                score=region.area,
                area=region.area,
                direction=_canonical_direction(x),
                anchor=point,
                basis="normal of a plane parallel to the primary axis, orthogonalised",
                direction_sigma_deg=combined if eligible else None,
                direction_sigma_basis="propagated",
            )
        )
    return _merge_parallel(out, angle_tolerance_deg)


#: Where each kind's fit record keeps the positional sigma of its own anchor.
#: A cone's anchor is its apex and a cylinder's is a point on its axis, and the
#: record names them accordingly (``FIT_UNCERTAINTY_KEYS``) -- reading one key
#: for both silently gives every cone no sigma at all, which reads as "carries
#: no measured uncertainty" and refuses a tie the record could have settled.
_ANCHOR_SIGMA_KEY = {"cylinder": "axis_point", "cone": "apex"}


def _combined_positional_sigma(anchor: float | None, origin: float | None) -> float | None:
    """The two measured numbers that place a second axis relative to the datum."""
    if anchor is None or origin is None:
        return None
    return math.hypot(anchor, origin)


def _secondary_from_second_axis(
    regions: Sequence[RegionFit],
    z: Vec3,
    origin: Vec3,
    primary_region_hash: str,
    offset_tolerance: float,
    z_sigma_deg: float | None,
    origin_sigma: float | None,
    sigma_multiple: float | None,
    primary_anchor: Vec3,
) -> list[AxisCandidate]:
    """A bolt pattern gives a natural X: the direction to the second axis."""
    out: list[AxisCandidate] = []
    for region in regions:
        fit = region.fit
        if fit is None or fit.kind not in _ANCHOR_SIGMA_KEY:
            continue
        if region.region_hash == primary_region_hash:
            continue
        anchor = region.anchor()
        if anchor is None:
            continue
        offset = _sub(anchor, origin)
        perpendicular = _sub(offset, _scale(z, _dot(offset, z)))
        radial = _length(perpendicular)
        if radial <= offset_tolerance:
            continue
        # Being far enough off the axis to *be* a candidate is a measurement
        # against `offset_tolerance`, like the plane case's parallelism. A
        # candidate whose clearance is smaller than its own positional bound is
        # one a re-tessellation drops out of the set -- and it can win an
        # `arbitrary-canonical` tie first, then vanish and change X on the next
        # fit. Its own bound has to keep it in.
        positional = _combined_positional_sigma(
            region.sigma(_ANCHOR_SIGMA_KEY[fit.kind]), origin_sigma
        )
        # `radial` is what is left after subtracting the primary axis, so a tilt
        # of that axis moves it too: over the lever the tilt pivots on, by
        # `axial * delta`. Bounding the clearance by the endpoints' positional
        # sigma alone therefore understates it, and a candidate sitting just
        # outside `offset_tolerance` on a long, weakly-measured primary axis
        # passes a test its own axis can fail -- which is the case this guard
        # exists to catch. Independent measurements, so in quadrature; the two
        # levers inside `axial` are added because one tilt swings both.
        axial = abs(_dot(_sub(anchor, primary_anchor), z)) + abs(
            _dot(_sub(origin, primary_anchor), z)
        )
        radial_sigma = (
            None
            if positional is None or z_sigma_deg is None
            else math.hypot(positional, axial * math.radians(z_sigma_deg))
        )
        stable_membership = (
            radial_sigma is not None
            and sigma_multiple is not None
            and radial - radial_sigma * sigma_multiple > offset_tolerance
        )
        x = _unit(perpendicular)
        if x is None:
            continue
        # This direction is not a fitted axis: it is the direction *to* one, so
        # three measured numbers move it and all three are propagated
        # first-order.
        #
        # The anchor's own positional sigma, spread over the lever arm -- and
        # read under the key this kind's record actually uses.
        anchor_sigma = region.sigma(_ANCHOR_SIGMA_KEY[fit.kind])
        # And the primary axis's angular sigma, because the projection that
        # produces this direction subtracts that axis. The tilt pivots about
        # the primary fit's *own* anchor, not about the datum origin: an origin
        # placed on an end cap while the fitted axis point sits mid-span means
        # a secondary anchor level with that cap has zero axial offset from the
        # origin and the whole anchor-to-cap distance from the pivot. Both
        # levers are measured from the pivot and added, because the tilt swings
        # the origin and the anchor the same way at once. (`axial` is computed
        # above, where the membership bound needs the same lever.)
        out.append(
            AxisCandidate(
                region_hash=region.region_hash,
                kind=fit.kind,
                score=radial,
                area=region.area,
                direction=_canonical_direction(x),
                anchor=anchor,
                basis="perpendicular offset from the origin to a second axis",
                direction_sigma_deg=(
                    None
                    if not stable_membership
                    or anchor_sigma is None
                    or z_sigma_deg is None
                    or origin_sigma is None
                    else math.hypot(
                        math.hypot(
                            math.degrees(math.atan2(anchor_sigma, radial)),
                            # The origin is this direction's other endpoint, and
                            # moving it across the axis turns the direction over
                            # the same lever arm as moving the far anchor does.
                            math.degrees(math.atan2(origin_sigma, radial)),
                        ),
                        # Two ways a tilt of the primary axis turns this
                        # direction, and an anchor level with the origin has
                        # only the second: the axial component it subtracts
                        # moves by `axial * delta` over the lever `radial`, and
                        # the projection plane itself tilts by `delta`
                        # regardless. `hypot(1, axial/radial)` carries both.
                        z_sigma_deg * math.hypot(1.0, axial / radial),
                    )
                ),
                direction_sigma_basis="propagated",
            )
        )
    return sorted(out, key=AxisCandidate.sort_key)


def derive_datum_frame(
    regions: Sequence[RegionFit],
    *,
    frame_margin: float,
    angle_tolerance_deg: float,
    offset_tolerance: float,
    sigma_multiple: float | None,
) -> DatumFrame:
    """Derive origin and axes from the accepted fits, or refuse.

    The order is total and stated, and every tie-break reads a measured number
    or a canonicalised vector — never dict iteration order, never a face-group
    temp id.  Determinism is a tested property here, not an aspiration.

    ``frame_margin`` is a *relative* margin: the winner must beat the best rival
    candidate by that fraction of its own score.  Relative rather than absolute
    because the scores are areas and radius-times-length products, whose scale
    is the part's, not ours.  Inside the margin the axis is not refused but
    settled canonically -- see ``_decide_axis`` -- and ``evidence.frame_choice``
    says which of the two happened.
    """
    for label, value in (
        ("frame_margin", frame_margin),
        ("angle_tolerance_deg", angle_tolerance_deg),
        ("offset_tolerance", offset_tolerance),
    ) + ((("sigma_multiple", sigma_multiple),) if sigma_multiple is not None else ()):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{label} must be a positive finite number declared by the caller.")

    accepted = [region for region in regions if region.accepted]
    if not accepted:
        raise _refuse(
            "frame-no-accepted-fits",
            "no region has an accepted fit, so there is nothing to derive a frame from.",
            {"region_count": len(list(regions))},
        )

    candidates, source = _primary_candidates(accepted, angle_tolerance_deg)
    if not candidates:
        raise _refuse(
            "frame-no-accepted-fits",
            "no accepted fit carries a direction, so no primary axis can be derived.",
            {"accepted_count": len(accepted)},
        )
    winner = candidates[0]
    rival = _first_rival(candidates, winner, angle_tolerance_deg)
    primary_margin = None if rival is None else _relative_margin(winner.score, rival.score)
    winner, primary_choice = _decide_axis(
        candidates,
        winner,
        rival,
        primary_margin,
        axis="primary",
        frame_margin=frame_margin,
        angle_tolerance_deg=angle_tolerance_deg,
        sigma_multiple=sigma_multiple,
    )
    z = winner.direction
    origin, origin_source, placing_sigma = _origin_on_axis(
        accepted, z, winner.anchor, angle_tolerance_deg
    )
    # A second-axis direction runs from the origin to another axis, so the
    # origin is one of its two endpoints and its own uncertainty turns that
    # direction exactly as the far endpoint's does. Two measured numbers place
    # the origin: the region that named it, and the primary axis's own anchor,
    # which is what fixes it *across* the axis. Either one missing leaves the
    # origin without a stated uncertainty -- and a direction with an endpoint
    # nothing measured is not a direction the canonical tie-break may certify.
    primary_region = next(
        (region for region in accepted if region.region_hash == winner.region_hash), None
    )
    # A plane's anchor is its *vertex centroid* and the only sigma a plane
    # record carries is `offset`, which bounds motion along the normal and says
    # nothing about where on the plane the centroid sits -- the same reason the
    # no-perpendicular-plane origin fallback states no bound. So a plane primary
    # states none either, and the canonical tie over directions measured from
    # that origin refuses rather than certifying a cell it can slide out of.
    primary_anchor_sigma = (
        None
        if primary_region is None
        or primary_region.fit is None
        or primary_region.fit.kind not in _ANCHOR_SIGMA_KEY
        else primary_region.sigma(_ANCHOR_SIGMA_KEY[primary_region.fit.kind])
    )
    origin_sigma = (
        None
        if placing_sigma is None or primary_anchor_sigma is None
        else math.hypot(placing_sigma, primary_anchor_sigma)
    )

    secondary = _secondary_candidates(
        accepted, z, angle_tolerance_deg, winner.direction_sigma_deg, sigma_multiple
    )
    secondary_basis = "plane parallel to the primary axis"
    if not secondary:
        secondary = _secondary_from_second_axis(
            accepted,
            z,
            origin,
            winner.region_hash,
            offset_tolerance,
            winner.direction_sigma_deg,
            origin_sigma,
            sigma_multiple,
            winner.anchor,
        )
        secondary_basis = "second axis off the primary axis"
    if not secondary:
        raise _refuse(
            "frame-x-underdetermined",
            "no plane parallel to the primary axis and no second axis offset from it, so rotation "
            "about the primary axis is not observable. The global X axis is not a substitute.",
            {"axis": "secondary", "primary": winner.to_dict()},
        )
    x_winner = secondary[0]
    x_rival = _first_rival(secondary, x_winner, angle_tolerance_deg)
    secondary_margin = None if x_rival is None else _relative_margin(x_winner.score, x_rival.score)
    x_winner, secondary_choice = _decide_axis(
        secondary,
        x_winner,
        x_rival,
        secondary_margin,
        axis="secondary",
        frame_margin=frame_margin,
        angle_tolerance_deg=angle_tolerance_deg,
        sigma_multiple=sigma_multiple,
    )

    x = _unit(_sub(x_winner.direction, _scale(z, _dot(x_winner.direction, z))))
    if x is None:  # pragma: no cover - the candidate builders already orthogonalised
        raise _refuse(
            "frame-x-underdetermined",
            "the secondary candidate collapsed onto the primary axis after orthogonalisation.",
            {"axis": "secondary", "winner": x_winner.to_dict()},
        )
    y = _cross(z, x)
    return DatumFrame(
        origin=origin,
        x_axis=x,
        y_axis=y,
        z_axis=z,
        evidence={
            # `frame_choice` is the worse of the two axes: a frame with one
            # arbitrary axis in it is an arbitrary frame, and a reader who sees
            # only "evidence" must be able to trust that both axes were measured.
            "frame_choice": (
                "evidence"
                if primary_choice["basis"] == "evidence" and secondary_choice["basis"] == "evidence"
                else "arbitrary-canonical"
            ),
            "primary": winner.to_dict(),
            # Relative to the candidate above, which the canonical rule may have
            # promoted over the highest scorer. `primary_choice` keeps the score
            # ranking under `highest_score*` when the two differ, so a reader is
            # never shown one candidate as both the winner and its own runner-up.
            "primary_runner_up": primary_choice["runner_up"],
            "primary_margin": primary_margin,
            "primary_source": source,
            "primary_choice": primary_choice,
            "secondary": x_winner.to_dict(),
            "secondary_runner_up": secondary_choice["runner_up"],
            "secondary_margin": secondary_margin,
            "secondary_source": secondary_basis,
            "secondary_choice": secondary_choice,
            "origin_source": origin_source,
            "frame_margin": frame_margin,
            "angle_tolerance_deg": angle_tolerance_deg,
            "offset_tolerance": offset_tolerance,
            "sigma_multiple": sigma_multiple,
        },
    )
