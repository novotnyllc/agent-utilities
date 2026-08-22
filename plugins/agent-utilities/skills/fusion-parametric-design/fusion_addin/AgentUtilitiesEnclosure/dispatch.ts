/**
 * Process-local one-shot request mailbox for the Fusion add-in.
 *
 * Ephemeral memory only -- no filesystem backing.  stage() returns a random
 * nonce; consume() returns the request exactly once; storeResult() records
 * the result for the dispatcher to collect.  Entries expire after a bounded
 * lifetime.
 */

export type MailboxEntry = {
  request_json: string;
  consumed: boolean;
  result: unknown;
  result_ready: boolean;
  _staged_at: number; // monotonic milliseconds, like time.monotonic()
};

const _MAX_LIFETIME_SECONDS = 300.0;

const _mailbox = new Map<string, MailboxEntry>();

let _lastConsumedNonce: string | null = null;

let _lastMonotonic = performance.now();

/** Monotonic clock: never goes backwards within this process. */
function monotonicMs(): number {
  const now = performance.now();
  if (now > _lastMonotonic) {
    _lastMonotonic = now;
  }
  return _lastMonotonic;
}

function nonce8(nonce: string): string {
  return nonce.slice(0, 8);
}

export class AddInNotRunningError extends Error {}
export class DispatchError extends Error {}

export function prune(): void {
  const now = monotonicMs();
  for (const [k, v] of _mailbox) {
    if (now - v._staged_at > _MAX_LIFETIME_SECONDS * 1000) {
      _mailbox.delete(k);
    }
  }
}

export function stage(requestJson: string): string {
  JSON.parse(requestJson); // throws on invalid input, like json.loads
  prune();
  const nonce = crypto.randomUUID().replace(/-/g, "");
  _mailbox.set(nonce, {
    request_json: requestJson,
    consumed: false,
    result: null,
    result_ready: false,
    _staged_at: monotonicMs(),
  });
  return nonce;
}

export function consume(nonce: string): string | null {
  prune();
  const entry = _mailbox.get(nonce);
  if (entry === undefined) {
    throw new DispatchError(`Unknown or expired nonce: ${nonce8(nonce)}`);
  }
  if (entry.consumed) {
    return null;
  }
  entry.consumed = true;
  _lastConsumedNonce = nonce;
  return entry.request_json;
}

/** Consume the first staged request, or the supplied nonce when a command
 * definition carries the hidden dispatch_nonce input. */
export function consumePending(nonce?: string): string | null {
  prune();
  if (nonce) return consume(nonce);
  for (const [candidate, entry] of _mailbox) {
    if (!entry.consumed) return consume(candidate);
  }
  _lastConsumedNonce = null;
  return null;
}

/** Nonce associated with the most recent consume/consumePending call. */
export function lastConsumedNonce(): string | null {
  return _lastConsumedNonce;
}

export function storeResult(nonce: string, result: unknown): void {
  const entry = _mailbox.get(nonce);
  if (entry === undefined) {
    throw new DispatchError(`Unknown nonce: ${nonce8(nonce)}`);
  }
  if (!entry.consumed) {
    throw new DispatchError("Cannot store result before consume().");
  }
  if (entry.result_ready) {
    throw new DispatchError("Result already stored for this nonce.");
  }
  entry.result = result;
  entry.result_ready = true;
}

export function peekResult(nonce: string): unknown {
  const entry = _mailbox.get(nonce);
  if (entry === undefined || !entry.result_ready) {
    return null;
  }
  return entry.result;
}

export function collectResult(nonce: string): unknown {
  const entry = _mailbox.get(nonce);
  _mailbox.delete(nonce);
  if (entry === undefined || !entry.result_ready) {
    throw new DispatchError(`No result for nonce: ${nonce8(nonce)}`);
  }
  return entry.result;
}

/** Lifecycle state of one nonce so a retrying dispatcher can distinguish
 * staged / consumed-but-running / completed instead of guessing from null. */
export function entryStatus(nonce: string): "staged" | "consumed" | "completed" | "unknown" {
  prune();
  const entry = _mailbox.get(nonce);
  if (entry === undefined) return "unknown";
  if (entry["result_ready"] === true) return "completed";
  if (entry["consumed"] === true) return "consumed";
  return "staged";
}

/** Explicit cleanup for dead requests (agent crash recovery). */
export function discard(nonce: string): boolean {
  return _mailbox.delete(nonce);
}

export function pendingNonce(): string | null {
  prune();
  for (const [nonce, entry] of _mailbox) {
    if (!entry.consumed) return nonce;
  }
  return null;
}
