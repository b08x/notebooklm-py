import type { ComponentType } from "react";
import { Activity, BookOpen, Map, Search, Settings, ShieldCheck, Table } from "lucide-react";
import type { Filters, Mode } from "@/lib/types";
import type { AppState } from "./store";

export type Tab = "review" | "search" | "browse" | "map" | "runs" | "factcheck" | "settings";

export interface TabConfig {
  id: Tab;
  label: string;
  icon: ComponentType<{ className?: string }>;
}

export const TABS: TabConfig[] = [
  { id: "review", label: "Review", icon: BookOpen },
  { id: "search", label: "Search", icon: Search },
  { id: "browse", label: "Browse", icon: Table },
  { id: "map", label: "Map", icon: Map },
  { id: "runs", label: "Runs", icon: Activity },
  { id: "factcheck", label: "Fact-check", icon: ShieldCheck },
  { id: "settings", label: "Settings", icon: Settings },
];

const MODES: Mode[] = ["keyword", "vector", "hybrid"];

/**
 * Serialize the URL-relevant part of the app state:
 * `/ui/<tab>?chunk=&q=&mode=&nb=&doc=&run=&strategy=&kind=&fact=&quality=&min=&max=&nd=&text=`
 */
export function toUrl(state: AppState): string {
  const p = new URLSearchParams();
  if (state.detailId) p.set("chunk", state.detailId);
  if (state.submittedQuery) p.set("q", state.submittedQuery);
  if (state.mode !== "hybrid") p.set("mode", state.mode);
  const f = state.filters;
  for (const nb of f.notebook_ids ?? []) p.append("nb", nb);
  for (const d of f.document_ids ?? []) p.append("doc", d);
  for (const r of f.run_ids ?? []) p.append("run", String(r));
  for (const s of f.strategies ?? []) p.append("strategy", s);
  for (const k of f.kinds ?? []) p.append("kind", k);
  for (const fc of f.fact_check ?? []) p.append("fact", fc);
  for (const q of f.quality ?? []) p.append("quality", q);
  if (f.min_len != null) p.set("min", String(f.min_len));
  if (f.max_len != null) p.set("max", String(f.max_len));
  if (f.has_near_duplicate) p.set("nd", "1");
  if (f.text) p.set("text", f.text);
  const qs = p.toString();
  return `/ui/${state.tab}${qs ? `?${qs}` : ""}`;
}

/** Parse a location into a state patch. Absent params reset to defaults. */
export function fromUrl(loc: { pathname: string; search: string }): Partial<AppState> {
  const seg = loc.pathname.replace(/^\/ui\/?/, "").split("/")[0];
  const tab = seg === "" ? "review" : TABS.find((t) => t.id === seg)?.id;
  const p = new URLSearchParams(loc.search);
  const filters: Filters = {};
  const nb = p.getAll("nb");
  const doc = p.getAll("doc");
  const run = p.getAll("run").map(Number).filter((n) => Number.isFinite(n));
  const strategy = p.getAll("strategy");
  const kind = p.getAll("kind");
  const fact = p.getAll("fact");
  const quality = p.getAll("quality");
  const min = p.get("min");
  const max = p.get("max");
  if (nb.length) filters.notebook_ids = nb;
  if (doc.length) filters.document_ids = doc;
  if (run.length) filters.run_ids = run;
  if (strategy.length) filters.strategies = strategy;
  if (kind.length) filters.kinds = kind;
  if (fact.length) filters.fact_check = fact;
  if (quality.length) filters.quality = quality;
  if (min != null && min !== "" && Number.isFinite(Number(min))) filters.min_len = Number(min);
  if (max != null && max !== "" && Number.isFinite(Number(max))) filters.max_len = Number(max);
  if (p.get("nd") === "1") filters.has_near_duplicate = true;
  const text = p.get("text");
  if (text) filters.text = text;
  const mode = p.get("mode");
  const q = p.get("q");
  return {
    ...(tab ? { tab } : {}),
    detailId: p.get("chunk"),
    query: q ?? "",
    submittedQuery: q ?? "",
    mode: mode && MODES.includes(mode as Mode) ? (mode as Mode) : "hybrid",
    filters,
  };
}
