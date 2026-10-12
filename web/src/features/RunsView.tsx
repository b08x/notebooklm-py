import { CloudDownload, Loader2, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { post } from "@/lib/api";
import { useJobs, useRuns } from "@/lib/queries";
import { cn, fmt, shortId } from "@/lib/utils";
import { actions, store } from "@/state/store";

const COLS = "64px minmax(180px,1fr) 92px 96px 70px 70px 64px 64px 64px 120px";

/** chunk_runs with strategy, parent/child counts, mean and p95 length, and the active flag. */
export function RunsView() {
  const runs = useRuns();
  const jobs = useJobs();
  const active = (jobs.data?.items ?? []).filter((j) => j.status === "running" || j.status === "queued");
  const items = runs.data?.items ?? [];
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex items-center gap-2.5 border-b border-line px-3.5 py-2 text-[12px] text-muted">
        <span className="tabular">{fmt.format(items.length)} runs</span>
        <Button className="ml-auto" onClick={() => store.set({ ingestOpen: true })}>
          <CloudDownload /> Ingest artifact
        </Button>
      </div>
      {active.map((j) => (
        <div key={j.id} role="status" className="flex items-center gap-2 border-b border-line bg-primary-soft/40 px-3.5 py-2 text-[12.5px]">
          <Loader2 className="size-3.5 animate-spin text-primary" />
          <span className="font-medium">{j.label}</span>
          <span className="text-muted">{j.message}</span>
          {j.total > 0 && (
            <span className="ml-auto font-mono text-[11.5px] tabular">
              {fmt.format(j.done)}/{fmt.format(j.total)}
            </span>
          )}
        </div>
      ))}
      <div role="table" aria-label="Chunk runs" className="min-h-0 flex-1 overflow-auto text-[13px]">
        <div className="min-w-[880px]">
          <div role="row" className="sticky top-0 grid gap-3 border-b border-line bg-bg px-3.5 py-1.5 text-[11px] font-semibold tracking-[0.06em] text-subtle uppercase" style={{ gridTemplateColumns: COLS }}>
            {["Run", "Document", "Kind", "Strategy", "Parents", "Children", "Mean", "p95", "Active", ""].map((h) => (
              <span role="columnheader" key={h}>{h}</span>
            ))}
          </div>
        {items.map((r) => (
          <div key={r.id} role="row" className={cn("grid items-center gap-3 border-b border-line/60 px-3.5 py-1.5", !r.is_active && "text-muted")} style={{ gridTemplateColumns: COLS }}>
            <span className="font-mono text-[11.5px] tabular">#{r.id}</span>
            <span className="truncate" title={r.document_id}>{r.title ?? shortId(r.document_id, 28)}</span>
            <Badge tone={r.kind === "source" ? "neutral" : "info"}>{r.kind.replace("_", " ")}</Badge>
            <span className="truncate font-mono text-[12px]">{r.strategy}</span>
            <span className="tabular">{fmt.format(r.n_parents)}</span>
            <span className="tabular">{fmt.format(r.n_children)}</span>
            <span className="tabular">{Math.round(r.mean_len)}</span>
            <span className="tabular">{Math.round(r.p95_len)}</span>
            <span>{r.is_active ? <Badge tone="ok">active</Badge> : <span className="text-subtle">—</span>}</span>
            <span className="flex justify-end gap-0.5">
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Tag SFL for run ${r.id}`}
                title="Tag SFL"
                onClick={async () => {
                  await post("/v1/corpus/sfl/runs", { scope: { run_ids: [r.id] } });
                  toast(`SFL tagging started for run #${r.id}`);
                }}
              >
                <Sparkles />
              </Button>
              <Button variant="ghost" size="icon" aria-label={`Fact-check run ${r.id}`} title="Fact-check" onClick={() => actions.startFactCheck({ run_ids: [r.id] })}>
                <ShieldCheck />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete run ${r.id}`}
                title="Delete run"
                onClick={() => actions.requestDelete({ level: "run", ids: [String(r.id)], hide: [], label: `run #${r.id}` })}
              >
                <Trash2 />
              </Button>
            </span>
          </div>
        ))}
        </div>
      </div>
    </div>
  );
}
