import assert from "node:assert/strict";
import test from "node:test";

import {
  decodeRequest,
  decodeResult,
  encodeRequest,
  encodeResult,
  WireCodecError,
} from "../../src/enclosure-features/request-codec.ts";
import {fixtureRequest, fixtureResult} from "./fixtures.ts";

test("request JSON round trip is exact and deterministic", () => {
  const request = fixtureRequest();
  const first = encodeRequest(request);
  const second = encodeRequest(request);
  assert.equal(first, second);
  assert.deepEqual(decodeRequest(first), request);
});

test("result JSON round trip preserves refusal and observations", () => {
  const result = fixtureResult();
  const encoded = encodeResult(result);
  assert.match(encoded, /"schema_version":1/);
  assert.deepEqual(decodeResult(encoded), result);
});

test("unknown fields and schema versions are rejected", () => {
  const request = fixtureRequest() as Record<string, unknown>;
  request.extra = true;
  const encodedBadRequest = encodeRequest(fixtureRequest()).replace("{", "{\"extra\":true,");
  assert.throws(() => decodeRequest(encodedBadRequest), WireCodecError);
  assert.throws(() => decodeRequest("{}"), /schema_version must be 1/);
  const encodedBadResult = encodeResult(fixtureResult()).replace("{", "{\"extra\":true,");
  assert.throws(() => decodeResult(encodedBadResult), /has unknown fields/);
});

test("invalid JSON is wrapped as a wire error", () => {
  assert.throws(() => decodeRequest("{nope"), /not valid JSON/);
});
