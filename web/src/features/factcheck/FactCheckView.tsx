import { useQueryClient } from "@tanstack/react-query";
import { AnimatePresence, motion } from "motion/react";
import { CircleCheck, CircleDashed, CircleDot, CircleSlash, CircleX, ExternalLink, Loader2, Pause, Play, ShieldCheck, Sparkles, Square, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { SectionLabel } from "@/components/ui/section-label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ApiError, followEvents, get, post } from "@/lib/api";
import { useFactCheckRuns, useNotebooks } from "@/lib/queries";
import type { FactCheckRunSnapshot, ItemStatus, JobSnapshot, RunEvent, RunItem } from "@/lib/types";
import { cn, formatElapsed, shortId } from "@/lib/utils";
import { SflChips } from "../DetailPane";
import { type FactCheckScope, actions, store, useApp } from "@/state/store";
import { GateCard } from "./GateCard";
import { activeItem, applyEvent } from "./runState";

const STATUS_ICON: Record<ItemStatus, React.ReactNode> = {
  pending: <CircleDashed className="size-3.5 text-subtle" />,
  active: <Loader2 className="size-3.5 animate-spin text-secondary" />,
  waiting: <CircleDot className="size-3.5 text-warn" />,
  verified: <CircleCheck className="size-3.5 text-ok" />,
  refuted: <CircleX className="size-3.5 text-bad" />,
  unverifiable: <CircleDashed className="size-3.5 text-muted" />,
  skipped: <CircleSlash className="size-3.5 text-muted" />,
  no_framework: <CircleSlash className="size-3.5 text-subtle" />,
  error: <TriangleAlert className="size-3.5 text-bad" />,
};

const SIFT: [string, string][] = [
  ["stop", "Stop"],
  ["investigate_source", "Investigate"],
  ["find_coverage", "Find coverage"],
  ["trace_claim", "Trace"],
];

export async function decide(runId: string, itemId: string, check: boolean): Promise<void> {
  await post(`/v1/corpus/factcheck/runs/${runId}/decision`, { item_id: itemId, decision: check ? "fact_check" : "skip" });
}

export async function setAutoSkip(runId: string, on: boolean): Promise<void> {
  await post(`/v1/corpus/factcheck/runs/${runId}/auto-skip`, { on });
}

function describeScope(scope: FactCheckScope | null): string {
  if (!scope) return "nothing selected";
  if (scope.external_ids?.length) return `${scope.external_ids.length} selected chunk${scope.external_ids.length === 1 ? "" : "s"}`;
  if (scope.run_ids?.length) return `run #${scope.run_ids.join(", #")}`;
  if (scope.document_ids?.length) return `${scope.document_ids.length} document(s)`;
  if (scope.notebook_id) return `notebook ${shortId(scope.notebook_id, 18)}`;
  return "nothing selected";
}

function StartPanel() {
  const scope = useApp((s) => s.factcheckScope);
  const notebooks = useNotebooks();
  const runs = useFactCheckRuns();
  const qc = useQueryClient();
  const [gateSource, setGateSource] = useState<"rule" | "jev">("rule");
  const [mode, setMode] = useState<"interactive" | "auto">("interactive");
  const [autoSkip, setAuto] = useState(false);
  const [sflNeeded, setSflNeeded] = useState<string | null>(null);
  const [tagging, setTagging] = useState<JobSnapshot | null>(null);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    if (!scope) return;
    setBusy(true);
    setSflNeeded(null);
    try {
      const snap = await post<FactCheckRunSnapshot>("/v1/corpus/factcheck/runs", {
        scope,
        gate_source: gateSource,
        gate_mode: mode,
        auto_skip: autoSkip,
      });
      store.set({ factcheckRunId: snap.id });
      void qc.invalidateQueries({ queryKey: ["factcheck-runs"] });
    } catch (e) {
      if (e instanceof ApiError && e.category === "sfl_required") setSflNeeded(e.message);
      else toast.error((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const tagFirst = async () => {
    const job = await post<JobSnapshot>("/v1/corpus/sfl/runs", { scope });
    setTagging(job);
    const ctl = new AbortController();
    await followEvents(
      `/v1/corpus/jobs/${job.id}/events`,
      (ev) => {
        if (ev.type === "progress") setTagging((j) => (j ? { ...j, message: String(ev.message), done: Number(ev.done), total: Number(ev.total) } : j));
        if (ev.type === "finished") {
          setTagging(null);
          if (ev.status === "done") {
            setSflNeeded(null);
            toast.success("SFL tagging finished — start the run");
          } else toast.error(`SFL tagging failed: ${String(ev.error)}`);
        }
      },
      { signal: ctl.signal, isFinal: (ev) => ev.type === "finished" },
    );
  };

  return (
    <div className="mx-auto grid w-full max-w-xl content-start gap-4 p-6">
      <div>
        <h2 className="text-[16px] font-semibold">Start a fact-check run</h2>
        <p className="text-[12.5px] text-muted">Runs keep going when you close the tab; reopen them below.</p>
      </div>
      <div className="grid gap-1.5">
        <SectionLabel className="mb-0">Scope</SectionLabel>
        <Select
          value={scope?.notebook_id ?? (scope ? "__custom" : undefined)}
          onValueChange={(v) => v !== "__custom" && store.set({ factcheckScope: { notebook_id: v } })}
        >
          <SelectTrigger aria-label="Scope">
            <SelectValue placeholder="Choose a notebook…" />
          </SelectTrigger>
          <SelectContent>
            {scope && !scope.notebook_id && <SelectItem value="__custom">{describeScope(scope)}</SelectItem>}
            {(notebooks.data?.items ?? []).map((n) => (
              <SelectItem key={n.id} value={n.id}>
                {n.title ?? shortId(n.id, 24)} · {n.chunks} chunks
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <SectionLabel>Gate</SectionLabel>
          <div role="radiogroup" aria-label="Gate source" className="flex rounded-lg bg-surface p-0.5 shadow-[inset_0_0_0_1px_var(--line)]">
            {(["rule", "jev"] as const).map((g) => (
              <button
                key={g}
                type="button"
                role="radio"
                aria-checked={gateSource === g}
                onClick={() => setGateSource(g)}
                className={cn("flex-1 rounded-md py-1 text-[12px] text-muted transition-[background-color,color,scale] duration-150 active:scale-[0.96]", gateSource === g && "bg-surface-2 text-fg")}
              >
                {g === "jev" ? "Jev model" : "Rule-based"}
              </button>
            ))}
          </div>
        </div>
        <div>
          <SectionLabel>Mode</SectionLabel>
          <div role="radiogroup" aria-label="Gate mode" className="flex rounded-lg bg-surface p-0.5 shadow-[inset_0_0_0_1px_var(--line)]">
            {(["interactive", "auto"] as const).map((m) => (
              <button
                key={m}
                type="button"
                role="radio"
                aria-checked={mode === m}
                onClick={() => setMode(m)}
                className={cn("flex-1 rounded-md py-1 text-[12px] text-muted transition-[background-color,color,scale] duration-150 active:scale-[0.96]", mode === m && "bg-surface-2 text-fg")}
              >
                {m === "interactive" ? "Interactive" : "Batch"}
              </button>
            ))}
          </div>
        </div>
      </div>
      <label className="flex items-center gap-2 text-[13px]">
        <Switch checked={autoSkip} onCheckedChange={setAuto} aria-label="Auto-skip meta-dialogue" /> Auto-skip meta-dialogue
      </label>
      {sflNeeded && (
        <div role="alert" className="flex items-center gap-2 rounded-lg bg-warn/10 p-3 text-[12.5px] text-warn">
          <TriangleAlert className="size-4 shrink-0" />
          <span className="flex-1">{sflNeeded}</span>
          <Button
            onClick={() =>
              void tagFirst().catch((e: Error) => {
                setTagging(null);
                toast.error(e.message);
              })
            }
            disabled={!!tagging}
          >
            {tagging ? <Loader2 className="animate-spin" /> : <Sparkles />}
            {tagging ? `Tagging ${tagging.done ?? 0}/${tagging.total ?? "?"}` : "Tag SFL first"}
          </Button>
        </div>
      )}
      <Button variant="primary" size="md" disabled={!scope || busy} onClick={() => void start()}>
        <ShieldCheck /> Start run over {describeScope(scope)}
      </Button>
      {(runs.data?.items.length ?? 0) > 0 && (
        <div className="mt-2">
          <SectionLabel>Runs</SectionLabel>
          <div className="grid gap-1">
            {runs.data?.items.map((r) => (
              <button
                type="button"
                key={r.id}
                onClick={() => store.set({ factcheckRunId: r.id })}
                className="flex items-center gap-2 rounded-md px-2 py-1.5 text-left text-[12.5px] transition-[background-color] duration-150 hover:bg-surface active:bg-surface-2"
              >
                <code className="font-mono text-[11px] text-subtle">{r.id}</code>
                <span className="flex-1 truncate">{r.label}</span>
                <span className="font-mono text-[11px] text-muted tabular">
                  {r.done}/{r.total}
                </span>
                <Badge tone={r.status === "finished" ? "ok" : r.status === "running" ? "info" : "neutral"}>{r.status}</Badge>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Queue({ snap, selected, onSelect, elapsed }: { snap: FactCheckRunSnapshot; selected: string | null; onSelect: (id: string) => void; elapsed: number }) {
  const pct = snap.total ? (snap.done / snap.total) * 100 : 0;
  const counts: [string, number, string][] = [
    ["verified", snap.counts.verified, "text-ok"],
    ["refuted", snap.counts.refuted, "text-bad"],
    ["skipped", snap.counts.skipped, ""],
    ["waiting", snap.counts.waiting, "text-warn"],
  ];
  return (
    <aside className="flex min-h-0 flex-col border-r border-line" aria-label="Run queue">
      <div className="grid gap-2.5 border-b border-line px-3 py-3.5">
        <div className="flex justify-between text-[12.5px]">
          <span className="truncate" data-testid="run-progress">
            {snap.label} · {snap.done} / {snap.total}
          </span>
          <span className="font-mono text-muted tabular" data-testid="run-elapsed">
            {formatElapsed(elapsed)}
          </span>
        </div>
        <div className="h-1.5 overflow-hidden rounded-[3px] bg-surface-2">
          <i className="block h-full bg-primary transition-[width] duration-300" style={{ width: `${pct}%` }} />
        </div>
        <div className="grid grid-cols-4 gap-1 text-center text-[11px] text-muted" data-testid="run-counts">
          {counts.map(([label, n, tone]) => (
            <div key={label}>
              <b className={cn("block text-[15px] font-semibold text-fg tabular", tone)}>{n}</b>
              {label}
            </div>
          ))}
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-1.5" role="list">
        {snap.items.map((i) => (
          <button
            type="button"
            role="listitem"
            key={i.item_id}
            data-status={i.status}
            onClick={() => onSelect(i.item_id)}
            className={cn(
              "grid w-full grid-cols-[18px_40px_1fr] items-baseline gap-1.5 rounded-md p-1.5 text-left text-[12.5px] text-muted transition-[background-color] duration-150 hover:bg-surface active:bg-surface-2",
              selected === i.item_id && "bg-selection text-fg shadow-[inset_2px_0_0_var(--warn)]",
            )}
          >
            <span className="self-center" aria-label={i.status}>{STATUS_ICON[i.status]}</span>
            <code className="font-mono text-[11px] text-subtle">{String(i.index).padStart(3, "0")}</code>
            <span className="truncate">{i.text}</span>
          </button>
        ))}
      </div>
    </aside>
  );
}

function lineLabel(index: number, text: string): string {
  const speaker = /^\[Speaker ([^\]]+)\]/.exec(text)?.[1];
  return `${String(index).padStart(3, "0")}${speaker !== undefined ? ` · S${speaker}` : ""}`;
}

function Transcript({ item, snap }: { item: RunItem; snap: FactCheckRunSnapshot }) {
  const before = item.context.before;
  const after = item.context.after;
  const own = before.length ? before[before.length - 1].sentence_index + 1 : after.length ? after[0].sentence_index - 1 : 0;
  const lines = [
    ...before.map((l) => ({ ...l, on: false })),
    { external_id: item.external_id, sentence_index: own, text: item.text, on: true },
    ...after.map((l) => ({ ...l, on: false })),
  ];
  return (
    <div>
      <SectionLabel>
        Transcript context · chunk {String(item.index).padStart(3, "0")} of {snap.total}
      </SectionLabel>
      <div className="rounded-xl bg-surface py-1.5 text-[13.5px] shadow-[inset_0_0_0_1px_var(--line)]" data-testid="transcript">
        {lines.map((l) => (
          <div
            key={l.external_id}
            className={cn("grid grid-cols-[72px_minmax(0,1fr)] gap-2.5 px-3.5 py-1.5 text-muted", l.on && "bg-warn/5 text-fg shadow-[inset_2px_0_0_var(--warn)]")}
          >
            <code className={cn("font-mono text-[11.5px] text-subtle", l.on && "text-warn")}>{lineLabel(l.sentence_index, l.text)}</code>
            <span>{l.text}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

const DONE_WITHOUT_SIFT: ItemStatus[] = ["skipped", "no_framework", "error"];

function SiftSteps({ item }: { item: RunItem }) {
  const steps = item.sift_steps ?? {};
  const notRun = DONE_WITHOUT_SIFT.includes(item.status) && !Object.keys(item.sift).length;
  return (
    <div>
      <SectionLabel>SIFT steps</SectionLabel>
      <div className="grid grid-cols-2 gap-1.5 md:grid-cols-4" data-testid="sift">
        {SIFT.map(([key, label]) => {
          const status = item.sift[key] ?? (steps[key] ? "done" : "pending");
          const detail = steps[key] ? Object.values(steps[key]).filter(Boolean).map(String)[0] : null;
          return (
            <div key={key} className="rounded-lg bg-surface px-2.5 py-2 text-[12px] text-muted shadow-[inset_0_0_0_1px_var(--line)]">
              <b className="block text-[12.5px] font-medium text-fg">{label}</b>
              {notRun ? "— not run" : status === "done" ? "✓ done" : status === "running" ? "◐ running" : "◌ pending"}
              {detail && <p className="mt-1 line-clamp-3 text-[11.5px]">{detail}</p>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Evidence({ snap }: { snap: FactCheckRunSnapshot }) {
  const items = snap.items.filter((i) => i.status !== "pending").slice().reverse();
  return (
    <div className="grid gap-2.5" data-testid="evidence">
      {items.length === 0 && <p className="text-[12.5px] text-muted">Evidence appears as chunks are checked.</p>}
      {items.map((i) => {
        const tone = i.status === "verified" ? "ok" : i.status === "refuted" ? "bad" : i.status === "waiting" || i.status === "active" ? "warn" : "neutral";
        return (
          <article key={i.item_id} className="grid gap-1.5 rounded-[10px] bg-surface px-3 py-2.5 text-[12.5px] text-muted shadow-[inset_0_0_0_1px_var(--line)]">
            <header className="flex items-center gap-2">
              <Badge tone={tone} className="font-sans font-semibold tracking-[0.05em] uppercase">
                {i.status === "active" ? "evaluating" : i.status.replace("_", " ")}
              </Badge>
              <code className="font-mono text-[11px] text-subtle">{String(i.index).padStart(3, "0")}</code>
              <span className="ml-auto font-mono text-[11px]">
                {i.confidence !== null ? `p ${i.confidence.toFixed(2)}` : i.probability !== null ? `p ${i.probability.toFixed(2)}` : "—"}
              </span>
            </header>
            <p>{i.rationale ?? i.reason ?? (i.status === "active" ? "Checking sources…" : "")}</p>
            {i.trace_url && (
              <a href={i.trace_url} target="_blank" rel="noreferrer" className="inline-flex w-fit items-center gap-1 text-[12px] text-secondary hover:underline">
                Langfuse trace <ExternalLink className="size-3" />
              </a>
            )}
          </article>
        );
      })}
    </div>
  );
}

function isTyping(e: KeyboardEvent): boolean {
  const t = e.target as HTMLElement | null;
  return !!t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable);
}

export function RunScreen({ runId }: { runId: string }) {
  const [snap, setSnap] = useState<FactCheckRunSnapshot | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [now, setNow] = useState(Date.now());
  const [clock, setClock] = useState<{ start: number; end: number | null }>({ start: Date.now(), end: null });
  const snapRef = useRef<FactCheckRunSnapshot | null>(null);
  snapRef.current = snap;

  useEffect(() => {
    const ctl = new AbortController();
    let cancelled = false;
    void (async () => {
      const initial = await get<FactCheckRunSnapshot>(`/v1/corpus/factcheck/runs/${runId}`);
      if (cancelled) return;
      setClock({ start: Date.now() - initial.elapsed_s * 1000, end: ["finished", "cancelled", "failed"].includes(initial.status) ? Date.now() : null });
      setSnap(initial);
      if (["finished", "cancelled", "failed"].includes(initial.status)) return;
      await followEvents(
        `/v1/corpus/factcheck/runs/${runId}/events`,
        (ev) => {
          if (ev.type === "run_finished") setClock((c) => ({ ...c, end: Date.now() }));
          setSnap((s) => (s ? applyEvent(s, ev as RunEvent) : s));
        },
        { signal: ctl.signal, after: initial.last_seq, isFinal: (ev) => ev.type === "run_finished" },
      ).catch((e: Error) => toast.error(e.message));
    })();
    return () => {
      cancelled = true;
      ctl.abort();
    };
  }, [runId]);

  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  const current = snap ? activeItem(snap) : null;
  const shown = useMemo(() => snap?.items.find((i) => i.item_id === selected) ?? current, [snap, selected, current]);
  const waiting = snap?.waiting[0] ?? null;

  const onDecide = (itemId: string, check: boolean) => {
    void decide(runId, itemId, check).catch((e: Error) => toast.error(e.message));
  };
  const onAutoSkip = (on: boolean) => {
    setSnap((s) => (s ? { ...s, auto_skip: on } : s));
    void setAutoSkip(runId, on).catch((e: Error) => toast.error(e.message));
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (isTyping(e) || e.metaKey || e.ctrlKey || e.altKey) return;
      const s = snapRef.current;
      if (!s) return;
      const w = s.waiting[0];
      const key = e.key.toLowerCase();
      if (key === "y" && w) onDecide(w.item_id, false);
      else if (key === "n" && w) onDecide(w.item_id, true);
      else if (key === "s") onAutoSkip(!s.auto_skip);
      else if (key === "j" || key === "k") {
        const ids = s.items.map((i) => i.item_id);
        const at = ids.indexOf(selected ?? (current?.item_id ?? ids[0]));
        const next = ids[Math.max(0, Math.min(ids.length - 1, at + (key === "j" ? 1 : -1)))];
        setSelected(next);
      } else if (key === "enter" && shown) actions.reveal(shown.external_id);
      else return;
      e.preventDefault();
      e.stopPropagation();
    };
    window.addEventListener("keydown", handler, true);
    return () => window.removeEventListener("keydown", handler, true);
  });

  if (!snap) return <p className="p-6 text-[12.5px] text-muted">Loading run…</p>;
  const finished = ["finished", "cancelled", "failed"].includes(snap.status);
  return (
    <div className="grid min-h-0 flex-1 grid-cols-[280px_minmax(0,1fr)_400px]">
      <Queue snap={snap} selected={shown?.item_id ?? null} onSelect={setSelected} elapsed={((clock.end ?? Math.max(now, Date.now())) - clock.start) / 1000} />
      <main className="flex min-w-0 flex-col gap-3.5 overflow-auto p-4">
        <div className="flex items-center gap-2">
          <Badge tone={snap.gate_source === "jev" ? "primary" : "neutral"}>{snap.gate_source === "jev" ? "Jev gate" : "Rule gate"}</Badge>
          <Badge>{snap.gate_mode}</Badge>
          <Badge tone={finished ? "ok" : snap.status === "paused" ? "warn" : "info"}>{snap.status}</Badge>
          {snap.error && <span className="text-[12px] text-bad">{snap.error}</span>}
          <span className="ml-auto flex gap-1.5">
            {!finished && (
              <Button
                onClick={() =>
                  void post(`/v1/corpus/factcheck/runs/${runId}/${snap.status === "paused" ? "resume" : "pause"}`).then(() =>
                    setSnap((s) => (s ? { ...s, status: s.status === "paused" ? "running" : "paused" } : s)),
                  )
                }
              >
                <AnimatePresence initial={false} mode="popLayout">
                  <motion.span
                    key={snap.status === "paused" ? "play" : "pause"}
                    initial={{ scale: 0.25, opacity: 0, filter: "blur(4px)" }}
                    animate={{ scale: 1, opacity: 1, filter: "blur(0px)" }}
                    exit={{ scale: 0.25, opacity: 0, filter: "blur(4px)" }}
                    transition={{ type: "spring", duration: 0.3, bounce: 0 }}
                    className="grid place-items-center"
                  >
                    {snap.status === "paused" ? <Play /> : <Pause />}
                  </motion.span>
                </AnimatePresence>
                {snap.status === "paused" ? "Resume" : "Pause"}
              </Button>
            )}
            {!finished && (
              <Button variant="destructive" onClick={() => void post(`/v1/corpus/factcheck/runs/${runId}/cancel`)}>
                <Square /> Cancel
              </Button>
            )}
            <Button variant="ghost" onClick={() => store.set({ factcheckRunId: null })}>
              All runs
            </Button>
          </span>
        </div>
        {snap.counts.no_framework > 0 && (
          <p role="note" className="rounded-lg bg-surface-2/60 px-3 py-2 text-[12.5px] text-muted">
            {snap.counts.no_framework} chunk{snap.counts.no_framework === 1 ? "" : "s"} passed the gate but were not checked: the SIFT
            fact-check framework (<code className="font-mono">sift.skill</code> under <code className="font-mono">FACT_CHECK_FRAMEWORK_PATH</code>) is not installed.
          </p>
        )}
        <GateCard itemId={waiting?.item_id ?? null} gate={waiting} autoSkip={snap.auto_skip} onDecide={onDecide} onAutoSkip={onAutoSkip} />
        {snap.auto_skip && !finished && (
          <label className="flex w-fit items-center gap-2 text-[12.5px] text-muted">
            <Switch checked onCheckedChange={onAutoSkip} aria-label="Auto-skip meta-dialogue" /> Auto-skipping meta-dialogue <Kbd>S</Kbd>
          </label>
        )}
        {shown ? (
          <>
            <Transcript item={shown} snap={snap} />
            <SiftSteps item={shown} />
          </>
        ) : (
          <p className="text-[12.5px] text-muted">Waiting for the first chunk…</p>
        )}
      </main>
      <aside className="flex min-h-0 flex-col border-l border-line" aria-label="Evidence">
        <Tabs defaultValue="evidence" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="border-b border-line px-2.5 py-2">
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="sfl">SFL</TabsTrigger>
          </TabsList>
          <div className="min-h-0 flex-1 overflow-auto p-3.5">
            <TabsContent value="evidence">
              <Evidence snap={snap} />
            </TabsContent>
            <TabsContent value="sfl">
              {shown?.sfl ? (
                <>
                  <SectionLabel>SFL metafunctions · {String(shown.index).padStart(3, "0")}</SectionLabel>
                  <SflChips sfl={shown.sfl} />
                </>
              ) : (
                <p className="text-[12.5px] text-muted">No SFL for this chunk.</p>
              )}
            </TabsContent>
          </div>
        </Tabs>
        <div className="flex gap-1.5 border-t border-line px-3.5 py-2.5">
          {shown && (
            <Button onClick={() => actions.reveal(shown.external_id)}>Open chunk</Button>
          )}
          {shown?.trace_url && (
            <Button asChild>
              <a href={shown.trace_url} target="_blank" rel="noreferrer">
                Langfuse <ExternalLink />
              </a>
            </Button>
          )}
        </div>
      </aside>
    </div>
  );
}

export function FactCheckView() {
  const runId = useApp((s) => s.factcheckRunId);
  return runId ? <RunScreen runId={runId} /> : <StartPanel />;
}
