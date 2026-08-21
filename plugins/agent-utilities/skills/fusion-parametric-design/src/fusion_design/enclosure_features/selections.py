"""Explicit selection descriptors; deliberately no nearest-geometry search."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EntityRef:
    component_path: str
    expected_type: str
    entity_token: str

    def __post_init__(self) -> None:
        if not self.component_path.strip():
            raise ValueError("component_path is required")
        if not self.expected_type.startswith("adsk::fusion::"):
            raise ValueError("expected_type must be an explicit Fusion object type")
        if not self.entity_token.strip():
            raise ValueError("entity_token is required; v1 never searches for a nearby entity")

    def to_payload(self) -> dict[str, str]:
        return {
            "component_path": self.component_path,
            "expected_type": self.expected_type,
            "entity_token": self.entity_token,
        }
