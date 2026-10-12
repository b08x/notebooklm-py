import { useSyncExternalStore } from "react";
import type { DeleteLevel, Filters, Mode } from "@/lib/types";
import type { Tab } from "./url";
import { fromUrl, toUrl } from "./url";

export type { Tab } from "./url";
export { TABS } from "./url";

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

/** Initial state from the address bar, so a deep link restores the view. */
function hydrate(state: AppState): AppState {
  if (typeof window === "undefined") return state;
  return { ...state, ...fromUrl(window.location) };
}

export const store = createStore<AppState>(hydrate(initial));

export function useApp<S>(selector: (s: AppState) => S): S {
  return useSyncExternalStore(store.subscribe, () => selector(store.get()), () => selector(store.get()));
}

export const resetStore = () => store.reset({ ...initial });

/** True while a popstate handler applies the URL, so the sync does not re-write it. */
let restoring = false;

function inApp(): boolean {
  return typeof window !== "undefined" && window.location.pathname.startsWith("/ui");
}

function currentUrl(): string {
  return window.location.pathname + window.location.search;
}

/** Push a new history entry for navigation (tab, open chunk); replace for the rest. */
function syncUrl(patch: Partial<AppState>, mode: "push" | "replace") {
  if (!inApp()) return;
  const url = toUrl({ ...store.get(), ...patch });
  if (currentUrl() === url) return;
  if (mode === "push") window.history.pushState(null, "", url);
  else window.history.replaceState(null, "", url);
}

if (typeof window !== "undefined") {
  // Filter, query and mode changes rewrite the current entry — typing must not
  // flood the history (pushState above already covered tab and chunk changes).
  store.subscribe(() => {
    if (restoring || !inApp()) return;
    const url = toUrl(store.get());
    if (currentUrl() !== url) window.history.replaceState(null, "", url);
  });
  window.addEventListener("popstate", () => {
    restoring = true;
    try {
      store.set(fromUrl(window.location));
    } finally {
      restoring = false;
    }
  });
}

export const actions = {
  setTab(tab: Tab) {
    syncUrl({ tab }, "push");
    store.set({ tab });
  },
  open(detailId: string | null) {
    syncUrl({ detailId }, detailId ? "push" : "replace");
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
