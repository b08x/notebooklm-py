import { useEffect, useState } from "react";
import { BP_INSPECTOR, BP_LIST, BP_SIDEBAR, type ViewportTier } from "@/lib/layout";

export function useViewportTier(): ViewportTier {
  const [tier, setTier] = useState<ViewportTier>(() => {
    if (typeof window === "undefined") return "wide";
    const w = window.innerWidth;
    if (w >= BP_INSPECTOR) return "wide";
    if (w >= BP_LIST) return "medium";
    if (w >= BP_SIDEBAR) return "narrow";
    return "tiny";
  });

  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;

    const mqWide = window.matchMedia(`(min-width: ${BP_INSPECTOR}px)`);
    const mqMedium = window.matchMedia(`(min-width: ${BP_LIST}px)`);
    const mqNarrow = window.matchMedia(`(min-width: ${BP_SIDEBAR}px)`);

    const update = () => {
      if (mqWide.matches) setTier("wide");
      else if (mqMedium.matches) setTier("medium");
      else if (mqNarrow.matches) setTier("narrow");
      else setTier("tiny");
    };

    update();

    mqWide.addEventListener?.("change", update);
    mqMedium.addEventListener?.("change", update);
    mqNarrow.addEventListener?.("change", update);

    return () => {
      mqWide.removeEventListener?.("change", update);
      mqMedium.removeEventListener?.("change", update);
      mqNarrow.removeEventListener?.("change", update);
    };
  }, []);

  return tier;
}
