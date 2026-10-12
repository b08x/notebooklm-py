import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { useJobInvalidation } from "@/state/useJobInvalidation";
import { mockFetch, renderWithClient, row, SseBody, sse } from "@/test/utils";
import { store } from "@/state/store";
import { DetailPane } from "./DetailPane";

const PARENT = "Before text. Kernel panics hit the cgroup memory limit. After text.";

const detail = {
  ...row({ has_sfl: true }),
  parent: { id: 10, index: 1, text: PARENT, char_start: 0, char_end: PARENT.length, child_start: 13, child_end: 55, n_children: 3 },
  n_parents: 4,
  context: {
    before: [{ external_id: "doc:1:-1", sentence_index: -1, text: "Before text." }],
    after: [{ external_id: "doc:1:1", sentence_index: 1, text: "After text." }],
  },
  entities: [{ text: "Kernel", label: "PROPN" }],
  sfl: {
    ideational: { participants: ["kernel panics"], processes: ["hit"], circumstances: [] },
    interpersonal: { tenor: ["formality: informal"], mood: ["declarative"], modality: ["high"] },
  },
  sfl_raw: {},
  tokens: [],
  groups: {},
  topic: null,
  latest_fact_check: { verdict: "supported", confidence: 0.91, probabilities: null, sift_steps: null, citations: null, trace_id: null, model: "m", created_at: null },
  run: { id: 1, strategy: "recursive", chunker_version: "1", is_active: true, trace_id: null, source_hash: "x", params: {}, created_at: null },
  created_at: null,
};

const job = (over: Record<string, unknown> = {}) => ({
  id: "j1",
  kind: "sfl_tag",
  label: "chunk doc:1:0",
  status: "queued",
  message: "",
  done: 0,
  total: 1,
  result: null,
  error: null,
  document_ids: [],
  trace_url: null,
  created_at: 100,
  started_at: null,
  finished_at: null,
  last_seq: 0,
  ...over,
});

