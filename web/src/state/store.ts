import { useSyncExternalStore } from "react";
import type { DeleteLevel, Filters, Mode } from "@/lib/types";

export type Tab = "search" | "browse" | "map" | "runs" | "factcheck";
export const TABS: { id: Tab; label: string }[] = [
  { id: "search", label: "Search" },
  { id: "browse", label: "Browse" },
  { id: "map", label: "Map" },
  { id: "runs", label: "Runs" },
  { id: "factcheck", label: "Fact-check" },
];

export interface DeleteRequest {
  level: DeleteLevel;
  ids: string[];
  /** External ids of rows that disappear when this delete is confirmed. */
  hide: string[];
  label: string;
}

export interface FactCheckScope {
  notebook_id?: string;
  document_ids?: string[];
  run_ids?: number[];
  external_ids?: string[];
}

export interface AppState {
  tab: Tab;
  query: string;
  submittedQuery: string;
  mode: Mode;
  filters: Filters;
  selected: string[];
  /** Row the keyboard cursor is on (external id). */
  cursor: string | null;
  detailId: string | null;
  detailTab: "context" | "linguistics" | "similar" | "raw";
  deleteRequest: DeleteRequest | null;
  hidden: string[];
  askOpen: boolean;
  ingestOpen: boolean;
  paletteOpen: boolean;
  shortcutsOpen: boolean;
  factcheckScope: FactCheckScope | null;
  factcheckRunId: string | null;
}

const initial: AppState = {
  tab: "search",
  query: "",
  submittedQuery: "",
  mode: "hybrid",
  filters: {},
  selected: [],
  cursor: null,
  detailId: null,
  detailTab: "context",
  deleteRequest: null,
  hidden: [],
  askOpen: false,
  ingestOpen: false,
  paletteOpen: false,
  shortcutsOpen: false,
  factcheckScope: null,
  factcheckRunId: null,
};

type Listener = () => void;

export function createStore<T>(init: T) {
  let state = init;
  const listeners = new Set<Listener>();
  return {
    get: () => state,
    set(patch: Partial<T> | ((s: T) => Partial<T>)) {
      const next = typeof patch === "function" ? patch(state) : patch;
      state = { ...state, ...next };
      listeners.forEach((l) => l());
    },
    reset(value: T) {
      state = value;
      listeners.forEach((l) => l());
    },
    subscribe(l: Listener) {
      listeners.add(l);
      return () => listeners.delete(l);
    },
  };
}

export const store = createStore<AppState>(tabFromUrl(initial));

export function useApp<S>(selector: (s: AppState) => S): S {
  return useSyncExternalStore(store.subscribe, () => selector(store.get()), () => selector(store.get()));
}

export const resetStore = () => store.reset({ ...initial });

function tabFromUrl(state: AppState): AppState {
  if (typeof window === "undefined") return state;
  const seg = window.location.pathname.replace(/^\/ui\/?/, "").split("/")[0];
  const tab = TABS.find((t) => t.id === seg)?.id;
  return tab ? { ...state, tab } : state;
}

export const actions = {
  setTab(tab: Tab) {
    store.set({ tab });
    if (typeof window !== "undefined" && window.location.pathname.startsWith("/ui")) {
      window.history.replaceState(null, "", `/ui/${tab}`);
    }
  },
  open(detailId: string | null) {
    store.set({ detailId, cursor: detailId ?? store.get().cursor });
  },
  toggleSelect(id: string) {
    const sel = store.get().selected;
    store.set({ selected: sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id] });
  },
  selectRange(ids: string[], from: string, to: string) {
    const a = ids.indexOf(from);
    const b = ids.indexOf(to);
    if (a < 0 || b < 0) return;
    const range = ids.slice(Math.min(a, b), Math.max(a, b) + 1);
    store.set((s) => ({ selected: Array.from(new Set([...s.selected, ...range])) }));
  },
  clearSelection() {
    store.set({ selected: [] });
  },
  setFilters(patch: Partial<Filters>) {
    store.set((s) => ({ filters: { ...s.filters, ...patch } }));
  },
  requestDelete(req: DeleteRequest) {
    store.set({ deleteRequest: req });
  },
  /** Open a chunk where its detail pane is visible (the Fact-check screen has none). */
  reveal(detailId: string) {
    store.set({ detailId, cursor: detailId });
    if (store.get().tab === "factcheck") actions.setTab("browse");
  },
  startFactCheck(scope: FactCheckScope) {
    store.set({ factcheckScope: scope, factcheckRunId: null });
    actions.setTab("factcheck");
  },
};
