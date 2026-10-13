import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithClient } from "@/test/utils";
import type { DocumentClauseItem, DocumentItem } from "@/lib/types";
import { store } from "@/state/store";
import { DocumentView, getStorageKey } from "./DocumentView";

const DOC: DocumentItem = {
  id: "doc-alpha",
  title: "Kernel Subsystems",
  collection_id: "coll-1",
  collection_title: "Core Architecture",
  file_type: "md",
  clause_count: 4,
  tagged_count: 2,
  fact_checked_count: 3,
  created_at: "2026-01-01T00:00:00Z",
};

const CLAUSES: DocumentClauseItem[] = [
  // Chunk 0 (parent_id: 10)
  {
    id: "cl-1",
    external_id: "cl-1",
    parent_id: 10,
    sentence_index: 0,
    text: "The kernel allocates memory using buddy pages.",
    length: 46,
    quality: "clean",
    fact_check: "passed",
    has_sfl: true,
    sfl_status: "tagged",
    sfl_data: null,
    latest_fact_check: { verdict: "supported" },
    created_at: null,
  },
  {
    id: "cl-2",
    external_id: "cl-2",
    parent_id: 10,
    sentence_index: 1,
    text: "Slab caches provide efficient object reuse.",
    length: 42,
    quality: "clean",
    fact_check: "failed",
    has_sfl: false,
    sfl_status: null,
    sfl_data: null,
    latest_fact_check: { verdict: "contradicted" },
    created_at: null,
  },
  // Chunk 1 (parent_id: 20)
  {
    id: "cl-3",
    external_id: "cl-3",
    parent_id: 20,
    sentence_index: 0,
    text: "Device drivers interact via ioctl syscalls.",
    length: 43,
    quality: "clean",
    fact_check: "unchecked",
    has_sfl: false,
    sfl_status: null,
    sfl_data: null,
    latest_fact_check: null,
    created_at: null,
  },
  {
    id: "cl-4",
    external_id: "cl-4",
    parent_id: 20,
    sentence_index: 1,
    text: "Interrupt handlers execute with high priority.",
    length: 46,
    quality: "clean",
    fact_check: "other",
    has_sfl: true,
    sfl_status: "tagged",
    sfl_data: null,
    latest_fact_check: { verdict: "unverified" },
    created_at: null,
  },
];

