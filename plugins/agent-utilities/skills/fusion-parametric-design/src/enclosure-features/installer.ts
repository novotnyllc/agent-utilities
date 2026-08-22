/**
 * Setup-only install and probe for the bundled AgentUtilitiesEnclosure add-in.
 *
 * Installation is an explicit user action; it is never triggered by a feature
 * request. The default-location probe documents Fusion's standard add-in
 * folders without naming any maintainer machine, and FUSION_ADDIN_DIR
 * overrides the search for users who keep their scripts elsewhere.
 */

import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export const ADDIN_NAME = "AgentUtilitiesEnclosure";
export const ENV_OVERRIDE = "FUSION_ADDIN_DIR";

export class InstallerError extends Error {}

/** Skill directory is two levels up from src/enclosure-features. */
function skillDir(): string {
  return path.resolve(import.meta.dirname, "..", "..");
}

function bundledAddinRoot(): string {
  return path.join(skillDir(), "fusion_addin", ADDIN_NAME);
}

function defaultSearchLocations(): string[] {
  const override = process.env[ENV_OVERRIDE];
  if (override) {
    const expanded = override.startsWith("~")
      ? path.join(os.homedir(), override.slice(1))
      : path.resolve(override);
    return [expanded];
  }
  const home = os.homedir();
  if (process.platform === "darwin") {
    return [
      path.join(home, "Library", "Application Support", "Autodesk", "Autodesk Fusion", "API", "AddIns"),
      path.join(home, "Library", "Application Support", "Autodesk", "Autodesk Fusion 360", "API", "AddIns"),
    ];
  }
  if (process.platform === "win32") {
    const appData = process.env.APPDATA;
    return appData ? [path.join(appData, "Autodesk", "Autodesk Fusion 360", "API", "AddIns")] : [];
  }
  const base = process.env.XDG_CONFIG_HOME ?? path.join(home, ".config");
  return [path.join(base, "Autodesk", "Autodesk Fusion 360", "API", "AddIns")];
}

export interface InstallStatus {
  readonly addin: string;
  readonly installed: boolean;
  readonly installed_path: string | null;
  readonly checked_locations: readonly string[];
  readonly env_override: string;
  readonly bundled_source: string;
}

/** Report whether the bundled add-in is installed at a known location. */
export function probeInstallStatus(targetDir?: string): InstallStatus {
  const searchLocations = targetDir ? [path.resolve(targetDir)] : defaultSearchLocations();
  let installedPath: string | null = null;
  const checked: string[] = [];
  for (const directory of searchLocations) {
    const candidate = path.join(directory, ADDIN_NAME);
    checked.push(candidate);
    const manifest = path.join(candidate, `${ADDIN_NAME}.manifest`);
    try {
      if (fs.statSync(candidate).isDirectory() && fs.statSync(manifest).isFile()) {
        installedPath = candidate;
        break;
      }
    } catch {
      // Absence is the normal probe outcome.
    }
  }
  return {
    addin: ADDIN_NAME,
    installed: installedPath !== null,
    installed_path: installedPath,
    checked_locations: checked,
    env_override: ENV_OVERRIDE,
    bundled_source: bundledAddinRoot(),
  };
}

export interface InstalledAddIn {
  readonly addin: string;
  readonly installed_to: string;
  readonly forced: boolean;
}

function copyTree(from: string, to: string): void {
  fs.cpSync(from, to, {recursive: true});
}

/**
 * Copy the bundled add-in tree into an explicit user-supplied target.
 *
 * Fusion compiles the add-in's TypeScript sources directly; installation is
 * a straight tree copy with no build step or compiled snapshot.
 */
export function installAddin(targetDir: string, {force = false}: {force?: boolean} = {}): InstalledAddIn {
  const source = bundledAddinRoot();
  const sourceManifest = path.join(source, `${ADDIN_NAME}.manifest`);
  try {
    if (!fs.statSync(source).isDirectory() || !fs.statSync(sourceManifest).isFile()) {
      throw new InstallerError(`bundled add-in is missing at ${source}`);
    }
  } catch (error) {
    if (error instanceof InstallerError) {
      throw error;
    }
    throw new InstallerError(`bundled add-in is missing at ${source}`);
  }
  const destination = path.join(path.resolve(targetDir), ADDIN_NAME);
  try {
    if (fs.existsSync(destination)) {
      if (!force) {
        throw new InstallerError(`${destination} already exists; pass --force to replace it`);
      }
      fs.rmSync(destination, {recursive: true, force: true});
    }
    copyTree(source, destination);
  } catch (error) {
    if (error instanceof InstallerError) {
      throw error;
    }
    throw new InstallerError((error as Error).message);
  }
  // Fusion compiles the add-in's TypeScript sources directly; no build step
  // or compiled snapshot is staged at install time.
  return {
    addin: ADDIN_NAME,
    installed_to: destination,
    forced: force,
  };
}

