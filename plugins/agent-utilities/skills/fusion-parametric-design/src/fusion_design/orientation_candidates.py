"""Orientation candidate enumeration for the PrusaSlicer optimization loop.

Given a printable part's declared orientation, produce the bounded set of bed-
contact faces that may be sliced as candidates: the declared alternatives when
any are listed, otherwise all six unique faces. The primary contact_face is a
candidate too (deduped), every rotation is the audited quarter-turn from
prusaslicer_project.rotation_for_contact_face, and the list is capped and
ordered deterministically so identical inputs yield byte-identical candidates.
"""

from __future__ import annotations

from typing import Any

from .printable_parts import CONTACT_FACES
from .prusaslicer_project import rotation_for_contact_face

MAX_ORIENTATION_CANDIDATES = 12

FACES_IN_CANONICAL_ORDER = tuple(sorted(CONTACT_FACES))


class OrientationCandidateError(ValueError):
    """Named failure for orientation-candidate enumeration breaches."""


def orientation_candidates(orientation: Any, part_path: str) -> list[dict[str, Any]]:
    """Return the deterministic orientation candidate set for one declared part."""
    if not isinstance(orientation, dict):
        raise OrientationCandidateError(
            f"Printable part {part_path!r} has no orientation object; cannot enumerate "
            "orientation candidates."
        )
    contact_face = orientation.get("contact_face")
    if not isinstance(contact_face, str) or contact_face not in CONTACT_FACES:
        raise OrientationCandidateError(
            f"Printable part {part_path!r} declares orientation.contact_face "
            f"{contact_face!r}, which is not one of {', '.join(sorted(CONTACT_FACES))}."
        )
    alternatives = orientation.get("allowed_alternatives", [])
    if alternatives is None:
        alternatives = []
    if not isinstance(alternatives, list):
        raise OrientationCandidateError(
            f"Printable part {part_path!r} declares allowed_alternatives that is not a list."
        )
    for alternative in alternatives:
        if not isinstance(alternative, str) or alternative not in CONTACT_FACES:
            raise OrientationCandidateError(
                f"Printable part {part_path!r} declares allowed_alternative {alternative!r}, "
                f"which is not one of {', '.join(sorted(CONTACT_FACES))}."
            )
        if alternative == contact_face:
            raise OrientationCandidateError(
                f"Printable part {part_path!r} repeats its primary contact_face in "
                f"allowed_alternatives ({alternative!r}); duplicates are refused."
            )

    if alternatives:
        faces = [contact_face] + sorted(alternatives)
    else:
        # No declared alternatives: enumerate all six unique faces. The primary
        # face stays first; the rest follow canonical order.
        faces = [contact_face] + [face for face in FACES_IN_CANONICAL_ORDER if face != contact_face]

    if len(faces) > MAX_ORIENTATION_CANDIDATES:
        raise OrientationCandidateError(
            f"Printable part {part_path!r} yields {len(faces)} orientation candidates, above "
            f"the hard cap of {MAX_ORIENTATION_CANDIDATES}; refusing to truncate silently."
        )

    return [
        {
            "contact_face": face,
            "is_primary": face == contact_face,
            "rotation": rotation,
            "rotation_record": record,
        }
        for face in faces
        for rotation, record in (rotation_for_contact_face(face),)
    ]
