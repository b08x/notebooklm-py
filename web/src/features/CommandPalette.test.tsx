import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useHotkeys } from "@/hooks/useHotkeys";
import { resetStore, store } from "@/state/store";
import { CommandPalette } from "./CommandPalette";

function Harness() {
  useHotkeys();
  return (
    <>
      <input id="corpus-search" aria-label="Search the corpus" />
      <CommandPalette />
    </>
  );
}

function setup() {
  resetStore();
  document.documentElement.classList.add("dark");
  render(<Harness />);
  act(() => {
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
  });
}

const choose = (name: RegExp) => fireEvent.click(screen.getByRole("option", { name }));

describe("CommandPalette (fact-41)", () => {
  it("opens with Ctrl-K and switches tabs", () => {
    setup();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    choose(/Runs/);
    expect(store.get().tab).toBe("runs");
    expect(store.get().paletteOpen).toBe(false);
  });

  it("toggles the theme", () => {
    setup();
    choose(/Toggle theme/);
    expect(document.documentElement.classList.contains("dark")).toBe(false);
    expect(localStorage.getItem("ce-theme")).toBe("light");
  });

  it("starts a fact-check run for the selection and deletes the selection", () => {
    resetStore();
    store.set({ selected: ["a:1:0", "b:1:0"] });
    render(<Harness />);
    act(() => {
      fireEvent.keyDown(window, { key: "k", metaKey: true });
    });
    choose(/Delete selection \(2\)/);
    expect(store.get().deleteRequest).toMatchObject({ level: "clause", ids: ["a:1:0", "b:1:0"] });
    act(() => store.set({ deleteRequest: null, paletteOpen: true }));
    choose(/Start fact-check run/);
    expect(store.get().tab).toBe("factcheck");
    expect(store.get().factcheckScope).toEqual({ external_ids: ["a:1:0", "b:1:0"] });
  });

  it("focuses search and filters commands by typing", async () => {
    setup();
    fireEvent.change(screen.getByPlaceholderText("Type a command…"), { target: { value: "focus" } });
    expect(screen.getAllByRole("option")).toHaveLength(1);
    choose(/Focus search/);
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    expect(document.activeElement).toBe(screen.getByLabelText("Search the corpus"));
  });
});
