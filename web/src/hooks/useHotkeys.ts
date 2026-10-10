import { useEffect } from "react";
import { focusSearch } from "@/features/CommandPalette";
import { deleteSelection } from "@/features/SelectionBar";
import { toggleRow } from "@/features/selection";
import { getRowIds } from "@/state/rows";
import { TABS, actions, store } from "@/state/store";

function typing(target: EventTarget | null): boolean {
  const t = target as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
}

function modalOpen(): boolean {
  const s = store.get();
  return s.paletteOpen || s.askOpen || s.ingestOpen || s.shortcutsOpen || !!s.deleteRequest;
}

/** Workbench keys: ⌘K, /, j/k, x, Enter, Backspace, ?, Esc, 1-5. */
export function handleKey(e: KeyboardEvent): boolean {
  const s = store.get();
  if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
    store.set({ paletteOpen: !s.paletteOpen });
    return true;
  }
  if (e.metaKey || e.ctrlKey || e.altKey || typing(e.target) || modalOpen()) return false;
  if (s.tab === "factcheck" && s.factcheckRunId && ["y", "n", "s", "j", "k", "Enter"].includes(e.key)) return false;
  const ids = getRowIds();
  const at = s.cursor ? ids.indexOf(s.cursor) : -1;
  switch (e.key) {
    case "/":
      focusSearch();
      return true;
    case "?":
      store.set({ shortcutsOpen: true });
      return true;
    case "j":
    case "k": {
      if (!ids.length) return false;
      const next = e.key === "j" ? Math.min(ids.length - 1, at + 1) : Math.max(0, at - 1);
      store.set({ cursor: ids[next] });
      document.querySelector(`[data-row-id="${CSS.escape(ids[next])}"]`)?.scrollIntoView({ block: "nearest" });
      return true;
    }
    case "x":
      if (!s.cursor) return false;
      toggleRow(s.cursor, e.shiftKey);
      return true;
    case "Enter":
      if (!s.cursor) return false;
      actions.open(s.cursor);
      return true;
    case "Backspace":
    case "Delete":
      if (s.selected.length) deleteSelection();
      else if (s.detailId) actions.requestDelete({ level: "clause", ids: [s.detailId], hide: [s.detailId], label: "this chunk" });
      else return false;
      return true;
    case "Escape":
      if (s.selected.length) actions.clearSelection();
      else if (s.detailId) store.set({ detailId: null });
      else return false;
      return true;
    default: {
      const n = Number(e.key);
      if (n >= 1 && n <= TABS.length) {
        actions.setTab(TABS[n - 1].id);
        return true;
      }
      return false;
    }
  }
}

export function useHotkeys(): void {
  useEffect(() => {
    const listener = (e: KeyboardEvent) => {
      if (handleKey(e)) e.preventDefault();
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);
}
