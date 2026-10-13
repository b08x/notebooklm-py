import {
  ChevronDown,
  Copy,
  ExternalLink,
  ShieldCheck,
  Tag,
  Trash2,
  X,
} from "lucide-react";
import React, { useRef, useState } from "react";
import { toast } from "sonner";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { SectionLabel } from "@/components/ui/section-label";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Drawer } from "@/features/Drawer";
import {
  ParentContext,
  SflChips,
} from "@/features/DetailPane";
import { RowMeta } from "@/features/RowMeta";
import { TagSflButton } from "@/features/TagSflButton";
import { useViewportTier } from "@/hooks/useViewportTier";
import { useDetail, useNeighbors } from "@/lib/queries";
import type { ChunkDetail } from "@/lib/types";
import { clauseNumber, cn, shortId } from "@/lib/utils";
import { actions, store, useApp } from "@/state/store";

export const INSPECTOR_WIDTH_KEY = "corpus-explorer:inspector-width";
export const DEFAULT_INSPECTOR_WIDTH = 360;
export const MIN_INSPECTOR_WIDTH = 320;
export const MAX_INSPECTOR_WIDTH = 480;

const ENTITY_COLORS: Record<string, string> = {
  PROPN: "var(--cat-blue)",
  NOUN: "var(--cat-green)",
  PRON: "var(--cat-pink)",
  NUM: "var(--cat-amber)",
};

