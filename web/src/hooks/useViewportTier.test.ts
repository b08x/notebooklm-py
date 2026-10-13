import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { BP_INSPECTOR, BP_LIST, BP_SIDEBAR } from "@/lib/layout";
import { useViewportTier } from "./useViewportTier";

describe("useViewportTier (facts 8, 11, 16, 17)", () => {
  let listeners: Map<string, Set<(e: { matches: boolean }) => void>>;
  let currentWidth: number;

  beforeEach(() => {
    listeners = new Map();
    currentWidth = 1440;

    vi.spyOn(window, "innerWidth", "get").mockImplementation(() => currentWidth);

    window.matchMedia = vi.fn().mockImplementation((query: string) => {
      const minWidthMatch = query.match(/min-width:\s*(\d+)px/);
      const minWidth = minWidthMatch ? parseInt(minWidthMatch[1], 10) : 0;

      if (!listeners.has(query)) {
        listeners.set(query, new Set());
      }

      return {
        get matches() {
          return currentWidth >= minWidth;
        },
        media: query,
        onchange: null,
        addListener: vi.fn(),
        removeListener: vi.fn(),
        addEventListener: vi.fn((event: string, handler: (e: { matches: boolean }) => void) => {
          if (event === "change") {
            listeners.get(query)?.add(handler);
          }
        }),
        removeEventListener: vi.fn((event: string, handler: (e: { matches: boolean }) => void) => {
          if (event === "change") {
            listeners.get(query)?.delete(handler);
          }
        }),
        dispatchEvent: vi.fn(),
      };
    });
  });

  function setWidth(w: number) {
    currentWidth = w;
    for (const [query, handlers] of listeners.entries()) {
      const minWidthMatch = query.match(/min-width:\s*(\d+)px/);
      const minWidth = minWidthMatch ? parseInt(minWidthMatch[1], 10) : 0;
      const matches = currentWidth >= minWidth;
      for (const h of handlers) {
        h({ matches });
      }
    }
  }

  it("returns 'wide' at BP_INSPECTOR (1400px) and above", () => {
    currentWidth = BP_INSPECTOR;
    const { result } = renderHook(() => useViewportTier());
    expect(result.current).toBe("wide");

    act(() => setWidth(BP_INSPECTOR + 200));
    expect(result.current).toBe("wide");
  });

  it("returns 'medium' between BP_LIST (1024px) and BP_INSPECTOR - 1 (1399px)", () => {
    currentWidth = BP_INSPECTOR - 1;
    const { result } = renderHook(() => useViewportTier());
    expect(result.current).toBe("medium");

    act(() => setWidth(BP_LIST));
    expect(result.current).toBe("medium");
  });

  it("returns 'narrow' between BP_SIDEBAR (768px) and BP_LIST - 1 (1023px)", () => {
    currentWidth = BP_LIST - 1;
    const { result } = renderHook(() => useViewportTier());
    expect(result.current).toBe("narrow");

    act(() => setWidth(BP_SIDEBAR));
    expect(result.current).toBe("narrow");
  });

  it("returns 'tiny' below BP_SIDEBAR (767px and below)", () => {
    currentWidth = BP_SIDEBAR - 1;
    const { result } = renderHook(() => useViewportTier());
    expect(result.current).toBe("tiny");

    act(() => setWidth(375));
    expect(result.current).toBe("tiny");
  });

  it("transitions reactively across all breakpoints", () => {
    currentWidth = BP_INSPECTOR + 40;
    const { result } = renderHook(() => useViewportTier());
    expect(result.current).toBe("wide");

    act(() => setWidth(BP_INSPECTOR - 1));
    expect(result.current).toBe("medium");

    act(() => setWidth(BP_LIST - 1));
    expect(result.current).toBe("narrow");

    act(() => setWidth(BP_SIDEBAR - 1));
    expect(result.current).toBe("tiny");

    act(() => setWidth(BP_INSPECTOR));
    expect(result.current).toBe("wide");
  });
});
