import type { Health } from "@/lib/types";
import { fmt } from "@/lib/utils";
import { store } from "@/state/store";

function Dot({ tone }: { tone: "ok" | "warn" | "bad" }) {
  return <i className="mr-1.5 inline-block size-[7px] rounded-full align-[1px]" style={{ background: `var(--${tone})` }} />;
}

/** Live status: Postgres, the Ollama embedder, and running ingest / fact-check jobs. */
export function StatusFooter({ health }: { health: Health | undefined }) {
  const pg = health?.postgres;
  const emb = health?.embedder;
  const jobs = health?.jobs ?? [];
  const runs = health?.factcheck_runs ?? [];
  return (
    <footer className="flex h-7 items-center gap-3.5 overflow-hidden border-t border-line px-3 font-mono text-[11px] whitespace-nowrap text-muted" data-testid="status-footer">
      <span data-testid="status-postgres">
        <Dot tone={!pg ? "warn" : pg.ok ? "ok" : "bad"} />
        postgres{pg?.ok && pg.latency_ms !== undefined ? ` ${pg.latency_ms}ms` : pg && !pg.ok ? " down" : ""}
      </span>
      <span data-testid="status-embedder">
        <Dot tone={!emb ? "warn" : emb.ok ? "ok" : "bad"} />
        ollama embed{emb && !emb.ok ? " down" : ""}
      </span>
      {jobs.map((j) => (
        <span key={j.id} data-testid="status-job">
          <Dot tone="warn" />
          {j.kind} · {j.total ? `${fmt.format(j.done)}/${fmt.format(j.total)}` : j.message || j.status}
        </span>
      ))}
      {runs.map((r) => (
        <button
          type="button"
          key={r.id}
          data-testid="status-run"
          className="transition-[color,scale] duration-150 hover:text-fg active:scale-[0.96]"
          onClick={() => {
            store.set({ factcheckRunId: r.id });
            store.set({ tab: "factcheck" });
          }}
        >
          <Dot tone={r.waiting.length ? "warn" : "ok"} />
          fact-check {r.done}/{r.total}
          {r.waiting.length ? ` · waiting on you · chunk ${r.waiting[0].item_id}` : ""}
        </button>
      ))}
      <span className="ml-auto hidden lg:inline">j/k move · x select · enter open · ⌫ delete · ? keys</span>
    </footer>
  );
}
