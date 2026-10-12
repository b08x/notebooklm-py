import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { FactCheckRunSnapshot, RunItem } from "@/lib/types";
import { mockFetch, renderWithClient, SseBody, Status, sse } from "@/test/utils";
import { store } from "@/state/store";
import { FactCheckView } from "./FactCheckView";
import { GateCard } from "./GateCard";
import { activeItem, applyEvent } from "./runState";

const item = (i: number, over: Partial<RunItem> = {}): RunItem => ({
  item_id: String(i).padStart(4, "0"),
  index: i,
  external_id: `d:1:${i}`,
  text: `[Speaker ${i % 2}] line ${i}`,
  status: "pending",
  reason: null,
  verdict: null,
  confidence: null,
  probability: null,
  gate: null,
  sift: {},
  sift_steps: null,
  citations: null,
  rationale: null,
  trace_url: null,
  context: { before: [{ external_id: "x", sentence_index: i - 1, text: "prev line" }], after: [{ external_id: "y", sentence_index: i + 1, text: "next line" }] },
  sfl: null,
  ...over,
});

const GATE = { flagged: true, reason: "jev: meta_dialogue_or_satire", source: "jev" as const, label: "meta_dialogue_or_satire", probability: 0.62, probabilities: null };

function snapshot(over: Partial<FactCheckRunSnapshot> = {}): FactCheckRunSnapshot {
  return {
    id: "run1",
    label: "notebook nb",
    status: "running",
    error: null,
    gate_source: "jev",
    gate_mode: "interactive",
    auto_skip: false,
    total: 3,
    done: 1,
    counts: { pending: 1, active: 0, waiting: 1, verified: 1, refuted: 0, unverifiable: 0, skipped: 0, no_framework: 0, error: 0 },
    elapsed_s: 476,
    last_seq: 6,
    waiting: [{ item_id: "0002", ...GATE }],
    items: [
      item(1, {
        status: "verified",
        confidence: 0.9,
        rationale: "Sources agree.",
        trace_url: "https://lf/trace/t",
        sift: { stop: "done", investigate_source: "done", find_coverage: "done", trace_claim: "done" },
        sift_steps: { find_coverage: { coverage_summary: "Sources agree." } },
      }),
      item(2, { status: "waiting", gate: GATE, probability: 0.62 }),
      item(3),
    ],
    ...over,
  };
}

describe("GateCard (fact-36)", () => {
  it("shows the classifier and probability; Skip/Fact-check/auto-skip call back", () => {
    const onDecide = vi.fn();
    const onAuto = vi.fn();
    render(<GateCard itemId="0002" gate={GATE} autoSkip={false} onDecide={onDecide} onAutoSkip={onAuto} />);
    expect(screen.getByTestId("gate")).toHaveTextContent("Meta-dialogue or satire detected");
    expect(screen.getByTestId("gate-probability")).toHaveTextContent("jev check-worthiness · p=0.62");
    fireEvent.click(screen.getByRole("button", { name: /Skip/ }));
    expect(onDecide).toHaveBeenLastCalledWith("0002", false);
    fireEvent.click(screen.getByRole("button", { name: /Fact-check/ }));
    expect(onDecide).toHaveBeenLastCalledWith("0002", true);
    fireEvent.click(screen.getByRole("switch", { name: "Auto-skip meta-dialogue" }));
    expect(onAuto).toHaveBeenCalledWith(true);
  });

  it("is hidden while auto-skip is on", () => {
    render(<GateCard itemId="0002" gate={GATE} autoSkip onDecide={vi.fn()} onAutoSkip={vi.fn()} />);
    expect(screen.queryByTestId("gate")).toBeNull();
  });
});

function setupRun(extra: Record<string, unknown> = {}) {
  const calls = mockFetch({
    "GET /v1/corpus/factcheck/runs/run1": snapshot(),
    "GET /v1/corpus/factcheck/runs/run1/events": new SseBody(""),
    "POST /v1/corpus/factcheck/runs/run1/decision": { ok: true },
    "POST /v1/corpus/factcheck/runs/run1/auto-skip": { ok: true },
    ...extra,
  });
  renderWithClient(<FactCheckView />);
  act(() => store.set({ tab: "factcheck", factcheckRunId: "run1" }));
  return calls;
}

