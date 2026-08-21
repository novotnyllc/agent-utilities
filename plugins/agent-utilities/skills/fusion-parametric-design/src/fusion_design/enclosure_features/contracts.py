"""Host-only typed contracts for one bounded enclosure feature."""

from dataclasses import dataclass

from .evidence import EvidenceClass, validate_evidence
from .identity import validate_feature_id, validate_instance_name
from .parameters import (
    validate_expression,
    validate_namespace,
    validate_parameter_name,
)
from .selections import EntityRef
from .rules import (
    INSERT_DIMENSION_EVIDENCE,
    INSERT_DIMENSION_INVALIDATED_BY,
    PHYSICAL_CLAIMS_NOT_MADE,
)


@dataclass(frozen=True)
class RecipeVersion:
    recipe_id: str
    version: int

    def __post_init__(self) -> None:
        if (self.recipe_id, self.version) != ("boss.heat_set_insert", 1):
            raise ValueError("v1 supports only boss.heat_set_insert recipe version 1")


@dataclass(frozen=True)
class FeatureParameter:
    semantic_name: str
    name: str
    expression: str
    units: str
    evidence_class: EvidenceClass
    source_ref: str | None = None
    provisional: bool = False
    coupon_required: bool = False

    def validate(self, namespace: str) -> None:
        if not self.semantic_name.strip():
            raise ValueError("semantic_name is required")
        if self.units != "mm":
            raise ValueError("v1 enclosure feature parameters support only mm")
        validate_parameter_name(self.name, namespace)
        validate_expression(self.expression, self.units)
        validate_evidence(self.evidence_class, self.source_ref)
        if self.provisional != (self.evidence_class is EvidenceClass.PROVISIONAL_DEFAULT):
            raise ValueError("provisional must match provisional-default evidence")

    def to_payload(self) -> dict[str, object]:
        return {
            "semantic_name": self.semantic_name,
            "name": self.name,
            "expression": self.expression,
            "units": self.units,
            "evidence_class": self.evidence_class.value,
            "source_ref": self.source_ref,
            "provisional": self.provisional,
            "coupon_required": self.coupon_required,
        }


@dataclass(frozen=True)
class BossRequest:
    feature_id: str
    instance_name: str
    recipe: RecipeVersion
    parameter_namespace: str
    target_body: EntityRef
    support_face: EntityRef
    placement: EntityRef
    outer_diameter: FeatureParameter
    boss_height: FeatureParameter
    bore_diameter: FeatureParameter
    bore_depth: FeatureParameter
    head_seat_diameter: FeatureParameter
    head_seat_depth: FeatureParameter
    rib_count: int = 0
    rib_thickness: FeatureParameter | None = None
    rib_length: FeatureParameter | None = None

    def __post_init__(self) -> None:
        validate_feature_id(self.feature_id)
        validate_instance_name(self.instance_name)
        namespace = validate_namespace(self.parameter_namespace)
        if self.target_body.expected_type != "adsk::fusion::BRepBody":
            raise ValueError("target_body must explicitly be a BRepBody")
        if self.support_face.expected_type != "adsk::fusion::BRepFace":
            raise ValueError("support_face must explicitly be a BRepFace")
        if self.placement.expected_type not in {
            "adsk::fusion::SketchPoint",
            "adsk::fusion::ConstructionPoint",
        }:
            raise ValueError("placement must be a SketchPoint or ConstructionPoint")
        selections = (self.target_body, self.support_face, self.placement)
        if any(selection.component_path != "Root" for selection in selections):
            raise ValueError("v1 enclosure features support only root-component entities")
        parameters = self.parameters()
        expected_semantics = (
            "outer_diameter",
            "boss_height",
            "bore_diameter",
            "bore_depth",
            "head_seat_diameter",
            "head_seat_depth",
        ) + (("rib_thickness", "rib_length") if self.rib_count else ())
        if tuple(item.semantic_name for item in parameters) != expected_semantics:
            raise ValueError("boss parameters must use the exact v1 semantic roles")
        if len({item.name for item in parameters}) != len(parameters):
            raise ValueError("parameter names must be unique")
        for parameter in parameters:
            parameter.validate(namespace)
        for parameter in (
            self.bore_diameter,
            self.bore_depth,
            self.head_seat_diameter,
            self.head_seat_depth,
        ):
            if parameter.evidence_class not in INSERT_DIMENSION_EVIDENCE:
                raise ValueError(
                    f"{parameter.semantic_name} must be manufacturer-specified or coupon-verified"
                )
            if not parameter.coupon_required:
                raise ValueError(f"{parameter.semantic_name} must remain coupon-sensitive")
        for parameter in (self.outer_diameter, self.boss_height):
            if parameter.coupon_required:
                raise ValueError(f"{parameter.semantic_name} is not an insert-fit dimension")
        if self.rib_count not in {0, 4}:
            raise ValueError("v1 supports either zero or four orthogonal gussets")
        if self.rib_count and (self.rib_thickness is None or self.rib_length is None):
            raise ValueError("four gussets require rib_thickness and rib_length")
        if not self.rib_count and (self.rib_thickness is not None or self.rib_length is not None):
            raise ValueError("rib parameters require rib_count=4")

    def parameters(self) -> tuple[FeatureParameter, ...]:
        required = (
            self.outer_diameter,
            self.boss_height,
            self.bore_diameter,
            self.bore_depth,
            self.head_seat_diameter,
            self.head_seat_depth,
        )
        if not self.rib_count:
            return required
        assert self.rib_thickness is not None and self.rib_length is not None
        return required + (self.rib_thickness, self.rib_length)

    def to_payload(self) -> dict[str, object]:
        return {
            "feature_id": self.feature_id.lower(),
            "instance_name": validate_instance_name(self.instance_name),
            "recipe_id": self.recipe.recipe_id,
            "recipe_version": self.recipe.version,
            "parameter_namespace": self.parameter_namespace,
            "target_body": self.target_body.to_payload(),
            "support_face": self.support_face.to_payload(),
            "placement": self.placement.to_payload(),
            "rib_count": self.rib_count,
            "invalidated_by": sorted(INSERT_DIMENSION_INVALIDATED_BY),
            "claims_not_made": sorted(PHYSICAL_CLAIMS_NOT_MADE),
            "parameters": [item.to_payload() for item in self.parameters()],
        }
