import { ChevronDown, Copy, ExternalLink, FileSearch, ShieldCheck, Sparkles, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuLabel, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Kbd } from "@/components/ui/kbd";
import { SectionLabel } from "@/components/ui/section-label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { post } from "@/lib/api";
import { useDetail, useNeighbors } from "@/lib/queries";
import type { ChunkDetail, SflFormatted } from "@/lib/types";
import { cn, shortId } from "@/lib/utils";
import { actions, store, useApp } from "@/state/store";
import { RowMeta } from "./RowMeta";

const ENTITY_COLORS: Record<string, string> = {
  PROPN: "var(--cat-blue)",
  NOUN: "var(--cat-green)",
  PRON: "var(--cat-pink)",
  NUM: "var(--cat-amber)",
};

/** Start SFL tagging for any scope (chunk, document, run or selection). */
export async function tagSfl(scope: Record<string, unknown>, label: string): Promise<void> {
  try {
    await post("/v1/corpus/sfl/runs", { scope });
    toast(`SFL tagging started for ${label}`);
  } catch (e) {
    toast.error((e as Error).message);
  }
}

export function ParentContext({ detail }: { detail: ChunkDetail }) {
  const p = detail.parent;
  if (!p) return <p className="text-[13px] text-muted">{detail.text}</p>;
  const start = p.child_start;
  const end = p.child_end;
  return (
    <div className="rounded-[10px] bg-surface p-3 text-[13px] leading-[1.6] break-words text-muted shadow-[inset_0_0_0_1px_var(--line)]" data-testid="parent-context">
      {start !== null && end !== null ? (
        <>
          {p.text.slice(0, start)}
          <b
            data-testid="child-highlight"
            className="rounded-[2px] bg-primary-soft px-1 py-px font-medium text-fg shadow-[inset_2px_0_0_var(--primary)]"
          >
            {p.text.slice(start, end)}
          </b>
          {p.text.slice(end)}
        </>
      ) : (
        <>
          {p.text}
          <b data-testid="child-highlight" className="mt-2 block rounded-[2px] bg-primary-soft px-1 text-fg">
            {detail.text}
          </b>
        </>
      )}
    </div>
  );
}

function ContextLines({ detail }: { detail: ChunkDetail }) {
  const lines = [
    ...detail.context.before.map((l) => ({ ...l, on: false })),
    { external_id: detail.external_id, sentence_index: detail.sentence_index ?? 0, text: detail.text, on: true },
    ...detail.context.after.map((l) => ({ ...l, on: false })),
  ];
  return (
    <div className="rounded-xl bg-surface py-1.5 text-[13px] shadow-[inset_0_0_0_1px_var(--line)]">
      {lines.map((l) => (
        <button
          type="button"
          key={l.external_id}
          disabled={l.on}
          onClick={() => actions.open(l.external_id)}
          className={cn(
            "grid w-full grid-cols-[44px_minmax(0,1fr)] gap-2.5 px-3 py-1 text-left text-muted transition-[background-color] duration-150 enabled:hover:bg-surface-2/60 enabled:active:bg-surface-2",
            l.on && "bg-primary-soft/40 text-fg shadow-[inset_2px_0_0_var(--primary)]",
          )}
        >
          <code className="font-mono text-[11px] text-subtle">{String(l.sentence_index).padStart(3, "0")}</code>
          <span className="line-clamp-2 break-words">{l.text}</span>
        </button>
      ))}
    </div>
  );
}

