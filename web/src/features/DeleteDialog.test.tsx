import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { Toaster } from "sonner";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithClient } from "@/test/utils";
import { actions, store } from "@/state/store";
import { DeleteDialog } from "./DeleteDialog";
import { flushDeletes, pendingDeleteCount, resetDeletes, undoDelete } from "./deletes";

const PREVIEW = { level: "clause", ids: ["a:1:0", "b:1:0"], counts: { clauses: 2, embeddings: 2, fact_checks: 1, parents: 0, runs: 0 } };

function setup(grace = 30) {
  resetDeletes();
  window.__CE_DELETE_GRACE_MS = grace;
  const calls = mockFetch({
    "POST /v1/corpus/delete/preview": PREVIEW,
    "POST /v1/corpus/delete": { level: "clause", ids: PREVIEW.ids, counts: PREVIEW.counts, removal_log_ids: [1, 2] },
  });
  renderWithClient(
    <>
      <DeleteDialog />
      <Toaster />
    </>,
  );
  act(() => actions.requestDelete({ level: "clause", ids: PREVIEW.ids, hide: PREVIEW.ids, label: "2 selected chunks" }));
  return calls;
}

const deletes = (calls: { method: string; path: string }[]) => calls.filter((c) => c.path === "/v1/corpus/delete");

describe("DeleteDialog (fact-23)", () => {
  beforeEach(() => {
    window.__CE_DELETE_GRACE_MS = 30;
  });
  afterEach(() => {
    delete window.__CE_DELETE_GRACE_MS;
  });

  it("names the level and the counts to be removed", async () => {
    setup();
    expect(await screen.findByRole("alertdialog")).toHaveTextContent("Delete 2 chunks?");
    expect(screen.getByText("clause")).toBeInTheDocument();
    const counts = await screen.findByTestId("delete-counts");
    await waitFor(() => expect(counts).toHaveTextContent("Clauses2Embeddings2Fact-checks1"));
  });

  it("Cancel removes nothing and sends no delete request", async () => {
    const calls = setup();
    await screen.findByText("Fact-checks");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await new Promise((r) => setTimeout(r, 80));
    expect(deletes(calls)).toHaveLength(0);
    expect(store.get().hidden).toEqual([]);
    expect(store.get().deleteRequest).toBeNull();
  });

  it("Confirm hides the rows and sends exactly one delete request", async () => {
    const calls = setup();
    const confirm = await screen.findByRole("button", { name: "Delete" });
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    expect(store.get().hidden).toEqual(PREVIEW.ids);
    await waitFor(() => expect(deletes(calls)).toHaveLength(1));
    expect(deletes(calls)[0]).toMatchObject({ method: "POST", body: { level: "clause", ids: PREVIEW.ids } });
    await new Promise((r) => setTimeout(r, 80));
    expect(deletes(calls)).toHaveLength(1);
    expect(await screen.findByText("Deleted 2 chunks")).toBeInTheDocument();
  });
});

describe("Undo toast", () => {
  it("Undo inside the grace period restores the rows and deletes nothing", async () => {
    const calls = setup(10_000);
    const confirm = await screen.findByRole("button", { name: "Delete" });
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    const undo = await screen.findByRole("button", { name: "Undo" });
    expect(screen.getAllByText("Deleting 2 selected chunks").length).toBeGreaterThan(0);
    fireEvent.click(undo);
    expect(store.get().hidden).toEqual([]);
    expect(await screen.findByText("Delete undone")).toBeInTheDocument();
    expect(pendingDeleteCount()).toBe(0);
    expect(deletes(calls)).toHaveLength(0);
    expect(undoDelete("missing")).toBe(false);
  });

  it("closing the page flushes a pending delete with keepalive", async () => {
    const calls = setup(10_000);
    const confirm = await screen.findByRole("button", { name: "Delete" });
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    flushDeletes();
    expect(deletes(calls)).toHaveLength(1);
    expect(pendingDeleteCount()).toBe(0);
  });
});
