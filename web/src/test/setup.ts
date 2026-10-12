import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach, vi } from "vitest";

const mockStorage = (() => {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => store.set(key, String(value)),
    removeItem: (key: string) => { store.delete(key); },
    clear: () => { store.clear(); },
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() { return store.size; },
  };
})();

if (!globalThis.localStorage || typeof globalThis.localStorage.getItem !== "function") {
  Object.defineProperty(globalThis, "localStorage", { value: mockStorage, writable: true, configurable: true });
}
if (typeof window !== "undefined" && (!window.localStorage || typeof window.localStorage.getItem !== "function")) {
  Object.defineProperty(window, "localStorage", { value: mockStorage, writable: true, configurable: true });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  localStorage?.clear();
});

// jsdom lacks these browser APIs used by Radix / cmdk / virtualizer.
class RO {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= RO as unknown as typeof ResizeObserver;
Element.prototype.scrollIntoView ??= function scrollIntoView() {};
HTMLCanvasElement.prototype.getContext = (() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
Element.prototype.hasPointerCapture ??= () => false;
Element.prototype.releasePointerCapture ??= () => {};
// jsdom has no PointerEvent, so fireEvent's pointer events would carry no
// coordinates; MouseEvent takes clientX/clientY through the same init bag.
globalThis.PointerEvent ??= MouseEvent as unknown as typeof PointerEvent;
window.matchMedia ??= ((query: string) => ({
  matches: false,
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
})) as unknown as typeof window.matchMedia;