describe("Fact-check run screen (facts 35-39)", () => {
  it("lists the queue with statuses, counts and elapsed time, and the ±2 transcript lines", async () => {
    setupRun();
    expect(await screen.findByTestId("run-progress")).toHaveTextContent("notebook nb · 1 / 3");
    expect(screen.getByTestId("run-counts")).toHaveTextContent("1verified0refuted0skipped1waiting");
    expect(screen.getByTestId("run-elapsed")).toHaveTextContent("07:56");
    expect(screen.getAllByRole("listitem").map((li) => li.getAttribute("data-status"))).toEqual(["verified", "waiting", "pending"]);
    const transcript = screen.getByTestId("transcript");
    expect(transcript).toHaveTextContent("prev line");
    expect(transcript).toHaveTextContent("[Speaker 0] line 2");
    expect(transcript).toHaveTextContent("next line");
    expect(screen.getByTestId("evidence")).toHaveTextContent("Sources agree.");
    // The waiting chunk has not reached SIFT yet; step status reads pending.
    expect(screen.getByTestId("sift")).toHaveTextContent("Stop◌ pendingInvestigate◌ pending");
    fireEvent.click(screen.getAllByRole("listitem")[0]);
    expect(screen.getByTestId("sift")).toHaveTextContent("Find coverage✓ done");
    expect(screen.getByRole("link", { name: /Langfuse trace/ })).toHaveAttribute("href", "https://lf/trace/t");
  });

  it("pressing n posts a fact-check decision for the waiting chunk; y posts skip", async () => {
    const calls = setupRun();
    await screen.findByTestId("gate");
    fireEvent.keyDown(window, { key: "n" });
    await waitFor(() => expect(calls.filter((c) => c.path.endsWith("/decision"))).toHaveLength(1));
    expect(calls.find((c) => c.path.endsWith("/decision"))?.body).toEqual({ item_id: "0002", decision: "fact_check" });
    fireEvent.keyDown(window, { key: "y" });
    await waitFor(() => expect(calls.filter((c) => c.path.endsWith("/decision"))).toHaveLength(2));
    expect(calls.filter((c) => c.path.endsWith("/decision"))[1].body).toEqual({ item_id: "0002", decision: "skip" });
  });

  it("the auto-skip toggle (s) posts and hides the gate", async () => {
    const calls = setupRun();
    await screen.findByTestId("gate");
    fireEvent.keyDown(window, { key: "s" });
    await waitFor(() => expect(screen.queryByTestId("gate")).toBeNull());
    expect(calls.find((c) => c.path.endsWith("/auto-skip"))?.body).toEqual({ on: true });
  });

  it("applies streamed events from the last seq (resume)", async () => {
    const calls = setupRun({
      "GET /v1/corpus/factcheck/runs/run1/events": new SseBody(
        sse([
          { seq: 7, type: "gate_resolved", item_id: "0002", decision: "skip" },
          { seq: 8, type: "item_done", item: item(2, { status: "skipped", rationale: "jev: filler" }) },
          { seq: 9, type: "run_finished", status: "finished" },
        ]),
      ),
    });
    await waitFor(() => expect(screen.getByTestId("run-counts")).toHaveTextContent("1skipped"));
    expect(calls.find((c) => c.path.startsWith("/v1/corpus/factcheck/runs/run1/events"))?.path).toContain("after=6");
    expect(screen.queryByTestId("gate")).toBeNull();
    expect(screen.getByText("finished")).toBeInTheDocument();
  });
});

describe("Start panel (facts 34, 49)", () => {
  it("starts a run for the chosen scope; sfl_required offers Tag SFL first", async () => {
    const calls = mockFetch({
      "GET /v1/corpus/notebooks": { items: [{ id: "nb", title: "Notebook", chunks: 3, documents: 1 }] },
      "GET /v1/corpus/factcheck/runs": { items: [] },
      "POST /v1/corpus/factcheck/runs": new Status(409, { error: { category: "sfl_required", message: "run sfl_tag first (3 children untagged)" } }),
      "POST /v1/corpus/sfl/runs": { id: "j", kind: "sfl_tag", label: "2 selected chunks", status: "queued", message: "", done: 0, total: 0, result: null, error: null, document_ids: [], trace_url: null, created_at: 0, started_at: null, finished_at: null, last_seq: 0 },
      "GET /v1/corpus/jobs/j/events": new SseBody(sse([{ seq: 1, type: "finished", status: "done" }])),
    });
    renderWithClient(<FactCheckView />);
    act(() => store.set({ tab: "factcheck", factcheckScope: { external_ids: ["a", "b"] } }));
    fireEvent.click(await screen.findByRole("button", { name: /Start run over 2 selected chunks/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("run sfl_tag first");
    expect(calls.find((c) => c.path === "/v1/corpus/factcheck/runs" && c.method === "POST")?.body).toMatchObject({
      scope: { external_ids: ["a", "b"] },
      gate_source: "rule",
      gate_mode: "interactive",
    });
    fireEvent.click(screen.getByRole("button", { name: /Tag SFL for 2 selected chunks/ }));
    await waitFor(() => expect(calls.find((c) => c.path === "/v1/corpus/sfl/runs")?.body).toEqual({ scope: { external_ids: ["a", "b"] } }));
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });
});

describe("runState", () => {
  it("ignores replayed events and tracks the active chunk", () => {
    const snap = snapshot();
    expect(applyEvent(snap, { seq: 5, type: "run_paused" })).toBe(snap);
    let next = applyEvent(snap, { seq: 7, type: "run_paused" });
    expect(next.status).toBe("paused");
    next = applyEvent(next, { seq: 8, type: "run_resumed" });
    next = applyEvent(next, { seq: 9, type: "sift_step", item_id: "0003", step: "stop", status: "running" });
    next = applyEvent(next, { seq: 10, type: "item_error", item_id: "0003", error: "boom" });
    next = applyEvent(next, { seq: 11, type: "auto_skip", auto_skip: true });
    expect(next.items[2]).toMatchObject({ status: "error", sift: { stop: "running" } });
    expect(next.auto_skip).toBe(true);
    expect(activeItem(next)?.item_id).toBe("0002");
    next = applyEvent(next, { seq: 12, type: "gate", item_id: "0003", gate: GATE });
    next = applyEvent(next, { seq: 13, type: "item_started", item_id: "0001" });
    next = applyEvent(next, { seq: 14, type: "run_started" });
    expect(next.counts.waiting).toBe(2);
  });
});
