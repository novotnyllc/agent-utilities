"""Normalization for PrusaSlicer's installed profile-query JSON."""

from __future__ import annotations

import math
from typing import Any


def _nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _profile_record(
    profile: Any,
    *,
    source: str,
    model: Any,
    variant: Any,
    vendor: Any,
    vendor_id: Any,
) -> dict[str, Any]:
    if not isinstance(profile, dict):
        raise ValueError("printer profile entries must be objects")
    name = _nonempty_string(profile.get("name"), "printer profile name")
    extruders = profile.get("extruders_cnt")
    if not isinstance(extruders, int) or isinstance(extruders, bool) or extruders < 1:
        raise ValueError(f"printer profile {name!r} has invalid extruders_cnt")
    bed = profile.get("bed")
    if not isinstance(bed, dict):
        raise ValueError(f"printer profile {name!r} has no bed object")
    width = bed.get("width")
    height = bed.get("height")
    if (
        not isinstance(width, (int, float))
        or isinstance(width, bool)
        or not math.isfinite(float(width))
        or width <= 0
    ):
        raise ValueError(f"printer profile {name!r} has invalid bed width")
    if (
        not isinstance(height, (int, float))
        or isinstance(height, bool)
        or not math.isfinite(float(height))
        or height <= 0
    ):
        raise ValueError(f"printer profile {name!r} has invalid bed height")
    record = {
        "name": name,
        "identifier": name,
        "source": source,
        "model": model,
        "variant": str(variant) if variant is not None else None,
        "vendor": vendor,
        "vendor_id": vendor_id,
        "extruders_cnt": extruders,
        "bed": {
            "type": bed.get("type"),
            "width": width,
            "height": height,
            "origin": bed.get("origin"),
            "max_print_height": bed.get("max_print_height"),
        },
    }
    return record


def normalize_printer_models(payload: Any) -> dict[str, Any]:
    """Normalize system and user printer identifiers while retaining exact names."""
    if not isinstance(payload, dict) or not isinstance(payload.get("printer_models"), list):
        raise ValueError("printer query JSON must contain a printer_models list")
    profiles: dict[str, dict[str, Any]] = {}
    models: list[dict[str, Any]] = []
    for model in payload["printer_models"]:
        if not isinstance(model, dict):
            raise ValueError("printer_models entries must be objects")
        model_id = _nonempty_string(model.get("id"), "printer model id")
        model_name = _nonempty_string(model.get("name"), "printer model name")
        variants = model.get("variants")
        if not isinstance(variants, list):
            raise ValueError(f"printer model {model_id!r} has no variants list")
        vendor = model.get("vendor_name")
        vendor_id = model.get("vendor_id")
        normalized_model = {
            "id": model_id,
            "name": model_name,
            "technology": model.get("technology"),
            "vendor": vendor,
            "vendor_id": vendor_id,
            "variants": [],
        }
        for variant in variants:
            if not isinstance(variant, dict) or variant.get("name") in (None, ""):
                raise ValueError(f"printer model {model_id!r} has an invalid variant")
            variant_name = variant.get("name")
            variant_record = {"name": variant_name, "printer_profiles": [], "user_printer_profiles": []}
            for key, source in (("printer_profiles", "system"), ("user_printer_profiles", "user")):
                entries = variant.get(key, [])
                if not isinstance(entries, list):
                    raise ValueError(f"variant {variant_name!r} has invalid {key}")
                for entry in entries:
                    record = _profile_record(
                        entry,
                        source=source,
                        model=model_id,
                        variant=variant_name,
                        vendor=vendor,
                        vendor_id=vendor_id,
                    )
                    identifier = record["identifier"]
                    if identifier in profiles:
                        raise ValueError(f"duplicate printer profile identifier {identifier!r}")
                    profiles[identifier] = record
                    variant_record[key].append(identifier)
            normalized_model["variants"].append(variant_record)
        models.append(normalized_model)
    return {"printer_models": models, "printer_profiles": profiles, "installed": True, "resolver": "prusaslicer"}


def _normalize_print_entries(entries: Any, *, source: str) -> list[dict[str, Any]]:
    if not isinstance(entries, list):
        raise ValueError("print profile collection must be a list")
    normalized: list[dict[str, Any]] = []
    for profile in entries:
        if not isinstance(profile, dict):
            raise ValueError("print profile entries must be objects")
        name = _nonempty_string(profile.get("name"), "print profile name")
        filament_profiles = profile.get("filament_profiles")
        user_filament_profiles = profile.get("user_filament_profiles", [])
        if not isinstance(filament_profiles, list) or not all(
            isinstance(value, str) and value.strip() for value in filament_profiles
        ):
            raise ValueError(f"print profile {name!r} has invalid filament_profiles")
        if not isinstance(user_filament_profiles, list) or not all(
            isinstance(value, str) and value.strip() for value in user_filament_profiles
        ):
            raise ValueError(f"print profile {name!r} has invalid user_filament_profiles")
        normalized.append(
            {
                "name": name,
                "identifier": name,
                "source": source,
                "filament_profiles": list(filament_profiles) + list(user_filament_profiles),
                "user_filament_profiles": list(user_filament_profiles),
            }
        )
    return normalized


def normalize_print_filament_profiles(payload: Any) -> dict[str, Any]:
    """Normalize compatible print/filament identifiers without rewriting names."""
    if not isinstance(payload, dict):
        raise ValueError("print/filament query JSON must be an object")
    printer_profile = _nonempty_string(payload.get("printer_profile"), "printer_profile")
    if "print_profiles" not in payload:
        raise ValueError("print/filament query JSON must contain print_profiles")
    system_profiles = _normalize_print_entries(payload["print_profiles"], source="system")
    user_profiles = _normalize_print_entries(payload.get("user_print_profiles", []), source="user")
    compatibility: dict[str, dict[str, Any]] = {}
    print_profiles: dict[str, dict[str, Any]] = {}
    for profile in [*system_profiles, *user_profiles]:
        name = profile["identifier"]
        if name in compatibility:
            raise ValueError(f"duplicate print profile identifier {name!r}")
        compatibility[name] = {
            "filament_profiles": list(profile["filament_profiles"]),
            "user_filament_profiles": list(profile["user_filament_profiles"]),
            "source": profile["source"],
        }
        print_profiles[name] = profile
    return {
        "printer_profile": printer_profile,
        "print_profiles": print_profiles,
        "compatibility": compatibility,
        "installed": True,
        "resolver": "prusaslicer",
    }
