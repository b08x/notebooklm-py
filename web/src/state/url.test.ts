import { beforeEach, describe, expect, it } from "vitest";
import { actions, resetStore, store } from "./store";
import { fromUrl, toUrl } from "./url";

const popstate = () => window.dispatchEvent(new PopStateEvent("popstate"));

describe("url serialization (facts 25-27)", () => {
  beforeEach(() => {
    resetStore();
    window.history.replaceState(null, "", "/ui/review");
  });

  it("round-trips tab, chunk, query, mode and every filter", () => {
    const state = {
      ...store.get(),
      tab: "browse" as const,
      query: "typed but not submitted",
      submittedQuery: "kernel panic",
      mode: "vector" as const,
      detailId: "doc:1:2",
      filters: {
        notebook_ids: ["nb-1", "nb-2"],
        document_ids: ["doc-a"],
        run_ids: [3, 7],
        strategies: ["recursive"],
        kinds: ["source"],
        fact_check: ["failed"],
        quality: ["clean"],
        min_len: 10,
        max_len: 400,
        has_near_duplicate: true,
      },
    };
    const url = toUrl(state);
    expect(url).toContain("/ui/browse?");
    expect(url).toContain("chunk=doc%3A1%3A2");
    const restored = { ...store.get(), ...fromUrl(new URL(url, "http://localhost")) };
    expect(toUrl(restored)).toBe(url);
    expect(restored.tab).toBe("browse");
    expect(restored.detailId).toBe("doc:1:2");
    expect(restored.submittedQuery).toBe("kernel panic");
    expect(restored.mode).toBe("vector");
    expect(restored.filters).toEqual(state.filters);
  });

  it("round-trips review screen with doc and chunk", () => {
    const state = {
      ...store.get(),
      tab: "review" as const,
      detailId: "clause-42",
      filters: {
        document_ids: ["doc-123"],
      },
    };
    const url = toUrl(state);
    expect(url).toBe("/ui/review?chunk=clause-42&doc=doc-123");
    const restored = { ...store.get(), ...fromUrl(new URL(url, "http://localhost")) };
    expect(restored.tab).toBe("review");
    expect(restored.detailId).toBe("clause-42");
    expect(restored.filters.document_ids).toEqual(["doc-123"]);
  });

  it("drops default values from the url", () => {
    expect(toUrl(store.get())).toBe("/ui/review");
  });

  it("fromUrl resets absent params to defaults", () => {
    const patch = fromUrl({ pathname: "/ui/map", search: "" });
    const merged = { ...store.get(), ...patch };
    expect(merged.tab).toBe("map");
    expect(merged.detailId).toBeNull();
    expect(merged.query).toBe("");
    expect(merged.mode).toBe("hybrid");
    expect(merged.filters).toEqual({});
  });

  it("ignores unknown tabs and modes", () => {
    const merged = { ...store.get(), ...fromUrl({ pathname: "/ui/nope", search: "?mode=nope" }) };
    expect(merged.tab).toBe("review");
    expect(merged.mode).toBe("hybrid");
  });
});

describe("history sync (facts 25-26)", () => {
  beforeEach(() => {
    resetStore();
    window.history.replaceState(null, "", "/ui/search");
  });

  it("setTab and open push history entries; filter changes replace", () => {
    const len = window.history.length;
    actions.setTab("browse");
    expect(window.location.pathname).toBe("/ui/browse");
    expect(window.history.length).toBe(len + 1);
    actions.open("doc:1:2");
    expect(window.location.search).toContain("chunk=doc%3A1%3A2");
    expect(window.history.length).toBe(len + 2);

    // A filter change rewrites the current entry instead of adding one.
    actions.setFilters({ notebook_ids: ["nb-1"] });
    expect(window.location.search).toContain("nb=nb-1");
    expect(window.history.length).toBe(len + 2);

    // Closing the chunk also replaces (no entry for the closed state).
    actions.open(null);
    expect(window.location.search).not.toContain("chunk=");
    expect(window.history.length).toBe(len + 2);
  });

  it("popstate restores the url's tab, chunk and filters", () => {
    actions.setTab("map");
    expect(store.get().tab).toBe("map");

    // Simulate Back to the browse entry with the chunk open.
    window.history.pushState(null, "", "/ui/browse?chunk=doc%3A1%3A2&nb=nb-1");
    popstate();
    expect(store.get().tab).toBe("browse");
    expect(store.get().detailId).toBe("doc:1:2");
    expect(store.get().filters.notebook_ids).toEqual(["nb-1"]);
    // The restoring flag kept the handler from re-writing the entry.
    expect(window.location.pathname + window.location.search).toBe("/ui/browse?chunk=doc%3A1%3A2&nb=nb-1");

    // Back again: same tab, chunk closed, filters gone.
    window.history.pushState(null, "", "/ui/browse");
    popstate();
    expect(store.get().tab).toBe("browse");
    expect(store.get().detailId).toBeNull();
    expect(store.get().filters).toEqual({});
  });

  it("a deep link hydrates the store on load", () => {
    window.history.replaceState(null, "", "/ui/runs?q=kernel&mode=keyword&doc=doc-a&doc=doc-b&run=2");
    const merged = { ...store.get(), ...fromUrl(window.location) };
    expect(merged.tab).toBe("runs");
    expect(merged.query).toBe("kernel");
    expect(merged.submittedQuery).toBe("kernel");
    expect(merged.mode).toBe("keyword");
    expect(merged.filters.document_ids).toEqual(["doc-a", "doc-b"]);
    expect(merged.filters.run_ids).toEqual([2]);
  });
});
