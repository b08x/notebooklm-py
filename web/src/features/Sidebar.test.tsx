import { act, fireEvent, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithClient } from "@/test/utils";
import { store } from "@/state/store";
import { SIDEBAR_STORAGE_KEY, Sidebar } from "./Sidebar";

describe("Sidebar (facts 5-8)", () => {
  beforeEach(() => {
    localStorage.clear();
    // Default to a wide desktop screen
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
  });

  it("lists Review, Search, Browse, Map, Runs, Fact-check, and Settings in order", () => {
    renderWithClient(<Sidebar />);
    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar).toBeInTheDocument();

    const expectedLabels = ["Review", "Search", "Browse", "Map", "Runs", "Fact-check", "Settings"];
    const buttons = screen.getAllByRole("button", { name: (n) => expectedLabels.includes(n) });
    expect(buttons.map((b) => b.textContent?.trim())).toEqual(expectedLabels);
  });

  it("defaults to 256px on wide viewports (>= 1280px) and toggles to 64px with persistence", () => {
    renderWithClient(<Sidebar />);
    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar).toHaveStyle({ width: "256px" });

    // Toggle button collapses to 64px
    const toggleBtn = screen.getByTestId("sidebar-toggle");
    fireEvent.click(toggleBtn);
    expect(sidebar).toHaveStyle({ width: "64px" });
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("true");

    // Toggle again expands to 256px
    fireEvent.click(screen.getByTestId("sidebar-toggle"));
    expect(sidebar).toHaveStyle({ width: "256px" });
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("false");
  });

  it("defaults to 64px below 1280px when no choice is stored", () => {
    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => 1100);
    renderWithClient(<Sidebar />);
    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar).toHaveStyle({ width: "64px" });
  });

  it("respects stored persistence even if width < 1280px", () => {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, "false");
    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => 1100);
    renderWithClient(<Sidebar />);
    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar).toHaveStyle({ width: "256px" });
  });

  it("switches to drawer mode when viewport is tiny (< 768px)", async () => {
    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => 600);
    window.matchMedia = vi.fn().mockImplementation((query: string) => ({
      matches: false, // None of the min-width: 768+ matches
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }));

    renderWithClient(<Sidebar />);
    // Aside is not in the DOM in drawer mode unless opened
    expect(screen.queryByTestId("sidebar")).not.toBeInTheDocument();

    // Open drawer via store
    act(() => {
      store.set({ sidebarDrawerOpen: true });
    });
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("Corpus Explorer")).toBeInTheDocument();
  });

  it("navigates to screen when tab button is clicked", () => {
    renderWithClient(<Sidebar />);
    const searchBtn = screen.getByTestId("sidebar-tab-search");
    fireEvent.click(searchBtn);
    expect(store.get().tab).toBe("search");
  });
});
