import { act, fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithClient, row } from "@/test/utils";
import type { DocumentClauseItem, DocumentItem } from "@/lib/types";
import { store } from "@/state/store";
import { ReviewScreen } from "./ReviewScreen";

const MOCK_DOC: DocumentItem = {
  id: "doc-test",
  title: "Test Document",
  collection_id: "coll-1",
  collection_title: "Test Collection",
  file_type: "md",
  clause_count: 2,
  tagged_count: 1,
  fact_checked_count: 1,
  created_at: "2026-01-01T00:00:00Z",
};

const MOCK_CLAUSES: DocumentClauseItem[] = [
  {
    id: "cl-1",
    external_id: "doc:1:0",
    parent_id: 1,
    sentence_index: 0,
    text: "Sample clause one.",
    length: 18,
    quality: "clean",
    fact_check: "passed",
    has_sfl: true,
    sfl_status: "tagged",
    sfl_data: null,
    latest_fact_check: { verdict: "supported" },
    created_at: null,
  },
];

const MOCK_DETAIL = {
  ...row({ id: 1, external_id: "doc:1:0", title: "Test Document", text: "Sample clause one." }),
  parent: null,
  n_parents: 1,
  context: { before: [], after: [] },
  entities: [],
  sfl: null,
  sfl_raw: null,
  tokens: [],
  groups: {},
  topic: null,
  latest_fact_check: null,
  run: null,
  created_at: null,
};

describe("ReviewScreen (facts 13-17)", () => {
  beforeEach(() => {
    localStorage.clear();
    mockFetch({
      "GET /v1/corpus/documents": { documents: [MOCK_DOC], total: 1 },
      "GET /v1/corpus/documents/doc-test/clauses": {
        document_id: "doc-test",
        clauses: MOCK_CLAUSES,
        total: 1,
      },
      "GET /v1/corpus/chunks/doc:1:0": MOCK_DETAIL,
      "GET /v1/corpus/chunks/cl-1": MOCK_DETAIL,
    });
    store.set({
      tab: "review",
      filters: { document_ids: ["doc-test"] },
      detailId: null,
      listDrawerOpen: false,
      inspectorDrawerOpen: false,
    });
  });

  it("at 1400px or more: DocumentList, DocumentView, and Inspector are all visible inline", async () => {
    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => 1440);
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: true,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    renderWithClient(<ReviewScreen />);
    expect(await screen.findByTestId("document-list")).toBeInTheDocument();
    expect(await screen.findByTestId("document-view")).toBeInTheDocument();
    expect(screen.getByTestId("inspector")).toBeInTheDocument();
  });

  it("between 1024px and 1399px: DocumentList and DocumentView are inline; Inspector is in a drawer", async () => {
    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => 1200);
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: !query.includes("1400"), // medium tier
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    renderWithClient(<ReviewScreen />);
    expect(await screen.findByTestId("document-list")).toBeInTheDocument();
    expect(await screen.findByTestId("document-view")).toBeInTheDocument();
    // Inline inspector is NOT rendered
    expect(screen.queryByTestId("inspector")).not.toBeInTheDocument();

    // Selecting a clause opens the inspector drawer
    const clauseSpan = await screen.findByTestId("clause-span-cl-1");
    fireEvent.click(clauseSpan);
    expect(store.get().inspectorDrawerOpen).toBe(true);
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("below 1024px: DocumentList becomes a drawer; choosing a document closes it", async () => {
    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => 900);
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("768"), // narrow tier
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    renderWithClient(<ReviewScreen />);
    // Inline document list is NOT rendered
    expect(screen.queryByTestId("document-list")).not.toBeInTheDocument();

    // Open list drawer via store (as header button does)
    act(() => {
      store.set({ listDrawerOpen: true });
    });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByTestId("document-list")).toBeInTheDocument();

    // Choosing a document closes the list drawer
    const docCard = await screen.findByTestId("doc-card-doc-test");
    fireEvent.click(docCard);
    expect(store.get().listDrawerOpen).toBe(false);
    expect(await screen.findByTestId("document-view")).toBeInTheDocument();
  });
});
