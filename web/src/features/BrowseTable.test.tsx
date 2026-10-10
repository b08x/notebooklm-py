import { act, fireEvent, screen, waitFor } from "@testing-library/react";
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
});
