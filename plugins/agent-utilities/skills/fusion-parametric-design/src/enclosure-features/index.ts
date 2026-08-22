/** Public exports for the host-side enclosure feature toolkit. */

export * from "./contracts.ts";
export * from "./dependencies.ts";
export {DispatchMailbox, DispatchStateError} from "./dispatch-state.ts";
export {EVIDENCE_CLASSES, INVALIDATION_FLAGS} from "./evidence.ts";
export {
  ensureAddinInstalled,
  ensureAddinReady,
  installAddin,
  InstallerError,
  probeInstallStatus,
  probeAddInReadiness,
  ADDIN_NAME,
  ENV_OVERRIDE,
  type InstallStatus,
  type InstalledAddIn,
  type AddInReadiness,
} from "./installer.ts";
export {
  REGISTRY,
  validateRecipeId,
  SUPPORTED_RECIPE,
  SUPPORTED_SHARED_PRIMITIVE,
  SUPPORTED_NATIVE_API,
  SUPPORTED_OPTIONAL_EXTENSION_API,
  ORDINARY_PREFERRED,
  REJECTED_BY_ARCHITECTURE,
  UNSUPPORTED_PUBLIC_API,
  type RecipeEntry,
} from "./recipe-registry.ts";
export {loadRuleCatalog, RuleCatalogError, RULE_SCHEMA_VERSION, type Rule, type RuleCatalog} from "./rules.ts";
export {
  decodeRequest,
  decodeResult,
  encodeRequest,
  encodeResult,
  stableStringify,
  WireCodecError,
  WIRE_SCHEMA_VERSION,
} from "./request-codec.ts";
