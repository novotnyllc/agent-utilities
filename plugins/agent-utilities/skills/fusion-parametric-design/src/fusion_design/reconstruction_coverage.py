"""One honest account of how much of a scan was rebuilt, and what was not.

Four stages each know a different part of the answer and none of them knows the
whole thing:

* **U2 (the fit record)** knows how much of the mesh got an accepted fit at all,
  and which components were never claimed by any region.
* **U3 (the program)** knows how much of *that* an archetype covers, and names a
  gate for every region it declined.
* **U4 (the rebuild report)** knows what Fusion actually built — which is not
  the same as what was planned, because a fillet can be skipped.
* **U5 (the editability verdict)** knows which parameters were proven to drive a
  rebuild, which is a different question again and is carried, not merged.

This module composes them without ever rounding up.  The arithmetic runs one
direction only: each stage can *lose* area relative to the one before it and can
never gain any, so the delivered fraction is the smallest honest number rather
than the largest defensible one.  A region that was refused, gated, or skipped
is subtracted — counting one as handled would be precisely the defect four
audits of this repository found.

Stdlib only, no Fusion, fully offline-testable.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

# The closed label set.  `parametric-partial` is the honest common case and it
# exists so that a partial result has a name of its own instead of being
# reported as a success with a footnote.
COVERAGE_LABELS = ("parametric-full", "parametric-partial", "reconstruction-refused")

# Below this, a fraction is treated as 1.0.  Areas are summed in floating point
# over thousands of triangles, so exact equality is not a thing to wait for; a
# part in a million of the surface is far below any mesh's own noise floor.
FULL_COVERAGE_EPSILON = 1e-6

NOT_CLAIMED = (
    "This account states what was rebuilt and what was not. It does not claim that what was "
    "rebuilt is dimensionally correct -- that is the deviation verdict's question -- nor that the "
    "recovered feature tree is the original designer's (it is *a* parameterization consistent with "
    "the measured surface, never *the* original), nor that any parameter drives a rebuild unless "
    "the editability proof exercised it and says so."
)


def _fraction(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _fit_stage(fit_record: Mapping[str, Any] | None) -> dict[str, Any]:
    """What U2 fitted, and what it never claimed at all."""
    if fit_record is None:
        return {
            "stage": "fit",
            "covered_area_fraction": None,
            "unavailable_reason": (
                "no fit record was supplied, so how much of the scan got an accepted fit at all is "
                "not known here. Absent is reported as absent; it is never read as complete."
            ),
            "unclaimed_components": None,
            "unfitted_regions": None,
        }
    unclaimed = fit_record.get("unclaimed")
    components = unclaimed.get("components") if isinstance(unclaimed, dict) else None
    return {
        "stage": "fit",
        "covered_area_fraction": _fraction(fit_record.get("covered_area_fraction")),
        "unavailable_reason": None,
        "unclaimed_components": [
            {
                "area_fraction": _fraction(entry.get("area_fraction")),
                "dominant_curvature": entry.get("dominant_curvature"),
            }
            for entry in components or ()
            if isinstance(entry, dict)
        ],
        "unfitted_regions": [
            {
                "region_id": entry.get("region_hash"),
                "area_fraction": _fraction(entry.get("area_fraction")),
                "gate": entry.get("failed_gate"),
            }
            for entry in fit_record.get("unfitted_regions") or ()
            if isinstance(entry, dict)
        ],
    }


def _plan_stage(program: Mapping[str, Any]) -> dict[str, Any]:
    """What U3's archetypes cover, and the named gate on everything else."""
    return {
        "stage": "plan",
        "covered_area_fraction": _fraction(program.get("covered_area_fraction")),
        "archetypes": [
            {
                "id": group.get("id"),
                "kind": group.get("kind"),
                "area_fraction": _fraction(group.get("area_fraction")),
            }
            for group in program.get("archetypes") or ()
            if isinstance(group, dict)
        ],
        "unreconstructed": [
            {
                "region_id": entry.get("region_id"),
                "area_fraction": _fraction(entry.get("area_fraction")),
                "gate": entry.get("gate"),
            }
            for entry in program.get("unreconstructed") or ()
            if isinstance(entry, dict)
        ],
    }


