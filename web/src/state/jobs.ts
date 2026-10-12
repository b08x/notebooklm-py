import { followEvents } from "@/lib/api";
import type { JobSnapshot } from "@/lib/types";

export type TrackedJob = JobSnapshot & { startedMs: number };

type Listener = () => void;

const tracked = new Map<string, TrackedJob>();
const controllers = new Map<string, AbortController>();
const invalidators = new Set<() => void>();
const listeners = new Set<Listener>();
// Cached list so useSyncExternalStore sees a stable snapshot identity.
let snapshot: TrackedJob[] = [];

function rebuild(): void {
  snapshot = [...tracked.values()].sort((a, b) => b.startedMs - a.startedMs);
}

function emit(): void {
  rebuild();
  listeners.forEach((l) => l());
}

function patch(id: string, patchValue: Partial<TrackedJob>): void {
  const job = tracked.get(id);
  if (!job) return;
  tracked.set(id, { ...job, ...patchValue });
  emit();
}

/** Register a callback run once for every job that reaches a finished state. */
export function onJobFinished(fn: () => void): () => void {
  invalidators.add(fn);
  return () => invalidators.delete(fn);
}

/** Track a job's SSE event stream so buttons and the tray can follow it. */
export function trackJob(snapshot: JobSnapshot): void {
  if (tracked.has(snapshot.id)) return;
  const job: TrackedJob = { ...snapshot, startedMs: snapshot.started_at ? snapshot.started_at * 1000 : Date.now() };
  tracked.set(snapshot.id, job);
  emit();
  const ctl = new AbortController();
  controllers.set(snapshot.id, ctl);
  void followEvents(
    `/v1/corpus/jobs/${snapshot.id}/events`,
    (ev) => {
      if (ev.type === "progress") {
        patch(snapshot.id, {
          message: String(ev.message ?? job.message),
          done: Number(ev.done ?? job.done),
          total: Number(ev.total ?? job.total),
        });
      } else if (ev.type === "finished") {
        patch(snapshot.id, {
          status: (["done", "failed", "cancelled"] as const).includes(ev.status as never)
            ? (ev.status as TrackedJob["status"])
            : "failed",
          error: ev.error ? String(ev.error) : null,
          done: Number(ev.done ?? snapshot.done),
          total: Number(ev.total ?? snapshot.total),
          finished_at: Date.now() / 1000,
        });
        controllers.delete(snapshot.id);
        ctl.abort();
        invalidators.forEach((fn) => fn());
      }
    },
    { signal: ctl.signal, isFinal: (ev) => ev.type === "finished" },
  ).catch((e: Error) => {
    patch(snapshot.id, { status: "failed", error: e.message, finished_at: Date.now() / 1000 });
    invalidators.forEach((fn) => fn());
  });
}

export function trackedJobs(): TrackedJob[] {
  return snapshot;
}

/** Subscribe to the tracked-jobs store; returns the current list. */
export function subscribeJobs(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Drop all tracked jobs (tests). */
export function resetJobs(): void {
  controllers.forEach((ctl) => ctl.abort());
  controllers.clear();
  tracked.clear();
  emit();
}