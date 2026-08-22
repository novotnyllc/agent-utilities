/** Shared recipe helpers: one canonical copy of guards and body collection. */
import { adsk } from "@adsk/fas";
import { AddInNotRunningError } from "../dispatch";

export type Refusal = [string, string, string];

export interface RecipeResult {
  created: unknown[];
  warnings: string[];
  refusal: Refusal | null;
}

export function requireAdsk(): void {
  if (!adsk || !adsk.core || !adsk.fusion) {
    throw new AddInNotRunningError("adsk not available.");
  }
}

export function featureBodies(feature: unknown): unknown[] {
  const coll = (feature as {bodies?: {count?: number; item?: (i: number) => unknown} | null})?.bodies;
  if (!coll || typeof coll.count !== "number") return [];
  const out: unknown[] = [];
  for (let i = 0; i < coll.count; i++) out.push(coll.item!(i));
  return out;
}