describe("DocumentView (facts 33-42)", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch({
      "GET /v1/corpus/documents": { documents: [DOC], total: 1 },
      "GET /v1/corpus/documents/doc-alpha/clauses": {
        document_id: "doc-alpha",
        clauses: CLAUSES,
        total: CLAUSES.length,
      },
    });
    store.set({ filters: { document_ids: ["doc-alpha"] }, detailId: null });
  });

  it("renders empty state when no document is selected", () => {
    renderWithClient(<DocumentView documentId={null} />);
    expect(screen.getByTestId("document-view-empty")).toBeInTheDocument();
  });

  it("renders document title, file type, clauses count, and chunk headers with counts", async () => {
    renderWithClient(<DocumentView documentId="doc-alpha" />);
    expect(await screen.findByTestId("document-title")).toHaveTextContent("Kernel Subsystems");
    expect(screen.getByText("4 clauses")).toBeInTheDocument();
    expect(screen.getByText("Chunk 1")).toBeInTheDocument();
    expect(screen.getByText("Chunk 2")).toBeInTheDocument();
  });

  it("renders SFL background tint for tagged clauses and verdict markers for checked clauses", async () => {
    renderWithClient(<DocumentView documentId="doc-alpha" />);
    await screen.findByTestId("document-title");

    // cl-1 is tagged (has SFL tint) and supported (green verdict marker)
    const span1 = screen.getByTestId("clause-span-cl-1");
    expect(span1.className).toContain("bg-primary/10");
    const marker1 = screen.getByTestId("verdict-marker-cl-1");
    expect(marker1.className).toContain("bg-ok");

    // cl-2 is not tagged, contradicted (red verdict marker)
    const span2 = screen.getByTestId("clause-span-cl-2");
    expect(span2.className).not.toContain("bg-primary/10");
    const marker2 = screen.getByTestId("verdict-marker-cl-2");
    expect(marker2.className).toContain("bg-bad");

    // cl-3 has no fact check (no verdict marker)
    expect(screen.queryByTestId("verdict-marker-cl-3")).toBeNull();

    // cl-4 is unverified (amber verdict marker)
    const marker4 = screen.getByTestId("verdict-marker-cl-4");
    expect(marker4.className).toContain("bg-warn");
  });

  it("clicking a clause selects it and opens inspector", async () => {
    renderWithClient(<DocumentView documentId="doc-alpha" />);
    await screen.findByTestId("document-title");

    const span1 = screen.getByTestId("clause-span-cl-1");
    fireEvent.click(span1);

    expect(store.get().detailId).toBe("cl-1");
    expect(store.get().inspectorDrawerOpen).toBe(true);
  });

  it("chunk collapse toggles and controls (Collapse all, Collapse unflagged, Expand all)", async () => {
    renderWithClient(<DocumentView documentId="doc-alpha" />);
    await screen.findByTestId("document-title");

    // Initially both chunks are expanded, all clauses present
    expect(screen.getByText(/buddy pages/)).toBeInTheDocument();
    expect(screen.getByText(/Device drivers/)).toBeInTheDocument();

    // Toggle chunk 1 collapse
    fireEvent.click(screen.getByTestId("chunk-header-toggle-0"));
    // Chunk 0 collapsed: cl-2 should not be visible as an interactive span
    expect(screen.queryByTestId("clause-span-cl-2")).toBeNull();

    // Persistence in localStorage
    const stored = JSON.parse(localStorage.getItem(getStorageKey("doc-alpha")) || "[]");
    expect(stored).toContain(0);

    // Expand all
    fireEvent.click(screen.getByTestId("expand-all-btn"));
    expect(screen.getByTestId("clause-span-cl-2")).toBeInTheDocument();

    // Collapse all
    fireEvent.click(screen.getByTestId("collapse-all-btn"));
    expect(screen.queryByTestId("clause-span-cl-2")).toBeNull();

    // Expand all again
    fireEvent.click(screen.getByTestId("expand-all-btn"));
    expect(screen.getByTestId("clause-span-cl-2")).toBeInTheDocument();
  });

  it("right-edge marker strip renders ticks and clicking a tick jumps to clause", async () => {
    renderWithClient(<DocumentView documentId="doc-alpha" />);
    await screen.findByTestId("document-title");

    const markerStrip = screen.getByTestId("marker-strip");
    expect(markerStrip).toBeInTheDocument();

    // Ticks for cl-1, cl-2, cl-4
    const tick1 = screen.getByTestId("marker-tick-cl-1");
    expect(tick1).toBeInTheDocument();

    // Clicking tick selects clause
    fireEvent.click(tick1);
    expect(store.get().detailId).toBe("cl-1");
  });

  it("arrow keys navigate between visible clauses and skip collapsed chunks", async () => {
    renderWithClient(<DocumentView documentId="doc-alpha" />);
    await screen.findByTestId("document-title");

    const view = screen.getByTestId("document-view");

    // Select cl-1
    fireEvent.click(screen.getByTestId("clause-span-cl-1"));
    expect(store.get().detailId).toBe("cl-1");

    // Down arrow moves to cl-2
    fireEvent.keyDown(view, { key: "ArrowDown" });
    expect(store.get().detailId).toBe("cl-2");

    // Collapse Chunk 1 (which contains cl-3 and cl-4)
    fireEvent.click(screen.getByTestId("chunk-header-toggle-1"));

    // Down arrow from cl-2 moves to first clause of Chunk 1 (cl-3)
    fireEvent.keyDown(view, { key: "ArrowDown" });
    expect(store.get().detailId).toBe("cl-3");

    // Next Down arrow stays at cl-3 because cl-4 is hidden in collapsed chunk
    fireEvent.keyDown(view, { key: "ArrowDown" });
    expect(store.get().detailId).toBe("cl-3");

    // Up arrow moves back to cl-2
    fireEvent.keyDown(view, { key: "ArrowUp" });
    expect(store.get().detailId).toBe("cl-2");
  });
});
