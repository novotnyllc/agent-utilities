import assert from "node:assert/strict";
import test from "node:test";

import {
  DependencyGraph,
  DependencyPolicyError,
} from "../../src/enclosure-features/dependencies.ts";

test("accepts declared prefix families and rejects undeclared edges", () => {
  const graph = new DependencyGraph();
  graph.addEdge("seam:abc", "seal-path:def");
  assert.deepEqual([...graph.dependentsOf("seam:abc")], ["seal-path:def"]);
  try {
    graph.addEdge("seam:abc", "boss-pair:def");
    assert.fail("expected illegal edge");
  } catch (error) {
    assert.ok(error instanceof DependencyPolicyError);
    assert.equal(error.refusalToken, "cross-feature-cycle");
  }
});

test("cycle detection refuses and rolls back the attempted edge", () => {
  const graph = new DependencyGraph();
  graph.addEdge("seam:a", "seal-path:b");
  // The declared reverse family is absent, so this is an illegal edge first;
  // exercise the cycle detector with a legal family that can return upstream.
  const cycleGraph = new DependencyGraph([
    ["shared-axis-datum", "boss-pair"],
    ["boss-pair", "shared-axis-datum"],
  ]);
  cycleGraph.addEdge("shared-axis-datum:a", "boss-pair:b");
  try {
    cycleGraph.addEdge("boss-pair:b", "shared-axis-datum:a");
    assert.fail("expected cycle refusal");
  } catch (error) {
    assert.ok(error instanceof DependencyPolicyError);
    assert.match(error.message, /managed cycle/);
  }
  assert.deepEqual(cycleGraph.dependentsOf("shared-axis-datum:a"), new Set(["boss-pair:b"]));
  assert.deepEqual(graph.cascadeDelete("seam:a"), ["seal-path:b", "seam:a"]);
  assert.deepEqual(graph.dependentsOf("seam:a"), new Set(["seal-path:b"]));
});

test("cascade delete returns reverse dependency order with dependents first", () => {
  const graph = new DependencyGraph();
  graph.addEdge("seam:a", "seal-path:b");
  graph.addEdge("skirt-channel:c", "bump-snap-receiver:d");
  assert.deepEqual(graph.cascadeDelete("seam:a"), ["seal-path:b", "seam:a"]);
  assert.deepEqual(
    graph.cascadeDelete("skirt-channel:c"),
    ["bump-snap-receiver:d", "skirt-channel:c"],
  );
});
