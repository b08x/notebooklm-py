import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithClient, row } from "@/test/utils";
import { store } from "@/state/store";
import { Breadcrumbs } from "./Breadcrumbs";

const NB = "11111111-2222-3333-4444-555555555555";

const detail = {
  ...row({ notebook_id: NB, document_id: "doc-a", title: "Audio transcript" }),
  parent: null,
  n_parents: 2,
  context: { before: [], after: [] },
  entities: [],
  sfl: null,
  sfl_raw: null,
  tokens: [],
  groups: {},
  topic: null,
  latest_fact_check: null,
  run: null,
  created_at: null,
};

const FACETS = {
  notebook: [{ value: NB, count: 42 }],
  document: [{ value: "doc-a", count: 40 }],
  run: [],
  strategy: [],
  kind: [],
  fact_check: [],
  quality: [],
  length: [],
  labels: { document: { "doc-a": "Audio transcript" } },
};

const routes = {
  "GET /v1/corpus/chunks/doc:1:0": detail,
  "GET /v1/corpus/notebooks": { items: [{ id: NB, title: "Field Notes", chunks: 42, documents: 1 }] },
  "GET /v1/corpus/facets": FACETS,
};

describe("Breadcrumbs (facts 25-27)", () => {
  it("renders nothing without a chunk or a single-valued filter", () => {
    mockFetch(routes);
    renderWithClient(<Breadcrumbs />);
    expect(screen.queryByTestId("breadcrumb")).toBeNull();
  });

  it("shows Tab › Notebook › Document › Chunk with titles, never a UUID (facts 3-5)", async () => {
    mockFetch(routes);
    renderWithClient(<Breadcrumbs />);
    store.set({ tab: "search", detailId: "doc:1:0" });
    // The titles arrive from /notebooks and the chunk detail — wait for them.
    expect(await screen.findByText("Field Notes")).toBeInTheDocument();
    expect(screen.getByTestId("crumb-tab")).toHaveTextContent("Search");
    expect(screen.getByTestId("crumb-notebook")).toHaveTextContent("Field Notes");
    expect(screen.getByTestId("crumb-document")).toHaveTextContent("Audio transcript");
    expect(screen.getByTestId("crumb-chunk")).toHaveTextContent("1:0");
    expect(document.body.textContent).not.toContain(NB);
  });

  it("shows Collection › Document › Chunk without tab on review screen (fact 53)", async () => {
    mockFetch(routes);
    renderWithClient(<Breadcrumbs />);
    store.set({ tab: "review", detailId: "doc:1:0" });
    expect(await screen.findByText("Field Notes")).toBeInTheDocument();
    expect(screen.queryByTestId("crumb-tab")).toBeNull();
    expect(screen.getByTestId("crumb-notebook")).toHaveTextContent("Field Notes");
    expect(screen.getByTestId("crumb-document")).toHaveTextContent("Audio transcript");
    expect(screen.getByTestId("crumb-chunk")).toHaveTextContent("1:0");
  });

  it("falls back to single-valued filters when no chunk is open", async () => {
    mockFetch(routes);
    renderWithClient(<Breadcrumbs />);
    store.set({ filters: { notebook_ids: [NB], document_ids: ["doc-a"] } });
    expect(await screen.findByText("Field Notes")).toBeInTheDocument();
    expect(screen.getByTestId("crumb-document")).toHaveTextContent("Audio transcript");
    expect(screen.queryByTestId("crumb-chunk")).toBeNull();
  });

  it("clicking a segment narrows and closes the chunk", async () => {
    mockFetch(routes);
    renderWithClient(<Breadcrumbs />);
    store.set({ tab: "search", detailId: "doc:1:0", filters: { run_ids: [2] } });
    await screen.findByText("Field Notes");

    // Notebook narrows to just that notebook and closes the chunk.
    await userEvent.click(screen.getByTestId("crumb-notebook"));
    expect(store.get().detailId).toBeNull();
    expect(store.get().filters).toEqual({ notebook_ids: [NB] });

    // Document keeps the other filters and closes the chunk.
    store.set({ tab: "search", detailId: "doc:1:0", filters: { notebook_ids: [NB], document_ids: ["doc-a"] } });
    await screen.findByTestId("crumb-chunk");
    await userEvent.click(screen.getByTestId("crumb-document"));
    expect(store.get().detailId).toBeNull();
    expect(store.get().filters).toEqual({ notebook_ids: [NB], document_ids: ["doc-a"] });

    // Tab closes the chunk and clears the narrowing filters.
    await userEvent.click(screen.getByTestId("crumb-tab"));
    expect(store.get().detailId).toBeNull();
    expect(store.get().filters.notebook_ids).toBeUndefined();
    expect(store.get().filters.document_ids).toBeUndefined();
    expect(screen.queryByTestId("breadcrumb")).toBeNull();
  });
});
