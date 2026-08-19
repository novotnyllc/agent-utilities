"""Fit-record parsing, fit uncertainty, and datum-frame derivation.

Pure arithmetic over U2's fit record: no Fusion, no live API, stdlib only.  Two
jobs live here, and they are together because the second is built from the first.

* **Reading the fit record** into typed regions, refusing a record that is
  missing a field this stage needs rather than substituting a default.  A
  missing field means *we cannot judge*, and turning that into *the condition
  was not met* is the exact defect this module is written to avoid.
* **Deriving the datum frame** from the accepted fits under a total, stated
  tie-break order, and refusing when the winning candidate does not beat its
  runner-up by the caller's declared margin.  A datum chosen by an unstated rule
  is not reproducible, and reproducibility is what makes the model reviewable.

Uncertainty handling is deliberately a thin, replaceable layer: a fit's
uncertainty is read from the record, never estimated here.  When the record
carries none, an uncertainty-based judgement **refuses**; it never quietly
becomes an absolute-threshold judgement wearing the same label.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from typing import Any, Iterable, Sequence

from .mesh_fitting import (
    PRIMITIVE_KINDS,
    ROUTER_REFUSALS,
    ROUTER_VERDICTS,
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
        "Two candidates are within the declared margin. Either declare a smaller frame_margin with a "
        "rationale that says why the winner is meaningfully better, or name the axis explicitly."
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
}

TOLERANCE_BASES = {"uncertainty", "declared-absolute"}


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
    #: U2's kinematic-router verdict, present only on regions the primitive
    #: stage disclaimed. ``None`` means the router did not run here, which is a
    #: different thing from having run and found nothing -- and the difference
    #: is why this is not defaulted to an empty verdict.
    routing: dict[str, Any] | None = None
    #: The region's dominant Besl-Jain signature, carried so an unreconstructed
    #: region can say what it looks like rather than only that it did not fit.
    dominant_curvature: str | None = None

    @property
    def accepted(self) -> bool:
        return self.fit is not None and self.fit.accepted

    def routed(self, verdict: str) -> bool:
        """Did the router reach ``verdict`` here, with no refusal against it?"""
        if not isinstance(self.routing, dict) or self.routing.get("refusal"):
            return False
        return self.routing.get("verdict") == verdict

    def router_direction(self) -> Vec3 | None:
        if not isinstance(self.routing, dict):
            return None
        value = self.routing.get("direction")
        return _vector(value)

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
            routing=self.routing,
            dominant_curvature=self.dominant_curvature,
        )


@dataclass(frozen=True, slots=True)
class FitRecord:
    dump_sha256: str
    units: str
    total_area: float
    regions: tuple[RegionFit, ...]

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


def _parse_routing(raw: Any, path: str) -> dict[str, Any] | None:
    """Read U2's router verdict, or refuse it. Absent is absent, never 'none'.

    A verdict outside the closed set, or a verdict claimed alongside a refusal,
    is refused rather than read past: this block is what licenses a region with
    no primitive fit to be built into a feature, so an unreadable one must stop
    the plan rather than quietly route nothing.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise _malformed(path, "an object, or absent when the router did not run")
    verdict = raw.get("verdict")
    if verdict not in ROUTER_VERDICTS:
        raise _malformed(f"{path}.verdict", f"one of {', '.join(sorted(ROUTER_VERDICTS))}")
    refusal_token = raw.get("refusal")
    if refusal_token is not None and refusal_token not in ROUTER_REFUSALS:
        raise _malformed(
            f"{path}.refusal", f"null or one of {', '.join(sorted(ROUTER_REFUSALS))}"
        )
    if refusal_token is not None and verdict != "none":
        raise _malformed(
            f"{path}.verdict",
            "'none' when a refusal is recorded; a refusal says the measurement licensed no verdict",
        )
    direction = raw.get("direction")
    if direction is not None and _vector(direction) is None:
        raise _malformed(f"{path}.direction", "a finite three-element vector when present")
    if verdict in ("extrusion", "revolution", "helical") and _vector(direction) is None:
        raise _malformed(
            f"{path}.direction",
            "present on a routed verdict; a motion with no recoverable direction is not a verdict",
        )
    return dict(raw)


