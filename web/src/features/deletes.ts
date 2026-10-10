import type { QueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { post } from "@/lib/api";
import { getToken } from "@/lib/token";
import type { DeleteLevel } from "@/lib/types";
import { fmt } from "@/lib/utils";
import { store } from "@/state/store";

declare global {
  interface Window {
    __CE_DELETE_GRACE_MS?: number;
  }
}

export function deleteGraceMs(): number {
  return typeof window !== "undefined" && typeof window.__CE_DELETE_GRACE_MS === "number"
    ? window.__CE_DELETE_GRACE_MS
    : 5000;
}

interface Pending {
  level: DeleteLevel;
  ids: string[];
  hide: string[];
  timer: ReturnType<typeof setTimeout>;
}

const pending = new Map<string, Pending>();
let seq = 0;

function unhide(hide: string[]) {
  store.set((s) => ({ hidden: s.hidden.filter((h) => !hide.includes(h)) }));
}

async function commit(key: string, qc: QueryClient) {
  const p = pending.get(key);
  if (!p) return;
  pending.delete(key);
  try {
    const receipt = await post<{ counts: { clauses: number } }>("/v1/corpus/delete", {
      level: p.level,
      ids: p.ids,
      reason: "other",
    });
    toast.success(`Deleted ${fmt.format(receipt.counts.clauses)} ${receipt.counts.clauses === 1 ? "chunk" : "chunks"}`);
    store.set((s) => ({
      detailId: p.hide.includes(s.detailId ?? "") ? null : s.detailId,
      selected: s.selected.filter((id) => !p.hide.includes(id)),
    }));
    await qc.invalidateQueries();
  } catch (e) {
    unhide(p.hide);
    toast.error(`Delete failed: ${(e as Error).message}`);
  }
}

/**
 * Confirmed delete with an undo window: rows disappear at once, the request is
 * sent when the grace period ends (or the page is hidden), Undo cancels it.
 */
export function scheduleDelete(
  qc: QueryClient,
  req: { level: DeleteLevel; ids: string[]; hide: string[]; label: string },
): string {
  const key = `del-${++seq}`;
  store.set((s) => ({ hidden: Array.from(new Set([...s.hidden, ...req.hide])) }));
  const timer = setTimeout(() => void commit(key, qc), deleteGraceMs());
  pending.set(key, { level: req.level, ids: req.ids, hide: req.hide, timer });
  toast(`Deleting ${req.label}`, {
    id: key,
    duration: deleteGraceMs(),
    action: {
      label: "Undo",
      onClick: () => undoDelete(key),
    },
  });
  return key;
}

export function undoDelete(key: string): boolean {
  const p = pending.get(key);
  if (!p) return false;
  clearTimeout(p.timer);
  pending.delete(key);
  unhide(p.hide);
  toast.dismiss(key);
  toast("Delete undone");
  return true;
}

/** Send pending deletes now (page is going away). */
export function flushDeletes(): void {
  const token = getToken();
  for (const [key, p] of pending) {
    clearTimeout(p.timer);
    pending.delete(key);
    void fetch("/v1/corpus/delete", {
      method: "POST",
      keepalive: true,
      headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: JSON.stringify({ level: p.level, ids: p.ids, reason: "other" }),
    });
  }
}

export function pendingDeleteCount(): number {
  return pending.size;
}

if (typeof window !== "undefined") window.addEventListener("pagehide", flushDeletes);

/** Test hook: drop pending deletes and their toasts without sending anything. */
export function resetDeletes(): void {
  for (const p of pending.values()) clearTimeout(p.timer);
  pending.clear();
  toast.dismiss();
}
