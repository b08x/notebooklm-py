import type { FactCheckRunSnapshot, GateInfo, ItemStatus, RunEvent, RunItem } from "@/lib/types";

const ALL: ItemStatus[] = ["pending", "active", "waiting", "verified", "refuted", "unverifiable", "skipped", "no_framework", "error"];

function recount(snap: FactCheckRunSnapshot): FactCheckRunSnapshot {
  const counts = Object.fromEntries(ALL.map((s) => [s, 0])) as Record<ItemStatus, number>;
  for (const i of snap.items) counts[i.status] += 1;
  const done = snap.items.filter((i) => !["pending", "active", "waiting"].includes(i.status)).length;
  return { ...snap, counts, done };
}

function patchItem(snap: FactCheckRunSnapshot, itemId: string, patch: Partial<RunItem>): FactCheckRunSnapshot {
  return { ...snap, items: snap.items.map((i) => (i.item_id === itemId ? { ...i, ...patch } : i)) };
}

/** Apply one run event (from SSE) to the snapshot. Events at or below ``last_seq`` are ignored. */
export function applyEvent(snap: FactCheckRunSnapshot, ev: RunEvent): FactCheckRunSnapshot {
  if (ev.seq <= snap.last_seq) return snap;
  let next: FactCheckRunSnapshot = { ...snap, last_seq: ev.seq };
  const itemId = ev.item_id as string | undefined;
  switch (ev.type) {
    case "run_started":
      next.status = "running";
      break;
    case "item_started":
      if (itemId) next = patchItem(next, itemId, { status: "active" });
      break;
    case "gate":
      if (itemId) {
        const gate = ev.gate as GateInfo;
        next = patchItem(next, itemId, { status: "waiting", gate, probability: gate.probability });
        next.waiting = [...next.waiting.filter((w) => w.item_id !== itemId), { item_id: itemId, ...gate }];
      }
      break;
    case "gate_resolved":
      if (itemId) {
        next = patchItem(next, itemId, { status: "active" });
        next.waiting = next.waiting.filter((w) => w.item_id !== itemId);
      }
      break;
    case "sift_step":
      if (itemId) {
        const item = next.items.find((i) => i.item_id === itemId);
        if (item) next = patchItem(next, itemId, { sift: { ...item.sift, [ev.step as string]: ev.status as string } });
      }
      break;
    case "item_done": {
      const item = ev.item as RunItem;
      next = patchItem(next, item.item_id, item);
      next.waiting = next.waiting.filter((w) => w.item_id !== item.item_id);
      break;
    }
    case "item_error":
      if (itemId) next = patchItem(next, itemId, { status: "error", reason: ev.error as string });
      break;
    case "auto_skip":
      next.auto_skip = Boolean(ev.auto_skip);
      break;
    case "run_paused":
      next.status = "paused";
      break;
    case "run_resumed":
      next.status = "running";
      break;
    case "run_finished":
      next.status = ev.status as FactCheckRunSnapshot["status"];
      next.waiting = [];
      break;
  }
  return recount(next);
}

/** The chunk the run is on: the one waiting at the gate, else the active one, else the latest done. */
export function activeItem(snap: FactCheckRunSnapshot): RunItem | null {
  const waiting = snap.waiting[0];
  if (waiting) return snap.items.find((i) => i.item_id === waiting.item_id) ?? null;
  const active = snap.items.find((i) => i.status === "active");
  if (active) return active;
  const done = snap.items.filter((i) => i.status !== "pending");
  return done[done.length - 1] ?? null;
}
