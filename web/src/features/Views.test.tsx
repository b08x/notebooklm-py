import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
  it("reports the projected points, method, and how they are colored", async () => {
    mockFetch({
      "GET /v1/corpus/map": {
        points: [
          { x: 0, y: 0, external_id: "a", document_id: "d1", preview: "p", topic: null },
          { x: 1, y: 1, external_id: "b", document_id: "d2", preview: "q", topic: null },
        ],
        color_by: "document",
        method: "pca",
      },
    });
    renderWithClient(<MapView />);
    expect(await screen.findByText("2 chunks")).toBeInTheDocument();
    expect(screen.getByText(/PCA projection of chunk embeddings · 1 point = 1 chunk · color = document/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Embedding map of 2 chunks" })).toBeInTheDocument();
  });

  it("zooms around the cursor with the wheel and resets the view", async () => {
    mockFetch({
      "GET /v1/corpus/map": {
        points: [
          { x: 0, y: 0, external_id: "a", document_id: "d1", preview: "p", topic: null },
          { x: 1, y: 1, external_id: "b", document_id: "d2", preview: "q", topic: null },
        ],
        color_by: "document",
        method: "umap",
      },
    });
    renderWithClient(<MapView />);
    const map = await screen.findByTestId("map");
    expect(map).toHaveAttribute("data-k", "1.00");
    fireEvent.wheel(map, { deltaY: -240, clientX: 100, clientY: 100 });
    await waitFor(() => expect(screen.getByTestId("map")).toHaveAttribute("data-k", "1.43"));
    fireEvent.wheel(map, { deltaY: 240, clientX: 100, clientY: 100 });
    await waitFor(() => expect(screen.getByTestId("map")).toHaveAttribute("data-k", "1.00"));
    // A drag pans the canvas and suppresses the click that opens a chunk.
    const canvas = screen.getByRole("img");
    fireEvent.pointerDown(canvas, { clientX: 50, clientY: 50, pointerId: 1 });
    fireEvent.pointerMove(canvas, { clientX: 90, clientY: 60, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: 90, clientY: 60, pointerId: 1 });
    const reset = await screen.findByTestId("map-reset");
    fireEvent.click(canvas); // the pan suppressed this click
    expect(store.get().detailId).toBeNull();
    fireEvent.click(reset);
    await waitFor(() => expect(screen.queryByTestId("map-reset")).toBeNull());
    expect(screen.getByTestId("map")).toHaveAttribute("data-k", "1.00");
  });

  it("legends document titles, isolates a group on click, and tooltips name the document", async () => {
    mockFetch({
      "GET /v1/corpus/map": {
        points: [
          { x: 0, y: 0, external_id: "a", document_id: "d1", preview: "preview text", topic: null },
          { x: 0.4, y: 0.4, external_id: "b", document_id: "d1", preview: "x", topic: null },
          { x: 1, y: 1, external_id: "c", document_id: "d2", preview: "y", topic: null },
        ],
        color_by: "document",
        method: "pca",
      },
      "GET /v1/corpus/facets": { labels: { document: { d1: "Design notes" } } },
    });
    renderWithClient(<MapView />);
    const legend = await screen.findByTestId("map-legend");
    expect(within(legend).getByText("Design notes")).toBeInTheDocument();
    expect(within(legend).getByText("d2 untitled")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("legend-d2"));
    expect(screen.getByTestId("legend-d2")).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByTestId("legend-d2"));
    expect(screen.getByTestId("legend-d2")).toHaveAttribute("aria-pressed", "false");
    // Hovering a point shows its document title in the tooltip.
    fireEvent.pointerMove(screen.getByRole("img"), { clientX: 24, clientY: 376, pointerId: 1 });
    expect(await screen.findByTestId("map-tooltip")).toHaveTextContent("Design notes");
    expect(screen.getByTestId("map-tooltip")).toHaveTextContent("preview text");
  });

  it("caps the legend and offers a +N more overflow line", async () => {
    mockFetch({
      "GET /v1/corpus/map": {
        points: Array.from({ length: 13 }, (_, i) => ({
          x: i, y: i, external_id: `e${i}`, document_id: `d${i}`, preview: "p", topic: null,
        })),
        color_by: "document",
        method: "pca",
      },
    });
    renderWithClient(<MapView />);
    const legend = await screen.findByTestId("map-legend");
    expect(within(legend).getAllByRole("button")).toHaveLength(12);
    expect(screen.getByTestId("map-legend-more")).toHaveTextContent("+1 more");
  });
});

