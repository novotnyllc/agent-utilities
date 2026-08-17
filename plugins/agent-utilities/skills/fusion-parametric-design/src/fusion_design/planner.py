from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .manifest import Manifest, validate_manifest_data


@dataclass(frozen=True, slots=True)
class PlanPhase:
    phase_id: str
    goal: str
    mutates_document: bool
    required_capabilities: tuple[str, ...]
    completion_evidence: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "goal": self.goal,
            "mutates_document": self.mutates_document,
            "required_capabilities": list(self.required_capabilities),
            "completion_evidence": list(self.completion_evidence),
        }


@dataclass(frozen=True, slots=True)
class Plan:
    project_name: str
    blocked: bool
    blockers: tuple[str, ...]
    phases: tuple[PlanPhase, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "blocked": self.blocked,
            "blockers": list(self.blockers),
            "phases": [phase.to_dict() for phase in self.phases],
        }


def build_plan(manifest: Manifest) -> Plan:
    issues = validate_manifest_data(manifest.data)
    blockers = [str(issue) for issue in issues if issue.severity == "error"]
    for parameter in manifest.parameters:
        if parameter.get("critical") and not str(parameter.get("expression", "")).strip():
            name = str(parameter.get("name", "<unnamed>"))
            message = f"Critical parameter {name} has no value; research or measurement must settle it before modeling."
            if message not in blockers:
                blockers.append(message)

    phases = (
        PlanPhase(
            "discover-capabilities",
            "Discover the current Fusion MCP tools, resources, prompts, schemas, and permissions instead of assuming names from an older release.",
            False,
            ("mcp-discovery",),
            ("capability map", "unsupported-capability list"),
        ),
        PlanPhase(
            "checkpoint-and-inventory",
            "Save or version the active Fusion document, then capture a read-only inventory of design type, parameters, timeline health, components, bodies, meshes, and placements.",
            False,
            ("document-read", "script-execution", "save-or-version"),
            ("checkpoint identifier", "inventory report"),
        ),
        PlanPhase(
            "research-gate",
            "Resolve exact manufactured parts, standards, critical fit dimensions, provenance, confidence, and provisional status before creating fit-dependent features.",
            False,
            ("documentation-read", "web-or-file-research"),
            ("validated manifest", "no unresolved critical dimensions"),
        ),
        PlanPhase(
            "sync-parameters",
            "Create or update named Fusion user parameters and provenance attributes without replacing existing features or deleting design history.",
            True,
            ("script-execution", "undo-or-checkpoint"),
            ("parameter sync report", "successful Compute All", "healthy timeline"),
        ),
        PlanPhase(
            "ensure-reference-system",
            "Create the component hierarchy and maintain separate editable reference, exact-or-conservative packing, and functional keep-out components for each real object.",
            True,
            ("script-execution", "document-write"),
            ("reference component inventory", "source attributes"),
        ),
        PlanPhase(
            "pack-components",
            "Place packing models and keep-outs, solve service and cable routes, and use measured distances rather than visual impressions.",
            True,
            ("script-execution", "measurement"),
            ("packing ledger", "clearance results", "interference results"),
        ),
        PlanPhase(
            "build-product-features",
            "Build or edit native Fusion sketches, constraints, timeline features, components, joints, and configurations that reference the user parameters.",
            True,
            ("script-execution", "document-write"),
            ("named feature groups", "healthy parametric timeline", "viewport evidence"),
        ),
        PlanPhase(
            "verify",
            "Run the verification contract: required entities, recompute health, clearances, disallowed interferences, print-part count, and any task-specific joint sweeps or fit coupons.",
            False,
            ("script-execution", "measurement", "interference-analysis"),
            ("machine-readable verification report", "screenshots for visual review"),
        ),
        PlanPhase(
            "export-and-cost",
            "Export manufacturing files from the validated Fusion document and obtain print time/material estimates from a configured external slicer when available.",
            True,
            ("export", "optional-external-slicer"),
            ("export hashes", "slicer estimate or explicit unsupported result", "handoff report"),
        ),
    )
    return Plan(manifest.project_name, bool(blockers), tuple(blockers), phases)
