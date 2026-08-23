/**
 * Acyclic managed-feature dependency policy.
 *
 * Fusion's own feature references remain authoritative; this graph is the pure
 * policy layer that refuses a managed cycle before any mutation happens and
 * answers whether a delete must refuse because managed dependents exist.
 */

export const LEGAL_EDGES: ReadonlyArray<readonly [string, string]> = [
  ["shared-axis-datum", "boss-pair"],
  ["port-cutout", "seam-interruption"],
  ["seam", "seal-path"],
  ["skirt-channel", "bump-snap-receiver"],
  ["boss-support", "reinforcement"],
  ["component-datum", "support-rest"],
  ["source-feature", "pattern-or-mirror"],
  ["rule-parameter", "fit-coupon"],
  ["coupon-result", "explicit-rule-override"],
] as const;

export class DependencyPolicyError extends Error {
  readonly refusalToken: string;

  constructor(message: string, refusalToken = "cross-feature-cycle") {
    super(message);
    this.name = "DependencyPolicyError";
    this.refusalToken = refusalToken;
  }
}

/** Concrete managed IDs carry their family as the prefix before ":". */
function edgeIsLegal(
  legalEdges: ReadonlyArray<readonly [string, string]>,
  upstream: string,
  downstream: string,
): boolean {
  return legalEdges.some(([legalUp, legalDown]) =>
    upstream.startsWith(`${legalUp}:`) && downstream.startsWith(`${legalDown}:`),
  );
}

export class DependencyGraph {
  readonly #legalEdges: ReadonlyArray<readonly [string, string]>;
  readonly #edges = new Map<string, Set<string>>();

  constructor(legalEdges: ReadonlyArray<readonly [string, string]> = LEGAL_EDGES) {
    this.#legalEdges = legalEdges;
  }

  addEdge(upstream: string, downstream: string): void {
    if (upstream === downstream) {
      throw new DependencyPolicyError(`self-dependency is illegal: ${upstream}`);
    }
    if (!edgeIsLegal(this.#legalEdges, upstream, downstream)) {
      throw new DependencyPolicyError(
        `illegal managed edge '${upstream}' -> '${downstream}'`,
      );
    }
    let downstreams = this.#edges.get(upstream);
    if (downstreams === undefined) {
      downstreams = new Set([downstream]);
      this.#edges.set(upstream, downstreams);
    } else {
      downstreams.add(downstream);
    }
    try {
      this.#detectCycle(upstream, downstream);
    } catch (error) {
      // Roll back the attempted edge so a refused add leaves no state behind.
      downstreams!.delete(downstream);
      if (downstreams!.size === 0) {
        this.#edges.delete(upstream);
      }
      throw error;
    }
  }

  #detectCycle(upstream: string, downstream: string): void {
    const stack = [downstream];
    const visited = new Set<string>();
    while (stack.length > 0) {
      const node = stack.pop()!;
      if (node === upstream) {
        throw new DependencyPolicyError(
          `adding '${upstream}' -> '${downstream}' would close a managed cycle`,
        );
      }
      if (visited.has(node)) {
        continue;
      }
      visited.add(node);
      stack.push(...this.#edges.get(node) ?? []);
    }
  }

  dependentsOf(featureId: string): Set<string> {
    const result = new Set<string>();
    for (const [upstream, downstreams] of this.#edges) {
      if (upstream === featureId) {
        for (const downstream of downstreams) {
          result.add(downstream);
        }
      }
    }
    return result;
  }

  /** Reverse dependency order starting from feature_id itself. */
  cascadeDelete(featureId: string): string[] {
    const order: string[] = [];
    const visited = new Set<string>();
    const visit = (node: string): void => {
      if (visited.has(node)) {
        return;
      }
      visited.add(node);
      for (const dependent of [...this.dependentsOf(node)].sort()) {
        visit(dependent);
      }
      order.push(node);
    };
    visit(featureId);
    return order;
  }
}
