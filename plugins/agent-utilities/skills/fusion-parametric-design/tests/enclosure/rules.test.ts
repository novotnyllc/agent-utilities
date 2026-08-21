import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {loadRuleCatalog, RuleCatalogError} from "../../src/enclosure-features/rules.ts";

const shippedCatalog = new URL(
  "../../../../../agent-utilities/skills/fusion-parametric-design/data/enclosure-feature-rules.json",
  import.meta.url,
);

function writeTemporaryCatalog(payload: unknown): string {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "enclosure-rules-"));
  const file = path.join(directory, "rules.json");
  fs.writeFileSync(file, JSON.stringify(payload));
  return file;
}

test("loads the shipped catalog in stable kind/id order", () => {
  // import.meta.url resolves through the tsx loader; decode it for fs.
  const catalogPath = path.resolve(decodeURIComponent(shippedCatalog.pathname));
  const catalog = loadRuleCatalog(catalogPath);
  assert.equal(catalog.schema_version, 1);
  assert.equal(catalog.entries.length, 7);
  assert.deepEqual(
    catalog.entries.map((entry) => [entry.kind, entry.rule_id]),
    [
      ["preset_parameter", "generic-fdm-fit-placeholder/design.wall_thickness_placeholder"],
      ["preset_parameter", "generic-fdm-fit-placeholder/fit.press_interference_placeholder"],
      ["preset_parameter", "generic-fdm-fit-placeholder/fit.sliding_clearance_placeholder"],
      ["preset_parameter", "generic-fdm-fit-placeholder/hardware.insert_bore_placeholder"],
      ["rule", "geometry.hex_corner_radius"],
      ["rule", "geometry.square_corner_radius"],
      ["rule", "process.fdm_layer_adhesion_anisotropy_warning"],
    ],
  );
});

test("numeric rule requires explicit units and full metadata", () => {
  const base = {
    classification: "material-datasheet", source_id: "datasheet",
    confidence: "high", safe_as_default: true, confirm_before_export: false,
    invalidated_by_material_change: false, invalidated_by_nozzle_change: false,
    invalidated_by_layer_height_change: false, invalidated_by_orientation_change: false,
    coupon_requirement: null,
  };
  const missingUnits = {value: 2, ...base};
  assert.throws(
    () => loadRuleCatalog(writeTemporaryCatalog({
      schema_version: 1, rules: [{rule_id: "x", ...missingUnits}], named_presets: [],
    })),
    RuleCatalogError,
  );
  const complete = {expression: "a+b", units: "mm", ...base};
  const loaded = loadRuleCatalog(writeTemporaryCatalog({
    schema_version: 1, rules: [{rule_id: "x", ...complete}], named_presets: [],
  }));
  assert.equal(loaded.entries.length, 1);
});

test("loader fails closed on schema drift and unknown evidence classes", () => {
  assert.throws(() => loadRuleCatalog("/definitely/not/a/catalog.json"), RuleCatalogError);
  const badSchema = {schema_version: 2, rules: [], named_presets: []};
  assert.throws(() => loadRuleCatalog(writeTemporaryCatalog(badSchema)), /schema_version must be 1/);
  const badEvidence = {
    schema_version: 1, named_presets: [], rules: [{
      rule_id: "x", expression: "y", units: "mm", classification: "vibes",
      source_id: "s", confidence: "c", safe_as_default: false,
      confirm_before_export: false, invalidated_by_material_change: false,
      invalidated_by_nozzle_change: false, invalidated_by_layer_height_change: false,
      invalidated_by_orientation_change: false, coupon_requirement: null,
    }],
  };
  assert.throws(() => loadRuleCatalog(writeTemporaryCatalog(badEvidence)), /evidence classification/);
});
