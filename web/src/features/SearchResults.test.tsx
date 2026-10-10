import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { SearchHit, SearchResult } from "@/lib/types";
import { row } from "@/test/utils";
import { SearchResults } from "./SearchResults";

const hit = (over: Partial<SearchHit>): SearchHit =>
  ({ ...row(), kw_rank: null, vec_rank: null, score: 0, distance: null, ...over }) as SearchHit;

const result = (hits: SearchHit[], vectorOk = true): SearchResult => ({
  query: "cgroup memory",
  mode: "hybrid",
  hits,
  vector_leg_ok: vectorOk,
  keyword_count: 25,
  vector_count: 25,
  elapsed_ms: 41,
});

function renderResults(res: SearchResult, extra: Partial<React.ComponentProps<typeof SearchResults>> = {}) {
  const onOpen = vi.fn();
  const onToggle = vi.fn();
  render(
    <SearchResults
      result={res}
      loading={false}
      query="cgroup memory"
      selected={[]}
      cursor={null}
      detailId={null}
      hidden={[]}
      onOpen={onOpen}
      onToggle={onToggle}
      {...extra}
    />,
  );
  return { onOpen, onToggle };
}

describe("SearchResults", () => {
  it("shows keyword rank, vector rank and fused score for every hit (fact-10)", () => {
    renderResults(
      result([
        hit({ external_id: "a:1:0", kw_rank: 1, vec_rank: 2, score: 0.0325 }),
        hit({ external_id: "b:1:0", text: "Only by meaning", kw_rank: null, vec_rank: 4, score: 0.0156 }),
      ]),
    );
    const bars = screen.getAllByTestId("score-bars");
    expect(within(bars[0]).getByLabelText("kw #1")).toBeInTheDocument();
    expect(within(bars[0]).getByLabelText("vec #2")).toBeInTheDocument();
    expect(within(bars[0]).getByLabelText("rrf .0325")).toBeInTheDocument();
    expect(within(bars[1]).getByLabelText("kw —")).toBeInTheDocument();
    expect(screen.getByText(/2 results · 41 ms/)).toBeInTheDocument();
  });

  it("highlights query terms in the result text (fact-12)", () => {
    renderResults(result([hit({ kw_rank: 1, score: 0.02 })]));
    const marks = document.querySelectorAll("mark");
    expect(Array.from(marks).map((m) => m.textContent)).toEqual(["cgroup", "memory"]);
  });

  it("warns when the vector leg is unavailable (fact-13)", () => {
    renderResults(result([hit({ kw_rank: 1, score: 0.02 })], false));
    expect(screen.getByRole("alert")).toHaveTextContent("Vector leg unavailable");
  });

  it("flags noise chunks and hides rows pending deletion", () => {
    renderResults(
      result([
        hit({ external_id: "a:1:0", quality: "base64", text: "NsMvbzsVTlHfstpSeMH70", kw_rank: 1, score: 0.01 }),
        hit({ external_id: "gone:1:0", kw_rank: 2, score: 0.01 }),
      ]),
      { hidden: ["gone:1:0"] },
    );
    expect(screen.getAllByTestId("result-row")).toHaveLength(1);
    expect(screen.getByText("base64")).toBeInTheDocument();
  });

  it("opens on click and toggles selection with shift info", () => {
    const { onOpen, onToggle } = renderResults(result([hit({ kw_rank: 1, score: 0.02 })]));
    fireEvent.click(screen.getByTestId("result-row"));
    expect(onOpen).toHaveBeenCalledWith("doc:1:0");
    fireEvent.click(screen.getByLabelText("Select chunk"), { shiftKey: true });
    expect(onToggle).toHaveBeenCalledWith("doc:1:0", true);
  });

  it("prompts when there is no query and reports no matches", () => {
    const { unmount } = render(
      <SearchResults result={undefined} loading={false} query="" selected={[]} cursor={null} detailId={null} hidden={[]} onOpen={vi.fn()} onToggle={vi.fn()} />,
    );
    expect(screen.getByText("Search the corpus")).toBeInTheDocument();
    unmount();
    renderResults(result([]));
    expect(screen.getByText(/No chunks match/)).toBeInTheDocument();
  });
});
