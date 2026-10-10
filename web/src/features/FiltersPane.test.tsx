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
});