export function SflChips({ sfl }: { sfl: SflFormatted }) {
  const rows: [string, string[], string][] = [
    ["Participants", sfl.ideational.participants, "var(--cat-blue)"],
    ["Processes", sfl.ideational.processes, "var(--cat-green)"],
    ["Circumstances", sfl.ideational.circumstances, "var(--cat-amber)"],
    ["Tenor", sfl.interpersonal.tenor, ""],
    ["Mood", sfl.interpersonal.mood, ""],
    ["Modality", sfl.interpersonal.modality, ""],
  ];
  return (
    <dl className="grid grid-cols-[96px_1fr] gap-x-2.5 gap-y-1.5 text-[12.5px]" data-testid="sfl">
      {rows.map(([label, values, color]) => (
        <div key={label} className="contents">
          <dt className="text-[11.5px] text-subtle">{label}</dt>
          <dd className="m-0">
            {values.length === 0 && <span className="text-subtle">—</span>}
            {color
              ? values.map((v) => (
                  <span
                    key={v}
                    className="mr-1 mb-1 inline-block rounded-[4px] px-1.5 text-[12px]"
                    style={{ color, background: `color-mix(in oklab, ${color} 12%, transparent)` }}
                  >
                    {v}
                  </span>
                ))
              : <span className="text-muted">{values.join("; ")}</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Similar({ id }: { id: string }) {
  const tab = useApp((s) => s.detailTab);
  const q = useNeighbors(id, tab === "similar");
  if (q.isLoading) return <p className="text-[12.5px] text-muted">Finding nearest neighbours…</p>;
  const items = q.data?.items ?? [];
  if (!items.length) return <p className="text-[12.5px] text-muted">No embedding stored for this chunk.</p>;
  return (
    <div className="grid gap-1.5" data-testid="similar">
      <SectionLabel>More like this · L2 distance (near-duplicate under {q.data?.near_dup_threshold})</SectionLabel>
      {items.map((n) => (
        <button
          type="button"
          key={n.external_id}
          onClick={() => actions.open(n.external_id)}
          className="grid grid-cols-[48px_minmax(0,1fr)] gap-2 rounded-md p-1 text-left text-[12.5px] text-muted transition-[background-color] duration-150 hover:bg-surface active:bg-surface-2"
        >
          <code className="font-mono text-[11px] text-secondary tabular">{n.distance.toFixed(3)}</code>
          <span>
            {n.near_duplicate && (
              <Badge tone="warn" className="mr-1.5">
                near-duplicate
              </Badge>
            )}
            <span className="line-clamp-2 break-words">{n.text}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

function Provenance({ detail }: { detail: ChunkDetail }) {
  const p = detail.parent;
  return (
    <div className="grid gap-1 font-mono text-[11.5px] text-muted">
      <span className="break-all">external_id {detail.external_id}</span>
      {detail.run && (
        <span>
          run #{detail.run.id} · {detail.run.strategy} · {detail.run.is_active ? "active" : "inactive"}
        </span>
      )}
      {p && (
        <span>
          parent {p.index + 1}/{detail.n_parents ?? "?"} · chars {p.char_start}–{p.char_end}
          {detail.sentence_index !== null && ` · line ${detail.sentence_index}`}
        </span>
      )}
      {detail.topic && <span>topic {detail.topic}</span>}
    </div>
  );
}

function FactCheckSummary({ detail }: { detail: ChunkDetail }) {
  const fc = detail.latest_fact_check;
  if (!fc) return null;
  const tone = fc.verdict === "supported" ? "ok" : fc.verdict === "contradicted" ? "bad" : "neutral";
  return (
    <div>
      <SectionLabel>Latest fact-check</SectionLabel>
      <div className="flex items-center gap-2 text-[12.5px]">
        <Badge tone={tone}>{fc.verdict}</Badge>
        {fc.confidence !== null && <span className="font-mono text-muted">p {fc.confidence.toFixed(2)}</span>}
        {fc.model && <span className="truncate text-muted">{fc.model}</span>}
      </div>
    </div>
  );
}

export function DetailPane() {
  const id = useApp((s) => s.detailId);
  const tab = useApp((s) => s.detailTab);
  const q = useDetail(id);
  const d = q.data;

  if (!id) {
    return (
      <div className="grid h-full place-items-center p-6 text-center text-[12.5px] text-muted">
        <div>
          <FileSearch className="mx-auto mb-2 size-5" />
          Select a chunk to see its parent passage, linguistics and similar items.
          <div className="mt-2">
            <Kbd>j</Kbd> <Kbd>k</Kbd> move · <Kbd>↵</Kbd> open
          </div>
        </div>
      </div>
    );
  }
  if (q.isError) return <p className="p-4 text-[12.5px] text-bad">This chunk no longer exists.</p>;
  if (!d) return <p className="p-4 text-[12.5px] text-muted">Loading…</p>;

  const remove = (level: "clause" | "parent" | "document" | "run") => {
    const ids =
      level === "clause" ? [d.external_id] : level === "parent" ? [String(d.parent?.id)] : level === "document" ? [d.document_id] : [String(d.run_id)];
    const label =
      level === "clause"
        ? "this chunk"
        : level === "parent"
          ? `parent chunk ${(d.parent?.index ?? 0) + 1} and its ${d.parent?.n_children ?? 0} children`
          : level === "document"
            ? `document ${shortId(d.title ?? d.document_id, 24)} (every run)`
            : `run #${d.run_id}`;
    actions.requestDelete({ level, ids, hide: [d.external_id], label });
  };

  return (
    <div className="flex h-full min-h-0 flex-col" aria-label="Chunk detail">
      <Tabs
        value={tab}
        onValueChange={(v) => store.set({ detailTab: v as typeof tab })}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="border-b border-line px-2.5 py-2">
          <TabsTrigger value="context">Context</TabsTrigger>
          <TabsTrigger value="linguistics">Linguistics</TabsTrigger>
          <TabsTrigger value="similar">Similar</TabsTrigger>
          <TabsTrigger value="raw">Raw</TabsTrigger>
        </TabsList>
        <div className="min-h-0 flex-1 overflow-auto p-3.5">
          <TabsContent value="context" className="grid gap-3.5">
            <div>
              <SectionLabel>
                Parent chunk · #{d.id} highlighted
              </SectionLabel>
              <ParentContext detail={d} />
            </div>
            <div>
              <SectionLabel>Neighbouring lines</SectionLabel>
              <ContextLines detail={d} />
            </div>
            <RowMeta row={d} />
            <FactCheckSummary detail={d} />
            <div>
              <SectionLabel>Provenance</SectionLabel>
              <Provenance detail={d} />
            </div>
          </TabsContent>
          <TabsContent value="linguistics" className="grid gap-3.5">
            <div>
              <SectionLabel>Entities</SectionLabel>
              <div className="flex flex-wrap gap-1.5" data-testid="entities">
                {d.entities.length === 0 && <span className="text-[12.5px] text-subtle">None found</span>}
                {d.entities.map((e) => (
                  <span key={e.text} className="rounded-md bg-surface-2 px-2 py-0.5 text-[12px]" style={{ color: ENTITY_COLORS[e.label] ?? "var(--fg)" }}>
                    {e.text}
                    <small className="ml-1 font-mono text-[10.5px] text-muted">{e.label}</small>
                  </span>
                ))}
              </div>
            </div>
            <div>
              <SectionLabel>SFL metafunctions</SectionLabel>
              {d.sfl ? (
                <SflChips sfl={d.sfl} />
              ) : (
                <div className="flex items-center gap-2 text-[12.5px] text-muted">
                  Not tagged yet.
                  <Button onClick={() => void tagSfl({ external_ids: [d.external_id] }, "this chunk")}>
                    <Sparkles /> Tag SFL
                  </Button>
                </div>
              )}
            </div>
          </TabsContent>
          <TabsContent value="similar">
            <Similar id={d.external_id} />
          </TabsContent>
          <TabsContent value="raw">
            <pre className="overflow-auto rounded-lg bg-surface p-3 font-mono text-[11px] leading-[1.5] text-muted shadow-[inset_0_0_0_1px_var(--line)]">
              {JSON.stringify(d, null, 2)}
            </pre>
          </TabsContent>
        </div>
      </Tabs>
      <div className="flex flex-wrap items-center gap-1.5 border-t border-line px-3.5 py-2.5">
        <Button
          onClick={() => {
            void navigator.clipboard?.writeText(d.text);
            toast("Copied chunk text");
          }}
        >
          <Copy /> Copy
        </Button>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button aria-label="Assess">
              <ShieldCheck /> Assess <ChevronDown />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuLabel>Fact-check…</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => actions.startFactCheck({ external_ids: [d.external_id] })}>This chunk</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => actions.startFactCheck({ document_ids: [d.document_id] })}>Whole document</DropdownMenuItem>
            {d.run_id !== null && (
              <DropdownMenuItem onSelect={() => actions.startFactCheck({ run_ids: [d.run_id as number] })}>Whole run #{d.run_id}</DropdownMenuItem>
            )}
            <DropdownMenuLabel>Tag SFL…</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => void tagSfl({ external_ids: [d.external_id] }, "this chunk")}>This chunk</DropdownMenuItem>
            <DropdownMenuItem onSelect={() => void tagSfl({ document_ids: [d.document_id] }, "this document")}>Whole document</DropdownMenuItem>
            {d.run_id !== null && (
              <DropdownMenuItem onSelect={() => void tagSfl({ run_ids: [d.run_id as number] }, `run #${d.run_id}`)}>Whole run #{d.run_id}</DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
        {d.notebook_id && (
          <Button asChild variant="ghost" size="icon" aria-label="Open notebook in NotebookLM" title="Open notebook in NotebookLM">
            <a href={`https://notebooklm.google.com/notebook/${d.notebook_id}`} target="_blank" rel="noreferrer">
              <ExternalLink />
            </a>
          </Button>
        )}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="destructive" className="ml-auto" aria-label="Delete">
              <Trash2 /> Delete <ChevronDown />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuLabel>Delete…</DropdownMenuLabel>
            <DropdownMenuItem onSelect={() => remove("clause")}>This chunk</DropdownMenuItem>
            {d.parent && <DropdownMenuItem onSelect={() => remove("parent")}>Parent chunk + {d.parent.n_children} children</DropdownMenuItem>}
            <DropdownMenuItem onSelect={() => remove("document")}>Whole document</DropdownMenuItem>
            {d.run_id !== null && <DropdownMenuItem onSelect={() => remove("run")}>Whole run #{d.run_id}</DropdownMenuItem>}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}
