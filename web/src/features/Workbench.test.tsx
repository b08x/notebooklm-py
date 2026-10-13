import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { POLL_MS } from "@/lib/queries";
import { mockFetch, renderWithClient, row } from "@/test/utils";
import { store } from "@/state/store";
import { Header } from "./Header";
import { Workbench } from "./Workbench";

const EMPTY_FACETS = { notebook: [], document: [], run: [], strategy: [], kind: [], fact_check: [], quality: [], length: [] };
const HIT = { ...row(), kw_rank: 1, vec_rank: 1, score: 0.03, distance: 0.1 };

describe("search mode toggle (fact-11)", () => {
  it("switches between Keyword, Vector and Hybrid RRF and searches in that mode", async () => {
    const calls = mockFetch({
      "POST /v1/corpus/search": { query: "q", mode: "keyword", hits: [HIT], vector_leg_ok: true, keyword_count: 1, vector_count: 0, elapsed_ms: 3 },
      "GET /v1/corpus/stats": { clauses: 1, filtered_max_clause_id: 5, new_since: 0 },
      "GET /v1/corpus/facets": EMPTY_FACETS,
    });
    renderWithClient(
      <>
        <Header />
        <Workbench />
      </>,
    );
    act(() => store.set({ tab: "search" }));
    const radios = screen.getAllByRole("radio").map((r) => r.textContent);
    expect(radios).toEqual(["Keyword", "Vector", "Hybrid · RRF"]);
    expect(screen.getByRole("radio", { name: "Hybrid · RRF" })).toHaveAttribute("aria-checked", "true");
    fireEvent.click(screen.getByRole("radio", { name: "Keyword" }));
    expect(store.get().mode).toBe("keyword");
    fireEvent.change(screen.getByLabelText("Search the corpus"), { target: { value: "kernel" } });
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() => expect(calls.find((c) => c.path === "/v1/corpus/search")?.body).toMatchObject({ query: "kernel", mode: "keyword" }));
    fireEvent.click(screen.getByRole("radio", { name: "Vector" }));
    await waitFor(() => expect(calls.filter((c) => c.path === "/v1/corpus/search").at(-1)?.body).toMatchObject({ mode: "vector" }));
  });
});

describe("live updates (fact-33)", () => {
  it("polls every 5 seconds and shows an 'N new chunks' pill that refreshes results", async () => {
    expect(POLL_MS).toBe(5000);
    let searches = 0;
    const calls = mockFetch({
      "POST /v1/corpus/search": () => {
        searches += 1;
        return { query: "q", mode: "hybrid", hits: [HIT], vector_leg_ok: true, keyword_count: 1, vector_count: 1, elapsed_ms: 3 };
      },
      "GET /v1/corpus/stats": (call) => ({ clauses: 10, filtered_max_clause_id: 100, new_since: call.path.includes("since=100") ? 37 : 0 }),
      "GET /v1/corpus/facets": EMPTY_FACETS,
    });
    renderWithClient(<Workbench />);
    act(() => store.set({ tab: "search", submittedQuery: "kernel", query: "kernel" }));
    const pill = await screen.findByRole("button", { name: /37 new chunks/ });
    expect(calls.some((c) => c.path.includes("since=100"))).toBe(true);
    const before = searches;
    fireEvent.click(pill);
    await waitFor(() => expect(searches).toBeGreaterThan(before));
  });
});
