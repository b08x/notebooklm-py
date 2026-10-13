import { act, fireEvent, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { mockFetch, renderWithClient, row } from "@/test/utils";
import { store } from "@/state/store";
import {
  DEFAULT_INSPECTOR_WIDTH,
  INSPECTOR_WIDTH_KEY,
  Inspector,
} from "./Inspector";

const DETAIL = {
  ...row({
    id: 1,
    external_id: "doc:1:0",
    title: "Operating Systems Internals",
    text: "Kernel memory is divided into zones.",
    sentence_index: 0,
    has_sfl: true,
  }),
  parent: {
    id: 10,
    index: 0,
    child_start: 0,
    child_end: 35,
    text: "Kernel memory is divided into zones. User memory is virtual.",
    n_children: 2,
    char_start: 0,
    char_end: 60,
  },
  n_parents: 1,
  context: { before: [], after: [] },
  entities: [{ text: "Kernel", label: "NOUN" }],
  sfl: {
    ideational: {
      participants: ["Kernel memory"],
      processes: ["is divided"],
      circumstances: ["into zones"],
    },
    interpersonal: {
      tenor: ["neutral"],
      mood: ["declarative"],
      modality: ["none"],
    },
  },
  sfl_raw: null,
  tokens: [],
  groups: {},
  topic: "Memory",
  latest_fact_check: {
    verdict: "supported",
    confidence: 0.95,
    model: "gemini-2.5-pro",
  },
  run: { id: 1, strategy: "recursive", is_active: true },
  created_at: null,
};

describe("Inspector (facts 43-49)", () => {
  beforeEach(() => {
    localStorage.clear();
    // Default to wide viewport (>=1400px)
    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => 1440);
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: query.includes("1400") || query.includes("1024") || query.includes("768"),
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));
    mockFetch({
      "GET /v1/corpus/chunks/doc:1:0": DETAIL,
      "GET /v1/corpus/neighbors/doc:1:0": { items: [], near_dup_threshold: 0.15 },
    });
    store.set({ detailId: null, detailTab: "context" });
  });

  it("shows 'Select a clause in the document.' with no clause selected", () => {
    renderWithClient(<Inspector />);
    expect(screen.getByTestId("inspector-empty")).toHaveTextContent(
      "Select a clause in the document.",
    );
  });

  it("header shows document title and chunk/clause number", async () => {
    renderWithClient(<Inspector />);
    store.set({ detailId: "doc:1:0" });

    expect(await screen.findByTestId("inspector-doc-title")).toHaveTextContent(
      "Operating Systems Internals",
    );
    expect(screen.getByText(/Chunk 1 · Clause 1:0/)).toBeInTheDocument();
  });

  it("switches between Context, Linguistics, Similar, and Raw tabs", async () => {
    renderWithClient(<Inspector />);
    store.set({ detailId: "doc:1:0" });
    await screen.findByTestId("inspector-doc-title");

    // Initially in Context tab: shows parent context
    expect(screen.getByTestId("parent-context")).toBeInTheDocument();

    // Click Linguistics tab using userEvent
    await userEvent.click(screen.getByRole("tab", { name: "Linguistics" }));
    expect(screen.getByTestId("entities")).toHaveTextContent("Kernel");
    expect(screen.getByTestId("sfl")).toBeInTheDocument();

    // Click Raw tab
    await userEvent.click(screen.getByRole("tab", { name: "Raw" }));
    expect(screen.getByText(/"external_id": "doc:1:0"/)).toBeInTheDocument();
  });

  it("pinned footer shows SFL tag state and fact-check verdict with action buttons", async () => {
    renderWithClient(<Inspector />);
    store.set({ detailId: "doc:1:0" });
    await screen.findByTestId("inspector-doc-title");

    const footer = screen.getByTestId("inspector-footer");
    expect(footer).toBeInTheDocument();
    expect(footer).toHaveTextContent("Tagged");
    expect(footer).toHaveTextContent("supported");

    // Fact-check button triggers startFactCheck
    const fcBtn = screen.getByTestId("inspector-factcheck-btn");
    fireEvent.click(fcBtn);
    expect(store.get().factcheckScope).toEqual({ external_ids: ["doc:1:0"] });
  });

  it("resizes via drag handle and persists width in localStorage", () => {
    renderWithClient(<Inspector />);
    const inspector = screen.getByTestId("inspector");
    expect(inspector).toHaveStyle({ width: `${DEFAULT_INSPECTOR_WIDTH}px` });

    const handle = screen.getByTestId("inspector-resize-handle");

    // Drag 40px left (making inspector wider from 360 to 400px)
    fireEvent.mouseDown(handle, { clientX: 1000 });
    fireEvent.mouseMove(window, { clientX: 960 });
    fireEvent.mouseUp(window);

    expect(inspector).toHaveStyle({ width: "400px" });
    expect(localStorage.getItem(INSPECTOR_WIDTH_KEY)).toBe("400");
  });

  it("renders inside Drawer when viewport tier is not wide (<1400px)", async () => {
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

    renderWithClient(<Inspector />);
    // In medium tier, drawer is closed by default unless open
    expect(screen.queryByTestId("inspector")).not.toBeInTheDocument();

    // Open drawer via store
    act(() => {
      store.set({ inspectorDrawerOpen: true });
    });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});