export function getInitialInspectorWidth(): number {
  if (typeof window === "undefined") return DEFAULT_INSPECTOR_WIDTH;
  const stored = localStorage.getItem(INSPECTOR_WIDTH_KEY);
  if (stored) {
    const parsed = parseInt(stored, 10);
    if (!isNaN(parsed) && parsed >= MIN_INSPECTOR_WIDTH && parsed <= MAX_INSPECTOR_WIDTH) {
      return parsed;
    }
  }
  return DEFAULT_INSPECTOR_WIDTH;
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

interface InspectorContentProps {
  onClose?: () => void;
}

export function InspectorContent({ onClose }: InspectorContentProps) {
  const id = useApp((s) => s.detailId);
  const tab = useApp((s) => s.detailTab);
  const q = useDetail(id);
  const d = q.data;

  if (!id) {
    return (
      <div
        data-testid="inspector-empty"
        className="grid h-full place-items-center p-6 text-center text-[13px] text-muted"
      >
        <p>Select a clause in the document.</p>
      </div>
    );
  }

  if (q.isError) {
    return <p className="p-4 text-[12.5px] text-bad">This clause no longer exists.</p>;
  }

  if (!d) {
    return <p className="p-4 text-[12.5px] text-muted">Loading clause details…</p>;
  }

  const remove = (level: "clause" | "parent" | "document" | "run") => {
    const ids =
      level === "clause"
        ? [d.external_id]
        : level === "parent"
          ? [String(d.parent?.id)]
          : level === "document"
            ? [d.document_id]
            : [String(d.run_id)];
    const label =
      level === "clause"
        ? "this clause"
        : level === "parent"
          ? `parent chunk ${(d.parent?.index ?? 0) + 1} and its ${d.parent?.n_children ?? 0} children`
          : level === "document"
            ? `document ${d.title ?? `${shortId(d.document_id, 8)} untitled`} (every run)`
            : `run #${d.run_id}`;
    actions.requestDelete({ level, ids, hide: [d.external_id], label });
  };

  const chunkNum = d.parent ? d.parent.index + 1 : 1;
  const clauseNum = clauseNumber(d.external_id);
  const fc = d.latest_fact_check;
  const tone = fc?.verdict === "supported" ? "ok" : fc?.verdict === "contradicted" ? "bad" : fc?.verdict === "unverified" ? "warn" : "neutral";

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface select-none" data-testid="inspector-panel">
      {/* Header: Document title + chunk/clause number */}
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-line px-3 bg-surface">
        <div className="min-w-0 flex-1">
          <h3
            data-testid="inspector-doc-title"
            className="text-[13px] font-semibold text-fg truncate leading-tight"
            title={d.title || "Document"}
          >
            {d.title || "Document"}
          </h3>
          <p className="text-[11px] font-mono text-muted leading-tight mt-0.5">
            Chunk {chunkNum} · Clause {clauseNum}
          </p>
        </div>

        {onClose && (
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            aria-label="Close inspector"
            className="size-7 rounded-md text-muted hover:text-fg ml-2 shrink-0 active:scale-[0.96]"
          >
            <X className="size-4" />
          </Button>
        )}
      </div>

      {/* Tabs: Context, Linguistics, Similar, Raw */}
      <Tabs
        value={tab}
        onValueChange={(v) => store.set({ detailTab: v as typeof tab })}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList className="border-b border-line px-2.5 py-1.5 shrink-0 bg-surface">
          <TabsTrigger value="context">Context</TabsTrigger>
          <TabsTrigger value="linguistics">Linguistics</TabsTrigger>
          <TabsTrigger value="similar">Similar</TabsTrigger>
          <TabsTrigger value="raw">Raw</TabsTrigger>
        </TabsList>

        <div className="min-h-0 flex-1 overflow-auto p-3.5">
          <TabsContent value="context" className="grid gap-3.5">
            <div>
              <SectionLabel>Parent passage · #{d.id} highlighted</SectionLabel>
              <ParentContext detail={d} />
            </div>
            <div>
              <SectionLabel>Neighbouring lines</SectionLabel>
              <ContextLines detail={d} />
            </div>
            <RowMeta row={d} />
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
                  <span
                    key={e.text}
                    className="rounded-md bg-surface-2 px-2 py-0.5 text-[12px]"
                    style={{ color: ENTITY_COLORS[e.label] ?? "var(--fg)" }}
                  >
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
                  <TagSflButton scope={{ external_ids: [d.external_id] }} label="this clause" size="sm" />
                </div>
              )}
            </div>
          </TabsContent>

          <TabsContent value="similar">
            <Similar id={d.external_id} />
          </TabsContent>

          <TabsContent value="raw">
            <pre className="overflow-auto rounded-lg bg-surface-2 p-3 font-mono text-[11px] leading-[1.5] text-muted shadow-[inset_0_0_0_1px_var(--line)]">
              {JSON.stringify(d, null, 2)}
            </pre>
          </TabsContent>
        </div>
      </Tabs>

      {/* Pinned Footer (≈120px): SFL tag state & fact-check verdict with action buttons */}
      <footer
        data-testid="inspector-footer"
        className="h-[120px] shrink-0 border-t border-line bg-surface-2/60 p-3 flex flex-col justify-between"
      >
        <div className="grid grid-cols-2 gap-2 text-[11.5px]">
          {/* SFL Tag Status */}
          <div className="rounded-lg bg-surface p-2 border border-line">
            <div className="text-[10px] uppercase font-semibold text-subtle tracking-wider flex items-center gap-1">
              <Tag className="size-3" /> SFL Status
            </div>
            <div className="mt-1 flex items-center justify-between">
              <span className="font-medium text-fg">
                {d.has_sfl || d.sfl ? "Tagged" : "Untagged"}
              </span>
              <TagSflButton scope={{ external_ids: [d.external_id] }} label="this clause" size="sm" />
            </div>
          </div>

          {/* Fact-check Status */}
          <div className="rounded-lg bg-surface p-2 border border-line">
            <div className="text-[10px] uppercase font-semibold text-subtle tracking-wider flex items-center gap-1">
              <ShieldCheck className="size-3" /> Fact-Check
            </div>
            <div className="mt-1 flex items-center justify-between">
              <Badge tone={tone} className="text-[10.5px] py-0 px-1.5 capitalize">
                {fc?.verdict || d.fact_check || "unchecked"}
              </Badge>
              <Button
                size="sm"
                variant="ghost"
                data-testid="inspector-factcheck-btn"
                onClick={() => actions.startFactCheck({ external_ids: [d.external_id] })}
                className="h-6 px-2 text-[11px] text-muted hover:text-fg active:scale-[0.96]"
              >
                Fact-check
              </Button>
            </div>
          </div>
        </div>

        {/* Action Row */}
        <div className="flex items-center gap-1.5 pt-1">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              void navigator.clipboard?.writeText(d.text);
              toast("Copied clause text");
            }}
            className="h-6 px-2 text-[11px] text-muted hover:text-fg gap-1 active:scale-[0.96]"
          >
            <Copy className="size-3" /> Copy
          </Button>

          {d.notebook_id && (
            <Button
              asChild
              variant="ghost"
              size="icon"
              aria-label="Open in NotebookLM"
              className="size-6 text-muted hover:text-fg"
            >
              <a href={`https://notebooklm.google.com/notebook/${d.notebook_id}`} target="_blank" rel="noreferrer">
                <ExternalLink className="size-3" />
              </a>
            </Button>
          )}

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto h-6 px-2 text-[11px] text-bad hover:text-bad hover:bg-bad/10 gap-1 active:scale-[0.96]"
                aria-label="Delete options"
              >
                <Trash2 className="size-3" /> Delete <ChevronDown className="size-2.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>Delete…</DropdownMenuLabel>
              <DropdownMenuItem onSelect={() => remove("clause")}>This clause</DropdownMenuItem>
              {d.parent && (
                <DropdownMenuItem onSelect={() => remove("parent")}>
                  Parent chunk + {d.parent.n_children} children
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => remove("document")}>Whole document</DropdownMenuItem>
              {d.run_id !== null && <DropdownMenuItem onSelect={() => remove("run")}>Whole run #{d.run_id}</DropdownMenuItem>}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </footer>
    </div>
  );
}

