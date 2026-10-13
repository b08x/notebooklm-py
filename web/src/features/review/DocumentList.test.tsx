import { fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { mockFetch, renderWithClient } from "@/test/utils";
import type { DocumentItem } from "@/lib/types";
import { store } from "@/state/store";
import { COLLAPSED_COLLECTIONS_KEY, DocumentList } from "./DocumentList";

const MOCK_DOCS: DocumentItem[] = [
  {
    id: "doc-1",
    title: "Kernel Architecture Notes",
    collection_id: "coll-a",
    collection_title: "Operating Systems",
    file_type: "md",
    clause_count: 50,
    tagged_count: 25,
    fact_checked_count: 10,
    created_at: "2026-01-01T00:00:00Z",
  },
  {
    id: "doc-2",
    title: "Memory Management Guide",
    collection_id: "coll-a",
    collection_title: "Operating Systems",
    file_type: "pdf",
    clause_count: 30,
    tagged_count: 0,
    fact_checked_count: 0,
    created_at: "2026-01-02T00:00:00Z",
  },
  {
    id: "doc-3",
    title: "Linguistics Field Study",
    collection_id: "coll-b",
    collection_title: "Systemic Functional Linguistics",
    file_type: "txt",
    clause_count: 40,
    tagged_count: 40,
    fact_checked_count: 5,
    created_at: "2026-01-03T00:00:00Z",
  },
];

describe("DocumentList (facts 24-32)", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch({
      "GET /v1/corpus/documents": { documents: MOCK_DOCS, total: MOCK_DOCS.length },
    });
  });

  it("groups documents under Collection headers and never uses the word 'Notebook'", async () => {
    renderWithClient(<DocumentList />);
    expect(await screen.findByText("Collection: Operating Systems")).toBeInTheDocument();
    expect(screen.getByText("Collection: Systemic Functional Linguistics")).toBeInTheDocument();
    expect(screen.queryByText(/Notebook/i)).toBeNull();
  });

  it("displays document card metadata: title, file type, clause count, tagged %, checked count", async () => {
    renderWithClient(<DocumentList />);
    expect(await screen.findByText("Kernel Architecture Notes")).toBeInTheDocument();
    expect(screen.getByText("md")).toBeInTheDocument();
    expect(screen.getByText("50 cls")).toBeInTheDocument();
    expect(screen.getByText("50% tagged")).toBeInTheDocument();
    expect(screen.getByText("10 checked")).toBeInTheDocument();
  });

  it("filters documents by title search input", async () => {
    renderWithClient(<DocumentList />);
    await screen.findByText("Kernel Architecture Notes");

    const searchInput = screen.getByLabelText("Filter documents by title");
    fireEvent.change(searchInput, { target: { value: "Linguistics" } });

    expect(screen.getByText("Linguistics Field Study")).toBeInTheDocument();
    expect(screen.queryByText("Kernel Architecture Notes")).toBeNull();
    expect(screen.queryByText("Memory Management Guide")).toBeNull();
  });

  it("filters documents using filter tabs (All, Untagged, Tagged, Fact-checked)", async () => {
    renderWithClient(<DocumentList />);
    await screen.findByText("Kernel Architecture Notes");

    // Click Untagged tab (doc-2 has tagged_count: 0)
    fireEvent.click(screen.getByTestId("document-filter-untagged"));
    expect(screen.getByText("Memory Management Guide")).toBeInTheDocument();
    expect(screen.queryByText("Kernel Architecture Notes")).toBeNull();
    expect(screen.queryByText("Linguistics Field Study")).toBeNull();

    // Click Tagged tab (doc-1 and doc-3 have tagged_count > 0)
    fireEvent.click(screen.getByTestId("document-filter-tagged"));
    expect(screen.getByText("Kernel Architecture Notes")).toBeInTheDocument();
    expect(screen.getByText("Linguistics Field Study")).toBeInTheDocument();
    expect(screen.queryByText("Memory Management Guide")).toBeNull();

    // Click Fact-checked tab (doc-1 and doc-3 have fact_checked_count > 0)
    fireEvent.click(screen.getByTestId("document-filter-factchecked"));
    expect(screen.getByText("Kernel Architecture Notes")).toBeInTheDocument();
    expect(screen.getByText("Linguistics Field Study")).toBeInTheDocument();
    expect(screen.queryByText("Memory Management Guide")).toBeNull();
  });

  it("toggling collection collapses its documents and persists to localStorage", async () => {
    renderWithClient(<DocumentList />);
    await screen.findByText("Kernel Architecture Notes");

    // Initially doc-1 and doc-2 in coll-a are visible
    expect(screen.getByText("Kernel Architecture Notes")).toBeInTheDocument();

    // Click toggle for coll-a
    const toggleBtn = screen.getByTestId("collection-toggle-coll-a");
    fireEvent.click(toggleBtn);

    // coll-a docs are collapsed
    expect(screen.queryByText("Kernel Architecture Notes")).toBeNull();
    expect(screen.queryByText("Memory Management Guide")).toBeNull();
    // coll-b doc is still visible
    expect(screen.getByText("Linguistics Field Study")).toBeInTheDocument();

    // Persisted in localStorage
    const stored = JSON.parse(localStorage.getItem(COLLAPSED_COLLECTIONS_KEY) || "[]");
    expect(stored).toContain("coll-a");

    // Click toggle again expands
    fireEvent.click(toggleBtn);
    expect(screen.getByText("Kernel Architecture Notes")).toBeInTheDocument();
  });

  it("selecting a document updates filters.document_ids and clears detailId", async () => {
    store.set({ detailId: "clause-99", listDrawerOpen: true });
    renderWithClient(<DocumentList />);
    await screen.findByText("Linguistics Field Study");

    const docBtn = screen.getByTestId("doc-card-doc-3");
    fireEvent.click(docBtn);

    expect(store.get().filters.document_ids).toEqual(["doc-3"]);
    expect(store.get().detailId).toBeNull();
    expect(store.get().listDrawerOpen).toBe(false);
  });
});
