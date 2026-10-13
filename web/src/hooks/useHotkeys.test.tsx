import { fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { setRowIds } from "@/state/rows";
import { resetStore, store } from "@/state/store";
import { useHotkeys } from "./useHotkeys";

function Harness() {
  useHotkeys();
  return <input aria-label="field" />;
}

const press = (key: string, opts: Record<string, unknown> = {}) => fireEvent.keyDown(window, { key, ...opts });

describe("keyboard shortcuts (fact-42, fact-24)", () => {
  beforeEach(() => {
    resetStore();
    setRowIds(["a", "b", "c", "d"]);
    render(<Harness />);
  });

  it("j/k move, Enter opens, x selects, shift-x extends a range", () => {
    press("j");
    expect(store.get().cursor).toBe("a");
    press("j");
    press("j");
    press("k");
    expect(store.get().cursor).toBe("b");
    press("Enter");
    expect(store.get().detailId).toBe("b");
    press("x");
    expect(store.get().selected).toEqual(["b"]);
    press("j");
    press("j");
    press("x", { shiftKey: true });
    expect(store.get().selected).toEqual(["b", "c", "d"]);
    press("Escape");
    expect(store.get().selected).toEqual([]);
    press("Escape");
    expect(store.get().detailId).toBeNull();
  });

  it("Backspace deletes the selection, or the open chunk", () => {
    store.set({ selected: ["a", "c"] });
    press("Backspace");
    expect(store.get().deleteRequest).toMatchObject({ level: "clause", ids: ["a", "c"] });
    store.set({ deleteRequest: null, selected: [], detailId: "d" });
    press("Delete");
    expect(store.get().deleteRequest).toMatchObject({ ids: ["d"], hide: ["d"] });
  });

  it("? opens the sheet, / focuses search, digits switch tabs, typing is ignored", () => {
    press("?");
    expect(store.get().shortcutsOpen).toBe(true);
    store.set({ shortcutsOpen: false });
    press("4");
    expect(store.get().tab).toBe("map");
    press("/");
    expect(store.get().tab).toBe("search");
    const input = document.querySelector("input") as HTMLInputElement;
    fireEvent.keyDown(input, { key: "j" });
    expect(store.get().cursor).toBeNull();
    store.set({ paletteOpen: true });
    press("j");
    expect(store.get().cursor).toBeNull();
  });
});
