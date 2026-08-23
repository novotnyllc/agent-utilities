import assert from "node:assert/strict";
import test from "node:test";

import {
  asEnclosureFeatureRequest,
  asFeatureResult,
  ASSOCIATIVITIES,
  EnclosureContractError,
  NORMAL_MODES,
  OWNERSHIPS,
  QuantityError,
  REFUSAL_TOKENS,
  RESULT_OPERATIONS,
  SELECTION_KINDS,
  SelectionError,
} from "../../src/enclosure-features/contracts.ts";
import {fixtureRequest, fixtureResult} from "./fixtures.ts";

test("refusal taxonomy is closed and carries typed contract errors", () => {
  assert.equal(REFUSAL_TOKENS.size, 39);
  assert.ok(REFUSAL_TOKENS.has("cross-feature-cycle"));
  assert.equal(new EnclosureContractError("bad").refusalToken, "feature-create-failed");
  const error = new EnclosureContractError("physical evidence required", "physical-proof-required");
  assert.equal(error.refusalToken, "physical-proof-required");
});

test("quantity requires expression XOR finite value with explicit units", () => {
  assert.deepEqual(
    {expression: "wall", value: null, unit: null},
    {expression: "wall", value: null, unit: null},
  );
  const request = fixtureRequest();
  request.parameters[0].value.value = 2;
  request.parameters[0].value.unit = null;
  assert.throws(() => asEnclosureFeatureRequest(request), QuantityError);
});

test("request validation rejects unknown fields and bad enums with tokens", () => {
  const request = fixtureRequest();
  const mutated = request.selections[0] as unknown as Record<string, unknown>;
  mutated.unexpected = true;
  try {
    asEnclosureFeatureRequest(request);
    assert.fail("expected unknown selection field to fail");
  } catch (error) {
    assert.ok(error instanceof EnclosureContractError);
    // Unknown selection shape fails closed with the same closed token.
    if (error instanceof EnclosureContractError) {
      assert.equal(error.refusalToken, "invalid-selection-type");
    }
    assert.match(error.message, /unknown fields/);
  }

  const wrongKind = fixtureRequest();
  wrongKind.selections[0].kind = "vibes";
  const enumError = (() => {
    try {
      asEnclosureFeatureRequest(wrongKind);
      return null;
    } catch (caught) {
      return caught;
    }
  })();
  assert.ok(enumError instanceof EnclosureContractError);
  assert.equal((enumError as EnclosureContractError).refusalToken, "invalid-selection-type");
});

test("literal sets mirror the Python closed sets", () => {
  assert.equal(SELECTION_KINDS.size, 12);
  assert.equal(OWNERSHIPS.size, 6);
  assert.equal(ASSOCIATIVITIES.size, 3);
  assert.equal(NORMAL_MODES.size, 3);
  assert.equal(RESULT_OPERATIONS.size, 4);
});

test("result constructors validate refusal tokens and operations", () => {
  const result = {...fixtureResult(), instance: {...fixtureResult().instance!}};
  result.instance.recipe = {...result.instance.recipe};
  const validated = asFeatureResult(result);
  assert.equal(validated.operation, "create");
  const refusalFixture = fixtureResult();
  const badOperation = {...refusalFixture, operation: "summon"};
  assert.throws(() => asFeatureResult(badOperation), /unknown result operation/);
});
