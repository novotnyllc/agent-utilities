/**
 * AgentUtilitiesEnclosure - standard Fusion add-in entrypoint.
 *
 * run(context) registers human commands; stop() removes them.  Startup must
 * succeed even if optional pieces are missing; failures are surfaced through
 * the Fusion UI when available.
 */

import { adsk } from "@adsk/fas";

import { registerCommands, unregisterCommands } from "./commands.ts";

export { runRequest } from "./commands.ts";

export function run(_context?: unknown): void {
  /** Register commands on Fusion startup. Must not crash if pieces are absent. */
  try {
    registerCommands(_context);
  } catch (exc) {
    try {
      const ui = adsk.core.Application.get().userInterface;
      ui.messageBox(`AgentUtilitiesEnclosure failed to start cleanly:\n${exc}`);
    } catch {
      // no Fusion UI available; startup still succeeds without crash
    }
  }
}

export function stop(_context?: unknown): void {
  /** Clean up registered commands on add-in shutdown. */
  try {
    unregisterCommands(_context);
  } catch {
    // Shutdown must never crash the host.
  }
}
