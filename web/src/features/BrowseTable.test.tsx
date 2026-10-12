import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { mockFetch, renderWithClient, row } from "@/test/utils";
import { getRowIds } from "@/state/rows";
import { store } from "@/state/store";
import { BrowseTable } from "./BrowseTable";

describe("BrowseTable (fact-15)", () => {
  it("renders a virtualized window over keyset pages and opens rows", async () => {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 720 });
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 900 });
    const page1 = Array.from({ length: 200 }, (_, i) => row({ id: i + 1, external_id: `d:1:${i}`, text: `chunk ${i}` }));
    const calls = mockFetch({
      "GET /v1/corpus/chunks": (call) =>
        call.path.includes("cursor=200")
          ? { items: [row({ id: 201, external_id: "d:1:200", text: "chunk 200", quality: "base64", fact_check: "passed" })], next_cursor: null, total: 201 }
          : { items: page1, next_cursor: 200, total: 201 },
    });
    renderWithClient(<BrowseTable />);
    await waitFor(() => expect(screen.getByTestId("browse-total")).toHaveTextContent("201 chunks"));
    const rendered = document.querySelectorAll('[data-row-id]').length;
    expect(rendered).toBeGreaterThan(0);
    expect(rendered).toBeLessThan(200); // only the visible window is in the DOM
    expect(calls.some((c) => c.path.includes("cursor=200"))).toBe(false);
    const scroller = screen.getByTestId("browse-scroll");
    scroller.scrollTop = 36 * 190;
    fireEvent.scroll(scroller);
    await waitFor(() => expect(getRowIds()).toHaveLength(201));
    expect(calls.some((c) => c.path.includes("cursor=200"))).toBe(true);
    expect(document.querySelector('[data-row-id="d:1:0"]')).toBeNull(); // scrolled out of the window
    const visible = document.querySelector("[data-row-id]") as HTMLElement;
    fireEvent.click(visible);
    expect(store.get().detailId).toBe(visible.dataset.rowId);
    act(() => store.set({ hidden: ["d:1:1"] }));
    await waitFor(() => expect(getRowIds()).toHaveLength(200));
  });

  it("resizes via drag handles, resets on double-click, and hides columns from the Columns menu", async () => {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 720 });
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 900 });
    mockFetch({ "GET /v1/corpus/chunks": { items: [row()], next_cursor: null, total: 1 } });
    renderWithClient(<BrowseTable />);
    await screen.findByRole("columnheader", { name: /Len/ });

    // Drag the Len handle 40px right: 56 -> 96, persisted under ce-browse-colsizing.
    const handle = screen.getByTestId("resize-len");
    fireEvent.mouseDown(handle, { clientX: 500 });
    fireEvent.mouseMove(document, { clientX: 540 });
    fireEvent.mouseUp(document, { clientX: 540 });
    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem("ce-browse-colsizing") ?? "{}")).toMatchObject({ len: 96 });
      expect(document.querySelector("div[role=row]")?.getAttribute("style")).toContain("96px");
    });

    // Double-click the handle to reset the column to its default size.
    fireEvent.doubleClick(handle);
    await waitFor(() => expect(JSON.parse(localStorage.getItem("ce-browse-colsizing") ?? "{}").len).toBeUndefined());

    // Hide the Kind column from the Columns dropdown; it is persisted.
    await userEvent.click(screen.getByTestId("columns-trigger"));
    fireEvent.click(await screen.findByTestId("column-toggle-kind"));
    await waitFor(() => expect(screen.queryByRole("columnheader", { name: /Kind/ })).toBeNull());
    expect(JSON.parse(localStorage.getItem("ce-browse-colvis") ?? "{}")).toMatchObject({ kind: false });
  });

  it("restores saved column sizing and visibility on mount", async () => {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 720 });
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 900 });
    localStorage.setItem("ce-browse-colsizing", JSON.stringify({ len: 123 }));
    localStorage.setItem("ce-browse-colvis", JSON.stringify({ kind: false }));
    mockFetch({ "GET /v1/corpus/chunks": { items: [row()], next_cursor: null, total: 1 } });
    renderWithClient(<BrowseTable />);
    await screen.findByTestId("browse-total");
    expect(await screen.findByRole("columnheader", { name: /Len/ })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: /Kind/ })).toBeNull();
    expect(document.querySelector("div[role=row]")?.getAttribute("style")).toContain("123px");
  });
});

describe("BrowseTable (fact-6)", () => {
  it("gives each resizable column a drag handle and resizes a column other than Len", async () => {
    Object.defineProperty(HTMLElement.prototype, "offsetHeight", { configurable: true, value: 720 });
    Object.defineProperty(HTMLElement.prototype, "offsetWidth", { configurable: true, value: 900 });
    mockFetch({ "GET /v1/corpus/chunks": { items: [row()], next_cursor: null, total: 1 } });
    renderWithClient(<BrowseTable />);
    await screen.findByRole("columnheader", { name: /Len/ });

    // Walk every rendered column header and record which resize handle, if any, it holds.
    const handleIds = screen
      .getAllByRole("columnheader")
      .map((h) => within(h).queryByRole("separator")?.dataset.testid?.replace(/^resize-/, "") ?? null);
    // Chunk (text) and Selector (select) have enableResizing: false in BrowseTable.tsx, so they have no handle.
    // Fact 6 says every column has one; the source does not match that for these two columns.
    expect(handleIds.filter((id) => id === null)).toHaveLength(2);
    expect(handleIds.filter((id): id is string => id !== null)).toEqual(["id", "doc", "kind", "len", "quality", "fc"]);

    // Drag the Document handle 40px right: 112 -> 152.
    const handle = screen.getByTestId("resize-doc");
    fireEvent.mouseDown(handle, { clientX: 500 });
    fireEvent.mouseMove(document, { clientX: 540 });
    fireEvent.mouseUp(document, { clientX: 540 });
    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem("ce-browse-colsizing") ?? "{}")).toMatchObject({ doc: 152 });
      expect(document.querySelector("div[role=row]")?.getAttribute("style")).toContain("152px");
    });
  });
});
