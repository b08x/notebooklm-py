import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ChunkRow } from "@/lib/types";
import { mockFetch, renderWithClient, row } from "@/test/utils";
import { RowMeta } from "./RowMeta";

const NB = "7f3c2a1e-9b4d-4c6e-8a1f-2d3e4f5a6b7c";
const DOC = "d0c1e2f3-1a2b-4c5d-8e9f-0a1b2c3d4e5f";

const chunk = (over: Partial<ChunkRow>): ChunkRow => ({ ...row(), ...over }) as ChunkRow;

function renderMeta(r: ChunkRow, notebooks: { id: string; title: string | null }[]) {
  mockFetch({
    "GET /v1/corpus/notebooks": { items: notebooks.map((n) => ({ ...n, chunks: 1, documents: 1 })) },
  });
  renderWithClient(<RowMeta row={r} />);
}

describe("RowMeta (facts 4-5)", () => {
  it("shows the notebook and document titles, never the full UUIDs (fact 4)", async () => {
    renderMeta(chunk({ notebook_id: NB, document_id: DOC, title: "Design notes" }), [{ id: NB, title: "Kernel Panic Notebook" }]);
    expect(await screen.findByTitle("Kernel Panic Notebook")).toHaveTextContent("nb Kernel Panic Notebook");
    expect(screen.getByTitle("Design notes")).toHaveTextContent("doc Design notes");
    expect(document.body.textContent).not.toContain(NB);
    expect(document.body.textContent).not.toContain(DOC);
  });

  it("a notebook whose stored title is null shows its short id with an untitled marker (fact 5)", async () => {
    renderMeta(chunk({ notebook_id: NB, document_id: DOC, title: "Design notes" }), [{ id: NB, title: null }]);
    expect(await screen.findByTitle("7f3c2a1e… untitled")).toHaveTextContent("nb 7f3c2a1e… untitled");
    expect(document.body.textContent).not.toContain(NB);
  });

  it("a notebook absent from the notebook list shows the untitled marker, not the full UUID (fact 5)", async () => {
    renderMeta(chunk({ notebook_id: NB, document_id: DOC, title: "Design notes" }), []);
    expect(screen.getByTitle("7f3c2a1e… untitled")).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(NB);
  });

  it("a document with no stored title shows its short id with an untitled marker (fact 5)", async () => {
    renderMeta(chunk({ notebook_id: NB, document_id: DOC, title: null }), [{ id: NB, title: "Kernel Panic Notebook" }]);
    expect(await screen.findByTitle("Kernel Panic Notebook")).toBeInTheDocument();
    expect(screen.getByTitle("d0c1e2f3… untitled")).toHaveTextContent("doc d0c1e2f3… untitled");
    expect(document.body.textContent).not.toContain(DOC);
  });
});
