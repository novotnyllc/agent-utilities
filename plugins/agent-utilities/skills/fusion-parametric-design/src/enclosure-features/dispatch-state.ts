/**
 * One-shot nonce mailbox semantics shared by host tests and dispatch design.
 *
 * Ephemeral process memory only: one staged request, one consumption,
 * bounded lifetime, no filesystem backing.
 */

import crypto from "node:crypto";

export class DispatchStateError extends Error {}

export class DispatchMailbox {
  readonly #ttlSeconds: number;
  #nonce: string | null = null;
  #payload: unknown = null;
  #stagedAtMonotonicMs = 0;
  #consumed = false;

  constructor(ttlSeconds = 60) {
    if (!(ttlSeconds > 0)) {
      throw new RangeError("mailbox ttl must be positive");
    }
    this.#ttlSeconds = ttlSeconds;
  }

  stage(payload: unknown): string {
    if (this.pending()) {
      throw new DispatchStateError("a request is already staged and has not been consumed");
    }
    this.#nonce = crypto.randomBytes(16).toString("hex");
    this.#payload = payload;
    this.#stagedAtMonotonicMs = performance.now();
    this.#consumed = false;
    return this.#nonce;
  }

  consume(nonce: string): unknown {
    if (this.#nonce === null) {
      throw new DispatchStateError("no request is staged");
    }
    if (!timingSafeEqual(nonce, this.#nonce)) {
      throw new DispatchStateError("nonce does not match the staged request");
    }
    if (this.#consumed) {
      throw new DispatchStateError("request was already consumed exactly once");
    }
    if (this.#expired()) {
      this.#nonce = null;
      this.#payload = null;
      throw new DispatchStateError("staged request expired before consumption");
    }
    this.#consumed = true;
    const payload = this.#payload;
    return payload;
  }

  complete(nonce: string, _result: unknown): void {
    if (
      this.#nonce === null
      || !timingSafeEqual(nonce, this.#nonce)
    ) {
      throw new DispatchStateError("nonce does not match the staged request");
    }
    if (!this.#consumed) {
      throw new DispatchStateError("complete requires the request to be consumed first");
    }
    this.#nonce = null;
    this.#payload = null;
  }

  pending(): boolean {
    return this.#nonce !== null && !this.#consumed && !this.#expired();
  }

  #expired(): boolean {
    return ((performance.now() - this.#stagedAtMonotonicMs) / 1000) > this.#ttlSeconds;
  }
}

function timingSafeEqual(left: string, right: string): boolean {
  const leftBytes = Buffer.from(left, "utf8");
  const rightBytes = Buffer.from(right, "utf8");
  return leftBytes.length === rightBytes.length && crypto.timingSafeEqual(leftBytes, rightBytes);
}
