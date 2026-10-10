import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithClient } from "@/test/utils";
import { store } from "@/state/store";
import { MapView } from "./MapView";
import { RunsView } from "./RunsView";
import { SelectionBar } from "./SelectionBar";
import { StatusFooter } from "./StatusFooter";
import { Toaster } from "sonner";

describe("RunsView (fact-32)", () => {
  it("lists runs with strategy, counts, lengths and the active flag", async () => {
    const calls = mockFetch({
      "GET /v1/corpus/runs": {
        items: [
          { id: 7, document_id: "doc", notebook_id: "nb", strategy: "recursive", kind: "audio", title: "Deep dive", n_parents: 12, n_children: 296, mean_len: 81.4, p95_len: 190, entity_vetoes: 0, is_active: true, created_at: null },
          { id: 6, document_id: "doc", notebook_id: "nb", strategy: "recursive", kind: "source", title: null, n_parents: 3, n_children: 30, mean_len: 50, p95_len: 90, entity_vetoes: 0, is_active: false, created_at: null },
        ],
      },
      "GET /v1/corpus/jobs": { items: [{ id: "j", kind: "ingest", label: "ingest artifact x", status: "running", message: "embedding", done: 3, total: 9 }] },
      "POST /v1/corpus/sfl/runs": { id: "s" },
    });
    renderWithClient(<RunsView />);
    await waitFor(() => expect(screen.getAllByRole("row")).toHaveLength(3));
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("#7Deep diveaudiorecursive1229681190active");
    expect(rows[2]).toHaveTextContent("#6");
    expect(await screen.findByRole("status")).toHaveTextContent("ingest artifact x");
    fireEvent.click(screen.getByLabelText("Tag SFL for run 7"));
    await waitFor(() => expect(calls.find((c) => c.path === "/v1/corpus/sfl/runs")?.body).toEqual({ scope: { run_ids: [7] } }));
    fireEvent.click(screen.getByLabelText("Fact-check run 7"));
    expect(store.get().factcheckScope).toEqual({ run_ids: [7] });
    fireEvent.click(screen.getByLabelText("Delete run 6"));
    expect(store.get().deleteRequest).toMatchObject({ level: "run", ids: ["6"] });
  });
});

describe("SelectionBar (facts 24-26)", () => {
  it("shows the bulk actions and exports Markdown as a download", async () => {
    const calls = mockFetch({
      "POST /v1/corpus/export": () => new Response("# export", { headers: { "content-disposition": 'attachment; filename="corpus-export.md"' } }),
      "POST /v1/corpus/export/note": { notes: [{ notebook_id: "nb", count: 2 }] },
    });
    const create = vi.fn(() => "blob:x");
    URL.createObjectURL = create;
    URL.revokeObjectURL = vi.fn();
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    renderWithClient(
      <>
        <SelectionBar />
        <Toaster />
      </>,
    );
    act(() => store.set({ selected: ["a:1:0", "b:1:0"] }));
    expect(screen.getByTestId("selection-count")).toHaveTextContent("2 selected");
    await userEvent.click(screen.getByRole("button", { name: /Export/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: "Download Markdown" }));
    await waitFor(() => expect(clicked).toHaveBeenCalled());
    expect(calls[0].body).toEqual({ ids: ["a:1:0", "b:1:0"], format: "markdown" });
    await userEvent.click(screen.getByRole("button", { name: /Export/ }));
    await userEvent.click(await screen.findByRole("menuitem", { name: /Push as note/ }));
    expect(await screen.findByText("Pushed 1 note to NotebookLM")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Re-fact-check/ }));
    expect(store.get().factcheckScope).toEqual({ external_ids: ["a:1:0", "b:1:0"] });
  });
});

describe("MapView (fact-31)", () => {
  it("reports the projected points and how they are colored", async () => {
    mockFetch({
      "GET /v1/corpus/map": {
        points: [
          { x: 0, y: 0, external_id: "a", document_id: "d1", preview: "p", topic: null },
          { x: 1, y: 1, external_id: "b", document_id: "d2", preview: "q", topic: null },
        ],
        color_by: "document",
      },
    });
    renderWithClient(<MapView />);
    expect(await screen.findByText("2 chunks")).toBeInTheDocument();
    expect(screen.getByText("colored by document")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Embedding map of 2 chunks" })).toBeInTheDocument();
  });
});

describe("StatusFooter", () => {
  it("links a waiting fact-check run back to its screen", () => {
    render(
      <StatusFooter
        health={{
          postgres: { ok: false },
          embedder: { ok: true },
          jobs: [],
          factcheck_runs: [{ id: "r", label: "x", status: "running", error: null, gate_source: "rule", gate_mode: "interactive", auto_skip: false, total: 9, done: 3, counts: {} as never, elapsed_s: 1, last_seq: 1, waiting: [{ item_id: "0004" }] }],
        }}
      />,
    );
    expect(screen.getByTestId("status-postgres")).toHaveTextContent("postgres down");
    fireEvent.click(screen.getByTestId("status-run"));
    expect(store.get()).toMatchObject({ tab: "factcheck", factcheckRunId: "r" });
    expect(screen.getByTestId("status-run")).toHaveTextContent("waiting on you · chunk 0004");
  });
});