describe("DetailPane", () => {
  it("shows the parent chunk with the clause highlighted inside it (fact-18)", async () => {
    mockFetch({ "GET /v1/corpus/chunks/doc:1:0": detail });
    renderWithClient(<DetailPane />);
    store.set({ detailId: "doc:1:0" });
    const mark = await screen.findByTestId("child-highlight");
    expect(mark).toHaveTextContent("Kernel panics hit the cgroup memory limit.");
    expect(screen.getByTestId("parent-context")).toHaveTextContent(PARENT);
    expect(screen.getByText("supported")).toBeInTheDocument();
    expect(screen.getByText(/run #1 · recursive · active/)).toBeInTheDocument();
  });

  it("renders SFL values (not field names) and entities in Linguistics", async () => {
    mockFetch({ "GET /v1/corpus/chunks/doc:1:0": detail });
    renderWithClient(<DetailPane />);
    store.set({ detailId: "doc:1:0", detailTab: "linguistics" });
    expect(await screen.findByTestId("sfl")).toHaveTextContent("formality: informal");
    expect(screen.getByTestId("entities")).toHaveTextContent("Kernel");
  });

  it("lists neighbours with distance and near-duplicate badges (facts 19-20)", async () => {
    mockFetch({
      "GET /v1/corpus/chunks/doc:1:0": detail,
      "GET /v1/corpus/chunks/doc:1:0/neighbors": {
        items: [
          { ...row({ external_id: "dup:1:0", text: "Near copy" }), distance: 0.05, near_duplicate: true },
          { ...row({ external_id: "far:1:0", text: "Far away" }), distance: 0.81, near_duplicate: false },
        ],
        near_dup_threshold: 0.2,
      },
    });
    renderWithClient(<DetailPane />);
    store.set({ detailId: "doc:1:0", detailTab: "similar" });
    expect(await screen.findByText("0.050")).toBeInTheDocument();
    expect(screen.getByText("0.810")).toBeInTheDocument();
    expect(screen.getAllByText("near-duplicate")).toHaveLength(1);
    fireEvent.click(screen.getByText("Far away"));
    expect(store.get().detailId).toBe("far:1:0");
  });

  it("offers delete at four levels and opens the confirm request (fact-21)", async () => {
    mockFetch({ "GET /v1/corpus/chunks/doc:1:0": detail });
    renderWithClient(<DetailPane />);
    store.set({ detailId: "doc:1:0" });
    await screen.findByTestId("child-highlight");
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual([
      "This chunk",
      "Parent chunk + 3 children",
      "Whole document",
      "Whole run #1",
    ]);
    await userEvent.click(items[1]);
    await waitFor(() => expect(store.get().deleteRequest?.level).toBe("parent"));
    expect(store.get().deleteRequest?.ids).toEqual(["10"]);
  });

  it("shows an empty state without a selection", () => {
    renderWithClient(<DetailPane />);
    expect(screen.getByText(/Select a chunk/)).toBeInTheDocument();
  });

  it("assesses a whole document or run: fact-check scope and SFL tagging (facts 49-50)", async () => {
    const calls = mockFetch({ "GET /v1/corpus/chunks/doc:1:0": detail, "POST /v1/corpus/sfl/runs": { id: "j" } });
    renderWithClient(<DetailPane />);
    store.set({ detailId: "doc:1:0" });
    await screen.findByTestId("child-highlight");
    await userEvent.click(screen.getByRole("button", { name: "Assess" }));
    const items = await screen.findAllByRole("menuitem");
    expect(items.map((i) => i.textContent)).toEqual([
      "This chunk",
      "Whole document",
      "Whole run #1",
      "This chunk",
      "Whole document",
      "Whole run #1",
    ]);
    await userEvent.click(items[4]);
    await waitFor(() => expect(calls.find((c) => c.path === "/v1/corpus/sfl/runs")?.body).toEqual({ scope: { document_ids: ["doc"] } }));
    await userEvent.click(screen.getByRole("button", { name: "Assess" }));
    await userEvent.click((await screen.findAllByRole("menuitem"))[2]);
    expect(store.get().factcheckScope).toEqual({ run_ids: [1] });
    expect(store.get().tab).toBe("factcheck");
  });

  it("shows notebook and document titles, not UUIDs (fact-4, partial)", async () => {
    const NB = "9b1d2c3e-0000-4000-8000-000000000001";
    const DOC = "7a6f5e4d-0000-4000-8000-000000000002";
    mockFetch({
      "GET /v1/corpus/chunks/doc:1:0": { ...detail, notebook_id: NB, document_id: DOC, title: "Kernel Incident Report" },
      "GET /v1/corpus/notebooks": { items: [{ id: NB, title: "Ops Notebook" }] },
    });
    renderWithClient(<DetailPane />);
    store.set({ detailId: "doc:1:0" });
    expect(await screen.findByText(/doc Kernel Incident Report/)).toBeInTheDocument();
    expect(await screen.findByText(/nb Ops Notebook/)).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(NB))).not.toBeInTheDocument();
    expect(screen.queryByText(new RegExp(DOC))).not.toBeInTheDocument();
  });

  it("switches Tag SFL to a running state with n/N and elapsed time (fact-11)", async () => {
    mockFetch({
      "GET /v1/corpus/chunks/doc:1:0": { ...detail, sfl: null },
      "POST /v1/corpus/sfl/runs": job(),
      "GET /v1/corpus/jobs/j1/events": () =>
        new SseBody(sse([{ seq: 1, type: "progress", message: "tagging clause 2/3", done: 2, total: 3 }])),
    });
    renderWithClient(<DetailPane />);
    store.set({ detailId: "doc:1:0", detailTab: "linguistics" });
    await userEvent.click(await screen.findByRole("button", { name: "Tag SFL for this chunk" }));
    const running = await screen.findByTestId("tag-sfl-running");
    expect(running).toBeDisabled();
    expect(running).toHaveTextContent(/2\/3 · 00:0\d/);
  });

  it("refreshes the chunk detail and shows new SFL tags when the job finishes (fact-14)", async () => {
    const tagged = {
      ...detail,
      sfl: {
        ideational: { participants: ["kernel"], processes: ["panics"], circumstances: [] },
        interpersonal: { tenor: ["formality: formal"], mood: ["declarative"], modality: ["high"] },
      },
    };
    let reads = 0;
    mockFetch({
      "GET /v1/corpus/chunks/doc:1:0": () => {
        reads += 1;
        return reads === 1 ? { ...detail, sfl: null } : tagged;
      },
      "POST /v1/corpus/sfl/runs": job(),
      "GET /v1/corpus/jobs/j1/events": () => new SseBody(sse([{ seq: 1, type: "finished", status: "done" }])),
    });
    // The same hook App.tsx mounts at the root refreshes the chunk query when the job finishes.
    function WithInvalidation() {
      useJobInvalidation();
      return <DetailPane />;
    }
    renderWithClient(<WithInvalidation />);
    store.set({ detailId: "doc:1:0", detailTab: "linguistics" });
    await userEvent.click(await screen.findByRole("button", { name: "Tag SFL for this chunk" }));
    const sfl = await screen.findByTestId("sfl");
    expect(sfl).toHaveTextContent("formality: formal");
    expect(reads).toBeGreaterThanOrEqual(2);
  });
});
