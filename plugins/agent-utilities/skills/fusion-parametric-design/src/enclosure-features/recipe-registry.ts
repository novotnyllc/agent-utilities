/** Declarative recipe registry: the single dispatch source of truth. */

export const SUPPORTED_RECIPE = "supported-recipe";
export const SUPPORTED_SHARED_PRIMITIVE = "supported-shared-primitive";
export const SUPPORTED_NATIVE_API = "supported-native-api";
export const SUPPORTED_OPTIONAL_EXTENSION_API = "supported-optional-extension-api";
export const ORDINARY_PREFERRED = "ordinary-native-modeling-preferred";
export const REJECTED_BY_ARCHITECTURE = "rejected-by-architecture";
export const UNSUPPORTED_PUBLIC_API = "unsupported-public-api";

const CAPABILITIES: ReadonlySet<string> = new Set([
  SUPPORTED_RECIPE,
  SUPPORTED_SHARED_PRIMITIVE,
  SUPPORTED_NATIVE_API,
  SUPPORTED_OPTIONAL_EXTENSION_API,
  ORDINARY_PREFERRED,
  REJECTED_BY_ARCHITECTURE,
  UNSUPPORTED_PUBLIC_API,
]);

export interface RecipeEntry {
  readonly recipe_id: string;
  readonly version: string;
  readonly request_type: string;
  readonly capability: string;
}

function requestType(prefix: string): string {
  const mapping: Record<string, string> = {
    boss: "BossRequest",
    hardware: "HardwareFeatureRequest",
    seam: "SeamRequest",
    seal: "SealRequest",
    retention: "RetentionRequest",
    support: "SupportRequest",
    reinforcement: "ReinforcementRequest",
    cutout: "CutoutRequest",
    strain_relief: "StrainReliefRequest",
    vent: "VentRequest",
    coupon: "FitCouponRequest",
    operation: "OperationRequest",
    solid: "OperationRequest",
  };
  return mapping[prefix] ?? "EnclosureFeatureRequest";
}

const BOSS_VARIANTS = [
  "support", "screw", "heat_set_insert", "captive_square_nut",
  "captive_hex_nut", "thread_forming", "tapped", "pcb_standoff",
  "coordinated_pair", "compression",
] as const;

const HARDWARE_SUBTYPES = [
  "through_clearance", "counterbore", "countersink", "spot_face",
  "heat_set_insert", "square_nut", "hex_nut", "thread_forming_pilot",
  "tapped", "modeled_thread",
] as const;

const SEAM_VARIANTS = [
  "lip", "groove", "lip_groove", "tongue_groove", "skirt_channel",
  "labyrinth", "splash_overlap",
] as const;

const SEAL_TYPES = [
  "flat_gasket_channel", "gasket_land", "o_ring_groove",
  "perimeter_channel", "interrupted_channel", "compression_stop",
] as const;

const RETENTION_TYPES = [
  "cantilever_parallel", "cantilever_perpendicular", "cantilever_hidden",
  "skirt_bump", "annular", "annular_slotted", "fingered_ring", "press_ring",
  "interference_ring", "keyed_annular", "dovetail", "sliding_key", "bayonet",
] as const;

const SUPPORT_TYPES = [
  "pcb_edge", "pcb_corner", "support_point", "shelf", "landing_pad",
  "saddle", "cylindrical_cradle", "profile_ledge",
  "rest",
] as const;

const REINFORCEMENT_TYPES = [
  "straight_rib", "radial_boss_rib", "gusset", "triangular_web",
  "wall_floor_rib", "boss_wall_rib", "support_reinforcement",
] as const;

const CUTOUT_SHAPES = ["rectangle", "rounded_rectangle", "circle", "named_profile"] as const;

const STRAIN_RELIEF_FAMILIES = [
  "cable_exit_support", "clamp_saddle", "zip_tie_anchor",
  "zip_tie_slot_pair", "retention_bridge", "bend_radius_guide",
  "flexible_fingers", "channel_transition", "service_loop_retainer",
] as const;

const VENT_PATTERNS = ["linear_slots", "rectangular_holes", "circular_holes", "hexagonal"] as const;

const COUPON_TYPES = [
  "sliding_clearance", "press_fit", "pin_hole", "captive_nut",
  "heat_set_insert", "lip_groove", "snap_engagement", "dovetail",
  "connector_cutout",
] as const;

const OPERATIONS = [
  "pattern_rectangular", "pattern_circular", "pattern_path", "mirror",
  "edit_feature", "delete_feature", "inspect_feature", "record_coupon_result",
  "assign_fdm_rule", "extrude", "shell", "thicken", "draft",
] as const;

// Entries whose design-matrix classification differs from supported-recipe.
const CAPABILITY_OVERRIDES: Record<string, string> = {
  // Hardware shared primitives per matrix.
  "hardware.through_clearance": SUPPORTED_NATIVE_API,
  "hardware.tapped": SUPPORTED_NATIVE_API,
  // Analyzed rejections and ordinary-modeling preferences.
  "retention.bayonet": SUPPORTED_RECIPE, // scoped cylindrical bayonet stays a recipe
  "vent.hexagonal": SUPPORTED_RECIPE, // bounded planar region stays a recipe
};

function entries(
  prefix: string,
  variants: readonly string[],
): RecipeEntry[] {
  return variants.map((variant) => ({
    recipe_id: `${prefix}.${variant}`,
    version: "1.0.0",
    request_type: requestType(prefix),
    capability: CAPABILITY_OVERRIDES[`${prefix}.${variant}`] ?? SUPPORTED_RECIPE,
  }));
}

function buildRegistry(): ReadonlyMap<string, RecipeEntry> {
  const allEntries = [
    ...entries("boss", BOSS_VARIANTS),
    ...entries("hardware", HARDWARE_SUBTYPES),
    ...entries("seam", SEAM_VARIANTS),
    ...entries("seal", SEAL_TYPES),
    ...entries("retention", RETENTION_TYPES),
    ...entries("support", SUPPORT_TYPES),
    ...entries("reinforcement", REINFORCEMENT_TYPES),
    ...entries("cutout", CUTOUT_SHAPES),
    ...entries("strain_relief", STRAIN_RELIEF_FAMILIES),
    ...entries("vent", VENT_PATTERNS),
    ...entries("coupon", COUPON_TYPES),
    ...OPERATIONS.map((operation) => ({
      recipe_id: `operation.${operation}`,
      version: "1.0.0",
      request_type: requestType("operation"),
      capability: SUPPORTED_RECIPE,
    })),
  ];
  for (const entry of allEntries) {
    if (!CAPABILITIES.has(entry.capability)) {
      throw new Error(`unknown recipe capability: ${entry.capability}`);
    }
  }
  return new Map(allEntries.map((entry) => [entry.recipe_id, Object.freeze(entry)]));
}

export const REGISTRY: ReadonlyMap<string, RecipeEntry> = buildRegistry();

export function validateRecipeId(recipeId: string): RecipeEntry {
  const entry = REGISTRY.get(recipeId);
  if (entry === undefined) {
    throw new Error(`unknown recipe id: ${recipeId}`);
  }
  return entry;
}
