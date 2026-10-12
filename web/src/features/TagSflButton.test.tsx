import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { onJobFinished } from "@/state/jobs";
import { mockFetch, renderWithClient, SseBody, sse } from "@/test/utils";
import { TagSflButton } from "./TagSflButton";

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
  trace_url: "https://langfuse.dev/trace/j1",
  created_at: 100,
  started_at: null,
  finished_at: null,
  last_seq: 0,
  ...over,
});

function setup(events: object[], over: Record<string, unknown> = {}) {
  return mockFetch({
    "POST /v1/corpus/sfl/runs": job(over),
    "GET /v1/corpus/jobs/j1/events": () => new SseBody(sse(events)),
  });
}

describe("TagSflButton", () => {
  it("follows the job stream, flashes done, and fires registered invalidators", async () => {
    const invalidator = vi.fn();
    const onDone = vi.fn();
    onJobFinished(invalidator);
    const calls = setup([
      { seq: 1, type: "progress", message: "tagging clause 1/1", done: 1, total: 1 },
      { seq: 2, type: "finished", status: "done" },
    ]);
    renderWithClient(
      <TagSflButton scope={{ external_ids: ["doc:1:0"] }} label="chunk doc:1:0" onDone={onDone} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Tag SFL for chunk doc:1:0" }));
    await screen.findByTestId("tag-sfl-done");
    expect(screen.getByTestId("tag-sfl-done")).toHaveTextContent("Tagged");
    expect(onDone).toHaveBeenCalledWith(true);
    expect(invalidator).toHaveBeenCalledTimes(1);
    const post = calls.find((c) => c.method === "POST");
    expect(post?.path).toBe("/v1/corpus/sfl/runs");
    expect(post?.body).toEqual({ scope: { external_ids: ["doc:1:0"] } });
  });

  it("keeps showing n/N progress while the stream is open", async () => {
    setup([
      { seq: 1, type: "progress", message: "tagging clause 1/3", done: 1, total: 3 },
      { seq: 2, type: "progress", message: "tagging clause 2/3", done: 2, total: 3 },
    ]);
    renderWithClient(<TagSflButton scope={{ run_ids: [7] }} label="run #7" />);
    await userEvent.click(screen.getByRole("button", { name: "Tag SFL for run #7" }));
    const running = await screen.findByTestId("tag-sfl-running");
    expect(running).toBeDisabled();
    expect(running).toHaveTextContent("2/3 · 00:00");
    expect(running).toHaveAttribute("title", "tagging clause 2/3");
  });

  it("shows the error from a failed job and retrying posts again", async () => {
    let posts = 0;
    mockFetch({
      "POST /v1/corpus/sfl/runs": () => {
        posts += 1;
        return job({ id: posts === 1 ? "j1" : "j2" });
      },
      "GET /v1/corpus/jobs/j1/events": () =>
        new SseBody(sse([{ seq: 1, type: "finished", status: "failed", error: "boom" }])),
      "GET /v1/corpus/jobs/j2/events": () =>
        new SseBody(sse([{ seq: 1, type: "finished", status: "done" }])),
    });
    renderWithClient(<TagSflButton scope={{ run_ids: [7] }} label="run #7" />);
    await userEvent.click(screen.getByRole("button", { name: "Tag SFL for run #7" }));
    const failed = await screen.findByTestId("tag-sfl-failed");
    expect(failed).toHaveAttribute("title", "boom");
    expect(failed).toHaveTextContent("failed — retry");
    await userEvent.click(failed);
    await screen.findByTestId("tag-sfl-done");
    expect(posts).toBe(2);
  });
});