def _parse_signature(raw: Any, path: str) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise _malformed(path, "the region's dominant curvature signature, or absent")
    return raw.strip()


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
        regions.append(
            RegionFit(
                region_hash=region_hash,
                area=area,
                bounding_box=(lo, hi),
                fit=fit,
                axial_span=axial_span,
                uncertainty=uncertainty,
                routing=_parse_routing(raw_region.get("routing"), f"{path}.routing"),
                dominant_curvature=_parse_signature(
                    raw_region.get("dominant_curvature"), f"{path}.dominant_curvature"
                ),
            )
        )
    return FitRecord(
        dump_sha256=dump_sha256,
        units=units.strip(),
        total_area=total_area,
        regions=tuple(regions),
    )


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


def _primary_candidates(regions: Sequence[RegionFit]) -> tuple[list[AxisCandidate], str]:
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
            )
        )
    return sorted(planes, key=AxisCandidate.sort_key), "plane"


def _origin_on_axis(
    regions: Sequence[RegionFit],
    z: Vec3,
    axis_anchor: Vec3,
    angle_tolerance_deg: float,
) -> tuple[Vec3, str]:
    """Where the primary axis meets the lowest plane perpendicular to it."""
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
        return origin, f"primary axis meets plane {region_hash[:12]} at station {station:.6g}"

    planes = sorted(
        (
            (-region.area, region.region_hash, region.anchor())
            for region in regions
            if region.fit is not None and region.fit.kind == "plane" and region.anchor() is not None
        )
    )
    if planes:
        _area, region_hash, point = planes[0]
        return point, f"centroid of the largest plane {region_hash[:12]}; no plane is perpendicular to the primary axis"

    anchors = sorted(
        (region.anchor(), region.region_hash) for region in regions if region.anchor() is not None
    )
    total = len(anchors)
    centroid = (
        sum(a[0][0] for a in anchors) / total,
        sum(a[0][1] for a in anchors) / total,
        sum(a[0][2] for a in anchors) / total,
    )
    return centroid, "centroid of every accepted fit's anchor point; the part has no fitted plane"


