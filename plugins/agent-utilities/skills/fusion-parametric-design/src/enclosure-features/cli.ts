#!/usr/bin/env -S npx tsx
/** Explicit status/install entry point for the bundled Fusion add-in. */

import process from "node:process";

import {ensureAddinInstalled, installAddin, InstallerError, probeInstallStatus} from "./installer.ts";

function usage(program: string): never {
  console.error(`Usage: ${program} <status [--target DIR] | install --target DIR [--force]>`);
  process.exit(2);
}

function main(argv: readonly string[]): void {
  const [command = "", ...rest] = argv;
  const program = "npx tsx src/enclosure-features/cli.ts";
  let target: string | undefined;
  let force = false;
  for (let index = 0; index < rest.length; index += 1) {
    const argument = rest[index];
    if (argument === "--target") {
      target = rest[++index];
      if (!target) {
        usage(program);
      }
    } else if (argument === "--force") {
      force = true;
    } else {
      usage(program);
    }
  }
  try {
    if (command === "status") {
      // Auto-install/update before every probe: first use installs, drift refreshes.
      const ensured = ensureAddinInstalled();
      console.log(JSON.stringify({ensured, ...probeInstallStatus(target)}, null, 2));
    } else if (command === "install") {
      if (!target) {
        console.error("install requires an explicit --target directory");
        process.exit(2);
      }
      console.log(JSON.stringify(installAddin(target, {force}), null, 2));
    } else {
      usage(program);
    }
  } catch (error) {
    if (error instanceof InstallerError || error instanceof RangeError) {
      console.error(error.message);
      process.exit(2);
    }
    throw error;
  }
}

main(process.argv.slice(2));