describe("MapView (facts 19-22)", () => {
  // Default size is 600x400 (the ResizeObserver stub never fires) with pad 24.
  // Screen positions at identity view: a=(24,376), b=(576,24), c=(134.4,164.8).
  const navPoints = [
    { x: 0, y: 0, external_id: "a", document_id: "d1", preview: "alpha", topic: null },
    { x: 1, y: 1, external_id: "b", document_id: "d1", preview: "beta", topic: null },
    { x: 0.2, y: 0.6, external_id: "c", document_id: "d2", preview: "gamma", topic: null },
  ];
  const groupPoints = [
    { x: 0, y: 0, external_id: "l1", document_id: "d1", preview: "p", topic: null },
    { x: 0.1, y: 0.1, external_id: "l2", document_id: "d1", preview: "p", topic: null },
    { x: 0.2, y: 0.2, external_id: "l3", document_id: "d1", preview: "p", topic: null },
    { x: 1, y: 1, external_id: "l4", document_id: "d2", preview: "p", topic: null },
  ];

  it("fact 19: wheel zoom keeps the point under the cursor fixed, and a drag pans by the drag distance", async () => {
    mockFetch({ "GET /v1/corpus/map": { points: navPoints, color_by: "document", method: "pca" } });
    renderWithClient(<MapView />);
    expect(await screen.findByText("3 chunks")).toBeInTheDocument();
    const map = screen.getByTestId("map");
    const canvas = screen.getByRole("img");
    const hoverAt = (x: number, y: number) => fireEvent.pointerMove(canvas, { clientX: x, clientY: y, pointerId: 1 });
    const C = { x: 134.4, y: 164.8 };

    hoverAt(C.x, C.y);
    expect(screen.getByTestId("map-tooltip")).toHaveTextContent("gamma");
    hoverAt(300, 200); // map center is empty; clears the tooltip
    expect(screen.queryByTestId("map-tooltip")).toBeNull();

    // Zoom at a non-center point. Point c must still hit-test at the cursor (within the 8px hover radius).
    fireEvent.wheel(map, { deltaY: -240, clientX: C.x, clientY: C.y });
    expect(map).toHaveAttribute("data-k", "1.43");
    hoverAt(C.x, C.y);
    expect(screen.getByTestId("map-tooltip")).toHaveTextContent("gamma");

    // Drag by (+40, +30) on the canvas. The pan suppresses hover while dragging.
    hoverAt(300, 200);
    fireEvent.pointerDown(canvas, { clientX: 200, clientY: 200, pointerId: 1 });
    fireEvent.pointerMove(canvas, { clientX: 240, clientY: 230, pointerId: 1 });
    fireEvent.pointerUp(canvas, { clientX: 240, clientY: 230, pointerId: 1 });
    expect(map).toHaveAttribute("data-k", "1.43"); // a pan does not change zoom
    hoverAt(C.x, C.y); // old position: c moved away
    expect(screen.queryByTestId("map-tooltip")).toBeNull();
    hoverAt(C.x + 40, C.y + 30); // new position: c moved by the drag distance
    expect(screen.getByTestId("map-tooltip")).toHaveTextContent("gamma");
  });

  it("fact 20: each document legend entry shows its title and point count, largest first", async () => {
    mockFetch({
      "GET /v1/corpus/map": { points: groupPoints, color_by: "document", method: "pca" },
      "GET /v1/corpus/facets": { labels: { document: { d1: "Design notes" } } },
    });
    renderWithClient(<MapView />);
    const legend = await screen.findByTestId("map-legend");
    const d1 = within(legend).getByTestId("legend-d1");
    expect(within(d1).getByText("Design notes")).toBeInTheDocument();
    expect(within(d1).getByText("3")).toBeInTheDocument();
    const d2 = within(legend).getByTestId("legend-d2");
    expect(within(d2).getByText("d2 untitled")).toBeInTheDocument();
    expect(within(d2).getByText("1")).toBeInTheDocument();
    expect(within(legend).getAllByRole("button").map((b) => b.dataset.testid)).toEqual(["legend-d1", "legend-d2"]);
  });

  it("fact 20: topic legend entries show the topic name and its point count", async () => {
    const topicPoints = [
      { x: 0, y: 0, external_id: "t1", document_id: "d1", preview: "p", topic: "billing" },
      { x: 0.5, y: 0.5, external_id: "t2", document_id: "d1", preview: "p", topic: "billing" },
      { x: 1, y: 1, external_id: "t3", document_id: "d2", preview: "p", topic: "infra" },
    ];
    mockFetch({ "GET /v1/corpus/map": { points: topicPoints, color_by: "topic", method: "pca" } });
    renderWithClient(<MapView />);
    const legend = await screen.findByTestId("map-legend");
    const billing = within(legend).getByTestId("legend-billing");
    expect(within(billing).getByText("billing")).toBeInTheDocument();
    expect(within(billing).getByText("2")).toBeInTheDocument();
    const infra = within(legend).getByTestId("legend-infra");
    expect(within(infra).getByText("infra")).toBeInTheDocument();
    expect(within(infra).getByText("1")).toBeInTheDocument();
  });

  it("fact 21: clicking a legend entry isolates its group, and clicking it again restores all groups", async () => {
    mockFetch({
      "GET /v1/corpus/map": { points: groupPoints, color_by: "document", method: "pca" },
      "GET /v1/corpus/facets": { labels: { document: { d1: "Design notes" } } },
    });
    renderWithClient(<MapView />);
    await screen.findByTestId("map-legend");
    const d1 = screen.getByTestId("legend-d1");
    const d2 = screen.getByTestId("legend-d2");
    expect(d1).toHaveAttribute("aria-pressed", "false");
    expect(d1).not.toHaveClass("opacity-40");
    expect(screen.queryByTestId("map-reset")).toBeNull();

    // Isolate d2: the other group is dimmed. The canvas alpha is not observable in jsdom.
    fireEvent.click(d2);
    expect(d2).toHaveAttribute("aria-pressed", "true");
    expect(d1).toHaveClass("opacity-40");
    expect(d2).not.toHaveClass("opacity-40");
    expect(screen.getByTestId("map-reset")).toBeInTheDocument();

    // Clicking the other entry moves the isolation.
    fireEvent.click(d1);
    expect(d1).toHaveAttribute("aria-pressed", "true");
    expect(d2).toHaveAttribute("aria-pressed", "false");
    expect(d2).toHaveClass("opacity-40");

    // Clicking the isolated entry again restores all groups.
    fireEvent.click(d1);
    expect(d1).toHaveAttribute("aria-pressed", "false");
    expect(d2).toHaveAttribute("aria-pressed", "false");
    expect(d1).not.toHaveClass("opacity-40");
    expect(d2).not.toHaveClass("opacity-40");
    expect(screen.queryByTestId("map-reset")).toBeNull();
  });

  it("fact 22: the explainer states that nearby points are semantically similar", async () => {
    mockFetch({ "GET /v1/corpus/map": { points: navPoints, color_by: "document", method: "pca" } });
    renderWithClient(<MapView />);
    expect(await screen.findByText(/nearby points are semantically similar/)).toBeInTheDocument();
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