def _secondary_candidates(
    regions: Sequence[RegionFit], z: Vec3, angle_tolerance_deg: float
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
        if abs(_angle_deg(normal, z) - 90.0) > angle_tolerance_deg:
            continue
        x = _unit(_sub(normal, _scale(z, _dot(normal, z))))
        if x is None:
            continue
        out.append(
            AxisCandidate(
                region_hash=region.region_hash,
                kind="plane",
                score=region.area,
                area=region.area,
                direction=_canonical_direction(x),
                anchor=point,
                basis="normal of a plane parallel to the primary axis, orthogonalised",
            )
        )
    return sorted(out, key=AxisCandidate.sort_key)


def _secondary_from_second_axis(
    regions: Sequence[RegionFit],
    z: Vec3,
    origin: Vec3,
    primary_region_hash: str,
    offset_tolerance: float,
) -> list[AxisCandidate]:
    """A bolt pattern gives a natural X: the direction to the second axis."""
    out: list[AxisCandidate] = []
    for region in regions:
        fit = region.fit
        if fit is None or fit.kind not in ("cylinder", "cone"):
            continue
        if region.region_hash == primary_region_hash:
            continue
        anchor = region.anchor()
        if anchor is None:
            continue
        offset = _sub(anchor, origin)
        perpendicular = _sub(offset, _scale(z, _dot(offset, z)))
        if _length(perpendicular) <= offset_tolerance:
            continue
        x = _unit(perpendicular)
        if x is None:
            continue
        out.append(
            AxisCandidate(
                region_hash=region.region_hash,
                kind=fit.kind,
                score=_length(perpendicular),
                area=region.area,
                direction=_canonical_direction(x),
                anchor=anchor,
                basis="perpendicular offset from the origin to a second axis",
            )
        )
    return sorted(out, key=AxisCandidate.sort_key)


def derive_datum_frame(
    regions: Sequence[RegionFit],
    *,
    frame_margin: float,
    angle_tolerance_deg: float,
    offset_tolerance: float,
) -> DatumFrame:
    """Derive origin and axes from the accepted fits, or refuse.

    The order is total and stated, and every tie-break reads a measured number
    or a canonicalised vector — never dict iteration order, never a face-group
    temp id.  Determinism is a tested property here, not an aspiration.

    ``frame_margin`` is a *relative* margin: the winner must beat the best rival
    candidate by that fraction of its own score.  Relative rather than absolute
    because the scores are areas and radius-times-length products, whose scale
    is the part's, not ours.
    """
    for label, value in (
        ("frame_margin", frame_margin),
        ("angle_tolerance_deg", angle_tolerance_deg),
        ("offset_tolerance", offset_tolerance),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0.0:
            raise ValueError(f"{label} must be a positive finite number declared by the caller.")

    accepted = [region for region in regions if region.accepted]
    if not accepted:
        raise _refuse(
            "frame-no-accepted-fits",
            "no region has an accepted fit, so there is nothing to derive a frame from.",
            {"region_count": len(list(regions))},
        )

    candidates, source = _primary_candidates(accepted)
    if not candidates:
        raise _refuse(
            "frame-no-accepted-fits",
            "no accepted fit carries a direction, so no primary axis can be derived.",
            {"accepted_count": len(accepted)},
        )
    winner = candidates[0]
    rival = _first_rival(candidates, winner, angle_tolerance_deg)
    primary_margin = None if rival is None else _relative_margin(winner.score, rival.score)
    if primary_margin is not None and primary_margin < frame_margin:
        raise _refuse(
            "frame-ambiguous",
            f"the primary-axis winner beats its nearest differently-directed rival by "
            f"{primary_margin:.4g}, below the declared margin {frame_margin:g}.",
            {
                "axis": "primary",
                "winner": winner.to_dict(),
                "runner_up": rival.to_dict(),
                "margin": primary_margin,
                "frame_margin": frame_margin,
            },
        )
    z = winner.direction
    origin, origin_source = _origin_on_axis(accepted, z, winner.anchor, angle_tolerance_deg)

    secondary = _secondary_candidates(accepted, z, angle_tolerance_deg)
    secondary_basis = "plane parallel to the primary axis"
    if not secondary:
        secondary = _secondary_from_second_axis(
            accepted, z, origin, winner.region_hash, offset_tolerance
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
    if secondary_margin is not None and secondary_margin < frame_margin:
        raise _refuse(
            "frame-ambiguous",
            f"the secondary-axis winner beats its nearest differently-directed rival by "
            f"{secondary_margin:.4g}, below the declared margin {frame_margin:g}.",
            {
                "axis": "secondary",
                "winner": x_winner.to_dict(),
                "runner_up": x_rival.to_dict(),
                "margin": secondary_margin,
                "frame_margin": frame_margin,
            },
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
            "primary": winner.to_dict(),
            "primary_runner_up": None if rival is None else rival.to_dict(),
            "primary_margin": primary_margin,
            "primary_source": source,
            "secondary": x_winner.to_dict(),
            "secondary_runner_up": None if x_rival is None else x_rival.to_dict(),
            "secondary_margin": secondary_margin,
            "secondary_source": secondary_basis,
            "origin_source": origin_source,
            "frame_margin": frame_margin,
            "angle_tolerance_deg": angle_tolerance_deg,
            "offset_tolerance": offset_tolerance,
        },
    )
