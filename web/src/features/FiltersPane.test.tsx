import { fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithClient } from "@/test/utils";
import { store } from "@/state/store";
import { FiltersPane } from "./FiltersPane";

const FACETS = {
  notebook: [{ value: "nb-1", count: 5991 }],
  document: [{ value: "doc-a", count: 40 }],
  run: [{ value: 3, count: 40 }],
  strategy: [{ value: "recursive", count: 5991 }],
  kind: [
    { value: "source", count: 5700 },
    { value: "audio", count: 291 },
  ],
  fact_check: [
    { value: "unchecked", count: 5991 },
    { value: "passed", count: 0 },
    { value: "failed", count: 0 },
    { value: "other", count: 0 },
  ],
  quality: [
    { value: "clean", count: 5702 },
    { value: "base64", count: 214 },
    { value: "numeric_table", count: 75 },
  ],
  length: [{ value: "<80", count: 10 }],
};

describe("FiltersPane (facts 16-17, 62)", () => {
  it("shows corpus stats and every facet value with its count", async () => {
    mockFetch({
      "GET /v1/corpus/facets": FACETS,
      "GET /v1/corpus/stats": { clauses: 5991, parents: 703, documents: 88, runs: 88 },
    });
    renderWithClient(<FiltersPane />);
    expect(await screen.findByTestId("facet-count-quality-base64")).toHaveTextContent("214");
    expect(screen.getByTestId("facet-count-quality-numeric_table")).toHaveTextContent("75");
    expect(screen.getByTestId("facet-count-kinds-audio")).toHaveTextContent("291");
    expect(screen.getByTestId("facet-count-fact_check-unchecked")).toHaveTextContent("5,991");
    await waitFor(() => expect(screen.getByTestId("corpus-stats")).toHaveTextContent("5,991clauses703parents88documents88runs"));
  });

  it("toggling a value narrows the filters; the near-duplicate switch sets its filter", async () => {
    const calls = mockFetch({ "GET /v1/corpus/facets": FACETS, "GET /v1/corpus/stats": { clauses: 1 } });
    renderWithClient(<FiltersPane />);
    fireEvent.click(await screen.findByLabelText("Base64 / binary"));
    expect(store.get().filters.quality).toEqual(["base64"]);
    fireEvent.click(screen.getByLabelText("Only chunks with a near-duplicate"));
    expect(store.get().filters.has_near_duplicate).toBe(true);
    await waitFor(() => expect(calls.some((c) => c.path.includes("quality=base64") && c.path.includes("has_near_duplicate=true"))).toBe(true));
    fireEvent.click(screen.getByText("Clear filters"));
    expect(store.get().filters.quality).toBeUndefined();
  });

  it("labels notebooks and documents by stored title; unnamed ones show a short id, never a full UUID", async () => {
    mockFetch({
      "GET /v1/corpus/facets": {
        ...FACETS,
        document: [{ value: "doc-a", count: 40 }, { value: "doc-b-uuid-long", count: 7 }],
        labels: { document: { "doc-a": "Design notes" } },
      },
      "GET /v1/corpus/notebooks": { items: [{ id: "nb-1", title: "Kernel Panic Notebook", chunks: 40, documents: 1 }] },
      "GET /v1/corpus/stats": { clauses: 1 },
    });
    renderWithClient(<FiltersPane />);
    expect(await screen.findByLabelText("Kernel Panic Notebook")).toBeInTheDocument();
    expect(screen.getByLabelText("Design notes")).toBeInTheDocument();
    expect(screen.getByLabelText("doc-b-uu… untitled")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("doc-b-uuid-long");
  });
});
