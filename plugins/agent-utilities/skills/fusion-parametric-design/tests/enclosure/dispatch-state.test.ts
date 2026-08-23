import assert from "node:assert/strict";
import test from "node:test";

import {
  DispatchMailbox,
  DispatchStateError,
} from "../../src/enclosure-features/dispatch-state.ts";

test("stage nonce is 32 hex characters and pending until consumed", () => {
  const mailbox = new DispatchMailbox();
  const nonce = mailbox.stage({hello: "fusion"});
  assert.match(nonce, /^[0-9a-f]{32}$/);
  assert.equal(mailbox.pending(), true);
});

test("payload is returned exactly once and completion requires consumption", () => {
  const mailbox = new DispatchMailbox();
  const payload = {request_id: "req"};
  const nonce = mailbox.stage(payload);
  assert.deepEqual(mailbox.consume(nonce), payload);
  assert.equal(mailbox.pending(), false);
  assert.throws(() => mailbox.consume(nonce), DispatchStateError);
  const completed = new DispatchMailbox();
  const secondNonce = completed.stage(payload);
  assert.throws(
    () => completed.complete(secondNonce, {ok: true}),
    /complete requires the request to be consumed first/,
  );
  completed.consume(secondNonce);
  completed.complete(secondNonce, {ok: true});
  assert.equal(completed.pending(), false);
});

test("wrong nonce and expiry fail closed", async () => {
  const mailbox = new DispatchMailbox();
  const nonce = mailbox.stage("payload");
  assert.throws(() => mailbox.consume("wrong"), DispatchStateError);
  const expired = new DispatchMailbox(0.01);
  const expiredNonce = expired.stage("soon");
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.throws(() => expired.consume(expiredNonce), /expired before consumption/);
  assert.equal(expired.pending(), false);
  // The wrong-nonce check above must not have cleared the valid staged item.
  assert.equal(mailbox.pending(), true);
});

test("a pending request blocks staging until consumed or expired", () => {
  const mailbox = new DispatchMailbox();
  mailbox.stage("one");
  assert.throws(() => mailbox.stage("two"), /already staged/);
});