def _build_stage(
    program: Mapping[str, Any], rebuild_report: Mapping[str, Any] | None
) -> dict[str, Any]:
    """What Fusion actually built, and which planned archetypes it did not."""
    planned = {
        str(group["id"]): group
        for group in program.get("archetypes") or ()
        if isinstance(group, dict) and group.get("id")
    }
    if rebuild_report is None:
        return {
            "stage": "build",
            "ran": False,
            "ok": None,
            "unavailable_reason": (
                "no rebuild report was supplied, so nothing here has been built. A plan is not a "
                "model."
            ),
            "delivered": [],
            "not_delivered": [
                {
                    "archetype_id": identifier,
                    "area_fraction": _fraction(group.get("area_fraction")),
                    "reason": "not-built",
                }
                for identifier, group in sorted(planned.items())
            ],
            "failures": [],
        }

    failures = [item for item in rebuild_report.get("failures") or () if isinstance(item, str)]
    ok = rebuild_report.get("ok") is True and not failures
    delivered_ids = {
        str(entry["archetype_id"])
        for entry in rebuild_report.get("created") or ()
        if isinstance(entry, dict) and entry.get("archetype_id")
    }
    skipped = {
        str(entry["archetype_id"]): entry
        for entry in rebuild_report.get("fillets_skipped") or ()
        if isinstance(entry, dict) and entry.get("archetype_id")
    }
    not_delivered = []
    for identifier, group in sorted(planned.items()):
        if identifier in delivered_ids:
            continue
        entry = skipped.get(identifier)
        not_delivered.append(
            {
                "archetype_id": identifier,
                "area_fraction": _fraction(group.get("area_fraction")),
                "reason": entry["reason"] if entry else ("refused" if not ok else "not-built"),
                "detail": entry.get("detail") if entry else None,
            }
        )
    return {
        "stage": "build",
        "ran": True,
        "ok": ok,
        "unavailable_reason": None,
        "delivered": [
            {
                "archetype_id": identifier,
                "kind": planned[identifier].get("kind"),
                "area_fraction": _fraction(planned[identifier].get("area_fraction")),
            }
            for identifier in sorted(delivered_ids)
            if identifier in planned
        ],
        "not_delivered": not_delivered,
        "failures": failures,
    }


def _editability_stage(verdict: Mapping[str, Any] | None) -> dict[str, Any]:
    """Which parameters were *proven* to drive a rebuild. Carried, never merged.

    Editability is a different axis from coverage: a fully-covered model whose
    parameters are all inert is not a better outcome than a partial model that
    edits. Folding one number into the other would hide both.
    """
    if verdict is None:
        return {
            "stage": "editability",
            "ran": False,
            "ok": None,
            "unavailable_reason": (
                "no editability verdict was supplied. Nothing here has been shown to rebuild when "
                "a parameter changes, and coverage says nothing about whether it would."
            ),
            "checked": [],
            "not_exercised": [],
        }
    report = verdict.get("report") if isinstance(verdict.get("report"), dict) else verdict
    return {
        "stage": "editability",
        "ran": True,
        "ok": verdict.get("ok") is True,
        "unavailable_reason": None,
        "checked": sorted(
            item for item in report.get("checked") or () if isinstance(item, str)
        ),
        "not_exercised": sorted(
            item for item in report.get("not_exercised") or () if isinstance(item, str)
        ),
        "interactions_exercised": report.get("interactions_exercised"),
    }


