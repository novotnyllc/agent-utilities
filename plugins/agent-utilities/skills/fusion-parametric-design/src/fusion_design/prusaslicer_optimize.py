"""Slice-in-the-loop optimizer: candidates through build, slice, measure, rank.

U5 of the optimization-loop plan. Consumes the deterministic candidate list
from ``orientation_candidates`` (U3), builds one project per candidate
through the existing verified path, slices headlessly with every guard intact
(complete profile set, hash-chain bindings, runtime fingerprints), and ranks
by a per-intent objective over *measured* G-code statistics. Nothing here
estimates: an unsliced candidate is a failure entry, never a number.

Drift guard (KTD7): each resolved preset file is hashed at build time and
re-verified immediately before every slice invocation; a mismatch aborts the
whole run naming the drifted preset -- slicing with half-migrated profiles
would produce numbers no report can attribute.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
import json
from pathlib import Path
import tempfile
from typing import Any, Callable

from .manifest import Manifest
from .mesh_strength_proxies import compute_strength_proxies
from .scripts import manifest_sha256
from .prusaslicer_project import CANDIDATE_VARIANTS
from .prusaslicer_project import (
    ResolvedPresets,
    build_project,
    preset_hashes,
)
from .prusaslicer_slice import slice_project

from .orientation_candidates import orientation_candidates

# Per-intent objective weights (KTD4): constants in code, recorded in every
# report. fast-structural optimizes wall-clock time with mass tiebreak;
# fine-detail prioritizes layer height (finer = better) with time secondary;
# enclosure balances. Proxy penalties arrive advisory-only from U4.
INTENT_WEIGHTS: dict[str, dict[str, float]] = {
    "fast-structural": {"time": 1.0, "mass": 0.25, "layer_height": 0.0},
    "fine-detail": {"time": 0.25, "mass": 0.0, "layer_height": 10.0},
    "enclosure": {"time": 0.5, "mass": 0.5, "layer_height": 0.5},
}

MAX_CANDIDATES = 12

# Neutral fine-detail term for a baseline candidate whose print preset cannot
# be resolved to a layer height. Mid-range of the variant bounds, so an explicit
# 0.12 mm detail variant always outranks it at equal time and the coarse
# 0.28 mm one always loses to it.
DEFAULT_LAYER_HEIGHT_MM = 0.2


def _parse_time_seconds(raw: Any) -> float:
    '''Parse PrusaSlicer's estimated printing time text into seconds.

    Format observed in real G-code: "18m 4s", "2h 13m 55s". Absent or malformed
    values return infinity so an unreadable statistic can never win by accident.
    '''
    if not isinstance(raw, str) or not raw.strip():
        return math.inf
    total = 0.0
    multipliers = {"h": 3600.0, "m": 60.0, "s": 1.0}
    for token in raw.split():
        unit = next((u for u in sorted(multipliers, key=len, reverse=True) if token.endswith(u)), None)
        if unit is None:
            continue
        try:
            total += float(token[: -len(unit)]) * multipliers[unit]
        except ValueError:
            continue
    return total if total > 0 else math.inf


def _measured_numbers(statistics: dict[str, Any]) -> tuple[float, float]:
    """(time seconds, mass grams) from parsed statistics; inf when absent."""
    time_s = min(
        _parse_time_seconds(statistics.get(key))
        for key in ("estimated_printing_time_normal", "estimated_printing_time_silent")
    )
    mass_g = statistics.get("total_filament_used_g")
    if isinstance(mass_g, bool) or not isinstance(mass_g, (int, float)) or not math.isfinite(float(mass_g)):
        mass_g = math.inf
    return time_s, float(mass_g)


def score_candidate(
    intent: str,
    statistics: dict[str, Any],
    layer_height_mm: float | None,
    proxy_penalty: float = 0.0,
) -> float:
    """Fixed-weight per-intent objective over measured quantities (KTD4)."""
    weights = INTENT_WEIGHTS[intent]
    time_s, mass_g = _measured_numbers(statistics)
    # Ascending sort: smaller is better everywhere. Layer height therefore
    # enters positively -- a finer (smaller) layer adds less penalty than a
    # coarse one. The previous 1/height form inverted that ranking.
    resolved_layer = layer_height_mm if layer_height_mm else DEFAULT_LAYER_HEIGHT_MM
    layer_term = resolved_layer if weights["layer_height"] else 0.0
    return (
        weights["time"] * time_s
        + weights["mass"] * mass_g
        + weights["layer_height"] * layer_term
        + proxy_penalty
    )


# Advisory structural-proxy penalties (U4 doctrine): overhang fraction and
# unsupported span always penalize; vertical-wall fraction only penalizes for
# fine-detail, where visible stair-stepping on curved walls is the point.
_PROXY_OVERHANG_WEIGHT = 10.0
_PROXY_SPAN_WEIGHT_PER_MM = 0.5
_PROXY_VERTICAL_WALL_WEIGHT_FINE_DETAIL = 1.0


def proxy_penalty(intent: str, proxies: dict[str, Any]) -> float:
    """Advisory score penalty from computed mesh strength proxies."""
    return (
        _PROXY_OVERHANG_WEIGHT * float(proxies["overhang_area_fraction"])
        + _PROXY_SPAN_WEIGHT_PER_MM * float(proxies["max_unsupported_span_mm"])
        + (_PROXY_VERTICAL_WALL_WEIGHT_FINE_DETAIL * float(proxies["vertical_wall_fraction"])
           if intent == "fine-detail" else 0.0)
    )


def _candidate_matrix(manifest: Manifest) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The deterministic (face x variant) matrix, bounded before expansion.

    Priority order: every enumerated face's baseline variant first (so no
    face is untested), then the remaining variants face by face in
    declaration/canonical order until the cap is hit. The kept-vs-dropped
    split is returned so the report can name every dropped candidate instead
    of truncating silently. Only a cross product that genuinely exceeds the
    cap produces drops; declared-alternatives runs under it keep everything.
    """
    all_entries: list[dict[str, Any]] = []
    for part in manifest.printable_parts or []:
        path = str(part.get("path", ""))
        for face_record in orientation_candidates(part.get("orientation"), path):
            face = face_record["contact_face"]
            for variant_index, variant in enumerate(CANDIDATE_VARIANTS):
                all_entries.append({
                    "candidate_id": f"{path}:{face}:{variant['label']}",
                    "part_path": path,
                    "contact_face": face,
                    "variant": variant,
                    "_variant_index": variant_index,
                })
    if len(all_entries) <= MAX_CANDIDATES:
        for entry in all_entries:
            entry.pop("_variant_index", None)
        return all_entries, []
    baselines = [e for e in all_entries if e["_variant_index"] == 0]
    extras = [e for e in all_entries if e["_variant_index"] > 0]
    kept = baselines[:MAX_CANDIDATES]
    dropped_ids = {e["candidate_id"] for e in baselines[MAX_CANDIDATES:]}
    for entry in extras:
        if len(kept) < MAX_CANDIDATES:
            kept.append(entry)
        else:
            dropped_ids.add(entry["candidate_id"])
    kept.sort(key=lambda e: (e["part_path"], e["contact_face"], e["_variant_index"]))
    dropped = [e["candidate_id"] for e in all_entries if e["candidate_id"] in dropped_ids]
    for entry in kept:
        entry.pop("_variant_index", None)
    return kept, dropped


