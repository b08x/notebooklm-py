/**
 * Layout breakpoints and named constants for Corpus Explorer responsive tiers.
 *
 * - 1400px: Inspector collapses into a right drawer below this width.
 * - 1024px: Document list collapses into a left drawer below this width.
 * - 768px:  Sidebar collapses into a left drawer below this width.
 * - 1280px: Default sidebar width switches to 64px (compact) when no stored choice exists.
 */

export const BP_INSPECTOR = 1400;
export const BP_LIST = 1024;
export const BP_SIDEBAR = 768;
export const BP_SIDEBAR_DEFAULT = 1280;

export type ViewportTier = "wide" | "medium" | "narrow" | "tiny";

export function getViewportTier(width: number): ViewportTier {
  if (width >= BP_INSPECTOR) return "wide";
  if (width >= BP_LIST) return "medium";
  if (width >= BP_SIDEBAR) return "narrow";
  return "tiny";
}