def compose_coverage(
    program: Mapping[str, Any],
    *,
    fit_record: Mapping[str, Any] | None = None,
    rebuild_report: Mapping[str, Any] | None = None,
    editability_verdict: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """The one account a user reads at the end of a reconstruction.

    ``delivered_area_fraction`` is the bottom line and it is deliberately the
    *smallest* honest number: the program's own coverage, minus every archetype
    the build did not deliver.  A skipped fillet subtracts its region here even
    though the build succeeded, because an archetype that was planned and not
    built is not reconstructed however the run finished.
    """
    stages = [
        _fit_stage(fit_record),
        _plan_stage(program),
        _build_stage(program, rebuild_report),
        _editability_stage(editability_verdict),
    ]
    fit, plan, build, editability = stages

    planned_fraction = plan["covered_area_fraction"]
    lost = sum(
        entry["area_fraction"] or 0.0 for entry in build["not_delivered"]
    )
    delivered = None if planned_fraction is None else max(0.0, planned_fraction - lost)
    if build["ran"] and not build["ok"]:
        # A refused rebuild rolls everything back and produces no geometry, so
        # the delivered fraction is zero however much was planned.
        delivered = 0.0

    if not build["ran"]:
        label = "reconstruction-refused"
        rationale = (
            "Nothing was built. A reconstruction program is a plan, and a plan that has not been "
            "run against Fusion has reconstructed no part of the scan."
        )
    elif not build["ok"]:
        label = "reconstruction-refused"
        rationale = (
            "The rebuild refused with "
            + ", ".join(build["failures"] or ["an unnamed failure"])
            + " and rolled back everything it created, so no geometry was delivered."
        )
    elif delivered is not None and delivered >= 1.0 - FULL_COVERAGE_EPSILON:
        label = "parametric-full"
        rationale = (
            "Every region of the scan that carried an accepted fit was planned as an archetype and "
            "built. This is a statement about surface area covered, not about accuracy."
        )
    else:
        label = "parametric-partial"
        rationale = (
            "Part of the scan was rebuilt as editable features and part was not. This is a "
            "successful outcome and it is reported under its own name rather than as a "
            "reconstruction with a footnote: the unreconstructed regions are listed below with the "
            "gate that stopped each one, and the source mesh remains in the document as reference "
            "geometry over the rebuild."
        )

    unreconstructed = list(plan["unreconstructed"])
    for entry in build["not_delivered"]:
        unreconstructed.append(
            {
                "region_id": entry["archetype_id"],
                "area_fraction": entry["area_fraction"],
                "gate": (
                    f"{entry['reason']}: this archetype was planned and the build did not deliver "
                    "it. " + (entry.get("detail") or "")
                ).strip(),
            }
        )

    return {
        "kind": "reconstruction-coverage",
        "label": label,
        "label_rationale": rationale,
        "labels": list(COVERAGE_LABELS),
        "delivered_area_fraction": delivered,
        "delivered_area_fraction_note": (
            "The program's coverage minus every archetype the build did not deliver. It is the "
            "fraction of the scan's surface area now standing as editable Fusion features, and it "
            "is never rounded up."
        ),
        "stages": stages,
        "unreconstructed": unreconstructed,
        "claims_not_made": NOT_CLAIMED,
    }


def format_coverage(account: Mapping[str, Any]) -> str:
    """The account as a few lines of prose, for a human at the end of a run."""
    lines = [f"{account['label']}: {account['label_rationale']}"]
    delivered = account.get("delivered_area_fraction")
    lines.append(
        "delivered area fraction: "
        + ("unknown" if delivered is None else f"{delivered:.4f}")
    )
    for stage in account["stages"]:
        if stage.get("unavailable_reason"):
            lines.append(f"  {stage['stage']}: {stage['unavailable_reason']}")
    unreconstructed: Sequence[Mapping[str, Any]] = account["unreconstructed"]
    if not unreconstructed:
        lines.append("  nothing was left unreconstructed.")
    for entry in unreconstructed:
        fraction = entry.get("area_fraction")
        share = "unknown share" if fraction is None else f"{fraction:.4f} of the area"
        lines.append(f"  {entry['region_id']} ({share}): {entry['gate']}")
    lines.append(account["claims_not_made"])
    return "\n".join(lines)