def _mesh_payload_for_part(index_path: str | Path, part_path: str, manifest_digest: str) -> bytes:
    """The verified 3MF artifact for one part, read out of the export index.

    The same index file build_project validated is re-read here; its
    manifest binding and artifact hash are checked again so the proxy mesh is
    provably the geometry the project was built from.
    """
    index = json.loads(Path(index_path).read_text(encoding="utf-8"))
    if index.get("manifest_sha256") != manifest_digest:
        raise ValueError(
            f"Export index {str(index_path)!r} no longer matches the manifest; "
            "refusing to compute mesh proxies for a foreign design."
        )
    artifact = next(
        (a for a in index.get("artifacts", []) if a.get("part_path") == part_path and a.get("format") == "3mf"),
        None,
    )
    if artifact is None:
        raise ValueError(f"Export index names no 3MF artifact for part {part_path!r}.")
    filename = artifact["filename"]
    if Path(filename).name != filename:
        raise ValueError(f"Export index artifact filename {filename!r} must be a bare filename.")
    artifact_path = Path(index_path).parent / str(filename)
    payload = artifact_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != artifact.get("sha256"):
        raise ValueError(f"3MF artifact for {part_path!r} does not match its export-index hash.")
    return payload


def optimize(
    manifest: Manifest,
    index_path: str | Path,
    presets: ResolvedPresets,
    *,
    intent: str = "fast-structural",
    executable: str | Path | None = None,
    datadir: str | Path | None = None,
    gcode_format: str = "binary",
    runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Build, slice, measure, rank every candidate; one failure never aborts."""
    if intent not in INTENT_WEIGHTS:
        raise ValueError(f"Unknown intent {intent!r}; expected one of {', '.join(sorted(INTENT_WEIGHTS))}.")
    # U3 candidate set: per-part orientation faces (declared alternatives or
    # all six), combined with the fixed setting variants; bounded to the cap
    # before any slice is attempted (KTD3), with drops recorded, not hidden.
    candidates, dropped_candidates = _candidate_matrix(manifest)
    hashes_before = preset_hashes(presets)
    results: list[dict[str, Any]] = []
    kwargs: dict[str, Any] = {}
    if runner is not None:
        kwargs["runner"] = runner
    with tempfile.TemporaryDirectory(prefix="prusaslicer-optimize-") as temporary:
        work = Path(temporary)
        for index, candidate in enumerate(candidates):
            project_path = work / f"candidate-{index:02d}.3mf"
            try:
                built = build_project(
                    manifest,
                    index_path,
                    project_path,
                    presets,
                    orientation_overrides={candidate["part_path"]: candidate["contact_face"]},
                    candidate_overrides={candidate["part_path"]: {k: str(v) for k, v in candidate["variant"].items() if k != "label"}},
                )
            except (OSError, ValueError) as error:
                results.append({"candidate_id": candidate["candidate_id"], "ok": False, "failure": str(error)})
                continue
            # Drift guard (KTD7): re-verify immediately before invoking the slicer.
            hashes_now = preset_hashes(presets)
            drifted = {
                kind: {"expected": hashes_before[kind], "actual": hashes_now[kind]}
                for kind in hashes_before
                if hashes_before[kind] != hashes_now[kind]
            }
            if drifted:
                return {
                    "kind": "prusaslicer-optimize",
                    "ok": False,
                    "outcome": "preset_drift",
                    "intent": intent,
                    "drifted_presets": drifted,
                    "failure": "Preset files changed between build and slice: "
                        + ", ".join(sorted(drifted)) + ". Aborting before any further slice.",
                    "candidates": results,
                }
            slice_result = slice_project(
                built["project_path"],
                presets,
                bindings={key: built[key] for key in (
                    "project_sha256", "export_index_sha256", "manifest_sha256",
                    "verification_report_sha256", "export_run_id",
                )},
                executable=executable,
                datadir=datadir if datadir is not None else presets.config_root,
                gcode_format=gcode_format,
                **kwargs,
            )
            if slice_result.get("ok"):
                statistics = slice_result.get("statistics", {})
                time_s, mass_g = _measured_numbers(statistics)
                layer_height = None
                overrides = next((o.get("overrides") for o in built.get("objects", [])), {})
                raw_layer = (overrides or {}).get("layer_height")
                if raw_layer is not None:
                    try:
                        layer_height = float(raw_layer)
                    except ValueError:
                        layer_height = None
                proxies: dict[str, Any] | None = None
                penalty = 0.0
                proxy_failure = None
                try:
                    # The export index is hash-verified by build_project, so the
                    # mesh bytes parsed here are the ones the project was built
                    # from -- the proxies describe the geometry actually sliced.
                    mesh_payload = _mesh_payload_for_part(index_path, candidate["part_path"], manifest_sha256(manifest))
                    proxies = compute_strength_proxies(mesh_payload, candidate["part_path"])
                    penalty = proxy_penalty(intent, proxies)
                except (OSError, ValueError) as error:
                    proxy_failure = str(error)
                entry = {
                    "candidate_id": candidate["candidate_id"],
                    "contact_face": candidate["contact_face"],
                    "variant_label": candidate["variant"]["label"],
                    "overrides": overrides,
                    "ok": True,
                    "score": score_candidate(intent, statistics, layer_height, penalty),
                    "time_s": time_s if math.isfinite(time_s) else None,
                    "mass_g": mass_g if math.isfinite(mass_g) else None,
                    "gcode_sha256": slice_result.get("gcode_sha256"),
                    "project_sha256": built["project_sha256"],
                }
                if proxies is not None:
                    entry["strength_proxies"] = proxies
                    entry["proxy_penalty"] = penalty
                if proxy_failure is not None:
                    entry["proxy_failure"] = proxy_failure
                results.append(entry)
            else:
                results.append({"candidate_id": candidate["candidate_id"], "ok": False, "failure": slice_result.get("failure", "slice failed")})
    ranked = sorted(results, key=lambda r: (r.get("score", math.inf), r["time_s"] if r.get("time_s") is not None else math.inf, r["candidate_id"]))
    sliced = [r for r in ranked if r.get("ok")]
    report: dict[str, Any] = {
        "kind": "prusaslicer-optimize",
        "ok": bool(sliced),
        "intent": intent,
        "objective_weights": INTENT_WEIGHTS[intent],
        "preset_hashes_at_build": hashes_before,
        "candidate_count": len(candidates),
        "dropped_candidates": dropped_candidates,
        "ranking": ranked,
        "best": sliced[0] if sliced else None,
    }
    if not sliced:
        report["failure"] = "No candidate produced measurable G-code."
        report["outcome"] = "all_candidates_failed"
    return report
