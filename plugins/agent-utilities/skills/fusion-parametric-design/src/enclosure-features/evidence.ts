/** Closed evidence taxonomy for enclosure feature rules. */

export const EVIDENCE_CLASSES: ReadonlySet<string> = new Set([
  "geometric-invariant",
  "fusion-api-constraint",
  "manufacturer-specified",
  "standard-specified",
  "material-datasheet",
  "fdm-process-heuristic",
  "user-preference",
  "provisional-default",
  "coupon-verified",
  "physical-test-required",
]);

/**
 * The exact fabrication changes that stale a process-sensitive rule. A rule's
 * four boolean flags select from this set; the names are part of the contract.
 */
export const INVALIDATION_FLAGS = [
  "invalidated_by_material_change",
  "invalidated_by_nozzle_change",
  "invalidated_by_layer_height_change",
  "invalidated_by_orientation_change",
] as const;