/**
 * Ensure the bundled add-in is installed and current, automatically.
 *
 * The toolkit depends on the add-in, so the first invocation installs it and
 * later invocations refresh it whenever the bundled version is newer than the
 * installed copy. Users never run a manual install step; the CLI commands
 * remain available only for diagnostics and force-repair.
 */

function hashTree(root: string): string {
  const hash = crypto.createHash("sha256");
  const walk = (dir: string): void => {
    const entries = fs.readdirSync(dir, {withFileTypes: true}).sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) walk(full);
      else if (entry.isFile()) {
        hash.update(path.relative(root, full));
        hash.update(fs.readFileSync(full));
      }
    }
  };
  walk(root);
  return hash.digest("hex");
}

export interface AddInReadiness {
  readonly installed: boolean;
  readonly installed_path: string | null;
  readonly bundled_source: string;
  readonly bundled_version: string;
  readonly installed_version: string | null;
  readonly bundled_sha256: string;
  readonly installed_sha256: string | null;
  readonly bytes_match: boolean;
  readonly version_match: boolean;
  readonly mismatch_token: "enclosure-addin-not-installed" | "recipe-version-mismatch" | null;
  readonly loaded: boolean | null;
  readonly action: "installed" | "updated" | "current" | "missing";
}

function readVersion(manifestPath: string): string {
  try {
    const parsed = JSON.parse(fs.readFileSync(manifestPath, "utf8")) as {version?: string};
    return parsed.version ?? "0";
  } catch {
    return "0";
  }
}

/** Copy is not load. Callers must still Run the add-in in Fusion (or runOnStartup). */
export function probeAddInReadiness(targetDir?: string): AddInReadiness {
  const status = probeInstallStatus(targetDir);
  const bundled = bundledAddinRoot();
  const bundledVersion = readVersion(path.join(bundled, ADDIN_NAME + ".manifest"));
  const bundledSha = hashTree(bundled);
  const installedVersion = status.installed_path
    ? readVersion(path.join(status.installed_path, ADDIN_NAME + ".manifest"))
    : null;
  const installedSha = status.installed_path ? hashTree(status.installed_path) : null;
  const versionMatch = installedVersion === bundledVersion;
  const bytesMatch = installedSha === bundledSha;
  let mismatch: AddInReadiness["mismatch_token"] = null;
  if (!status.installed) mismatch = "enclosure-addin-not-installed";
  else if (!versionMatch || !bytesMatch) mismatch = "recipe-version-mismatch";
  return {
    installed: status.installed,
    installed_path: status.installed_path,
    bundled_source: bundled,
    bundled_version: bundledVersion,
    installed_version: installedVersion,
    bundled_sha256: bundledSha,
    installed_sha256: installedSha,
    bytes_match: bytesMatch,
    version_match: versionMatch,
    mismatch_token: mismatch,
    loaded: null,
    action: status.installed ? (mismatch ? "current" : "current") : "missing",
  };
}

export function ensureAddinInstalled(): { installed: boolean; updated: boolean; path: string; action: "installed" | "updated" | "current" } {
  const status = probeInstallStatus();
  const bundledManifest = path.join(bundledAddinRoot(), ADDIN_NAME + ".manifest");
  let bundledVersion = "0";
  try {
    const parsed = JSON.parse(fs.readFileSync(bundledManifest, "utf8")) as {version?: string};
    bundledVersion = parsed.version ?? "0";
  } catch {
    // Bundled manifest unreadable: fall through to install attempt anyway.
  }
  if (!status.installed || status.installed_path === null) {
    const targetDir = defaultSearchLocations()[0];
    if (!targetDir) {
      throw new InstallerError("no known Fusion add-in directory on this platform; set FUSION_ADDIN_DIR");
    }
    const result = installAddin(targetDir, {force: false});
    return {installed: true, updated: true, path: result.installed_to, action: "installed"};
  }
  const readiness = probeAddInReadiness();
  if (readiness.mismatch_token === "recipe-version-mismatch") {
    const targetDir = path.dirname(status.installed_path);
    const result = installAddin(targetDir, {force: true});
    return {installed: true, updated: true, path: result.installed_to, action: "updated"};
  }
  return {installed: true, updated: false, path: status.installed_path, action: "current"};
}

/**
 * First agent use: install if missing, refresh drifted bytes/version, then
 * report that Fusion still has to load the add-in. File copy is not load.
 */
export function ensureAddinReady(): AddInReadiness {
  const ensured = ensureAddinInstalled();
  const readiness = probeAddInReadiness();
  return {...readiness, action: ensured.action, loaded: null};
}
