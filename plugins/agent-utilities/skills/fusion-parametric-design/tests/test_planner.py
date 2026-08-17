from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from fusion_design.manifest import Manifest
from fusion_design.planner import build_plan


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "electronics-enclosure" / "fusion-project.json"


class PlannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = json.loads(EXAMPLE.read_text(encoding="utf-8"))

    def test_plan_has_research_and_fusion_native_update_phases(self) -> None:
        plan = build_plan(Manifest.from_data(self.data))
        self.assertFalse(plan.blocked)
        phase_ids = [phase.phase_id for phase in plan.phases]
        self.assertEqual(
            [
                "discover-capabilities",
                "checkpoint-and-inventory",
                "research-gate",
                "sync-parameters",
                "ensure-reference-system",
                "pack-components",
                "build-product-features",
                "verify",
                "export-and-cost",
            ],
            phase_ids,
        )
        serialized = plan.to_dict()
        self.assertNotIn("regenerate-whole-model", json.dumps(serialized))

    def test_plan_blocks_when_research_gate_is_incomplete(self) -> None:
        data = copy.deepcopy(self.data)
        data["parameters"][0]["expression"] = ""
        plan = build_plan(Manifest.from_data(data, validate=False))
        self.assertTrue(plan.blocked)
        self.assertTrue(any("src_pd_board_length" in blocker for blocker in plan.blockers))


if __name__ == "__main__":
    unittest.main()
