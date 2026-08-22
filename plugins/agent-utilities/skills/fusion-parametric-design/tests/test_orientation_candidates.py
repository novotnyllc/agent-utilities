from __future__ import annotations

import unittest
from unittest import mock

from fusion_design.orientation_candidates import (
    MAX_ORIENTATION_CANDIDATES,
    OrientationCandidateError,
    orientation_candidates,
)
from fusion_design.printable_parts import CONTACT_FACES


def _orientation(contact_face: str, alternatives: list[str] | None = None) -> dict:
    orientation = {"contact_face": contact_face, "rationale": "flat floor"}
    if alternatives is not None:
        orientation["allowed_alternatives"] = alternatives
    return orientation


class OrientationCandidateTests(unittest.TestCase):
    def test_declared_alternatives_yield_exactly_those_faces(self) -> None:
        candidates = orientation_candidates(
            _orientation("+Z", ["-Y", "-X"]), "Product/Base"
        )
        self.assertEqual(["+Z", "-X", "-Y"], [c["contact_face"] for c in candidates])
        self.assertEqual([True, False, False], [c["is_primary"] for c in candidates])

    def test_alternatives_are_sorted_deterministically(self) -> None:
        first = orientation_candidates(_orientation("-Z", ["+X", "+Y"]), "p")
        second = orientation_candidates(_orientation("-Z", ["+Y", "+X"]), "p")
        self.assertEqual(first, second)

    def test_empty_alternatives_yield_all_six_unique_faces(self) -> None:
        for alternatives in ([], None):
            with self.subTest(alternatives=alternatives):
                candidates = orientation_candidates(
                    _orientation("+Y", alternatives), "Product/Lid"
                )
                faces = [c["contact_face"] for c in candidates]
                self.assertEqual(6, len(faces))
                self.assertEqual(len(set(faces)), len(faces))
                self.assertEqual("+Y", faces[0])
                self.assertEqual(sorted(CONTACT_FACES), sorted(faces))

    def test_duplicate_alternative_is_rejected(self) -> None:
        with self.assertRaisesRegex(OrientationCandidateError, "duplicates are refused"):
            orientation_candidates(_orientation("-Z", ["-Z"]), "Product/Base")

    def test_cap_breach_fails_named(self) -> None:
        # Six unique faces is the physical maximum, so the cap is
        # defense-in-depth; lower it to prove the breach path raises named.
        orientation = {"contact_face": "-Z", "allowed_alternatives": ["+X", "+Y", "+Z"]}
        lowered_cap = 3
        with self.assertRaisesRegex(OrientationCandidateError, f"hard cap of {lowered_cap}"):
            with mock.patch(
                "fusion_design.orientation_candidates.MAX_ORIENTATION_CANDIDATES", 3
            ):
                orientation_candidates(orientation, "Product/Overgrown")

    def test_invalid_contact_face_fails_named(self) -> None:
        with self.assertRaisesRegex(OrientationCandidateError, "not one of"):
            orientation_candidates(_orientation("down"), "Product/Base")

    def test_missing_orientation_object_fails_named(self) -> None:
        with self.assertRaisesRegex(OrientationCandidateError, "no orientation object"):
            orientation_candidates(None, "Product/Base")


if __name__ == "__main__":
    unittest.main()
