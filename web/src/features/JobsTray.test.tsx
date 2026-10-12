import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithClient, SseBody, sse } from "@/test/utils";
import { JobsTray } from "./JobsTray";
import { TagSflButton } from "./TagSflButton";

const job = {
  id: "j1",
  kind: "sfl_tag",
  label: "chunk doc:1:0",
  status: "queued",
  message: "",
  done: 0,
  total: 3,
  result: null,
  error: null,
  document_ids: [],
  trace_url: "https://langfuse.dev/trace/j1",
  created_at: 100,
  started_at: null,
  finished_at: null,
  last_seq: 0,
};

describe("JobsTray", () => {
  it("shows an empty state before any job is tracked", async () => {
    mockFetch({});
    renderWithClient(<JobsTray />);
    await userEvent.click(screen.getByTestId("jobs-tray-trigger"));
    expect(screen.getByTestId("jobs-tray")).toHaveTextContent("No jobs yet.");
    expect(screen.queryByTestId("jobs-badge")).toBeNull();
  });

  it("badges running jobs and lists progress with a trace link", async () => {
    mockFetch({
      "POST /v1/corpus/sfl/runs": job,
      "GET /v1/corpus/jobs/j1/events": () =>
        new SseBody(sse([{ seq: 1, type: "progress", message: "tagging clause 1/3", done: 1, total: 3 }])),
    });
    renderWithClient(
      <>
        <TagSflButton scope={{ run_ids: [7] }} label="run #7" />
        <JobsTray />
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Tag SFL for run #7" }));
    expect(await screen.findByTestId("jobs-badge")).toHaveTextContent("1");
    await userEvent.click(screen.getByTestId("jobs-tray-trigger"));
    expect(screen.getByTestId("jobs-row-j1")).toHaveTextContent("sfl_tag");
    expect(screen.getByTestId("jobs-row-j1")).toHaveTextContent("chunk doc:1:0");
    expect(screen.getByTestId("jobs-message-j1")).toHaveTextContent("tagging clause 1/3 · 1/3");
    expect(screen.getByTestId("jobs-trace-j1")).toHaveAttribute("href", "https://langfuse.dev/trace/j1");
  });

  it("lists a finished job with its outcome and elapsed time", async () => {
    // Started 75s before the POST resolves, so the finished row reads 01:15 (formatElapsed floors seconds).
    mockFetch({
      "POST /v1/corpus/sfl/runs": () => ({ ...job, started_at: Date.now() / 1000 - 75 }),
      "GET /v1/corpus/jobs/j1/events": () =>
        new SseBody(sse([{ seq: 1, type: "finished", status: "done" }])),
    });
    renderWithClient(
      <>
        <TagSflButton scope={{ run_ids: [7] }} label="run #7" />
        <JobsTray />
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Tag SFL for run #7" }));
    await screen.findByTestId("tag-sfl-done");
    expect(screen.queryByTestId("jobs-badge")).toBeNull();
    await userEvent.click(screen.getByTestId("jobs-tray-trigger"));
    expect(screen.getByTestId("jobs-row-j1")).toHaveTextContent("sfl_tag");
    expect(screen.getByTestId("jobs-message-j1")).toHaveTextContent("done · 0/3 · 01:15");
  });

  it("shows a failed job's error text in the tray and on the triggering button", async () => {
    mockFetch({
      "POST /v1/corpus/sfl/runs": job,
      "GET /v1/corpus/jobs/j1/events": () =>
        new SseBody(sse([{ seq: 1, type: "finished", status: "failed", error: "boom" }])),
    });
    renderWithClient(
      <>
        <TagSflButton scope={{ run_ids: [7] }} label="run #7" />
        <JobsTray />
      </>,
    );
    await userEvent.click(screen.getByRole("button", { name: "Tag SFL for run #7" }));
    expect(await screen.findByTestId("tag-sfl-failed")).toHaveAttribute("title", "boom");
    await userEvent.click(screen.getByTestId("jobs-tray-trigger"));
    expect(screen.getByTestId("jobs-message-j1")).toHaveTextContent(/^boom/);
    expect(screen.getByTestId("jobs-message-j1")).not.toHaveTextContent("failed");
  });
});