export function Inspector() {
  const tier = useViewportTier();
  const drawerOpen = useApp((s) => s.inspectorDrawerOpen);
  const [width, setWidth] = useState(getInitialInspectorWidth);
  const isDragging = useRef(false);

  // Handle drag resizing on left edge
  const handleMouseDown = (e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    const startX = e.clientX;
    const startWidth = width;

    const handleMouseMove = (moveEvent: MouseEvent) => {
      if (!isDragging.current) return;
      const delta = startX - moveEvent.clientX; // Drag left -> wider, Drag right -> narrower
      const nextWidth = Math.min(
        MAX_INSPECTOR_WIDTH,
        Math.max(MIN_INSPECTOR_WIDTH, startWidth + delta),
      );
      setWidth(nextWidth);
    };

    const handleMouseUp = () => {
      if (isDragging.current) {
        isDragging.current = false;
        setWidth((finalWidth) => {
          localStorage.setItem(INSPECTOR_WIDTH_KEY, String(finalWidth));
          return finalWidth;
        });
      }
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
  };

  // Viewport tier < 1400px: Inspector becomes right drawer
  if (tier !== "wide") {
    return (
      <Drawer
        open={drawerOpen}
        onOpenChange={(open) => store.set({ inspectorDrawerOpen: open })}
        side="right"
        width={360}
        title="Inspector"
      >
        <InspectorContent onClose={() => store.set({ inspectorDrawerOpen: false })} />
      </Drawer>
    );
  }

  return (
    <aside
      aria-label="Inspector"
      data-testid="inspector"
      style={{ width }}
      className="relative h-full shrink-0 border-l border-line bg-surface flex flex-col min-h-0 overflow-hidden"
    >
      {/* Resizing drag handle on left edge */}
      <div
        data-testid="inspector-resize-handle"
        onMouseDown={handleMouseDown}
        className="absolute left-0 top-0 bottom-0 w-1.5 cursor-col-resize hover:bg-primary/40 active:bg-primary z-20 transition-colors duration-150"
        title="Drag to resize inspector (320-480px)"
      />

      <InspectorContent />
    </aside>
  );
}
