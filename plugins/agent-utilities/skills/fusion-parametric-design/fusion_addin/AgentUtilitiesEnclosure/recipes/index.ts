/**
 * Recipe registry: family name -> execute function.
 */

import { executeBossRecipe } from "./boss";
import { executeCouponRecipe, recordCouponResult } from "./coupon";
import { executeCutoutRecipe } from "./cutout";
import { executeReinforcementRecipe } from "./reinforcement";
import { executeRetentionRecipe } from "./retention";
import { executeSeamRecipe } from "./seam";
import { executeSealRecipe } from "./seal";
import { executeStrainReliefRecipe } from "./strain_relief";
import { executeSupportRecipe } from "./support";
import { executeVentRecipe } from "./vent";
import { executeSolidRecipe } from "./solid";

export { executeBossRecipe } from "./boss";
export { executeCouponRecipe, recordCouponResult } from "./coupon";
export { executeCutoutRecipe } from "./cutout";
export { executeReinforcementRecipe } from "./reinforcement";
export { executeRetentionRecipe } from "./retention";
export { executeSeamRecipe } from "./seam";
export { executeSealRecipe } from "./seal";
export { executeStrainReliefRecipe } from "./strain_relief";
export { executeSupportRecipe } from "./support";
export { executeVentRecipe } from "./vent";
export { executeSolidRecipe } from "./solid";

export type RecipeExecute = (
  component: any,
  identity: any,
  request: Record<string, any>,
) => { created: unknown[]; warnings: string[]; refusal: [string, string, string] | null };

/**
 * All ten recipe families: boss, coupon, cutout, reinforcement, retention,
 * seam, seal, strain_relief, support, vent.
 */
export const RECIPES: Record<string, RecipeExecute> = {
  boss: executeBossRecipe,
  coupon: executeCouponRecipe,
  cutout: executeCutoutRecipe,
  reinforcement: executeReinforcementRecipe,
  retention: executeRetentionRecipe,
  seam: executeSeamRecipe,
  seal: executeSealRecipe,
  strain_relief: executeStrainReliefRecipe,
  support: executeSupportRecipe,
  vent: executeVentRecipe,
  solid: executeSolidRecipe,
};
