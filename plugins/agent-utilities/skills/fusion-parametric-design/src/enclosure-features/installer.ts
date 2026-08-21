/**
 * Setup-only install and probe for the bundled AgentUtilitiesEnclosure add-in.
 *
 * Installation is an explicit user action; it is never triggered by a feature
 * request. The default-location probe documents Fusion's standard add-in
 * folders without naming any maintainer machine, and FUSION_ADDIN_DIR
 * overrides the search for users who keep their scripts elsewhere.
 */

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
